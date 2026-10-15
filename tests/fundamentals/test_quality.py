from datetime import date

import pytest

from domains.fundamentals import quality
from domains.fundamentals.quality import KnownGap, build_report


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
