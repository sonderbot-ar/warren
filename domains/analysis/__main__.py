"""Command line for the DCF engine.

    python -m domains.analysis dcf --ticker AAPL --as-of 2024-03-31 [--as-of 2026-09-30 ...]
    python -m domains.analysis dcf --all --as-of 2024-03-31
    python -m domains.analysis reproduce --run-id AAPL_2024-03-31_1
    python -m domains.analysis reproduce --all [--rebuild]
    python -m domains.analysis fallbacks [--as-of 2026-10-26]

`dcf` stores each run and writes data/reports/dcf/<TICKER>_<as_of>.md; it exits 1 if any run
fails. `reproduce` values stored runs again from their assumptions and exits 1 on any mismatch; with
`--rebuild` it also builds each run's assumptions again from the data it used and compares them
(a run made by older code may differ in method text only; that is listed apart).
`fallbacks` compares every fallback with its primary item across the universe.
"""

import argparse
import sys
from datetime import date

from domains.analysis.math_engine import EngineError, fallback_backtest
from domains.analysis.report import write_report
from domains.analysis.runs import rebuild, reproduce, run_baseline
from domains.fundamentals.universe import PHASE1_UNIVERSE, get_universe_company
from domains.market.store import MarketDataError
from shared_kernel.config import PROJECT_ROOT
from shared_kernel.database import apply_migrations, get_db_connection


def cmd_dcf(args: argparse.Namespace) -> int:
    tickers = (
        [c.ticker for c in PHASE1_UNIVERSE]
        if args.all
        else [get_universe_company(args.ticker).ticker]
    )
    failed = 0
    with get_db_connection() as conn:
        apply_migrations(conn)
        for as_of in [date.fromisoformat(d) for d in args.as_of]:
            for ticker in tickers:
                try:
                    run_id = run_baseline(conn, ticker, as_of)
                except (EngineError, MarketDataError, ValueError) as e:
                    failed += 1
                    print(f"{ticker:5} {as_of}  FAILED: {e}")
                    continue
                path = write_report(conn, run_id)
                row = conn.execute(
                    "SELECT value FROM run_outputs WHERE run_id = ? AND name = 'value_per_share'",
                    (run_id,),
                ).fetchone()
                shown = (
                    path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path
                )
                print(
                    f"{ticker:5} {as_of}  value per share {row['value']:10,.2f}  "
                    f"{run_id:22} {shown}"
                )
    return 1 if failed else 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        run_ids = (
            [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id")]
            if args.all
            else [args.run_id]
        )
        bad = unbuilt = text_only = 0
        for run_id in run_ids:
            result = reproduce(conn, run_id)
            status = "OK      " if result.ok else "MISMATCH"
            print(f"{status} {run_id:22} {result.outputs_checked} outputs")
            for name, period, stored, now in result.mismatches:
                print(f"         {name} {period}: stored {stored}, now {now}")
            if result.stored_code_version != result.current_code_version:
                print(f"         code {result.stored_code_version} → {result.current_code_version}")
            bad += not result.ok
            if args.rebuild:
                try:
                    rebuilt = rebuild(conn, run_id)
                except (EngineError, MarketDataError, ValueError) as e:
                    print(f"         rebuild FAILED: {e}")
                    unbuilt += 1
                    continue
                if rebuilt.ok:
                    status = "OK"
                elif rebuilt.values_ok:
                    status = f"values OK, method text differs in {len(rebuilt.mismatches)} rows"
                else:
                    status = "MISMATCH"
                print(f"         rebuild {status}, {rebuilt.rows_checked} rows")
                if not rebuilt.values_ok:
                    for name, period, what in rebuilt.mismatches:
                        print(f"         {name} {period}: {what} differs")
                unbuilt += not rebuilt.ok
                text_only += rebuilt.values_ok and not rebuilt.ok
    print(f"{len(run_ids) - bad} of {len(run_ids)} runs reproduced to the cent")
    if args.rebuild:
        print(
            f"{len(run_ids) - unbuilt} of {len(run_ids)} runs rebuilt to identical rows; "
            f"{text_only} more with identical values (method text from older code)"
        )
    return 1 if bad or unbuilt else 0


def cmd_fallbacks(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    with get_db_connection() as conn:
        for check in fallback_backtest(conn, as_of):
            worst = check.worst
            detail = (
                f"median {check.median:.2%}, worst {worst[2]:+.1%} ({worst[0]} FY{worst[1]})"
                if worst
                else "no period reports both"
            )
            flag = "  FLAG" if check.flagged else ""
            print(
                f"{check.chain:8} {check.fallback:45} vs {check.primary:26} "
                f"{len(check.gaps):3} years, {detail}{flag}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.analysis")
    commands = parser.add_subparsers(dest="command", required=True)

    dcf = commands.add_parser("dcf", help="baseline DCF runs")
    target = dcf.add_mutually_exclusive_group(required=True)
    target.add_argument("--ticker")
    target.add_argument("--all", action="store_true", help="the Phase 1 universe")
    dcf.add_argument("--as-of", action="append", required=True, help="YYYY-MM-DD, repeatable")
    dcf.set_defaults(func=cmd_dcf)

    rep = commands.add_parser("reproduce", help="value stored runs again and compare")
    which = rep.add_mutually_exclusive_group(required=True)
    which.add_argument("--run-id")
    which.add_argument("--all", action="store_true", help="every stored run")
    rep.add_argument(
        "--rebuild", action="store_true", help="also rebuild the assumptions from data and compare"
    )
    rep.set_defaults(func=cmd_reproduce)

    fb = commands.add_parser("fallbacks", help="compare each fallback with its primary item")
    fb.add_argument("--as-of", help="YYYY-MM-DD (default: today)")
    fb.set_defaults(func=cmd_fallbacks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
