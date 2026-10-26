from datetime import date

import pytest

from domains.fundamentals.edgar_client import EdgarError
from domains.fundamentals.ingest import (
    CalendarEntry,
    build_filing_calendar,
    content_sha256,
    ingest_company,
    label_fact,
)
from tests.fundamentals.conftest import TEST_CIK, FakeEdgar


def facts_for(conn, tag, end, start=None):
    return conn.execute(
        "SELECT value, fiscal_year, fiscal_period, accession_no FROM financial_facts "
        "WHERE xbrl_concept = ? AND period_end = ? AND COALESCE(period_start, '') = ? "
        "ORDER BY filed_at",
        (f"us-gaap:{tag}", end, start or ""),
    ).fetchall()


def test_filing_calendar_labels_each_filing_period():
    calendar = build_filing_calendar(FakeEdgar().facts)
    assert [(e.end.isoformat(), e.fiscal_year, e.quarter) for e in calendar] == [
        ("2023-12-31", 2023, 4),
        ("2024-03-31", 2024, 1),
        ("2024-06-30", 2024, 2),
        ("2024-09-30", 2024, 3),
        ("2024-12-31", 2024, 4),
        ("2025-12-31", 2025, 4),
    ]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2024-01-01", "2024-03-31", (2024, "Q1", None)),
        ("2024-01-01", "2024-06-30", (2024, "H1", None)),
        ("2024-01-01", "2024-09-30", (2024, "M9", None)),
        ("2024-01-01", "2024-12-31", (2024, "FY", None)),
        (None, "2024-06-30", (2024, "Q2", None)),
        (None, "2024-12-31", (2024, "FY", None)),
        ("2023-01-01", "2023-03-31", (2023, "Q1", None)),  # placed one year before 2024 Q1
        ("2025-11-01", "2025-12-31", (None, None, "odd_duration")),
        ("2023-07-01", "2024-06-30", (None, None, "non_ytd_duration")),  # trailing 12 months
    ],
)
def test_label_fact(start, end, expected):
    calendar = build_filing_calendar(FakeEdgar().facts)
    assert label_fact(calendar, start, end) == expected


def test_52_53_week_ends_within_tolerance_share_a_label():
    calendar = [CalendarEntry(end=date(2025, 9, 27), fiscal_year=2025, quarter=4)]
    assert label_fact(calendar, None, "2025-09-29") == (2025, "FY", None)
    assert label_fact(calendar, "2023-10-01", "2024-09-28") == (2024, "FY", None)


def test_comparative_gets_its_own_fiscal_year_not_the_filings(ingested):
    conn, _ = ingested
    # the FY2024 10-K reports FY2023 revenue with fy=2024 in the JSON
    rows = facts_for(conn, "Revenues", "2023-12-31", "2023-01-01")
    assert [(r["fiscal_year"], r["fiscal_period"]) for r in rows] == [(2023, "FY")]


def test_every_filing_version_is_kept(ingested):
    conn, _ = ingested
    rows = facts_for(conn, "Revenues", "2024-12-31", "2024-01-01")
    assert [r["value"] for r in rows] == [460.0, 455.0]  # original, then restated


def test_unmapped_tags_8k_facts_and_odd_durations_are_skipped(ingested):
    conn, result = ingested
    tags = {r[0] for r in conn.execute("SELECT DISTINCT xbrl_concept FROM financial_facts")}
    assert "us-gaap:SomethingElse" not in tags
    forms = {r[0] for r in conn.execute("SELECT DISTINCT form FROM financial_facts")}
    assert "8-K" not in forms
    assert result.skipped["form"] == 1
    assert result.skipped["odd_duration"] == 1


def test_reingest_adds_nothing(ingested):
    conn, first = ingested
    second = ingest_company(conn, "TST", client=FakeEdgar())
    assert first.facts_new == first.facts_kept > 0
    assert second.facts_new == 0
    assert second.facts_kept == first.facts_kept


def test_company_row_and_aliases(ingested):
    conn, _ = ingested
    row = conn.execute("SELECT * FROM companies WHERE cik = ?", (TEST_CIK,)).fetchone()
    assert row["ticker"] == "TST"
    assert row["aliases_json"] == '["Test Corp", "Test Holdings"]'


def test_financial_company_is_rejected(conn):
    with pytest.raises(EdgarError, match="outside the Phase 1 universe"):
        ingest_company(conn, "BNK", client=FakeEdgar(sic="6021"))


def test_fact_ending_after_its_filing_date_is_rejected(conn):
    edgar = FakeEdgar()
    cash = edgar.facts["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"]
    bad = dict(cash[0], end="2025-06-30")  # filed 2024-02-15, so the period hasn't ended yet
    cash.append(bad)
    result = ingest_company(conn, "TST", client=edgar)
    assert result.skipped["future_period"] == 1
    assert not conn.execute("SELECT 1 FROM financial_facts WHERE period_end > filed_at").fetchone()


def test_each_ingest_records_what_data_and_concept_map_it_used(ingested):
    conn, first = ingested
    ingest_company(conn, "TST", client=FakeEdgar())
    runs = conn.execute("SELECT * FROM ingest_runs ORDER BY run_id").fetchall()
    assert len(runs) == 2
    assert runs[0]["companyfacts_sha256"] == runs[1]["companyfacts_sha256"]  # same content
    assert len(runs[0]["concept_map_sha256"]) == 64
    assert runs[0]["companyfacts_fetched_at"] == "2026-10-26T12:00:00Z"
    assert (runs[0]["facts_new"], runs[1]["facts_new"]) == (first.facts_new, 0)


def test_content_hash_ignores_key_order():
    assert content_sha256({"a": 1, "b": [1, 2]}) == content_sha256({"b": [1, 2], "a": 1})
    assert content_sha256({"a": 1}) != content_sha256({"a": 2})


def test_mid_quarter_balance_is_stored_without_a_label(conn):
    edgar = FakeEdgar()
    cash = edgar.facts["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"]
    cash.append(dict(cash[-1], end="2025-05-15", val=1))  # filed 2026-02-15
    result = ingest_company(conn, "TST", client=edgar)
    assert result.unlabelled == 1
    row = conn.execute("SELECT fiscal_year FROM financial_facts WHERE period_end = '2025-05-15'")
    assert row.fetchone()[0] is None
