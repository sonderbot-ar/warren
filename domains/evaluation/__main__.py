"""Command line for the evaluation harness.

    python -m domains.evaluation run [--case AAPL_2020-02-17 ...] [--cases-file PATH]
    python -m domains.evaluation report --batch eval_2026-10-30_1

`run` scores every case in the case file (or the ones named) and writes
data/reports/eval/<batch_id>.md. Cases that can't be scored are listed with their reason; it exits
1 only when no case could be scored. `report` writes a stored batch's report again.
"""

import argparse
import sys
from pathlib import Path

from domains.evaluation.cases import CASES_PATH, cases_sha256, load_cases
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
        batch_id = run_batch(conn, cases, cases_sha256(path))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="score the baseline on the case library")
    run.add_argument("--case", action="append", help="a case id (repeatable); default: all")
    run.add_argument("--cases-file", default=str(CASES_PATH))
    run.set_defaults(func=cmd_run)
    rep = commands.add_parser("report", help="write a stored batch's report again")
    rep.add_argument("--batch", required=True)
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
