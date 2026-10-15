"""Command line for the fundamentals data layer.

    python -m domains.fundamentals ingest --ticker AAPL [--refresh]
    python -m domains.fundamentals ingest --all
    python -m domains.fundamentals report --ticker AAPL [--as-of 2025-12-31]
    python -m domains.fundamentals report --all

`report` writes data/reports/quality/<TICKER>.md and exits 1 if any gap is unexplained.
"""

import argparse
import sys
from datetime import date

from domains.fundamentals.edgar_client import EdgarClient
from domains.fundamentals.ingest import ingest_company
from domains.fundamentals.quality import build_report
from domains.fundamentals.universe import PHASE1_UNIVERSE, get_universe_company
from shared_kernel.config import REPORTS_DIR
from shared_kernel.database import apply_migrations, get_db_connection


def _companies(args: argparse.Namespace):
    if args.all:
        return PHASE1_UNIVERSE
    return [get_universe_company(args.ticker)]


def cmd_ingest(args: argparse.Namespace) -> int:
    client = EdgarClient()
    with get_db_connection() as conn:
        apply_migrations(conn)
        for company in _companies(args):
            result = ingest_company(
                conn, company.ticker, client=client, cik=company.cik, refresh=args.refresh
            )
            skipped = ", ".join(f"{k} {v}" for k, v in sorted(result.skipped.items())) or "none"
            print(
                f"{result.ticker:5} CIK {result.cik}: {result.facts_kept} facts kept "
                f"({result.facts_new} new) of {result.facts_seen} mapped; "
                f"{result.calendar_entries} filing periods; skipped: {skipped}"
            )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    out_dir = REPORTS_DIR / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    total_unexplained = 0
    with get_db_connection() as conn:
        for company in _companies(args):
            report = build_report(conn, company.ticker, as_of=as_of)
            path = out_dir / f"{report.ticker}.md"
            path.write_text(report.to_markdown())
            total_unexplained += len(report.unexplained)
            print(
                f"{report.ticker:5} unexplained gaps {len(report.unexplained):4} · explained "
                f"{len(report.explained):4} · {path.relative_to(REPORTS_DIR.parent.parent)}"
            )
    return 1 if total_unexplained else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.fundamentals")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, func in (("ingest", cmd_ingest), ("report", cmd_report)):
        sub = commands.add_parser(name)
        target = sub.add_mutually_exclusive_group(required=True)
        target.add_argument("--ticker")
        target.add_argument("--all", action="store_true", help="the Phase 1 universe")
        sub.set_defaults(func=func)
    commands.choices["ingest"].add_argument("--refresh", action="store_true")
    commands.choices["report"].add_argument("--as-of", help="YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
