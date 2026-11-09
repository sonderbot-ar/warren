"""A company's forecast track record (backlog #145, front-end R4, brief question 6).

How well has Warren forecast this company? From M9's monthly origins (`forecast_origins`,
`baseline_errors`), as of a date D: every past forecast quarter beside its first-reported
actual, the miss, the seasonal random walk's miss (M3's benchmark: the same quarter a year
earlier, as known when the forecast was made), and whether M9's p10–p90 range held the actual.
Monthly origins repeat a forecast until a filing lands, so each target quarter and horizon is
one row, from the first origin that made it. Then summaries per item and horizon, with a sign
test against the benchmark and the range's coverage beside all companies'. Nothing is written;
gaps are coded, never raised. Design: docs/designs/backlog-145-track-record.md.
"""

import re
import sqlite3
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

from domains.analysis.math_engine import CHAINS, step_quarter
from domains.analysis.montecarlo import DEFAULT_SAMPLES, _currency
from domains.analysis.reported import Coded
from domains.analysis.runs import load_assumptions
from domains.evaluation import ranges as R
from domains.evaluation import ranges_report as RR
from domains.evaluation import run_ranges as RN
from domains.evaluation.backtest import sign_test
from domains.evaluation.harness import (
    BASIS_TOLERANCE,
    EvaluationError,
    _alternative,
    comparative,
    label,
    parse_label,
    score,
)
from domains.evaluation.hindsight import MISS_UNITS, FactReads
from shared_kernel.calendar import last_ended_day

ITEMS = ("revenue", "ebit")
QUARTER_LABEL = re.compile(r"FY\d{4}Q[1-4]")
MIN_QUARTERS = 12  # distinct target quarters, else `few_quarters` / `few_scored` (M9's own minimum)
SIGN_ALPHA = 0.05
TIE = 1e-12  # absolute misses this close are a tie
MIN_CHANGES = 4  # seasonal changes the drift benchmark needs (one year), else `no_drift`
WILSON_Z = 1.6448536269514722  # the 90% two-sided normal quantile, the bootstrap's level
TARGET = RN.TARGET
ACCEPTABLE = RN.ACCEPTABLE


@dataclass(frozen=True)
class RangeHeld:
    made_on: date | None  # the origin whose range this is: the group's first in M9's test
    p10: float | None
    p90: float | None
    held: str | None  # inside, below, above; None with a gap
    missing: Coded | None = None


@dataclass(frozen=True)
class DriftRow:
    """Foster's (1977) seasonal random walk with drift: Q(t−4) + δ, δ the mean seasonal change
    in the origin run's own history (backlog #188)."""

    forecast: float | None
    step: float | None  # δ in money: the mean of Q(s) − Q(s−4) over the run's history
    n_changes: int  # seasonal changes behind δ
    miss: float | None
    signed_miss: float | None  # positive: the benchmark forecast too high
    closer: str | None  # warren, benchmark, tie; None without a forecast
    missing: Coded | None = None
    left_out: list[str] = field(default_factory=list)  # quarters s whose change spans two bases
    basis_checked: bool = False  # the changes were checked for a change of basis


@dataclass(frozen=True)
class ItemRow:
    forecast: float
    actual: float
    filed_at: date
    miss: float  # |forecast − actual| / |actual|; EBIT over |actual revenue| (miss_unit)
    signed_miss: float  # (forecast − actual) / scale: positive means Warren forecast too high
    miss_unit: str  # fraction_of_actual (revenue), fraction_of_actual_revenue (EBIT), as v0.9.7
    benchmark_forecast: float | None
    benchmark_miss: float | None
    benchmark_signed_miss: float | None
    closer: str | None  # warren, benchmark, tie; None without a benchmark
    ranges: dict[str, RangeHeld]
    benchmark_missing: Coded | None = None
    drift: DriftRow | None = None


@dataclass(frozen=True)
class Row:
    period: str
    period_end: str | None
    horizon: int
    made_on: date  # the earliest origin that made this forecast
    origin_id: str
    run_id: str
    n_origins: int  # monthly origins before D that repeated it
    basis_change: bool | None  # the quarter's filing recast the year before; None unchecked
    items: dict[str, ItemRow]


@dataclass(frozen=True)
class RangeCell:
    """How the range of one pool did on the company's rows of one summary cell."""

    inside: int
    below: int  # the actual fell below p10: Warren's range was too high
    above: int
    n_rows: int  # quarter-and-horizon rows scored
    n_quarters: int  # distinct target quarters among them
    n_clusters: int  # distinct calendar quarters, the bootstrap's clusters
    share: float | None
    interval: list[float] | None  # 90% cluster bootstrap by calendar quarter (M9's)
    target: float
    acceptable: list[float]
    verdict: str | None  # held, too_narrow, too_wide; None with a gap
    target_in_interval: bool | None
    width: float | None  # median (p90 − p10) / p50; EBIT over the revenue p50 (#144's)
    others_share: float | None  # the other companies' share, deduplicated the same way
    differs_from_others: bool | None  # others_share outside this company's interval
    share_by_origin: float | None  # M9's and #144's count: every monthly origin a row
    basis_changes: int | None
    basis_changes_outside: int | None
    missing: Coded | None = None
    notes: list[Coded] = field(default_factory=list)
    wilson_interval: list[float] | None = None  # 90% Wilson score, n = wilson_n (#188)
    wilson_n: int | None = None  # the calendar-quarter clusters, each taken as one draw


@dataclass(frozen=True)
class DriftSummary:
    """The drift benchmark's record over a summary cell, under the same test rules."""

    n_rows: int  # rows with a drift forecast
    median_miss: float | None
    mean_miss: float | None
    skill: float | None  # 1 − Warren's mean miss / the drift benchmark's, on the same rows
    wins: int
    losses: int
    ties: int
    sign_p: float | None
    verdict: str | None
    missing: Coded | None = None


@dataclass(frozen=True)
class Summary:
    item: str
    horizon: int | None  # None: horizons 1–4 together, tested per target quarter
    miss_unit: str
    n_rows: int
    n_quarters: int  # distinct target quarters
    median_miss: float | None  # absolute misses, in miss_unit
    mean_miss: float | None
    benchmark_median_miss: float | None
    benchmark_mean_miss: float | None
    skill: float | None  # 1 − mean miss / benchmark mean miss (relative MAE); > 0 beats it
    wins: int  # Warren closer (per target quarter when horizon is None)
    losses: int  # benchmark closer
    ties: int
    sign_p: float | None
    verdict: str | None  # warren_better, benchmark_better, not_shown; None at h ≥ 2
    basis_changes: int | None
    ranges: dict[str, RangeCell]
    missing: Coded | None = None
    notes: list[Coded] = field(default_factory=list)
    drift: DriftSummary | None = None


@dataclass(frozen=True)
class TrackRecord:
    ticker: str
    as_of: date
    as_of_default: bool
    currency: str
    errors_sha256: str
    headline: dict  # which summary cell the screen leads with
    rows: list[Row]
    summaries: list[Summary]
    notes: list[Coded]
    missing: Coded | None = None

    def to_dict(self) -> dict:
        return RN._plain(asdict(self))


# -- codes -------------------------------------------------------------------------------------

BENCHMARK_IS_SRW = Coded(
    "benchmark_is_srw", {},
    "the benchmark is the same quarter a year earlier, as known when the forecast was made",
)  # fmt: skip
BENCHMARK_WITH_DRIFT = Coded(
    "benchmark_with_drift", {"min_changes": MIN_CHANGES},
    "a second benchmark adds growth: the same quarter a year earlier plus the average "
    "year-on-year change of the quarters known when the forecast was made",
)  # fmt: skip
BASELINE_ONLY = Coded(
    "baseline_only", {},
    "these are the baseline's own forecasts and ranges, without news shocks",
)  # fmt: skip
HEADLINE_CELL = {"horizon": None, "pool": "pooled"}
HEADLINE = Coded(
    "headline", HEADLINE_CELL,
    "the headline is all horizons together and the pooled range, the range the forecast screen "
    "shows; the other cells are detail",
)  # fmt: skip
CASES_NOT_INCLUDED = Coded(
    "cases_not_included", {},
    "the event case library is not included: its dates were chosen around events, so they are "
    "not a fair sample of the company",
)  # fmt: skip


def _warm_up(made_on: date) -> Coded:
    return Coded(
        "warm_up", {"made_on": made_on.isoformat(), "origins_from": R.ROLLING_FROM.isoformat()},
        f"ranges are scored for forecasts made from {R.ROLLING_FROM}; earlier ones build the "
        f"history",
    )  # fmt: skip


def _no_history(pool: str) -> Coded:
    return Coded(
        "no_history", {"pool": pool, "min_errors": R.MIN_ERRORS[pool]},
        f"too few past misses in the {pool} pool on that date for a range",
    )  # fmt: skip


def _no_benchmark(period: str) -> Coded:
    year, quarter = parse_label(period)
    prior = label(*step_quarter(year, quarter, -4))
    return Coded(
        "no_benchmark", {"period": period, "prior": prior},
        f"the forecast's run holds no figure for {prior}, the year before: no benchmark",
    )  # fmt: skip


def _no_drift(period: str, n: int) -> Coded:
    return Coded(
        "no_drift", {"period": period, "n_changes": n, "min_changes": MIN_CHANGES},
        f"the forecast's run holds {n} year-on-year changes, fewer than {MIN_CHANGES}: no "
        f"benchmark with drift for {period}",
    )  # fmt: skip


def _few(code: str, n: int) -> Coded:
    return Coded(
        code, {"n_quarters": n, "min_quarters": MIN_QUARTERS},
        f"only {n} past quarters, fewer than {MIN_QUARTERS}: the figure means little",
    )  # fmt: skip


# -- rows --------------------------------------------------------------------------------------


def _group_rows(conn: sqlite3.Connection, ticker: str, on: date) -> dict[tuple, list]:
    """Revenue and EBIT error rows of the company's ok origins dated before `on`, both ok and
    both filed by `on`, grouped by (period, horizon), earliest origin first."""
    rows = conn.execute(
        "SELECT r.origin_id, o.as_of, o.run_id, r.horizon, r.period, r.period_end, "
        "r.forecast AS rf, r.actual AS ra, r.actual_filed_at AS rfiled, "
        "e.forecast AS ef, e.actual AS ea, e.actual_revenue AS ear, e.actual_filed_at AS efiled "
        "FROM baseline_errors r JOIN baseline_errors e ON e.origin_id = r.origin_id "
        "AND e.horizon = r.horizon AND e.item = 'ebit' "
        "JOIN forecast_origins o ON o.origin_id = r.origin_id "
        "WHERE r.item = 'revenue' AND r.status = 'ok' AND e.status = 'ok' AND o.status = 'ok' "
        "AND o.ticker = ? AND o.as_of < ? ORDER BY o.as_of, r.horizon",
        (ticker, on.isoformat()),
    ).fetchall()
    out: dict[tuple, list] = {}
    for r in rows:
        filed = max(date.fromisoformat(r["rfiled"]), date.fromisoformat(r["efiled"]))
        if filed <= on:
            out.setdefault((r["period"], r["horizon"]), []).append(r)
    return out


def history(conn: sqlite3.Connection, run_id: str) -> dict[str, dict[tuple[int, int], float]]:
    """The run's own history rows per item, keyed by (fiscal year, quarter): what it knew."""
    return _history(conn, run_id)[0]


def _history(conn: sqlite3.Connection, run_id: str) -> tuple[dict, dict[tuple[int, int], int]]:
    """`history`, and the EBIT definition (`harness._alternative`) of each EBIT history row."""
    out: dict[str, dict[tuple[int, int], float]] = {item: {} for item in ITEMS}
    alts: dict[tuple[int, int], int] = {}
    for a in load_assumptions(conn, run_id):
        item = a.name.removeprefix("history:")
        quarter = QUARTER_LABEL.fullmatch(a.period or "")
        # a run also holds fiscal-year history rows (FY2016): only quarters are seasonal
        if a.name.startswith("history:") and item in out and a.value is not None and quarter:
            out[item][parse_label(a.period)] = a.value
            if item == "ebit":
                alts[parse_label(a.period)] = _alternative(a.method)
    return out, alts


def mixed_pairs(
    reads: FactReads, cik: str, run_as_of: date, hist: dict, alts: dict[tuple[int, int], int]
) -> dict[str, set[tuple[int, int]]]:
    """Per item, the quarters s whose seasonal change Q(s) − Q(s−4) in the run's history may
    span two bases. F is the filing that first reported s (known on the run's date); the pair
    is mixed when the run's Q(s) differs from F's by more than BASIS_TOLERANCE (s was recast
    later, so it no longer sits beside the s−4 that F printed), when F gives s−4 a value that
    far from the run's (v0.9.7's test, `hindsight`), or, for EBIT, when the two quarters were
    built on different EBIT definitions. A pair that can't be checked (s not found as first
    reported, a comparative derived across vintages) is kept, as v0.9.7 keeps such a quarter."""
    out: dict[str, set[tuple[int, int]]] = {item: set() for item in ITEMS}
    first = reads.quarterly(cik, run_as_of, "first_reported")

    def off(a: float | None, b: float | None) -> bool:
        return a is not None and b is not None and b != 0 and abs(a - b) / abs(b) > BASIS_TOLERANCE

    for s in sorted(hist["revenue"].keys() | hist["ebit"].keys()):
        prior = step_quarter(*s, -4)
        alt = alts.get(s, 0)
        f0 = first.get(("revenue", s[0], f"Q{s[1]}"))
        if f0 is None:
            reported, comp = (None, None), (None, None)
        else:
            ebit = [first.get((n, s[0], f"Q{s[1]}")) for n in CHAINS["ebit"][alt]]
            reported = (f0.value, sum(f.value for f in ebit) if all(ebit) else None)
            comp = comparative(reads.quarterly(cik, f0.filed_at, "latest"), *s, alt)
        for idx, item in enumerate(ITEMS):
            if s not in hist[item] or prior not in hist[item]:
                continue
            if item == "ebit" and alts.get(prior, 0) != alt:
                out[item].add(s)
            elif off(hist[item][s], reported[idx]) or off(comp[idx], hist[item][prior]):
                out[item].add(s)
    return out


def benchmark(conn: sqlite3.Connection, run_id: str, period: str) -> dict[str, float | None]:
    """M3's seasonal random walk for `period`: the run's own history rows a year earlier."""
    prior = step_quarter(*parse_label(period), -4)
    return {item: h.get(prior) for item, h in history(conn, run_id).items()}


def drift_forecast(
    known: dict[tuple[int, int], float], period: str, skip: set[tuple[int, int]] = frozenset()
) -> tuple[float | None, float | None, int]:
    """The seasonal random walk with drift (one of Foster's 1977 models) for `period` from one
    item's history `known`: (Q(t−4) + δ, δ, n), δ the mean of Q(s) − Q(s−4) over every s in
    `known` whose year-earlier quarter is there too, less the quarters in `skip` (changes that
    span two bases). Forecast and δ are None under MIN_CHANGES changes or without Q(t−4)."""
    changes = [v - known[q] for s, v in sorted(known.items())
               if (q := step_quarter(*s, -4)) in known and s not in skip]  # fmt: skip
    base = known.get(step_quarter(*parse_label(period), -4))
    if len(changes) < MIN_CHANGES or base is None:
        return None, None, len(changes)
    delta = statistics.fmean(changes)
    return base + delta, delta, len(changes)


def _drift_row(
    known: dict[tuple[int, int], float],
    period: str,
    act: float,
    scale: float,
    warren: float,
    item: str,
    skip: set[tuple[int, int]] | None,
) -> DriftRow:
    """`skip`: the changes left out for spanning two bases; None when not checked."""
    fc, delta, n = drift_forecast(known, period, skip or frozenset())
    left = sorted(label(*s) for s in skip or ())
    if fc is None:
        gap = _no_drift(period, n) if step_quarter(*parse_label(period), -4) in known else (
            _no_benchmark(period))  # fmt: skip
        return DriftRow(None, None, n, None, None, None, gap, left, skip is not None)
    signed = score(item, fc, act, scale)[1]
    return DriftRow(fc, delta, n, abs(signed), signed, _closer(warren, abs(signed)), None, left,
                    skip is not None)  # fmt: skip


def _closer(warren: float, bench: float | None) -> str | None:
    if bench is None:
        return None
    if abs(warren - bench) <= TIE:
        return "tie"
    return "warren" if warren < bench else "benchmark"


def _held(r: dict | None, last_made: date, pool: str) -> RangeHeld:
    """M9's range row for a group; `last_made`: its latest origin (warm-up when before
    ROLLING_FROM, so no origin of the group was in the rolling test)."""
    if last_made < R.ROLLING_FROM:
        return RangeHeld(None, None, None, None, _warm_up(last_made))
    if r is None or r["p10"] is None:
        return RangeHeld(None, None, None, None, _no_history(pool))
    a = r["actual"]
    held = "below" if a < r["p10"] else "above" if a > r["p90"] else "inside"
    return RangeHeld(date.fromisoformat(r["as_of"]), r["p10"], r["p90"], held)


def _range_index(scored: list[dict], ticker: str) -> dict[tuple, dict]:
    """(period, horizon, pool, item) -> the company's deduplicated M9 range row: the earliest
    origin of the group that M9's rolling test scored (from ROLLING_FROM on)."""
    return {(r["period"], r["horizon"], r["pool"], r["item"]): r
            for r in scored if r["ticker"] == ticker}  # fmt: skip


def rows_for(
    conn: sqlite3.Connection,
    ticker: str,
    on: date,
    index: dict[tuple, dict],
    flags: set[tuple[str, str, str]] | None,
    reads: FactReads | None = None,
) -> list[Row]:
    """One row per target quarter and horizon, from the earliest origin that made it. With
    `reads` (when the basis is checked), the drift benchmark leaves out changes that span two
    bases (`mixed_pairs`)."""
    out = []
    hist_cache: dict[str, tuple] = {}
    for (period, h), group in sorted(_group_rows(conn, ticker, on).items()):
        first = group[0]
        made_on = date.fromisoformat(first["as_of"])
        last_made = date.fromisoformat(group[-1]["as_of"])  # warm-up if before 2021
        if first["run_id"] not in hist_cache:
            hist, alts = _history(conn, first["run_id"])
            mixed = None
            if reads is not None:
                run = conn.execute(
                    "SELECT cik, as_of FROM runs WHERE run_id = ?", (first["run_id"],)
                ).fetchone()
                mixed = mixed_pairs(reads, run["cik"], date.fromisoformat(run["as_of"]), hist,
                                    alts)  # fmt: skip
            hist_cache[first["run_id"]] = (hist, mixed)
        hist, mixed = hist_cache[first["run_id"]]
        prior = step_quarter(*parse_label(period), -4)
        bench = {item: hist[item].get(prior) for item in ITEMS}
        items = {}
        for item, fc, act, scale in (
            ("revenue", first["rf"], first["ra"], first["ra"]),
            ("ebit", first["ef"], first["ea"], first["ear"]),
        ):
            # an ok M9 row has a positive actual revenue (its log miss exists), so `score` can't
            # meet a zero scale here
            _, signed, _ = score(item, fc, act, scale)
            b = bench[item]
            b_signed = score(item, b, act, scale)[1] if b is not None else None
            b_miss = None if b_signed is None else abs(b_signed)
            filed = first["rfiled"] if item == "revenue" else first["efiled"]
            ranges = {
                pool: _held(index.get((period, h, pool, item)), last_made, pool) for pool in R.POOLS
            }
            items[item] = ItemRow(
                fc, act, date.fromisoformat(filed), abs(signed), signed, MISS_UNITS[item], b,
                b_miss, b_signed, _closer(abs(signed), b_miss), ranges,
                None if b is not None else _no_benchmark(period),
                _drift_row(hist[item], period, act, scale, abs(signed), item,
                           None if mixed is None else mixed[item]),
            )  # fmt: skip
        flagged = None
        if flags is not None:
            flagged = any((g["origin_id"], period, i) in flags for g in group for i in ITEMS)
        out.append(Row(period, first["period_end"], h, made_on, first["origin_id"],
                       first["run_id"], len(group), flagged, items))  # fmt: skip
    return out


# -- summaries ---------------------------------------------------------------------------------


def dedup_scored(scored: list[dict]) -> list[dict]:
    """M9's scored rows, one per company, target quarter, horizon, pool and item: the earliest
    origin's (the forecast is the same across a group; its range is the first one built)."""
    best: dict[tuple, dict] = {}
    for r in sorted(scored, key=lambda r: (r["as_of"], r["subject_id"])):
        best.setdefault((r["ticker"], r["period"], r["horizon"], r["pool"], r["item"]), r)
    return list(best.values())


def _many_inside(c: RR.Cover) -> list[Coded]:
    if c.n and c.inside == c.n:
        return [Coded(
            "all_inside", {"n_rows": c.n},
            "every actual fell inside the range, so there is no miss to measure how sure that is: "
            "the interval says nothing; read the width",
        )]  # fmt: skip
    return []


def wilson(share: float, n: int, z: float = WILSON_Z) -> tuple[float, float] | None:
    """Wilson's (1927) score interval for a share `share` out of `n` draws; None with none."""
    if n <= 0:
        return None
    centre = (share + z * z / (2 * n)) / (1 + z * z / n)
    half = z / (1 + z * z / n) * (share * (1 - share) / n + z * z / (4 * n * n)) ** 0.5
    return max(0.0, centre - half), min(1.0, centre + half)


def range_cell(
    mine: list[dict],
    others: list[dict],
    by_origin: list[dict],
    flagged: set[tuple[str, int]] | None,
    width: float | None = None,
) -> RangeCell:
    """`mine`: the company's deduplicated M9 rows for one pool and item; `others`: the other
    companies' deduplicated rows; `by_origin`: the company's rows before deduplication;
    `flagged`: (period, horizon) of basis changes; `width`: #144's width of `mine`."""
    rows = RR.scored(mine)
    c = RR.cover(rows)
    quarters = len({r["period"] for r in rows})
    clusters = len({RR.calendar_quarter(r["period_end"]) for r in rows})
    iv = RR.cluster_bootstrap(rows) if rows else None
    other = RR.cover(RR.scored(others)).share
    missing = _few("few_scored", quarters) if quarters < MIN_QUARTERS else None
    judged = missing is None and iv is not None
    differs = (not (iv[0] <= other <= iv[1])) if judged and other is not None else None
    changes = outside = None
    if flagged is not None:
        hit = [r for r in rows if (r["period"], r["horizon"]) in flagged]
        changes, outside = len(hit), sum(not RR.is_inside(r) for r in hit)
    return RangeCell(
        c.inside, c.below, c.above, c.n, quarters, clusters, c.share, list(iv) if iv else None,
        TARGET, list(ACCEPTABLE), None if missing else RN.verdict(c.share),
        iv[0] <= TARGET <= iv[1] if judged else None, width, other, differs,
        RR.cover(RR.scored(by_origin)).share, changes, outside, missing, _many_inside(c),
        list(w) if (w := wilson(c.share, clusters) if c.share is not None else None) else None,
        clusters if c.share is not None else None,
    )  # fmt: skip


def _diffs(xs: list[tuple[Row, ItemRow]], per_quarter: bool) -> list[float]:
    """|Warren miss| − |benchmark miss|; with `per_quarter`, the mean over a target quarter's
    horizons, so one actual is one test unit (M8: the unit of evidence is not the row)."""
    if not per_quarter:
        return [x.miss - x.benchmark_miss for _, x in xs if x.benchmark_miss is not None]
    by: dict[str, list[float]] = {}
    for r, x in xs:
        if x.benchmark_miss is not None:
            by.setdefault(r.period, []).append(x.miss - x.benchmark_miss)
    return [statistics.fmean(v) for _, v in sorted(by.items())]


OVERLAPPING = Coded(
    "overlapping_horizon", {},
    "forecasts two or more quarters ahead overlap from one quarter to the next, so their misses "
    "are not independent: no verdict is given at this horizon",
)  # fmt: skip
PER_QUARTER = Coded(
    "tested_per_quarter", {},
    "all horizons together: each target quarter counts once in the test, as the mean of its "
    "horizons' differences",
)  # fmt: skip


def _test(ds: list[float], h: int | None, missing: Coded | None):
    """The sign test and its verdict under the track record's rules: a verdict at h1 and over
    all horizons (per target quarter), none at h ≥ 2 or with few quarters."""
    st = sign_test([0.0 if abs(d) <= TIE else d for d in ds])
    verdict = None
    if (h is None or h < 2) and missing is None and st.p is not None:
        verdict = "not_shown"
        if st.p < SIGN_ALPHA:
            verdict = "warren_better" if st.better > st.worse else "benchmark_better"
    return st, verdict


def _drift_diffs(xs: list[tuple[Row, ItemRow]], per_quarter: bool) -> list[float]:
    """As `_diffs`, against the drift benchmark."""
    by: dict[str, list[float]] = {}
    flat = []
    for r, x in xs:
        if x.drift is not None and x.drift.miss is not None:
            d = x.miss - x.drift.miss
            flat.append(d)
            by.setdefault(r.period, []).append(d)
    return [statistics.fmean(v) for _, v in sorted(by.items())] if per_quarter else flat


def drift_summary(xs: list[tuple[Row, ItemRow]], h: int | None) -> DriftSummary:
    """The drift benchmark over one summary cell; skill on the rows that have its forecast."""
    have = [(r, x) for r, x in xs if x.drift is not None and x.drift.miss is not None]
    quarters = len({r.period for r, _ in have})
    missing = _few("few_quarters", quarters) if quarters < MIN_QUARTERS else None
    st, verdict = _test(_drift_diffs(xs, per_quarter=h is None), h, missing)
    bench = [x.drift.miss for _, x in have]
    mean_b = statistics.fmean(bench) if bench else None
    mean_w = statistics.fmean([x.miss for _, x in have]) if have else None
    skill = 1 - mean_w / mean_b if mean_w is not None and mean_b else None
    return DriftSummary(
        len(have), statistics.median(bench) if bench else None, mean_b, skill,
        st.better, st.worse, st.ties, st.p, verdict, missing,
    )  # fmt: skip


def summaries(
    rows: list[Row], ticker: str, scored: list[dict], by_origin: list[dict]
) -> list[Summary]:
    """Per item and horizon (None: all four). `scored`: every company's deduplicated M9 rows;
    `by_origin`: this company's rows before deduplication."""
    out = []
    keep = {(r.period, r.horizon) for r in rows}
    flagged = None
    if all(r.basis_change is not None for r in rows):
        flagged = {(r.period, r.horizon) for r in rows if r.basis_change}
    for item in ITEMS:
        for h in (None, *R.HORIZONS):
            rs = [r for r in rows if h is None or r.horizon == h]
            xs = [(r, r.items[item]) for r in rs]
            warren = [x.miss for _, x in xs]
            bench = [x.benchmark_miss for _, x in xs if x.benchmark_miss is not None]
            quarters = len({r.period for r in rs})
            ds = _diffs(xs, per_quarter=h is None)
            st = sign_test([0.0 if abs(d) <= TIE else d for d in ds])
            missing = _few("few_quarters", quarters) if quarters < MIN_QUARTERS else None
            notes = [RN.HORIZONS_POOLED, PER_QUARTER] if h is None else []
            verdict = None
            if h is not None and h >= 2:
                notes.append(OVERLAPPING)
            elif missing is None and st.p is not None:
                verdict = "not_shown"
                if st.p < SIGN_ALPHA:
                    verdict = "warren_better" if st.better > st.worse else "benchmark_better"
            mean_w = statistics.fmean(warren) if warren else None
            mean_b = statistics.fmean(bench) if bench else None
            skill = 1 - mean_w / mean_b if mean_w is not None and mean_b else None

            def in_h(r: dict, h: int | None = h) -> bool:
                return h is None or r["horizon"] == h

            cells = {}
            for pool in R.POOLS:
                both = [r for r in scored if r["ticker"] == ticker and r["pool"] == pool
                        and in_h(r) and (r["period"], r["horizon"]) in keep]  # fmt: skip
                mine = [r for r in both if r["item"] == item]
                others = [r for r in scored if r["ticker"] != ticker and r["pool"] == pool
                          and r["item"] == item and in_h(r)]  # fmt: skip
                origin = [r for r in by_origin if r["pool"] == pool and r["item"] == item
                          and in_h(r)]  # fmt: skip
                cells[pool] = range_cell(mine, others, origin, flagged, RR.widths(both)[item])
            changes = None if flagged is None else sum((r.period, r.horizon) in flagged for r in rs)
            out.append(Summary(
                item, h, MISS_UNITS[item], len(rs), quarters,
                statistics.median(warren) if warren else None, mean_w,
                statistics.median(bench) if bench else None, mean_b, skill,
                st.better, st.worse, st.ties, st.p, verdict, changes, cells, missing, notes,
                drift_summary(xs, h),
            ))  # fmt: skip
    return out


# -- the call ----------------------------------------------------------------------------------


def track_record(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date | None = None,
    n: int = DEFAULT_SAMPLES,
    check_basis: bool = True,
    now: datetime | None = None,
) -> TrackRecord:
    """The company's track record as of `as_of` (default: the last day ended in New York)."""
    ticker = ticker.upper()
    if conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone() is None:
        raise EvaluationError(f"{ticker} has not been ingested")
    default = as_of is None
    if default:
        as_of = last_ended_day(now or datetime.now(UTC))
    pairs = R.load_pairs(conn)
    known = [p for p in pairs if p.filed_at <= as_of]
    raw = RN.scored_origin_rows(conn, as_of, pairs, n)
    scored = dedup_scored(raw)
    flags = RN.basis_flags(conn, ticker, as_of) if check_basis else None
    reads = FactReads(conn) if check_basis else None
    rows = rows_for(conn, ticker, as_of, _range_index(scored, ticker), flags, reads)
    by_origin = [r for r in raw if r["ticker"] == ticker]
    notes = [
        Coded(
            "deduplicated",
            {"rows": len(rows), "origins": sum(r.n_origins for r in rows)},
            "one row per target quarter and horizon, from the first monthly forecast that made "
            "it; later months repeated the same forecast. The range's share per origin "
            "(share_by_origin) is the count the forecast's own range screen uses",
        ),
        BENCHMARK_IS_SRW,
        BASELINE_ONLY,
        CASES_NOT_INCLUDED,
        HEADLINE,
        BENCHMARK_WITH_DRIFT,
    ]
    versions = sorted({r[0] for r in conn.execute(
        "SELECT DISTINCT code_version FROM forecast_origins WHERE status = 'ok' AND ticker = ? "
        "AND as_of < ?", (ticker, as_of.isoformat()))})  # fmt: skip
    if len(versions) > 1:
        notes.append(Coded(
            "code_differs", {"origins_code_versions": versions},
            f"the past forecasts were made with more than one code version: {', '.join(versions)}",
        ))  # fmt: skip
    failed = conn.execute(
        "SELECT as_of, reason FROM forecast_origins WHERE status = 'failed' AND ticker = ? "
        "AND as_of < ? ORDER BY as_of", (ticker, as_of.isoformat())).fetchall()  # fmt: skip
    if failed:
        notes.append(Coded(
            "origins_failed",
            {"n": len(failed), "first": failed[0]["as_of"], "last": failed[-1]["as_of"],
             "reasons": sorted({f["reason"] for f in failed})},
            f"{len(failed)} monthly forecasts could not be made ({failed[0]['as_of']} to "
            f"{failed[-1]['as_of']}), so the record has fewer quarters",
        ))  # fmt: skip
    missing = None
    if not rows:
        missing = Coded(
            "no_track_record", {"ticker": ticker, "as_of": as_of.isoformat()},
            f"no past forecast of {ticker} has a reported actual by {as_of}",
        )  # fmt: skip
    return TrackRecord(
        ticker, as_of, default, _currency(conn), R.pairs_sha256(known), HEADLINE_CELL, rows,
        summaries(rows, ticker, scored, by_origin) if rows else [], notes, missing,
    )  # fmt: skip


# -- text --------------------------------------------------------------------------------------


def _pct(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def render(t: TrackRecord) -> str:
    """The call as text: the summaries, then each item's quarters, then the notes."""
    when = " (the last day ended in New York)" if t.as_of_default else ""
    out = [f"{t.ticker} track record as of {t.as_of}{when}: monthly baseline forecasts against "
           f"the actuals as first reported; {t.currency} millions"]  # fmt: skip
    if t.missing:
        return "\n".join([*out, "", t.missing.text]) + "\n"
    out += ["", "| Item | Horizon | Quarters | Warren's median miss | Benchmark's | Skill | "
            "Warren closer | Verdict | Pooled range held | Own range held |",
            "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for s in t.summaries:
        cells = []
        for pool in R.POOLS:
            c = s.ranges[pool]
            v = c.missing.code if c.missing else c.verdict
            cells.append(f"{_pct(c.share, 0)} of {c.n_rows} ({v})")
        verdict = s.missing.code if s.missing else (s.verdict or "–")
        out.append(
            f"| {s.item} | {s.horizon or 'all'} | {s.n_quarters} | {_pct(s.median_miss)} | "
            f"{_pct(s.benchmark_median_miss)} | {_pct(s.skill, 0)} | {s.wins} of "
            f"{s.wins + s.losses + s.ties} | {verdict} | {cells[0]} | {cells[1]} |"
        )
    out += ["", "Second benchmark: the same quarter a year earlier plus the average year-on-year "
            "change known then (Foster's seasonal random walk with drift)",
            "| Item | Horizon | Rows | Its median miss | Warren's skill against it | Warren closer "
            "| Verdict | Pooled range, Wilson 90% | Own range, Wilson 90% |",
            "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for s in t.summaries:
        d = s.drift
        verdict = d.missing.code if d.missing else (d.verdict or "–")
        wil = []
        for pool in R.POOLS:
            w = s.ranges[pool].wilson_interval
            wil.append(f"{_pct(w[0], 0)}–{_pct(w[1], 0)}" if w else "–")
        out.append(
            f"| {s.item} | {s.horizon or 'all'} | {d.n_rows} | {_pct(d.median_miss)} | "
            f"{_pct(d.skill, 0)} | {d.wins} of {d.wins + d.losses + d.ties} | {verdict} | "
            f"{wil[0]} | {wil[1]} |"
        )
    for item in ITEMS:
        out += ["", f"{item}: forecast, first-reported actual, miss (+ = forecast too high)",
                "| Quarter | h | Made on | Forecast | Actual | Miss | Benchmark miss | Closer | "
                "Pooled | Own |", "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for r in t.rows:
            x = r.items[item]
            held = [x.ranges[p].held or x.ranges[p].missing.code for p in R.POOLS]
            mark = " *" if r.basis_change else ""
            out.append(
                f"| {r.period}{mark} | {r.horizon} | {r.made_on} | {x.forecast / 1e6:,.0f} | "
                f"{x.actual / 1e6:,.0f} | {_pct(x.signed_miss)} | "
                f"{_pct(x.benchmark_signed_miss)} | {x.closer or '–'} | {held[0]} | {held[1]} |"
            )
    if any(r.basis_change for r in t.rows):
        out += ["", "* the quarter's filing recast the year before (a change of reporting basis)"]
    out += ["", *[f"Note: {n.text}" for n in t.notes]]
    return "\n".join(out) + "\n"
