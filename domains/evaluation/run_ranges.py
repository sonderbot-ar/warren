"""The error range and its track record on any stored run (backlog #144, front-end R3).

M9 (`ranges.py`) gives a forecast quarter a p10–p90 range from the baseline's own past misses,
but only for its stored origins and backtest cases. This gives one to any run, as of the run's
own date D, by M9's method unchanged: the misses whose actual was filed by D, both pools, the
same seeding rule. Beside it, how M9's ranges have done so far: the share of past quarters that
fell inside their range, over all companies and over this company, counting only origins dated
before D whose actual was filed by D. Nothing is written; gaps are coded, never raised.
With a simulation (backlog #167), the misses are applied to its shocked samples instead of the
baseline repeated, as M9 does for its cases ("combined" range).
Designs: docs/designs/backlog-144-run-ranges.md, docs/designs/backlog-167-shocked-range.md.
"""

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from domains.analysis import financial_math as fm
from domains.analysis.dcf import YEARS
from domains.analysis.montecarlo import (
    DEFAULT_SAMPLES,
    _currency,
    load_simulation_shocks,
    sample_lines,
)
from domains.analysis.reported import Coded
from domains.analysis.runs import load_assumptions, load_outputs
from domains.evaluation import ranges as R
from domains.evaluation import ranges_report as RR
from domains.evaluation.harness import EvaluationError
from domains.evaluation.ranges_report import cover

BASIS = "baseline"
SHOCKED = "shocked"
METHOD = "resampled_misses"
ITEMS = ("revenue", "ebit")
MAX_HORIZON = max(R.HORIZONS)
MIN_QUARTERS = 12  # distinct target quarters in a coverage cell, else `few_scored` (M9's own min)
SCOPES = ("all", "company")
TARGET = RR.TARGET
ACCEPTABLE = RR.COMPANY_BAND


@dataclass(frozen=True)
class Band:
    pool: str  # pooled (all companies' misses) or own (this company's)
    n_errors: int
    n_quarters: int
    revenue: dict | None  # {p10, p50, p90}, in the run's currency; None when no band
    ebit: dict | None
    revenue_vs_forecast: dict | None  # the band is forecast × (1 + x)
    ebit_vs_forecast: dict | None  # (band − EBIT forecast) / revenue forecast: margin points
    basis_changes: int | None  # known misses that are a change of basis; None when unchecked
    method: str = METHOD
    missing: Coded | None = None
    notes: list[Coded] = field(default_factory=list)
    # the same, read from the centre (the samples' median; backlog #167): for a baseline range
    # equal to the two above; for a shocked range, measured from the shocked p50
    revenue_vs_center: dict | None = None  # the band is centre × (1 + x)
    ebit_vs_center: dict | None = None  # (band − EBIT centre) / revenue centre


@dataclass(frozen=True)
class Quarter:
    period: str  # the run's label, e.g. FY2026Q3
    horizon: int  # 1 for the run's first forecast quarter
    revenue_forecast: float  # the baseline's
    ebit_forecast: float
    bands: list[Band]
    revenue_center: float  # median of the samples the misses are applied to: the forecast
    ebit_center: float  # for a baseline range, the simulation's p50 for a shocked one


@dataclass(frozen=True)
class Cell:
    """How M9's range has done so far, for one pool, scope and item."""

    pool: str
    scope: str  # all (every company) or company (this run's company)
    item: str
    inside: int
    below: int
    above: int
    n: int  # rows: origin × horizon; one target quarter is scored by several origins
    n_quarters: int  # distinct company and fiscal quarter
    n_clusters: int  # distinct calendar quarters, the bootstrap's clusters
    share: float | None
    interval: list[float] | None  # 90% cluster bootstrap by calendar quarter (M9's)
    target: float
    acceptable: list[float]
    verdict: str | None  # held, too_narrow, too_wide; None with a gap
    target_in_interval: bool | None
    differs_from_all: bool | None  # company cells only
    width: float | None  # median (p90 − p10) / p50; EBIT over the revenue p50
    basis_changes: int | None  # company cells; None when unchecked
    basis_changes_outside: int | None
    origins_from: date
    missing: Coded | None = None
    notes: list[Coded] = field(default_factory=list)


@dataclass(frozen=True)
class RunRanges:
    run_id: str
    ticker: str
    as_of: date
    currency: str
    basis: str  # baseline or shocked
    sim_id: str | None  # the simulation whose samples a shocked range is built on
    n_samples: int
    errors_sha256: str
    errors_filed_to: date | None
    quarters: list[Quarter]
    coverage: list[Cell]
    notes: list[Coded]

    def to_dict(self) -> dict:
        return _plain(asdict(self))


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


KEYS = ("p10", "p50", "p90")


def _pcts(band: tuple[float, float, float] | None) -> dict | None:
    return None if band is None else dict(zip(KEYS, band, strict=True))


def vs_forecast(
    revenue: dict | None, ebit: dict | None, revenue_forecast: float, ebit_forecast: float
) -> tuple[dict | None, dict | None]:
    """A band as a change from the forecast: revenue as a growth (band = forecast × (1 + x)),
    EBIT in margin points of forecast revenue."""
    if revenue is None or ebit is None:
        return None, None
    return (
        {k: fm.growth(revenue[k], revenue_forecast) for k in KEYS},
        {k: fm.ratio(ebit[k] - ebit_forecast, revenue_forecast) for k in KEYS},
    )


def _no_history(h: int, pool: str, n_errors: int) -> Coded:
    need = R.MIN_ERRORS[pool]
    return Coded(
        "no_history",
        {"horizon": h, "pool": pool, "n_errors": n_errors, "min_errors": need},
        f"quarter {h}: {n_errors} past misses known in the {pool} pool, fewer than the {need} "
        "a range needs",
    )


def _beyond(h: int) -> Coded:
    return Coded(
        "beyond_horizon",
        {"horizon": h, "max_horizon": MAX_HORIZON},
        f"quarter {h}: past misses are measured for the first {MAX_HORIZON} quarters only",
    )


def _unchecked(ticker: str) -> Coded:
    return Coded(
        "basis_unchecked",
        {"checked": ticker},
        f"changes of reporting basis are counted for {ticker} only; other companies' misses may "
        "include some, scored as misses (backlog #162)",
    )


COVERAGE_SKIPPED = Coded(
    "coverage_skipped",
    {},
    "the track record was not computed for this call (it is the baseline range's either way)",
)


def _shocked_note(sim_id: str) -> Coded:
    return Coded(
        "shocked_plus_misses",
        {"sim_id": sim_id},
        "the range adds the baseline's past misses to each shocked sample of the simulation; the "
        "shocks mostly move where the band sits. When a shock captures an event the baseline "
        "would have missed, part of that miss is counted twice, which can widen the band a little",
    )


def _stale(on: date, newest: date) -> Coded:
    return Coded(
        "errors_stale",
        {"as_of": on.isoformat(), "errors_filed_to": newest.isoformat()},
        f"the stored misses end with actuals filed on {newest}; any filed after that and by "
        f"{on} are not in the range yet (they come with the next rebuild of the misses)",
    )


COVERAGE_IS_BASELINE = Coded(
    "coverage_is_baseline",
    {"basis": BASIS},
    "the track record is the baseline range's: past ranges were tested without shocks",
)


BASELINE_ONLY = Coded(
    "baseline_only",
    {"basis": BASIS},
    "the range shows how far the baseline forecast has missed before; it does not include news "
    "or other shocks, so it is not the whole uncertainty",
)
HORIZONS_POOLED = Coded(
    "horizons_pooled",
    {"horizons": list(R.HORIZONS)},
    "the track record counts quarters 1 to 4 together; M9 found it about the same at each",
)


def centers(samples: dict[int, tuple[np.ndarray, np.ndarray]]) -> dict[int, tuple[float, float]]:
    """The median revenue and EBIT of each horizon's samples (M9's `forecast` of a variant)."""
    return {h: (float(np.median(r)), float(np.median(e))) for h, (r, e) in samples.items()}


def bands(
    forecasts: dict[int, tuple[float, float]],
    pairs: list[R.ErrorPair],
    on: date,
    ticker: str,
    subject_id: str,
    n: int = DEFAULT_SAMPLES,
    flags: set[tuple[str, str, str]] | None = None,
    samples: dict[int, tuple[np.ndarray, np.ndarray]] | None = None,
    basis: str = BASIS,
) -> dict[int, list[Band]]:
    """Both pools' bands per horizon 1–4, as M9 builds a subject's (`ranges.subject_rows`).
    `flags` holds this company's basis changes as (origin id, period, item). Without `samples`
    the misses are applied to the forecasts repeated n times (the baseline range); with them,
    to each sample, and the change from the forecast is read from the samples' median. The
    seed key is `<subject_id>:<basis>`."""
    if samples is None:
        samples = R.constant_samples(forecasts, n)
        middle = forecasts
    else:
        middle = centers(samples)
    out: dict[int, list[Band]] = {h: [] for h in forecasts}
    for pool in R.POOLS:
        seed = R.range_seed(f"{subject_id}:{basis}", pool)
        for h, r in sorted(R.ranges(samples, pairs, on, pool, ticker, seed, n).items()):
            revenue, ebit = _pcts(r.revenue), _pcts(r.ebit)
            rev_vs, ebit_vs = vs_forecast(revenue, ebit, *forecasts[h])
            rev_vc, ebit_vc = vs_forecast(revenue, ebit, *middle[h])
            changes, notes = None, []
            if pool == "own" and flags is not None:
                changes = sum(
                    any((p.origin_id, p.period, i) in flags for i in ITEMS)
                    for p in R.known(pairs, on, h, pool, ticker)
                )
            else:
                notes.append(_unchecked(ticker))
            out[h].append(Band(pool, r.n_errors, r.n_quarters, revenue, ebit, rev_vs, ebit_vs,
                               changes, METHOD, None if r.ok else _no_history(h, pool, r.n_errors),
                               notes, rev_vc, ebit_vc))  # fmt: skip
    return out


def basis_flags(conn: sqlite3.Connection, ticker: str, on: date) -> set[tuple[str, str, str]]:
    """This company's origin quarters whose reporting filing recast the year before
    (`hindsight` `restated_basis`, v0.9.7), with the filings public by `on`: (origin, period,
    item)."""
    from domains.evaluation.hindsight import FactReads, against_actuals

    reads = FactReads(conn)  # every origin of the company reads the same filings (#252)
    out = set()
    for o in conn.execute(
        "SELECT origin_id, run_id FROM forecast_origins WHERE ticker = ? AND status = 'ok' "
        "AND as_of < ? ORDER BY origin_id",
        (ticker, on.isoformat()),
    ).fetchall():
        for q in against_actuals(conn, o["run_id"], on, reads).quarters[:MAX_HORIZON]:
            for item in q.items:
                if item.missing is not None and item.missing.code == "restated_basis":
                    out.add((o["origin_id"], q.period, item.name))
    return out


def scored_origin_rows(
    conn: sqlite3.Connection, on: date, pairs: list[R.ErrorPair], n: int = DEFAULT_SAMPLES
) -> list[dict]:
    """M9's rolling-test rows cut at `on`: baseline ranges of the origins dated ROLLING_FROM or
    later and before `on`, each from the misses known on its own date, scored only where the
    item's actual was filed by `on`. Each row gains `ticker`."""
    query = "SELECT origin_id, horizon, item, actual_filed_at FROM baseline_errors"
    filed = {(r["origin_id"], r["horizon"], r["item"]): r["actual_filed_at"]
             for r in conn.execute(query)}  # fmt: skip
    out = []
    for s in R.origin_subjects(conn):
        if not (R.ROLLING_FROM <= s.as_of < on):
            continue
        for row in R.subject_rows(s, pairs, {BASIS: R.baseline_samples(s, n)}, n):
            when = filed.get((s.subject_id, row["horizon"], row["item"]))
            if row["status"] == "ok" and when and date.fromisoformat(when) <= on:
                out.append(row | {"ticker": s.ticker})
    return out


def verdict(share: float | None) -> str | None:
    if share is None:
        return None
    if share < ACCEPTABLE[0]:
        return "too_narrow"
    return "too_wide" if share > ACCEPTABLE[1] else "held"


def coverage_cells(
    rows: list[dict], ticker: str, on: date, flags: set[tuple[str, str, str]] | None = None
) -> list[Cell]:
    """Inside, below and above p10–p90, per pool, scope (all companies, this one) and item."""
    cells: list[Cell] = []
    for pool in R.POOLS:
        alls: dict[str, float | None] = {}
        for scope in SCOPES:
            mine = [r for r in rows if r["pool"] == pool
                    and (scope == "all" or r["ticker"] == ticker)]  # fmt: skip
            width = RR.widths(mine)
            for item in ITEMS:
                rs = [r for r in mine if r["item"] == item]
                c = cover(rs)
                quarters = len({(r["ticker"], r["period"]) for r in rs})
                clusters = len({RR.calendar_quarter(r["period_end"]) for r in rs})
                missing = None
                if on <= R.ROLLING_FROM:
                    missing = Coded(
                        "no_coverage_history",
                        {"origins_from": R.ROLLING_FROM.isoformat(), "as_of": on.isoformat()},
                        f"the range's track record starts with forecasts made from "
                        f"{R.ROLLING_FROM}; none was made before {on}",
                    )
                elif quarters < MIN_QUARTERS:
                    missing = Coded(
                        "few_scored",
                        {"n": c.n, "n_quarters": quarters, "min_quarters": MIN_QUARTERS},
                        f"only {quarters} past quarters to check the range on, fewer than "
                        f"{MIN_QUARTERS}: the share means little",
                    )
                iv = RR.cluster_bootstrap(rs)
                share = c.share
                if scope == "all":
                    alls[item] = share
                differs = None
                judged = not missing and iv is not None
                if scope == "company" and judged and alls.get(item) is not None:
                    differs = not (iv[0] <= alls[item] <= iv[1])
                changes = outside = None
                notes = []
                if scope == "company" and flags is not None:
                    hit = [r for r in rs if (r["subject_id"], r["period"], item) in flags]
                    changes = len(hit)
                    outside = sum(not RR.is_inside(r) for r in hit)
                elif scope == "all":
                    notes.append(_unchecked(ticker))
                cells.append(Cell(
                    pool, scope, item, c.inside, c.below, c.above, c.n, quarters, clusters,
                    share, list(iv) if iv else None, TARGET, list(ACCEPTABLE),
                    None if missing else verdict(share),
                    None if missing or iv is None else iv[0] <= TARGET <= iv[1],
                    differs, width[item], changes, outside, R.ROLLING_FROM, missing, notes,
                ))  # fmt: skip
    return cells


def simulation_samples(
    conn: sqlite3.Connection, run_id: str, sim_id: str, periods: list[str]
) -> tuple[int, dict[int, tuple[np.ndarray, np.ndarray]]]:
    """The stored simulation's sample count and its shocked revenue and EBIT samples for every
    forecast quarter (horizon 1 up), drawn again from its stored shocks and seed
    (`montecarlo.sample_lines`)."""
    sim = conn.execute(
        "SELECT run_id, seed, n_samples FROM simulations WHERE sim_id = ?", (sim_id,)
    ).fetchone()
    if sim is None:
        raise EvaluationError(f"simulation {sim_id} is not stored")
    if sim["run_id"] != run_id:
        raise EvaluationError(f"simulation {sim_id} is of run {sim['run_id']}, not {run_id}")
    n = sim["n_samples"]
    lines = sample_lines(
        load_assumptions(conn, run_id), load_simulation_shocks(conn, sim_id), n, sim["seed"]
    )
    samples = {
        h: (lines[("revenue", p)], lines[("ebit", p)]) for h, p in enumerate(periods, start=1)
    }
    return n, samples


def run_ranges(
    conn: sqlite3.Connection,
    run_id: str,
    n: int = DEFAULT_SAMPLES,
    check_basis: bool = True,
    sim_id: str | None = None,
    coverage: bool = True,
) -> RunRanges:
    """The range of each forecast quarter of `run_id` and the range's track record, as of the
    run's own date. `check_basis` runs the change-of-basis count on the run's company. With
    `sim_id` (a simulation of this run), the range is built on its shocked samples, with its own
    sample count in place of `n` (backlog #167). `coverage=False` skips the track record."""
    run = conn.execute(
        "SELECT ticker, as_of, code_version FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise EvaluationError(f"run {run_id} is not stored")
    ticker, on = run["ticker"], date.fromisoformat(run["as_of"])
    outputs = load_outputs(conn, run_id)
    periods = sorted(p for (name, p) in outputs if name == "revenue" and p not in YEARS)
    samples, basis, subject, coverage_n = None, BASIS, run_id, n
    if sim_id is not None:
        n, samples = simulation_samples(conn, run_id, sim_id, periods)
        basis, subject = SHOCKED, sim_id
    pairs = R.load_pairs(conn)
    known = [p for p in pairs if p.filed_at <= on]
    flags = basis_flags(conn, ticker, on) if check_basis else None
    forecasts = {
        h: (outputs[("revenue", p)], outputs[("ebit", p)])
        for h, p in enumerate(periods, start=1)
        if h <= MAX_HORIZON
    }
    banded = None if samples is None else {h: samples[h] for h in forecasts}
    by_h = bands(forecasts, known, on, ticker, subject, n, flags, banded, basis)
    middle = forecasts if samples is None else centers(samples)
    quarters = []
    for h, p in enumerate(periods, start=1):
        bs = by_h.get(h) or [
            Band(pool, 0, 0, None, None, None, None, None, METHOD, _beyond(h)) for pool in R.POOLS
        ]
        rev, ebit = outputs[("revenue", p)], outputs[("ebit", p)]
        center = middle.get(h, (rev, ebit))
        quarters.append(Quarter(p, h, rev, ebit, bs, *center))
    cells = []
    if coverage:
        rows = scored_origin_rows(conn, on, pairs, coverage_n)  # the baseline's, as asked
        cells = coverage_cells(rows, ticker, on, flags)
    if sim_id is None:
        notes = [BASELINE_ONLY, HORIZONS_POOLED]
    else:
        notes = [_shocked_note(sim_id), COVERAGE_IS_BASELINE, HORIZONS_POOLED]
    if not coverage:
        notes.append(COVERAGE_SKIPPED)
    newest = max((p.filed_at for p in pairs), default=None)
    if newest is not None and on > newest:
        notes.append(_stale(on, newest))
    versions = sorted({r[0] for r in conn.execute(
        "SELECT DISTINCT code_version FROM forecast_origins WHERE status = 'ok'")})  # fmt: skip
    if versions and run["code_version"] not in versions:
        notes.append(Coded(
            "code_differs",
            {"run_code_version": run["code_version"], "origins_code_versions": versions},
            f"the run was made with code {run['code_version']}; the past misses are those of the "
            f"baseline built with {', '.join(versions)}",
        ))  # fmt: skip
    return RunRanges(
        run_id, ticker, on, _currency(conn), basis, sim_id, n, R.pairs_sha256(known),
        max((p.filed_at for p in known), default=None), quarters, cells, notes,
    )  # fmt: skip


# -- text --------------------------------------------------------------------------------------


def _m(value: float | None) -> str:
    return "–" if value is None else f"{value / 1e6:,.0f}"


def _p(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def render(r: RunRanges) -> str:
    """The call as text: a table per pool, the track record and the notes."""
    out = [
        f"{r.ticker} run {r.run_id}"
        + (f", simulation {r.sim_id}" if r.sim_id else "")
        + f" as of {r.as_of}: p10–p90 range of the {r.basis} forecast "
        f"from past misses filed by {r.as_of} (newest {r.errors_filed_to}); {r.currency} millions",
    ]
    for i, pool in enumerate(R.POOLS):
        whose = "every company" if pool == "pooled" else f"{r.ticker} only"
        out += ["", f"{pool} pool (past misses of {whose})",
                "| Quarter | Revenue | p10 | p50 | p90 | EBIT | p10 | p50 | p90 | Misses |",
                "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for q in r.quarters:
            b = q.bands[i]
            rev, ebit = b.revenue or {}, b.ebit or {}
            out.append(
                f"| {q.period} | {_m(q.revenue_forecast)} | "
                + " | ".join(_m(rev.get(k)) for k in KEYS)
                + f" | {_m(q.ebit_forecast)} | "
                + " | ".join(_m(ebit.get(k)) for k in KEYS)
                + f" | {b.n_errors if b.missing is None else b.missing.code} |"
            )
    out += ["", f"Track record: share of past quarters inside their p10–p90 (target "
            f"{TARGET:.0%}, acceptable {ACCEPTABLE[0]:.0%}–{ACCEPTABLE[1]:.0%}), forecasts made "
            f"from {R.ROLLING_FROM} to before {r.as_of}"]  # fmt: skip
    for c in r.coverage:
        who = "all companies" if c.scope == "all" else r.ticker
        iv = f"{_p(c.interval[0])}–{_p(c.interval[1])}" if c.interval else "–"
        line = (f"- {c.pool} range, {c.item}, {who}: {_p(c.share)} inside ({c.inside} of {c.n} "
                f"rows, {c.n_quarters} quarters; {c.below} below, {c.above} above), 90% interval "
                f"{iv}, {c.missing.code if c.missing else c.verdict}")  # fmt: skip
        if c.basis_changes:
            line += (f"; {c.basis_changes} rows are changes of basis "
                     f"({c.basis_changes_outside} outside)")  # fmt: skip
        out.append(line)
    out += ["", *[f"Note: {n.text}" for n in r.notes]]
    if any(n.code == "basis_unchecked" for c in r.coverage for n in c.notes):
        out.append(f"Note: {_unchecked(r.ticker).text}")
    return "\n".join(out) + "\n"
