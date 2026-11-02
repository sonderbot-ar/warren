"""Honest ranges (M9, Decision 7): each forecast quarter's p10–p90 from the baseline's past errors.

The baseline runs on the 1st of every month since 2019-04 for every company ("origins"), and each
forecast quarter's miss against the actual as first reported is stored with the date that actual
was filed. On any date D, the misses filed on or before D are the past errors a range may use: the
forecast with each of them applied, drawn N times, gives the p10, p50 and p90. With shocks, each
shocked sample of the M4 simulation gets one drawn error. Design: docs/designs/m9-honest-ranges.md.

Errors (financial_math): revenue as ln(actual / forecast); EBIT in margin points,
(actual − forecast) / actual revenue. Revenue and EBIT of one quarter share one draw.
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date

import numpy as np

from domains.analysis import financial_math as fm
from domains.analysis.montecarlo import DEFAULT_SAMPLES
from domains.analysis.runs import code_version
from domains.evaluation.cases import Case
from domains.evaluation.harness import (
    EvaluationError,
    evaluate_case,
    guard_coverage,
    scoring_errors,
)
from domains.fundamentals.universe import PHASE1_UNIVERSE

FIRST_ORIGIN = date(2019, 4, 1)  # the first full month the engine supports (SUPPORTED_FROM)
LAST_ORIGIN = date(2026, 10, 1)
ROLLING_FROM = date(2021, 1, 1)  # the rolling test's first origin; earlier ones are warm-up
POOLS = ("pooled", "own")
MIN_ERRORS = {"pooled": 20, "own": 12}  # known pairs at the horizon, else no range
HORIZONS = (1, 2, 3, 4)
PERCENTILES = (10, 50, 90)


class RangeError(ValueError):
    """A range that can't be built or a build that doesn't reproduce."""


# -- origins and their errors ------------------------------------------------------------------


def origin_dates(start: date = FIRST_ORIGIN, end: date = LAST_ORIGIN) -> list[date]:
    """The 1st of every month from `start`'s month to `end`'s, both included."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def origin_id(ticker: str, as_of: date) -> str:
    return f"{ticker}_{as_of.isoformat()}"


def _case(ticker: str, as_of: date, horizon: int = 4) -> Case:
    return Case(
        case_id=origin_id(ticker, as_of), ticker=ticker, event_date=as_of, event_type="origin",
        description="M9 forecast origin", horizon_quarters=horizon,
        selected_because="M9 origin rule", source_url="", scope_change="",
    )  # fmt: skip


def origin_case(ticker: str, as_of: date) -> Case:
    """The origin as a case, with the longest horizon (up to 4) that stays inside the company's
    filings here (`harness.guard_coverage`); a whole origin isn't dropped for a later cut-off."""
    for horizon in (4, 3, 2, 1):
        case = _case(ticker, as_of, horizon)
        try:
            guard_coverage(case)
            return case
        except EvaluationError:
            continue
    return _case(ticker, as_of, 1)  # fails in guard_coverage with its reason


def error_rows(oid: str, ticker: str, as_of: date, rows: list[dict]) -> list[dict]:
    """The baseline's eval rows of one origin as error rows: ok, missing (not reported by the
    actuals date) or excluded (revenue ≤ 0, so no log ratio). EBIT is ok only with its revenue."""
    out = []
    by_period = {(r["period"], r["item"]): r for r in rows if r["variant"] == "baseline"}
    for (period, item), r in sorted(by_period.items()):
        row = {
            "origin_id": oid, "ticker": ticker, "origin_date": as_of.isoformat(),
            "horizon": r["horizon"], "period": period, "period_end": r.get("period_end"),
            "item": item, "forecast": r["forecast"], "actual": r.get("actual"),
            "actual_revenue": r.get("actual_revenue"),
            "actual_filed_at": r.get("actual_filed_at"),
            "error": None, "status": "missing", "reason": None,
        }  # fmt: skip
        if r["status"] == "ok":
            revenue_row = by_period[(period, "revenue")]
            try:
                fm.log_ratio(revenue_row["actual"], revenue_row["forecast"])
                if item == "revenue":
                    row["error"] = fm.log_ratio(r["actual"], r["forecast"])
                else:
                    row["error"] = fm.margin_error(r["actual"], r["forecast"], r["actual_revenue"])
                row["status"] = "ok"
            except fm.FinancialMathError as e:
                row |= {"status": "excluded", "reason": f"revenue: {e}"}
        out.append(row)
    return out


ERROR_COLUMNS = (
    "origin_id ticker origin_date horizon period period_end item forecast actual actual_revenue "
    "actual_filed_at error status reason"
).split()


def build_origin(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date,
    actuals_as_of: date,
    choices=None,
    today: date | None = None,
) -> str:
    """Store one origin's run and errors (or its failure); returns 'built', 'rescored' or 'kept'.

    An origin stored with today's code version is kept; its missing errors are scored again on
    its stored run, since their actuals may have been filed since."""
    oid, version = origin_id(ticker, as_of), code_version()
    stored = conn.execute("SELECT * FROM forecast_origins WHERE origin_id = ?", (oid,)).fetchone()
    run_id = None
    if stored is not None and stored["code_version"] == version:
        if stored["status"] == "failed":
            return "kept"
        missing = conn.execute(
            "SELECT COUNT(*) FROM baseline_errors WHERE origin_id = ? AND status = 'missing'",
            (oid,),
        ).fetchone()[0]
        if not missing:
            return "kept"
        run_id = stored["run_id"]
    outcome = "rescored" if run_id else "built"
    try:
        run_id, rows = evaluate_case(
            conn, origin_case(ticker, as_of), choices, actuals_as_of=actuals_as_of, today=today,
            run_id=run_id,
        )  # fmt: skip
        status, reason, errors = "ok", None, error_rows(oid, ticker, as_of, rows)
    except scoring_errors() as e:
        status, reason, errors = "failed", str(e), []
        run_id = None
    with conn:
        conn.execute("DELETE FROM baseline_errors WHERE origin_id = ?", (oid,))
        conn.execute("DELETE FROM forecast_origins WHERE origin_id = ?", (oid,))
        conn.execute(
            "INSERT INTO forecast_origins (origin_id, ticker, as_of, run_id, code_version, "
            "status, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (oid, ticker, as_of.isoformat(), run_id, version, status, reason),
        )
        conn.executemany(
            f"INSERT INTO baseline_errors ({', '.join(ERROR_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(ERROR_COLUMNS))})",
            [tuple(r[c] for c in ERROR_COLUMNS) for r in errors],
        )
    return outcome if status == "ok" else "failed"


def build_origins(
    conn: sqlite3.Connection,
    tickers: list[str] | None = None,
    start: date = FIRST_ORIGIN,
    end: date = LAST_ORIGIN,
    actuals_as_of: date | None = None,
    choices=None,
    today: date | None = None,
) -> dict[str, int]:
    """Every origin of every company (the universe file's, unless named): counts by outcome."""
    today = today or date.today()
    tickers = tickers or [c.ticker for c in PHASE1_UNIVERSE]
    counts: dict[str, int] = {}
    for ticker in tickers:
        for d in origin_dates(start, min(end, today)):
            outcome = build_origin(conn, ticker, d, actuals_as_of or today, choices, today)
            counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# -- known errors ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorPair:
    """One origin's revenue and EBIT miss for one forecast quarter."""

    origin_id: str
    ticker: str
    horizon: int
    period: str
    filed_at: date
    revenue: float
    ebit: float


def load_pairs(conn: sqlite3.Connection) -> list[ErrorPair]:
    """Every quarter whose revenue and EBIT errors are both ok, in a fixed order."""
    rows = conn.execute(
        "SELECT r.origin_id, r.ticker, r.horizon, r.period, r.actual_filed_at, "
        "r.error AS rev, e.error AS ebit, e.actual_filed_at AS ebit_filed "
        "FROM baseline_errors r JOIN baseline_errors e "
        "ON e.origin_id = r.origin_id AND e.horizon = r.horizon AND e.item = 'ebit' "
        "JOIN forecast_origins o ON o.origin_id = r.origin_id "
        "WHERE r.item = 'revenue' AND r.status = 'ok' AND e.status = 'ok' AND o.status = 'ok' "
        "ORDER BY r.origin_id, r.horizon"
    ).fetchall()
    out = []
    for r in rows:
        filed = max(date.fromisoformat(r["actual_filed_at"]), date.fromisoformat(r["ebit_filed"]))
        out.append(
            ErrorPair(r["origin_id"], r["ticker"], r["horizon"], r["period"], filed, r["rev"],
                      r["ebit"])
        )  # fmt: skip
    return out


def pairs_sha256(pairs: list[ErrorPair]) -> str:
    text = "\n".join(
        f"{p.origin_id}|{p.horizon}|{p.filed_at}|{p.revenue!r}|{p.ebit!r}" for p in pairs
    )
    return hashlib.sha256(text.encode()).hexdigest()


def known(
    pairs: list[ErrorPair], on: date, horizon: int, pool: str, ticker: str
) -> list[ErrorPair]:
    """The pairs public on `on` (actual filed on or before it) at this horizon, in the pool."""
    if pool not in POOLS:
        raise RangeError(f"unknown pool {pool!r}")
    return [
        p
        for p in pairs
        if p.horizon == horizon and p.filed_at <= on and (pool == "pooled" or p.ticker == ticker)
    ]


# -- ranges ------------------------------------------------------------------------------------


def range_seed(subject_id: str, pool: str) -> int:
    """A fixed seed per subject and pool: the first 15 hex digits of SHA-256('range:<s>:<p>')."""
    return int(hashlib.sha256(f"range:{subject_id}:{pool}".encode()).hexdigest()[:15], 16)


@dataclass(frozen=True)
class Range:
    horizon: int
    n_errors: int
    n_quarters: int
    revenue: tuple[float, float, float] | None  # p10, p50, p90; None when no history
    ebit: tuple[float, float, float] | None

    @property
    def ok(self) -> bool:
        return self.revenue is not None


def ranges(
    samples: dict[int, tuple[np.ndarray, np.ndarray]],
    pairs: list[ErrorPair],
    on: date,
    pool: str,
    ticker: str,
    seed: int,
    n: int = DEFAULT_SAMPLES,
) -> dict[int, Range]:
    """p10/p50/p90 of revenue and EBIT per horizon, from `samples[h]` = (revenue, EBIT) arrays
    of length n (the baseline repeated, or the shocked samples) and the errors known on `on`.

    One generator per call; horizons draw in order 1 to 4, each n indices, so they are
    independent draws and the same seed gives the same ranges. Revenue and EBIT share an index."""
    rng = np.random.Generator(np.random.PCG64(seed))
    out = {}
    for h in sorted(samples):
        pool_h = known(pairs, on, h, pool, ticker)
        quarters = len({(p.ticker, p.period) for p in pool_h})
        if len(pool_h) < MIN_ERRORS[pool]:
            out[h] = Range(h, len(pool_h), quarters, None, None)
            continue
        idx = rng.integers(0, len(pool_h), n)
        e_rev = np.array([p.revenue for p in pool_h])[idx]
        e_ebit = np.array([p.ebit for p in pool_h])[idx]
        rev_s, ebit_s = samples[h]
        revenue = fm.apply_revenue_error(np.asarray(rev_s, dtype=float), e_rev)
        ebit = fm.apply_margin_error(np.asarray(ebit_s, dtype=float), e_ebit, revenue)
        q = [tuple(float(v) for v in np.percentile(x, PERCENTILES)) for x in (revenue, ebit)]
        out[h] = Range(h, len(pool_h), quarters, q[0], q[1])
    return out


def constant_samples(
    forecasts: dict[int, tuple[float, float]], n: int = DEFAULT_SAMPLES
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """The baseline's revenue and EBIT per horizon, as n identical samples."""
    return {h: (np.full(n, r), np.full(n, e)) for h, (r, e) in forecasts.items()}
