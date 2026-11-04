"""Command line for the DCF engine.

    python -m domains.analysis dcf --ticker AAPL [--as-of 2024-03-31 --as-of 2026-09-30 ...]
    python -m domains.analysis dcf --all [--as-of 2024-03-31]
    python -m domains.analysis reproduce --run-id AAPL_2024-03-31_1
    python -m domains.analysis reproduce --all [--rebuild]
    python -m domains.analysis fallbacks [--as-of 2026-10-26]
    python -m domains.analysis simulate --run-id AAPL_2024-03-31_1 --shocks FILE [--n] [--seed]
    python -m domains.analysis reproduce-sim --sim-id AAPL_2024-03-31_1_sim1
    python -m domains.analysis reported --ticker AAPL --period latest-quarter [--as-of 2026-11-02]
        [--period FY2024 ...] [--json]

Without `--as-of`, `dcf` and `reported` use the last day that has ended in New York (backlog #128)
and say so, with the date of the company's last EDGAR download and a warning when that download
is older than the end of the day (filings after it may be missing).

`dcf` stores each run and writes data/reports/dcf/<TICKER>_<as_of>.md; it exits 1 if any run
fails. `reproduce` values stored runs again from their assumptions and exits 1 on any mismatch; with
`--rebuild` it also builds each run's assumptions again from the data it used and compares them
(a run made by older code may differ in method text only; that is listed apart).
`fallbacks` compares every fallback with its primary item across the universe.
`simulate` runs a stored baseline under hand-entered shocks (M4), stores the simulation and writes
data/reports/sim/<sim_id>.md; `reproduce-sim` runs it again from its seed and compares to the cent.
`reported` prints a fiscal period's reported lines, with their filings, and the named ratios, as
known on the as-of date (backlog #140); `--json` prints the same for the app. Nothing is stored.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from domains.analysis import sim_report
from domains.analysis.math_engine import EngineError, fallback_backtest
from domains.analysis.montecarlo import (
    DEFAULT_SAMPLES,
    RATES_CLEAN,
    SimulationError,
    load_shocks,
    reproduce_simulation,
    save_simulation,
)
from domains.analysis.report import write_report
from domains.analysis.reported import ReportedError, ReportedPeriod, reported_period
from domains.analysis.runs import rebuild, reproduce, run_baseline
from domains.fundamentals.universe import PHASE1_UNIVERSE, get_universe_company
from domains.market.store import MarketDataError
from shared_kernel.calendar import known_by, last_ended_day
from shared_kernel.config import PROJECT_ROOT
from shared_kernel.database import apply_migrations, get_db_connection


def now() -> datetime:
    """The clock; tests replace it."""
    return datetime.now(UTC)


def chosen_day_notes(conn, tickers: list[str], as_of: date) -> list[str]:
    """What a user should know when the date was chosen for them (backlog #128): the day, and
    each company's last EDGAR download, with a warning when it is older than the day's end."""
    notes = [f"as of {as_of} (the latest day that has ended in New York)"]
    for ticker in tickers:
        row = conn.execute(
            "SELECT i.companyfacts_fetched_at AS fetched, i.ingested_at AS ingested "
            "FROM ingest_runs i JOIN companies c USING (cik) WHERE c.ticker = ? "
            "ORDER BY i.run_id DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        stamp = row and (row["fetched"] or row["ingested"])
        if not stamp:
            notes.append(f"WARNING: {ticker}: no EDGAR download is stored")
            continue
        fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        fetched = fetched if fetched.tzinfo else fetched.replace(tzinfo=UTC)
        notes.append(f"{ticker}: filings as downloaded from EDGAR on {stamp[:10]}")
        if fetched < known_by(as_of):
            notes.append(
                f"WARNING: {ticker}: filings after {stamp[:10]} may be missing: run "
                f"python -m domains.fundamentals ingest --ticker {ticker}"
            )
    return notes


def cmd_dcf(args: argparse.Namespace) -> int:
    tickers = (
        [c.ticker for c in PHASE1_UNIVERSE]
        if args.all
        else [get_universe_company(args.ticker).ticker]
    )
    failed = 0
    with get_db_connection() as conn:
        apply_migrations(conn)
        days = [date.fromisoformat(d) for d in args.as_of or []]
        if not days:
            days = [last_ended_day(now())]
            print("\n".join(chosen_day_notes(conn, tickers, days[0])))
        for as_of in days:
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
        bad = unbuilt = text_only = whatifs = 0
        for run_id in run_ids:
            result = reproduce(conn, run_id)
            status = "OK      " if result.ok else "MISMATCH"
            print(f"{status} {run_id:22} {result.outputs_checked} outputs")
            for name, period, stored, now in result.mismatches:
                print(f"         {name} {period}: stored {stored}, now {now}")
            for name, period, stored, now in result.gap_mismatches:
                print(
                    f"         {name} {period}: no value because {stored}, now {now or 'a value'}"
                )
            if result.stored_code_version != result.current_code_version:
                print(f"         code {result.stored_code_version} → {result.current_code_version}")
            bad += not result.ok
            parent = conn.execute(
                "SELECT parent_run_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()["parent_run_id"]
            if args.rebuild and parent is not None:
                print(f"         rebuild skipped: a what-if of {parent} (rebuild the parent)")
                whatifs += 1
            elif args.rebuild:
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
            f"{len(run_ids) - unbuilt - whatifs} of {len(run_ids) - whatifs} runs rebuilt to "
            "identical rows; "
            f"{text_only} more with identical values (method text from older code)"
            + (f"; {whatifs} what-ifs not rebuilt (their parents are)" if whatifs else "")
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


def cmd_simulate(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        try:
            sim_id = save_simulation(
                conn, args.run_id, load_shocks(Path(args.shocks)), args.n, args.seed
            )
        except (SimulationError, ValueError) as e:
            print(f"FAILED: {e}")
            return 1
        path = sim_report.write_report(conn, sim_id)
        vps = conn.execute(
            "SELECT * FROM simulation_outputs WHERE sim_id = ? AND name = 'value_per_share'",
            (sim_id,),
        ).fetchone()
        notes = conn.execute("SELECT notes FROM simulations WHERE sim_id = ?", (sim_id,)).fetchone()
    print(
        f"{sim_id}  value per share baseline {vps['baseline']:,.2f}, shocked p10 {vps['p10']:,.2f}"
        f" p50 {vps['p50']:,.2f} p90 {vps['p90']:,.2f}  {path}"
    )
    for line in (notes["notes"] or "").split("\n")[1:]:
        if line and line != RATES_CLEAN:
            print(f"WARNING: {line}")
    return 0


def cmd_reproduce_sim(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        result = reproduce_simulation(conn, args.sim_id)
    print(f"{'OK' if result.ok else 'MISMATCH'} {result.sim_id} {result.outputs_checked} outputs")
    for line in result.mismatches:
        print(f"         {line}")
    return 0 if result.ok else 1


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"{value:.1%}" if unit == "fraction" else f"{value:,.0f} {unit}"


def render_reported(r: ReportedPeriod) -> str:
    """A period's lines, ratios and disagreements as plain text, for the terminal."""
    out = [
        f"{r.ticker} {r.company_name} · {r.period} ({r.period_start} to {r.period_end}) · "
        f"as of {r.as_of}"
    ]
    out.append("Lines (latest known; first reported where it differs):")
    for x in r.lines:
        source = x.latest.filing
        where = (
            f"{source.form} {source.accession_no} filed {source.filed_at}"
            if source
            else "derived from " + ", ".join(f"{i.form} {i.accession_no}" for i in x.latest.inputs)
        )
        line = f"  {x.name:32} {_fmt(x.value, x.unit):>26}  {x.latest.xbrl_concept}  {where}"
        if x.changed:
            line += f"  (first reported {_fmt(x.first_reported.value, x.unit)})"
        out.append(line)
    out.append("Ratios (" + r.as_reported_note.text + "):")
    for ratio in r.ratios:
        out.append(f"  {ratio.name:20} {_fmt(ratio.value, ratio.unit):>22}  {ratio.formula}")
        for coded in [*([ratio.missing] if ratio.missing else []), *ratio.notes]:
            out.append(f"  {'':20} {'':>22}  note: {coded.text}")
    if r.disagreements:
        out.append("Newest filing disagrees with the selected value:")
        for d in r.disagreements:
            out.append(
                f"  {d.name} {d.period_start or ''}–{d.period_end}: "
                f"selected {d.selected.value:,.0f}"
                f" ({d.selected.xbrl_concept}), newest {d.newest.value:,.0f}"
                f" ({d.newest.xbrl_concept})"
            )
    for w in r.warnings:
        out.append(f"WARNING: {w.text}")
    return "\n".join(out)


def cmd_reported(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else last_ended_day(now())
    results = []
    with get_db_connection() as conn:
        apply_migrations(conn)
        if not args.as_of:  # to standard error, so --json output stays plain JSON
            print("\n".join(chosen_day_notes(conn, [args.ticker], as_of)), file=sys.stderr)
        try:
            results = [reported_period(conn, args.ticker, p, as_of) for p in args.period]
        except ReportedError as e:
            print(f"FAILED: {e}")
            return 1
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(render_reported(r) for r in results))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.analysis")
    commands = parser.add_subparsers(dest="command", required=True)

    dcf = commands.add_parser("dcf", help="baseline DCF runs")
    target = dcf.add_mutually_exclusive_group(required=True)
    target.add_argument("--ticker")
    target.add_argument("--all", action="store_true", help="the Phase 1 universe")
    dcf.add_argument(
        "--as-of",
        action="append",
        help="YYYY-MM-DD, repeatable (default: the last day that has ended in New York)",
    )
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

    sim = commands.add_parser("simulate", help="Monte Carlo of a stored run under shocks")
    sim.add_argument("--run-id", required=True)
    sim.add_argument("--shocks", required=True, help="CSV of shocks")
    sim.add_argument("--n", type=int, default=DEFAULT_SAMPLES, help="samples")
    sim.add_argument("--seed", type=int, help="default: a fresh seed, stored with the run")
    sim.set_defaults(func=cmd_simulate)

    rsim = commands.add_parser("reproduce-sim", help="run a stored simulation again and compare")
    rsim.add_argument("--sim-id", required=True)
    rsim.set_defaults(func=cmd_reproduce_sim)

    rp = commands.add_parser("reported", help="a period's reported figures and named ratios")
    rp.add_argument("--ticker", required=True)
    rp.add_argument(
        "--period",
        action="append",
        required=True,
        help="FY2025, FY2025Q4, latest-quarter or latest-year; repeatable",
    )
    rp.add_argument(
        "--as-of",
        help="YYYY-MM-DD: only filings public by then (default: the last day ended in New York)",
    )
    rp.add_argument("--json", action="store_true", help="print JSON for the app")
    rp.set_defaults(func=cmd_reported)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
