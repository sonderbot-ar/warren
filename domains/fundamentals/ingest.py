"""Ingestion: flatten EDGAR company facts into financial_facts, keeping every filing's version.

Fiscal labels come from the company's own filing calendar, not from the JSON's fy/fp, because
those describe the *filing*: a prior-year comparative in the FY2024 10-K carries fy=2024.
"""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from domains.fundamentals.concepts import (
    ConceptRow,
    concept_map_sha256,
    load_concept_map,
    sync_concepts,
)
from domains.fundamentals.edgar_client import (
    EdgarClient,
    EdgarError,
    is_financial_sic,
    parse_company,
)

FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
FP_TO_QUARTER = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}

# Duration lengths in days (end - start) for 52/53-week and calendar fiscal years.
MONTHS_BY_DAYS = [
    (range(84, 99), 3),
    (range(175, 191), 6),
    (range(266, 283), 9),
    (range(357, 379), 12),
]
# Which YTD label a duration gets, keyed by (months, quarter its end falls in).
DURATION_LABELS = {(6, 2): "H1", (9, 3): "M9", (12, 4): "FY"}

SAME_END_TOLERANCE_DAYS = 7  # 52/53-week years move period ends by a few days
YEAR_DRIFT_TOLERANCE_DAYS = 10  # when placing a period a whole number of years before/after


@dataclass(frozen=True)
class CalendarEntry:
    end: date
    fiscal_year: int
    quarter: int  # 1-4; 4 is the fiscal year end


@dataclass
class IngestResult:
    ticker: str
    cik: str
    facts_seen: int = 0
    facts_kept: int = 0
    facts_new: int = 0
    calendar_entries: int = 0
    unlabelled: int = 0  # stored, but no fiscal period could be assigned
    renumbered: int = 0  # filing periods whose fiscal year was renumbered (backlog #306)
    skipped: Counter = field(default_factory=Counter)


# -- filing calendar -------------------------------------------------------------------------


def _iter_facts(facts_json: dict[str, Any]):
    """Yield (taxonomy, tag, unit, fact) for every fact in a companyfacts document."""
    for taxonomy, concepts in facts_json.get("facts", {}).items():
        for tag, concept in concepts.items():
            for unit, rows in concept.get("units", {}).items():
                for row in rows:
                    yield taxonomy, tag, unit, row


def build_filing_calendar(facts_json: dict[str, Any]) -> list[CalendarEntry]:
    """Label each 10-K/10-Q's own period end with the filing's fy/fp.

    A filing's own period is the end date most of its facts share (comparatives are a minority).
    When filings disagree about an end date, the majority label wins. A company that changed
    how it numbers its fiscal years is renumbered to its newer numbering (backlog #306).
    """
    return _continuous_year_numbers(_raw_calendar(facts_json))


def _raw_calendar(facts_json: dict[str, Any]) -> list[CalendarEntry]:
    """The calendar exactly as the filings number it."""
    votes: dict[date, Counter] = defaultdict(Counter)
    for primary_end, fy, fp in _primary_periods(facts_json).values():
        votes[primary_end][(fy, FP_TO_QUARTER[fp])] += 1

    entries = []
    for end, counter in sorted(votes.items()):
        (fy, quarter), _ = counter.most_common(1)[0]
        entries.append(CalendarEntry(end=end, fiscal_year=fy, quarter=quarter))
    return entries


def _one_year_apart(older: CalendarEntry, newer: CalendarEntry) -> bool:
    return abs((newer.end - older.end).days - 365.25) <= YEAR_DRIFT_TOLERANCE_DAYS


def _continuous_year_numbers(entries: list[CalendarEntry]) -> list[CalendarEntry]:
    """Renumber older fiscal years when a company changed how it numbers them.

    Two fiscal year ends one year apart must carry consecutive fiscal years. When they don't
    (Walmart's filings named the year ending January 2014 fy=2013 and the next one fy=2015,
    because it switched from the year a fiscal year starts in to the year it ends in), the
    newer filings' numbering wins and every entry up to the older year end is shifted to meet
    it. The shift chains through newer shifts and can be up or down by any number of years.

    - The newer numbering must hold for at least two consecutive year ends (the newer year end
      and the one after it, one year apart and consecutive once renumbered); otherwise the
      break is left as filed, so one wrong `fy` in the newest 10-K cannot renumber a whole
      history. A wrong `fy` in an older 10-K is renumbered to fit its neighbours, and the
      years before it are compared with that corrected number, so they keep theirs.
    - Across year ends further apart (a gap in the calendar, or a change of year end) the
      shift carries on unchanged, since nothing there says the numbering changed.
    - An entry takes the shift of the first year end on or after its own end (within
      SAME_END_TOLERANCE_DAYS); entries after the newest year end never move.
    - Only quarter-4 entries (a filing's own fiscal year end) define year ends.

    Only labels move; no value or date changes.
    """
    year_ends = [e for e in entries if e.quarter == 4]
    shifts: dict[date, int] = {}  # year end -> how many years its fiscal year moves
    shift = 0
    for i in range(len(year_ends) - 2, -1, -1):
        older, newer = year_ends[i], year_ends[i + 1]
        after = year_ends[i + 2] if i + 2 < len(year_ends) else None
        newer_number = newer.fiscal_year + shifts.get(newer.end, 0)
        newer_holds = (
            after is not None
            and _one_year_apart(newer, after)
            and after.fiscal_year + shifts.get(after.end, 0) == newer_number + 1
        )
        if _one_year_apart(older, newer) and newer_holds:
            shift = newer_number - 1 - older.fiscal_year
        shifts[older.end] = shift
    if not any(shifts.values()):
        return entries

    def shift_for(end: date) -> int:
        for year_end in year_ends:
            if year_end.end >= end - timedelta(days=SAME_END_TOLERANCE_DAYS):
                return shifts.get(year_end.end, 0)
        return 0

    return [
        CalendarEntry(end=e.end, fiscal_year=e.fiscal_year + shift_for(e.end), quarter=e.quarter)
        for e in entries
    ]


def renumbered_entries(facts_json: dict[str, Any]) -> int:
    """How many filing-calendar entries `_continuous_year_numbers` renumbered (0 for most)."""
    raw = _raw_calendar(facts_json)
    return sum(a != b for a, b in zip(raw, _continuous_year_numbers(raw), strict=True))


def filing_periods(
    facts_json: dict[str, Any], calendar: list[CalendarEntry]
) -> dict[str, tuple[int, int]]:
    """accession -> (fiscal_year, quarter) of the filing's own period, placed in the calendar."""
    placed = {
        accn: place_period_end(calendar, primary_end)
        for accn, (primary_end, _fy, _fp) in _primary_periods(facts_json).items()
    }
    return {accn: p for accn, p in placed.items() if p is not None}


# How many months a filing's own period can span, by form: a 10-K's year, a 10-Q's quarter or
# its year to date (backlog #310). Lengths in days come from MONTHS_BY_DAYS, as for labels.
OWN_PERIOD_MONTHS = {"10-K": {12}, "10-Q": {3, 6, 9}}


def _own_length(form: str, start: str | None, end: str) -> bool:
    """True when a duration fact has the length of its filing's own period."""
    if start is None:
        return False
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    months = next((m for span, m in MONTHS_BY_DAYS if days in span), None)
    return months in OWN_PERIOD_MONTHS[form.removesuffix("/A")]


def _primary_periods(facts_json: dict[str, Any]) -> dict[str, tuple[date, int, str]]:
    """accession -> (its own period end, the filing's fy, the filing's fp).

    A filing's own period is the latest end among its duration facts of the form's length (a
    year for a 10-K; a quarter, half or nine months for a 10-Q) that end by its filing date:
    comparatives always end earlier. Counting which end most facts share instead put three
    10-Ks a year or two early, because their comparatives outnumbered their own year (Apple's
    fiscal 2009 10-K and its amendment, Caterpillar's 2009 10-K; backlog #310). A filing with
    no such duration falls back to that majority end.
    """
    ends_by_accession: dict[str, Counter] = defaultdict(Counter)
    own_ends: dict[str, set[str]] = defaultdict(set)
    label_by_accession: dict[str, tuple[int, str]] = {}
    for taxonomy, _tag, _unit, row in _iter_facts(facts_json):
        if taxonomy != "us-gaap" or row.get("form") not in FORMS:
            continue
        if not row.get("fy") or row.get("fp") not in FP_TO_QUARTER:
            continue
        ends_by_accession[row["accn"]][row["end"]] += 1
        label_by_accession.setdefault(row["accn"], (row["fy"], row["fp"]))
        if row["end"] <= row["filed"] and _own_length(row["form"], row.get("start"), row["end"]):
            own_ends[row["accn"]].add(row["end"])

    periods = {}
    for accn, ends in ends_by_accession.items():
        if own_ends[accn]:
            primary_end = max(own_ends[accn])
        else:
            top = max(ends.values())
            primary_end = max(end for end, n in ends.items() if n == top)
        periods[accn] = (date.fromisoformat(primary_end), *label_by_accession[accn])
    return periods


def place_period_end(calendar: list[CalendarEntry], end: date) -> tuple[int, int] | None:
    """(fiscal_year, quarter) for a period end, or None if it can't be placed.

    An end within a few days of a calendar entry takes its label. Otherwise it is placed a whole
    number of years before or after the closest entry with a matching day of year.
    """
    best = None
    for entry in calendar:
        delta = (entry.end - end).days
        if abs(delta) <= SAME_END_TOLERANCE_DAYS:
            return entry.fiscal_year, entry.quarter
        years = round(delta / 365.25)
        drift = abs(delta - years * 365.25)
        if years != 0 and drift <= YEAR_DRIFT_TOLERANCE_DAYS:
            if best is None or (drift, abs(years)) < best[0]:
                best = ((drift, abs(years)), (entry.fiscal_year - years, entry.quarter))
    return best[1] if best else None


def label_fact(
    calendar: list[CalendarEntry], start: str | None, end: str
) -> tuple[int | None, str | None, str | None]:
    """(fiscal_year, fiscal_period, skip_reason). skip_reason is set when the fact isn't stored."""
    placed = place_period_end(calendar, date.fromisoformat(end))
    if start is None:
        if placed is None:
            return None, None, None
        fy, quarter = placed
        return fy, ("FY" if quarter == 4 else f"Q{quarter}"), None

    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    months = next((m for span, m in MONTHS_BY_DAYS if days in span), None)
    if months is None:
        return None, None, "odd_duration"
    if placed is None:
        return None, None, None
    fy, quarter = placed
    if months == 3:
        return fy, f"Q{quarter}", None
    label = DURATION_LABELS.get((months, quarter))
    if label is None:
        return None, None, "non_ytd_duration"  # e.g. trailing twelve months ending in Q2
    return fy, label, None


def label_cover_fact(
    filing_period: tuple[int, int] | None,
) -> tuple[int | None, str | None, str | None]:
    """Label a cover-page fact with its filing's own (fiscal_year, quarter)."""
    if filing_period is None:
        return None, None, None
    fy, quarter = filing_period
    return fy, ("FY" if quarter == 4 else f"Q{quarter}"), None


# -- ingestion -------------------------------------------------------------------------------

UPSERT_COMPANY = """
INSERT INTO companies (cik, ticker, name, sic, fiscal_year_end, aliases_json)
VALUES (:cik, :ticker, :name, :sic, :fiscal_year_end, :aliases_json)
ON CONFLICT (cik) DO UPDATE SET
    ticker = excluded.ticker, name = excluded.name, sic = excluded.sic,
    fiscal_year_end = excluded.fiscal_year_end, aliases_json = excluded.aliases_json,
    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
"""

# Stored values never change on re-ingest; only labels can (if the filing calendar improved).
UPSERT_FACT = """
INSERT INTO financial_facts
    (cik, xbrl_concept, period_start, period_end, fiscal_year, fiscal_period,
     value, unit, form, accession_no, filed_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (cik, xbrl_concept, unit, COALESCE(period_start, ''), period_end, accession_no)
DO UPDATE SET fiscal_year = excluded.fiscal_year, fiscal_period = excluded.fiscal_period
"""


INSERT_RUN = """
INSERT INTO ingest_runs (cik, companyfacts_sha256, companyfacts_fetched_at, concept_map_sha256,
                         facts_kept, facts_new)
VALUES (?, ?, ?, ?, ?, ?)
"""


def extract_facts(
    cik: str, facts_json: dict[str, Any], concepts: list[ConceptRow], result: IngestResult
) -> list[tuple]:
    """Rows for financial_facts: mapped concepts only, every filing's version, labelled."""
    by_tag = {(c.taxonomy, c.tag): c for c in concepts}
    calendar = build_filing_calendar(facts_json)
    own_period = filing_periods(facts_json, calendar)
    result.calendar_entries = len(calendar)
    result.renumbered = renumbered_entries(facts_json)

    rows: dict[tuple, tuple] = {}
    for taxonomy, tag, unit, fact in _iter_facts(facts_json):
        concept = by_tag.get((taxonomy, tag))
        if concept is None:
            continue
        result.facts_seen += 1
        if fact.get("form") not in FORMS:
            result.skipped["form"] += 1
            continue
        if unit != concept.unit:
            result.skipped["unit"] += 1
            continue
        if fact["end"] > fact["filed"]:
            result.skipped["future_period"] += 1  # a period can't end after its filing: data error
            continue
        start = fact.get("start")
        if (start is None) != (concept.period_type == "instant"):
            result.skipped["period_type"] += 1
            continue
        if taxonomy == "dei":
            # cover-page facts are dated near the filing date, not at a period end: they take the
            # fiscal period of the filing they appear in
            fy, fp, reason = label_cover_fact(own_period.get(fact["accn"]))
        else:
            fy, fp, reason = label_fact(calendar, start, fact["end"])
        if reason:
            result.skipped[reason] += 1
            continue
        if fy is None:
            result.unlabelled += 1  # still stored, e.g. a mid-quarter date
        key = (concept.xbrl_concept, unit, start or "", fact["end"], fact["accn"])
        row = (
            cik, concept.xbrl_concept, start, fact["end"], fy, fp,
            float(fact["val"]), unit, fact["form"], fact["accn"], fact["filed"],
        )  # fmt: skip
        if key in rows and rows[key][6] != row[6]:
            result.skipped["conflicting_duplicate"] += 1  # same filing, two values: keep the first
            continue
        rows.setdefault(key, row)
    return list(rows.values())


def ingest_company(
    conn: sqlite3.Connection,
    ticker: str,
    client: EdgarClient | None = None,
    cik: str | None = None,
    refresh: bool = False,
    allow_financial: bool = False,
) -> IngestResult:
    """Load one company's facts. Re-running adds nothing new unless EDGAR has new filings."""
    client = client or EdgarClient()
    cik = cik or client.lookup_cik(ticker, refresh=refresh)
    company = parse_company(client.get_submissions(cik, refresh=refresh), ticker)
    if is_financial_sic(company["sic"]) and not allow_financial:
        raise EdgarError(
            f"{ticker} has SIC {company['sic']} (finance, insurance or real estate), which is "
            "outside the Phase 1 universe."
        )
    facts_json = client.get_company_facts(cik, refresh=refresh)

    concepts = load_concept_map()
    sync_concepts(conn, concepts)
    result = IngestResult(ticker=company["ticker"], cik=company["cik"])
    rows = extract_facts(company["cik"], facts_json, concepts, result)
    result.facts_kept = len(rows)

    with conn:
        conn.execute(UPSERT_COMPANY, {**company, "aliases_json": json.dumps(company["aliases"])})
        before = conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0]
        conn.executemany(UPSERT_FACT, rows)
        after = conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0]
        result.facts_new = after - before
        conn.execute(
            INSERT_RUN,
            (
                company["cik"],
                content_sha256(facts_json),
                client.company_facts_fetched_at(cik),
                concept_map_sha256(),
                result.facts_kept,
                result.facts_new,
            ),
        )
    return result


def content_sha256(document: dict[str, Any]) -> str:
    """Fingerprint of a JSON document's content, independent of key order and whitespace."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
