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
import re
import sqlite3
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis import sources as src
from domains.analysis.coded import Coded, coded_warnings, pass_on
from domains.analysis.dcf import QUARTERS, SEED, YEARS
from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.analysis.schemas import SINGLE, Assumption
from domains.fundamentals.concepts import concept_map_sha256
from domains.fundamentals.facts import (
    MeaningChange,
    dating_changes,
    filing_dates,
    get_facts,
    mixes_meanings,
    same_filing_annual_comparisons,
    state_for_change,
    tag_meaning_changes,
)
from domains.fundamentals.quality import CONSISTENCY_TOLERANCE
from domains.fundamentals.schemas import MINUEND_WORDS, Fact
from domains.fundamentals.universe import FISCAL_YEARS
from domains.market.erp import equity_risk_premium
from domains.market.prices import MARKET_INDEX, PricePoint, aligned_weekly_returns, raw_close
from domains.market.prices import split_factor as price_split_factor
from domains.market.store import selected_fetch
from domains.market.yields import RISK_FREE_SERIES, risk_free_rate
from shared_kernel.calendar import case_today

USER_ASSUMPTIONS_PATH = Path(__file__).parent / "user_assumptions.csv"
# A choice added later needs a rule for runs made before it: see CHOICES_ADDED_LATER in runs.py.
USER_CHOICES = {
    "erp_method": {"historical_geometric"},
    "erp_first_year": None,  # a year
    "terminal_growth_method": {"risk_free"},
    "terminal_method": {"value_driver_ronic_wacc"},  # M4; runs without it are Gordon on FCFF
}

SUPPORTED_FROM = date(2019, 3, 1)  # three full fiscal years of FY2016+ history behind it
HISTORY_YEARS = 3
HISTORY_QUARTERS = 12
MIN_QUARTERS_PER_LABEL = 2
BETA_WEEKS = 104  # 2 years of weekly returns (D6)
COMPONENT_MAX_AGE = timedelta(days=370)  # a balance older than this before the balance date is 0
# Stale fundamentals (backlog #342): warn when the newest quarter ended longer ago than the next
# report's deadline allows. US SEC large accelerated filer deadlines: 40 days for a 10-Q (Form 10-Q,
# General Instruction A.1) and 60 for a 10-K (Form 10-K, General Instruction A(2)(a)); a deadline on
# a weekend or holiday moves to the next business day (Exchange Act Rule 0-3). After a third quarter
# the next report is the 10-K, which covers the fourth quarter. Working rules, Warren's own; a
# non-US source would bring its own deadlines.
QUARTER_DAYS = 92
LONG_QUARTER_DAYS = 98  # a 14-week fourth quarter in a 53-week year (JNJ FY2015)
DEADLINE_10Q_DAYS = 40
DEADLINE_10K_DAYS = 60
DEADLINE_SLACK_DAYS = 3
STALE_AFTER = timedelta(days=QUARTER_DAYS + DEADLINE_10Q_DAYS + DEADLINE_SLACK_DAYS)  # 135
STALE_AFTER_Q3 = timedelta(days=LONG_QUARTER_DAYS + DEADLINE_10K_DAYS + DEADLINE_SLACK_DAYS)  # 161
# A late-filing notice (Form NT 10-Q or NT 10-K, Exchange Act Rule 12b-25(b)) gives 5 or 15 more
# days, and a report filed within them counts as on time. The lines above do not add them: the
# stale lesson names the case instead (backlog #352).
NT_EXTENSION_10Q_DAYS = 5
NT_EXTENSION_10K_DAYS = 15
ANNUAL_MIN_DAYS = 300  # a flow longer than this is a fiscal year's (52 or 53 weeks)
TAX_RATE_BOUNDS = (0.0, 0.5)
COST_OF_DEBT_BOUNDS = (0.0, 0.15)
SHARES_TOLERANCE = 0.10  # cover-page vs diluted shares
SHARE_SCALES = (1_000, 1_000_000)  # the steps between units a filing states (thousands, millions)
TERMINAL_SPREAD_WARNING = 0.03  # WACC − terminal growth below this: the terminal value dominates
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
# What D3 subtracts from debt: cash and every marketable security, current and non-current.
CASH_ITEMS = (
    "cash",
    "marketable_securities_current",
    "marketable_securities_noncurrent",
    "other_short_term_investments",
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

    @classmethod
    def from_assumption(cls, row: Assumption) -> "UserChoice":
        """The choice a run stored, read back from its row: the inverse of `as_assumption`."""
        match = _CHOICE_METHOD.fullmatch(row.method)
        if row.source != "user" or match is None:
            raise EngineError(f"{row.name}: not a stored choice of the owner ({row.method!r})")
        return cls(row.name, **match.groupdict())


# as_assumption's method text; the first " on <date>. " ends the name, so a note may hold dates
_CHOICE_METHOD = re.compile(
    r"(?P<value>.+?): set by (?P<set_by>.+?) on (?P<set_on>\d{4}-\d{2}-\d{2})\. (?P<note>.*)",
    re.DOTALL,
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
            # a run stores the choice as text that UserChoice.from_assumption must read back
            try:
                date.fromisoformat(choice.set_on)
            except ValueError:
                raise EngineError(
                    f"{path.name} line {line}: set_on must be a date like 2026-10-26"
                ) from None
            if " on " in choice.set_by or ": set by " in choice.set_by:
                raise EngineError(
                    f"{path.name} line {line}: set_by can't hold ' on ' or ': set by '"
                )
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
    if fact.one_basis:  # backlog #264
        source += " (year and year-to-date taken on one basis: a newer version of one was restated)"
    if fact.narrower_tag:  # backlog #324
        source += (
            f" (worked out on the year's tag: its own filing gives the quarter only under "
            f"{fact.narrower_tag.replace('us-gaap:', '')}, a tag ranked below it)"
        )
    if fact.kept_on_own_tag is not None:  # backlog #336
        source += (
            f" (kept as filed under a tag ranked below the year's "
            f"{fact.kept_on_own_tag.year_tag.replace('us-gaap:', '')}: on its own tag "
            f"{MINUEND_WORDS.get(fact.kept_on_own_tag.minuend, 'the year')} less the earlier "
            f"periods is {fact.kept_on_own_tag.on_own_tag:,.0f})"
        )
    return f"{fact.canonical_name} [{_tag(fact)}] {fact.period_end} {source}"


def basis_kind(fact: Fact) -> str:
    """Which basis a quarter fact the run reads sits on (backlog #279), from the flags
    `get_facts(one_basis=True)` sets:

    - `first_filed`: put back on the basis it was first filed on, because a newer version of an
      input was restated (#264 rule 3);
    - `restated`: on a newer basis than first filed (a restated reported quarter, a derivation
      from restated inputs only, or #264 rule 2);
    - `no_basis`: derived from restated and unrestated inputs and left so;
    - `unchanged`: not refiled, no second version public by the as-of date; it may still be on
      the old basis (analyst, #279 review).

    `restated` is Warren's name (`Fact.restated`); text a student reads says "recast".
    """
    if fact.one_basis:
        return "restated" if fact.restated else "first_filed"
    if fact.mixed_vintage:
        return "no_basis"
    return "restated" if fact.restated else "unchanged"


def two_bases(kinds: Iterable[str]) -> bool:
    """Facts sit on two bases when one was kept as first reported while another is recast, or one
    is on no basis (backlog #279). `unchanged` alone never makes a split: no filing public by the
    as-of date says which basis it is on, so a note lists it apart as `not_refiled`."""
    kinds = set(kinds)
    return {"first_filed", "restated"} <= kinds or "no_basis" in kinds


@dataclass(frozen=True)
class Resolved:
    value: float
    method: str  # which alternative, with each fact's trace
    fallback: bool
    facts: tuple[Fact, ...] = ()  # the facts summed, for the row's sources (backlog #175)


def resolve(chain: str, get: Callable[[str], Fact | None], where: str) -> Resolved:
    alternatives = CHAINS[chain]
    for i, items in enumerate(alternatives):
        facts = [get(item) for item in items]
        if all(f is not None for f in facts):
            method = "; ".join(map(trace, facts))
            if i:
                method = f"fallback: {' + '.join(items)} = {method}"
            return Resolved(sum(f.value for f in facts), method, fallback=i > 0, facts=tuple(facts))
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
    quarterly = get_facts(conn, cik, ITEMS, as_of, frequency="quarterly", one_basis=True)
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
    notes: list[Coded] = field(default_factory=list)  # warnings as codes (backlog #172)
    snapshot: dict = field(default_factory=dict)  # data the run was built from (hashes, ids)
    sources: dict[tuple[str, str], list[dict]] = field(default_factory=dict)  # by row (#175)
    # each revenue fact the run reads, by part then period label; never stored (#297)
    revenue_read: dict[str, dict[str, Fact]] = field(default_factory=dict, repr=False)
    seed_years_times_share: list[int] = field(default_factory=list, repr=False)

    def read(self, part: str, label: str, fact: Fact) -> None:
        self.revenue_read.setdefault(part, {})[label] = fact

    @property
    def warnings(self) -> list[str]:
        """The warnings' English texts, in order (as stored in `runs.notes`)."""
        return [n.text for n in self.notes]

    def warn(self, code: str, params: dict, text: str) -> None:
        self.notes.append(Coded(code, params, text))

    def add(
        self,
        name: str,
        value: float | None,
        method: str,
        period: str = SINGLE,
        *,
        sources: list[dict],
    ) -> float:
        """Add a computed row with its sources (backlog #175): every row names what it was made
        from, so the caller must say."""
        self.assumptions.append(
            Assumption(name=name, period=period, value=value, source="computed", method=method)
        )
        self._put(name, period, sources)
        return value

    def _put(self, name: str, period: str, sources: list[dict]) -> None:
        if (name, period) in self.sources:
            raise EngineError(f"{name} {period}: sources given twice")
        if not sources:
            raise EngineError(f"{name} {period}: a row needs at least one source")
        self.sources[(name, period)] = list(sources)

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
    today = today or case_today(datetime.now(UTC))
    if not SUPPORTED_FROM <= as_of <= today:
        raise EngineError(f"as-of date must be from {SUPPORTED_FROM} to {today}, got {as_of}")
    company = conn.execute("SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if company is None:
        raise EngineError(f"{ticker} has not been ingested")
    choices = load_user_assumptions() if choices is None else choices
    result = EngineResult(company["ticker"], company["cik"], as_of)
    for choice in choices.values():
        result.assumptions.append(choice.as_assumption())
        result._put(
            choice.name,
            SINGLE,
            [src.owner_choice(choice.name, choice.value, choice.set_by, choice.set_on)],
        )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        history = load_history(conn, company["cik"], as_of)
        comparisons = same_filing_annual_comparisons(conn, company["cik"], "revenue", as_of)
        changes = tag_meaning_changes(conn, company["cik"], ["revenue"], as_of)
    result.notes += coded_warnings(caught)  # one per text
    pass_on(caught)  # a library's warning goes to the log, never into the notes (#196)

    last_year, last_quarter, base_date = _last_actual_quarter(history, result)
    fiscal_years = _history_years(history, last_year, result)
    _revenue_seed(history, last_year, last_quarter, result)
    _history_rows(history, fiscal_years, result)
    balance_date = _balance(history, base_date, result)
    price = _market(conn, history, result, choices, balance_date)
    _cost_of_debt(history, fiscal_years, result)
    _drivers(history, comparisons, fiscal_years, last_year, last_quarter, result)
    if changes:
        _meaning_notes(result, changes, filing_dates(conn, company["cik"], as_of))
    last_seed = quarter_label(last_year, last_quarter)
    result.add(
        "roll_years",
        (as_of - base_date).days / 365.25,
        f"years from the end of the last actual quarter ({base_date}) to the as-of date",
        sources=[src.derived((SEED, last_seed))],
    )
    result.snapshot |= _snapshot(conn, company["cik"], result.ticker, price)
    if result.snapshot["concept_map_sha256"] != result.snapshot["ingest_concept_map_sha256"]:
        result.warn(
            "concept_map_changed",
            {},
            "concept_map.csv changed since the last ingest: re-run ingest",
        )
    return result


def _last_actual_quarter(history: History, result: EngineResult) -> tuple[int, int, date]:
    revenue = [f for (n, _y, _p), f in history.quarterly.items() if n == "revenue"]
    if not revenue:
        raise EngineError(f"{result.ticker}: no quarterly revenue reported by {result.as_of}")
    last = max(revenue, key=lambda f: f.period_end)
    days = (result.as_of - last.period_end).days
    newer = _newer_figure(history, last.period_end)
    if newer is not None:
        # A newer report is loaded but its revenue wasn't read or derived (backlog #352): say so
        # whatever the age; the stale line then keys on the newer period, since "ingest" would be
        # the wrong advice for the unread one.
        annual = (newer.period_end - newer.period_start).days > ANNUAL_MIN_DAYS
        report = "the annual report for the year" if annual else "a report for the period"
        result.warn(
            "newer_report_not_read",
            {
                "last_quarter_end": last.period_end.isoformat(),
                "newer_period_end": newer.period_end.isoformat(),
                "newer_annual": annual,
                "newer_accession_no": newer.accession_no,
                "days": days,
            },
            f"The newest quarter with revenue ended {last.period_end}, but figures from {report} "
            f"ended {newer.period_end} are loaded: that period's revenue could not be read or "
            "derived, so the run starts at least one report behind (check that filing's revenue "
            "line).",
        )
        # A second fault, a report after the newer one missing too, is still stale (analyst).
        _warn_if_stale(result, newer.period_end, "Q4" if annual else newer.fiscal_period)
    else:
        _warn_if_stale(result, last.period_end, last.fiscal_period)
    return last.fiscal_year, int(last.fiscal_period[1]), last.period_end


def _warn_if_stale(result: EngineResult, period_end: date, fiscal_period: str | None) -> None:
    """`fundamentals_stale` when the next report after the period ending `period_end` is past
    its line: after a Q3 the next report is the 10-K, otherwise a 10-Q (backlog #342)."""
    line = STALE_AFTER_Q3 if fiscal_period == "Q3" else STALE_AFTER
    days = (result.as_of - period_end).days
    if result.as_of - period_end > line:
        result.warn(
            "fundamentals_stale",
            {
                "last_quarter_end": period_end.isoformat(),
                "days": days,
                "threshold_days": line.days,
            },
            f"Fundamentals may be stale: the last reported quarter ended {period_end}, "
            f"{days} days before the as-of date (check that the newest filings are ingested).",
        )


def _newer_figure(history: History, last_quarter_end: date) -> Fact | None:
    """A flow figure (one over a period, quarterly or annual) in the history that ends after the
    newest revenue quarter, or None: the latest such end, the longest period on it, a reported
    figure before a derived one (so its filing can be named). Balances are left out: the cover
    page's share count is dated after the quarter it belongs to (backlog #352)."""
    newer = [
        f
        for f in (*history.quarterly.values(), *history.annual.values())
        if f.period_start is not None and f.period_end > last_quarter_end
    ]
    return max(
        newer,
        key=lambda f: (f.period_end, f.period_end - f.period_start, not f.derived),
        default=None,
    )


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
    noted: dict[int, str] = {}  # a year whose quarters sit on two bases: its method words (#279)
    for step in range(-3, 1):
        year, quarter = step_quarter(last_year, last_quarter, step)
        period = f"Q{quarter}"
        fact = history.quarterly.get(("revenue", year, period))
        if fact is None:
            raise EngineError(f"{result.ticker}: revenue for FY{year} {period} is not reported")
        value, method, used, shared = fact.value, trace(fact), [fact], False
        result.read("seed", quarter_label(year, quarter), fact)
        # a fiscal year whose quarters don't add up to it mixes restatement bases: use the
        # year (newest basis) times this quarter's share of it
        quarters = [history.quarterly.get(("revenue", year, f"Q{q}")) for q in range(1, 5)]
        annual = history.annual.get(("revenue", year))
        if annual is not None and all(quarters):
            total = sum(q.value for q in quarters)
            gap = (total - annual.value) / abs(annual.value)
            if abs(gap) > CONSISTENCY_TOLERANCE:
                shared = True
                value = annual.value * fact.value / total
                method = (
                    f"FY{year} quarters differ from the year by {gap:+.1%}: year × this "
                    f"quarter's share ({fact.value / total:.4f}); {trace(annual)}; {method}"
                )
                # the share's denominator is all four quarters (analyst, #175)
                used = [annual, fact] + [q for q in quarters if q is not fact]
                result.read("seed", f"FY{year}", annual)
                for q, other in enumerate(quarters, start=1):
                    result.read("seed", quarter_label(year, q), other)
                if year not in result.seed_years_times_share:
                    result.seed_years_times_share.append(year)
        if all(quarters) and two_bases(basis_kind(q) for q in quarters):
            if year not in noted:
                noted[year] = _seed_basis_note(result, year, quarters, shared)
            method = f"{noted[year]}; {method}"
        result.add(
            SEED,
            value,
            method,
            quarter_label(year, quarter),
            sources=[src.filing(f) for f in used],
        )


def _seed_basis_note(
    result: EngineResult, year: int, quarters: list[Fact], year_times_share: bool
) -> str:
    """One note for a seed year whose revenue quarters sit on two bases (backlog #279); returns
    the words the year's seed rows put in their method. The seed rule is unchanged (#265)."""
    kinds = {f"Q{q}": basis_kind(f) for q, f in enumerate(quarters, start=1)}
    groups = {
        BASIS_PARAMS[k]: sorted(q for q, kind in kinds.items() if kind == k) for k in BASIS_WORDS
    }
    words = "; ".join(
        f"{', '.join(groups[BASIS_PARAMS[k]])} {BASIS_WORDS[k]}"
        for k in BASIS_WORDS
        if groups[BASIS_PARAMS[k]]
    )
    text = (
        f"FY{year}'s revenue quarters are not on one basis: {words}. The forecast grows from "
        "these quarters"
        + (
            ", and because they don't add up to the year it splits the year by their shares, "
            "so the mix also sets those shares."
            if year_times_share
            else "."
        )
    )
    result.warn(
        "seed_year_two_bases",
        {"fiscal_year": year, **groups, "year_times_share": year_times_share},
        text,
    )
    return f"FY{year}'s quarters are not on one basis ({words})"


def _history_rows(history: History, fiscal_years: list[int], result: EngineResult) -> None:
    """Reported annual values the drivers are computed from, one row per item and year."""
    for year in fiscal_years:
        get = history.year(year)
        if get("revenue") is not None:
            result.read("history", f"FY{year}", get("revenue"))
        for chain in ("revenue", "ebit", "pretax", "tax", "d_and_a", "capex"):
            r = resolve(chain, get, f"FY{year}")
            result.add(
                f"history:{chain}",
                r.value,
                r.method,
                f"FY{year}",
                sources=[src.filing(f) for f in r.facts],
            )
        nwc, method, used, missing = _operating_nwc(lambda item, g=get: g(item), f"FY{year}")
        result.add(
            "history:nwc",
            nwc,
            method,
            f"FY{year}",
            sources=[src.filing(f) for f in used]
            + ([src.rule("not_in_annual_report_zero")] if missing else []),
        )


def _operating_nwc(
    get: Callable[[str], Fact | None], where: str
) -> tuple[float, str, list[Fact], list[str]]:
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
    return nwc, method, [f for f in parts.values() if f], missing


def _lease_inclusive(*facts: Fact | None) -> bool:
    return any(
        f and ("CapitalLease" in f.xbrl_concept or "FinanceLease" in f.xbrl_concept) for f in facts
    )


def debt_parts(get: Callable[[str], Fact | None]) -> tuple[float, list[Fact], list[str], str]:
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
        items = [
            {"item": i, "period_end": f.period_end.isoformat()}
            for i, f in facts.items()
            if f and f.period_end < balance_date
        ]
        result.warn(
            "balance_carried_forward",
            {"balance_date": balance_date.isoformat(), "items": items},
            f"Carried forward to the {balance_date} balance sheet: {', '.join(carried)}",
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

    debt, used, zero, notes = debt_parts(get)
    for fact in used:
        result.add(
            f"balance:{fact.canonical_name}",
            fact.value,
            trace(fact),
            sources=[src.filing(fact)],
        )
    result.add(
        "debt",
        debt,
        "D3 debt = " + " + ".join(f.canonical_name for f in used) + (f"; {notes}" if notes else ""),
        sources=[src.derived(*((f"balance:{f.canonical_name}", SINGLE) for f in used))]
        if used
        else [src.rule("not_reported_zero")],
    )
    cash_rows = []
    for item in CASH_ITEMS:
        if facts[item] is not None:
            result.add(
                f"balance:{item}",
                facts[item].value,
                trace(facts[item]),
                sources=[src.filing(facts[item])],
            )
            cash_rows.append((f"balance:{item}", SINGLE))
        else:
            zero.append(item)
    result.add(
        "cash_and_investments",
        sum(val(i) for i in CASH_ITEMS),
        "cash + marketable securities (current, non-current) + other short-term investments",
        sources=[src.derived(*cash_rows)] if cash_rows else [src.rule("not_reported_zero")],
    )
    minority = facts["minority_interest"]
    if minority is None:
        zero.append("minority_interest")
    result.add(
        "minority_interest",
        minority.value if minority else 0.0,
        trace(minority) if minority else "not reported within a year: counted as zero",
        sources=[src.filing(minority)] if minority else [src.rule("not_reported_zero")],
    )
    if zero:
        result.warn(
            "balance_counted_zero",
            {"balance_date": balance_date.isoformat(), "items": sorted(set(zero))},
            f"Counted as zero (not reported within a year of the {balance_date} balance sheet): "
            f"{', '.join(sorted(set(zero)))}",
        )
    if balance_date != base_date:
        result.warn(
            "balance_date_differs",
            {"balance_date": balance_date.isoformat(), "last_quarter_end": base_date.isoformat()},
            f"Balance sheet date {balance_date} differs from the last quarter end {base_date}",
        )
    return balance_date


def share_scale(a: float, b: float) -> int | None:
    """1,000 or 1,000,000 when two share counts, either way round, are that many times apart
    within `SHARES_TOLERANCE`: one of them was filed in the wrong unit (backlog #343); else None.

    A thousand is the step between the units filings state (thousands, millions); no split or
    buyback comes near it, so a gap of that size is a unit error, not a change in the count."""
    if not (a > 0 and b > 0):
        return None
    ratio = max(a, b) / min(a, b)
    for scale in SHARE_SCALES:
        if abs(ratio / scale - 1) <= SHARES_TOLERANCE:
            return scale
    return None


def _shares(
    conn: sqlite3.Connection, history: History, result: EngineResult, price: PricePoint
) -> float:
    """Cover-page shares outstanding, split-adjusted to the price date (D4); diluted as fallback,
    skipping a diluted count filed in the wrong unit (backlog #343) and any count of zero or below
    (backlog #364)."""

    def basis(fact: Fact) -> date:
        # a cover-page count is as of its own date; statement share counts in a filing made
        # after a split are already restated for it, so only later splits apply
        return fact.period_end if fact.canonical_name == "shares_outstanding" else fact.filed_at

    def adjusted(fact: Fact) -> tuple[float, float]:
        factor = price_split_factor(conn, result.ticker, basis(fact), price.date)
        return fact.value * factor, factor

    def wrong_unit(params: dict, fact: Fact, value: float, scale: int) -> dict:
        return params | {
            "diluted_shares_adjusted": value,
            "scale": scale,
            "diluted_accession_no": fact.accession_no,
            "diluted_period_end": fact.period_end.isoformat(),
        }

    def positive(facts: list[Fact], count: str, label: str, divisor: bool) -> list[Fact]:
        """The counts above zero, newest first. A count of zero or below is never used (backlog
        #364). Each one newer than the newest count above zero, which it would have replaced, is
        noted; with none above zero, only the newest is. An older one is left out silently (it
        only leaves the fallback's middle count). `divisor`: whether the newest such count
        would have been the run's share count, not only a check beside it."""
        kept = [f for f in facts if f.value > 0]
        skipped = [f for f in facts if f.value <= 0]
        if kept:
            skipped = [f for f in skipped if f.period_end > kept[0].period_end]
        for fact in skipped if kept else skipped[:1]:
            result.warn(
                "shares_not_positive",
                {
                    "count": count,
                    "value": fact.value,
                    "accession_no": fact.accession_no,
                    "period_end": fact.period_end.isoformat(),
                    "divisor": divisor,
                },
                f"{label} for {fact.period_end} are filed as {fact.value:g} "
                f"({fact.accession_no}); a share count must be above zero, so that count is not "
                "used",
            )
        return kept

    cover_filed = sorted(
        history.instants.get("shares_outstanding", []), key=lambda f: f.period_end, reverse=True
    )
    cover = positive(cover_filed, "cover", "Cover-page shares", True)[:1]  # the newest, as before
    diluted = [f for (n, _y, _p), f in history.quarterly.items() if n == "diluted_shares"]
    diluted += [f for (n, _y), f in history.annual.items() if n == "diluted_shares"]
    diluted.sort(key=lambda f: f.period_end, reverse=True)
    diluted = positive(diluted, "diluted", "Diluted shares", not cover)
    latest_diluted = diluted[0] if diluted else None
    if cover:
        shares, factor = adjusted(cover[-1])
        method = f"cover page: {trace(cover[-1])}"
        counted = cover[-1]
    elif latest_diluted is not None:
        # the newest diluted count whose unit agrees with the history's middle count (the lower
        # middle one, so it is a filed count and always agrees with itself)
        values = [adjusted(f)[0] for f in diluted]
        middle = sorted(values)[(len(values) - 1) // 2]
        for fact, value in zip(diluted, values, strict=True):
            scale = share_scale(value, middle) if len(diluted) > 1 else None
            if scale is None:
                counted = fact
                break
            result.warn(
                "shares_scale_mismatch",
                wrong_unit(
                    {"median_diluted_adjusted": middle, "tolerance": SHARES_TOLERANCE},
                    fact,
                    value,
                    scale,
                ),
                f"Diluted shares for {fact.period_end} ({value:,.0f}) look filed in the wrong "
                f"unit: the history's middle count ({middle:,.0f}) is about {scale:,} times "
                f"{'larger' if middle > value else 'smaller'}; that count is not used",
            )
        shares, factor = adjusted(counted)
        method = f"fallback: weighted diluted shares {trace(counted)}"
    else:
        if cover_filed or any(n.code == "shares_not_positive" for n in result.notes):
            raise EngineError(f"{result.ticker}: no share count above zero reported")
        raise EngineError(
            f"{result.ticker}: neither shares_outstanding nor diluted_shares reported"
        )
    if factor != 1:
        method += f"; × {factor:g} for splits up to {price.date}"
    if cover and latest_diluted is not None:
        diluted_now, _ = adjusted(latest_diluted)
        scale = share_scale(shares, diluted_now)
        if scale is not None:
            result.warn(
                "shares_scale_mismatch",
                wrong_unit(
                    {"cover_shares_adjusted": shares, "tolerance": SHARES_TOLERANCE},
                    latest_diluted,
                    diluted_now,
                    scale,
                ),
                f"Cover-page shares ({shares:,.0f}) and diluted shares ({diluted_now:,.0f}) are "
                f"about {scale:,} times apart, so one was filed in the wrong unit; the cover-page "
                "count is used",
            )
        elif abs(shares / diluted_now - 1) > SHARES_TOLERANCE:
            result.warn(
                "shares_cover_differs",
                {
                    "cover_shares_adjusted": shares,
                    "diluted_shares_adjusted": diluted_now,
                    "tolerance": SHARES_TOLERANCE,
                },
                f"Cover-page shares ({shares:,.0f}) differ from diluted shares ({diluted_now:,.0f})"
                f" by more than {SHARES_TOLERANCE:.0%}",
            )
    sources = [src.filing(counted)]
    if factor != 1:
        sources.append(src.market("yahoo", result.ticker, "splits", basis(counted), price.date))
    return result.add("shares", shares, method, sources=sources)


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
        sources=_price_sources(conn, result.ticker, price),
    )
    shares = _shares(conn, history, result, price)
    result.add(
        "equity_market_value",
        price.close * shares,
        f"price on {price.date} × shares",
        sources=[src.derived(("price", SINGLE), ("shares", SINGLE))],
    )

    rf = risk_free_rate(conn, result.as_of)
    result.add(
        "risk_free",
        rf.rate,
        f"{rf.series} on {rf.date} (FRED)",
        sources=[src.market("fred", rf.series, "yield", rf.date, rf.date)],
    )

    pairs = aligned_weekly_returns(conn, result.ticker, result.as_of, BETA_WEEKS)
    raw = fm.ols_beta(pairs.stock, pairs.market)
    result.add(
        "beta",
        fm.blume_adjusted_beta(raw),
        f"Blume-adjusted OLS beta of {BETA_WEEKS} weekly total returns vs {MARKET_INDEX}, weeks "
        f"ending {pairs.first_week} to {pairs.last_week}; raw beta {raw:.4f}",
        sources=[
            src.market("yahoo", series, "weekly_total_return", pairs.first_week, pairs.last_week)
            for series in (result.ticker, MARKET_INDEX)
        ],
    )

    first_year = int(choices["erp_first_year"].value)
    erp = equity_risk_premium(conn, result.as_of, first_year)
    years = f"{erp.first_year}-{erp.last_year}"
    erp_sources = _erp_sources(erp.first_year, erp.last_year)
    result.add(
        "erp",
        erp.premium.geometric,
        f"historical geometric premium, {years} ({erp.premium.years} years): {MARKET_INDEX} total "
        f"return vs 10-year Treasury total return from {RISK_FREE_SERIES}",
        sources=erp_sources,
    )
    result.add(
        "erp_std_error",
        erp.premium.std_error,
        f"standard error of the premium, {years}",
        sources=erp_sources,
    )
    result.add(
        "info:erp_arithmetic",
        erp.premium.arithmetic,
        f"arithmetic premium, {years}; information only",
        sources=erp_sources,
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
            sources=_erp_sources(alt.first_year, alt.last_year),
        )
    result.add(
        "terminal_growth",
        rf.rate,
        f"= risk-free rate ({rf.series} on {rf.date}), terminal_growth_method risk_free",
        sources=[src.derived(("risk_free", SINGLE), ("terminal_growth_method", SINGLE))],
    )
    result.snapshot |= {
        "index_fetch_sha256": erp.price_fetch_sha256,
        "yield_fetch_sha256": erp.yield_fetch_sha256,
    }
    return price


def _price_sources(conn: sqlite3.Connection, ticker: str, price: PricePoint) -> list[dict]:
    """The close, and when the download has since applied a split, the adjustment that puts it
    back on that day's basis (`raw_close`): its window runs to the download's last date, after
    the as-of date, but it only undoes a later restatement of the same public close."""
    out = [src.market("yahoo", ticker, "close", price.date, price.date)]
    last = conn.execute(
        "SELECT last_date FROM market_fetches WHERE fetch_id = ?", (price.fetch_id,)
    ).fetchone()["last_date"]
    if price_split_factor(conn, ticker, price.date, date.fromisoformat(last)) != 1:
        out.append(src.market("yahoo", ticker, "splits", price.date, date.fromisoformat(last)))
    return out


def _erp_sources(first_year: int, last_year: int) -> list[dict]:
    """The index and the 10-year yield, year-end to year-end: the first return starts from the
    close and yield at the end of the year before `first_year`."""
    start, end = date(first_year - 1, 12, 31), date(last_year, 12, 31)
    return [
        src.market("yahoo", MARKET_INDEX, "annual_total_return", start, end),
        src.market("fred", RISK_FREE_SERIES, "yield", start, end),
    ]


def _cost_of_debt(history: History, fiscal_years: list[int], result: EngineResult) -> None:
    """Interest over average debt, from the newest fiscal year that reports both (D8)."""
    if result.value_of("debt") == 0:
        result.add(
            "cost_of_debt",
            0.0,
            "no debt at the balance date: not used (weight 0)",
            sources=[src.rule("no_debt")],
        )
        return
    for year in reversed(fiscal_years):
        try:
            interest = resolve("interest", history.year(year), f"FY{year}")
        except EngineError:
            continue
        end, end_used, _, _ = debt_parts(history.year(year))
        start, start_used, _, _ = debt_parts(history.year(year - 1))
        average = (start + end) / 2 if start_used else end
        if average <= 0:
            continue
        kd = fm.cost_of_debt(interest.value, average)
        opening = f"FY{year - 1} {start:,.0f}" if start_used else f"FY{year - 1} not reported"
        result.add(
            "cost_of_debt",
            kd,
            f"FY{year} interest / average debt ({opening}, FY{year} {end:,.0f}); {interest.method}",
            sources=[src.filing(f) for f in (*interest.facts, *start_used, *end_used)],
        )
        if not COST_OF_DEBT_BOUNDS[0] <= kd <= COST_OF_DEBT_BOUNDS[1]:
            low, high = COST_OF_DEBT_BOUNDS
            result.warn(
                "cost_of_debt_out_of_bounds",
                {"cost_of_debt": kd, "low": low, "high": high},
                f"Cost of debt {kd:.2%} is outside {COST_OF_DEBT_BOUNDS}",
            )
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
    growth_sources = [src.filing(f) for c in recent for f in (c.current, c.prior)]
    growth_sources.append(src.derived(("terminal_growth", SINGLE)))
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
            sources=growth_sources,
        )

    # operating margin: by fiscal quarter over the last 12 quarters; annual for Y3-Y5
    margins: dict[int, list[float]] = defaultdict(list)
    margin_rows: dict[int, list[tuple[str, str]]] = defaultdict(list)
    used = []
    for step in range(-HISTORY_QUARTERS + 1, 1):
        year, quarter = step_quarter(last_year, last_quarter, step)
        get = history.quarter(year, f"Q{quarter}")
        revenue = get("revenue")
        if revenue is None:
            continue
        ebit = resolve("ebit", get, f"FY{year} Q{quarter}")
        margins[quarter].append(ebit.value / revenue.value)
        label = quarter_label(year, quarter)
        result.read("operating_margin", label, revenue)
        used.append(
            label
            + (" (fallback)" if ebit.fallback else "")
            + _basis_mark(result, label, revenue, ebit.facts)
        )
        result.add(
            "history:ebit",
            ebit.value,
            ebit.method,
            label,
            sources=[src.filing(f) for f in ebit.facts],
        )
        result.add(
            "history:revenue", revenue.value, trace(revenue), label, sources=[src.filing(revenue)]
        )
        margin_rows[quarter] += [("history:ebit", label), ("history:revenue", label)]
    annual_margin = _sum(result, "ebit", fiscal_years) / _sum(result, "revenue", fiscal_years)
    for period in periods:
        if period in YEARS:
            margin = annual_margin
            method = f"Σ EBIT / Σ revenue, {span}"
            inputs = _yearly(("ebit", "revenue"), fiscal_years)
        else:
            quarter = int(period[-1])
            if len(margins[quarter]) < MIN_QUARTERS_PER_LABEL:
                raise EngineError(
                    f"{result.ticker}: fewer than {MIN_QUARTERS_PER_LABEL} reported Q{quarter} in "
                    f"the last {HISTORY_QUARTERS} quarters"
                )
            margin = sum(margins[quarter]) / len(margins[quarter])
            method = f"average Q{quarter} EBIT / revenue of the last {HISTORY_QUARTERS} quarters"
            inputs = margin_rows[quarter]
        result.add(
            "operating_margin",
            margin,
            method + f" (quarters used: {', '.join(used)})" if period not in YEARS else method,
            period,
            sources=[src.derived(*inputs)],
        )

    # tax rate, reinvestment and working capital: 3-year annual ratios
    tax = _sum(result, "tax", fiscal_years) / _sum(result, "pretax", fiscal_years)
    clipped = min(max(tax, TAX_RATE_BOUNDS[0]), TAX_RATE_BOUNDS[1])
    tax_method = f"Σ income tax / Σ pretax income, {span}"
    if clipped != tax:
        low, high = TAX_RATE_BOUNDS
        result.warn(
            "tax_rate_clipped",
            {"tax_rate": tax, "clipped_to": clipped, "low": low, "high": high},
            f"Effective tax rate {tax:.1%} clipped to {clipped:.0%}",
        )
        tax_method += f"; {tax:.2%} clipped to {TAX_RATE_BOUNDS}"
    revenue = _sum(result, "revenue", fiscal_years)
    ratio_inputs = {
        "tax_rate": _yearly(("tax", "pretax"), fiscal_years),
        "da_pct": _yearly(("d_and_a", "revenue"), fiscal_years),
        "capex_pct": _yearly(("capex", "revenue"), fiscal_years),
        "nwc_pct": _yearly(("nwc", "revenue"), fiscal_years),
    }
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
            result.add(name, value, method, period, sources=[src.derived(*ratio_inputs[name])])
    result.add(
        "debt_tax_rate",
        clipped,
        f"effective tax rate, {span}",
        sources=[src.derived(*ratio_inputs["tax_rate"])],
    )


# the run parts that read revenue (backlog #297), in note order, with their English words
MEANING_PARTS = {
    "seed": "the revenue the forecast starts from",
    "operating_margin": "the quarterly operating margins",
    "history": "the annual margin and the D&A, capex and working-capital shares",
}


def _label_order(label: str) -> tuple[int, int]:
    """FY2019Q3 -> (2019, 3); a year FY2019 sorts after its Q4."""
    return int(label[2:6]), int(label[7]) if len(label) > 6 else 5


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _meaning_notes(
    result: EngineResult, changes: list[MeaningChange], filed_at: dict[str, date]
) -> None:
    """One `run_mixes_meanings` note per change of meaning whose revenue figures the run reads
    together are not like for like (backlog #297 item 1; the rule of the series note, v0.9.50).
    Values, rows and methods are unchanged: a note only."""
    facts = {k: f for part in result.revenue_read.values() for k, f in part.items()}
    for change in dating_changes(facts.values(), changes, filed_at):
        state = {k: state_for_change(f, change, changes, filed_at) for k, f in facts.items()}
        if not mixes_meanings(state.values()):
            continue
        parts = [
            p
            for p in MEANING_PARTS
            if mixes_meanings(state[k] for k in result.revenue_read.get(p, {}))
        ]
        split = [
            y
            for y in sorted(result.seed_years_times_share)
            if mixes_meanings(state[k] for k in state if k == f"FY{y}" or k.startswith(f"FY{y}Q"))
        ]
        result.notes.append(_meaning_note(change, state, parts, split))


def _meaning_note(
    change: MeaningChange, state: dict[str, str], parts: list[str], split: list[int]
) -> Coded:
    groups = {
        s: sorted((k for k, v in state.items() if v == s), key=_label_order)
        for s in ("old", "new", "mixed", "other")
    }
    day = change.filed_at.isoformat()
    gap = max(abs(new / old - 1) for _s, _e, old, new in change.periods)
    said = []
    if groups["old"]:
        verb = "carries" if len(groups["old"]) == 1 else "carry"
        said.append(f"{_and(groups['old'])} {verb} the tag's earlier meaning")
    if groups["new"]:
        said.append(f"{_and(groups['new'])} the meaning the {change.form} filed {day} gave it")
    if groups["mixed"]:
        said.append(
            f"{_and(groups['mixed'])} a mix of both (worked out from figures filed on both sides)"
        )
    if groups["other"]:
        said.append(f"{_and(groups['other'])} another tag, of unknown meaning")
    if parts:
        where = (
            "These are worked out on revenue that is not like for like: "
            f"{_and([MEANING_PARTS[p] for p in parts])}."
        )
    else:
        where = (
            "Each part of the run is on one meaning, but not the same one, so the margins and "
            "shares may not match the revenue the forecast starts from."
        )
    if split:
        years = _and([f"FY{y}" for y in split])
        where += (
            f" For {years} the forecast starts from the year's total as filed, split by its "
            "quarters' shares, so only the split between quarters mixes the two."
        )
    text = (
        f"This run reads revenue as {change.xbrl_concept} with more than one meaning: "
        f"{'; '.join(said)}. {where} On the periods the change shows, the two meanings differ "
        f"by up to {gap:.1%}; there the earlier meaning is still filed, under "
        f"{change.other_concept}. This says nothing about other changes within either side."
    )
    return Coded(
        "run_mixes_meanings",
        {
            "item": change.canonical_name,
            "tag": change.xbrl_concept,
            "other_tag": change.other_concept,
            "changed_on": day,
            "form": change.form,
            "accession_no": change.accession_no,
            "old_periods": groups["old"],
            "new_periods": groups["new"],
            "mixed_periods": groups["mixed"],
            "other_tag_periods": groups["other"],
            "parts": parts,
            "seed_split_years": split,
            "largest_gap": gap,
        },
        text,
    )


def _basis_mark(result: EngineResult, label: str, revenue: Fact, ebit: Iterable[Fact]) -> str:
    """A margin quarter's mark in the margin method, and a note when its revenue and EBIT sit on
    two bases (backlog #279): "(two bases)", "(one basis)" when a fact was put on one basis, or
    nothing."""
    facts = [revenue, *ebit]
    kinds = {f.canonical_name: basis_kind(f) for f in facts}
    if not two_bases(kinds.values()):
        return " (one basis)" if any(f.one_basis for f in facts) else ""
    groups = {
        BASIS_PARAMS[k]: sorted(n for n, kind in kinds.items() if kind == k) for k in BASIS_WORDS
    }
    words = [
        f"{' and '.join(n.replace('_', ' ') for n in groups[BASIS_PARAMS[k]])} {BASIS_WORDS[k]}"
        for k in BASIS_WORDS
        if groups[BASIS_PARAMS[k]]
    ]
    result.warn(
        "margin_quarter_two_bases",
        {"period": label, **groups},
        f"{label}'s operating margin divides figures that are not on one basis: "
        f"{'; '.join(words)}. It is one of the {HISTORY_QUARTERS} quarters the quarterly "
        "margins average.",
    )
    return " (two bases)"


# the basis kinds a note names, in order, with their English words (professor, #279 review:
# "restated" is kept for the code, the text says "recast", the term for a change of basis).
# `unchanged` only means no second version is public yet, so a figure not given again may still
# be on the old basis (analyst, #279 review): a note lists it apart, never as fine.
BASIS_WORDS = {
    "first_filed": "as first reported",
    "restated": "as recast",
    "no_basis": "worked out from recast and unrecast figures together",
    "unchanged": "not given again since first reported, so possibly still on the old basis",
}
BASIS_PARAMS = {
    "first_filed": "first_filed",
    "restated": "restated",
    "no_basis": "no_basis",
    "unchanged": "not_refiled",
}


def _yearly(items: tuple[str, ...], fiscal_years: list[int]) -> list[tuple[str, str]]:
    """The history rows of `items` for each fiscal year, as derived inputs."""
    return [(f"history:{item}", f"FY{y}") for y in fiscal_years for item in items]


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
        "reading_rules_version": READING_RULES_VERSION,
        "price_fetch_sha256": selected_fetch(conn, "yahoo", ticker)["content_sha256"],
    }


def post_checks(
    assumptions: Iterable[Assumption], outputs: dict[tuple[str, str], float]
) -> list[str]:
    """The texts of `post_check_notes`, as stored in `runs.notes`."""
    return [n.text for n in post_check_notes(assumptions, outputs)]


def post_check_notes(
    assumptions: Iterable[Assumption], outputs: dict[tuple[str, str], float]
) -> list[Coded]:
    """Warnings about a valuation, from its rows and outputs alone, as codes (backlog #172).

    They read nothing but the run, so they apply to any row set: a baseline, or (M4) one whose
    drivers were shocked.
    """
    assumptions = list(assumptions)
    rows: dict[str, dict[str, float]] = defaultdict(dict)
    for a in assumptions:
        rows[a.name][a.period] = a.value
    out = []

    # forecast margins far outside the reported quarterly margins behind them
    history = [
        rows["history:ebit"][p] / rows["history:revenue"][p]
        for p in rows.get("history:ebit", {})
        if "Q" in p and rows["history:revenue"].get(p)
    ]
    if len(history) > 1:
        mean = sum(history) / len(history)
        sd = math.sqrt(sum((m - mean) ** 2 for m in history) / (len(history) - 1))
        for period, margin in sorted(rows.get("operating_margin", {}).items()):
            if sd > 0 and abs(margin - mean) > MARGIN_SIGMAS * sd:
                params = {
                    "period": period,
                    "margin": margin,
                    "mean": mean,
                    "sd": sd,
                    "sigmas": MARGIN_SIGMAS,
                    "n_quarters": len(history),
                }
                out.append(
                    Coded(
                        "margin_outside_history",
                        params,
                        f"Operating margin {margin:.1%} in {period} is outside the historical "
                        f"range ({mean:.1%} ± {MARGIN_SIGMAS} × {sd:.1%}, {len(history)} quarters)",
                    )
                )

    # WACC set directly on a what-if (backlog #171): it is an override, not a weighted average,
    # so say when it lies outside the two costs it would average, and that the ERP is out of it
    if dcf.wacc_is_set(assumptions):
        out += _wacc_set_notes(rows, outputs)

    # under the value-driver terminal value the spread no longer drives the value (M4)
    if dcf.terminal_method(assumptions) != dcf.GORDON:
        return out
    growth = rows["terminal_growth"][SINGLE]
    spread = outputs[("wacc", SINGLE)] - growth
    if _thin(spread):
        share = outputs[("terminal_share", SINGLE)]
        params = {
            "spread": spread,
            "threshold": TERMINAL_SPREAD_WARNING,
            "wacc": outputs[("wacc", SINGLE)],
            "terminal_growth": growth,
            "terminal_share": share,
        }
        out.append(
            Coded(
                "thin_terminal_spread",
                params,
                f"WACC − terminal growth is {spread * 100:.2f} points (below "
                f"{TERMINAL_SPREAD_WARNING * 100:.0f}): terminal value is "
                f"{share:.0%} of enterprise value, so the result depends "
                "mostly on terminal growth and WACC",
            )
        )
    # the same check at ERP ± 1 SE (backlog #10): revalue the run's own rows with the ERP moved,
    # the path that made the stored sensitivity; a bound with no value is noted elsewhere (#9)
    std_error = rows.get("erp_std_error", {}).get(SINGLE)
    # with WACC set directly (a what-if, backlog #171) the ERP doesn't enter the rate: no bounds
    if std_error is None or dcf.wacc_is_set(assumptions):
        return out
    erp = rows["erp"][SINGLE]
    bounds = (
        (-1, "erp_minus_1se", "ERP − 1 SE", "lower"),
        (1, "erp_plus_1se", "ERP + 1 SE", "higher"),
    )
    for sign, bound, label, word in bounds:
        try:
            shifted = dcf.value(dcf.with_value(assumptions, "erp", erp + sign * std_error))
        except fm.FinancialMathError:
            continue
        spread = shifted.wacc - growth
        if _thin(spread):
            params = {
                "bound": bound,
                "spread": spread,
                "threshold": TERMINAL_SPREAD_WARNING,
                "wacc": shifted.wacc,
                "terminal_growth": growth,
                "terminal_share": shifted.dcf.terminal_share,
            }
            out.append(
                Coded(
                    "thin_terminal_spread_at_erp_bound",
                    params,
                    f"At {label}, WACC − terminal growth is {spread * 100:.2f} points (below "
                    f"{TERMINAL_SPREAD_WARNING * 100:.0f}): terminal value is "
                    f"{shifted.dcf.terminal_share:.0%} of enterprise value there, so this bound "
                    f"mostly shows how the terminal value reacts to the {word} ERP",
                )
            )
    return out


def _wacc_set_notes(rows: dict, outputs: dict) -> list[Coded]:
    wacc = rows[dcf.WACC_SET][SINGLE]
    cost_of_equity = outputs[("cost_of_equity", SINGLE)]
    debt_after_tax = fm.after_tax_cost_of_debt(
        rows["cost_of_debt"][SINGLE], rows["debt_tax_rate"][SINGLE]
    )
    out = []
    low, high = sorted((debt_after_tax, cost_of_equity))
    if not low <= wacc <= high:
        params = {
            "wacc": wacc,
            "cost_of_equity": cost_of_equity,
            "after_tax_cost_of_debt": debt_after_tax,
        }
        out.append(
            Coded(
                "wacc_outside_its_parts",
                params,
                f"The WACC set here ({wacc:.2%}) is outside the two costs a weighted average "
                f"would lie between (debt after tax {debt_after_tax:.2%}, equity "
                f"{cost_of_equity:.2%}): it is an override, not a weighted average of this "
                "run's costs",
            )
        )
    out.append(
        Coded(
            "erp_bounds_not_computed",
            {},
            "Value per share at ERP ± 1 standard error is not computed: with WACC set directly "
            "the ERP no longer enters the discount rate",
        )
    )
    return out


def _thin(spread: float) -> bool:
    """Below the warning line; a spread of exactly 3 points that floating point lands a hair
    under still counts as 3."""
    return spread < TERMINAL_SPREAD_WARNING - 1e-12


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
