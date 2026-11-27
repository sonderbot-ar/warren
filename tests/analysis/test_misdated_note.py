"""The cost-of-debt chart says when a filed figure was left out because its filing put it under
the wrong year (backlog #613, `misdated_fact_left_out`).

Test Corp's interest is 8 a year on 200 of debt (a 4% book cost of debt). Each 10-K also files a
loss of 1 on paying debt off early for its own year, read for TST, so a counted year's interest is
7 (3.5%). The FY2018 figure, from the FY2018 10-K (0000000123-19-000011), is listed as misdated
with 2017 as the year its text gives.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from domains.analysis import misdated_facts as mf
from domains.analysis.math_engine import History, Resolved, trace
from domains.analysis.runs import run_baseline
from domains.analysis.single_values import (
    BALANCE_NOTES,
    CELL_NOTES,
    MISDATED_NOTE,
    POINT_NOTES,
    _misdated_notes,
)
from domains.fundamentals import ingest
from tests.analysis.conftest import AS_OF, CHOICES
from tests.analysis.test_extinguishment_interest import fact
from tests.analysis.test_single_values import _cost_points

ITEM = "debt_extinguishment_in_interest"
TAG = "GainsLossesOnExtinguishmentOfDebt"
FY2018_10K = "0000000123-19-000011"
FY2019_10K = "0000000123-20-000015"
LATE = "0000000123-20-000099"  # filed 2020-08-01, after AS_OF


def _listed(*rows):
    table = {(r.canonical_name, r.fiscal_year, r.accession_no): r for r in rows}
    return lambda: table


def _row(year, accession, stated):
    return mf.MisdatedFact("TST", ITEM, year, accession, stated, f"{accession} says {stated}")


def _company(make_company, monkeypatch, listed=(), late=(), with_item=True):
    """Test Corp with the extinguishment item read for TST (when `with_item`), a loss of 1 filed
    in each 10-K for its own year (after `AS_OF` for a year in `late`), and `listed` rows."""
    real_map = ingest.load_concept_map

    def with_tst():
        return [
            dataclasses.replace(r, companies=r.companies | {"TST"})
            if r.canonical_name == ITEM
            else r
            for r in real_map()
        ]

    monkeypatch.setattr(ingest, "load_concept_map", with_tst)
    monkeypatch.setattr(mf, "_by_key", _listed(*listed))

    def edit(tag, row):
        own_year = row["form"] == "10-K" and row["end"] == f"{row['fy']}-12-31"
        if tag != "InterestExpense" or not own_year or not with_item:
            return row
        loss = {**row, "val": -1}
        if row["fy"] in late:
            loss |= {"filed": "2020-08-01", "accn": LATE}
        return [(tag, row), (TAG, loss)]

    conn = make_company(edit)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _, points = _cost_points(conn, run_id)
    return {p.fiscal_year: p for p in points}


def _notes(point):
    return [n for n in point.notes if n.code == MISDATED_NOTE]


def test_a_listed_year_carries_the_note_with_its_params(make_company, monkeypatch):
    by_year = _company(make_company, monkeypatch, listed=[_row(2018, FY2018_10K, 2017)])
    point = by_year[2018]
    (note,) = _notes(point)
    assert point.notes[0] is note  # first: it explains a part that is missing (product lead)
    params = note.params
    assert params["fiscal_year"] == 2018 and params["item"] == ITEM
    assert params["value"] == -1
    assert params["filing"]["accession_no"] == FY2018_10K
    assert params["stated_fiscal_year"] == 2017
    assert params["stated_year_value"] == -1  # FY2017's own figure, counted on its point
    assert params["evidence"] == f"{FY2018_10K} says 2017"
    assert "puts it in FY2017" in note.text
    # the figure is not a part of the point, and the point is the plain 4%
    assert ITEM not in {p.name for p in point.parts}
    assert point.value == 8 / 200


def test_other_years_keep_their_part_and_get_no_note(make_company, monkeypatch):
    by_year = _company(make_company, monkeypatch, listed=[_row(2018, FY2018_10K, 2017)])
    for year in (2017, 2019):
        assert not _notes(by_year[year])
        assert ITEM in {p.name for p in by_year[year].parts}
        assert by_year[year].value == 7 / 200


def test_nothing_listed_gives_no_note(make_company, monkeypatch):
    by_year = _company(make_company, monkeypatch)
    assert by_year and not any(_notes(p) for p in by_year.values())


def test_a_listed_fact_filed_after_the_run_date_gives_no_note(make_company, monkeypatch):
    """Point in time: the run cannot know the misdating filing yet, so the chart says nothing of
    it (professor)."""
    by_year = _company(make_company, monkeypatch, listed=[_row(2019, LATE, 2018)], late=(2019,))
    assert not _notes(by_year[2019])
    assert ITEM not in {p.name for p in by_year[2019].parts}  # not known yet, so no part either
    assert by_year[2019].value == 8 / 200


def test_the_note_reads_no_new_number(make_company, monkeypatch, company):
    """The listed year's point equals the same company's with no extinguishment item at all."""
    listed = _company(make_company, monkeypatch, listed=[_row(2018, FY2018_10K, 2017)])
    plain = _company(make_company, monkeypatch, with_item=False)
    assert listed[2018].value == plain[2018].value


def test_no_note_when_the_interest_never_read_the_figure():
    """The cash fallback and the cash-paid path never look at the figure, so no note, even when
    it is listed (analyst)."""
    ext = fact(ITEM, -320, 2016, "0000021344-17-000009")
    history = History(quarterly={}, annual={(ITEM, 2016): ext}, instants={})
    singles = SimpleNamespace(history=history)
    row = _row(2016, "0000021344-17-000009", 2015)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mf, "_by_key", _listed(row))
        never_read = Resolved(733e6, "interest paid (cash)", True, ())
        assert _misdated_notes(singles, 2016, never_read) == []
        counted = Resolved(413e6, f"x - y: {trace(ext)}", False, (ext,))
        assert _misdated_notes(singles, 2016, counted) == []


def test_the_note_code_stays_in_the_closed_lists():
    assert MISDATED_NOTE == "misdated_fact_left_out"
    assert MISDATED_NOTE in POINT_NOTES and MISDATED_NOTE not in CELL_NOTES
    assert MISDATED_NOTE not in BALANCE_NOTES
