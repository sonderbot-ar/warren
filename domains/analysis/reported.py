"""Reported figures and named ratios for a company and fiscal period, point in time (backlog #140).

The query behind brief questions 1 and 2 (`docs/product/brief.md`): what a company reported for a
fiscal quarter or year, as known on an as-of date, each line with its filing, first-reported and
latest values, and the ratios a student asks about, computed here and never by the app
(Decision 13). Nothing is stored: the answer is a deterministic read of `financial_facts`.

- Lines are the items the period reports, the latest version known on `as_of` beside the first
  one reported. Quarters the company never reports alone (Apple's fiscal Q4) are derived as in
  `facts.py` and say so, with the filings they came from.
- Ratios reuse the valuation engine's own rules (`math_engine.CHAINS`, `debt_parts`,
  `CASH_ITEMS`), so a student sees the operating margin, D&A and debt that a run uses, and every
  division goes through `financial_math`.
- Reader-facing words are not the contract: every ratio, gap, note and warning carries a stable
  code with its parameters, and the English `text` beside it is a fallback (front-end review).
- A derived quarter whose inputs were recast is put on one basis, as a run reads it (backlog #264,
  #290): the line's value is the one-basis figure, the plain derivation sits beside it in
  `plain`, and `basis_note` says why; ratios use the one-basis figure and say so.
- Values are raw, unrounded, in the line's unit (USD, shares); ratios are fractions (0.2 = 20%).
"""

import re
import sqlite3
import warnings
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

from domains.analysis import financial_math as fm
from domains.analysis.coded import Coded, coded_warnings, pass_on
from domains.analysis.math_engine import CASH_ITEMS, CHAINS, History, basis_kind, debt_parts
from domains.fundamentals.facts import (
    MeaningChange,
    get_facts,
    meaning_of,
    newest_filing_disagreements,
    tag_meaning_changes,
)
from domains.fundamentals.schemas import Fact
from domains.fundamentals.universe import PHASE1_UNIVERSE

LATEST_QUARTER, LATEST_YEAR = "latest-quarter", "latest-year"
PERIOD_FORMS = f"FY2025, FY2025Q4, {LATEST_QUARTER} or {LATEST_YEAR}"
_PERIOD = re.compile(r"FY(?P<year>\d{4})(?:Q(?P<quarter>[1-4]))?")
LENGTH_NOTE_DAYS = 7  # a 14-week quarter or 53-week year is 7 days longer: flagged (analyst)
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

AS_REPORTED = {
    "code": "as_reported",
    "text": (
        "Ratios are as reported: one-off charges and gains are included, and each uses the "
        "latest value known on the as-of date."
    ),
}


class ReportedError(ValueError):
    """The period can't be answered: unknown form, company not ingested, or not yet reported."""


# -- periods ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    fiscal_year: int
    fiscal_period: str  # Q1-Q4 or FY

    @property
    def label(self) -> str:
        return f"FY{self.fiscal_year}" + ("" if self.fiscal_period == "FY" else self.fiscal_period)

    @property
    def quarterly(self) -> bool:
        return self.fiscal_period != "FY"

    def year_earlier(self) -> "Period":
        return Period(self.fiscal_year - 1, self.fiscal_period)


def parse_period(text: str) -> Period:
    match = _PERIOD.fullmatch(text.strip().upper())
    if match is None:
        raise ReportedError(f"unknown period {text!r}: use {PERIOD_FORMS}")
    quarter = match["quarter"]
    return Period(int(match["year"]), f"Q{quarter}" if quarter else "FY")


# -- output -----------------------------------------------------------------------------------


def filing_url(cik: str, accession_no: str) -> str:
    """The filing's folder in the EDGAR archive, from its accession number (no download)."""
    return EDGAR_ARCHIVE.format(cik=int(cik), accession=accession_no.replace("-", ""))


@dataclass(frozen=True)
class Filing:
    accession_no: str
    form: str | None
    filed_at: date
    url: str


@dataclass(frozen=True)
class Version:
    """One filing's value for a line: the latest or the first reported."""

    value: float
    xbrl_concept: str
    filed_at: date
    filing: Filing | None  # None when derived: see `inputs`
    inputs: list[Filing] = field(default_factory=list)


@dataclass(frozen=True)
class Line:
    name: str  # the canonical item, e.g. revenue
    unit: str
    period_start: date | None  # None for a balance-sheet item
    period_end: date
    fiscal_year: int
    fiscal_period: str
    value: float  # the latest known on as_of
    latest: Version
    first_reported: Version
    changed: bool  # latest differs from first reported (the engine knows that, not why)
    derived: bool  # computed by Warren from other periods, e.g. Q4 = FY − nine months
    mixed_vintage: bool  # derived from restated and first-reported inputs together
    # backlog #290: a derived quarter put on one basis, as a run reads it (#264), carries the
    # plain derivation it replaced and a coded reason (`one_basis`); otherwise False and None
    one_basis: bool = False
    plain: Version | None = None
    basis_note: Coded | None = None


@dataclass(frozen=True)
class Ratio:
    name: str
    formula_id: str
    formula: str  # in words, English fallback
    value: float | None
    unit: str  # "fraction" or a currency
    uses: list[dict]  # {line, period}: entries of `lines`, or of `prior_lines` for growth
    missing: Coded | None = None
    notes: list[Coded] = field(default_factory=list)


@dataclass(frozen=True)
class Disagreement:
    """A period where the newest filing differs from the selected value (as the quality report)."""

    name: str
    period_start: date | None
    period_end: date
    selected: Version
    newest: Version


@dataclass
class ReportedPeriod:
    ticker: str
    cik: str
    company_name: str
    fiscal_year_end: str | None  # MMDD as SEC reports it
    history_ends: date | None  # where this CIK's filings stop (universe.csv), if they do
    period: str
    fiscal_year: int
    fiscal_period: str
    period_start: date
    period_end: date
    as_of: date
    lines: list[Line]
    prior_lines: list[Line]  # the same period a year earlier, used by growth
    ratios: list[Ratio]
    disagreements: list[Disagreement]
    as_reported_note: Coded
    warnings: list[Coded]

    def line(self, name: str) -> Line | None:
        return next((x for x in self.lines if x.name == name), None)

    def ratio(self, name: str) -> Ratio:
        return next(r for r in self.ratios if r.name == name)

    def to_dict(self) -> dict:
        """Plain JSON types: dates as ISO text, numbers unrounded."""
        return _plain(asdict(self))


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


# -- the query --------------------------------------------------------------------------------


@dataclass
class _Views:
    """Every item's facts as known on as_of, latest and first reported, keyed like History."""

    latest: History
    first: dict[tuple, Fact]
    names: list[str]
    plain: dict[tuple, Fact] = field(default_factory=dict)  # quarters before one basis (#290)


def _key(fact: Fact, quarterly: bool) -> tuple:
    if quarterly:
        return (fact.canonical_name, fact.fiscal_year, fact.fiscal_period)
    return (fact.canonical_name, fact.fiscal_year)


def _views(conn: sqlite3.Connection, cik: str, as_of: date, quarterly: bool) -> _Views:
    names = [r[0] for r in conn.execute("SELECT DISTINCT canonical_name FROM concepts")]
    frequency = "quarterly" if quarterly else "annual"
    # quarters on one basis, as a run reads them (#290); the plain derivation is kept beside
    latest = get_facts(conn, cik, names, as_of, frequency=frequency, one_basis=quarterly)
    first = get_facts(conn, cik, names, as_of, mode="first_reported", frequency=frequency)
    plain = {}
    if quarterly:
        plain = {_key(f, True): f for f in get_facts(conn, cik, names, as_of, frequency=frequency)}
    instants: dict[str, list[Fact]] = defaultdict(list)
    for f in sorted(latest, key=lambda f: f.period_end):
        if f.period_start is None:
            instants[f.canonical_name].append(f)
    history = History(
        quarterly={_key(f, True): f for f in latest} if quarterly else {},
        annual={} if quarterly else {_key(f, False): f for f in latest},
        instants=dict(instants),
    )
    return _Views(history, {_key(f, quarterly): f for f in first}, sorted(names), plain)


def _getter(views: _Views, period: Period) -> Callable[[str], Fact | None]:
    if period.quarterly:
        return views.latest.quarter(period.fiscal_year, period.fiscal_period)
    return views.latest.year(period.fiscal_year)


def latest_period(views: _Views, quarterly: bool) -> Period:
    facts = views.latest.quarterly if quarterly else views.latest.annual
    revenue = [f for k, f in facts.items() if k[0] == "revenue" and f.period_start is not None]
    if not revenue:
        raise ReportedError("no revenue reported by the as-of date")
    last = max(revenue, key=lambda f: f.period_end)
    return Period(last.fiscal_year, last.fiscal_period if quarterly else "FY")


class _Filings:
    """Form and filing date of every accession of one company (one query)."""

    def __init__(self, conn: sqlite3.Connection, cik: str):
        self.cik = cik
        self.rows = {
            r["accession_no"]: (r["form"], r["filed_at"])
            for r in conn.execute(
                "SELECT accession_no, MIN(form) AS form, MIN(filed_at) AS filed_at "
                "FROM financial_facts WHERE cik = ? GROUP BY accession_no",
                (cik,),
            )
        }

    def get(self, accession_no: str) -> Filing:
        form, filed_at = self.rows.get(accession_no, (None, None))
        return Filing(
            accession_no,
            form,
            date.fromisoformat(filed_at) if filed_at else None,
            filing_url(self.cik, accession_no),
        )

    def version(self, fact: Fact) -> Version:
        if fact.derived:
            inputs = [self.get(a) for a in fact.inputs]
            return Version(fact.value, fact.xbrl_concept, fact.filed_at, None, inputs)
        return Version(fact.value, fact.xbrl_concept, fact.filed_at, self.get(fact.accession_no))


def _line(fact: Fact, first: Fact | None, filings: _Filings, plain: Fact | None = None) -> Line:
    first = first or fact
    replaced = fact.one_basis and plain is not None and plain.value != fact.value
    return Line(
        name=fact.canonical_name,
        unit=fact.unit,
        period_start=fact.period_start,
        period_end=fact.period_end,
        fiscal_year=fact.fiscal_year,
        fiscal_period=fact.fiscal_period,
        value=fact.value,
        latest=filings.version(fact),
        first_reported=filings.version(first),
        changed=fact.value != first.value,
        derived=fact.derived,
        mixed_vintage=fact.mixed_vintage,
        one_basis=replaced,
        plain=filings.version(plain) if replaced else None,
        basis_note=_basis_note(fact, plain) if replaced else None,
    )


def _basis_note(fact: Fact, plain: Fact) -> Coded:
    """Why a derived quarter's value is not the plain derivation (backlog #264, #290)."""
    kind = basis_kind(fact)
    period = f"FY{fact.fiscal_year}{fact.fiscal_period}"
    if kind == "first_filed":
        why = (
            "a newer filing recast part of the year and no filing on the new basis gives the "
            "whole year yet, so the quarter is worked out from the figures as first reported, "
            "which share one basis"
        )
    else:
        why = (
            "a newer filing recast part of the year, so the quarter is worked out from the first "
            "filing that gives the year on the same new basis"
        )
    return Coded(
        "one_basis",
        {
            "item": fact.canonical_name,
            "period": period,
            "value": fact.value,
            "plain_value": plain.value,
            "basis": kind,
        },
        f"{fact.canonical_name} {period} is {fact.value:,.0f}, not {plain.value:,.0f} "
        f"(the year less the other quarters, each its newest version): {why}",
    )


def _lines(views: _Views, period: Period, filings: _Filings) -> list[Line]:
    """Every item the period reports: its flows, and the balances dated at its end."""
    get = _getter(views, period)
    revenue = get("revenue")
    if revenue is None:
        raise ReportedError(f"{period.label}: revenue not reported by the as-of date")
    lines = []
    for name in views.names:
        fact = get(name)
        if fact is None:
            continue
        if fact.period_start is None and fact.period_end != revenue.period_end:
            continue  # a balance dated elsewhere is not this period's line
        key = _key(fact, period.quarterly)
        lines.append(_line(fact, views.first.get(key), filings, views.plain.get(key)))
    return lines


def _in_scope(pair: tuple[Fact, Fact], line: Line) -> bool:
    """A disagreement row belongs to a line on the line's own period or, for a derived line, on a
    period of the same fiscal year that ends by the line's end (what a derivation is built from)."""
    selected = pair[0]
    if selected.canonical_name != line.name:
        return False
    if line.period_start is None:
        return selected.period_start is None and selected.period_end == line.period_end
    if not line.derived:
        return (selected.period_start, selected.period_end) == (line.period_start, line.period_end)
    return (
        selected.period_start is not None
        and selected.fiscal_year == line.fiscal_year
        and selected.period_end <= line.period_end
    )


def _disagreements(conn, cik, lines, as_of, filings) -> list[Disagreement]:
    names = sorted({x.name for x in lines})
    rows = newest_filing_disagreements(conn, cik, names, as_of)
    out = []
    for pair in rows:
        if any(_in_scope(pair, x) for x in lines):
            selected, newest = pair
            out.append(
                Disagreement(
                    selected.canonical_name,
                    selected.period_start,
                    selected.period_end,
                    filings.version(selected),
                    filings.version(newest),
                )
            )
    return out


def reported_period(
    conn: sqlite3.Connection, ticker: str, period: str | Period, as_of: date
) -> ReportedPeriod:
    """One fiscal period's reported lines and named ratios, as known on `as_of` (inclusive)."""
    company = conn.execute("SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if company is None:
        raise ReportedError(f"{ticker} has not been ingested")
    cik = company["cik"]
    if isinstance(period, str) and period.strip().lower() in (LATEST_QUARTER, LATEST_YEAR):
        quarterly = period.strip().lower() == LATEST_QUARTER
        resolved = None
    else:
        resolved = parse_period(period) if isinstance(period, str) else period
        quarterly = resolved.quarterly

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        views = _views(conn, cik, as_of, quarterly)
        resolved = resolved or latest_period(views, quarterly)
        filings = _Filings(conn, cik)
        lines = _lines(views, resolved, filings)
        disagreements = _disagreements(conn, cik, lines, as_of, filings)
        changes = tag_meaning_changes(conn, cik, ["revenue"], as_of)
    prior = resolved.year_earlier()
    prior_revenue = _getter(views, prior)("revenue")
    prior_key = _key(prior_revenue, quarterly) if prior_revenue else None
    prior_lines = (
        [_line(prior_revenue, views.first.get(prior_key), filings, views.plain.get(prior_key))]
        if prior_revenue
        else []
    )
    revenue = next(x for x in lines if x.name == "revenue")
    universe = next((c for c in PHASE1_UNIVERSE if c.cik == cik), None)
    return ReportedPeriod(
        ticker=company["ticker"],
        cik=cik,
        company_name=company["name"],
        fiscal_year_end=company["fiscal_year_end"],
        history_ends=universe.history_ends if universe else None,
        period=resolved.label,
        fiscal_year=resolved.fiscal_year,
        fiscal_period=resolved.fiscal_period,
        period_start=revenue.period_start,
        period_end=revenue.period_end,
        as_of=as_of,
        lines=lines,
        prior_lines=prior_lines,
        ratios=_ratios(views, resolved, lines, prior_lines, changes),
        disagreements=disagreements,
        as_reported_note=Coded(AS_REPORTED["code"], {}, AS_REPORTED["text"]),
        warnings=_coded_warnings(caught, universe),
    )


def _coded_warnings(caught, universe) -> list[Coded]:
    """The caught warnings, coded as a run's are (backlog #172): `beyond_history` carries
    `history_ends` and, since #172, `ticker`, `cik`, `as_of` and `note`; since #196, `reason`,
    `successor_cik` and `successor_name`. A warning that is not Warren's own goes back to the
    log."""
    pass_on(caught)
    return coded_warnings(caught)


# -- ratios -----------------------------------------------------------------------------------


def _missing(items: list[str]) -> Coded:
    return Coded(
        "not_reported", {"items": items}, f"not reported for this period: {', '.join(items)}"
    )


def _base_not_positive(item: str, value: float) -> Coded:
    return Coded(
        "base_not_positive",
        {"item": item, "value": value},
        f"{item} is {value:,.0f}, at or below zero: the ratio has no meaning",
    )


def _uses(facts: list[Fact], period: Period) -> list[dict]:
    """Each line a ratio used, once (tax appears in both terms under the third pretax rule)."""
    names = dict.fromkeys(f.canonical_name for f in facts)
    return [{"line": name, "period": period.label} for name in names]


def _changed_note(facts: list[Fact], lines: list[Line]) -> list[Coded]:
    names = {f.canonical_name for f in facts}
    changed = [x.name for x in lines if x.changed and x.name in names]
    out = []
    if changed:
        out.append(
            Coded(
                "uses_changed_line",
                {"items": changed},
                f"uses the latest value of {', '.join(changed)}, which differs from the first "
                "reported",
            )
        )
    return out + _one_basis_note([x for x in lines if x.name in names])


def _one_basis_note(lines: list[Line]) -> list[Coded]:
    """A ratio that uses a quarter put on one basis says so (backlog #290)."""
    used = [x for x in lines if x.one_basis]
    if not used:
        return []
    items = list(dict.fromkeys(x.name for x in used))
    periods = sorted({f"FY{x.fiscal_year}{_q(x)}" for x in used})
    return [
        Coded(
            "uses_one_basis_line",
            {"items": items, "periods": periods},
            f"uses {', '.join(items)} for {', '.join(periods)} on one basis, not the plain "
            "derivation (see the line)",
        )
    ]


def _chain(chain: str, get) -> tuple[list[Fact] | None, int, list[str]]:
    """The first alternative of an engine chain that the period reports, and its index."""
    tried = []
    for i, items in enumerate(CHAINS[chain]):
        facts = [get(item) for item in items]
        if all(facts):
            return facts, i, []
        tried += [item for item, f in zip(items, facts, strict=True) if f is None]
    return None, -1, sorted(set(tried))


def _ratio(name, formula_id, formula, numerator, base, lines, period, notes=(), used=None) -> Ratio:
    """A fraction: the summed numerator facts (or a number) over the summed base facts, which
    must be positive. `used` lists the facts behind a numerator given as a number."""
    num_facts = [] if isinstance(numerator, int | float) else numerator
    used = [*(used or num_facts), *base]
    base_value = sum(f.value for f in base)
    if base_value <= 0:
        missing = _base_not_positive("+".join(f.canonical_name for f in base), base_value)
        return Ratio(name, formula_id, formula, None, "fraction", _uses(used, period), missing)
    top = numerator if not num_facts else sum(f.value for f in num_facts)
    value = fm.ratio(top, base_value)
    notes = [*notes, *_changed_note(used, lines)]
    return Ratio(name, formula_id, formula, value, "fraction", _uses(used, period), None, notes)


def _gap(name, formula_id, formula, items) -> Ratio:
    return Ratio(name, formula_id, formula, None, "fraction", [], _missing(items))


QUARTERLY_TAX_NOTE = Coded(
    "interim_tax_rate",
    {},
    "a quarter's rate follows the estimated annual rate plus that quarter's one-off items, so it "
    "can swing from quarter to quarter",
)


def _ratios(
    views: _Views,
    period: Period,
    lines: list[Line],
    prior_lines: list[Line],
    changes: list[MeaningChange] = (),
):
    get = _getter(views, period)
    revenue = get("revenue")
    out = []

    name, fid = "gross_margin", "revenue_less_cost_over_revenue"
    formula = (
        "(revenue − cost of revenue) ÷ revenue, on total revenue as tagged (a company's own "
        "gross margin may use net sales, and cost of revenue includes D&A for some companies)"
    )
    cost = get("cost_of_revenue")
    if cost is None:
        out.append(_gap(name, fid, formula, ["cost_of_revenue"]))
    else:
        gross = revenue.value - cost.value
        out.append(_ratio(name, fid, formula, gross, [revenue], lines, period, used=[cost]))

    facts, i, missing = _chain("ebit", get)
    if facts is None:
        out.append(_gap("operating_margin", "ebit_over_revenue", "EBIT ÷ revenue", missing))
    elif i == 0:
        formula = "operating income ÷ revenue"
        fid = "ebit_over_revenue"
        out.append(_ratio("operating_margin", fid, formula, facts, [revenue], lines, period))
    else:
        formula = (
            "(pretax income + interest expense) ÷ revenue: the company reports no operating "
            "income, so this EBIT keeps other income such as interest and equity-company income"
        )
        note = Coded(
            "ebit_from_pretax_plus_interest",
            {},
            "EBIT is pretax income + interest expense, not operating income",
        )
        out.append(
            _ratio(
                "operating_margin",
                "pretax_plus_interest_over_revenue",
                formula,
                facts,
                [revenue],
                lines,
                period,
                [note],
            )
        )

    out.append(_growth(views, period, revenue, lines, prior_lines, changes))

    for chain, name, words in (("capex", "capex_share", "capex"), ("d_and_a", "da_share", "D&A")):
        facts, i, missing = _chain(chain, get)
        fid = f"{chain}_over_revenue" + ("" if i <= 0 else "_fallback")
        formula = f"{words} ÷ revenue" + (
            " (D&A = depreciation + amortisation of intangibles)" if i > 0 else ""
        )
        if facts is None:
            out.append(_gap(name, fid, formula, missing))
        else:
            out.append(_ratio(name, fid, formula, facts, [revenue], lines, period))

    out.append(_tax(get, period, lines))
    out.append(_net_debt(views, revenue, period, lines))
    out.append(_net_margin(get, revenue, period, lines))
    return out


NET_MARGIN_FORMULA = (
    "net income attributable to the parent's shareholders ÷ revenue (after the non-controlling "
    "interests' share; includes discontinued operations)"
)


def _net_margin(get, revenue: Fact, period: Period, lines: list[Line]) -> Ratio:
    """Net income to the parent over revenue (backlog #157). Discontinued operations stay in, as
    the filing reports them, and a coded note gives their amount and, when it is one, their share
    of net income, so a one-off exit is not read as a better business."""
    name, fid = "net_margin", "net_income_to_parent_over_revenue"
    net_income = get("net_income")
    if net_income is None:
        return _gap(name, fid, NET_MARGIN_FORMULA, ["net_income"])
    notes, used = [], [net_income]
    discontinued = get("discontinued_operations")
    if discontinued is not None and discontinued.value != 0:
        used.append(discontinued)
        params = {"amount": discontinued.value, "currency": discontinued.unit}
        text = f"includes {discontinued.value:,.0f} from discontinued operations"
        if net_income.value > 0 and 0 < discontinued.value <= net_income.value:
            share = fm.ratio(discontinued.value, net_income.value)
            params["share_of_net_income"] = share
            text += f" ({share:.0%} of net income)"
        notes.append(Coded("includes_discontinued_operations", params, text))
    return _ratio(
        name, fid, NET_MARGIN_FORMULA, [net_income], [revenue], lines, period, notes, used
    )


def _growth(views, period, revenue, lines, prior_lines, changes=()) -> Ratio:
    prior_period = period.year_earlier()
    formula = f"revenue {period.label} ÷ revenue {prior_period.label} − 1"
    fid = "revenue_yoy"
    if not prior_lines:
        return Ratio(
            "revenue_growth_yoy", fid, formula, None, "fraction", [], _missing(["revenue (prior)"])
        )
    prior = _getter(views, prior_period)("revenue")
    uses = [{"line": "revenue", "period": period.label}]
    uses.append({"line": "revenue", "period": prior_period.label})
    if prior.value <= 0:
        missing = _base_not_positive("revenue (prior)", prior.value)
        return Ratio("revenue_growth_yoy", fid, formula, None, "fraction", uses, missing)
    notes = []
    days = (revenue.period_end - revenue.period_start).days + 1
    prior_days = (prior.period_end - prior.period_start).days + 1
    if abs(days - prior_days) >= LENGTH_NOTE_DAYS:
        notes.append(
            Coded(
                "period_length_differs",
                {"days": days, "prior_days": prior_days},
                f"the periods differ in length ({days} days against {prior_days}): a 53-week "
                "year or a 14-week quarter",
            )
        )
    if revenue.xbrl_concept != prior.xbrl_concept:
        notes.append(
            Coded(
                "tag_differs",
                {"tag": revenue.xbrl_concept, "prior_tag": prior.xbrl_concept},
                f"the two years use different tags ({revenue.xbrl_concept} against "
                f"{prior.xbrl_concept})",
            )
        )
    if revenue.mixed_vintage or prior.mixed_vintage:
        notes.append(
            Coded(
                "mixed_vintage",
                {},
                "a derived quarter here mixes restated and first-reported figures",
            )
        )
    changed = [x for x in [*lines, *prior_lines] if x.name == "revenue" and x.changed]
    if changed:
        periods = sorted({f"FY{x.fiscal_year}" + _q(x) for x in changed})
        notes.append(
            Coded(
                "uses_changed_line",
                {"items": ["revenue"], "periods": periods},
                "uses the latest revenue, which differs from the first reported for "
                + ", ".join(periods),
            )
        )
    notes += _one_basis_note([x for x in [*lines, *prior_lines] if x.name == "revenue"])
    notes += _meaning_note(revenue, prior, period, prior_period, changes)
    value = fm.growth(revenue.value, prior.value)
    return Ratio("revenue_growth_yoy", fid, formula, value, "fraction", uses, None, notes)


def _meaning_note(revenue, prior, period, prior_period, changes) -> list[Coded]:
    """Growth across a tag that changed meaning (backlog #295): one period's revenue carries the
    tag's new meaning, the other its old one, so the two are not like for like."""
    new, old = meaning_of(revenue, changes), meaning_of(prior, changes)
    if (new is None) == (old is None):
        return []
    change = new or old
    newer, older = (period, prior_period) if new else (prior_period, period)
    return [
        Coded(
            "tag_changed_meaning",
            {
                "item": "revenue",
                "tag": change.xbrl_concept,
                "other_tag": change.other_concept,
                "changed_on": change.filed_at.isoformat(),
                "form": change.form,
                "accession_no": change.accession_no,
                "new_meaning": newer.label,
                "old_meaning": older.label,
            },
            f"revenue for {newer.label} uses {change.xbrl_concept} as the {change.form} filed "
            f"{change.filed_at.isoformat()} redefined it, {older.label} its old meaning (the old "
            f"figures are still filed under {change.other_concept}): not like for like",
        )
    ]


def _q(line: Line) -> str:
    return "" if line.fiscal_period == "FY" else line.fiscal_period


def _tax(get, period: Period, lines: list[Line]) -> Ratio:
    tax, _, missing_tax = _chain("tax", get)
    pretax, i, missing_pretax = _chain("pretax", get)
    words = ["pretax income", "domestic + foreign pretax income", "net income + income tax"][
        max(i, 0)
    ]
    fid = ["tax_over_pretax", "tax_over_pretax_by_region", "tax_over_net_income_plus_tax"][
        max(i, 0)
    ]
    formula = f"income tax ÷ {words}, not clipped (the valuation clips its tax rate to 0–50%)"
    if tax is None or pretax is None:
        return _gap("effective_tax_rate", fid, formula, sorted(missing_tax + missing_pretax))
    notes = [QUARTERLY_TAX_NOTE] if period.quarterly else []
    return _ratio("effective_tax_rate", fid, formula, tax, pretax, lines, period, notes)


def _net_debt(views: _Views, revenue: Fact, period: Period, lines: list[Line]) -> Ratio:
    """Debt (D3) less cash and securities at the period's end; a balance not dated there is
    carried from up to a year before, as the valuation does, and named."""
    day = revenue.period_end
    get = lambda item: views.latest.latest_before(item, day)  # noqa: E731
    formula = (
        "debt (current and non-current debt, short-term borrowings or commercial paper, finance "
        "leases; operating leases excluded, their cost is in operating income) − (cash + "
        "marketable securities, current and non-current, + other short-term investments)"
    )
    fid = "debt_less_cash_and_securities"
    cash = get("cash")
    if cash is None:
        return Ratio("net_debt", fid, formula, None, "USD", [], _missing(["cash"]))
    debt, used, zero, debt_notes = debt_parts(get)
    cash_facts = [f for f in (get(i) for i in CASH_ITEMS) if f is not None]
    zero += [i for i in CASH_ITEMS if get(i) is None]
    value = fm.net_debt(debt, sum(f.value for f in cash_facts))
    facts = [*used, *cash_facts]
    uses = [
        {"line": f.canonical_name, "period": period.label, "balance_date": f.period_end.isoformat()}
        for f in facts
    ]
    notes = []
    carried = {f.canonical_name: f.period_end.isoformat() for f in facts if f.period_end < day}
    if carried:
        notes.append(
            Coded(
                "carried_forward",
                {"items": carried},
                "not reported at the period's end, taken from an earlier balance within a year: "
                + ", ".join(f"{k} ({v})" for k, v in carried.items()),
            )
        )
    if zero:
        items = sorted(set(zero))
        notes.append(
            Coded(
                "counted_as_zero",
                {"items": items},
                "not reported within a year of the period's end, counted as zero: "
                + ", ".join(items),
            )
        )
    if debt_notes:
        notes.append(Coded("finance_leases_in_debt_tag", {}, debt_notes))
    if value < 0:
        notes.append(Coded("net_cash", {}, "negative: the company holds more cash than debt"))
    notes += _changed_note(facts, lines)
    return Ratio("net_debt", fid, formula, value, revenue.unit, uses, None, notes)
