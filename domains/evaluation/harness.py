"""The evaluation harness (M3, Decision 7): how good the baseline forecast is, case by case.

For each case, Warren runs the baseline as of the case date (point-in-time data only) and its
first 1-4 forecast quarters of revenue and EBIT are compared with the values as first reported in
later filings. Next to the baseline, every quarter is also scored for a seasonal random walk (the
same quarter a year earlier, as known on the case date), the standard naive yardstick for quarterly
accounting numbers. Design and review: docs/designs/m3-evaluation-harness.md.

Errors: revenue as absolute percentage error; EBIT in margin points (error ÷ actual revenue),
because EBIT can be near zero or negative and a percentage error then explodes.
"""

import re
import sqlite3
import warnings
from dataclasses import dataclass
from datetime import date, timedelta

from domains.analysis.dcf import YEARS
from domains.analysis.math_engine import CHAINS, EngineError, UserChoice, step_quarter, trace
from domains.analysis.runs import code_version, load_assumptions, load_outputs, run_baseline
from domains.evaluation.cases import CONTROL_OFFSET_DAYS, Case, store_cases
from domains.fundamentals.facts import get_facts
from domains.fundamentals.schemas import Fact
from domains.fundamentals.universe import get_universe_company
from domains.market.store import MarketDataError

DIRECTION_BAND = 0.005  # a change within ±0.5% of the prior year counts as flat
ACCESSION = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
QUARTER_DAYS = 92
FILING_LAG_DAYS = 45  # a quarter's 10-Q comes about this long after it ends
ITEMS = sorted({"revenue", *(item for alt in CHAINS["ebit"] for item in alt)})
VARIANTS = ("baseline", "naive_srw")


class EvaluationError(ValueError):
    """A case can't be scored; the reason is stored in eval_failures."""


def direction(value: float | None, reference: float | None) -> int | None:
    """1 up, -1 down, 0 flat (within DIRECTION_BAND) against a reference; None if unknown."""
    if value is None or reference is None or reference == 0:
        return None
    change = (value - reference) / abs(reference)
    return 1 if change > DIRECTION_BAND else -1 if change < -DIRECTION_BAND else 0


def parse_label(label: str) -> tuple[int, int]:
    match = re.fullmatch(r"FY(\d{4})Q([1-4])", label)
    if match is None:
        raise EvaluationError(f"not a fiscal quarter label: {label}")
    return int(match.group(1)), int(match.group(2))


def label(fiscal_year: int, quarter: int) -> str:
    return f"FY{fiscal_year}Q{quarter}"


# -- guards ------------------------------------------------------------------------------------


def guard_look_ahead(conn: sqlite3.Connection, run_id: str, case_date: date) -> int:
    """Fail if any filing the run's assumptions cite was public after the case date.

    Independent of the point-in-time queries that built the run, so a bug in those is caught
    here. Market data is guarded where it is read (downloads pinned and dated, M2.1).
    Returns the number of filings checked.
    """
    methods = " ".join(a.method for a in load_assumptions(conn, run_id))
    accessions = sorted(set(ACCESSION.findall(methods)))
    if not accessions:
        raise EvaluationError(f"{run_id}: no filing cited by the run's assumptions")
    placeholders = ", ".join("?" * len(accessions))
    filed = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT accession_no, MAX(filed_at) FROM financial_facts "
            f"WHERE accession_no IN ({placeholders}) GROUP BY accession_no",
            accessions,
        )
    }
    unknown = [a for a in accessions if a not in filed]
    late = [f"{a} (filed {filed[a]})" for a in accessions if filed.get(a, "") > str(case_date)]
    if unknown or late:
        raise EvaluationError(
            f"look-ahead guard: {run_id} cites filings public after {case_date}: "
            + ", ".join(late + [f"{a} (unknown)" for a in unknown])
        )
    return len(accessions)


def guard_control_date(conn: sqlite3.Connection, cik: str, case: Case) -> None:
    """Fail a control that isn't CONTROL_OFFSET_DAYS after one of its company's quarter ends.

    The case file can't check this alone: fiscal quarters end on the company's own calendar
    (JNJ and KO on the Sunday or Friday nearest the month end), so the dates come from filings.
    """
    if not case.is_control:
        return
    quarter_end = case.event_date - timedelta(days=CONTROL_OFFSET_DAYS)
    found = conn.execute(
        "SELECT 1 FROM financial_facts WHERE cik = ? AND period_end = ? AND period_start IS NOT "
        "NULL AND fiscal_period IN ('Q1', 'Q2', 'Q3', 'FY') LIMIT 1",
        (cik, quarter_end.isoformat()),
    ).fetchone()
    if found is None:
        raise EvaluationError(
            f"control rule: {case.event_date} is not {CONTROL_OFFSET_DAYS} days after a fiscal "
            f"quarter end of {case.ticker} ({quarter_end} is not one)"
        )


def guard_coverage(case: Case) -> None:
    """Fail when the horizon reaches past the point where the company's filings stop here."""
    ends = get_universe_company(case.ticker).history_ends
    if ends is None:
        return
    reach = case.event_date + timedelta(
        days=QUARTER_DAYS * (case.horizon_quarters + 1) + FILING_LAG_DAYS
    )
    if reach >= ends:
        raise EvaluationError(
            f"coverage: {case.ticker}'s filings here stop on {ends}; a {case.horizon_quarters}"
            f"-quarter horizon from {case.event_date} needs filings up to about {reach}"
        )


# -- actuals -----------------------------------------------------------------------------------


def _alternative(method: str) -> int:
    """Which EBIT alternative a history:ebit row used (0 primary, i for the i-th fallback)."""
    if not method.startswith("fallback: "):
        return 0
    items = tuple(method.removeprefix("fallback: ").split(" = ", 1)[0].split(" + "))
    try:
        return CHAINS["ebit"].index(items)
    except ValueError as e:
        raise EvaluationError(f"unrecognised EBIT method: {method[:80]}") from e


def _quarterly(conn, cik: str, as_of: date | str, mode: str) -> dict[tuple, Fact]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # coverage is a hard error here (guard_coverage)
        facts = get_facts(conn, cik, ITEMS, as_of, mode=mode, frequency="quarterly")
    return {(f.canonical_name, f.fiscal_year, f.fiscal_period): f for f in facts}


@dataclass(frozen=True)
class Actual:
    revenue: Fact
    ebit: float
    ebit_facts: list[Fact]
    filed_at: date

    @property
    def derived(self) -> bool:
        return self.revenue.derived or any(f.derived for f in self.ebit_facts)

    @property
    def method(self) -> str:
        return "; ".join(trace(f) for f in [self.revenue, *self.ebit_facts])


def first_reported(
    facts: dict[tuple, Fact], fiscal_year: int, quarter: int, alternative: int
) -> Actual | None:
    """A quarter's revenue and EBIT as first reported, EBIT on the run's own definition.

    None when the quarter isn't reported yet. Fails when it is reported but only under another
    EBIT definition, so forecast and actual are never on different definitions.
    """
    period = f"Q{quarter}"
    revenue = facts.get(("revenue", fiscal_year, period))
    if revenue is None:
        return None
    alternatives = CHAINS["ebit"]
    chosen = [facts.get((item, fiscal_year, period)) for item in alternatives[alternative]]
    if any(f is None for f in chosen):
        others = [
            " + ".join(alt)
            for i, alt in enumerate(alternatives)
            if i != alternative and all(facts.get((n, fiscal_year, period)) for n in alt)
        ]
        detail = f"reported only as {', '.join(others)}" if others else "not reported"
        raise EvaluationError(
            f"EBIT for {label(fiscal_year, quarter)} on the run's definition "
            f"({' + '.join(alternatives[alternative])}) is {detail}"
        )
    used = [f for f in chosen if f is not None]
    filed = max(f.filed_at for f in [revenue, *used])
    return Actual(revenue, sum(f.value for f in used), used, filed)


def comparative(
    facts: dict[tuple, Fact], fiscal_year: int, quarter: int, alternative: int
) -> tuple[float | None, float | None]:
    """Revenue and EBIT of the same quarter a year earlier, from `facts` (one as-of date).

    A value derived from inputs on different bases (e.g. a recast prior year in the actual's
    10-K minus last year's nine months as first reported) is not a same-filing comparative: it's
    None, and so is the actual direction.
    """
    year, q = step_quarter(fiscal_year, quarter, -4)

    def basis(item: str) -> Fact | None:
        fact = facts.get((item, year, f"Q{q}"))
        return None if fact is None or fact.mixed_vintage else fact

    revenue = basis("revenue")
    ebit = [basis(item) for item in CHAINS["ebit"][alternative]]
    return (
        revenue.value if revenue else None,
        sum(f.value for f in ebit) if all(ebit) else None,
    )


# -- scoring -----------------------------------------------------------------------------------


def score(
    item: str, forecast: float, actual: float, actual_revenue: float
) -> tuple[float, float, float | None]:
    """(error, signed error, percentage error): revenue in % of actual, EBIT in margin points."""
    scale = abs(actual) if item == "revenue" else abs(actual_revenue)
    if scale == 0:
        raise EvaluationError(f"{item}: cannot scale an error by a zero actual")
    signed = (forecast - actual) / scale
    pct = (forecast - actual) / abs(actual) if actual else None
    return abs(signed), signed, pct


def evaluate_case(
    conn: sqlite3.Connection,
    case: Case,
    choices: dict[str, UserChoice] | None = None,
    actuals_as_of: date | None = None,
    today: date | None = None,
) -> tuple[str, list[dict]]:
    """Run the baseline as of the case date and score it and the naive forecast; (run_id, rows)."""
    guard_coverage(case)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = ?", (case.ticker,)).fetchone()
    if cik is None:
        raise EvaluationError(f"{case.ticker} has not been ingested")
    cik = cik["cik"]
    guard_control_date(conn, cik, case)
    run_id = run_baseline(conn, case.ticker, case.event_date, choices=choices, today=today)
    guard_look_ahead(conn, run_id, case.event_date)

    outputs = load_outputs(conn, run_id)
    rows_used = load_assumptions(conn, run_id)
    history = {(a.name, a.period): a for a in rows_used if a.name.startswith("history:")}
    quarters = sorted(p for (n, p) in outputs if n == "revenue" and p not in YEARS)
    actuals = _quarterly(conn, cik, actuals_as_of or date.today(), "first_reported")
    at_filing: dict[date, dict[tuple, Fact]] = {}

    rows = []
    for horizon, period in enumerate(quarters[: case.horizon_quarters], start=1):
        year, quarter = parse_label(period)
        prior = label(*step_quarter(year, quarter, -4))
        known_ebit = history.get(("history:ebit", prior))
        known_revenue = history.get(("history:revenue", prior))
        if known_ebit is None or known_revenue is None:
            raise EvaluationError(f"{run_id}: no history row for {prior}, the year before {period}")
        alternative = _alternative(known_ebit.method)
        actual = first_reported(actuals, year, quarter, alternative)
        if actual is not None and actual.filed_at not in at_filing:
            at_filing[actual.filed_at] = _quarterly(conn, cik, actual.filed_at, "latest")
        comp = None
        if actual is not None:
            comp = comparative(at_filing[actual.filed_at], year, quarter, alternative)

        for item, known in (("revenue", known_revenue.value), ("ebit", known_ebit.value)):
            forecasts = {"baseline": outputs[(item, period)], "naive_srw": known}
            for variant, forecast in forecasts.items():
                row = {
                    "case_id": case.case_id,
                    "run_id": run_id,
                    "variant": variant,
                    "item": item,
                    "period": period,
                    "horizon": horizon,
                    "forecast": forecast,
                    "prior_year_known": known,
                    "direction_forecast": direction(forecast, known),
                    "derived": 0,
                    "status": "missing",
                }
                if actual is not None:
                    value = actual.revenue.value if item == "revenue" else actual.ebit
                    error, signed, pct = score(item, forecast, value, actual.revenue.value)
                    start, end = actual.revenue.period_start, actual.revenue.period_end
                    reference = comp[0] if item == "revenue" else comp[1]
                    row |= {
                        "status": "ok",
                        "actual": value,
                        "actual_revenue": actual.revenue.value,
                        "comparative": reference,
                        "period_end": end.isoformat(),
                        "days": (end - start).days + 1 if start else None,
                        "error": error,
                        "signed_error": signed,
                        "pct_error": pct,
                        "direction_actual": direction(value, reference),
                        "derived": int(actual.derived),
                        "actual_method": actual.method,
                    }
                rows.append(row)
    if not rows:
        raise EvaluationError(f"{run_id}: no forecast quarters")
    return run_id, rows


# -- batches -----------------------------------------------------------------------------------

COLUMNS = (
    "case_id run_id variant item period horizon period_end days forecast actual actual_revenue "
    "comparative prior_year_known error signed_error pct_error direction_forecast "
    "direction_actual derived actual_method status"
).split()


def run_batch(
    conn: sqlite3.Connection,
    cases: list[Case],
    cases_sha256: str,
    choices: dict[str, UserChoice] | None = None,
    actuals_as_of: date | None = None,
    today: date | None = None,
) -> str:
    """Score every case; returns the batch id. A case that can't be scored is recorded, with
    its reason, in eval_failures and never silently dropped."""
    store_cases(conn, cases)
    prefix = f"eval_{(today or date.today()).isoformat()}_"
    count = conn.execute(
        "SELECT COUNT(*) FROM eval_batches WHERE batch_id LIKE ?", (prefix + "%",)
    ).fetchone()[0]
    batch_id = f"{prefix}{count + 1}"
    with conn:
        conn.execute(
            "INSERT INTO eval_batches (batch_id, code_version, cases_sha256) VALUES (?, ?, ?)",
            (batch_id, code_version(), cases_sha256),
        )
    for case in cases:
        try:
            _, rows = evaluate_case(conn, case, choices, actuals_as_of, today)
        except (EvaluationError, EngineError, MarketDataError, ValueError) as e:
            with conn:
                conn.execute(
                    "INSERT INTO eval_failures (batch_id, case_id, reason) VALUES (?, ?, ?)",
                    (batch_id, case.case_id, str(e)),
                )
            continue
        with conn:
            conn.executemany(
                f"INSERT INTO eval_results (batch_id, {', '.join(COLUMNS)}) "
                f"VALUES (?, {', '.join('?' * len(COLUMNS))})",
                [(batch_id, *(row.get(c) for c in COLUMNS)) for row in rows],
            )
    return batch_id
