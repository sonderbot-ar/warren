"""From point-in-time facts and market data to the assumption rows of a baseline DCF (Decision 4).

Every number a run uses becomes an assumption row with its rule, tags and filings in `method`, so
dcf.value() can value the run from its rows alone and any number traces back to a filing. The
rules are the owner decisions of the build plan (M2, D2-D8, D11) and are the same for every
company: there are no per-company exceptions.

- History rows (`history:<item>`) hold the reported values the drivers are computed from.
- Fallbacks (D8) apply only when the primary item is missing; if both are missing the run fails,
  naming the item, the period and every alternative tried.
- Optional items (securities, leases, commercial paper) missing near the balance date count as
  zero, with a warning; required ones fail the run.
"""

import csv
import math
import sqlite3
import warnings
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from domains.analysis import financial_math as fm
from domains.analysis.dcf import QUARTERS, SEED, YEARS
from domains.analysis.schemas import SINGLE, Assumption
from domains.fundamentals.concepts import concept_map_sha256
from domains.fundamentals.facts import get_facts, same_filing_annual_comparisons
from domains.fundamentals.quality import CONSISTENCY_TOLERANCE
from domains.fundamentals.schemas import Fact
from domains.fundamentals.universe import FISCAL_YEARS
from domains.market.erp import equity_risk_premium
from domains.market.prices import MARKET_INDEX, PricePoint, aligned_weekly_returns, raw_close
from domains.market.prices import split_factor as price_split_factor
from domains.market.store import selected_fetch
from domains.market.yields import RISK_FREE_SERIES, risk_free_rate

USER_ASSUMPTIONS_PATH = Path(__file__).parent / "user_assumptions.csv"
USER_CHOICES = {
    "erp_method": {"historical_geometric"},
    "erp_first_year": None,  # a year
    "terminal_growth_method": {"risk_free"},
}

SUPPORTED_FROM = date(2019, 3, 1)  # three full fiscal years of FY2016+ history behind it
HISTORY_YEARS = 3
HISTORY_QUARTERS = 12
MIN_QUARTERS_PER_LABEL = 2
BETA_WEEKS = 104  # 2 years of weekly returns (D6)
COMPONENT_MAX_AGE = timedelta(days=370)  # a balance older than this before the balance date is 0
STALE_AFTER = timedelta(days=135)  # last reported quarter this long before as_of: warn
TAX_RATE_BOUNDS = (0.0, 0.5)
COST_OF_DEBT_BOUNDS = (0.0, 0.15)
SHARES_TOLERANCE = 0.10  # cover-page vs diluted shares
TERMINAL_SHARE_WARNING = 0.75
MARGIN_SIGMAS = 2
ERP_INFO_FIRST_YEARS = (1999, 2009)  # alternative windows, shown for information only

# Alternatives, in order: the first whose items are all reported is used (D8).
CHAINS: dict[str, list[tuple[str, ...]]] = {
    "ebit": [("operating_income",), ("pretax_income", "interest_expense")],
    "d_and_a": [("depreciation_amortization",), ("depreciation", "amortization_intangibles")],
    "pretax": [
        ("pretax_income",),
        ("pretax_income_domestic", "pretax_income_foreign"),
        ("net_income_including_nci", "income_tax_expense"),
    ],
    "interest": [("interest_expense",), ("interest_paid",)],
    "revenue": [("revenue",)],
    "capex": [("capex",)],
    "tax": [("income_tax_expense",)],
}
BALANCE_ITEMS = (
    "current_assets",
    "current_liabilities",
    "cash",
    "marketable_securities_current",
    "marketable_securities_noncurrent",
    "other_short_term_investments",
    "debt_current",
    "debt_noncurrent",
    "short_term_borrowings",
    "commercial_paper",
    "finance_lease_liabilities",
    "minority_interest",
)
REQUIRED_BALANCE = {"current_assets", "current_liabilities", "cash"}
SHARE_ITEMS = ("shares_outstanding", "diluted_shares")
ITEMS = sorted({n for chain in CHAINS.values() for alt in chain for n in alt})
ITEMS += [*BALANCE_ITEMS, *SHARE_ITEMS]


class EngineError(ValueError):
    """A run can't be built: a required input is missing or the data breaks an invariant."""


# -- user assumptions --------------------------------------------------------------------------


@dataclass(frozen=True)
class UserChoice:
    name: str
    value: str
    set_by: str
    set_on: str
    note: str

    def as_assumption(self) -> Assumption:
        try:
            number = float(self.value)
        except ValueError:
            number = None
        return Assumption(
            name=self.name,
            period=SINGLE,
            value=number,
            source="user",
            method=f"{self.value}: set by {self.set_by} on {self.set_on}. {self.note}",
        )


def load_user_assumptions(path: Path = USER_ASSUMPTIONS_PATH) -> dict[str, UserChoice]:
    """The owner's choices; a missing, unknown or invalid one is an error, never a default."""
    choices = {}
    with open(path, newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            if None in row or None in row.values():
                raise EngineError(f"{path.name} line {line}: wrong number of fields")
            choice = UserChoice(**{k: v.strip() for k, v in row.items()})
            if choice.name not in USER_CHOICES:
                raise EngineError(f"{path.name} line {line}: unknown assumption {choice.name}")
            allowed = USER_CHOICES[choice.name]
            if allowed is None and not choice.value.isdigit():
                raise EngineError(f"{path.name} line {line}: {choice.name} must be a year")
            if allowed is not None and choice.value not in allowed:
                raise EngineError(
                    f"{path.name} line {line}: {choice.name} must be one of {allowed}"
                )
            if not (choice.set_by and choice.set_on):
                raise EngineError(f"{path.name} line {line}: {choice.name} needs set_by and set_on")
            choices[choice.name] = choice
    missing = sorted(set(USER_CHOICES) - set(choices))
    if missing:
        raise EngineError(f"{path.name}: the owner has not set {missing}")
    return choices


# -- point-in-time history ---------------------------------------------------------------------


def _tag(fact: Fact) -> str:
    return fact.xbrl_concept.replace("us-gaap:", "").replace("dei:", "")


def trace(fact: Fact) -> str:
    """Item, tag, period and filing of one fact: enough to find it in EDGAR."""
    source = fact.accession_no or "derived from " + ", ".join(fact.inputs)
    return f"{fact.canonical_name} [{_tag(fact)}] {fact.period_end} {source}"


@dataclass(frozen=True)
class Resolved:
    value: float
    method: str  # which alternative, with each fact's trace
    fallback: bool


def resolve(chain: str, get: Callable[[str], Fact | None], where: str) -> Resolved:
    alternatives = CHAINS[chain]
    for i, items in enumerate(alternatives):
        facts = [get(item) for item in items]
        if all(f is not None for f in facts):
            method = "; ".join(map(trace, facts))
            if i:
                method = f"fallback: {' + '.join(items)} = {method}"
            return Resolved(sum(f.value for f in facts), method, fallback=i > 0)
    tried = " | ".join(" + ".join(items) for items in alternatives)
    raise EngineError(f"{chain} for {where}: none of the alternatives is reported ({tried})")


@dataclass
class History:
    quarterly: dict[tuple[str, int, str], Fact]
    annual: dict[tuple[str, int], Fact]
    instants: dict[str, list[Fact]]  # balance-sheet facts by item, oldest first

    def quarter(self, fiscal_year: int, period: str) -> Callable[[str], Fact | None]:
        return lambda item: self.quarterly.get((item, fiscal_year, period))

    def year(self, fiscal_year: int) -> Callable[[str], Fact | None]:
        return lambda item: self.annual.get((item, fiscal_year))

    def latest_before(self, item: str, day: date) -> Fact | None:
        """The newest balance of an item dated on or before `day` and within a year of it."""
        facts = [f for f in self.instants.get(item, []) if f.period_end <= day]
        if not facts or facts[-1].period_end < day - COMPONENT_MAX_AGE:
            return None
        return facts[-1]


def load_history(conn: sqlite3.Connection, cik: str, as_of: date) -> History:
    quarterly = get_facts(conn, cik, ITEMS, as_of, frequency="quarterly")
    annual = get_facts(conn, cik, ITEMS, as_of, frequency="annual")
    instants: dict[str, list[Fact]] = defaultdict(list)
    for f in sorted(quarterly + annual, key=lambda f: f.period_end):
        if f.period_start is None and (
            not instants[f.canonical_name]
            or (instants[f.canonical_name][-1].period_end != f.period_end)
        ):
            instants[f.canonical_name].append(f)
    return History(
        quarterly={(f.canonical_name, f.fiscal_year, f.fiscal_period): f for f in quarterly},
        annual={(f.canonical_name, f.fiscal_year): f for f in annual},
        instants=dict(instants),
    )


def quarter_label(fiscal_year: int, quarter: int) -> str:
    return f"FY{fiscal_year}Q{quarter}"


def step_quarter(fiscal_year: int, quarter: int, step: int) -> tuple[int, int]:
    index = fiscal_year * 4 + (quarter - 1) + step
    return index // 4, index % 4 + 1


# -- the run -----------------------------------------------------------------------------------


@dataclass
class EngineResult:
    ticker: str
    cik: str
    as_of: date
    assumptions: list[Assumption] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)  # data the run was built from (hashes, ids)

    def add(self, name: str, value: float | None, method: str, period: str = SINGLE) -> float:
        self.assumptions.append(
            Assumption(name=name, period=period, value=value, source="computed", method=method)
        )
        return value

    def value_of(self, name: str, period: str = SINGLE) -> float:
        return next(a.value for a in self.assumptions if (a.name, a.period) == (name, period))


def build_inputs(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date,
    choices: dict[str, UserChoice] | None = None,
    today: date | None = None,
) -> EngineResult:
    """Every assumption a baseline DCF of `ticker` as of `as_of` needs, known on that date."""
    today = today or date.today()
    if not SUPPORTED_FROM <= as_of <= today:
        raise EngineError(f"as-of date must be from {SUPPORTED_FROM} to {today}, got {as_of}")
    company = conn.execute("SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if company is None:
        raise EngineError(f"{ticker} has not been ingested")
    choices = load_user_assumptions() if choices is None else choices
    result = EngineResult(company["ticker"], company["cik"], as_of)
    for choice in choices.values():
        result.assumptions.append(choice.as_assumption())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        history = load_history(conn, company["cik"], as_of)
        comparisons = same_filing_annual_comparisons(conn, company["cik"], "revenue", as_of)
    result.warnings += [str(w.message) for w in caught]

    last_year, last_quarter, base_date = _last_actual_quarter(history, result)
    fiscal_years = _history_years(history, last_year, result)
    _revenue_seed(history, last_year, last_quarter, result)
    _history_rows(history, fiscal_years, result)
    balance_date = _balance(history, base_date, result)
    price = _market(conn, history, result, choices, balance_date)
    _cost_of_debt(history, fiscal_years, result)
    _drivers(history, comparisons, fiscal_years, last_year, last_quarter, result)
    result.add(
        "roll_years",
        (as_of - base_date).days / 365.25,
        f"years from the end of the last actual quarter ({base_date}) to the as-of date",
    )
    result.snapshot |= _snapshot(conn, company["cik"], result.ticker, price)
    if result.snapshot["concept_map_sha256"] != result.snapshot["ingest_concept_map_sha256"]:
        result.warnings.append("concept_map.csv changed since the last ingest: re-run ingest")
    return result


def _last_actual_quarter(history: History, result: EngineResult) -> tuple[int, int, date]:
    revenue = [f for (n, _y, _p), f in history.quarterly.items() if n == "revenue"]
    if not revenue:
        raise EngineError(f"{result.ticker}: no quarterly revenue reported by {result.as_of}")
    last = max(revenue, key=lambda f: f.period_end)
    if result.as_of - last.period_end > STALE_AFTER:
        result.warnings.append(
            f"Fundamentals may be stale: the last reported quarter ended {last.period_end}, "
            f"{(result.as_of - last.period_end).days} days before the as-of date (check that "
            "the newest filings are ingested)."
        )
    return last.fiscal_year, int(last.fiscal_period[1]), last.period_end


def _history_years(history: History, last_year: int, result: EngineResult) -> list[int]:
    """The newest HISTORY_YEARS fiscal years with an annual report, oldest first."""
    years = sorted({y for (n, y) in history.annual if n == "revenue" and y <= last_year})
    if len(years) < HISTORY_YEARS:
        raise EngineError(
            f"{result.ticker}: {HISTORY_YEARS} fiscal years of history needed, found {years}"
        )
    return years[-HISTORY_YEARS:]


def _revenue_seed(history: History, last_year: int, last_quarter: int, result: EngineResult):
    """The last 4 actual quarters, the base that forecast quarters grow from (D2)."""
    for step in range(-3, 1):
        year, quarter = step_quarter(last_year, last_quarter, step)
        period = f"Q{quarter}"
        fact = history.quarterly.get(("revenue", year, period))
        if fact is None:
            raise EngineError(f"{result.ticker}: revenue for FY{year} {period} is not reported")
        value, method = fact.value, trace(fact)
        # a fiscal year whose quarters don't add up to it mixes restatement bases: use the
        # year (newest basis) times this quarter's share of it
        quarters = [history.quarterly.get(("revenue", year, f"Q{q}")) for q in range(1, 5)]
        annual = history.annual.get(("revenue", year))
        if annual is not None and all(quarters):
            total = sum(q.value for q in quarters)
            gap = (total - annual.value) / abs(annual.value)
            if abs(gap) > CONSISTENCY_TOLERANCE:
                value = annual.value * fact.value / total
                method = (
                    f"FY{year} quarters differ from the year by {gap:+.1%}: year × this "
                    f"quarter's share ({fact.value / total:.4f}); {trace(annual)}; {method}"
                )
        result.add(SEED, value, method, quarter_label(year, quarter))


def _history_rows(history: History, fiscal_years: list[int], result: EngineResult) -> None:
    """Reported annual values the drivers are computed from, one row per item and year."""
    for year in fiscal_years:
        get = history.year(year)
        for chain in ("revenue", "ebit", "pretax", "tax", "d_and_a", "capex"):
            r = resolve(chain, get, f"FY{year}")
            result.add(f"history:{chain}", r.value, r.method, f"FY{year}")
        nwc, method = _operating_nwc(lambda item, g=get: g(item), f"FY{year}")
        result.add("history:nwc", nwc, method, f"FY{year}")


def _operating_nwc(get: Callable[[str], Fact | None], where: str) -> tuple[float, str]:
    """(Current assets − cash and short-term investments) − (current liabilities − debt in them)."""
    parts, missing = {}, []
    for item in (
        "current_assets",
        "cash",
        "marketable_securities_current",
        "other_short_term_investments",
        "current_liabilities",
        "debt_current",
        "short_term_borrowings",
        "commercial_paper",
    ):
        fact = get(item)
        if fact is None and item in REQUIRED_BALANCE:
            raise EngineError(f"{item} for {where} is not reported (needed for working capital)")
        parts[item] = fact
        if fact is None:
            missing.append(item)
    v = {k: (f.value if f else 0.0) for k, f in parts.items()}
    short_term = (
        v["short_term_borrowings"] if parts["short_term_borrowings"] else v["commercial_paper"]
    )
    nwc = (
        v["current_assets"]
        - v["cash"]
        - v["marketable_securities_current"]
        - v["other_short_term_investments"]
    ) - (v["current_liabilities"] - v["debt_current"] - short_term)
    method = "; ".join(trace(f) for f in parts.values() if f)
    if missing:
        method += f"; counted as zero: {', '.join(missing)}"
    return nwc, method


def _lease_inclusive(*facts: Fact | None) -> bool:
    return any(
        f and ("CapitalLease" in f.xbrl_concept or "FinanceLease" in f.xbrl_concept) for f in facts
    )


def _debt(get: Callable[[str], Fact | None]) -> tuple[float, list[Fact], list[str], str]:
    """Debt (D3): long-term debt, current and non-current, short-term borrowings (or commercial
    paper when there are none), and finance leases unless a debt tag already includes them.
    Returns (total, facts used, items counted as zero, notes)."""
    used, zero, notes = [], [], []
    current, noncurrent = get("debt_current"), get("debt_noncurrent")
    short_term = get("short_term_borrowings")
    if short_term is None:
        short_term = get("commercial_paper")
        if short_term is None:
            zero.append("short_term_borrowings/commercial_paper")
    leases = get("finance_lease_liabilities")
    if leases is not None and _lease_inclusive(current, noncurrent):
        notes.append("finance leases skipped: the debt tag already includes them")
        leases = None
    elif leases is None:
        zero.append("finance_lease_liabilities")
    for item, fact in (("debt_current", current), ("debt_noncurrent", noncurrent)):
        if fact is None:
            zero.append(item)
    for fact in (current, noncurrent, short_term, leases):
        if fact is not None:
            used.append(fact)
    return sum(f.value for f in used), used, zero, "; ".join(notes)


def _balance(history: History, base_date: date, result: EngineResult) -> date:
    """Net debt, minority interest and the invariants, from the latest balance sheet (D3, D11)."""
    assets = history.latest_before("current_assets", result.as_of)
    if assets is None:
        raise EngineError(f"{result.ticker}: no balance sheet within a year of {result.as_of}")
    balance_date = assets.period_end
    get = lambda item: history.latest_before(item, balance_date)  # noqa: E731
    facts = {item: get(item) for item in BALANCE_ITEMS}
    for item in REQUIRED_BALANCE:
        if facts[item] is None:
            raise EngineError(f"{result.ticker}: {item} not reported at {balance_date}")
    for item, fact in facts.items():
        if fact is not None and fact.value < 0 and item != "minority_interest":
            raise EngineError(f"{result.ticker}: {trace(fact)} is negative")
    carried = [
        f"{i} ({f.period_end})" for i, f in facts.items() if f and f.period_end < balance_date
    ]
    if carried:
        result.warnings.append(
            f"Carried forward to the {balance_date} balance sheet: {', '.join(carried)}"
        )

    def val(item: str) -> float:
        return facts[item].value if facts[item] else 0.0

    short_term_investments = val("marketable_securities_current") + val(
        "other_short_term_investments"
    )
    if short_term_investments > val("current_assets"):
        raise EngineError(
            f"{result.ticker}: current securities ({short_term_investments:,.0f}) exceed current "
            f"assets ({val('current_assets'):,.0f}) at {balance_date}: a tag picks up the wrong "
            "measure"
        )
    if val("cash") + short_term_investments > val("current_assets"):
        raise EngineError(
            f"{result.ticker}: cash and current securities exceed current assets at {balance_date}"
        )

    debt, used, zero, notes = _debt(get)
    for fact in used:
        result.add(f"balance:{fact.canonical_name}", fact.value, trace(fact))
    result.add(
        "debt",
        debt,
        "D3 debt = " + " + ".join(f.canonical_name for f in used) + (f"; {notes}" if notes else ""),
    )
    cash_items = (
        "cash",
        "marketable_securities_current",
        "marketable_securities_noncurrent",
        "other_short_term_investments",
    )
    for item in cash_items:
        if facts[item] is not None:
            result.add(f"balance:{item}", facts[item].value, trace(facts[item]))
        else:
            zero.append(item)
    result.add(
        "cash_and_investments",
        sum(val(i) for i in cash_items),
        "cash + marketable securities (current, non-current) + other short-term investments",
    )
    minority = facts["minority_interest"]
    if minority is None:
        zero.append("minority_interest")
    result.add(
        "minority_interest",
        minority.value if minority else 0.0,
        trace(minority) if minority else "not reported within a year: counted as zero",
    )
    if zero:
        result.warnings.append(
            f"Counted as zero (not reported within a year of the {balance_date} balance sheet): "
            f"{', '.join(sorted(set(zero)))}"
        )
    if balance_date != base_date:
        result.warnings.append(
            f"Balance sheet date {balance_date} differs from the last quarter end {base_date}"
        )
    return balance_date


def _shares(
    conn: sqlite3.Connection, history: History, result: EngineResult, price: PricePoint
) -> float:
    """Cover-page shares outstanding, split-adjusted to the price date (D4); diluted as fallback."""

    def adjusted(fact: Fact) -> tuple[float, float]:
        # a cover-page count is as of its own date; statement share counts in a filing made
        # after a split are already restated for it, so only later splits apply
        basis = fact.period_end if fact.canonical_name == "shares_outstanding" else fact.filed_at
        factor = price_split_factor(conn, result.ticker, basis, price.date)
        return fact.value * factor, factor

    cover = history.instants.get("shares_outstanding", [])
    diluted = [f for (n, _y, _p), f in history.quarterly.items() if n == "diluted_shares"]
    diluted += [f for (n, _y), f in history.annual.items() if n == "diluted_shares"]
    latest_diluted = max(diluted, key=lambda f: f.period_end) if diluted else None
    if cover:
        shares, factor = adjusted(cover[-1])
        method = f"cover page: {trace(cover[-1])}"
    elif latest_diluted is not None:
        shares, factor = adjusted(latest_diluted)
        method = f"fallback: weighted diluted shares {trace(latest_diluted)}"
    else:
        raise EngineError(
            f"{result.ticker}: neither shares_outstanding nor diluted_shares reported"
        )
    if factor != 1:
        method += f"; × {factor:g} for splits up to {price.date}"
    if cover and latest_diluted is not None:
        diluted_now, _ = adjusted(latest_diluted)
        if abs(shares / diluted_now - 1) > SHARES_TOLERANCE:
            result.warnings.append(
                f"Cover-page shares ({shares:,.0f}) differ from diluted shares ({diluted_now:,.0f})"
                f" by more than {SHARES_TOLERANCE:.0%}"
            )
    return result.add("shares", shares, method)


def _market(
    conn: sqlite3.Connection,
    history: History,
    result: EngineResult,
    choices: dict[str, UserChoice],
    balance_date: date,
) -> PricePoint:
    """Price, market value, risk-free rate, beta, equity risk premium and terminal growth."""
    price = raw_close(conn, result.ticker, result.as_of)
    result.add(
        "price",
        price.close,
        f"close on {price.date} (Yahoo), as it traded; not used in the valuation",
    )
    shares = _shares(conn, history, result, price)
    result.add("equity_market_value", price.close * shares, f"price on {price.date} × shares")

    rf = risk_free_rate(conn, result.as_of)
    result.add("risk_free", rf.rate, f"{rf.series} on {rf.date} (FRED)")

    pairs = aligned_weekly_returns(conn, result.ticker, result.as_of, BETA_WEEKS)
    raw = fm.ols_beta(pairs.stock, pairs.market)
    result.add(
        "beta",
        fm.blume_adjusted_beta(raw),
        f"Blume-adjusted OLS beta of {BETA_WEEKS} weekly total returns vs {MARKET_INDEX}, weeks "
        f"ending {pairs.first_week} to {pairs.last_week}; raw beta {raw:.4f}",
    )

    first_year = int(choices["erp_first_year"].value)
    erp = equity_risk_premium(conn, result.as_of, first_year)
    years = f"{erp.first_year}-{erp.last_year}"
    result.add(
        "erp",
        erp.premium.geometric,
        f"historical geometric premium, {years} ({erp.premium.years} years): {MARKET_INDEX} total "
        f"return vs 10-year Treasury total return from {RISK_FREE_SERIES}",
    )
    result.add("erp_std_error", erp.premium.std_error, f"standard error of the premium, {years}")
    result.add(
        "info:erp_arithmetic",
        erp.premium.arithmetic,
        f"arithmetic premium, {years}; information only",
    )
    for info_year in ERP_INFO_FIRST_YEARS:
        try:
            alt = equity_risk_premium(conn, result.as_of, info_year)
        except ValueError:
            continue  # fewer than the minimum years
        result.add(
            f"info:erp_from_{info_year}",
            alt.premium.geometric,
            f"geometric premium {alt.first_year}-{alt.last_year}; information only, not used",
        )
    result.add(
        "terminal_growth",
        rf.rate,
        f"= risk-free rate ({rf.series} on {rf.date}), terminal_growth_method risk_free",
    )
    result.snapshot |= {
        "index_fetch_sha256": erp.price_fetch_sha256,
        "yield_fetch_sha256": erp.yield_fetch_sha256,
    }
    return price


def _cost_of_debt(history: History, fiscal_years: list[int], result: EngineResult) -> None:
    """Interest over average debt, from the newest fiscal year that reports both (D8)."""
    if result.value_of("debt") == 0:
        result.add("cost_of_debt", 0.0, "no debt at the balance date: not used (weight 0)")
        return
    for year in reversed(fiscal_years):
        try:
            interest = resolve("interest", history.year(year), f"FY{year}")
        except EngineError:
            continue
        end, _, _, _ = _debt(history.year(year))
        start, start_used, _, _ = _debt(history.year(year - 1))
        average = (start + end) / 2 if start_used else end
        if average <= 0:
            continue
        kd = fm.cost_of_debt(interest.value, average)
        opening = f"FY{year - 1} {start:,.0f}" if start_used else f"FY{year - 1} not reported"
        result.add(
            "cost_of_debt",
            kd,
            f"FY{year} interest / average debt ({opening}, FY{year} {end:,.0f}); {interest.method}",
        )
        if not COST_OF_DEBT_BOUNDS[0] <= kd <= COST_OF_DEBT_BOUNDS[1]:
            result.warnings.append(f"Cost of debt {kd:.2%} is outside {COST_OF_DEBT_BOUNDS}")
        break
    else:
        raise EngineError(
            f"{result.ticker}: no fiscal year in {fiscal_years} reports interest "
            "(interest_expense | interest_paid) with debt"
        )


def _sum(result: EngineResult, item: str, years: list[int]) -> float:
    return sum(result.value_of(f"history:{item}", f"FY{y}") for y in years)


def _drivers(
    history: History,
    comparisons: list,
    fiscal_years: list[int],
    last_year: int,
    last_quarter: int,
    result: EngineResult,
) -> None:
    span = f"FY{fiscal_years[0]}-FY{fiscal_years[-1]}"
    periods = [
        quarter_label(*step_quarter(last_year, last_quarter, step))
        for step in range(1, QUARTERS + 1)
    ] + list(YEARS)

    # revenue growth (D2): same-filing 10-K comparatives, averaged, fading to terminal growth
    recent = comparisons[:HISTORY_YEARS]
    if len(recent) < HISTORY_YEARS:
        raise EngineError(
            f"{result.ticker}: {HISTORY_YEARS} annual reports with comparatives needed"
        )
    start = sum(c.growth for c in recent) / len(recent)
    terminal = result.value_of("terminal_growth")
    detail = "; ".join(
        f"FY{c.fiscal_year} {c.growth:+.2%} ({_tag(c.current)}, {c.current.accession_no})"
        for c in recent
    )
    for i, period in enumerate(periods):
        year = i // 4 + 1 if i < QUARTERS else QUARTERS // 4 + 1 + (i - QUARTERS)
        growth = start + (terminal - start) * (year - 1) / 4
        result.add(
            "revenue_growth",
            growth,
            f"forecast year {year} of 5: 3-year same-filing average {start:+.2%} fading linearly "
            f"to terminal growth {terminal:.2%}"
            + (" (vs the same quarter a year earlier)" if i < QUARTERS else "")
            + f". {detail}",
            period,
        )

    # operating margin: by fiscal quarter over the last 12 quarters; annual for Y3-Y5
    margins: dict[int, list[float]] = defaultdict(list)
    used = []
    for step in range(-HISTORY_QUARTERS + 1, 1):
        year, quarter = step_quarter(last_year, last_quarter, step)
        get = history.quarter(year, f"Q{quarter}")
        revenue = get("revenue")
        if revenue is None:
            continue
        ebit = resolve("ebit", get, f"FY{year} Q{quarter}")
        margins[quarter].append(ebit.value / revenue.value)
        used.append(f"FY{year}Q{quarter}" + (" (fallback)" if ebit.fallback else ""))
        result.add("history:ebit", ebit.value, ebit.method, quarter_label(year, quarter))
        result.add("history:revenue", revenue.value, trace(revenue), quarter_label(year, quarter))
    annual_margin = _sum(result, "ebit", fiscal_years) / _sum(result, "revenue", fiscal_years)
    all_margins = [m for ms in margins.values() for m in ms]
    mean = sum(all_margins) / len(all_margins)
    sd = math.sqrt(sum((m - mean) ** 2 for m in all_margins) / max(len(all_margins) - 1, 1))
    for period in periods:
        if period in YEARS:
            margin = annual_margin
            method = f"Σ EBIT / Σ revenue, {span}"
        else:
            quarter = int(period[-1])
            if len(margins[quarter]) < MIN_QUARTERS_PER_LABEL:
                raise EngineError(
                    f"{result.ticker}: fewer than {MIN_QUARTERS_PER_LABEL} reported Q{quarter} in "
                    f"the last {HISTORY_QUARTERS} quarters"
                )
            margin = sum(margins[quarter]) / len(margins[quarter])
            method = f"average Q{quarter} EBIT / revenue of the last {HISTORY_QUARTERS} quarters"
        if abs(margin - mean) > MARGIN_SIGMAS * sd and sd > 0:
            result.warnings.append(
                f"Operating margin {margin:.1%} in {period} is outside the historical range "
                f"({mean:.1%} ± {MARGIN_SIGMAS} × {sd:.1%})"
            )
        result.add(
            "operating_margin",
            margin,
            method + f" (quarters used: {', '.join(used)})" if period not in YEARS else method,
            period,
        )

    # tax rate, reinvestment and working capital: 3-year annual ratios
    tax = _sum(result, "tax", fiscal_years) / _sum(result, "pretax", fiscal_years)
    clipped = min(max(tax, TAX_RATE_BOUNDS[0]), TAX_RATE_BOUNDS[1])
    tax_method = f"Σ income tax / Σ pretax income, {span}"
    if clipped != tax:
        result.warnings.append(f"Effective tax rate {tax:.1%} clipped to {clipped:.0%}")
        tax_method += f"; {tax:.2%} clipped to {TAX_RATE_BOUNDS}"
    revenue = _sum(result, "revenue", fiscal_years)
    ratios = {
        "tax_rate": (clipped, tax_method),
        "da_pct": (_sum(result, "d_and_a", fiscal_years) / revenue, f"Σ D&A / Σ revenue, {span}"),
        "capex_pct": (
            _sum(result, "capex", fiscal_years) / revenue,
            f"Σ capex / Σ revenue, {span}",
        ),
        "nwc_pct": (
            sum(
                result.value_of("history:nwc", f"FY{y}")
                / result.value_of("history:revenue", f"FY{y}")
                for y in fiscal_years
            )
            / len(fiscal_years),
            f"average year-end operating working capital / revenue, {span}",
        ),
    }
    for name, (value, method) in ratios.items():
        for period in periods:
            result.add(name, value, method, period)
    result.add("debt_tax_rate", clipped, f"effective tax rate, {span}")


def _snapshot(conn: sqlite3.Connection, cik: str, ticker: str, price: PricePoint) -> dict:
    ingest = conn.execute(
        "SELECT * FROM ingest_runs WHERE cik = ? ORDER BY run_id DESC LIMIT 1", (cik,)
    ).fetchone()
    if ingest is None:
        raise EngineError(f"{ticker}: no ingest run recorded")
    return {
        "ingest_run_id": ingest["run_id"],
        "concept_map_sha256": concept_map_sha256(),
        "ingest_concept_map_sha256": ingest["concept_map_sha256"],
        "price_fetch_sha256": selected_fetch(conn, "yahoo", ticker)["content_sha256"],
    }


def post_checks(terminal_share: float) -> list[str]:
    """Warnings about a finished valuation."""
    if terminal_share > TERMINAL_SHARE_WARNING:
        return [
            f"Terminal value is {terminal_share:.0%} of enterprise value (above "
            f"{TERMINAL_SHARE_WARNING:.0%}): the result depends mostly on terminal growth and WACC"
        ]
    return []


# -- fallback back-test (D11) ------------------------------------------------------------------

FALLBACK_TOLERANCE = 0.05  # median gap between a fallback and its primary item


@dataclass(frozen=True)
class FallbackCheck:
    chain: str
    primary: str
    fallback: str
    gaps: list[tuple[str, int, float]]  # (ticker, fiscal year, (fallback − primary) / |primary|)

    @property
    def median(self) -> float:
        values = sorted(abs(g) for _t, _y, g in self.gaps)
        n = len(values)
        return (values[n // 2] + values[(n - 1) // 2]) / 2 if n else float("nan")

    @property
    def worst(self) -> tuple[str, int, float] | None:
        return max(self.gaps, key=lambda g: abs(g[2])) if self.gaps else None

    @property
    def flagged(self) -> bool:
        return bool(self.gaps) and self.median > FALLBACK_TOLERANCE


def fallback_backtest(conn: sqlite3.Connection, as_of: date) -> list[FallbackCheck]:
    """Each fallback against its primary item, for every company and fiscal year (FY2016-FY2025)
    that reports both."""
    companies = conn.execute("SELECT ticker, cik FROM companies ORDER BY ticker").fetchall()
    annual: dict[str, dict[tuple[str, int], Fact]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for c in companies:
            facts = get_facts(conn, c["cik"], ITEMS, as_of, frequency="annual")
            annual[c["ticker"]] = {(f.canonical_name, f.fiscal_year): f for f in facts}
    checks = []
    for chain, alternatives in CHAINS.items():
        primary = alternatives[0]
        for fallback in alternatives[1:]:
            gaps = []
            for ticker, facts in annual.items():
                for year in FISCAL_YEARS:
                    p = [facts.get((n, year)) for n in primary]
                    f = [facts.get((n, year)) for n in fallback]
                    if all(p) and all(f) and sum(x.value for x in p):
                        base = sum(x.value for x in p)
                        gaps.append((ticker, year, (sum(x.value for x in f) - base) / abs(base)))
            checks.append(FallbackCheck(chain, " + ".join(primary), " + ".join(fallback), gaps))
    return checks
