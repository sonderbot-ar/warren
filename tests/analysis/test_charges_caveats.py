"""Charges Coca-Cola's interest still holds, said on the cost-of-debt chart (backlog #613 items 2
and 3): `extinguishment_not_tagged` and `hedge_reclass_in_interest`, from interest_caveats.csv.

Test Corp's interest is 8 a year on 200 of debt (a 4% book cost, above the 3% yield). Its FY2018
10-K is 0000000123-19-000011, filed 2019-02-15, before the run's date (2020-06-30);
0000000123-20-000099 is never ingested, so Warren cannot date it.
"""

from datetime import date

import pytest

from domains.analysis import interest_caveats as ic
from domains.analysis.inputs import inputs_behind
from domains.analysis.runs import run_baseline
from domains.analysis.single_values import CELL_NOTES, POINT_NOTES
from tests.analysis.conftest import AS_OF, CHOICES
from tests.analysis.test_single_values import VPS, _cell, _cost_points

RECLASS = "hedge_reclass_in_interest"
UNTAGGED = "extinguishment_not_tagged"
HEDGE = "interest_net_of_hedge_gains"
FY2018_10K = "0000000123-19-000011"
FY2017_10K = "0000000123-18-000011"
UNKNOWN = "0000000123-20-000099"
EVIDENCE = f'{FY2018_10K} (FY2018 10-K): "charges of 5". {UNKNOWN} (later 10-K): "charges of 9".'


def _caveat(code, first, last, evidence=EVIDENCE, rate_item=None):
    return ic.InterestCaveat("TST", code, first, last, rate_item, evidence, "")


def _company(make_company, monkeypatch, *caveats):
    monkeypatch.setattr(ic, "_shipped", lambda: tuple(caveats))
    conn = make_company(lambda _tag, row: row)
    return conn, run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _by_year(conn, run_id):
    cell, points = _cost_points(conn, run_id)
    return cell, {p.fiscal_year: p for p in points}


def test_covered_years_carry_the_note_with_the_public_filings_only(make_company, monkeypatch):
    conn, run_id = _company(make_company, monkeypatch, _caveat(RECLASS, 2017, 2018))
    _, by_year = _by_year(conn, run_id)
    for year in (2016, 2019):
        assert not any(n.code == RECLASS for n in by_year[year].notes)
    for year in (2017, 2018):
        (note,) = [n for n in by_year[year].notes if n.code == RECLASS]
        p = note.params
        assert (p["fiscal_year"], p["from_fiscal_year"], p["to_fiscal_year"]) == (year, 2017, 2018)
        assert p["cost_of_debt"] == by_year[year].value
        [filing] = p["evidence_filings"]  # the undated one is left out
        assert (filing["accession_no"], filing["form"]) == (FY2018_10K, "10-K")
        assert date.fromisoformat(filing["filed_at"]) <= AS_OF
        [quoted] = p["evidence"]
        assert quoted["filing"] == filing
        assert quoted["quote"] == '(FY2018 10-K): "charges of 5".'
        assert "hedge losses" in note.text and "reads a little high" in note.text


def test_no_cited_filing_public_on_the_run_date_gives_no_note(make_company, monkeypatch):
    late = _caveat(UNTAGGED, 2015, 2019, evidence=f'{UNKNOWN} (later 10-K): "charges of 9".')
    conn, run_id = _company(make_company, monkeypatch, late)
    cell, by_year = _by_year(conn, run_id)
    assert not any(n.code == UNTAGGED for p in by_year.values() for n in p.notes)
    assert not any(n.code == UNTAGGED for n in cell.notes)


def test_the_values_are_the_same_with_and_without_the_caveat(make_company, monkeypatch):
    conn, run_id = _company(make_company, monkeypatch)
    _, before = _by_year(conn, run_id)
    monkeypatch.setattr(ic, "_shipped", lambda: (_caveat(UNTAGGED, 2015, 2019),))
    _, after = _by_year(conn, run_id)
    assert {y: (p.value, p.parts) for y, p in before.items()} == {
        y: (p.value, p.parts) for y, p in after.items()
    }
    for year, p in after.items():
        assert [n for n in p.notes if n.code != UNTAGGED] == before[year].notes


def test_the_cell_carries_the_note_on_the_runs_own_year(make_company, monkeypatch):
    conn, run_id = _company(make_company, monkeypatch, _caveat(RECLASS, 2019, None))
    cell, by_year = _by_year(conn, run_id)
    (used,) = [p for p in by_year.values() if p.used]
    (on_cell,) = [n for n in cell.notes if n.code == RECLASS]
    assert on_cell in used.notes
    assert on_cell.params["cost_of_debt"] == cell.rows[0].value  # the run's own row
    conn, run_id = _company(make_company, monkeypatch, _caveat(RECLASS, 2010, 2012))
    cell = _cell(inputs_behind(conn, run_id, VPS), "cost_of_debt")
    assert not any(n.code == RECLASS for n in cell.notes)


def test_two_codes_and_the_hedge_note_sit_on_one_point_in_order(make_company, monkeypatch):
    hedge = _caveat(HEDGE, 2017, None, evidence="10-K tables")
    conn, run_id = _company(
        make_company,
        monkeypatch,
        hedge,
        _caveat(UNTAGGED, 2018, 2018),
        _caveat(RECLASS, 2018, 2018),
    )
    _, by_year = _by_year(conn, run_id)
    assert [n.code for n in by_year[2018].notes] == [UNTAGGED, RECLASS, HEDGE]
    assert [n.code for n in by_year[2017].notes] == [HEDGE]


def test_the_codes_stay_in_the_closed_lists():
    for code in (UNTAGGED, RECLASS):
        assert code in POINT_NOTES and code in CELL_NOTES and code in ic.CAVEAT_CODES
    assert ic.CHARGES_CODES == (UNTAGGED, RECLASS)


@pytest.mark.parametrize("year", [2013])
def test_the_shipped_coca_cola_rows_are_found_by_code(year):
    assert ic.caveat_for("KO", year) is None  # never read as the hedge row
    assert [c.code for c in ic.charges_caveats("KO", 2013)] == [UNTAGGED]
    assert [c.code for c in ic.charges_caveats("KO", 2020)] == [RECLASS]
    assert [c.code for c in ic.charges_caveats("KO", 2021)] == [RECLASS]
    assert ic.charges_caveats("KO", 2019) == () and ic.charges_caveats("KO", 2022) == ()
    assert ic.charges_caveats("JNJ", 2020) == ()
