from datetime import date

import pytest

from domains.fundamentals import quality
from domains.fundamentals.quality import KnownGap, build_report
from tests.fundamentals.conftest import TEST_CIK


@pytest.fixture
def two_years(monkeypatch):
    """Limit the report to the fixture's fiscal years."""
    monkeypatch.setattr(quality, "FISCAL_YEARS", range(2023, 2025))


def report_for(conn, known_gaps=()):
    return build_report(conn, "TST", as_of=date(2025, 3, 1), known_gaps=list(known_gaps))


def test_report_finds_a_planted_gap(ingested, two_years):
    conn, _ = ingested
    # capex FY2023 is reported; Q1-Q4 2023 are not (no 2023 10-Qs in the fixture)
    gaps = {(g.canonical_name, g.fiscal_year, g.period) for g in report_for(conn).unexplained}
    assert ("capex", 2023, "Q1") in gaps
    assert ("capex", 2023, "FY") not in gaps
    assert ("capex", 2024, "Q4") not in gaps  # derived, so not a gap


def test_known_gap_is_classed_as_explained(ingested, two_years):
    conn, _ = ingested
    known = [KnownGap("TST", "capex", "2023", "Q1;Q2;Q3;Q4", "No 2023 10-Qs in the fixture.")]
    report = report_for(conn, known)
    explained = {(g.canonical_name, g.fiscal_year, g.period) for g in report.explained}
    assert {("capex", 2023, p) for p in ("Q1", "Q2", "Q3", "Q4")} <= explained
    assert not any(g.canonical_name == "capex" for g in report.unexplained)


@pytest.mark.parametrize(
    ("gap", "args", "covered"),
    [
        (KnownGap("TST", "*", "*", "*", "r"), ("TST", "cash", 2019, "Q2"), True),
        (KnownGap("TST", "cash", "2016-2018", "*", "r"), ("TST", "cash", 2019, "Q2"), False),
        (KnownGap("TST", "cash", "2016-2019", "Q4", "r"), ("TST", "cash", 2019, "Q2"), False),
        (KnownGap("TST", "cash", "2016-2019", "Q2;Q4", "r"), ("TST", "cash", 2019, "Q2"), True),
        (KnownGap("XYZ", "cash", "*", "*", "r"), ("TST", "cash", 2019, "Q2"), False),
    ],
)
def test_known_gap_matching(gap, args, covered):
    assert gap.covers(*args) is covered


def test_markdown_shows_grid_tags_and_gap_lists(ingested, two_years):
    conn, _ = ingested
    text = report_for(conn).to_markdown()
    # 2023: Q1 (a comparative) and FY only; 2024: Q4 derived from FY - M9
    assert "| revenue | `R!!!R` | `RRRdR` |" in text
    assert "**revenue**: Revenues FY2023–FY2024" in text
    assert "## Unexplained gaps" in text


def test_shipped_known_gaps_file_loads():
    assert isinstance(quality.load_known_gaps(), list)


def test_unquoted_comma_in_a_reason_is_reported_with_its_line(tmp_path):
    path = tmp_path / "gaps.csv"
    path.write_text(
        "ticker,canonical_name,fiscal_years,periods,reason\n"
        'TST,cash,*,*,"Quoted, fine."\n'
        "TST,capex,*,*,Unquoted, broken.\n"
    )
    with pytest.raises(ValueError, match="line 3"):
        quality.load_known_gaps(path)


def test_quarters_that_do_not_add_up_to_the_year_are_listed(ingested, two_years):
    conn, _ = ingested
    # a later filing restates Q3 2024 revenue; FY and the nine months stay as first filed
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', "
        "'us-gaap:Revenues', '2024-07-01', '2024-09-30', 2024, 'Q3', 150, 'USD', '10-Q', "
        "'0000000123-25-000050', '2025-02-20')"
    )
    report = report_for(conn)
    found = [i for i in report.inconsistencies if i.canonical_name == "revenue"]
    assert [(i.fiscal_year, i.quarters_total, i.restated) for i in found] == [
        (2024, 100 + 110 + 150 + 130, ("Q3",))
    ]
    assert "- **revenue** FY2024: quarters" in report.to_markdown()


def test_report_names_its_data_snapshot(ingested, two_years):
    conn, _ = ingested
    report = report_for(conn)
    assert report.last_ingest is not None and not report.concept_map_changed
    assert "fetched 2026-10-26T12:00:00Z" in report.to_markdown()


def test_report_warns_when_the_concept_map_changed_after_ingest(ingested, two_years, monkeypatch):
    conn, _ = ingested
    monkeypatch.setattr(quality, "concept_map_sha256", lambda: "0" * 64)
    assert "changed since this ingest" in report_for(conn).to_markdown()


def test_inferred_gaps_link_to_the_filing_to_check(ingested, two_years):
    conn, _ = ingested
    known = [KnownGap("TST", "capex", "2023", "Q1", "[inferred] Not tagged in that 10-Q.")]
    report = report_for(conn, known)
    link = report.gap_links[("capex", 2023, "Q1")]
    # Q1 2023 was first reported (as a comparative) in the Q1 2024 10-Q
    assert link == "https://www.sec.gov/Archives/edgar/data/123/000000012324000010/"
    assert f"([check]({link}))" in report.to_markdown()


def test_consistent_quarters_are_not_listed(ingested, two_years):
    conn, _ = ingested
    report = report_for(conn)
    assert report.inconsistencies == []
    assert "## Quarters vs full year" in report.to_markdown()


def test_optional_item_gaps_are_listed_but_never_gated(ingested, two_years):
    conn, _ = ingested
    report = report_for(conn)  # the fixture holds no securities and no fallback items
    assert any(g.canonical_name == "marketable_securities_current" for g in report.optional_gaps)
    assert not any(g.canonical_name == "marketable_securities_current" for g in report.unexplained)
    assert not any(g.canonical_name == "interest_paid" for g in report.explained)
    assert "- marketable_securities_current: 10 of 10 periods missing" in report.to_markdown()


def test_newest_filing_disagreement_appears_in_the_report(ingested, two_years):
    conn, _ = ingested
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, "
        "'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax', '2024-01-01', "
        "'2024-12-31', 2024, 'FY', 450, 'USD', '10-K', 'a-25-9', '2025-02-20')",
        (TEST_CIK,),
    )
    markdown = report_for(conn).to_markdown()
    assert "selected Revenues, newest filing RevenueFromContractWithCustomer" in markdown
    assert "2024-12-31 0M vs 0M" in markdown  # fixture values are tiny; shown in millions
