"""A run whose revenue crosses a tag's change of meaning (backlog #297 item 1), on Test Corp
(tests/analysis/conftest.py) with `Revenues` 4% higher from its Q3 2019 10-Q (filed 2019-10-30),
the old figures kept under the contract-revenue tag (`_redefine_revenues`). Its FY2019 10-K
(filed 2020-02-15) refiles 2017 and 2018 on the new meaning; FY2019Q2 is never refiled."""

from datetime import date

import pytest

from domains.analysis import math_engine
from domains.analysis.coded import RUN_NOTE_CODES
from domains.analysis.math_engine import EngineResult, _meaning_notes, build_inputs
from domains.fundamentals.facts import MeaningChange
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF, CHOICES
from tests.analysis.test_reported import CONTRACT, _redefine_revenues

TAG, OTHER = "us-gaap:Revenues", f"us-gaap:{CONTRACT}"


def _build(conn, as_of=AS_OF):
    return build_inputs(conn, "TST", as_of, choices=CHOICES, today=AS_OF)


def _notes(result):
    return [n for n in result.notes if n.code == "run_mixes_meanings"]


def test_a_run_across_the_change_says_so(make_company):
    (note,) = _notes(_build(make_company(_redefine_revenues)))
    p = note.params
    assert note.code in RUN_NOTE_CODES
    assert (p["item"], p["tag"], p["other_tag"], p["changed_on"], p["form"]) == (
        "revenue",
        TAG,
        OTHER,
        "2019-10-30",
        "10-Q",
    )
    # the seed FY2019Q2–FY2020Q1 mixes FY2019Q2 (never refiled) with later quarters, and the
    # margin window FY2017Q2–FY2020Q1 mixes 2017 and early 2018 with the refiled quarters; the
    # three history years all come from the FY2019 10-K, on the new meaning
    assert p["parts"] == ["seed", "operating_margin"]
    assert "FY2019Q2" in p["old_periods"] and "FY2017Q2" in p["old_periods"]
    assert {"FY2019Q3", "FY2020Q1", "FY2017", "FY2018", "FY2019"} <= set(p["new_periods"])
    # Test Corp files no nine-month figures, so a Q4 is its year less Q1, Q2 and Q3, filed on
    # both sides of the change
    assert p["mixed_periods"] == ["FY2018Q4", "FY2019Q4"] and p["other_tag_periods"] == []
    labels = p["old_periods"] + p["new_periods"] + p["mixed_periods"]
    assert len(labels) == len(set(labels))  # each label once
    # FY2019's quarters miss the year, so the seed is the year split by the quarters' shares
    assert p["seed_split_years"] == [2019]
    assert p["largest_gap"] == pytest.approx(0.04)
    assert note.text.startswith(f"This run reads revenue as {TAG} with more than one meaning: ")
    assert "the revenue the forecast starts from and the quarterly operating margins." in note.text
    assert "For FY2019 the forecast starts from the year's total as filed" in note.text
    assert "differ by up to 4.0%" in note.text and OTHER in note.text


def test_the_note_changes_no_row(make_company, monkeypatch):
    conn = make_company(_redefine_revenues)
    noted = _build(conn)
    monkeypatch.setattr(math_engine, "tag_meaning_changes", lambda *a, **k: [])
    plain = _build(conn)
    assert noted.assumptions == plain.assumptions
    assert noted.sources == plain.sources
    assert [n for n in noted.notes if n.code != "run_mixes_meanings"] == plain.notes


def test_no_note_before_the_change_is_public(make_company):
    assert _notes(_build(make_company(_redefine_revenues), date(2019, 10, 29))) == []


def test_no_note_without_a_change(company):
    assert _notes(_build(company)) == []


# -- the rule on hand-built facts ---------------------------------------------------------------

CHANGE = MeaningChange(
    "revenue",
    TAG,
    OTHER,
    "0000000123-19-000014",
    "10-Q",
    date(2019, 10, 30),
    [(date(2018, 7, 1), date(2018, 9, 30), 100.0, 104.0)],
)


def _fact(label, filed, tag=TAG):
    year, quarter = int(label[2:6]), label[7:] or None
    return Fact(
        canonical_name="revenue",
        xbrl_concept=tag,
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        fiscal_year=year,
        fiscal_period=f"Q{quarter}" if quarter else "FY",
        value=100.0,
        unit="USD",
        accession_no=f"a-{label}",
        filed_at=filed,
    )


def _run(parts):
    result = EngineResult("TST", "123", date(2020, 6, 30))
    for part, facts in parts.items():
        for label, filed, *tag in facts:
            result.read(part, label, _fact(label, filed, *tag))
    _meaning_notes(result, [CHANGE], {})
    return _notes(result)


OLD, NEW = date(2019, 2, 15), date(2020, 2, 15)


def test_parts_each_on_one_meaning_but_not_the_same_one():
    (note,) = _run(
        {
            "seed": [("FY2019Q4", NEW), ("FY2020Q1", NEW)],
            "operating_margin": [("FY2018Q1", OLD), ("FY2018Q2", OLD)],
        }
    )
    assert note.params["parts"] == []
    assert note.params["old_periods"] == ["FY2018Q1", "FY2018Q2"]
    assert "Each part of the run is on one meaning, but not the same one" in note.text


def test_old_and_other_tags_without_the_new_meaning_have_no_note():
    assert _run({"seed": [("FY2018Q1", OLD), ("FY2018Q2", OLD, "us-gaap:SalesRevenueNet")]}) == []


def test_all_on_the_new_meaning_has_no_note():
    assert _run({"seed": [("FY2019Q4", NEW)], "history": [("FY2019", NEW)]}) == []


def test_another_tag_beside_the_new_meaning_is_noted_as_other():
    (note,) = _run({"history": [("FY2016", OLD, "us-gaap:SalesRevenueNet"), ("FY2019", NEW)]})
    assert note.params["other_tag_periods"] == ["FY2016"]
    assert note.params["parts"] == ["history"]
    assert "FY2016 another tag, of unknown meaning" in note.text
