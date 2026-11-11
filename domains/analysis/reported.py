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
- A version filed with its sign flipped is skipped (backlog #280); the line it would have been
  says so in `sign_notes`, naming both filings, and ratios that use the line say so (#282).
- A tag that changed meaning (#295) is noted on growth and, since #297, on the line itself
  (`meaning_note`): which meaning its figure, its first-reported figure and its plain derivation
  carry, "mixed" for a derived quarter worked out from figures filed on both sides of the change.
- Values are raw, unrounded, in the line's unit (USD, shares); ratios are fractions (0.2 = 20%).
"""

import re
import sqlite3
import warnings
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date

from domains.analysis import financial_math as fm
from domains.analysis.coded import Coded, coded_warnings, pass_on
from domains.analysis.math_engine import CASH_ITEMS, CHAINS, History, basis_kind, debt_parts
from domains.fundamentals.facts import (
    MEANING_CHANGE_MATCH,
    MeaningChange,
    Recast,
    dating_changes,
    filing_dates,
    get_facts,
    item_recasts,
    meaning_state,
    mixes_meanings,
    newest_filing_disagreements,
    side_of_recast,
    skipped_sign_flips,
    state_for_change,
    tag_meaning_changes,
    version_dates,
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
        "latest value known on the as-of date (a version whose sign is flipped against another "
        "filing's version of the same period is skipped, and the line says so)."
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
    # backlog #282: one `sign_flip_skipped` note per version filed with its sign flipped that
    # was skipped for this line (#280), its own period's or a derivation input's; usually empty
    sign_notes: list[Coded] = field(default_factory=list)
    # backlog #297: a `tag_changed_meaning` note when the line's figure, its first-reported figure
    # or its plain derivation do not all carry the same meaning of a tag that changed meaning
    # (#295), e.g. Exxon's FY2018 revenue, first reported as sales and now total revenues and
    # other income; otherwise None
    meaning_note: Coded | None = None
    # backlog #324: a quarter its filing gave only under a tag Warren ranks below the one tag of
    # the year and the periods before it is derived on the year's tag; `tag_note` (code
    # `quarter_on_year_tag`) gives the figure as filed. Otherwise None
    tag_note: Coded | None = None


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
    # a quarter derived on its year's tag (#324): the narrower figure its own filing gave
    narrow: dict[tuple, Fact] = field(default_factory=dict)


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
    narrow = {}
    if any(f.narrower_tag for f in latest):
        spans = {
            (f.canonical_name, f.period_start, f.period_end, f.narrower_tag): _key(f, True)
            for f in latest
            if f.narrower_tag
        }
        for f in get_facts(conn, cik, sorted({k[0] for k in spans}), as_of):
            key = spans.get((f.canonical_name, f.period_start, f.period_end, f.xbrl_concept))
            if key is not None:
                narrow[key] = f
    first_by_key = {_key(f, quarterly): f for f in first}
    return _Views(history, first_by_key, sorted(names), plain, narrow)


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
        self.filed_at = filing_dates(conn, cik)

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


def _line(
    fact: Fact,
    first: Fact | None,
    filings: _Filings,
    plain: Fact | None = None,
    changes: list[MeaningChange] | None = None,
) -> Line:
    first = first or fact
    replaced = fact.one_basis and plain is not None and plain.value != fact.value
    line = Line(
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
    if not changes:
        return line
    facts = {"latest": fact, "first_reported": first, "plain": plain if replaced else None}
    return _with_meaning_note(line, facts, changes, filings)


def _with_tag_note(line: Line, fact: Fact, narrow: Fact | None, filings: "_Filings") -> Line:
    """A quarter derived on its year's tag says what its own filing gave (backlog #324)."""
    if not fact.narrower_tag or narrow is None:
        return line
    filing = filings.get(narrow.accession_no)
    period = f"FY{fact.fiscal_year}{fact.fiscal_period}"
    tag = fact.xbrl_concept
    filed = filing.filed_at.isoformat() if filing.filed_at else None
    note = Coded(
        "quarter_on_year_tag",
        {
            "item": fact.canonical_name,
            "period": period,
            "period_end": fact.period_end.isoformat(),
            "value": fact.value,
            "reported_value": narrow.value,
            "reported_tag": narrow.xbrl_concept,
            "tag": tag,
            "form": filing.form,
            "filed_at": filed,
            "accession_no": narrow.accession_no,
        },
        f"{fact.canonical_name} {period} (the quarter ending {fact.period_end}) is "
        f"{fact.value:,.0f}, worked out from figures all under {tag}, the tag of the year and "
        f"the other quarters; the {filing.form} filed {filed} gives the quarter as "
        f"{narrow.value:,.0f}, but only under {narrow.xbrl_concept}, a tag Warren ranks below "
        "it, so the four quarters would not measure the same line or add up to the year",
    )
    return replace(line, tag_note=note)


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


def _lines(
    views: _Views, period: Period, filings: _Filings, changes: list[MeaningChange]
) -> list[Line]:
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
        line = _line(fact, views.first.get(key), filings, views.plain.get(key), changes)
        lines.append(_with_tag_note(line, fact, views.narrow.get(key), filings))
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


def _rests_on(line: Line, used: Fact) -> bool:
    """The line's value was read from `used`: its own period's version, or for a derived quarter
    an input of the derivation (same fiscal year, ending by the line's end, and its filing one of
    the derivation's inputs)."""
    if not _in_scope((used, used), line):
        return False
    if not line.derived:
        return True
    return used.accession_no in {i.accession_no for i in line.latest.inputs}


def _with_sign_notes(line: Line, flips: list[tuple[Fact, Fact]], filings: _Filings) -> Line:
    """The line with a `sign_flip_skipped` note for each skipped version it rests on (#282)."""
    notes = [
        _sign_note(line, used, skipped, filings) for used, skipped in flips if _rests_on(line, used)
    ]
    return replace(line, sign_notes=notes) if notes else line


def _filing_params(fact: Fact, filings: _Filings) -> dict:
    filing = filings.get(fact.accession_no)
    return {
        "accession_no": fact.accession_no,
        "form": filing.form,
        "filed_at": fact.filed_at.isoformat(),
        "value": fact.value,
    }


def _sign_note(line: Line, used: Fact, skipped: Fact, filings: _Filings) -> Coded:
    """Why the line's figure is not the version a filing tagged with the opposite sign (#280)."""
    period = f"FY{line.fiscal_year}{_q(line)}"
    first = line.first_reported
    first_filings = [first.filing] if first.filing else first.inputs
    first_skipped = skipped.accession_no in {f.accession_no for f in first_filings}
    skip, use = _filing_params(skipped, filings), _filing_params(used, filings)
    text = (
        f"{line.name} {period}: the {skip['form']} filed {skip['filed_at']} tagged "
        f"{skipped.value:,.0f} for {used.period_start or ''}–{used.period_end}, the opposite sign "
        f"of {used.value:,.0f} in the {use['form']} filed {use['filed_at']}; treated as a "
        "sign-tagging error and skipped"
    )
    size_differs = abs(skipped.value) != abs(used.value)
    if first_skipped and not size_differs:
        text += " (the figure differs from the first reported because of this, not a restatement)"
    elif first_skipped:
        text += (
            " (the figure differs from the first reported because of this; the size changed "
            "too, so part of the change is a revision)"
        )
    return Coded(
        "sign_flip_skipped",
        {
            "item": line.name,
            "period": period,
            "input_start": used.period_start.isoformat() if used.period_start else None,
            "input_end": used.period_end.isoformat(),
            "used": use,
            "skipped": skip,
            "first_reported_skipped": first_skipped,
            "size_differs": size_differs,
        },
        text,
    )


def _with_meaning_note(
    line: Line, facts: dict[str, Fact | None], changes: list[MeaningChange], filings: "_Filings"
) -> Line:
    """The line with a `tag_changed_meaning` note when its figures carry different meanings of
    a changed tag (backlog #297). `facts` holds the line's latest, first-reported and plain
    `Fact`s (the plain one only when it was replaced by a one-basis figure)."""
    states = {
        k: meaning_state(f, changes, filings.filed_at) for k, f in facts.items() if f is not None
    }
    change = next((c for _s, c in states.values() if c is not None), None)
    meaning = {k: s for k, (s, _c) in states.items()}
    if change is None or (len(set(meaning.values())) == 1 and "mixed" not in meaning.values()):
        return line
    return replace(line, meaning_note=_meaning_line_note(line, change, meaning))


_MEANING_WORDS = {
    "new": "the meaning the {form} filed {day} gave the tag",
    "old": "the tag's earlier meaning",
    "mixed": "both meanings: it is worked out from figures filed before and after the change",
}


def _meaning_line_note(line: Line, change: MeaningChange, meaning: dict[str, str]) -> Coded:
    """Which meaning each of the line's figures carries, and what that does to `changed`."""
    period = f"FY{line.fiscal_year}{_q(line)}"
    day = change.filed_at.isoformat()

    def words(state: str) -> str:
        return _MEANING_WORDS[state].format(form=change.form, day=day)

    first_differs = meaning["first_reported"] != meaning["latest"]
    whole = _whole_change(line, change) if first_differs else None
    text = f"{line.name} {period} is {change.xbrl_concept} with {words(meaning['latest'])}"
    if first_differs:
        text += (
            f"; the first-reported {line.first_reported.value:,.0f} has "
            f"{words(meaning['first_reported'])}, whose figures are still filed under "
            f"{change.other_concept}. "
        )
        text += (
            "The difference from the first reported comes from the move to a different line, "
            "not a restatement"
            if whole
            else "At least part of the difference from the first reported comes from the move "
            "to a different line, not a restatement; the rest may be a revision"
        )
    if "plain" in meaning and meaning["plain"] != meaning["latest"]:
        text += (
            f"; the year less the other quarters, each its newest version, would have "
            f"{words(meaning['plain'])}"
        )
    return Coded(
        "tag_changed_meaning",
        {
            "item": line.name,
            "period": period,
            "tag": change.xbrl_concept,
            "other_tag": change.other_concept,
            "changed_on": day,
            "form": change.form,
            "accession_no": change.accession_no,
            "meaning": meaning["latest"],
            "first_reported_meaning": meaning["first_reported"],
            "plain_meaning": meaning.get("plain"),
            "first_reported_differs": first_differs,
            "whole_change": whole,
        },
        text,
    )


def _whole_change(line: Line, change: MeaningChange) -> bool | None:
    """Whether the new meaning explains all of the change from the first reported: the line's
    own period is one the change shows, its first-reported figure is the tag's value before the
    change and its value the tag's value after (within `MEANING_CHANGE_MATCH`). False when the
    period shows the change but either differs (part is a revision); None when the period is not
    one the change shows, as for a derived quarter (not known, so the text hedges)."""
    for start, end, old, new in change.periods:
        if (start, end) == (line.period_start, line.period_end) and not line.derived:
            return _close(line.first_reported.value, old) and _close(line.value, new)
    return None


def _close(value: float, target: float) -> bool:
    return abs(value - target) <= MEANING_CHANGE_MATCH * abs(target)


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
        changes = tag_meaning_changes(conn, cik, ["revenue"], as_of)
        lines = _lines(views, resolved, filings, changes)
        disagreements = _disagreements(conn, cik, lines, as_of, filings)
        flips = skipped_sign_flips(conn, cik, sorted({x.name for x in lines}), as_of)
    prior = resolved.year_earlier()
    prior_revenue = _getter(views, prior)("revenue")
    prior_key = _key(prior_revenue, quarterly) if prior_revenue else None
    prior_lines = (
        [
            _with_tag_note(
                _line(
                    prior_revenue,
                    views.first.get(prior_key),
                    filings,
                    views.plain.get(prior_key),
                    changes,
                ),
                prior_revenue,
                views.narrow.get(prior_key),
                filings,
            )
        ]
        if prior_revenue
        else []
    )
    lines = [_with_sign_notes(x, flips, filings) for x in lines]
    prior_lines = [_with_sign_notes(x, flips, filings) for x in prior_lines]
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
        ratios=_ratios(views, resolved, lines, prior_lines, changes, filings.filed_at),
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
    used = [x for x in lines if x.name in names]
    return out + _year_tag_note(used) + _one_basis_note(used) + _sign_checked_note(used)


def _year_tag_note(lines: list[Line]) -> list[Coded]:
    """A ratio that uses a quarter derived on its year's tag says so (backlog #324)."""
    used = [x for x in lines if x.tag_note]
    if not used:
        return []
    items = list(dict.fromkeys(x.name for x in used))
    periods = sorted({f"FY{x.fiscal_year}{_q(x)}" for x in used})
    return [
        Coded(
            "uses_quarter_on_year_tag",
            {"items": items, "periods": periods},
            f"uses {', '.join(items)} for {', '.join(periods)} worked out on the year's tag, not "
            "the figure its filing gave under a lower-ranked tag (see the line)",
        )
    ]


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


def _sign_checked_note(lines: list[Line]) -> list[Coded]:
    """A ratio that uses a line where a version filed with its sign flipped was skipped (#282)."""
    used = [x for x in lines if x.sign_notes]
    if not used:
        return []
    items = list(dict.fromkeys(x.name for x in used))
    periods = sorted({f"FY{x.fiscal_year}{_q(x)}" for x in used})
    return [
        Coded(
            "uses_sign_checked_line",
            {"items": items, "periods": periods},
            f"uses {', '.join(items)} for {', '.join(periods)}, where a version filed with its "
            "sign flipped was skipped (see the line)",
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
    filed_at: dict[str, date] | None = None,
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

    out.append(_growth(views, period, revenue, lines, prior_lines, changes, filed_at))

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


def _growth(views, period, revenue, lines, prior_lines, changes=(), filed_at=None) -> Ratio:
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
    notes += _year_tag_note([x for x in [*lines, *prior_lines] if x.name == "revenue"])
    notes += _one_basis_note([x for x in [*lines, *prior_lines] if x.name == "revenue"])
    notes += _sign_checked_note([x for x in [*lines, *prior_lines] if x.name == "revenue"])
    notes += _meaning_note(revenue, prior, period, prior_period, changes, filed_at)
    value = fm.growth(revenue.value, prior.value)
    return Ratio("revenue_growth_yoy", fid, formula, value, "fraction", uses, None, notes)


def _meaning_note(revenue, prior, period, prior_period, changes, filed_at) -> list[Coded]:
    """Growth across a tag that changed meaning (backlog #295): one period's revenue carries the
    tag's new meaning, the other its old one, so the two are not like for like. Since #297 a
    derived quarter worked out from figures filed on both sides of the change is "mixed", and
    growth with a mixed period is noted too (`mixed` names it; `new_meaning` or `old_meaning`
    is null when no period carries that meaning alone)."""
    state, change = meaning_state(revenue, changes, filed_at)
    prior_state, prior_change = meaning_state(prior, changes, filed_at)
    change = change or prior_change
    if change is None or (state == prior_state and state != "mixed"):
        return []
    labels = {period.label: state, prior_period.label: prior_state}
    newer = next((k for k, v in labels.items() if v == "new"), None)
    older = next((k for k, v in labels.items() if v == "old"), None)
    mixed = [k for k, v in labels.items() if v == "mixed"]
    day = change.filed_at.isoformat()
    if not mixed:
        text = (
            f"revenue for {newer} is {change.xbrl_concept} with the meaning the {change.form} "
            f"filed {day} gave it; {older} has its earlier meaning, whose figures are still "
            f"filed under {change.other_concept}. The two measure different lines: not like "
            "for like"
        )
    else:
        text = (
            f"revenue for {' and '.join(mixed)} is worked out from {change.xbrl_concept} figures "
            f"filed before and after the {change.form} of {day} gave the tag a new meaning, so "
            "it mixes two different lines (the earlier meaning is still filed under "
            f"{change.other_concept}): not like for like"
        )
    return [
        Coded(
            "tag_changed_meaning",
            {
                "item": "revenue",
                "tag": change.xbrl_concept,
                "other_tag": change.other_concept,
                "changed_on": day,
                "form": change.form,
                "accession_no": change.accession_no,
                "new_meaning": newer,
                "old_meaning": older,
                "mixed": mixed,
            },
            text,
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


# -- backlog #297 item 2: a series of periods across a tag that changed meaning ---------------

SERIES_MAX_PERIODS = 20


@dataclass(frozen=True)
class ReportedSeries:
    """Several fiscal periods asked together (brief Q2), each exactly as `reported_period` gives
    it, in time order, with notes about the series as a whole."""

    ticker: str
    cik: str
    company_name: str
    as_of: date
    periods: list[ReportedPeriod]
    notes: list[Coded]

    def to_dict(self) -> dict:
        """Plain JSON types: dates as ISO text, numbers unrounded."""
        return _plain(asdict(self))


def reported_series(
    conn: sqlite3.Connection, ticker: str, periods: list[str | Period], as_of: date
) -> ReportedSeries:
    """Several fiscal years, or several quarters, as known on `as_of`, and a
    `series_mixes_meanings` note when their revenue figures do not all carry one meaning of a
    tag that changed meaning (Exxon's FY2016 revenue is sales, its FY2017 total revenues and
    other income, so a margin series across them is not like for like)."""
    if not periods:
        raise ReportedError("a series needs at least one period")
    if len(periods) > SERIES_MAX_PERIODS:
        raise ReportedError(f"a series takes at most {SERIES_MAX_PERIODS} periods")
    answers = [reported_period(conn, ticker, p, as_of) for p in periods]
    labels = [r.period for r in answers]
    if len(set(labels)) != len(labels):
        twice = sorted({x for x in labels if labels.count(x) > 1})
        raise ReportedError(f"a period is asked twice: {', '.join(twice)}")
    if len({r.fiscal_period == "FY" for r in answers}) > 1:
        raise ReportedError("a series is all fiscal years or all quarters, not both")
    answers.sort(key=lambda r: r.period_end)
    first = answers[0]
    return ReportedSeries(
        ticker=first.ticker,
        cik=first.cik,
        company_name=first.company_name,
        as_of=as_of,
        periods=answers,
        notes=_series_meaning_notes(conn, answers, as_of)
        + _series_recast_notes(conn, answers, as_of),
    )


def _series_meaning_notes(
    conn: sqlite3.Connection, answers: list[ReportedPeriod], as_of: date
) -> list[Coded]:
    """One `series_mixes_meanings` note per change of meaning whose periods in the series do not
    all carry its new meaning, when at least one does (or any is a mix). A period's state is
    `meaning_state` on the very fact its revenue line shows (one-basis for a quarter). A period
    filed under the changed tag, or under the tag that keeps the earlier meaning, before the
    change is "old"; one filed under any other tag is "other" (nothing is known of its meaning).
    The note says where this break is; it says nothing about other changes on either side (a
    recast that no other tag records is `series_mixes_vintages`, #297 item 13)."""
    cik, quarterly = answers[0].cik, answers[0].fiscal_period != "FY"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # each period already carries its coded warnings
        changes = tag_meaning_changes(conn, cik, ["revenue"], as_of)
        if not changes:
            return []
        views = _views(conn, cik, as_of, quarterly)
    filed_at = _Filings(conn, cik).filed_at
    facts = {r.period: _getter(views, parse_period(r.period))("revenue") for r in answers}
    ratios = _revenue_ratios(answers)
    notes = []
    for change in dating_changes(facts.values(), changes, filed_at):
        of = {k: state_for_change(f, change, changes, filed_at) for k, f in facts.items()}
        if mixes_meanings(of.values()):
            notes.append(_series_note(change, of, ratios))
    return notes


def _series_note(change: MeaningChange, of: dict[str, str], ratios: list[str]) -> Coded:
    kinds = ("old", "new", "mixed", "other")
    groups = {s: [k for k, v in of.items() if v == s] for s in kinds}
    day = change.filed_at.isoformat()
    parts = []
    if groups["old"]:
        verb = "carries" if len(groups["old"]) == 1 else "carry"
        parts.append(f"{_and(groups['old'])} {verb} the tag's earlier meaning")
    if groups["new"]:
        parts.append(f"{_and(groups['new'])} the meaning the {change.form} filed {day} gave it")
    if groups["mixed"]:
        parts.append(
            f"{_and(groups['mixed'])} a mix of both (worked out from figures filed on both sides)"
        )
    if groups["other"]:
        parts.append(f"{_and(groups['other'])} another tag, of unknown meaning")
    on = f", and the ratios on it ({', '.join(ratios)})," if ratios else ""
    text = (
        f"revenue in this series is {change.xbrl_concept} with more than one meaning: "
        f"{'; '.join(parts)}. Across that break revenue{on} are not like for like. Only the "
        f"periods the change shows are also filed on the earlier meaning, under "
        f"{change.other_concept}. This says nothing about other changes within either side."
    )
    return Coded(
        "series_mixes_meanings",
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
            "ratios": ratios,
        },
        text,
    )


# -- backlog #297 item 13: a series across a recast that left some of its periods unchanged ----

ANNUAL_MIN_DAYS = 300  # a recast counts for a series of years only when it moved a year
QUARTER_SPAN = (80, 100)  # and for a series of quarters only when it moved a quarter (#325)


def _series_recast_notes(
    conn: sqlite3.Connection, answers: list[ReportedPeriod], as_of: date
) -> list[Coded]:
    """One `series_mixes_vintages` note per recast of revenue (`facts.item_recasts`: a filing
    gave earlier periods new figures, and no tag still holds the old ones) that leaves the series
    on both sides: at least one period every filing of which came before the recast, and at least
    one reported in it or after it (or, for a derived quarter, worked out across it). A series of
    years counts only recasts that moved a year. A series of quarters counts recasts that moved
    a quarter or a year, and gives the largest quarter move, or the year's when no quarter moved
    (`largest_move_on`, backlog #325): a restated year restates its quarters even when they are
    not tagged (Apple's 10-K/A of 2010-01-25, analyst, design review), while a filing that moved
    only half years or nine months moved nothing a quarter series shows. A recast whose split
    repeats an earlier one's is left out (Johnson & Johnson's 10-Q of 2023-10-27, then its 10-K
    of 2024-02-16)."""
    cik, quarterly = answers[0].cik, answers[0].fiscal_period != "FY"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # each period already carries its coded warnings
        recasts = [
            r
            for r in item_recasts(conn, cik, "revenue", as_of)
            if r.largest_move(ANNUAL_MIN_DAYS) is not None
            or (quarterly and r.largest_move(*QUARTER_SPAN) is not None)
        ]
        if not recasts:
            return []
        views = _views(conn, cik, as_of, quarterly)
        versions = version_dates(conn, cik, "revenue", as_of)
    filed_at = _Filings(conn, cik).filed_at
    facts = {r.period: _getter(views, parse_period(r.period))("revenue") for r in answers}
    ratios = _revenue_ratios(answers)
    notes, seen = [], set()
    for recast in recasts:
        side = {k: side_of_recast(f, recast, versions, filed_at) for k, f in facts.items()}
        split = tuple(sorted(side.items()))
        if "before" not in side.values() or set(side.values()) == {"before"} or split in seen:
            continue
        move, move_on = recast.largest_move(*QUARTER_SPAN) if quarterly else None, "quarter"
        if move is None:
            move, move_on = recast.largest_move(ANNUAL_MIN_DAYS), "year"
        if move is None:
            continue
        seen.add(split)
        moved = [k for k, f in facts.items() if _moved_by(f, recast)]
        notes.append(_recast_note(recast, side, moved, ratios, move, move_on, quarterly))
    return notes


def _revenue_ratios(answers: list[ReportedPeriod]) -> list[str]:
    return sorted(
        {x.name for r in answers for x in r.ratios if any(u["line"] == "revenue" for u in x.uses)}
    )


def _moved_by(fact: Fact, recast: Recast) -> bool:
    return not fact.derived and any(
        (s, e) == (fact.period_start, fact.period_end) for s, e, _o, _n in recast.periods
    )


_YEAR_MOVE = " on a full year; it moved no tagged quarter"


def _recast_note(
    recast: Recast,
    side: dict[str, str],
    moved: list[str],
    ratios: list[str],
    move: float,
    move_on: str = "year",
    quarterly: bool = False,
) -> Coded:
    groups = {s: [k for k, v in side.items() if v == s] for s in ("before", "after", "mixed")}
    day = recast.filed_at.isoformat()
    verb = "keeps" if len(groups["before"]) == 1 else "keep"
    parts = [
        f"the {recast.form} filed {day} {'lowered' if move < 0 else 'raised'} revenue figures "
        f"already reported (by up to {abs(move):.1%}"
        f"{_YEAR_MOVE if quarterly and move_on == 'year' else ''})"
        f"{', including ' + _and(moved) if moved else ''}",
        f"{_and(groups['before'])} {verb} figures filed before it, with no later version in the "
        "filings' tagged data",
    ]
    if groups["after"]:
        parts.append(
            f"{_and(groups['after'])} {'is' if len(groups['after']) == 1 else 'are'} "
            "as filed in it or later"
        )
    if groups["mixed"]:
        verb = "is" if len(groups["mixed"]) == 1 else "are"
        parts.append(f"{_and(groups['mixed'])} {verb} worked out from figures on both sides")
    on = f", and the ratios on it ({', '.join(ratios)})," if ratios else ""
    text = (
        f"revenue in this series is not all on one footing: {'; '.join(parts)}. Across that "
        f"break revenue{on} may not be like for like. Warren does not know why the figures "
        f"changed (for example a business separated, sold or brought back, a new accounting "
        f"rule, a change in presentation, or a correction); the {recast.form} explains it."
    )
    return Coded(
        "series_mixes_vintages",
        {
            "item": recast.canonical_name,
            "recast_on": day,
            "form": recast.form,
            "accession_no": recast.accession_no,
            "largest_move": move,
            "largest_move_on": move_on,
            "moved_periods": moved,
            "before_periods": groups["before"],
            "after_periods": groups["after"],
            "mixed_periods": groups["mixed"],
            "ratios": ratios,
        },
        text,
    )


def _and(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
