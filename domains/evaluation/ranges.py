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
from datetime import UTC, date, datetime

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
from shared_kernel.calendar import case_today, last_ended_day

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
    now = datetime.now(UTC)
    last = today or last_ended_day(now)
    tickers = tickers or [c.ticker for c in PHASE1_UNIVERSE]
    counts: dict[str, int] = {}
    for ticker in tickers:
        for d in origin_dates(start, min(end, last)):
            outcome = build_origin(conn, ticker, d, actuals_as_of or last, choices, today)
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


# -- builds: ranges for every origin and case, stored ------------------------------------------

RESULT_COLUMNS = (
    "subject_kind subject_id run_id as_of variant pool item period period_end horizon forecast "
    "n_errors n_quarters p10 p50 p90 actual actual_revenue seed status"
).split()
MONEY = 0.005  # currency units: to the cent
RATIO = 1e-9


@dataclass(frozen=True)
class Subject:
    """What a range is built for: an origin or a case, on one stored run."""

    kind: str  # 'origin' or 'case'
    subject_id: str
    ticker: str
    as_of: date
    run_id: str
    quarters: dict[int, dict]  # horizon -> period, period_end, forecasts and actuals by item


def _quarter_item(row) -> dict:
    keys = ("forecast", "actual", "actual_revenue", "status")
    return {k: row[k] for k in keys}


def origin_subjects(conn: sqlite3.Connection) -> list[Subject]:
    """Every ok origin, with its baseline forecasts and actuals per horizon."""
    out = []
    for o in conn.execute(
        "SELECT * FROM forecast_origins WHERE status = 'ok' ORDER BY origin_id"
    ).fetchall():
        quarters: dict[int, dict] = {}
        for e in conn.execute(
            "SELECT * FROM baseline_errors WHERE origin_id = ? ORDER BY horizon, item",
            (o["origin_id"],),
        ):
            q = quarters.setdefault(
                e["horizon"], {"period": e["period"], "period_end": e["period_end"]}
            )
            q[e["item"]] = _quarter_item(e)
        quarters = {h: q for h, q in quarters.items() if "revenue" in q and "ebit" in q}
        out.append(Subject("origin", o["origin_id"], o["ticker"],
                           date.fromisoformat(o["as_of"]), o["run_id"], quarters))  # fmt: skip
    return out


def case_subjects(conn: sqlite3.Connection, batch_id: str) -> list[Subject]:
    """Every case of an M8 batch with baseline rows, on the run the batch scored."""
    rows = conn.execute(
        "SELECT r.*, c.ticker, c.event_date FROM eval_results r JOIN eval_cases c "
        "USING (case_id) WHERE r.batch_id = ? AND r.variant = 'baseline' "
        "ORDER BY r.case_id, r.horizon, r.item",
        (batch_id,),
    ).fetchall()
    by_case: dict[str, list] = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)
    out = []
    for case_id, rs in by_case.items():
        quarters: dict[int, dict] = {}
        for r in rs:
            q = quarters.setdefault(
                r["horizon"], {"period": r["period"], "period_end": r["period_end"]}
            )
            q[r["item"]] = _quarter_item(r)
        first = rs[0]
        out.append(Subject("case", case_id, first["ticker"],
                           date.fromisoformat(first["event_date"]), first["run_id"],
                           quarters))  # fmt: skip
    return out


def shocked_samples(
    conn: sqlite3.Connection, batch_id: str, subject: Subject, guides=None, n: int = DEFAULT_SAMPLES
) -> dict[str, dict[int, tuple[np.ndarray, np.ndarray]]]:
    """For a case, the shocked samples of each variant the M8 batch scored, as it drew them."""
    from domains.analysis.montecarlo import sample_lines
    from domains.analysis.runs import load_assumptions
    from domains.evaluation.backtest_batch import _shock_sets, batch_notes
    from domains.evaluation.guidance import to_shocks
    from domains.evaluation.harness import case_seed

    notes = batch_notes(conn, batch_id)
    scored = {
        r["variant"]
        for r in conn.execute(
            "SELECT DISTINCT variant FROM eval_results WHERE batch_id = ? AND case_id = ?",
            (batch_id, subject.subject_id),
        )
    }
    rows_used = load_assumptions(conn, subject.run_id)
    shock_sets: dict[str, list] = {}
    set_ids = notes["sets"].get(subject.subject_id)
    if set_ids:
        shock_sets |= _shock_sets(conn, set_ids)
    case_guides = [g for g in guides or [] if g.case_id == subject.subject_id]
    if case_guides:
        shock_sets["with_shocks"] = to_shocks(case_guides, rows_used)
    out = {}
    seed = case_seed(subject.subject_id)
    for variant, shock_list in sorted(shock_sets.items()):
        if variant not in scored or not shock_list:
            continue
        lines = sample_lines(rows_used, shock_list, n, seed)
        out[variant] = {
            h: (lines[("revenue", q["period"])], lines[("ebit", q["period"])])
            for h, q in subject.quarters.items()
        }
    return out


def subject_rows(
    subject: Subject,
    pairs: list[ErrorPair],
    samples: dict[str, dict[int, tuple[np.ndarray, np.ndarray]]],
    n: int = DEFAULT_SAMPLES,
) -> list[dict]:
    """The range_results rows of one subject: every variant, pool, item and horizon."""
    rows = []
    for variant in sorted(samples):
        for pool in POOLS:
            seed = range_seed(f"{subject.subject_id}:{variant}", pool)
            built = ranges(samples[variant], pairs, subject.as_of, pool, subject.ticker, seed, n)
            for h, r in sorted(built.items()):
                q = subject.quarters[h]
                for item, band in (("revenue", r.revenue), ("ebit", r.ebit)):
                    fc = float(np.median(samples[variant][h][0 if item == "revenue" else 1]))
                    a = q[item]
                    status = "no_history" if band is None else (
                        "ok" if a["status"] == "ok" else "missing")  # fmt: skip
                    rows.append({
                        "subject_kind": subject.kind, "subject_id": subject.subject_id,
                        "run_id": subject.run_id, "as_of": subject.as_of.isoformat(),
                        "variant": variant, "pool": pool, "item": item, "period": q["period"],
                        "period_end": q["period_end"], "horizon": h, "forecast": fc,
                        "n_errors": r.n_errors, "n_quarters": r.n_quarters,
                        "p10": band[0] if band else None, "p50": band[1] if band else None,
                        "p90": band[2] if band else None,
                        "actual": a["actual"] if a["status"] == "ok" else None,
                        "actual_revenue": a["actual_revenue"] if a["status"] == "ok" else None,
                        "seed": seed, "status": status,
                    })  # fmt: skip
    return rows


def baseline_samples(subject: Subject, n: int = DEFAULT_SAMPLES) -> dict:
    return constant_samples(
        {h: (q["revenue"]["forecast"], q["ebit"]["forecast"]) for h, q in subject.quarters.items()},
        n,
    )


def build_rows(
    conn: sqlite3.Connection,
    pairs: list[ErrorPair],
    batch_id: str | None,
    guides=None,
    n: int = DEFAULT_SAMPLES,
) -> list[dict]:
    """Every range row: origins (baseline only), then the batch's cases (baseline and shocked)."""
    rows = []
    for s in origin_subjects(conn):
        rows += subject_rows(s, pairs, {"baseline": baseline_samples(s, n)}, n)
    if batch_id:
        for s in case_subjects(conn, batch_id):
            samples = {"baseline": baseline_samples(s, n)}
            samples |= shocked_samples(conn, batch_id, s, guides, n)
            rows += subject_rows(s, pairs, samples, n)
    return rows


def pairs_as_of(conn: sqlite3.Connection, actuals_as_of: date) -> list[ErrorPair]:
    """The stored pairs whose actuals were filed by the build's actuals date."""
    return [p for p in load_pairs(conn) if p.filed_at <= actuals_as_of]


def run_build(
    conn: sqlite3.Connection,
    actuals_as_of: date,
    batch_id: str | None = None,
    guides=None,
    guidance_sha256: str | None = None,
    n: int = DEFAULT_SAMPLES,
    today: date | None = None,
) -> str:
    """Build and store every range; the build id, `ranges_<date>_<n>`."""
    import json

    pairs = pairs_as_of(conn, actuals_as_of)
    rows = build_rows(conn, pairs, batch_id, guides, n)
    prefix = f"ranges_{(today or case_today(datetime.now(UTC))).isoformat()}_"
    count = conn.execute(
        "SELECT COUNT(*) FROM range_builds WHERE build_id LIKE ?", (prefix + "%",)
    ).fetchone()[0]
    build_id = f"{prefix}{count + 1}"
    notes = json.dumps({"n_samples": n, "guidance_sha256": guidance_sha256}, sort_keys=True)
    with conn:
        conn.execute(
            "INSERT INTO range_builds (build_id, code_version, actuals_as_of, errors_sha256, "
            "eval_batch_id, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (build_id, code_version(), actuals_as_of.isoformat(), pairs_sha256(pairs), batch_id,
             notes),
        )  # fmt: skip
        conn.executemany(
            f"INSERT INTO range_results (build_id, {', '.join(RESULT_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' * len(RESULT_COLUMNS))})",
            [(build_id, *(r[c] for c in RESULT_COLUMNS)) for r in rows],
        )
    return build_id


# -- reproduce ---------------------------------------------------------------------------------


@dataclass
class BuildReproduction:
    build_id: str
    code_then: str
    code_now: str
    errors_checked: int = 0
    rows_checked: int = 0
    mismatches: list[str] | None = None

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _differs(a, b, tolerance: float) -> bool:
    if a is None or b is None:
        return a is not b
    if isinstance(a, str) or isinstance(b, str):
        return a != b
    return abs(a - b) > tolerance


def reproduce_build(conn: sqlite3.Connection, build_id: str, guides=None) -> BuildReproduction:
    """Score every stored origin again on its stored run, as of the build's actuals date, and
    build every range again from those errors and its seed; compare to the cent."""
    import json

    build = conn.execute("SELECT * FROM range_builds WHERE build_id = ?", (build_id,)).fetchone()
    if build is None:
        raise RangeError(f"no build {build_id}")
    out = BuildReproduction(build_id, build["code_version"], code_version(), mismatches=[])
    as_of = date.fromisoformat(build["actuals_as_of"])
    n = json.loads(build["notes"] or "{}").get("n_samples", DEFAULT_SAMPLES)
    for o in conn.execute(
        "SELECT * FROM forecast_origins WHERE status = 'ok' ORDER BY origin_id"
    ).fetchall():
        d = date.fromisoformat(o["as_of"])
        try:
            _, rows = evaluate_case(
                conn, origin_case(o["ticker"], d), actuals_as_of=as_of, run_id=o["run_id"]
            )
        except scoring_errors() as e:
            out.mismatches.append(f"{o['origin_id']}: {e}")
            continue
        now = {
            (r["horizon"], r["item"]): r for r in error_rows(o["origin_id"], o["ticker"], d, rows)
        }
        for e in conn.execute(
            "SELECT * FROM baseline_errors WHERE origin_id = ?", (o["origin_id"],)
        ).fetchall():
            if e["status"] != "ok" or date.fromisoformat(e["actual_filed_at"]) > as_of:
                continue  # not part of the build
            r = now.get((e["horizon"], e["item"]))
            if r is None or r["status"] != "ok":
                out.mismatches.append(f"{o['origin_id']} h{e['horizon']} {e['item']}: not ok now")
                continue
            if e["actual_filed_at"] != r["actual_filed_at"]:
                out.mismatches.append(
                    f"{o['origin_id']} h{e['horizon']} {e['item']} actual_filed_at: stored "
                    f"{e['actual_filed_at']}, now {r['actual_filed_at']}"
                )
            for col, tol in (("forecast", MONEY), ("actual", MONEY), ("error", RATIO)):
                if _differs(e[col], r[col], tol):
                    out.mismatches.append(
                        f"{o['origin_id']} h{e['horizon']} {e['item']} {col}: stored {e[col]}, "
                        f"now {r[col]}"
                    )
            out.errors_checked += 1
    pairs = pairs_as_of(conn, as_of)
    if pairs_sha256(pairs) != build["errors_sha256"]:
        out.mismatches.append("the errors the build read have changed (errors_sha256)")
    rows = build_rows(conn, pairs, build["eval_batch_id"], guides, n)
    now = {(r["subject_kind"], r["subject_id"], r["variant"], r["pool"], r["item"], r["period"]): r
           for r in rows}  # fmt: skip
    stored = {
        (r["subject_kind"], r["subject_id"], r["variant"], r["pool"], r["item"], r["period"]): r
        for r in conn.execute("SELECT * FROM range_results WHERE build_id = ?", (build_id,))
    }
    if set(now) != set(stored):
        diff = sorted(set(now) ^ set(stored))
        out.mismatches.append(f"{len(diff)} range rows differ, e.g. {diff[:3]}")
    for key in sorted(set(now) & set(stored)):
        a, b = stored[key], now[key]
        for col in RESULT_COLUMNS:
            tol = RATIO if col in ("n_errors", "n_quarters", "horizon", "seed") else MONEY
            if _differs(a[col], b[col], tol):
                out.mismatches.append(
                    f"{' '.join(map(str, key))} {col}: stored {a[col]}, now {b[col]}"
                )
        out.rows_checked += 1
    return out
