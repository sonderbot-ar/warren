"""Command line for the LLM steps (M6).

    python -m domains.llm classify --case MSFT_2022-06-02 | --all-cases [--variant both]
    python -m domains.llm propose --case MSFT_2022-06-02 | --all-cases [--variant both]
    python -m domains.llm review --case MSFT_2022-06-02 [--auto]
    python -m domains.llm check-headlines
    python -m domains.llm stability
    python -m domains.llm report

`classify`, `propose` and `check-headlines` call the model (key in WARREN_ANTHROPIC_API_KEY, or
ANTHROPIC_API_KEY locally) and stop cleanly when the batch has used `--max-tokens-total`. With
`--dry-run` they call nothing: they render every prompt on a throwaway copy of the database and
print calls and estimated tokens per node.
`review --auto` records every proposal as auto-approved (eval cases: a person today knows what
happened next). The report goes to data/reports/llm/.
"""

import argparse
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from domains.analysis.runs import run_baseline
from domains.evaluation.cases import CASES_PATH, Case, load_cases
from domains.llm import calls, extract, headlines, propose, report, review
from domains.llm.client import AnthropicClient, LLMError, Reply
from domains.news.matching import load_aliases, load_headline_rule
from domains.news.report import read_sample
from shared_kernel.config import DB_PATH, REPORTS_DIR, ConfigError, anthropic_api_key
from shared_kernel.database import apply_migrations, get_db_connection


class DryRunClient:
    """Records each request and answers none, so nothing is paid and nothing valid is stored."""

    def __init__(self):
        self.requests: list[tuple[str, int]] = []

    def call(self, model: str, system: str, user: str, schema: dict) -> Reply:
        self.requests.append((model, (len(system) + len(user)) // 4))
        raise LLMError("dry run")


def _cases(args) -> list[Case]:
    cases = load_cases(CASES_PATH)
    if not args.all_cases:
        cases = [c for c in cases if c.case_id in (args.case or [])]
    return cases


def _variants(args) -> tuple[str, ...]:
    return extract.VARIANTS if args.variant == "both" else (args.variant,)


def _batch(command: str) -> str:
    return f"{command}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"


def _baseline_run(conn: sqlite3.Connection, case: Case) -> str:
    """The latest baseline run as of the case date, or a new one."""
    row = conn.execute(
        "SELECT run_id FROM runs WHERE ticker = ? AND as_of = ? AND seed IS NULL "
        "ORDER BY created_at DESC, run_id DESC LIMIT 1",
        (case.ticker, case.event_date.isoformat()),
    ).fetchone()
    return row["run_id"] if row else run_baseline(conn, case.ticker, case.event_date)


def _with_client(args, work) -> int:
    """Run `work(conn, client)` for real, or on a copy of the database with a dry-run client."""
    if not args.dry_run:
        try:
            client = AnthropicClient(anthropic_api_key())
        except ConfigError as e:
            print(e, file=sys.stderr)
            return 2
        with get_db_connection() as conn:
            apply_migrations(conn)
            try:
                work(conn, client)
            except calls.BudgetSpent as e:
                print(f"Stopped: {e}. Run the same command again to continue.")
                return 3
        return 0
    client = DryRunClient()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "dry.db"
        if DB_PATH.exists():  # the backup API also copies what is still in the WAL file
            with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(copy)) as dst:
                src.backup(dst)
        with get_db_connection(copy) as conn:
            apply_migrations(conn)
            work(conn, client)
    first = client.requests[:: calls.ATTEMPTS]  # each question is asked ATTEMPTS times
    by_model = Counter(m for m, _ in first)
    tokens = Counter()
    for m, t in first:
        tokens[m] += t
    for model, n in sorted(by_model.items()):
        print(f"dry run: {model}: {n} calls, about {tokens[model]:,} input tokens")
    if not first:
        print("dry run: no calls")
    return 0


def cmd_classify(args) -> int:
    cases = _cases(args)
    if not cases:
        print("No cases selected")
        return 2

    def work(conn, client):
        aliases = load_aliases(conn)
        rule = load_headline_rule(conn, aliases)
        batch = _batch("classify")
        for c in cases:
            out = extract.classify_case(conn, client, c.case_id, c.ticker, c.event_date, aliases,
                                        rule, _variants(args), batch,
                                        args.max_tokens_total)  # fmt: skip
            print(f"{c.case_id}  " + "  ".join(f"{v} {len(ids)}" for v, ids in out.items()),
                  flush=True)  # fmt: skip

    return _with_client(args, work)


def cmd_propose(args) -> int:
    cases = _cases(args)
    if not cases:
        print("No cases selected")
        return 2

    def work(conn, client):
        aliases = load_aliases(conn)
        batch = _batch("propose")
        for c in cases:
            co = extract.company(conn, c.ticker)
            run_id = _baseline_run(conn, c)
            for variant in _variants(args):
                set_id = propose.propose_case(conn, client, c.case_id, co, c.event_date, run_id,
                                              aliases, variant, batch,
                                              args.max_tokens_total)  # fmt: skip
                print(f"{c.case_id} {variant}  set {set_id if set_id else 'none (no events)'}",
                      flush=True)  # fmt: skip

    return _with_client(args, work)


def _ask(row, shock):
    print(f"\n{shock.driver} ({shock.basis}): low {shock.low:.2f}  base {shock.base:.2f}  "
          f"high {shock.high:.2f}  from Q{shock.start_period}, {shock.horizon} quarters, "
          f"decay {shock.decay}\n{shock.rationale}")  # fmt: skip
    while True:
        choice = input("[a]pprove, [e]dit or [r]eject? ").strip().lower()
        if choice == "a":
            return "approve", None
        if choice == "r":
            return "reject", input("Why? ")
        if choice == "e":
            changes = {}
            for field in review.EDITABLE:
                value = input(f"{field} [{getattr(shock, field)}]: ").strip()
                if value:
                    changes[field] = float(value) if field in ("low", "base", "high",
                                                               "decay") else int(value)  # fmt: skip
            return "edit", changes


def cmd_review(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        p_model, p_sha, _, x_sha = propose.current_keys()
        sets = conn.execute(  # the current prompts' sets only; older ones stay as they were
            "SELECT set_id, variant FROM proposal_sets WHERE case_id = ? AND status = 'ok' "
            "AND model = ? AND prompt_sha256 = ? AND extract_prompt_sha256 = ? ORDER BY set_id",
            (args.case, p_model, p_sha, x_sha),
        ).fetchall()
        if not sets:
            print(f"No proposals for {args.case}")
            return 2
        for s in sets:
            counts = review.review_set(conn, s["set_id"], auto=args.auto,
                                       ask=None if args.auto else _ask,
                                       reviewer=args.reviewer)  # fmt: skip
            print(f"{args.case} {s['variant']}  {counts or 'nothing left to review'}")
    return 0


def cmd_check_headlines(args) -> int:
    rows = read_sample()
    if not rows:
        print("No labelled headlines")
        return 2

    def work(conn, client):
        added, failed = headlines.check_headlines(conn, client, rows, _batch("check_headlines"),
                                                  args.max_tokens_total)  # fmt: skip
        print(f"headlines checked: {added}")
        if failed:
            print(f"batches with no valid answer: {failed} (run again to retry them)")

    return _with_client(args, work)


def cmd_stability(args) -> int:
    def work(conn, client):
        aliases = load_aliases(conn)
        rule = load_headline_rule(conn, aliases)
        rows = extract.stability(conn, client, load_cases(CASES_PATH), aliases, rule,
                                 _batch("stability"), args.max_tokens_total)  # fmt: skip
        for r in rows:
            print(f"{r.case_id}  {r.event_id}  {' / '.join(r.types)}  "
                  f"{'same' if r.same else 'DIFFERENT'}")  # fmt: skip
        same = sum(r.same for r in rows)
        verdict = "pass" if same >= extract.STABILITY_PASS else "FAIL"
        print(f"stability: same type in all {extract.STABILITY_RUNS} runs for {same} of "
              f"{len(rows)} events ({verdict}; the bar is {extract.STABILITY_PASS} of "
              f"{extract.STABILITY_CASES})")  # fmt: skip

    return _with_client(args, work)


def cmd_report(args) -> int:
    path = REPORTS_DIR / "llm" / "llm_report.md"
    with get_db_connection() as conn:
        apply_migrations(conn)
        report.write_report(conn, path)
    print(f"Report: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.llm")
    sub = parser.add_subparsers(dest="command", required=True)

    def calling(p):
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--max-tokens-total", type=int, default=calls.DEFAULT_BUDGET)

    def with_cases(p):
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--case", action="append")
        group.add_argument("--all-cases", action="store_true")
        p.add_argument("--variant", choices=("named", "masked", "both"), default="both")
        calling(p)

    with_cases(sub.add_parser("classify"))
    with_cases(sub.add_parser("propose"))
    p = sub.add_parser("review")
    p.add_argument("--case", required=True)
    p.add_argument("--auto", action="store_true")
    p.add_argument("--reviewer", default="owner")
    calling(sub.add_parser("check-headlines"))
    calling(sub.add_parser("stability"))
    sub.add_parser("report")
    args = parser.parse_args(argv)
    commands = {"classify": cmd_classify, "propose": cmd_propose, "review": cmd_review,
                "check-headlines": cmd_check_headlines, "stability": cmd_stability,
                "report": cmd_report}  # fmt: skip
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
