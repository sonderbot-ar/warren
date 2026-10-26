"""Ingestion: flatten EDGAR company facts into financial_facts, keeping every filing's version.

Fiscal labels come from the company's own filing calendar, not from the JSON's fy/fp, because
those describe the *filing*: a prior-year comparative in the FY2024 10-K carries fy=2024.
"""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
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
    When filings disagree about an end date, the majority label wins.
    """
    ends_by_accession: dict[str, Counter] = defaultdict(Counter)
    label_by_accession: dict[str, tuple[int, str]] = {}
    for taxonomy, _tag, _unit, row in _iter_facts(facts_json):
        if taxonomy != "us-gaap" or row.get("form") not in FORMS:
            continue
        if not row.get("fy") or row.get("fp") not in FP_TO_QUARTER:
            continue
        ends_by_accession[row["accn"]][row["end"]] += 1
        label_by_accession.setdefault(row["accn"], (row["fy"], row["fp"]))

    votes: dict[date, Counter] = defaultdict(Counter)
    for accn, ends in ends_by_accession.items():
        top = max(ends.values())
        primary_end = max(end for end, n in ends.items() if n == top)
        fy, fp = label_by_accession[accn]
        votes[date.fromisoformat(primary_end)][(fy, FP_TO_QUARTER[fp])] += 1

    entries = []
    for end, counter in sorted(votes.items()):
        (fy, quarter), _ = counter.most_common(1)[0]
        entries.append(CalendarEntry(end=end, fiscal_year=fy, quarter=quarter))
    return entries


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
    result.calendar_entries = len(calendar)

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
