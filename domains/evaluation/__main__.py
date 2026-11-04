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
    python -m domains.evaluation ranges run --run-id R [--json]

M9 (honest ranges): `origins` runs the baseline on the 1st of every month for every company and
stores each forecast quarter's miss; `test` builds every range from the misses public on its
date, scores the rolling test and (with --batch) the backtest's cases, and writes
data/reports/eval/<build_id>_ranges.md; `reproduce` checks a stored build to the cent. `run`
(backlog #144) gives any stored run its range and the range's track record, as of the run's date;
`--json` prints it for the app. It writes nothing.

    python -m domains.evaluation track-record --ticker T [--as-of D] [--json]

`track-record` (backlog #145) shows how well Warren has forecast one company: every past
monthly forecast quarter beside its first-reported actual, the benchmark's miss and whether the
range held, with summaries. Without --as-of it uses the last day ended in New York. It writes
nothing.
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


def cmd_ranges_run(args: argparse.Namespace) -> int:
    import json

    from domains.evaluation import run_ranges
    from domains.evaluation.harness import EvaluationError

    with get_db_connection() as conn:
        apply_migrations(conn)
        try:
            result = run_ranges.run_ranges(conn, args.run_id)
        except EvaluationError as e:
            print(f"FAILED: {e}")
            return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(run_ranges.render(result), end="")
    return 0


def cmd_track_record(args: argparse.Namespace) -> int:
    import json
    from datetime import date

    from domains.evaluation import track_record
    from domains.evaluation.harness import EvaluationError

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    with get_db_connection() as conn:
        apply_migrations(conn)
        try:
            result = track_record.track_record(conn, args.ticker, as_of)
        except EvaluationError as e:
            print(f"FAILED: {e}")
            return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(track_record.render(result), end="")
    return 0


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
    rn = rcmd.add_parser("run", help="a stored run's range and the range's track record")
    rn.add_argument("--run-id", required=True)
    rn.add_argument("--json", action="store_true", help="print JSON for the app")
    rn.set_defaults(func=cmd_ranges_run)
    tr = commands.add_parser("track-record", help="how well Warren has forecast one company")
    tr.add_argument("--ticker", required=True)
    tr.add_argument("--as-of", help="YYYY-MM-DD; default: the last day ended in New York")
    tr.add_argument("--json", action="store_true", help="print JSON for the app")
    tr.set_defaults(func=cmd_track_record)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
