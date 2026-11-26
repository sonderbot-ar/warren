"""The cost-of-debt chart's check against the rate the company states (backlog #543).

Test Corp's interest (8 a year on 200 of debt: 20 current, 180 non-current) gives a 4% book cost
of debt. Rates are filed at the year ends in each 10-K, under the two new items' own tags, read
for TST.
"""

import dataclasses
from datetime import date

import pytest

from domains.analysis import interest_caveats, stated_debt_rates
from domains.analysis.inputs import inputs_behind
from domains.analysis.runs import run_baseline
from domains.analysis.single_values import (
    BALANCE_NOTES,
    CELL_NOTES,
    POINT_NOTES,
    STATED_NOTE,
    STATED_RATE_GAP,
)
from domains.analysis.stated_debt_rates import StatedDebtRates
from domains.fundamentals import ingest
from tests.analysis.conftest import AS_OF, CHOICES
from tests.analysis.test_single_values import SINGLE_CELLS, VPS, _cell, _cost_points, _primary

LONG_TAG = "LongtermDebtWeightedAverageInterestRate"
SHORT_TAG = "ShortTermDebtWeightedAverageInterestRate"
BORROW_TAG = "NotesAndLoansPayableCurrent"
LATE_ACCESSION = "0000000123-20-000099"  # filed 2020-08-01, after AS_OF
HEDGE = "interest_net_of_hedge_gains"


def _stated(
    make_company,
    monkeypatch,
    long=None,
    short=None,
    covers="due_within_one_year",
    short_item=True,
    late=(),
    borrowings=0,
    caveat_from=None,
):
    """Test Corp with a stated long-term rate (`long`) and short-term rate (`short`) at each
    listed year end ({year: rate}, filed in that year's 10-K, or after `AS_OF` for a year in
    `late`), and a `StatedDebtRates` row for TST (no short-term item when `short_item` is False).
    `borrowings` adds that much short-term borrowings at every balance date. `caveat_from` adds
    an interest caveat for TST from that fiscal year."""
    long, short = long or {}, short or {}
    real_map = ingest.load_concept_map
    tags = {
        "debt_average_rate_long_term": LONG_TAG,
        "debt_average_rate_short_term": SHORT_TAG,
    }

    def with_tst():
        out = []
        for r in real_map():
            if r.canonical_name in tags:
                assert r.xbrl_concept == f"us-gaap:{tags[r.canonical_name]}"
                r = dataclasses.replace(r, companies=frozenset({"TST"}))
            elif r.canonical_name == "debt_effective_rate" or (
                borrowings and r.canonical_name == "short_term_borrowings"
            ):
                r = dataclasses.replace(r, companies=r.companies | {"TST"})
            out.append(r)
        return out

    monkeypatch.setattr(ingest, "load_concept_map", with_tst)
    row = StatedDebtRates(
        "TST",
        "debt_average_rate_long_term",
        "debt_average_rate_short_term" if short_item else None,
        covers if short_item else None,
        "test filings 0000000123-19-000011",
    )
    monkeypatch.setattr(
        stated_debt_rates, "stated_rates_for", lambda t: row if t == "TST" else None
    )
    if caveat_from is not None:
        caveat = interest_caveats.InterestCaveat(
            "TST", HEDGE, caveat_from, None, "debt_effective_rate", "test filings", ""
        )
        monkeypatch.setattr(
            interest_caveats,
            "caveat_for",
            lambda ticker, year: caveat if ticker == "TST" and caveat.covers(year) else None,
        )

    def edit(tag, row):
        if tag != "LongTermDebtNoncurrent":
            return row
        extra = [(tag, row)]
        if borrowings:
            extra.append((BORROW_TAG, {**row, "val": borrowings}))
        if row["form"] == "10-K" and row["end"] == f"{row['fy']}-12-31":
            for rate_tag, rates in ((LONG_TAG, long), (SHORT_TAG, short)):
                if row["fy"] in rates:
                    rate = {**row, "val": rates[row["fy"]]}
                    if row["fy"] in late:
                        rate |= {"filed": "2020-08-01", "accn": LATE_ACCESSION}
                    extra.append((rate_tag, rate))
        return extra

    conn = make_company(edit)
    return conn, run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _by_year(conn, run_id):
    cell, points = _cost_points(conn, run_id)
    return cell, {p.fiscal_year: p for p in points}


def _stated_notes(point):
    return [n for n in point.notes if n.code == STATED_NOTE]


def _one(point):
    (note,) = _stated_notes(point)
    return note


def test_a_stated_rate_within_a_point_gives_no_note(make_company, monkeypatch):
    # 4% book against 4.9% stated: a 0.9 point gap, inside the 1 point threshold
    rates = {y: 0.049 for y in range(2015, 2020)}
    conn, run_id = _stated(make_company, monkeypatch, long=rates, short_item=False)
    cell, by_year = _by_year(conn, run_id)
    for p in by_year.values():
        assert not _stated_notes(p), p.fiscal_year
    assert not any(n.code == STATED_NOTE for n in cell.notes)
    assert STATED_RATE_GAP == 0.01


@pytest.mark.parametrize(("stated", "fires"), [(0.0499, False), (0.0501, True)])
def test_the_line_sits_at_one_point(make_company, monkeypatch, stated, fires):
    # 4% book against 4.99% (0.99 points) and 5.01% (1.01 points), at every year end
    rates = {y: stated for y in range(2015, 2020)}
    conn, run_id = _stated(make_company, monkeypatch, long=rates, short_item=False)
    _, by_year = _by_year(conn, run_id)
    assert bool(_stated_notes(by_year[2019])) is fires


def test_a_rate_beyond_a_point_gives_the_note_with_its_params(make_company, monkeypatch):
    rates = {2018: 0.06, 2019: 0.07}
    conn, run_id = _stated(make_company, monkeypatch, long=rates, short_item=False)
    _, by_year = _by_year(conn, run_id)
    point = by_year[2019]
    note = _one(point)
    p = note.params
    assert p["fiscal_year"] == 2019 and p["cost_of_debt"] == point.value
    assert p["cost_of_debt"] == pytest.approx(0.04)
    assert p["stated_rate"] == pytest.approx(0.065)  # the two year ends averaged
    assert p["gap"] == pytest.approx(0.04 - 0.065) and p["gap"] < 0  # book below stated
    assert p["threshold"] == 0.01 and p["short_rate_covers"] is None
    first, last = p["year_ends"]  # oldest first
    assert (first["period_end"], last["period_end"]) == ("2018-12-31", "2019-12-31")
    assert (first["stated_rate"], last["stated_rate"]) == (pytest.approx(0.06), pytest.approx(0.07))
    assert last["long_term_rate"] == 0.07 and last["long_term_rate_filing"]["form"] == "10-K"
    assert last["long_term_rate_filing"]["accession_no"].startswith("0000000123-")
    assert "percentage points below" in note.text
    # the 2018 point has no opening rate (2017) and its closing one alone is 6%
    only = _one(by_year[2018]).params["year_ends"]
    assert [e["period_end"] for e in only] == ["2018-12-31"]
    assert _one(by_year[2018]).params["stated_rate"] == pytest.approx(0.06)


def test_a_book_rate_above_the_stated_rate_has_a_positive_gap(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company, monkeypatch, long={2018: 0.02, 2019: 0.02}, short_item=False
    )
    _, by_year = _by_year(conn, run_id)
    p = _one(by_year[2019]).params
    assert p["gap"] == pytest.approx(0.02) and p["stated_rate"] == pytest.approx(0.02)
    assert "percentage points above" in _one(by_year[2019]).text


def test_the_closing_rate_alone_is_used_when_the_opening_has_none(make_company, monkeypatch):
    conn, run_id = _stated(make_company, monkeypatch, long={2019: 0.07}, short_item=False)
    _, by_year = _by_year(conn, run_id)
    p = _one(by_year[2019]).params
    assert [e["period_end"] for e in p["year_ends"]] == ["2019-12-31"]
    assert p["stated_rate"] == pytest.approx(0.07)  # not averaged with anything


def test_no_note_without_a_closing_rate(make_company, monkeypatch):
    # FY2019's opening (2018) has a rate, its closing (2019) has none
    conn, run_id = _stated(make_company, monkeypatch, long={2018: 0.08}, short_item=False)
    _, by_year = _by_year(conn, run_id)
    assert not _stated_notes(by_year[2019])
    assert _stated_notes(by_year[2018])  # 2018's closing has one (opening 2017 has none)


def test_the_short_rate_blends_by_the_current_portion_when_it_is_due_within_a_year(
    make_company, monkeypatch
):
    # 20 of 200 is current: share 0.1; blend 0.9 * 6% + 0.1 * 2% = 5.6% at each year end
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2018: 0.06, 2019: 0.06},
        short={2018: 0.02, 2019: 0.02},
        covers="due_within_one_year",
    )
    _, by_year = _by_year(conn, run_id)
    p = _one(by_year[2019]).params
    assert p["short_rate_covers"] == "due_within_one_year"
    assert p["stated_rate"] == pytest.approx(0.056)
    assert p["gap"] == pytest.approx(0.04 - 0.056)
    for end in p["year_ends"]:
        assert end["short_term_share"] == pytest.approx(0.1)
        assert (end["long_term_rate"], end["short_term_rate"]) == (0.06, 0.02)
        assert end["stated_rate"] == pytest.approx(0.056)
        assert end["short_term_rate_filing"]["form"] == "10-K"


def test_short_term_borrowings_cover_leaves_the_current_portion_at_the_long_rate(
    make_company, monkeypatch
):
    # Warren counts no short-term borrowings here: the whole 200 takes the long-term rate, and
    # the short-term rate is never read
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2018: 0.06, 2019: 0.06},
        short={2018: 0.01, 2019: 0.01},
        covers="short_term_borrowings",
    )
    _, by_year = _by_year(conn, run_id)
    p = _one(by_year[2019]).params
    assert p["short_rate_covers"] == "short_term_borrowings"
    assert p["stated_rate"] == pytest.approx(0.06)
    for end in p["year_ends"]:
        assert end["short_term_share"] == 0.0 and end["short_term_rate"] is None


def test_short_term_borrowings_cover_blends_by_the_borrowings_counted(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2018: 0.06, 2019: 0.06},
        short={2018: 0.01, 2019: 0.01},
        covers="short_term_borrowings",
        borrowings=50,
    )
    cell, by_year = _by_year(conn, run_id)
    point = by_year[2019]
    closing = {q.name: q.value for q in point.parts if q.period == "2019-12-31"}
    # counted at the closing year end: 50 of borrowings, 20 current and 180 non-current debt
    assert closing["short_term_borrowings"] == 50
    assert (closing["debt_current"], closing["debt_noncurrent"]) == (20, 180)
    share = 50 / 250
    expected = 0.06 * (1 - share) + 0.01 * share  # by hand: 0.048 + 0.002 = 0.05
    assert expected == pytest.approx(0.05)
    notes = _stated_notes(point)
    assert len(notes) == 1
    end = notes[0].params["year_ends"][-1]
    assert end["short_term_share"] == pytest.approx(share) and 0 < share < 1
    assert end["stated_rate"] == pytest.approx(expected)
    # the current portion, when counted too, stays at the long-term rate under this cover
    assert end["long_term_rate"] == 0.06 and end["short_term_rate"] == 0.01


def test_no_short_term_item_means_the_long_rate_covers_all_the_debt(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2018: 0.07, 2019: 0.07},
        short={2018: 0.001, 2019: 0.001},  # filed, but the row names no short-term item
        short_item=False,
    )
    _, by_year = _by_year(conn, run_id)
    p = _one(by_year[2019]).params
    assert p["short_rate_covers"] is None
    assert p["stated_rate"] == pytest.approx(0.07)
    for end in p["year_ends"]:
        assert end["short_term_rate"] is None and end["short_term_share"] == 0
        assert end["short_term_rate_filing"] is None


def test_no_note_when_a_short_rate_is_stated_but_missing_at_the_year_end(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company, monkeypatch, long={2018: 0.07, 2019: 0.07}, short={2018: 0.02}
    )
    _, by_year = _by_year(conn, run_id)
    # 2019's closing year end has current debt but no short-term rate: no note for the year
    assert not _stated_notes(by_year[2019])
    # 2018 closing has both rates: the note is there
    assert _stated_notes(by_year[2018])


def test_a_rate_filed_after_the_run_date_is_never_read(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2018: 0.06, 2019: 0.5},
        short_item=False,
        late={2019},
    )
    cell, by_year = _by_year(conn, run_id)
    assert not _stated_notes(by_year[2019])  # the closing rate is not yet public
    assert not any(n.code == STATED_NOTE for n in cell.notes)
    note = _one(by_year[2018])
    assert note.params["year_ends"][-1]["long_term_rate_filing"]["accession_no"] != LATE_ACCESSION
    for p in by_year.values():
        for n in _stated_notes(p):
            for end in n.params["year_ends"]:
                assert end["long_term_rate"] != 0.5
                assert date.fromisoformat(end["long_term_rate_filing"]["filed_at"]) <= AS_OF


def test_a_year_an_interest_caveat_covers_gets_only_the_hedge_note(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={y: 0.07 for y in range(2015, 2020)},
        short_item=False,
        caveat_from=2018,
    )
    cell, by_year = _by_year(conn, run_id)
    for year in (2018, 2019):
        codes = [n.code for n in by_year[year].notes]
        assert HEDGE in codes and STATED_NOTE not in codes, year
    assert _stated_notes(by_year[2017])  # before the caveat: this note as usual
    assert not any(n.code == STATED_NOTE for n in cell.notes)
    assert any(n.code == HEDGE for n in cell.notes)


def test_the_cell_carries_the_used_years_note_and_its_run_row(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company, monkeypatch, long={2018: 0.06, 2019: 0.07}, short_item=False
    )
    cell, points = _cost_points(conn, run_id)
    (used,) = [p for p in points if p.used]
    (on_cell,) = [n for n in cell.notes if n.code == STATED_NOTE]
    assert on_cell == _one(used)
    assert on_cell.params["cost_of_debt"] == cell.rows[0].value  # the run's own row
    assert on_cell.params["fiscal_year"] == used.fiscal_year == 2019
    # a year that is not the run's own never reaches the cell
    others = [p for p in points if not p.used and _stated_notes(p)]
    assert others and all(
        n.params["fiscal_year"] != used.fiscal_year for p in others for n in _stated_notes(p)
    )
    assert {n.code for n in cell.notes} <= set(CELL_NOTES)


def test_the_cell_has_no_note_when_the_used_year_is_close(make_company, monkeypatch):
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={2016: 0.08, 2017: 0.08, 2018: 0.041, 2019: 0.041},
        short_item=False,
    )
    cell, by_year = _by_year(conn, run_id)
    assert _stated_notes(by_year[2017])  # other years far from it still carry the note
    assert not any(n.code == STATED_NOTE for n in cell.notes)


def test_the_note_code_stays_in_the_closed_lists(make_company, monkeypatch):
    assert STATED_NOTE == "far_from_stated_rate"
    assert STATED_NOTE in POINT_NOTES and STATED_NOTE in CELL_NOTES
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={y: 0.07 for y in range(2015, 2020)},
        short={y: 0.02 for y in range(2015, 2020)},
    )
    answer = inputs_behind(conn, run_id, VPS, years=10)
    point_codes = {*BALANCE_NOTES, *POINT_NOTES}
    seen = False
    for name in SINGLE_CELLS:
        cell = _cell(answer, name)
        assert {n.code for n in cell.notes} <= set(CELL_NOTES)
        for series in cell.history:
            for p in series.points:
                assert {n.code for n in p.notes} <= point_codes
                seen |= bool(_stated_notes(p))
    assert seen


def _run_rows(conn, run_id):
    return conn.execute(
        "SELECT name, period, value FROM assumptions WHERE run_id = ? ORDER BY name, period",
        (run_id,),
    ).fetchall()


def test_adding_the_rates_changes_no_row_and_no_number(make_company, monkeypatch, company):
    plain_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    conn, run_id = _stated(
        make_company,
        monkeypatch,
        long={y: 0.07 for y in range(2015, 2020)},
        short={y: 0.02 for y in range(2015, 2020)},
    )
    assert _by_year(conn, run_id)[1][2019].notes  # the note is really there
    plain_rows, rows = _run_rows(company, plain_id), _run_rows(conn, run_id)
    assert rows and [tuple(r) for r in rows] == [tuple(r) for r in plain_rows]
    plain = inputs_behind(company, plain_id, VPS, years=10)
    stated = inputs_behind(conn, run_id, VPS, years=10)
    assert stated.outputs == plain.outputs
    for c, d in zip(stated.cells, plain.cells, strict=True):
        assert [r.value for r in c.rows] == [r.value for r in d.rows], c.name
        if c.name != "cost_of_debt":
            continue
        assert [p.value for p in _primary(c).points] == [p.value for p in _primary(d).points]
