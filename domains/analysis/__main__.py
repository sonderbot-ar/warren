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
`notes` prints a stored run's warnings as codes with parameters (backlog #172); `--backfill` gives
runs stored before them their codes, only where the rebuilt text matches the stored text exactly.
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
from domains.analysis.runs import (
    RunNotes,
    backfill_notes,
    rebuild,
    reproduce,
    run_baseline,
    run_notes,
)
from domains.analysis.sensitivity import Block, Grid, GridError, grid
from domains.analysis.sources import SourceError, backfill, run_sources
from domains.analysis.whatif import Change, WhatIf, WhatIfError, revalue
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
    as_of = date.fromisoformat(args.as_of) if args.as_of else last_ended_day(datetime.now(UTC))
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
            code = getattr(e, "code", None)
            print(f"FAILED ({code}): {e}" if code else f"FAILED: {e}")
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


def parse_change(text: str, kind: str) -> Change:
    """NAME=NUMBER or NAME@PERIOD=NUMBER, for --set (kind value) or --add (kind delta)."""
    target, sep, number = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"{text!r}: expected NAME[@PERIOD]=NUMBER")
    name, _, period = target.partition("@")
    try:
        amount = float(number)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{text!r}: {number!r} is not a number") from e
    return Change(name.strip(), period=period.strip() or None, **{kind: amount})


def parse_switch(text: str) -> Change:
    """NAME=METHOD, for --switch (the terminal formula on a what-if)."""
    name, sep, method = text.partition("=")
    if not sep or not method.strip():
        raise argparse.ArgumentTypeError(f"{text!r}: expected NAME=METHOD")
    return Change(name.strip(), method=method.strip())


def _fmt_change(value) -> str:
    return value if isinstance(value, str) else f"{value:.6g}"


def _fmt_line(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "fraction":
        return f"{value:.3%}"
    if unit == "per_share":
        return f"{value:,.2f}"
    return f"{value / 1e6:,.1f}m"


def render_whatif(w: WhatIf) -> str:
    """A what-if's changes, its before / after / change lines and its notes, for the terminal."""
    out = [
        f"What-if {w.run_id} on {w.parent_run_id} ({w.ticker} as of {w.as_of}, {w.currency})"
        + (" — already stored" if w.reused else ""),
        "Changed inputs:",
    ]
    for c in w.changes:
        out.append(
            f"  {c.name:22} {c.period:9} {_fmt_change(c.before):>14} → "
            f"{_fmt_change(c.after):<14} ({c.how})"
        )
    out.append(f"Terminal value: {w.terminal_formula.text}")
    out.append(
        f"  {'line':24} {'period':9} {'before':>14} {'after':>14} {'change':>14}  because of"
    )
    for x in w.lines:
        if not x.change and x.period != "-":
            continue  # unchanged per-period lines are left out of the table, not the JSON
        change = "—" if x.change is None else _fmt_line(x.change, x.unit)
        pct = "" if x.change_pct is None or not x.change else f" ({x.change_pct:+.2%})"
        out.append(
            f"  {x.name:24} {x.period:9} {_fmt_line(x.before, x.unit):>14} "
            f"{_fmt_line(x.after, x.unit):>14} {change:>14}{pct}  {', '.join(x.driven_by)}"
        )
    for note in w.notes:
        out.append(f"Note: {note.text}")
    return "\n".join(out)


def cmd_whatif(args: argparse.Namespace) -> int:
    changes = [parse_change(t, "value") for t in args.set or []]
    changes += [parse_change(t, "delta") for t in args.add or []]
    changes += [parse_switch(t) for t in args.switch or []]
    with get_db_connection() as conn:
        apply_migrations(conn)
        try:
            result = revalue(conn, args.run_id, changes)
        except WhatIfError as e:
            print(f"REFUSED ({e.code}): {e.text}")
            return 1
    print(json.dumps(result.to_dict(), indent=2) if args.json else render_whatif(result))
    return 0


def parse_steps(text: str) -> list[float]:
    """A comma-separated list of shifts in fractions, e.g. "-0.01,0,0.01" (pass a list that
    starts with a minus as --wacc-steps=-0.01,0.01)."""
    try:
        return [float(x) for x in text.split(",") if x.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"steps must be numbers separated by commas: {text}"
        ) from e


def _render_block(g: Grid, b: Block, title: str) -> list[str]:
    out = [f"{title}: {b.terminal_formula.text}"]
    corner = "WACC / growth"
    out.append(f"  {corner:>14} " + " ".join(f"{x:>11.2%}" for x in g.growth_values))
    reasons = []
    for i, row in enumerate(b.cells):
        cells = []
        for j, c in enumerate(row):
            if c.value_per_share is None:
                if c.gap and c.gap.text not in reasons:
                    reasons.append(c.gap.text)
                cells.append(f"{'n/a':>11}")
            else:
                mark = "*" if (i, j) == (g.run_point["row"], g.run_point["column"]) else " "
                cells.append(f"{c.value_per_share:>10.2f}{mark}")
        out.append(f"  {g.wacc_values[i]:>14.2%} " + " ".join(cells))
    if reasons:
        out.append(f"  n/a: no value ({'; '.join(reasons)})")
    for s in (b.wacc_spread, b.growth_spread):
        if s.per_point is None:
            out.append(f"  along {s.axis}: no spread ({s.gap})")
        else:
            out.append(
                f"  along {s.axis}: {s.low_value:.2f} to {s.high_value:.2f} "
                f"({s.low_change_pct:+.1%} to {s.high_change_pct:+.1%}), "
                f"{s.per_point:+.2%} of the value per point"
            )
    if b.reinvestment_rate is not None:
        out.append(f"  year-5 reinvestment rate {b.reinvestment_rate:.1%}")
    return out


def render_grid(g: Grid) -> str:
    """The run's table, the contrast table, their spreads and the notes, for the terminal."""
    out = [
        f"Sensitivity of {g.run_id} ({g.ticker} as of {g.as_of}, {g.currency} per share); "
        "* is the run's own point"
    ]
    out += _render_block(g, g.method, f"This run's method ({g.method.terminal_method})")
    out += _render_block(g, g.contrast, f"Contrast ({g.contrast.terminal_method})")
    for note in g.notes:
        out.append(f"Note: {note.text}")
    return "\n".join(out)


def cmd_sensitivity(args: argparse.Namespace) -> int:
    kwargs = {}
    if args.wacc_steps is not None:
        kwargs["wacc_steps"] = args.wacc_steps
    if args.growth_steps is not None:
        kwargs["growth_steps"] = args.growth_steps
    with get_db_connection() as conn:
        apply_migrations(conn)
        try:
            result = grid(conn, args.run_id, **kwargs)
        except GridError as e:
            print(f"REFUSED ({e.code}): {e.text}")
            return 1
    print(json.dumps(result.to_dict(), indent=2) if args.json else render_grid(result))
    return 0


def render_sources(r, name: str | None = None) -> str:
    out = [f"Sources of {r.run_id} ({r.ticker}, as of {r.as_of})"]
    if not r.recorded:
        out.append("Not recorded: this run was stored before sources were (try --backfill).")
    for row in r.rows:
        if name and row["name"] != name:
            continue
        value = "—" if row["value"] is None else f"{row['value']:,.6g}"
        out.append(f"  {row['name']:28} {row['period']:9} {value:>14}")
        for item in row["sources"]:
            out.append(f"      {_describe_source(item)}")
    return "\n".join(out)


def _describe_source(item: dict) -> str:
    kind = item["kind"]
    if kind == "filing":
        filing = item["filing"]
        where = (
            f"{filing['form']} {filing['accession_no']} filed {filing['filed_at']}"
            if filing
            else "derived from " + ", ".join(f["accession_no"] for f in item["input_filings"])
        )
        return f"filing: {item['concept']} {item['period_end']} = {item['value']:,.6g} ({where})"
    if kind == "market":
        span = (
            item["start"] if item["start"] == item["end"] else f"{item['start']} to {item['end']}"
        )
        return f"market: {item['label']} {item['series']} {item['measure']} {span}"
    if kind == "owner_choice":
        who = f"{item['set_by']}, {item['set_on']}"
        return f"owner's choice: {item['choice']} = {item['value']} ({who})"
    if kind == "derived":
        refs = [
            f"{i['name']} {i['period']}" + (f" of {i['run_id']}" if "run_id" in i else "")
            for i in item["inputs"]
        ]
        return "from rows: " + ", ".join(refs)
    if kind == "rule":
        return f"rule: {item['text']}"
    return f"what-if: {item['how']} on {item['parent_run_id']} (was {item['before']:,.6g})"


def cmd_sources(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        if args.backfill:
            if not (args.run_id or args.all):
                print("--backfill needs --run-id R or --all")
                return 2
            ids = (
                [args.run_id]
                if args.run_id
                else [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id")]
            )
            counts: dict[str, int] = {}
            for run_id in ids:
                status, detail = backfill(conn, run_id)
                counts[status] = counts.get(status, 0) + 1
                if status not in ("filled", "already_recorded"):
                    print(f"{run_id}: {status} {detail}".rstrip())
            print("Backfill: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
            return 0
        if not args.run_id:
            print("--run-id is required")
            return 2
        try:
            result = run_sources(conn, args.run_id)
        except SourceError as e:
            print(f"REFUSED: {e}")
            return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_sources(result, args.name))
    return 0


def render_notes(r: RunNotes) -> str:
    head = f"Notes of {r.run_id}" + ("" if r.recorded else " (stored as text only: no codes)")
    lines = [f"- [{n.code}] {n.text}" for n in r.notes] or ["None."]
    return "\n".join([head, *lines])


def cmd_notes(args: argparse.Namespace) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        if args.backfill:
            if not (args.run_id or args.all):
                print("--backfill needs --run-id R or --all")
                return 2
            ids = (
                [args.run_id]
                if args.run_id
                else [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id")]
            )
            counts: dict[str, int] = {}
            for run_id in ids:
                status, detail = backfill_notes(conn, run_id)
                counts[status] = counts.get(status, 0) + 1
                if status not in ("filled", "already_recorded", "no_notes"):
                    print(f"{run_id}: {status} {detail}".rstrip())
            print("Backfill: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
            return 0
        if not args.run_id:
            print("--run-id is required")
            return 2
        try:
            result = run_notes(conn, args.run_id)
        except ValueError as e:
            print(f"REFUSED: {e}")
            return 1
    print(json.dumps(result.to_dict(), indent=2) if args.json else render_notes(result))
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

    wi = commands.add_parser("whatif", help="a stored run valued again with inputs changed")
    wi.add_argument("--run-id", required=True)
    wi.add_argument(
        "--set",
        action="append",
        metavar="NAME[@PERIOD]=VALUE",
        help="set an input (fractions for rates: 0.05 = 5%%); repeatable",
    )
    wi.add_argument(
        "--add",
        action="append",
        metavar="NAME[@PERIOD]=DELTA",
        help="add to an input (0.01 = one point); repeatable",
    )
    wi.add_argument(
        "--switch",
        action="append",
        metavar="terminal_method=METHOD",
        help="value under the other terminal formula (gordon_fcff or value_driver_ronic_wacc)",
    )
    wi.add_argument("--json", action="store_true", help="print JSON for the app")
    wi.set_defaults(func=cmd_whatif)

    se = commands.add_parser(
        "sensitivity", help="value per share over WACC × terminal growth on a stored run"
    )
    se.add_argument("--run-id", required=True)
    se.add_argument(
        "--wacc-steps",
        type=parse_steps,
        metavar="S,S,...",
        help="shifts from the run's WACC (0.01 = one point; write --wacc-steps=-0.01,0.01)",
    )
    se.add_argument(
        "--growth-steps",
        type=parse_steps,
        metavar="S,S,...",
        help="shifts from the run's terminal growth (write --growth-steps=-0.005,0.005)",
    )
    se.add_argument("--json", action="store_true", help="print JSON for the app")
    se.set_defaults(func=cmd_sensitivity)

    so = commands.add_parser("sources", help="where each assumption of a stored run came from")
    so.add_argument("--run-id", help="the run (with --backfill: only this run)")
    so.add_argument("--name", help="only this assumption, in the table")
    so.add_argument("--json", action="store_true", help="print JSON for the app")
    so.add_argument(
        "--backfill",
        action="store_true",
        help="give older runs their sources, when their rows rebuild exactly",
    )
    so.add_argument("--all", action="store_true", help="with --backfill: every stored run")
    so.set_defaults(func=cmd_sources)

    no = commands.add_parser("notes", help="a stored run's warnings, as codes (backlog #172)")
    no.add_argument("--run-id", help="the run (with --backfill: only this run)")
    no.add_argument("--json", action="store_true", help="print JSON for the app")
    no.add_argument(
        "--backfill",
        action="store_true",
        help="give older runs their codes, when the rebuilt text matches exactly",
    )
    no.add_argument("--all", action="store_true", help="with --backfill: every stored run")
    no.set_defaults(func=cmd_notes)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
