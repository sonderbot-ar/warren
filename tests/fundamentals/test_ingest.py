from datetime import date

import pytest

from domains.fundamentals.edgar_client import EdgarError
from domains.fundamentals.ingest import (
    CalendarEntry,
    _continuous_year_numbers,
    build_filing_calendar,
    content_sha256,
    ingest_company,
    label_fact,
    renumbered_entries,
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


def with_cover_shares(edgar):
    """Add cover-page shares outstanding to the Q1 2024 10-Q and the FY2024 10-K (and a 10-K/A)."""

    def cover(val, end, accn, form, filed, fy, fp):
        return {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form,
                "filed": filed}  # fmt: skip

    edgar.facts["facts"]["dei"] = {
        "EntityCommonStockSharesOutstanding": {
            "units": {
                "shares": [
                    cover(
                        1000, "2024-04-20", "0000000123-24-000010", "10-Q", "2024-05-01", 2024, "Q1"
                    ),
                    cover(
                        990, "2025-02-01", "0000000123-25-000001", "10-K", "2025-02-15", 2024, "FY"
                    ),
                    cover(
                        985,
                        "2025-03-10",
                        "0000000123-25-000077",
                        "10-K/A",
                        "2025-03-20",
                        2024,
                        "FY",
                    ),
                ]
            }
        }
    }
    return edgar


def test_cover_page_shares_take_their_filings_fiscal_period(conn):
    ingest_company(conn, "TST", client=with_cover_shares(FakeEdgar()))
    rows = conn.execute(
        "SELECT period_end, fiscal_year, fiscal_period FROM financial_facts "
        "WHERE xbrl_concept = 'dei:EntityCommonStockSharesOutstanding' ORDER BY period_end"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("2024-04-20", 2024, "Q1"),  # a date between quarter ends, labelled by its filing
        ("2025-02-01", 2024, "FY"),
        ("2025-03-10", None, None),  # the 10-K/A has no other facts, so its period is unknown
    ]


def test_mid_quarter_balance_is_stored_without_a_label(conn):
    edgar = FakeEdgar()
    cash = edgar.facts["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"]
    cash.append(dict(cash[-1], end="2025-05-15", val=1))  # filed 2026-02-15
    result = ingest_company(conn, "TST", client=edgar)
    assert result.unlabelled == 1
    row = conn.execute("SELECT fiscal_year FROM financial_facts WHERE period_end = '2025-05-15'")
    assert row.fetchone()[0] is None


# -- a company that changed how it numbers its fiscal years (backlog #306) ---------------------


def _walmart_like_calendar():
    """Year ends in January; filings up to January 2014 numbered a year by the year it started
    in, later ones by the year it ends in (Walmart: fy=2013, then fy=2015)."""
    return [
        CalendarEntry(date(2013, 1, 31), 2012, 4),
        CalendarEntry(date(2013, 4, 30), 2013, 1),
        CalendarEntry(date(2013, 10, 31), 2013, 3),
        CalendarEntry(date(2014, 1, 31), 2013, 4),
        CalendarEntry(date(2014, 4, 30), 2015, 1),
        CalendarEntry(date(2015, 1, 31), 2015, 4),
        CalendarEntry(date(2015, 4, 30), 2016, 1),
        CalendarEntry(date(2016, 1, 31), 2016, 4),
    ]


def test_older_years_take_the_newer_numbering_when_a_company_changes_it():
    fixed = _continuous_year_numbers(_walmart_like_calendar())
    assert [(e.end.isoformat(), e.fiscal_year, e.quarter) for e in fixed] == [
        ("2013-01-31", 2013, 4),
        ("2013-04-30", 2014, 1),
        ("2013-10-31", 2014, 3),
        ("2014-01-31", 2014, 4),
        ("2014-04-30", 2015, 1),
        ("2015-01-31", 2015, 4),
        ("2015-04-30", 2016, 1),
        ("2016-01-31", 2016, 4),
    ]
    # A comparative year and quarter in a later filing take the same label.
    assert label_fact(fixed, "2013-02-01", "2014-01-31") == (2014, "FY", None)
    assert label_fact(fixed, "2013-11-01", "2014-01-31") == (2014, "Q4", None)
    assert label_fact(fixed, "2012-02-01", "2012-04-30") == (2013, "Q1", None)


def test_consecutive_numbering_is_left_alone():
    calendar = build_filing_calendar(FakeEdgar().facts)
    assert _continuous_year_numbers(calendar) == calendar


def test_year_ends_more_than_a_year_apart_keep_their_gap():
    # A two-year hole: nothing says the numbering changed, so the labels stay as filed.
    calendar = [
        CalendarEntry(date(2008, 9, 27), 2008, 4),
        CalendarEntry(date(2010, 9, 25), 2010, 4),
        CalendarEntry(date(2011, 9, 24), 2011, 4),
    ]
    assert _continuous_year_numbers(calendar) == calendar


def test_a_shift_carries_across_a_gap_older_than_the_change():
    calendar = [
        CalendarEntry(date(2010, 1, 31), 2009, 4),
        CalendarEntry(date(2012, 1, 31), 2011, 4),  # two years later, same old numbering
        CalendarEntry(date(2013, 1, 31), 2013, 4),  # the change
        CalendarEntry(date(2014, 1, 31), 2014, 4),
    ]
    assert [e.fiscal_year for e in _continuous_year_numbers(calendar)] == [
        2010,
        2012,
        2013,
        2014,
    ]


def test_one_wrong_year_in_the_newest_filing_does_not_renumber_the_history():
    calendar = [
        CalendarEntry(date(2021, 12, 31), 2021, 4),
        CalendarEntry(date(2022, 12, 31), 2022, 4),
        CalendarEntry(date(2023, 12, 31), 2025, 4),  # a typo, held by no later year
    ]
    assert _continuous_year_numbers(calendar) == calendar


def test_a_numbering_that_moves_down_shifts_older_years_down():
    calendar = [
        CalendarEntry(date(2012, 12, 31), 2013, 4),
        CalendarEntry(date(2013, 12, 31), 2014, 4),
        CalendarEntry(date(2014, 12, 31), 2014, 4),
        CalendarEntry(date(2015, 12, 31), 2015, 4),
    ]
    assert [e.fiscal_year for e in _continuous_year_numbers(calendar)] == [
        2012,
        2013,
        2014,
        2015,
    ]


def test_filing_calendar_renumbers_a_changed_numbering_from_the_filings_own_fy():
    def filing(accn, end, fy, fp, start):
        return {
            "accn": accn,
            "end": end,
            "start": start,
            "fy": fy,
            "fp": fp,
            "form": "10-K",
            "filed": f"{int(end[:4])}-03-25",
            "val": 1,
        }

    rows = [
        filing("a1", "2013-01-31", 2012, "FY", "2012-02-01"),
        filing("a2", "2014-01-31", 2013, "FY", "2013-02-01"),
        filing("a3", "2015-01-31", 2015, "FY", "2014-02-01"),
        filing("a4", "2016-01-31", 2016, "FY", "2015-02-01"),
    ]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    assert [(e.end.year, e.fiscal_year) for e in build_filing_calendar(facts)] == [
        (2013, 2013),
        (2014, 2014),
        (2015, 2015),
        (2016, 2016),
    ]
    assert renumbered_entries(facts) == 2
    assert renumbered_entries(FakeEdgar().facts) == 0
