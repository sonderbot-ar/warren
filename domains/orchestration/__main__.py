"""Command line for the one-command pipeline (M7). `python main.py ...` is the same command.

    python main.py run --ticker MSFT --as-of 2022-06-02 [--variant named|masked|both]
                       [--review auto|manual|later] [--seed N] [--n 10000] [--refresh]
                       [--offline] [--max-tokens-total N]
    python main.py resume --pipeline-id ID [--max-tokens-total N]
    python main.py show --pipeline-id ID
    python main.py reproduce --pipeline-id ID
    python main.py report --pipeline-id ID

`run` goes from filings to report for one company and date: fundamentals (SEC EDGAR, needs
SEC_USER_AGENT), prices and the risk-free rate (Yahoo Finance, FRED), a week of GDELT news, the
two LLM steps (key in WARREN_ANTHROPIC_API_KEY, or ANTHROPIC_API_KEY locally), the review, the
Monte Carlo and the report in data/reports/pipeline/. Every step's state is checkpointed in the
database and every step writes telemetry lines to data/telemetry/<pipeline id>.jsonl.
Review: `auto` (the default for any date more than 7 days old), `manual` (asks here), `later`
(stops; `resume` asks then). Exit codes: 0 done, 1 a step failed (`resume` retries it), 2 bad
arguments or setup, 3 the LLM budget was spent (`resume --max-tokens-total` continues), 4 waiting
for review.
"""

import argparse
import sys
from datetime import date

from domains.analysis.montecarlo import reproduce_simulation
from domains.analysis.runs import reproduce
from domains.fundamentals.edgar_client import EdgarClient
from domains.llm import calls
from domains.llm.client import AnthropicClient
from domains.orchestration import graph, nodes, report
from shared_kernel.config import DATA_DIR, REPORTS_DIR, ConfigError, anthropic_api_key
from shared_kernel.database import apply_migrations, get_db_connection

FOLDERS = graph.Folders(reports=REPORTS_DIR / "pipeline", telemetry=DATA_DIR / "telemetry")


def make_deps(conn) -> nodes.Deps:
    """The real sources; each client is built on first use."""
    return nodes.Deps(conn=conn, llm=lambda: AnthropicClient(anthropic_api_key()),
                      edgar=EdgarClient)  # fmt: skip


def _ask(waiting: dict) -> dict:
    """Ask a person approve, edit or reject for every open proposal (the M6 questions)."""
    if waiting.get("problem"):
        print(f"\nThose answers were not used: {waiting['problem']}")
    answers = {}
    for variant, proposals in waiting["proposals"].items():
        for p in proposals:
            print(f"\n[{variant}] {p['driver']}: low {p['low']:.2f}  base {p['base']:.2f}  "
                  f"high {p['high']:.2f}  from Q{p['start_period']}, {p['horizon']} quarters, "
                  f"decay {p['decay']}\n{p['rationale']}")  # fmt: skip
            while True:
                choice = input("[a]pprove, [e]dit or [r]eject? ").strip().lower()
                if choice in ("a", "e", "r"):
                    break
            if choice == "a":
                answers[p["proposal_id"]] = {"action": "approve"}
            elif choice == "r":
                answers[p["proposal_id"]] = {"action": "reject", "reason": input("Why? ")}
            else:
                changes = {}
                for field in ("low", "base", "high", "start_period", "horizon", "decay"):
                    value = input(f"{field} [{p[field]}]: ").strip()
                    if value:
                        whole = field in ("start_period", "horizon")
                        changes[field] = int(value) if whole else float(value)
                answers[p["proposal_id"]] = {"action": "edit", "changes": changes}
    return answers


def _finish(out: graph.Outcome, deps: nodes.Deps, review: str) -> int:
    while out.status == "waiting_review" and review == "manual":
        out = graph.resume(deps, FOLDERS, out.pipeline_id, answers=_ask(out.waiting))
    if out.status == "waiting_review":
        n = sum(len(p) for p in out.waiting["proposals"].values())
        print(f"{out.pipeline_id}: waiting for review of {n} proposals. Continue with: "
              f"python main.py resume --pipeline-id {out.pipeline_id}")  # fmt: skip
        return 4
    if out.status == "failed":
        print(f"{out.pipeline_id}: FAILED: {out.error}")
        if isinstance(out.error, calls.BudgetSpent):
            print(f"Continue with: python main.py resume --pipeline-id {out.pipeline_id} "
                  "--max-tokens-total N")  # fmt: skip
            return 3
        if isinstance(out.error, ConfigError):
            return 2
        print(f"Fix the cause, then: python main.py resume --pipeline-id {out.pipeline_id}")
        return 1
    s = out.state
    shocked = "  ".join(
        f"{v} p10 {x.p10:,.2f} p50 {x.p50:,.2f} p90 {x.p90:,.2f}" if x else f"{v} no shock"
        for v, x in s.sim.items()
    )
    print(f"{s.pipeline_id}  value per share baseline {s.baseline_value_per_share:,.2f}  "
          f"{shocked}\nreport {s.report_path}")  # fmt: skip
    return 0


def cmd_run(args) -> int:
    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError:
        print(f"--as-of must be YYYY-MM-DD, got {args.as_of!r}", file=sys.stderr)
        return 2
    if not args.offline:
        try:
            anthropic_api_key()  # before anything runs, so a missing key costs nothing
        except ConfigError as e:
            print(e, file=sys.stderr)
            return 2
    variants = None if args.variant is None else (
        ["named", "masked"] if args.variant == "both" else [args.variant])  # fmt: skip
    with get_db_connection() as conn:
        apply_migrations(conn)
        deps = make_deps(conn)
        try:
            out = graph.start(deps, FOLDERS, args.ticker, as_of, variants=variants,
                              review=args.review, seed=args.seed, n_samples=args.n,
                              budget=args.max_tokens_total, offline=args.offline,
                              refresh=args.refresh)  # fmt: skip
        except Exception as e:  # tracing on: refused before anything runs
            print(e, file=sys.stderr)
            return 2
        return _finish(out, deps, out.state.review if out.state else "auto")


def cmd_resume(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        deps = make_deps(conn)
        out = graph.resume(deps, FOLDERS, args.pipeline_id, budget=args.max_tokens_total)
        review = out.state.review if out.state else "auto"
        return _finish(out, deps, "manual" if review in ("manual", "later") else review)


def cmd_show(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        steps = graph.history(conn, FOLDERS, args.pipeline_id)
    if not steps:
        print(f"No checkpoints for {args.pipeline_id}")
        return 2
    for step, node, changed in steps:
        print(f"{step:3}  {node:18} {', '.join(changed) or '(no change)'}")
    return 0


def cmd_reproduce(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        state = graph.final_state(conn, FOLDERS, args.pipeline_id)
        if state is None:
            print(f"{args.pipeline_id} is not done")
            return 2
        bad = 0
        run = reproduce(conn, state.run_id)
        print(f"{'OK' if run.ok else 'MISMATCH'} baseline {state.run_id} "
              f"{run.outputs_checked} outputs")  # fmt: skip
        bad += not run.ok
        for variant, sim in state.sim.items():
            if sim is None:
                continue
            sized_on = conn.execute("SELECT run_id FROM proposal_sets WHERE set_id = ?",
                                    (state.proposal_set[variant],)).fetchone()[0]  # fmt: skip
            r = reproduce_simulation(conn, sim.sim_id)
            ok = r.ok and sized_on == state.run_id
            elsewhere = "" if sized_on == state.run_id else f", sized on {sized_on}"
            print(f"{'OK' if ok else 'MISMATCH'} {variant} {sim.sim_id} {r.outputs_checked} "
                  f"outputs{elsewhere}")  # fmt: skip
            bad += not ok
        path = FOLDERS.reports / f"{state.pipeline_id}.md"
        same = path.exists() and report.body(path) == report.render(conn, state)
        print(f"{'OK' if same else 'MISMATCH'} report {path} (up to the trace)")
        bad += not same
    return 1 if bad else 0


def cmd_report(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        state = graph.final_state(conn, FOLDERS, args.pipeline_id)
        if state is None:
            print(f"{args.pipeline_id} is not done")
            return 2
        path = report.write_report(conn, state, FOLDERS.reports,
                                   FOLDERS.telemetry / f"{state.pipeline_id}.jsonl")  # fmt: skip
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="filings to report for one company and date")
    run.add_argument("--ticker", required=True)
    run.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    run.add_argument("--variant", choices=("named", "masked", "both"),
                     help="default: both for an eval case, else named")  # fmt: skip
    run.add_argument("--review", choices=("auto", "manual", "later"),
                     help="default: auto for a date over 7 days old, else manual")  # fmt: skip
    run.add_argument("--seed", type=int, help="default: a fresh seed, stored with the pipeline")
    run.add_argument("--n", type=int, default=graph.DEFAULT_SAMPLES, help="samples")
    run.add_argument("--refresh", action="store_true", help="download every source again")
    run.add_argument("--offline", action="store_true", help="download nothing")
    run.add_argument("--max-tokens-total", type=int, default=calls.DEFAULT_BUDGET)
    run.set_defaults(func=cmd_run)
    res = sub.add_parser("resume", help="continue a failed or paused pipeline")
    res.add_argument("--pipeline-id", required=True)
    res.add_argument("--max-tokens-total", type=int, help="a larger LLM budget")
    res.set_defaults(func=cmd_resume)
    by_id = (("show", cmd_show, "every checkpoint, oldest first"),
             ("reproduce", cmd_reproduce, "check a pipeline to the cent"),
             ("report", cmd_report, "write a pipeline's report again"))  # fmt: skip
    for name, func, what in by_id:
        p = sub.add_parser(name, help=what)
        p.add_argument("--pipeline-id", required=True)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
