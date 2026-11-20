"""History for the single values behind an answer (backlog #476, part 2 of #471).

A single value (the risk-free rate, beta, the equity risk premium, debt, cash, minority interest,
the cost of debt, the share count) is one number in a run. Its history is the same rule run on
earlier dates: the engine's own functions (`risk_free_rate`, the beta regression,
`equity_risk_premium`, the balance step `_balance`, `cost_of_debt_year`, the share basis rule)
on the run's own downloads (pinned by the hashes the run stores, as `reproduce` does) and on the
filings known on the run's `as_of`. Nothing here is a new rule, so a chart can never disagree
with the run: the point the run used equals its row.

Point-in-time: a market point dated d reads only what a run dated d reads (yields before d,
prices on or before d); filings are those known on the run's `as_of`, the same for every point.
"""

import sqlite3
import warnings
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, timedelta

from domains.analysis import financial_math as fm
from domains.analysis.coded import Coded
from domains.analysis.schemas import SINGLE

# The `missing` code of a point the rule could not compute on that date, with the rule's own
# refusal code in `params["reason"]`; a closed list the app words as a short chart note (not as a
# refused run's advice).
NOT_COMPUTABLE = "not_computable"
MISSING_REASONS = (
    # market data
    "too_few_return_weeks",  # beta: fewer than 104 weeks of returns before the date
    "no_risk_free_rate",
    "no_price_on_date",
    "erp_too_few_years",  # fewer than ten years from the run's first ERP year
    "market_data_not_loaded",
    "market_data_not_refreshed",  # the download does not reach the date
    "market_year_end_missing",  # ERP: no close or yield at a year end
    "market_data_error",  # any other market-data failure (its text is in the note)
    # the balance step (`math_engine._balance`)
    "no_balance_sheet",
    "balance_item_not_reported",
    "balance_item_negative",
    "securities_exceed_current_assets",
    # the cost of debt (D8)
    "no_interest_reported",  # the year's filings report no interest expense or interest paid
    "average_debt_not_positive",  # the year's average debt is zero: nothing to divide by
)
# Notes a balance point can carry: the balance step's own notes on that date (their codes and
# params are the run notes' own, `coded.RUN_NOTE_CODES`)
BALANCE_NOTES = (
    "balance_counted_zero",
    "balance_carried_forward",
    "debt_current_inside_short_term",
    "debt_current_total_in_place",
    "debt_current_within_rounding",
    "commercial_paper_beside_short_term",
)
# Notes of this module, a closed list
POINT_NOTES = (
    "run_date",  # the run's own date (the last point of a monthly series), not a month start
    "split_adjusted",  # params factor: new shares per old share (4.0 = one became four)
    "run_read_differently",  # the used point differs from the run's row (an older run)
    # beta: the regression's standard error, params raw_std_error, std_error (the adjusted
    # beta's), weeks (backlog #481)
    "beta_std_error",
    # cost of debt: the book (embedded) rate is below the 10-year Treasury yield, params
    # cost_of_debt, risk_free, risk_free_date, against (backlog #481)
    "below_risk_free",
)
CELL_NOTES = (
    "follows_risk_free",  # terminal growth equals the risk-free rate by the owner's method
    "computed_from_other_cells",  # params inputs: the rows it is computed from
    # a what-if child's cost of debt is the risk-free rate, not a book year (backlog #481)
    "floored_at_risk_free",
)
SERIES_NOTES = (
    "book_value",  # debt, cash and minority interest are the balance sheet's book values
    "overlapping_windows",  # beta: each month's 104 weeks share all but about 4 with the last
    "expanding_window",  # ERP: one more year each point, from the same first year
)
# What each cell's series measure is called
MEASURES = {
    "risk_free": "risk_free_yield",
    "terminal_growth": "risk_free_yield",
    "beta": "beta",
    "erp": "erp",
    "debt": "debt",
    "cash_and_investments": "cash_and_investments",
    "minority_interest": "minority_interest",
    "cost_of_debt": "cost_of_debt",
}
BALANCE_CELLS = ("debt", "cash_and_investments", "minority_interest")
DERIVED_CELLS = ("equity_market_value", "roll_years")


@dataclass
class Singles:
    """What the single-value cells of one answer share: the run, its pins, its history."""

    conn: sqlite3.Connection
    run: sqlite3.Row
    as_of: date
    years: int
    stored: dict  # the run's stored sources, by (name, period)
    reader: object  # inputs._Reader
    filings: object  # reported._Filings
    _history: object = None
    _balances: list | None = None
    cache: dict = field(default_factory=dict)

    @property
    def history(self):
        if self._history is None:
            from domains.analysis.math_engine import load_history

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._history = load_history(self.conn, self.run["cik"], self.as_of)
        return self._history

    def pins(self):
        """The run's own downloads, as `reproduce` pins them; none if one is no longer stored."""
        from domains.market.prices import MARKET_INDEX
        from domains.market.store import MarketDataError, fetch_with_hash, pin_fetches
        from domains.market.yields import RISK_FREE_SERIES

        pins = {}
        for source, symbol, column in (
            ("yahoo", self.run["ticker"], "price_fetch_sha256"),
            ("yahoo", MARKET_INDEX, "index_fetch_sha256"),
            ("fred", RISK_FREE_SERIES, "yield_fetch_sha256"),
        ):
            try:  # pin each download the run names that is still stored
                pins[(source, symbol)] = fetch_with_hash(
                    self.conn, source, symbol, self.run[column]
                )["fetch_id"]
            except (MarketDataError, KeyError, IndexError, TypeError):
                continue
        return pin_fetches(pins) if pins else nullcontext()

    def months(self) -> list[date]:
        """The first of each month, `years` × 12 of them, before the run's date."""
        first = self.as_of.replace(day=1)
        if first == self.as_of:
            first = _add_months(first, -1)
        return [_add_months(first, -k) for k in range(self.years * 12 - 1, -1, -1)]


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _not_computable(error) -> Coded:
    code = getattr(error, "code", None)
    params = dict(getattr(error, "params", None) or {})
    if code not in MISSING_REASONS:  # keep the list closed: the app words every reason
        params = {**params, "error_code": code}
        code = "market_data_error"
    return Coded(NOT_COMPUTABLE, {"reason": code, **params}, str(error))


def _run_date_note(as_of: date) -> Coded:
    return Coded("run_date", {"date": as_of.isoformat()}, "the run's own date")


def single_cell(singles: Singles, name: str, cell_rows: list):
    """The cell of a single value with its history, or None when it has none (the caller then
    gives it the gap `history_not_built`)."""
    from domains.analysis.inputs import Cell

    if name in DERIVED_CELLS:
        return _derived_cell(singles, name, cell_rows)
    if name == "terminal_growth":
        sources = singles.stored.get((name, SINGLE), [])
        follows = any(
            s["kind"] == "derived" and any(i["name"] == "risk_free" for i in s["inputs"])
            for s in sources
        )
        if not follows:
            return None
        note = Coded(
            "follows_risk_free",
            {"method": "risk_free", "cell": "risk_free"},
            "terminal growth is set equal to the risk-free rate (the owner's method choice), "
            "so its history is the risk-free rate's",
        )
        series = _cached(singles, "risk_free", lambda: _risk_free(singles))
        series = _checked(series, cell_rows)
        return Cell(name, cell_rows, [series], None, [note])
    builders = {
        "risk_free": lambda: [_risk_free(singles)],
        "beta": lambda: [_beta(singles)],
        "erp": lambda: [_erp(singles)],
        "cost_of_debt": lambda: [_cost_of_debt(singles)],
        "shares": lambda: _shares(singles),
        **{n: (lambda n=n: [_balance_series(singles, n)]) for n in BALANCE_CELLS},
    }
    if name not in builders:
        return None
    history = [_checked(s, cell_rows) for s in builders[name]()]
    notes = []
    if name == "cost_of_debt" and (floored := _floored_note(singles)) is not None:
        notes.append(floored)
    return Cell(name, cell_rows, history, None, notes)


def _cached(singles: Singles, key: str, build):
    if key not in singles.cache:
        singles.cache[key] = build()
    return singles.cache[key]


def _checked(series, cell_rows):
    """Mark the primary series' used point when its value differs from the run's row (a run
    stored before a filing or a download changed the figure): `run_read_differently`."""
    from domains.analysis.inputs import Point, Series, _fields, _fields_of

    if not series.primary or not cell_rows or cell_rows[0].value is None:
        return series
    run_value = cell_rows[0].value
    points = []
    for p in series.points:
        if (
            p.used
            and p.value is not None
            and abs(p.value - run_value) > 1e-9 * max(1.0, abs(run_value))
        ):
            note = Coded(
                "run_read_differently",
                {"period": p.period, "run_value": run_value, "value": p.value},
                f"the run read {p.period} as {run_value:.6g}, not {p.value:.6g}",
            )
            p = Point(**{**_fields(p), "notes": [*p.notes, note]})
        points.append(p)
    return Series(**{**_fields_of(series), "points": points})


# -- market cells -----------------------------------------------------------------------------


def _monthly(singles: Singles, measure: str, value_at, notes=()):
    """A point per month start and the run's own date, each the value a run dated that day
    reads; the run's date is the used point."""
    from domains.analysis.inputs import Point, Series
    from domains.market.store import MarketDataError

    points = []
    with singles.pins():
        for day in [*singles.months(), singles.as_of]:
            is_run = day == singles.as_of
            run_notes = [_run_date_note(day)] if is_run else []
            try:
                value, period_end, parts, extra = value_at(day)
            except MarketDataError as e:
                points.append(
                    Point(
                        day.isoformat(),
                        None,
                        None,
                        None,
                        None,
                        is_run,
                        notes=run_notes,
                        missing=_not_computable(e),
                    )
                )
                continue
            points.append(
                Point(
                    day.isoformat(),
                    None,
                    None,
                    period_end,
                    value,
                    is_run,
                    parts,
                    [*extra, *run_notes],
                )
            )
    return Series(measure, "month", "latest", True, None, points, list(notes))


def _risk_free(singles: Singles):
    from domains.analysis.inputs import Part
    from domains.market.yields import risk_free_rate

    def at(day):
        rf = risk_free_rate(singles.conn, day)
        part = Part(rf.series, rf.rate, rf.date.isoformat(), None)
        return rf.rate, rf.date, [part], []

    return _monthly(singles, "risk_free_yield", at)


def _beta(singles: Singles):
    from domains.analysis.inputs import Part
    from domains.analysis.math_engine import BETA_WEEKS
    from domains.market.prices import aligned_weekly_returns

    ticker = singles.run["ticker"]

    def at(day):
        pairs = aligned_weekly_returns(singles.conn, ticker, day, BETA_WEEKS)
        raw = fm.ols_beta(pairs.stock, pairs.market)
        raw_se = fm.ols_beta_std_error(pairs.stock, pairs.market)
        se = fm.blume_adjusted_std_error(raw_se)
        window = f"{pairs.first_week.isoformat()}/{pairs.last_week.isoformat()}"
        looseness = Coded(
            "beta_std_error",
            {"raw_std_error": raw_se, "std_error": se, "weeks": len(pairs.stock)},
            f"standard error {se:.2f} (the raw beta's {raw_se:.2f}, plain least squares on "
            f"{len(pairs.stock)} weekly returns, scaled by the fixed Blume weight): how far "
            "this estimate may be from the true beta; it is not a test of the change from "
            "last month, since neighbouring months share most of their weeks",
        )
        return (
            fm.blume_adjusted_beta(raw),
            pairs.last_week,
            [Part("raw_beta", raw, window, None)],
            [looseness],
        )

    overlap = Coded(
        "overlapping_windows",
        {"weeks": BETA_WEEKS, "step": "month"},
        f"each point regresses the {BETA_WEEKS} weeks before its date, so neighbouring points "
        "share most of their weeks and move slowly",
    )
    return _monthly(singles, "beta", at, [overlap])


def _erp(singles: Singles):
    from domains.analysis.inputs import Part, Point, Series
    from domains.market.erp import YEAR_END_LAG, equity_risk_premium, last_complete_year
    from domains.market.prices import MARKET_INDEX, annual_total_returns
    from domains.market.store import MarketDataError
    from domains.market.yields import RISK_FREE_SERIES, annual_bond_returns

    first_year = _erp_first_year(singles)
    last = last_complete_year(singles.as_of)
    points = []
    with singles.pins():
        for year in range(last - singles.years + 1, last + 1):
            used = year == last
            day = date(year + 1, 1, 1) + YEAR_END_LAG  # the first day the year counts
            try:
                erp = equity_risk_premium(singles.conn, day, first_year)
                equity = annual_total_returns(singles.conn, MARKET_INDEX, year, year)[year]
                bonds = annual_bond_returns(singles.conn, year, year)[year]
            except MarketDataError as e:
                points.append(
                    Point(
                        str(year),
                        None,
                        None,
                        date(year, 12, 31),
                        None,
                        used,
                        missing=_not_computable(e),
                    )
                )
                continue
            parts = [
                Part(f"{MARKET_INDEX}_total_return", equity, str(year), None),
                Part(f"{RISK_FREE_SERIES}_bond_total_return", bonds, str(year), None),
                Part("erp_std_error", erp.premium.std_error, f"{first_year}-{year}", None),
            ]
            points.append(
                Point(str(year), None, None, date(year, 12, 31), erp.premium.geometric, used, parts)
            )
    note = Coded(
        "expanding_window",
        {"first_year": first_year},
        f"each point averages every year from {first_year} to its own year, so one more year "
        "moves it only a little, and a good year for stocks raises it",
    )
    return Series("erp", "year", "latest", True, None, points, [note])


def _erp_first_year(singles: Singles) -> int:
    """The owner's first ERP year as the run itself stored it (not today's file)."""
    from domains.analysis.runs import load_assumptions

    rows = load_assumptions(singles.conn, singles.run["run_id"])
    return int(next(a.value for a in rows if a.name == "erp_first_year"))


# -- balance-sheet cells ----------------------------------------------------------------------


def _filing_of(singles: Singles, accession_no: str | None):
    from domains.analysis.inputs import _filing

    return _filing(singles.filings.get(accession_no)) if accession_no else None


def _balances(singles: Singles) -> list:
    """The engine's balance step on each balance-sheet date in the window, as known on the run's
    date: [(date, scratch result or the step's refusal)]."""
    if singles._balances is not None:
        return singles._balances
    from domains.analysis.math_engine import EngineError, EngineResult, _balance

    history = singles.history
    start = singles.as_of - timedelta(days=round(365.25 * singles.years))
    dates = [
        f.period_end
        for f in history.instants.get("current_assets", [])
        if start < f.period_end < singles.as_of
    ]
    out = []
    for day in dates:
        scratch = EngineResult(singles.run["ticker"], singles.run["cik"], day + timedelta(days=1))
        try:
            _balance(history, day, scratch)
        except EngineError as e:
            out.append((day, e))
            continue
        out.append((day, scratch))
    singles._balances = out
    return out


def _run_balance_date(singles: Singles) -> str | None:
    from domains.analysis.math_engine import EngineError, EngineResult, _balance

    scratch = EngineResult(singles.run["ticker"], singles.run["cik"], singles.as_of)
    try:
        return _balance(singles.history, singles.as_of, scratch).isoformat()
    except EngineError:
        return None


def _balance_series(singles: Singles, name: str):
    from domains.analysis.inputs import Part, Point, Series

    used_date = _cached(singles, "run_balance_date", lambda: _run_balance_date(singles))
    points = []
    for day, result in _balances(singles):
        label = day.isoformat()
        used = label == used_date
        if not hasattr(result, "assumptions"):
            points.append(
                Point(label, None, None, day, None, used, missing=_not_computable(result))
            )
            continue
        parts = []
        for source in result.sources.get((name, SINGLE), []):
            refs = (
                [i["name"] for i in source["inputs"]]
                if source["kind"] == "derived"
                else [name]
                if source["kind"] == "filing"
                else []
            )
            for ref in refs:
                for s in result.sources.get((ref, SINGLE), []):
                    if s["kind"] == "filing":
                        parts.append(
                            Part(
                                s["item"],
                                s["value"],
                                s["period_end"],
                                _filing_of(singles, s["accession_no"]),
                            )
                        )
        notes = [n for n in result.notes if n.code in BALANCE_NOTES]
        points.append(Point(label, None, None, day, result.value_of(name), used, parts, notes))
    note = Coded(
        "book_value",
        {"cell": name, "known_on": singles.as_of.isoformat()},
        "the balance sheet's book value, as the valuation uses it (not a market value), each "
        "date as known on the run's date (a later restatement replaces the first filing)",
    )
    return Series(MEASURES[name], "quarter", "latest", True, None, points, [note])


def _cost_of_debt(singles: Singles):
    from domains.analysis.inputs import Part, Point, Series, _year_labels
    from domains.analysis.math_engine import EngineError, cost_of_debt_year, resolve

    sources = singles.stored.get(("cost_of_debt", SINGLE), [])
    interest = _interest_source(sources)
    # a what-if child's changed cost of debt is not a book year: no point is used (backlog #481)
    used_label = f"FY{interest['fiscal_year']}" if interest else None
    last_quarter = singles.reader.latest(quarterly=True)
    last_year = max(singles.reader.latest(quarterly=False).fiscal_year, last_quarter.fiscal_year)
    labels = _year_labels(last_year, singles.years, {used_label} if used_label else set())
    points = []
    for label in labels:
        year = int(label[2:])
        used = label == used_label
        found = cost_of_debt_year(singles.history, year)
        if found is None:
            try:
                resolve("interest", singles.history.year(year), label)
                reason, why = "average_debt_not_positive", f"{label}'s average debt is zero"
            except EngineError:
                reason, why = "no_interest_reported", f"{label} reports no interest"
            missing = Coded(NOT_COMPUTABLE, {"reason": reason, "fiscal_year": year}, why)
            points.append(Point(label, year, "FY", None, None, used, missing=missing))
            continue
        kd, paid, (_start, opening), (_end, closing) = found
        parts = [
            Part(
                f.canonical_name,
                f.value,
                f.period_end.isoformat(),
                None if f.derived else _filing_of(singles, f.accession_no),
                f.derived,
                [_filing_of(singles, a) for a in f.inputs],
            )
            for f in (*paid.facts, *opening, *closing)
        ]
        period_end = paid.facts[0].period_end if paid.facts else None
        notes = _below_risk_free(singles, kd, used, period_end)
        points.append(Point(label, year, "FY", period_end, kd, used, parts, notes))
    return Series("cost_of_debt", "year", "latest", True, None, points)


def _interest_source(sources: list) -> dict | None:
    return next(
        (s for s in sources if s["kind"] == "filing" and s["item"].startswith("interest")), None
    )


def _floored_note(singles: Singles):
    """`floored_at_risk_free` on a what-if child whose cost of debt the debt change floored at
    the child's own risk-free row (`whatif._leverage_rows`; backlog #481): the value is that row
    (itself a what-if value when `risk_free_changed`), and the parent's book cost of debt and
    its fiscal year (None when the parent's sources name no interest filing) say what it
    replaced."""
    sources = singles.stored.get(("cost_of_debt", SINGLE), [])
    floored = next(
        (s for s in sources if s["kind"] == "what_if" and s.get("how") == "floored_at_risk_free"),
        None,
    )
    if floored is None:
        return None
    value = singles.conn.execute(
        "SELECT value FROM assumptions WHERE run_id = ? AND name = 'cost_of_debt' AND period = ?",
        (singles.run["run_id"], SINGLE),
    ).fetchone()["value"]
    book = _interest_source(floored.get("parent_sources") or [])
    rf_sources = singles.stored.get(("risk_free", SINGLE), [])
    return Coded(
        "floored_at_risk_free",
        {
            "value": value,
            "book_cost_of_debt": floored["before"],
            "book_year": f"FY{book['fiscal_year']}" if book else None,
            "parent_run_id": floored["parent_run_id"],
            "cell": "risk_free",
            "risk_free_changed": any(s["kind"] == "what_if" for s in rf_sources),
        },
        f"the cost of debt is the risk-free rate ({value:.2%}), not a book year: the debt "
        f"changed and the book cost of debt ({floored['before']:.2%}) was below the risk-free "
        "rate, so Warren holds it at that floor (a lender charges at least what the government "
        "pays). The floor is a minimum, not an estimate: more debt usually costs more, so this "
        "what-if's value is on the high side",
    )


def _run_risk_free(singles: Singles):
    """The run's own risk-free row and the date of its DGS10 observation (its stored source)."""
    row = singles.conn.execute(
        "SELECT value FROM assumptions WHERE run_id = ? AND name = 'risk_free' AND period = ?",
        (singles.run["run_id"], SINGLE),
    ).fetchone()
    if row is None:
        return None
    source = next(
        (s for s in singles.stored.get(("risk_free", SINGLE), []) if s["kind"] == "market"),
        None,
    )
    return row["value"], source["end"] if source else None


def _below_risk_free(singles: Singles, kd: float, used: bool, period_end: date | None) -> list:
    """`below_risk_free` when a year's book (embedded) cost of debt is strictly below the 10-year
    Treasury yield (backlog #481): the used year against the run's own risk-free row (the rate
    in the same WACC, and the row `whatif._would_floor` compares with), every other year against
    the average 10-year yield over that fiscal year (interest over average debt is a flow over
    the year, so one day's yield is not like for like; analyst, #481). Nothing after `as_of`."""
    from domains.market.store import MarketDataError
    from domains.market.yields import yields_through

    if used:
        found = _run_risk_free(singles)
        if found is None:
            return []
        rf, rf_date = found
        extra = {"against": "run_risk_free"}
        benchmark = f"the run's own risk-free rate, on {rf_date}"
    else:
        if period_end is None or period_end >= singles.as_of:
            return []
        try:
            with singles.pins():
                obs = yields_through(singles.conn, period_end - timedelta(days=364), period_end)
        except MarketDataError:
            return []
        if not obs:
            return []
        rf, rf_date = fm.mean([o.rate for o in obs]), obs[-1].date.isoformat()
        extra = {
            "against": "year_average_yield",
            "risk_free_from": obs[0].date.isoformat(),
            "observations": len(obs),
        }
        benchmark = f"its average from {obs[0].date.isoformat()} to {rf_date}"
    if not kd < rf:
        return []
    return [
        Coded(
            "below_risk_free",
            {"cost_of_debt": kd, "risk_free": rf, "risk_free_date": rf_date, **extra},
            f"the book cost of debt ({kd:.2%}, interest over average book debt) is below the "
            f"10-year Treasury yield ({rf:.2%}, {benchmark}): it is the average rate on debt "
            "raised in past years, often when rates were lower (and on short-term borrowing "
            "and swaps), not what a lender would charge today, so it is common, not a mistake",
        )
    ]


def _shares(singles: Singles):
    """Every cover-page count and every quarter's diluted count in the window, on the run's
    share basis (split-adjusted to the run's price date with the engine's basis rule)."""
    from domains.analysis.inputs import Part, Point, Series, _label
    from domains.market.prices import split_factor

    history = singles.history
    price = next(
        (
            s
            for s in singles.stored.get(("price", SINGLE), [])
            if s["kind"] == "market" and s["measure"] == "close"
        ),
        None,
    )
    price_date = date.fromisoformat(price["start"]) if price else singles.as_of
    counted = next(
        (s for s in singles.stored.get(("shares", SINGLE), []) if s["kind"] == "filing"), None
    )
    start = singles.as_of - timedelta(days=round(365.25 * singles.years))

    def point(fact, label, frequency_basis):
        basis = fact.period_end if fact.canonical_name == "shares_outstanding" else fact.filed_at
        with singles.pins():
            factor = split_factor(singles.conn, singles.run["ticker"], basis, price_date)
        used = bool(
            counted
            and counted["item"] == fact.canonical_name
            and counted["accession_no"] == fact.accession_no
            and counted["period_end"] == fact.period_end.isoformat()
        )
        notes = (
            [
                Coded(
                    "split_adjusted",
                    {"factor": factor, "through": price_date.isoformat()},
                    f"× {factor:g} for share splits up to {price_date} (new shares per old share)",
                )
            ]
            if factor != 1
            else []
        )
        part = Part(
            fact.canonical_name,
            fact.value,
            label,
            _filing_of(singles, fact.accession_no),
        )
        year, fp = frequency_basis
        return Point(label, year, fp, fact.period_end, fact.value * factor, used, [part], notes)

    cover = [
        point(f, f.period_end.isoformat(), (None, None))
        for f in history.instants.get("shares_outstanding", [])
        if start < f.period_end <= singles.as_of and f.value > 0
    ]
    diluted_facts = sorted(
        (
            f
            for (n, _y, _p), f in history.quarterly.items()
            if n == "diluted_shares" and start < f.period_end and f.value > 0
        ),
        key=lambda f: f.period_end,
    )
    diluted = [
        point(f, _label(f.fiscal_year, f.fiscal_period), (f.fiscal_year, f.fiscal_period))
        for f in diluted_facts
    ]
    cover_used = bool(counted and counted["item"] == "shares_outstanding")
    return [
        Series("shares_outstanding", "date", "latest", cover_used, None, cover),
        Series("diluted_shares", "quarter", "latest", not cover_used, None, diluted),
    ]


# -- cells computed from other cells -----------------------------------------------------------


def _derived_cell(singles: Singles, name: str, cell_rows: list):
    from domains.analysis.inputs import Cell

    inputs = [
        {"name": i["name"], "period": i["period"]}
        for s in singles.stored.get((name, SINGLE), [])
        if s["kind"] == "derived"
        for i in s["inputs"]
    ]
    gap = Coded(
        "computed_from_other_cells",
        {"cell": name, "inputs": inputs},
        f"{name} is computed from {', '.join(i['name'] for i in inputs)}: see their cards",
    )
    return Cell(name, cell_rows, [], gap, [])
