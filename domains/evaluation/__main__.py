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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
