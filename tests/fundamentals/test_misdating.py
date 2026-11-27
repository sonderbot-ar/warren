"""Figures a 10-K may have filed under the wrong fiscal year (backlog #613 item 1).

Test Corp's ingested fixture has no figure of this shape. Each test adds annual facts by hand in
the shape of Coca-Cola's FY2016 10-K: a loss of 320 on paying debt off early, filed for 2015 in
the FY2015 10-K, and the same 320 filed for 2016 in the FY2016 10-K, which gives 2015 none.
"""

from datetime import date

import pytest

from domains.fundamentals import quality
from domains.fundamentals.misdating import misdating_candidates
from domains.fundamentals.quality import build_report
from tests.fundamentals.conftest import TEST_CIK

TAG = "us-gaap:GainsLossesOnExtinguishmentOfDebt"
FY2015_10K = ("0000000123-16-000001", "2016-02-25")
FY2016_10K = ("0000000123-17-000001", "2017-02-24")
FY2017_10K = ("0000000123-18-000001", "2018-02-23")
LATE = date(2026, 1, 1)


def add(conn, year, value, filing, tag=TAG, period="FY", unit="USD"):
    accession, filed_at = filing
    start, end = (
        (f"{year}-01-01", f"{year}-12-31")
        if period == "FY"
        else (
            f"{year}-01-01",
            f"{year}-03-31",
        )
    )
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '10-K', ?, ?)",
        (TEST_CIK, tag, start, end, year, period, value, unit, accession, filed_at),
    )


def found(conn, as_of=LATE):
    return [
        (c.canonical_name, c.fiscal_year, c.value, c.accession_no)
        for c in misdating_candidates(conn, TEST_CIK, as_of)
    ]


@pytest.fixture
def ko_shape(ingested):
    conn, _ = ingested
    add(conn, 2015, -320, FY2015_10K)
    add(conn, 2016, -320, FY2016_10K)
    return conn


def test_the_fixture_alone_has_no_candidate(ingested):
    conn, _ = ingested
    assert found(conn) == []


def test_the_coca_cola_shape_is_found(ko_shape):
    [c] = misdating_candidates(ko_shape, TEST_CIK, LATE)
    assert (c.ticker, c.canonical_name, c.xbrl_concept) == (
        "TST",
        "debt_extinguishment_in_interest",
        TAG,
    )
    assert (c.fiscal_year, c.value, c.stated_fiscal_year) == (2016, -320, 2015)
    assert (c.accession_no, c.filed_at, c.form) == (*FY2016_10K, "10-K")
    assert (c.prior_accession_no, c.prior_filed_at) == FY2015_10K


def test_not_found_when_the_filing_also_gives_the_year_before_the_same_figure(ko_shape):
    add(ko_shape, 2015, -320, FY2016_10K)  # the FY2016 10-K states both years: a true repeat
    assert found(ko_shape) == []


def test_found_when_the_filing_gives_the_year_before_another_figure(ko_shape):
    add(ko_shape, 2015, -300, FY2016_10K)
    assert len(found(ko_shape)) == 1


def test_not_found_when_another_filing_gives_the_year_the_same_figure(ko_shape):
    add(ko_shape, 2017, -10, FY2017_10K)  # the FY2017 10-K, on its own year
    add(ko_shape, 2016, -320, FY2017_10K)  # corroborated by a later 10-K
    assert found(ko_shape) == []
    assert len(found(ko_shape, as_of=date(2017, 3, 1))) == 1  # before that 10-K was public


def test_found_when_another_filing_gives_the_year_a_different_figure(ko_shape):
    add(ko_shape, 2016, 0, FY2017_10K)
    assert len(found(ko_shape)) == 1


def test_the_earlier_figure_must_be_filed_before(ingested):
    conn, _ = ingested
    add(conn, 2016, -320, FY2017_10K)
    add(conn, 2015, -320, ("0000000123-19-000001", "2019-02-21"))  # the year before, filed after
    assert found(conn) == []


def test_the_earlier_figure_must_be_in_another_filing(ingested):
    conn, _ = ingested
    add(conn, 2015, -320, FY2016_10K)
    add(conn, 2016, -320, FY2016_10K)
    assert found(conn) == []


def test_a_zero_is_never_a_candidate(ingested):
    conn, _ = ingested
    add(conn, 2015, 0, FY2015_10K)
    add(conn, 2016, 0, FY2016_10K)
    assert found(conn) == []


@pytest.mark.parametrize("value", [-321, -319.9999, 320])
def test_figures_must_be_exactly_equal(ingested, value):
    conn, _ = ingested
    add(conn, 2015, -320, FY2015_10K)
    add(conn, 2016, value, FY2016_10K)
    assert found(conn) == []


def test_point_in_time(ko_shape):
    assert found(ko_shape, as_of=date(2017, 2, 23)) == []  # the FY2016 10-K is not public yet
    assert len(found(ko_shape, as_of=date(2017, 2, 24))) == 1  # public on its filing day


def test_another_tag_of_the_same_item_is_not_compared(ingested):
    conn, _ = ingested
    add(conn, 2015, 50, FY2015_10K, tag="us-gaap:InterestExpense")
    add(conn, 2016, 50, FY2016_10K, tag="us-gaap:InterestExpenseNonoperating")
    assert found(conn) == []
    add(conn, 2016, 50, FY2017_10K, tag="us-gaap:InterestExpense")
    # on its own tag the FY2017 10-K gives 2016 the figure 2015 had, so it is found there
    assert found(conn) == [("interest_expense", 2016, 50, FY2017_10K[0])]


def test_quarters_are_not_scanned(ingested):
    conn, _ = ingested
    add(conn, 2015, -320, FY2015_10K, period="Q1")
    add(conn, 2016, -320, FY2016_10K, period="Q1")
    assert found(conn) == []


def test_one_candidate_per_filing_and_sorted(ko_shape):
    add(ko_shape, 2018, 27, ("0000000123-19-000001", "2019-02-21"))
    add(ko_shape, 2019, 27, ("0000000123-21-000001", "2021-02-25"))
    assert [c[1] for c in found(ko_shape)] == [2016, 2019]


def test_the_quality_report_lists_candidates(ko_shape, monkeypatch):
    monkeypatch.setattr(quality, "FISCAL_YEARS", range(2023, 2025))
    report = build_report(ko_shape, "TST", as_of=LATE, known_gaps=[])
    markdown = report.to_markdown()
    assert "- Possible misdated figures: 1 (informational; see below)" in markdown
    section = markdown[markdown.index("## Possible misdated figures") :]
    assert "**debt_extinguishment_in_interest** FY2016: -0M" in section
    assert FY2016_10K[0] in section and FY2015_10K[0] in section
    assert "does its text put the figure in 2015?" in section
    assert "https://www.sec.gov/Archives/edgar/data/123/000000012317000001/" in section


def test_the_quality_report_says_none(ingested, monkeypatch):
    conn, _ = ingested
    monkeypatch.setattr(quality, "FISCAL_YEARS", range(2023, 2025))
    markdown = build_report(conn, "TST", as_of=LATE, known_gaps=[]).to_markdown()
    assert "- Possible misdated figures: 0" in markdown
    section = markdown[markdown.index("## Possible misdated figures") :]
    assert section.rstrip().endswith("None.")


def test_candidates_do_not_change_the_report_exit_code(ko_shape, monkeypatch):
    monkeypatch.setattr(quality, "FISCAL_YEARS", range(2023, 2025))
    with_candidate = build_report(ko_shape, "TST", as_of=LATE, known_gaps=[])
    assert with_candidate.misdating
    assert "misdat" not in " ".join(g.reason or "" for g in with_candidate.gaps)
    without = build_report(ko_shape, "TST", as_of=date(2016, 3, 1), known_gaps=[])
    assert not without.misdating
    assert len(with_candidate.unexplained) == len(
        build_report(ko_shape, "TST", as_of=LATE, known_gaps=[]).unexplained
    )


def test_an_amendment_of_the_same_report_does_not_corroborate(ko_shape):
    # a 10-K/A filed the next day re-files the FY2016 10-K: a copy, not a second source
    amendment = ("0000000123-17-000002", "2017-02-25")
    add(ko_shape, 2016, -320, amendment)
    assert [c[3] for c in found(ko_shape)] == [FY2016_10K[0], amendment[0]]


def test_a_fact_with_no_fiscal_year_is_skipped(ko_shape):
    ko_shape.execute(
        "UPDATE financial_facts SET fiscal_year = NULL WHERE accession_no = ?", (FY2016_10K[0],)
    )
    assert found(ko_shape) == []
