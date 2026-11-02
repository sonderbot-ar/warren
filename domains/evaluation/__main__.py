"""Command line for the evaluation harness.

    python -m domains.evaluation run [--case AAPL_2020-02-17 ...] [--cases-file PATH]
        [--guidance PATH]
    python -m domains.evaluation report --batch eval_2026-10-30_1
    python -m domains.evaluation backtest [--guidance PATH] [--case ID ...]
    python -m domains.evaluation reproduce --batch BATCH [--guidance PATH]

`run` scores every case in the case file (or the ones named) and writes
data/reports/eval/<batch_id>.md. Cases that can't be scored are listed with their reason; it exits
1 only when no case could be scored. With `--guidance`, the cases it covers are also simulated
under the shocks their company guidance implies and scored as `with_shocks` (M4). `report`
writes a stored batch's report again.

`backtest` (M8) scores every case in five variants on the run the AI's shocks were sized on:
baseline, naive, guidance shocks (with --guidance) and the AI's named and masked shocks, and
writes the M3 report and data/reports/eval/<batch_id>_backtest.md. `reproduce` scores a stored
backtest batch again from stored data and checks every row to the cent; it exits 1 on any
difference.

    python -m domains.evaluation ranges origins [--ticker T ...] [--from D] [--to D]
    python -m domains.evaluation ranges test [--batch EVAL_BATCH] [--guidance PATH]
    python -m domains.evaluation ranges reproduce --build B [--guidance PATH]

M9 (honest ranges): `origins` runs the baseline on the 1st of every month for every company and
stores each forecast quarter's miss; `test` builds every range from the misses public on its
date, scores the rolling test and (with --batch) the backtest's cases, and writes
data/reports/eval/<build_id>_ranges.md; `reproduce` checks a stored build to the cent.
"""

import argparse
import sys
from pathlib import Path

from domains.evaluation import backtest_report
from domains.evaluation.backtest_batch import reproduce_batch, run_backtest
from domains.evaluation.cases import CASES_PATH, cases_sha256, load_cases
from domains.evaluation.guidance import guidance_sha256, load_guides
from domains.evaluation.harness import run_batch
from domains.evaluation.report import load_rows, summary, write_report
from shared_kernel.config import PROJECT_ROOT
from shared_kernel.database import apply_migrations, get_db_connection


def _shown(path: Path) -> Path:
    return path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.cases_file)
    cases = load_cases(path)
    if args.case:
        unknown = set(args.case) - {c.case_id for c in cases}
        if unknown:
            print(f"Unknown case ids: {sorted(unknown)}")
            return 2
        cases = [c for c in cases if c.case_id in args.case]
    with get_db_connection() as conn:
        apply_migrations(conn)
        guides = sha = None
        if args.guidance:
            guides, sha = load_guides(Path(args.guidance)), guidance_sha256(Path(args.guidance))
        batch_id = run_batch(conn, cases, cases_sha256(path), guides=guides, guidance_sha256=sha)
        report = write_report(conn, batch_id)
        failed = conn.execute(
            "SELECT case_id, reason FROM eval_failures WHERE batch_id = ?", (batch_id,)
        ).fetchall()
        stats = summary(load_rows(conn, batch_id))
    for f in failed:
        print(f"{f['case_id']:18} FAILED: {f['reason']}")
    for item in ("revenue", "ebit"):
        s = stats.get((item, None))
        if s:
            print(
                f"{item:8} median error baseline {s['baseline']:.4f}  naive {s['naive']:.4f}  "
                f"baseline beat naive {s['beat']:.0%}  (n={s['n']})"
            )
    print(f"{batch_id}  {len(cases) - len(failed)}/{len(cases)} cases scored  {_shown(report)}")
    return 1 if len(failed) == len(cases) else 0


def cmd_report(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        print(_shown(write_report(conn, args.batch)))
    return 0


def _cases(args: argparse.Namespace):
    cases = load_cases(Path(args.cases_file))
    if getattr(args, "case", None):
        unknown = set(args.case) - {c.case_id for c in cases}
        if unknown:
            raise SystemExit(f"Unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c.case_id in args.case]
    return cases


def _guides(args: argparse.Namespace):
    if not args.guidance:
        return None, None
    return load_guides(Path(args.guidance)), guidance_sha256(Path(args.guidance))


def cmd_backtest(args: argparse.Namespace) -> int:
    cases = _cases(args)
    guides, sha = _guides(args)
    with get_db_connection() as conn:
        apply_migrations(conn)
        batch_id = run_backtest(conn, cases, cases_sha256(Path(args.cases_file)), guides, sha)
        m3 = write_report(conn, batch_id)
        m8 = backtest_report.write_report(conn, batch_id)
        failed = conn.execute(
            "SELECT case_id, reason FROM eval_failures WHERE batch_id = ?", (batch_id,)
        ).fetchall()
    for f in failed:
        print(f"{f['case_id']:18} FAILED: {f['reason']}")
    print(f"{batch_id}  {len(cases) - len(failed)}/{len(cases)} cases scored")
    print(f"  {_shown(m3)}\n  {_shown(m8)}")
    return 1 if len(failed) == len(cases) else 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    guides, sha = _guides(args)
    with get_db_connection() as conn:
        apply_migrations(conn)
        check = reproduce_batch(conn, args.batch, load_cases(Path(args.cases_file)), guides, sha)
    for m in check.mismatches:
        print(f"MISMATCH {m}")
    print(f"code {check.code_then} → {check.code_now}")
    verdict = "OK" if check.ok else "FAILED"
    print(f"{verdict}  {args.batch}: {check.rows_checked} rows and "
          f"{check.simulations_checked} simulations checked")  # fmt: skip
    return 0 if check.ok else 1


def cmd_ranges_origins(args: argparse.Namespace) -> int:
    from datetime import date

    from domains.evaluation import ranges

    start = date.fromisoformat(args.start) if args.start else ranges.FIRST_ORIGIN
    end = date.fromisoformat(args.end) if args.end else ranges.LAST_ORIGIN
    with get_db_connection() as conn:
        apply_migrations(conn)
        counts = ranges.build_origins(conn, args.ticker, start, end)
        failed = conn.execute(
            "SELECT origin_id, reason FROM forecast_origins WHERE status = 'failed'"
        ).fetchall()
    for f in failed:
        print(f"{f['origin_id']:18} FAILED: {f['reason']}")
    print("origins: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    return 0


def cmd_ranges_test(args: argparse.Namespace) -> int:
    from datetime import date

    from domains.evaluation import ranges, ranges_report

    guides, sha = _guides(args)
    with get_db_connection() as conn:
        apply_migrations(conn)
        build_id = ranges.run_build(conn, date.today(), args.batch, guides, sha)
        text = ranges_report.render(conn, build_id)
    path = PROJECT_ROOT / "data" / "reports" / "eval" / f"{build_id}_ranges.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"{build_id}  {_shown(path)}")
    return 0


def cmd_ranges_reproduce(args: argparse.Namespace) -> int:
    import json

    from domains.evaluation import ranges

    guides, sha = _guides(args)
    with get_db_connection() as conn:
        apply_migrations(conn)
        build = conn.execute(
            "SELECT notes FROM range_builds WHERE build_id = ?", (args.build,)
        ).fetchone()
        if build is None:
            print(f"no build {args.build}")
            return 2
        then = json.loads(build["notes"] or "{}").get("guidance_sha256")
        if then != sha:
            print(f"FAILED  guidance file hash {sha}, the build ran {then}")
            return 1
        check = ranges.reproduce_build(conn, args.build, guides)
    for m in check.mismatches[:50]:
        print(f"MISMATCH {m}")
    print(f"code {check.code_then} → {check.code_now}")
    verdict = "OK" if check.ok else f"FAILED ({len(check.mismatches)} mismatches)"
    print(f"{verdict}  {args.build}: {check.errors_checked} errors and {check.rows_checked} "
          "ranges checked")  # fmt: skip
    return 0 if check.ok else 1


def cmd_grid(args) -> int:
    """Write or check the grid file (M10): every company on every rule-picked date."""
    from datetime import date

    from domains.evaluation import grid

    end = date.fromisoformat(args.end) if args.end else grid.GRID_END
    if args.write:
        cases = grid.write_grid(end=end)
        print(f"wrote {len(cases)} grid cases to {grid.GRID_PATH}")
    else:
        cases = grid.load_grid(end=end)
        print(f"OK  {grid.GRID_PATH.name}: {len(cases)} grid cases match the rule")
    _, left_out = grid.grid_cases(end=end)
    post = sum(grid.is_post_cutoff(c.event_date) for c in cases)
    dates = len({c.event_date for c in cases})
    print(f"{dates} dates; {len(cases) - post} pre-cutoff, {post} post-cutoff cases; "
          f"{len(left_out)} left out by rule")  # fmt: skip
    for case_id, reason in left_out:
        print(f"  left out {case_id}: {reason}")
    shared = grid.shared_with_hand_picked(cases)
    short = [c for c in cases if c.horizon_quarters < grid.HORIZON]
    print(f"{len(short)} with a shorter horizon (coverage guard); {len(shared)} shared with "
          f"hand-picked cases: {', '.join(shared) or 'none'}")  # fmt: skip
    return 0


def cmd_run_grid(args) -> int:
    """Run the grid cases through the pipeline (M10), under one spending cap."""
    from datetime import date

    from domains.evaluation import grid, grid_run

    cases = grid.load_grid()
    if args.ticker:
        cases = [c for c in cases if c.ticker in {t.upper() for t in args.ticker}]
    if args.start:
        cases = [c for c in cases if c.event_date >= date.fromisoformat(args.start)]
    if args.end:
        cases = [c for c in cases if c.event_date <= date.fromisoformat(args.end)]
    with get_db_connection() as conn:
        apply_migrations(conn)
        todo, done = grid_run.pending(conn, cases)
        if args.dry_run:
            dates = len({c.event_date for c in todo})
            print(f"{len(done)} grid cases done, {len(todo)} to run on {dates} dates; about "
                  f"${grid_run.estimate_usd(conn, len(todo)):.2f} of AI calls "
                  f"(${grid_run.ESTIMATE_USD:.2f} a case, the measured M7 date)")  # fmt: skip
            for c in todo[:10]:
                print(f"  next {c.case_id}")
            return 0
        from domains.orchestration import graph
        from domains.orchestration.__main__ import FOLDERS, make_deps
        from shared_kernel.config import anthropic_api_key

        anthropic_api_key()  # before anything runs, so a missing key costs nothing
        deps = make_deps(conn)

        def start(ticker, as_of, seed, budget):
            return graph.start(deps, FOLDERS, ticker, as_of, variants=["named", "masked"],
                               review="auto", seed=seed, budget=budget)  # fmt: skip

        def resume(pipeline_id, budget):
            return graph.resume(deps, FOLDERS, pipeline_id, budget=budget)

        summary = grid_run.run_grid(conn, cases, args.max_usd, start, resume)
    print(f"{len(summary.done)} done now, {len(summary.done_before)} before, "
          f"{len(summary.failed)} failed, {len(summary.not_run)} not run; "
          f"${summary.spent_usd:.2f} spent")  # fmt: skip
    if summary.stopped:
        print(f"stopped: {summary.stopped}")
    return 0 if not summary.failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="score the baseline on the case library")
    run.add_argument("--case", action="append", help="a case id (repeatable); default: all")
    run.add_argument("--cases-file", default=str(CASES_PATH))
    run.add_argument("--guidance", help="transcribed company guidance (M4); default: none")
    run.set_defaults(func=cmd_run)
    rep = commands.add_parser("report", help="write a stored batch's report again")
    rep.add_argument("--batch", required=True)
    rep.set_defaults(func=cmd_report)
    bt = commands.add_parser("backtest", help="score all five variants (M8)")
    bt.add_argument("--case", action="append", help="a case id (repeatable); default: all")
    bt.add_argument("--cases-file", default=str(CASES_PATH))
    bt.add_argument("--guidance", help="transcribed company guidance (M4); default: none")
    bt.set_defaults(func=cmd_backtest)
    rp = commands.add_parser("reproduce", help="score a stored backtest batch again")
    rp.add_argument("--batch", required=True)
    rp.add_argument("--cases-file", default=str(CASES_PATH))
    rp.add_argument("--guidance", help="the guidance file the batch ran with, if any")
    rp.set_defaults(func=cmd_reproduce)
    rg = commands.add_parser("ranges", help="honest ranges from past errors (M9)")
    rcmd = rg.add_subparsers(dest="ranges_command", required=True)
    ro = rcmd.add_parser("origins", help="run the baseline monthly and store its misses")
    ro.add_argument("--ticker", action="append", help="a ticker (repeatable); default: all")
    ro.add_argument("--from", dest="start", help="first origin month, YYYY-MM-DD")
    ro.add_argument("--to", dest="end", help="last origin month, YYYY-MM-DD")
    ro.set_defaults(func=cmd_ranges_origins)
    rt = rcmd.add_parser("test", help="build every range and write the report")
    rt.add_argument("--batch", help="an M8 backtest batch whose cases to range")
    rt.add_argument("--guidance", help="the guidance file the batch ran with, if any")
    rt.set_defaults(func=cmd_ranges_test)
    rr = rcmd.add_parser("reproduce", help="check a stored build to the cent")
    rr.add_argument("--build", required=True)
    rr.add_argument("--guidance", help="the guidance file the build ran with, if any")
    rr.set_defaults(func=cmd_ranges_reproduce)
    gr = commands.add_parser("grid", help="write or check the rule-dated grid cases (M10)")
    gr.add_argument("--write", action="store_true", help="regenerate the file from the rule")
    gr.add_argument("--end", help="the last grid date, YYYY-MM-DD; default: grid.GRID_END")
    gr.set_defaults(func=cmd_grid)
    rgr = commands.add_parser("run-grid", help="run the grid cases through the pipeline (M10)")
    rgr.add_argument("--max-usd", type=float, required=True, help="the spending cap for AI calls")
    rgr.add_argument("--ticker", action="append", help="a ticker (repeatable); default: all")
    rgr.add_argument("--from", dest="start", help="first grid date, YYYY-MM-DD")
    rgr.add_argument("--to", dest="end", help="last grid date, YYYY-MM-DD")
    rgr.add_argument("--dry-run", action="store_true", help="list what would run and its cost")
    rgr.set_defaults(func=cmd_run_grid)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
