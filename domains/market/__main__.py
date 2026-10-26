"""Command line for market data.

    python -m domains.market load [--refresh]

Loads daily prices for the Phase 1 universe and the S&P 500 (Yahoo Finance), and the 10-year
Treasury yield (FRED). Without --refresh, symbols already stored are not downloaded again.
"""

import argparse
import sys

from domains.fundamentals.universe import PHASE1_UNIVERSE
from domains.market.prices import MARKET_INDEX, load_prices
from domains.market.yields import RISK_FREE_SERIES, load_yields
from shared_kernel.database import apply_migrations, get_db_connection


def _describe(conn, fetch_id: int) -> str:
    f = conn.execute("SELECT * FROM market_fetches WHERE fetch_id = ?", (fetch_id,)).fetchone()
    return f"{f['row_count']} rows {f['first_date']} to {f['last_date']}, fetched {f['fetched_at']}"


def cmd_load(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        for ticker in [c.ticker for c in PHASE1_UNIVERSE] + [MARKET_INDEX]:
            fetch_id = load_prices(conn, ticker, refresh=args.refresh)
            print(f"{ticker:6} {_describe(conn, fetch_id)}")
        fetch_id = load_yields(conn, RISK_FREE_SERIES, refresh=args.refresh)
        print(f"{RISK_FREE_SERIES:6} {_describe(conn, fetch_id)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.market")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="download prices and the risk-free yield")
    load.add_argument("--refresh", action="store_true", help="download again even if stored")
    load.set_defaults(func=cmd_load)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
