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
from typing import TYPE_CHECKING

from domains.analysis import financial_math as fm
from domains.analysis.coded import Coded
from domains.analysis.schemas import SINGLE

if TYPE_CHECKING:  # `inputs` imports this module, so its types are read only by type checkers
    from domains.analysis.inputs import Point

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
    # the fiscal year is after the newest one with an annual figure known on the run's date (in
    # progress, or ended with its 10-K not out); params fiscal_year, period_end (the year's
    # expected end, ISO, `expected_year_end`) (backlog #564)
    "not_filed_yet",
    # diluted shares by quarter: the fourth quarter has no count of its own (the 10-K files the
    # year's weighted count instead); params fiscal_year, annual_period (FY2024, the annual
    # series' point, or None when that year's count is not filed either) (backlog #481)
    "no_fourth_quarter_count",
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
# The cost-of-debt note for a company whose interest line is net of swap gains (backlog #542)
HEDGE_NOTE = "interest_net_of_hedge_gains"
# The cost-of-debt note for a book rate far from the company's own stated rate (backlog #543)
STATED_NOTE = "far_from_stated_rate"
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
    # cost of debt: the company's interest line is net of what its currency swaps earn
    # (interest_caveats.csv), with its own stated effective rate beside; replaces
    # below_risk_free on the years it covers, keeping its params inside (backlog #542)
    HEDGE_NOTE,
    # cost of debt: the book rate is more than STATED_RATE_GAP from the rate the company states
    # on its own debt (stated_debt_rates.csv), averaged over the year's two year ends; never on
    # a year an interest caveat covers, whose note already compares the two (backlog #543)
    STATED_NOTE,
)
CELL_NOTES = (
    # the run's own cost-of-debt year is one an interest caveat covers (backlog #542)
    HEDGE_NOTE,
    # the run's own cost-of-debt year is far from the company's stated rate (backlog #543)
    STATED_NOTE,
    "follows_risk_free",  # terminal growth equals the risk-free rate by the owner's method
    "computed_from_other_cells",  # params inputs: the rows it is computed from
    # a what-if child's cost of debt is the risk-free rate, not a book year (backlog #481)
    "floored_at_risk_free",
)
SERIES_NOTES = (
    "book_value",  # debt, cash and minority interest are the balance sheet's book values
    "overlapping_windows",  # beta: each month's 104 weeks share all but about 4 with the last
    "expanding_window",  # ERP: one more year each point, from the same first year
    # the debt card's second series: the filing's own fair value of its long-term debt, params
    # known_on, tag, left_out_dates (figures filed for a date that is not a balance date, so not
    # the total); or, when Warren reads none in the window, fair_value_not_read (#481 item 3)
    "fair_value_as_filed",
    "fair_value_not_read",
    # a market series read a download that is not the run's own (no kept download has the
    # hash the run stored), so the newest stored download was read instead; params
    # downloads: [{role, source, symbol, read_fetched_at, covers_run_date}] (backlog #601)
    "download_not_pinned",
)
# The run's three market downloads, by role (backlog #601)
DOWNLOAD_ROLES = ("price", "index", "yield")
# The filed fair value of long-term debt (concept_map_reported.csv): context beside book debt,
# never read by a valuation (backlog #481 item 3)
FAIR_VALUE_ITEM = "debt_fair_value"
FAIR_VALUE_TAG = "us-gaap:LongTermDebtFairValue"
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

    def _downloads(self) -> list[tuple[str, str, str, str]]:
        """The run's three market downloads: (role, source, symbol, runs column of its hash)."""
        from domains.market.prices import MARKET_INDEX
        from domains.market.yields import RISK_FREE_SERIES

        return [
            ("price", "yahoo", self.run["ticker"], "price_fetch_sha256"),
            ("index", "yahoo", MARKET_INDEX, "index_fetch_sha256"),
            ("yield", "fred", RISK_FREE_SERIES, "yield_fetch_sha256"),
        ]

    def _pin_map(self) -> dict:
        """The run's own downloads still stored, by (source, symbol); read once per answer."""
        if "pin_map" not in self.cache:
            from domains.market.store import MarketDataError, fetch_with_hash

            pins = {}
            for _role, source, symbol, column in self._downloads():
                try:  # pin each download the run names that is still stored
                    pins[(source, symbol)] = fetch_with_hash(
                        self.conn, source, symbol, self.run[column]
                    )["fetch_id"]
                except (MarketDataError, KeyError, IndexError, TypeError):
                    continue
            self.cache["pin_map"] = pins
        return self.cache["pin_map"]

    def unpinned(self) -> list[dict]:
        """Each of the run's downloads that could not be pinned (no kept download has the hash
        the run stored), so reads inside `pins()` take the newest stored download instead, the
        newest by `fetch_id` as `selected_fetch` reads it (backlog #601): its role, source and
        symbol; when that download was made (UTC, ISO); and whether it covers the run's date
        (made after that day ended in New York). Most reads refuse a download that does not cover
        their date (`require_coverage`), but the share series' split factor does not
        (`split_factor`), so a price download that stops before the run's date can miss a split
        silently: `covers_run_date` false says so (analyst). A symbol with no stored download
        at all is left out: its points already carry `market_data_not_loaded`, and a second
        message would say the same (product lead)."""
        if "unpinned" not in self.cache:
            from domains.market.store import covered_through, fetch_time, latest_fetch

            pins = self._pin_map()
            out = []
            for role, source, symbol, _column in self._downloads():
                if (source, symbol) in pins:
                    continue
                newest = latest_fetch(self.conn, source, symbol)
                if newest is None:
                    continue
                out.append(
                    {
                        "role": role,
                        "source": source,
                        "symbol": symbol,
                        "read_fetched_at": fetch_time(newest).isoformat(),
                        "covers_run_date": covered_through(newest) >= self.as_of,
                    }
                )
            self.cache["unpinned"] = out
        return self.cache["unpinned"]

    def unpinned_note(self, *roles: str) -> list[Coded]:
        """`download_not_pinned` for a series reading these downloads, or nothing when every
        one was the run's own (backlog #601)."""
        downloads = [d for d in self.unpinned() if d["role"] in roles]
        if not downloads:
            return []
        names = ", ".join(
            f"{d['role']} ({d['symbol']}, downloaded {d['read_fetched_at'][:10]}"
            + ("" if d["covers_run_date"] else ", before the run's date ended")
            + ")"
            for d in downloads
        )
        return [
            Coded(
                "download_not_pinned",
                {"downloads": downloads},
                f"the run's own download is no longer stored, so this is drawn on the newest "
                f"one: {names}; no point reads a date after its own, but the chart may differ "
                "from the one the run would draw",
            )
        ]

    def pins(self):
        """The run's own downloads, as `reproduce` pins them; none if one is no longer stored."""
        from domains.market.store import pin_fetches

        pins = self._pin_map()
        return pin_fetches(pins) if pins else nullcontext()

    def yield_pinned(self) -> bool:
        """Whether the run's own 10-year yield download is still stored, so a yield read inside
        `pins()` is the run's; otherwise it is the newest download (backlog #499). The yield's
        own pin, never "any pin"."""
        from domains.market.yields import RISK_FREE_SERIES

        return ("fred", RISK_FREE_SERIES) in self._pin_map()

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
        "debt": lambda: [_balance_series(singles, "debt"), _debt_fair_value(singles)],
    }
    if name not in builders:
        return None
    history = [_checked(s, cell_rows) for s in builders[name]()]
    notes = []
    if name == "cost_of_debt":
        notes = _cost_of_debt_cell_notes(singles, singles.cache.get("cost_of_debt_used_notes"))
    return Cell(name, cell_rows, history, None, notes)


def _cost_of_debt_cell_notes(singles: Singles, used_point) -> list[Coded]:
    """The `cost_of_debt` cell's notes: `floored_at_risk_free` on a floored what-if, else the
    used year's caveat note or its `far_from_stated_rate` (never both), so a screen showing only
    the run's figure has it too. `used_point` is the used year's point, or None."""
    if (floored := _floored_note(singles)) is not None:
        return [floored]
    if used_point is None:
        return []
    return [n for n in used_point.notes if n.code in (HEDGE_NOTE, STATED_NOTE)]


def _cached(singles: Singles, key: str, build):
    if key not in singles.cache:
        singles.cache[key] = build()
    return singles.cache[key]


def _checked(series, cell_rows):
    """Mark the primary series' used point when its value differs from the run's row (a run
    stored before a filing or a download changed the figure): `run_read_differently`."""
    from domains.analysis.inputs import Series, _fields_of

    if not series.primary or not cell_rows or cell_rows[0].value is None:
        return series
    points = [_read_differently(p, cell_rows[0].value) for p in series.points]
    return Series(**{**_fields_of(series), "points": points})


def _read_differently(p, run_value: float | None):
    """The point with `run_read_differently` added when it is the used one and its value
    differs from the run's row."""
    from domains.analysis.inputs import Point, _fields

    if (
        p.used
        and run_value is not None
        and p.value is not None
        and abs(p.value - run_value) > 1e-9 * max(1.0, abs(run_value))
    ):
        note = Coded(
            "run_read_differently",
            {"period": p.period, "run_value": run_value, "value": p.value},
            f"the run read {p.period} as {run_value:.6g}, not {p.value:.6g}",
        )
        p = Point(**{**_fields(p), "notes": [*p.notes, note]})
    return p


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

    return _monthly(singles, "risk_free_yield", at, singles.unpinned_note("yield"))


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
    return _monthly(singles, "beta", at, [overlap, *singles.unpinned_note("price", "index")])


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
    notes = [note, *singles.unpinned_note("index", "yield")]
    return Series("erp", "year", "latest", True, None, points, notes)


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
    start = _window_start(singles)
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


def _window_start(singles: Singles) -> date:
    return singles.as_of - timedelta(days=round(365.25 * singles.years))


def _debt_fair_value(singles: Singles):
    """The debt card's context series (backlog #481 item 3): the fair value of long-term debt
    each filing names (`LongTermDebtFairValue`), on its own balance dates in the book series'
    window, as known on the run's date (a later filing's restatement replaces the first figure).
    Never used by the valuation: `primary` and every point's `used` are false. When Warren reads
    no figure in the window the series is empty and says so (`fair_value_not_read`), never that
    the company does not disclose one."""
    from domains.analysis.inputs import Part, Point, Series
    from domains.fundamentals.facts import get_facts

    start = _window_start(singles)
    # only on the book series' balance dates: a figure filed for another date is not the
    # company's total (Coca-Cola's 9,345M at 2010-10-02, the day the CCE deal closed, the debt it
    # took on, beside its 2010-10-01 quarter end), so it is left out and its date listed
    balance_dates = {day for day, _ in _balances(singles)}
    newest = {}  # one figure per balance date: the newest filing's, as `latest` reads it
    left_out = set()
    for f in get_facts(singles.conn, singles.run["cik"], [FAIR_VALUE_ITEM], singles.as_of):
        if f.period_start is not None or not start < f.period_end < singles.as_of:
            continue
        if f.period_end not in balance_dates:
            left_out.add(f.period_end.isoformat())
            continue
        kept = newest.get(f.period_end)
        if kept is None or (f.filed_at, f.accession_no or "") > (
            kept.filed_at,
            kept.accession_no or "",
        ):
            newest[f.period_end] = f
    points = []
    for day in sorted(newest):
        f = newest[day]
        label = day.isoformat()
        part = Part(FAIR_VALUE_ITEM, f.value, label, _filing_of(singles, f.accession_no))
        points.append(Point(label, None, None, day, f.value, False, [part]))
    params = {
        "known_on": singles.as_of.isoformat(),
        "tag": FAIR_VALUE_TAG,
        "left_out_dates": sorted(left_out),
    }
    if points:
        note = Coded(
            "fair_value_as_filed",
            params,
            "the filing's own estimate of what its long-term debt (with the part due within a "
            "year) would be worth on that date, which moves when interest rates or the "
            "company's credit change; textbooks prefer it to book value, and the valuation uses "
            "book value as a proxy, which is fine while the two are close. It leaves out "
            "short-term borrowings and commercial paper, and often leases, so it is not the same "
            "debt as the book line: compare how the two move, not their gap. Many filings round it "
            "(to $0.1B), so a small move between dates means little",
        )
    else:
        note = Coded(
            "fair_value_not_read",
            params,
            "Warren reads no fair value of long-term debt for this company in the window; the "
            "filing may give it in its text or by instrument, which Warren does not read",
        )
    return Series("debt_fair_value", "quarter", "latest", False, None, points, [note])


def _cost_of_debt(singles: Singles):
    from domains.analysis.inputs import Series, _year_labels

    used_year = _cost_of_debt_used_year(singles)
    used_label = f"FY{used_year}" if used_year is not None else None
    last_quarter = singles.reader.latest(quarterly=True)
    last_year = max(singles.reader.latest(quarterly=False).fiscal_year, last_quarter.fiscal_year)
    labels = _year_labels(last_year, singles.years, {used_label} if used_label else set())
    points = []
    singles.cache["cost_of_debt_used_notes"] = None
    for label in labels:
        point = _cost_of_debt_point(singles, int(label[2:]), label == used_label)
        if point.used:
            # a screen showing only the run's figure has the used year's notes too
            singles.cache["cost_of_debt_used_notes"] = point
        points.append(point)
    return Series("cost_of_debt", "year", "latest", True, None, points)


def _cost_of_debt_window(singles: Singles) -> tuple[int, int] | None:
    """The first and last fiscal year of the cost-of-debt chart's window, read from the history
    alone (no fiscal calendar): the last year is the newer of the newest quarter's and the newest
    year's fiscal year, each the revenue figure with the latest period end known on the run's
    date, as the chart's reader takes them (`reported.latest_period`). None when either the
    quarterly or the annual facts hold no revenue figure, since the chart's reader then refuses
    and the chart has no window either (backlog #561, #565)."""
    last = None
    for facts in (singles.history.quarterly, singles.history.annual):
        revenue = [f for k, f in facts.items() if k[0] == "revenue" and f.period_start is not None]
        if not revenue:
            return None
        year = max(revenue, key=lambda f: f.period_end).fiscal_year
        last = year if last is None else max(last, year)
    return last - singles.years + 1, last


def _annual_revenue(history) -> list:
    """Every annual revenue figure with a period known on the run's date, oldest first, by end
    then start (two periods can share an end: Caterpillar FY2009-2010). The one order both
    `_filed_years` and `_newest_filed_year` read (backlog #569)."""
    revenue = [
        f for k, f in history.annual.items() if k[0] == "revenue" and f.period_start is not None
    ]
    return sorted(revenue, key=lambda f: (f.period_end, f.period_start))


def _filed_years(history) -> list[tuple[date, date]]:
    """The (start, end) of every fiscal year with an annual revenue figure known on the run's
    date, oldest first; the last is the newest year whose 10-K is out (as the chart's window
    reads it)."""
    return list(dict.fromkeys((f.period_start, f.period_end) for f in _annual_revenue(history)))


def _newest_filed_year(singles: Singles) -> tuple[int | None, int | None]:
    """(filed, read): `read` is the fiscal year of the newest annual revenue figure known on the
    run's date; `filed` is the newer of it and the newest fiscal year of a 10-K or 10-K/A filed
    on or before that date (`filing_labels`), so a 10-K whose revenue Warren does not read still
    counts as filed (backlog #569). Either is None when nothing is known."""
    revenue = _annual_revenue(singles.history)
    read = revenue[-1].fiscal_year if revenue else None
    row = singles.conn.execute(
        "SELECT MAX(fiscal_year) FROM filing_labels WHERE cik = ? AND form IN ('10-K', '10-K/A') "
        "AND fiscal_period = 'FY' AND filed_at <= ?",
        (singles.run["cik"], singles.as_of.isoformat()),
    ).fetchone()
    years = [y for y in (read, row[0]) if y is not None]
    return (max(years) if years else None), read


WEEK_YEAR_DAYS = (364, 371)  # a 52 or 53-week fiscal year
WEEK_YEAR_REACH = 3  # such a year ends on the weekday nearest its anchor date: at most 3 days off


def _week_year(filed: list[tuple[date, date]]) -> bool:
    """Whether the newest filed year is a 52 or 53-week year: 364 or 371 days long, counting
    both ends; or 365 or 372 when its start is tagged as the previous year's end (#569 item 2),
    and then only if the weekday repeats, its end a whole number of weeks after the previous
    filed end. A calendar year tagged from 1 January is 365 days long too, but its ends are 365
    or 366 days apart, never a whole number of weeks (over a year or two)."""
    start, end = filed[-1]
    days = (end - start).days + 1
    if days in WEEK_YEAR_DAYS:
        return True
    earlier = [e for _, e in filed if e < end]  # the previous distinct end (two can share one)
    if days - 1 not in WEEK_YEAR_DAYS or not earlier:
        return False
    gap = (end - max(earlier)).days
    return 0 < gap <= 2 * max(WEEK_YEAR_DAYS) and gap % 7 == 0


def _shifted(day: date, years: int) -> date:
    """`day` moved by whole years, kept at the month's end when it was one (29 February too)."""
    year = day.year + years
    if (day + timedelta(days=1)).day == 1:
        return _month_end(date(year, day.month, 1))
    return day.replace(year=year)


def _month_end(day: date) -> date:
    """The last day of `day`'s month."""
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1) - timedelta(days=1)


def _last_weekday_of_month(day: date) -> bool:
    """Whether `day` is the last of its weekday in its month (a week later is the next month)."""
    return (day + timedelta(days=7)).month != day.month


def _last_weekday_rule(filed: list[tuple[date, date]]) -> bool:
    """Whether every filed end is the last of its weekday in one and the same month."""
    return len({e.month for _, e in filed}) == 1 and all(
        _last_weekday_of_month(e) for _, e in filed
    )


def _nearest_month_end_offset(day: date) -> int:
    """Days from `day` to the month end nearest it (its own month's, or the month before's)."""
    own, before = _month_end(day), day.replace(day=1) - timedelta(days=1)
    return min(((own - day).days, (before - day).days), key=abs)


def expected_year_end(filed: list[tuple[date, date]], years_ahead: int) -> date:
    """The expected end of the fiscal year `years_ahead` after the newest filed one, read only
    from the filed years' own periods, `filed` as (start, end) oldest first (point-in-time;
    backlog #564).

    A calendar-month year ends on the same day, kept at the month's end when it ended on one
    (Walmart's 31 January; 29 February falls to the 28th).

    A 52 or 53-week year (the newest is 364 or 371 days long) ends, under 26 U.S.C. §441(f) and
    Treas. Reg. §1.441-2(a)(1), on a given weekday either (i) the last time it occurs in a
    calendar month (Apple: the last Saturday of September), which can be six days before the
    month's end, or (ii) nearest the last day of a calendar month (Johnson & Johnson: the Sunday
    nearest 31 December, which can fall in January). Both are tried first (backlog #574):
    - (ii) fits when the month end nearest the newest end lies within three days of every filed
      end; the expected end is then the weekday nearest that month end in the target year, so
      February's follows leap years;
    - (i) fits when every filed end is the last of its weekday in one and the same month; the
      expected end is that weekday's last day in the target month.
    Both fit only when every filed end sits in its month's last four days, and then nothing in
    the filings tells them apart yet. That case, and a calendar that fits neither form (not a
    §441(f) year as filed: a changed calendar, or a tag Warren misread), fall back to a band: an
    anchor date within three days of every filed end, taken as the middle of the dates all of
    them allow (the later of two middle days). With few years the band is wide and its middle a
    guess, and when no date fits every end the newest end alone is the anchor, a week early
    before a 53-week year. Either way the answer is an estimate until the 10-K is filed."""
    if years_ahead < 1:
        raise ValueError(f"years_ahead must be at least 1, got {years_ahead}")
    if not filed:
        raise ValueError("no filed fiscal year to read forward from")
    start, end = filed[-1]
    target = _shifted(end, years_ahead)
    if not _week_year(filed):
        return target
    # each older end as days from the newest end's date in the same year (the nearest whole year)
    offsets = []
    for _, older in filed:
        back = round((end - older).days / 365.2425)
        offsets.append((older - _shifted(end, -back)).days)
    low, high = max(offsets) - WEEK_YEAR_REACH, min(offsets) + WEEK_YEAR_REACH
    nearest_fits = low <= _nearest_month_end_offset(end) <= high
    last_fits = _last_weekday_rule(filed)
    if nearest_fits and not last_fits:
        # the weekday nearest a month's end, and only it, fits every filed end: that month end,
        # in the target year (so February's moves with leap years), is the anchor
        anchor = target + timedelta(days=_nearest_month_end_offset(target))
    elif last_fits and not nearest_fits:
        last = _month_end(target)  # the last weekday of the target month, read exactly
        return last - timedelta(days=(last.weekday() - end.weekday()) % 7)
    elif low <= high:
        # the middle of the band; of two middle days the later (Apple's FY2017 from 2009-2016)
        anchor = target + timedelta(days=-((-low - high) // 2))
    else:
        anchor = target
    shift = (end.weekday() - anchor.weekday()) % 7  # days forward to the same weekday
    return anchor + timedelta(days=shift if shift <= 3 else shift - 7)


def _cost_of_debt_used_year(singles: Singles) -> int | None:
    """The fiscal year the run's cost of debt was read from; None on a what-if child whose
    changed cost of debt is not a book year (backlog #481)."""
    interest = _interest_source(singles.stored.get(("cost_of_debt", SINGLE), []))
    return interest["fiscal_year"] if interest else None


def _cost_of_debt_point(singles: Singles, year: int, used: bool):
    """One fiscal year's cost-of-debt point with its parts and notes (`below_risk_free`, or the
    caveat's note in its place), or its `not_computable` reason. The chart's series and
    `cost_of_debt_notes` both build their points here, so the two cannot drift (backlog #550)."""
    from domains.analysis.inputs import Part, Point
    from domains.analysis.interest_caveats import caveat_for
    from domains.analysis.math_engine import EngineError, cost_of_debt_year, resolve

    label = f"FY{year}"
    found = cost_of_debt_year(singles.history, year)
    if found is None:
        params = {"fiscal_year": year}
        # fixed for a run (its CIK and date), so read once per answer, not per year (#575)
        filed_year, read_year = _cached(
            singles, "newest_filed_year", lambda: _newest_filed_year(singles)
        )
        if read_year is not None and year > filed_year:  # read_year set: filed_year is too
            # the expected end reads forward from the years whose periods Warren has
            end = expected_year_end(_filed_years(singles.history), year - read_year)
            reason = "not_filed_yet"
            params["period_end"] = end.isoformat()
            why = f"{label}'s annual report was not filed by the run's date (expected end {end})"
        else:
            try:
                resolve("interest", singles.history.year(year), label)
                reason, why = "average_debt_not_positive", f"{label}'s average debt is zero"
            except EngineError:
                reason, why = "no_interest_reported", f"{label} reports no interest"
        missing = Coded(NOT_COMPUTABLE, {"reason": reason, **params}, why)
        return Point(label, year, "FY", None, None, used, missing=missing)
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
    period_start = paid.facts[0].period_start if paid.facts else None
    notes = _below_risk_free(singles, kd, used, period_end, period_start)
    caveat = caveat_for(singles.run["ticker"], year)
    if caveat is not None and caveat.code == HEDGE_NOTE:
        # the run's own row on the used year, as `below_risk_free` compares (product lead)
        shown = _run_row(singles, "cost_of_debt") if used else kd
        # `below_risk_free`'s sentence gives the wrong cause here (#542)
        notes = [_hedge_note(singles, caveat, year, shown, period_end, notes)]
    else:
        # the run's own row on the used year, as `below_risk_free` compares (product lead, #542)
        shown = _run_row(singles, "cost_of_debt") if used else kd
        notes += _stated_rate_note(singles, year, shown, opening, closing)
    return Point(label, year, "FY", period_end, kd, used, parts, notes)


def _refuse_outside_window(singles: Singles, fiscal_year: int) -> None:
    """`year_outside_window` for a year the cost-of-debt chart does not show (backlog #561)."""
    from domains.analysis.inputs import InputsError

    window = _cost_of_debt_window(singles)
    if window is not None and window[0] <= fiscal_year <= window[1]:
        return
    first, last = window or (None, None)
    shown = f"FY{first} to FY{last}" if window else "none: no revenue filed"
    raise InputsError(
        f"FY{fiscal_year} is not on the cost-of-debt chart ({shown}) and is not the run's own year",
        "year_outside_window",
        {
            "fiscal_year": fiscal_year,
            "first_year": first,
            "last_year": last,
            "years": singles.years,
        },
    )


@dataclass(frozen=True)
class CostOfDebtNotes:
    """One fiscal year's cost-of-debt point and the cell's notes, as `inputs_behind` gives them
    (backlog #550)."""

    run_id: str
    fiscal_year: int | None  # the year asked, or the run's own; None when it has no book year
    point: "Point | None"  # equal to the chart's point for that year; None as above
    cell_notes: list[Coded]  # the `cost_of_debt` cell's notes

    def to_dict(self) -> dict:
        """Plain JSON types, as `InputsBehind.to_dict`: dates as ISO text, numbers unrounded."""
        from dataclasses import asdict

        from domains.analysis.reported import _plain

        return _plain(asdict(self))


def cost_of_debt_notes(
    conn: sqlite3.Connection,
    run_id: str,
    fiscal_year: int | None = None,
    years: int | None = None,
) -> CostOfDebtNotes:
    """The cost-of-debt notes for one fiscal year of a run, without building the rest of the
    answer (backlog #550, for the app): the year's point (value, parts, `below_risk_free` or the
    caveat's note, `run_read_differently` on the used year, or its `not_computable` reason) and
    the cell's notes. `fiscal_year` None means the run's own year. Built by the same functions as
    the chart's series, on the filings known on the run's date (and, for a year other than the
    run's own, the 10-year yields over that year, as the chart reads them).

    Only a year the chart shows (`years` fiscal years, as `inputs_behind`'s `years`, default
    `inputs.DEFAULT_YEARS`) or the run's own is answered; any other is refused with `InputsError`
    code `year_outside_window` (params `fiscal_year`, `first_year`, `last_year`, `years`; the
    bounds are None when the history has no revenue figure), since a year after the newest
    filing known on the run's date would read `no_interest_reported`, "not filed yet" shown as
    "reported none" (backlog #561). The window is read from the history, not the fiscal
    calendar, so the call stays cheap. The call assumes the run has a `cost_of_debt` row
    (every run stores one) that is not an owner choice (`cost_of_debt` is not one today), where
    `inputs_behind` would give no history. Refuses with `InputsError` (`run_not_found`,
    `concepts_not_synced`, `years_out_of_range`) as `inputs_behind` does."""
    from domains.analysis import sources as src
    from domains.analysis.inputs import DEFAULT_YEARS, InputsError, check_years
    from domains.analysis.reported import _Filings
    from domains.fundamentals.facts import ConceptsNotSyncedError

    years = DEFAULT_YEARS if years is None else years
    check_years(years)
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise InputsError(f"no run {run_id}", "run_not_found", {"run_id": run_id})
    as_of = date.fromisoformat(run["as_of"])
    stored = src.load(conn, run_id)
    # no reader: one year's point needs no fiscal calendar, only the history and the filings
    singles = Singles(conn, run, as_of, years, stored, None, _Filings(conn, run["cik"]))
    try:
        used_year = _cost_of_debt_used_year(singles)
        if fiscal_year is not None and fiscal_year != used_year:
            _refuse_outside_window(singles, fiscal_year)
        run_value = _run_row(singles, "cost_of_debt")
        used = None
        if used_year is not None:
            used = _read_differently(_cost_of_debt_point(singles, used_year, True), run_value)
        year = used_year if fiscal_year is None else fiscal_year
        if year is None:
            point = None
        elif year == used_year:
            point = used
        else:
            point = _cost_of_debt_point(singles, year, False)
        cell_notes = _cost_of_debt_cell_notes(singles, used)
    except ConceptsNotSyncedError as e:  # one coded refusal, as `inputs_behind` (backlog #548)
        raise InputsError(str(e), e.code, dict(e.params)) from e
    return CostOfDebtNotes(run_id, year, point, cell_notes)


# How many fiscal years older than the point a stated rate may be and still stand beside it: a
# company that stops stating the rate (J&J's FY2025 10-K) would otherwise show an old rate for good
# (analyst, #542)
RATE_MAX_YEARS_OLDER = 1


def _effective_rate(singles: Singles, item: str, period_end: date | None, year: int):
    """The company's stated rate at this year end as known on `as_of` (the newest filing's
    version), else the newest one at an earlier year end at most `RATE_MAX_YEARS_OLDER` fiscal
    years older; None when there is none."""
    from domains.fundamentals.facts import get_facts

    if period_end is None:
        return None
    newest = {}
    for f in get_facts(singles.conn, singles.run["cik"], [item], singles.as_of):
        if f.period_start is not None or f.period_end > period_end or f.filed_at > singles.as_of:
            continue
        kept = newest.get(f.period_end)
        if kept is None or (f.filed_at, f.accession_no or "") > (
            kept.filed_at,
            kept.accession_no or "",
        ):
            newest[f.period_end] = f
    if not newest:
        return None
    rate = newest[max(newest)]
    if rate.period_end != period_end and (
        rate.fiscal_year is None or year - rate.fiscal_year > RATE_MAX_YEARS_OLDER
    ):
        return None
    return rate


def _hedge_note(
    singles: Singles, caveat, year: int, kd: float | None, period_end, below: list
) -> Coded:
    """`interest_net_of_hedge_gains` (backlog #542): the year's interest line is net of what the
    company's currency swaps earn (interest_caveats.csv), with the rate it states on its
    long-term debt beside. `below_risk_free` is not shown on its own here, since its cause (old,
    lower rates) is the wrong one; its params stay inside, or None. `evidence_filings` lists the
    data file's filings known on the run's date."""
    rate = (
        _effective_rate(singles, caveat.rate_item, period_end, year) if caveat.rate_item else None
    )
    params = {
        "fiscal_year": year,
        "from_fiscal_year": caveat.from_fiscal_year,
        "to_fiscal_year": caveat.to_fiscal_year,
        "cost_of_debt": kd,
        "effective_rate": rate.value if rate else None,
        "effective_rate_period": rate.period_end.isoformat() if rate else None,
        "effective_rate_fiscal_year": rate.fiscal_year if rate else None,
        # true when the rate is from an earlier year end than the point's (at most one year)
        "effective_rate_older": (rate.period_end != period_end) if rate else None,
        "effective_rate_filing": _filing_of(singles, rate.accession_no) if rate else None,
        "below_effective_rate": (kd < rate.value) if rate and kd is not None else None,
        "below_risk_free": dict(below[0].params) if below else None,
        # the filings the data file cites for the caveat, each only when Warren knows it was
        # filed on or before the run's date (backlog #551); an unknown accession is left out
        "evidence_filings": [
            _filing_of(singles, a)
            for a in caveat.accessions
            if (filed := singles.filings.get(a).filed_at) is not None and filed <= singles.as_of
        ],
    }
    shown = "this cost of debt" if kd is None else f"this cost of debt ({kd:.2%})"
    if rate:
        when = (
            f"at the {rate.period_end.isoformat()} year end; long-term debt only"
            if rate.period_end == period_end
            else f"at the {rate.period_end.isoformat()} year end, a year older, the newest it "
            "states; long-term debt only"
        )
        beside = (
            f"so {shown} reads below the {rate.value:.2%} weighted average "
            f"effective rate it states on its long-term debt ({when})"
            if params["below_effective_rate"]
            else f"so {shown} is not like for like with the "
            f"{rate.value:.2%} weighted average effective rate it states on its long-term debt "
            f"({when})"
        )
    else:
        beside = f"so {shown} mixes dollar and foreign-currency borrowing costs"
    return Coded(
        HEDGE_NOTE,
        params,
        f"the interest expense is net of what the company's currency swaps earn (booked in its "
        f"interest line since FY{caveat.from_fiscal_year}): the swaps turn part of its dollar "
        f"debt into lower-rate foreign-currency debt, {beside}; a valuation in dollars needs a "
        "dollar cost of debt, and Warren cannot yet separate the two",
    )


# How far a year's book cost of debt may sit from the rate the company states on its own debt
# before the chart says so: one percentage point, a Warren working rule chosen from Coca-Cola's,
# P&G's and J&J's years (backlog #543 design doc): P&G's quiet years stay within 0.65 points of
# their two-year-end average, while J&J's hedge-netted years and Coca-Cola's FY2020 and FY2021,
# whose interest line holds charges for repaying debt early, are 1.4 points or more away. Stated
# rates are rounded (Coca-Cola's to 0.1%), so a gap of a few tenths says nothing.
STATED_RATE_GAP = 0.01


def _stated_rate_on(singles: Singles, item: str, day: date):
    """The company's stated rate dated exactly `day` (a year end), as known on `as_of` (the
    newest filing's version); None when there is none. Each item's facts are read once per
    answer."""
    from domains.fundamentals.facts import get_facts

    def read():
        newest = {}
        for f in get_facts(singles.conn, singles.run["cik"], [item], singles.as_of):
            if f.period_start is not None or f.filed_at > singles.as_of:
                continue
            kept = newest.get(f.period_end)
            if kept is None or (f.filed_at, f.accession_no or "") > (
                kept.filed_at,
                kept.accession_no or "",
            ):
                newest[f.period_end] = f
        return newest

    return _cached(singles, f"stated_rate:{item}", read).get(day)


def _stated_year_end(singles: Singles, rates, total: float, debt: list) -> dict | None:
    """One year end's stated rate, blended by the debt Warren counted there (`debt`, whose
    values add up to `total`): the short-term rate on the part `rates.short_rate_covers` names,
    the long-term rate on the rest, or the long-term rate on all of it when the company states
    no short-term rate Warren reads. None when the year end has no long-term rate, its debt is
    not above zero, or a short-term rate is stated for it but not at this year end."""
    from domains.analysis.stated_debt_rates import SHORT_RATE_COVERS

    if not debt or total <= 0:
        return None
    day = max(f.period_end for f in debt)
    long_rate = _stated_rate_on(singles, rates.long_rate_item, day)
    if long_rate is None:
        return None
    short_rate, short = None, 0.0
    if rates.short_rate_item is not None:
        covered = SHORT_RATE_COVERS[rates.short_rate_covers]
        short = sum(f.value for f in debt if f.canonical_name in covered and f.value > 0)
        if short > 0:
            short_rate = _stated_rate_on(singles, rates.short_rate_item, day)
            if short_rate is None:
                return None
    short = min(short, total)
    rate = fm.blended_rate(
        long_rate.value,
        total - short,
        short_rate.value if short_rate is not None else long_rate.value,
        short,
    )
    return {
        "period_end": day.isoformat(),
        "stated_rate": rate,
        "long_term_rate": long_rate.value,
        # None: no short-term debt at this year end, or no short-term rate stated (then the
        # long-term rate stands for all the debt; `short_rate_covers` None says which)
        "short_term_rate": short_rate.value if short_rate is not None else None,
        # the share of this year end's debt the short-term rate covers (0 when it covers none)
        "short_term_share": short / total if short_rate is not None else 0.0,
        "long_term_rate_filing": _filing_of(singles, long_rate.accession_no),
        "short_term_rate_filing": (
            _filing_of(singles, short_rate.accession_no) if short_rate is not None else None
        ),
    }


def _stated_rate_note(
    singles: Singles, year: int, kd: float | None, opening: list, closing: list
) -> list[Coded]:
    """`far_from_stated_rate` (backlog #543): a year's book cost of debt more than
    `STATED_RATE_GAP` from the rate the company states on its own debt, averaged over the
    year's two year ends (the closing one alone when the opening has no stated rate or no debt),
    each blended by the debt Warren counted there (`_stated_year_end`). Interest over average
    debt is a flow over the year and a stated rate is a year end's, so the average of both ends
    is the fairer comparison (analyst, #543). Nothing filed after `as_of`; no number changes."""
    from domains.analysis.stated_debt_rates import stated_rates_for

    rates = stated_rates_for(singles.run["ticker"])
    if rates is None or kd is None:
        return []
    ends = []
    for debt in (opening, closing):
        found = _stated_year_end(singles, rates, sum(f.value for f in debt), debt)
        if found is not None:
            ends.append(found)
    closing_day = max((f.period_end for f in closing), default=None)
    if not ends or ends[-1]["period_end"] != (closing_day.isoformat() if closing_day else None):
        return []  # the closing year end is the one the check needs
    stated = fm.mean([e["stated_rate"] for e in ends])
    gap = kd - stated
    if abs(gap) <= STATED_RATE_GAP:
        return []
    side = "below" if gap < 0 else "above"
    return [
        Coded(
            STATED_NOTE,
            {
                "fiscal_year": year,
                "cost_of_debt": kd,
                "stated_rate": stated,
                "gap": gap,  # cost_of_debt − stated_rate: below zero when the book rate is lower
                "threshold": STATED_RATE_GAP,
                "short_rate_covers": rates.short_rate_covers,
                "year_ends": ends,  # oldest first; one when only the closing year end has a rate
            },
            f"the book cost of debt ({kd:.2%}, interest over average book debt) is "
            f"{abs(gap) * 100:.2f} percentage points {side} the {stated:.2%} the company states "
            f"on its own debt (weighted average rates, the mean of {len(ends)} year end"
            f"{'s' if len(ends) > 1 else ''}, blended by the debt Warren counted there): "
            "something besides interest on the debt is likely inside the interest line, such as "
            "hedge gains or charges for repaying debt early",
        )
    ]


def _interest_source(sources: list) -> dict | None:
    return next(
        (s for s in sources if s["kind"] == "filing" and s["item"].startswith("interest")), None
    )


def _floored_note(singles: Singles):
    """`floored_at_risk_free` on a what-if child whose cost of debt the debt change floored at
    the child's own risk-free row (`whatif._leverage_rows`; backlog #481): the value is that row
    (itself a what-if value when `risk_free_changed`), and the parent's book cost of debt and
    its fiscal year (None when the parent's sources name no interest filing) say what it
    replaced. A child of a parent stored before sources were recorded has no sources at all
    (`whatif.revalue`), so it gets no note, not one with `book_year` None; its cell still shows
    the floor, its own row (backlog #499)."""
    sources = singles.stored.get(("cost_of_debt", SINGLE), [])
    floored = next(
        (s for s in sources if s["kind"] == "what_if" and s.get("how") == "floored_at_risk_free"),
        None,
    )
    if floored is None:
        return None
    value = _run_row(singles, "cost_of_debt")
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


def _run_row(singles: Singles, name: str) -> float | None:
    row = singles.conn.execute(
        "SELECT value FROM assumptions WHERE run_id = ? AND name = ? AND period = ?",
        (singles.run["run_id"], name, SINGLE),
    ).fetchone()
    return None if row is None else row["value"]


def _run_risk_free(singles: Singles):
    """The run's own risk-free row and the date of its DGS10 observation (its stored source)."""
    value = _run_row(singles, "risk_free")
    if value is None:
        return None
    source = next(
        (s for s in singles.stored.get(("risk_free", SINGLE), []) if s["kind"] == "market"),
        None,
    )
    return value, source["end"] if source else None


def _below_risk_free(
    singles: Singles,
    kd: float,
    used: bool,
    period_end: date | None,
    period_start: date | None = None,
) -> list:
    """`below_risk_free` when a year's book (embedded) cost of debt is strictly below the 10-year
    Treasury yield (backlog #481): the used year against the run's own risk-free row (the rate
    in the same WACC, and the row `whatif._would_floor` compares with), every other year against
    the average 10-year yield over that fiscal year (interest over average debt is a flow over
    the year, so one day's yield is not like for like; analyst, #481). Nothing after `as_of`.

    The fiscal year is the interest fact's own period, `period_start` to `period_end`, so a
    53-week year reads its first week and a 52-week year reads no day of the year before
    (backlog #499); 364 days before the end only when the fact has no start."""
    from domains.market.store import MarketDataError
    from domains.market.yields import yields_through

    if used:
        found = _run_risk_free(singles)
        if found is None:
            return []
        rf, rf_date = found
        # the run's own row, so the note agrees with the what-if floor's test on the same two
        # stored values (`whatif._would_floor`; analyst, #481), even on an older run whose
        # year now reads differently (`run_read_differently` says so)
        kd = _run_row(singles, "cost_of_debt")
        extra = {"against": "run_risk_free"}
        benchmark = f"the run's own risk-free rate, on {rf_date}"
    else:
        if period_end is None or period_end >= singles.as_of:
            return []
        try:
            with singles.pins():
                first = period_start or period_end - timedelta(days=364)
                obs = yields_through(singles.conn, first, period_end)
        except MarketDataError:
            return []
        if not obs:
            return []
        rf, rf_date = fm.mean([o.rate for o in obs]), obs[-1].date.isoformat()
        extra = {
            "against": "year_average_yield",
            "risk_free_from": obs[0].date.isoformat(),
            "observations": len(obs),
            # false: the run's yield download is no longer stored, so the newest was read
            "yield_fetch_pinned": singles.yield_pinned(),
        }
        benchmark = f"its average from {obs[0].date.isoformat()} to {rf_date}"
    if kd is None or not kd < rf:
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
    """Every cover-page count, every quarter's diluted count and every fiscal year's diluted count
    in the window, on the run's share basis (split-adjusted to the run's price date with the
    engine's basis rule). The engine's fallback reads both diluted frequencies, newest first, so
    the count it used is in one of the two diluted series (backlog #481)."""
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
            # a 10-K may file a fourth quarter's count beside the year's, on the same date
            and counted.get("fiscal_period", fact.fiscal_period) == fact.fiscal_period
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

    def diluted_facts(facts):
        return sorted(
            (f for f in facts if start < f.period_end and f.value > 0),
            key=lambda f: f.period_end,
        )

    cover = [
        point(f, f.period_end.isoformat(), (None, None))
        for f in history.instants.get("shares_outstanding", [])
        if start < f.period_end <= singles.as_of and f.value > 0
    ]
    quarterly = diluted_facts(
        f for (n, _y, _p), f in history.quarterly.items() if n == "diluted_shares"
    )
    annual = diluted_facts(f for (n, _y), f in history.annual.items() if n == "diluted_shares")
    diluted = [
        point(f, _label(f.fiscal_year, f.fiscal_period), (f.fiscal_year, f.fiscal_period))
        for f in quarterly
    ]
    yearly = [point(f, _label(f.fiscal_year, "FY"), (f.fiscal_year, "FY")) for f in annual]
    diluted = sorted(
        diluted + _fourth_quarter_gaps(quarterly, annual),
        key=lambda p: (p.fiscal_year, _quarter_number(p.fiscal_period)),
    )
    cover_used = bool(counted and counted["item"] == "shares_outstanding")
    # every point's split factor reads the company's price download (backlog #601)
    split_notes = singles.unpinned_note("price")
    return [
        Series("shares_outstanding", "date", "latest", cover_used, None, cover, split_notes),
        Series(
            "diluted_shares",
            "quarter",
            "latest",
            any(p.used for p in diluted),
            None,
            diluted,
            list(split_notes),
        ),
        Series(
            "diluted_shares",
            "year",
            "latest",
            any(p.used for p in yearly),
            None,
            yearly,
            list(split_notes),
        ),
    ]


def _quarter_number(fiscal_period: str) -> int:
    """1 to 4 for `Q1` to `Q4`, so the quarterly series sorts on the quarter's number, not on its
    label's spelling; any other label is refused rather than placed by a string compare
    (gatekeeper, #502)."""
    if fiscal_period not in ("Q1", "Q2", "Q3", "Q4"):
        raise ValueError(f"not a fiscal quarter: {fiscal_period!r}")
    return int(fiscal_period[1])


def _fourth_quarter_gaps(quarterly: list, annual: list) -> list:
    """A point with no value for each fiscal year whose fourth quarter has ended in the filings
    (the year's own count is read, or a later year's) but has no quarterly count: a 10-K files the
    year's weighted count, not the fourth quarter's, and Warren never derives one. The year minus
    three quarters is not exact for diluted counts: each period is tested for anti-dilution on its
    own and a loss quarter counts no potential shares (ASC 260-10-45-20, IAS 33.41-44), and
    quarters can differ in length. Only years with a quarterly count in the window get a gap, so
    the series never opens on one (analyst)."""
    from domains.analysis.inputs import Point

    have = {f.fiscal_year for f in quarterly if f.fiscal_period != "Q4"}
    q4 = {f.fiscal_year for f in quarterly if f.fiscal_period == "Q4"}
    by_year = {f.fiscal_year: f for f in annual}
    latest = max((f.fiscal_year for f in (*quarterly, *annual)), default=None)
    gaps = []
    for year in sorted(have - q4):
        year_count = by_year.get(year)
        if year_count is None and year >= latest:
            continue  # the year may still be open: its fourth quarter is not due yet
        annual_period = f"FY{year}" if year_count is not None else None
        why = (
            f"FY{year}'s 10-K files the year's weighted diluted count ({annual_period}, in the "
            "yearly series), not the fourth quarter's; Warren does not derive one"
            if annual_period
            # the 10-K may be filed with a count Warren's concept map does not read (Exxon's FY2009
            # and FY2010), so the text never says the company did not file it (analyst)
            else f"FY{year}Q4 has no diluted count of its own, and Warren read no count for "
            f"FY{year} from the filings"
        )
        missing = Coded(
            NOT_COMPUTABLE,
            {"reason": "no_fourth_quarter_count", "fiscal_year": year,
             "annual_period": annual_period},
            why,
        )  # fmt: skip
        end = year_count.period_end if year_count is not None else None
        gaps.append(Point(f"FY{year}Q4", year, "Q4", end, None, False, missing=missing))
    return gaps


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
