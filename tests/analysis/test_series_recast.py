"""A series across a recast that left some of its periods unchanged (backlog #297 item 13), on
Test Corp (tests/analysis/conftest.py). `_recast_revenues`: from its FY2018 10-K (filed
2019-02-15), every filing gives revenue for periods ending in 2017 or later 5% lower, with no
other tag keeping the old figures (a recast, as Exxon's 10-K of 2018-02-28 cut FY2015 and
FY2016). That 10-K covers 2016 to 2018, so FY2017 moves, FY2016 is filed again unchanged, and
FY2015 (last in the FY2017 10-K, filed 2018-02-15) is never filed again."""

import json
from datetime import date, timedelta

import pytest

from domains.analysis.reported import QUARTER_SPAN, _recast_note, reported_series
from domains.fundamentals.facts import RECAST_MOVE, Recast, item_recasts, side_of_recast
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF, revenue
from tests.analysis.test_reported import _redefine_revenues
from tests.analysis.test_reported_series import REVENUE_RATIOS

TEN_K_2018 = "2019-02-15"


def _recast_revenues(tag, row, factor=0.95):
    if tag != "Revenues" or row["filed"] < TEN_K_2018 or row["end"] < "2017-01-01":
        return row
    return {**row, "val": row["val"] * factor}


def _notes(series):
    return [n for n in series.notes if n.code == "series_mixes_vintages"]


def _note(series):
    notes = _notes(series)
    assert len(notes) == 1
    return notes[0]


def test_the_recast_is_found_and_dated_by_its_filing(make_company):
    conn = make_company(_recast_revenues)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    recasts = item_recasts(conn, cik, "revenue", AS_OF)
    first = recasts[0]
    assert (first.form, first.filed_at.isoformat()) == ("10-K", TEN_K_2018)
    years = [(s, e) for s, e, _o, _n in first.periods if (e - s).days > 300]
    assert years == [(date(2017, 1, 1), date(2017, 12, 31))]
    assert first.largest_move(300) == pytest.approx(-0.05)
    # the 2019 10-Qs recast the 2018 comparative quarters, each on its own filing
    assert {r.form for r in recasts[1:]} == {"10-Q"}


def test_years_across_the_recast_say_which_kept_the_old_figures(make_company):
    conn = make_company(_recast_revenues)
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018"], AS_OF)
    note = _note(s)
    assert note.params == {
        "item": "revenue",
        "recast_on": TEN_K_2018,
        "form": "10-K",
        "accession_no": note.params["accession_no"],
        "largest_move": pytest.approx(-0.05),
        "largest_move_on": "year",
        "moved_periods": ["FY2017"],
        "before_periods": ["FY2015"],
        "after_periods": ["FY2016", "FY2017", "FY2018"],
        "mixed_periods": [],
        "ratios": REVENUE_RATIOS,
    }
    assert "the 10-K filed 2019-02-15 lowered revenue figures already reported" in note.text
    assert "(by up to 5.0%), including FY2017" in note.text
    assert (
        "FY2015 keeps figures filed before it, with no later version in the filings' tagged data"
        in note.text
    )
    assert "may not be like for like" in note.text
    assert "Warren does not know why" in note.text and "the 10-K explains it" in note.text
    assert json.loads(json.dumps(s.to_dict()))["notes"][0]["code"] == "series_mixes_vintages"


@pytest.mark.parametrize(
    "periods",
    [
        ["FY2016", "FY2017", "FY2018", "FY2019"],  # all filed again on or after the recast
        ["FY2014", "FY2015"],  # all before it
    ],
)
def test_a_series_on_one_side_has_no_note(make_company, periods):
    conn = make_company(_recast_revenues)
    assert _notes(reported_series(conn, "TST", periods, AS_OF)) == []


def test_the_note_waits_for_the_recast_to_be_public(make_company):
    conn = make_company(_recast_revenues)
    years = ["FY2015", "FY2016", "FY2017"]
    assert _notes(reported_series(conn, "TST", years, date(2019, 2, 14))) == []
    assert _note(reported_series(conn, "TST", years, date(2019, 2, 15))) is not None


def test_a_move_within_the_threshold_is_not_a_recast(make_company):
    conn = make_company(lambda tag, row: _recast_revenues(tag, row, 1 - RECAST_MOVE / 2))
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018"], AS_OF)
    assert _notes(s) == []


def test_a_tag_that_changed_meaning_is_not_a_recast(make_company):
    """The old figures stay under another tag: the meaning note's case, not this one."""
    conn = make_company(_redefine_revenues)
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018", "FY2019"], AS_OF)
    assert _notes(s) == []
    assert [n.code for n in s.notes] == ["series_mixes_meanings"]


def test_a_company_without_a_recast_has_no_note(company):
    s = reported_series(company, "TST", ["FY2014", "FY2015", "FY2016", "FY2017"], AS_OF)
    assert s.notes == []


def test_quarters_name_before_and_after(make_company):
    """Against the 10-K of 2019-02-15: Q1 2017 was last filed in the Q1 2018 10-Q (before); Q4
    2017 on one basis is the 2017 year as first filed less three quarters filed with it (#264),
    so before too; Q1 2018 was filed again in the Q1 2019 10-Q (after). The Q1 2019 10-Q's own
    recast of Q1 2018 splits the series the same way and is not listed again."""
    conn = make_company(_recast_revenues)
    s = reported_series(conn, "TST", ["FY2017Q1", "FY2017Q4", "FY2018Q1"], AS_OF)
    note = _note(s)
    assert (note.params["form"], note.params["recast_on"]) == ("10-K", TEN_K_2018)
    assert note.params["before_periods"] == ["FY2017Q1", "FY2017Q4"]
    assert note.params["after_periods"] == ["FY2018Q1"]
    assert note.params["mixed_periods"] == []
    assert s.periods[1].line("revenue").one_basis


def _quarter(inputs, derived=True):
    return Fact(
        canonical_name="revenue",
        xbrl_concept="us-gaap:Revenues",
        period_start=date(2017, 10, 1),
        period_end=date(2017, 12, 31),
        value=1.0,
        unit="USD",
        filed_at=date(2019, 2, 15),
        derived=derived,
        inputs=inputs,
    )


@pytest.mark.parametrize(
    ("inputs", "side"),
    [(["a", "b"], "mixed"), (["b"], "after"), (["a"], "before")],
)
def test_a_derived_quarter_sits_where_its_inputs_were_filed(inputs, side):
    recast = Recast("revenue", "b", "10-K", date(2019, 2, 15), [])
    filed_at = {"a": date(2018, 2, 15), "b": date(2019, 2, 15)}
    assert side_of_recast(_quarter(inputs), recast, {}, filed_at) == side


def _reported(start, end):
    return Fact(
        canonical_name="revenue",
        xbrl_concept="us-gaap:Revenues",
        period_start=start,
        period_end=end,
        value=1.0,
        unit="USD",
        filed_at=date(2019, 7, 25),
    )


@pytest.mark.parametrize(
    ("filed", "side"),
    [
        # first filed before the recast, filed again (unchanged) in a later filing: presented
        # beside recast figures, so presumed on the new basis (ASC 250-10-45-5, backlog #331)
        ([date(2019, 7, 25), date(2020, 7, 23)], "after"),
        # filed again unchanged in the recast's own filing
        ([date(2019, 7, 25), date(2019, 10, 24)], "after"),
        # never filed again
        ([date(2019, 7, 25)], "before"),
    ],
)
def test_a_period_filed_again_unchanged_sits_after_the_recast(filed, side):
    """Coca-Cola's shape: Q2 2019 is first filed in July 2019, before the 10-Q of 2019-10-24
    recast the 2018 comparative quarters, and filed again unchanged a year later."""
    q2 = (date(2019, 4, 1), date(2019, 6, 28))
    recast = Recast("revenue", "b", "10-Q", date(2019, 10, 24), [])
    versions = {(*q2, "us-gaap:Revenues"): filed}
    assert side_of_recast(_reported(*q2), recast, versions, {}) == side


@pytest.mark.parametrize(
    ("mixed", "words"),
    [
        (["FY2017Q4"], "FY2017Q4 is worked out"),
        (["FY2017Q3", "FY2017Q4"], "FY2017Q4 are worked out"),
    ],
)
def test_the_mixed_clause_has_its_verb(mixed, words):
    recast = Recast("revenue", "b", "10-K", date(2019, 2, 15), [])
    side = {"FY2017Q1": "before", **dict.fromkeys(mixed, "mixed"), "FY2018Q1": "after"}
    note = _recast_note(recast, side, [], [], -0.05)
    assert f"{words} from figures on both sides" in note.text


def test_both_notes_when_a_series_crosses_a_recast_and_a_change_of_meaning(make_company):
    def both(tag, row):
        out = _recast_revenues(tag, row)
        return _redefine_revenues(tag, out)

    conn = make_company(both)
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018", "FY2019"], AS_OF)
    assert [n.code for n in s.notes] == ["series_mixes_meanings", "series_mixes_vintages"]


def test_a_recast_up_says_raised(make_company):
    conn = make_company(lambda tag, row: _recast_revenues(tag, row, 1.05))
    note = _note(reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017"], AS_OF))
    assert note.params["largest_move"] == pytest.approx(0.05)
    assert "raised revenue figures already reported (by up to 5.0%)" in note.text


def _lower_tag_in_the_10k(tag, row):
    """The 10-K of 2019-02-15 gives FY2016 only under the lower-ranked `SalesRevenueNet`, 5%
    lower (Walmart's 10-Ks tag quarters as net sales, its 10-Qs as total revenues): the figure
    shown stays the `Revenues` one, so nothing a reader sees moved."""
    if tag == "Revenues" and row["filed"] == TEN_K_2018 and row["end"] == "2016-12-31":
        return [("SalesRevenueNet", {**row, "val": row["val"] * 0.95})]
    return row


def test_a_filing_under_a_lower_ranked_tag_is_not_a_recast_of_the_figure_shown(make_company):
    conn = make_company(_lower_tag_in_the_10k)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    assert item_recasts(conn, cik, "revenue", AS_OF) == []
    s = reported_series(conn, "TST", ["FY2014", "FY2015", "FY2016", "FY2017"], AS_OF)
    assert s.periods[2].line("revenue").latest.xbrl_concept == "us-gaap:Revenues"
    assert _notes(s) == []


# -- backlog #325: the figure a filing is compared with, and a quarter series' own moves -------

TEN_K_2019 = "2020-02-15"  # the FY2019 10-K, the next to file FY2017 after TEN_K_2018


def _fy2017_via_lower_tag(factor_2019):
    """FY2017 is filed under `Revenues` in the FY2017 10-K, only under the lower-ranked
    `SalesRevenueNet` 5% lower in the FY2018 10-K, and under `Revenues` times `factor_2019` in
    the FY2019 10-K. `latest` mode shows `Revenues` throughout."""

    def edit(tag, row):
        if tag != "Revenues" or row["end"] != "2017-12-31" or row["start"] != "2017-01-01":
            return row
        if row["filed"] == TEN_K_2018:
            return [("SalesRevenueNet", {**row, "val": row["val"] * 0.95})]
        if row["filed"] == TEN_K_2019:
            return {**row, "val": row["val"] * factor_2019}
        return row

    return edit


def _fy2017_recasts(conn):
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    return [
        r
        for r in item_recasts(conn, cik, "revenue", AS_OF)
        if any((e - s).days > 300 and e == date(2017, 12, 31) for s, e, _o, _n in r.periods)
    ]


def test_a_filing_back_on_the_shown_tag_is_compared_with_the_figure_shown(make_company):
    """A on `Revenues`, B on a lower tag only, C on `Revenues` unchanged: the figure a reader
    saw never moved, so C is not a recast (it was compared with B's 95 before #325)."""
    conn = make_company(_fy2017_via_lower_tag(1.0))
    assert _fy2017_recasts(conn) == []
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018"], AS_OF)
    assert _notes(s) == []


def test_a_recast_matching_a_lower_tag_figure_is_still_found(make_company):
    """C lowers `Revenues` by 5%, to B's lower-tag figure: a recast of the figure shown, found
    against A's figure (missed before #325, when C was compared with B)."""
    conn = make_company(_fy2017_via_lower_tag(0.95))
    [recast] = _fy2017_recasts(conn)
    assert (recast.form, recast.filed_at.isoformat()) == ("10-K", TEN_K_2019)
    assert recast.largest_move(300) == pytest.approx(-0.05)


def test_a_switch_onto_the_shown_tag_still_counts(make_company):
    """Earlier filings give FY2016 only under the lower tag, the FY2018 10-K first under
    `Revenues` 5% lower (the shape of the real tag switches: Microsoft FY2016 and FY2017):
    compared with the only figure a reader had, it is a recast."""

    def edit(tag, row):
        if tag != "Revenues" or row["end"] != "2016-12-31" or row["start"] != "2016-01-01":
            return row
        if row["filed"] < TEN_K_2018:
            return [("SalesRevenueNet", row)]
        return {**row, "val": row["val"] * 0.95}

    conn = make_company(edit)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    [recast] = item_recasts(conn, cik, "revenue", AS_OF)
    assert (recast.form, recast.filed_at.isoformat()) == ("10-K", TEN_K_2018)
    assert recast.largest_move(300) == pytest.approx(-0.05)


def _years_only(tag, row):
    """From the FY2018 10-K, every filing gives the years ending in 2017 or later 5% lower;
    no quarter moves (a 10-K that recast only its years)."""
    year = (
        tag == "Revenues"
        and (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days > 300
    )
    if tag != "Revenues" or row["filed"] < TEN_K_2018 or row["end"] < "2017-01-01" or not year:
        return row
    return {**row, "val": row["val"] * 0.95}


def test_a_10k_that_moved_only_years_marks_a_quarter_series_with_the_year_s_move(make_company):
    """A restated year restates its quarters even when no quarter is tagged (Apple's 10-K/A of
    2010-01-25, analyst, design review): the quarter series keeps the 10-K's note, and its move
    is said to be on a full year."""
    conn = make_company(_years_only)
    years = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017", "FY2018"], AS_OF)
    assert _note(years).params["largest_move_on"] == "year"
    assert "(by up to 5.0%), including FY2017" in _note(years).text
    s = reported_series(conn, "TST", ["FY2017Q1", "FY2017Q4", "FY2018Q1"], AS_OF)
    note = _note(s)
    assert (note.params["form"], note.params["recast_on"]) == ("10-K", TEN_K_2018)
    assert note.params["largest_move"] == pytest.approx(-0.05)
    assert note.params["largest_move_on"] == "year"
    assert "(by up to 5.0% on a full year; it moved no tagged quarter)" in note.text


def test_a_quarter_series_gives_a_quarter_move(make_company):
    """The 10-K moves the years by 5%, the 10-Qs the quarters by 3%: the note on a quarter
    series gives the 10-Q's quarter move, never the year's (backlog #325)."""

    def edit(tag, row):
        out = _years_only(tag, row)
        if out is not row:
            return out
        return _recast_revenues(tag, row, 0.97)

    conn = make_company(edit)
    s = reported_series(conn, "TST", ["FY2017Q1", "FY2017Q4", "FY2018Q1"], AS_OF)
    note = _note(s)
    assert note.params["recast_on"] == TEN_K_2018
    notes = _notes(reported_series(conn, "TST", ["FY2018Q1", "FY2018Q2", "FY2019Q1"], AS_OF))
    assert notes and {n.params["form"] for n in notes} == {"10-Q"}
    assert {n.params["largest_move_on"] for n in notes} == {"quarter"}
    assert [n.params["largest_move"] for n in notes] == pytest.approx([-0.03] * len(notes))


H1_2018 = revenue(2018, 1) + revenue(2018, 2)


def _half_year_only(tag, row):
    """The Q2 10-Qs also tag the six months to June 2018; the 2019 one gives it 5% lower while
    leaving the 2018 quarters as they were (Johnson & Johnson's 10-Q of 2024-07-25 and P&G's of
    2013-01-25 moved only a half year, analyst, design review)."""
    if tag != "Revenues" or row["end"] != "2018-06-30":
        return row
    factor = 0.95 if row["filed"] > "2019-01-01" else 1.0
    half = {**row, "start": "2018-01-01", "val": H1_2018 * factor}
    return [(tag, row), (tag, half)]


def test_a_filing_that_moved_only_a_half_year_gives_no_note(make_company):
    conn = make_company(_half_year_only)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    [recast] = item_recasts(conn, cik, "revenue", AS_OF)
    assert (recast.form, recast.largest_move(*QUARTER_SPAN)) == ("10-Q", None)
    for periods in (["FY2018Q1", "FY2018Q2", "FY2019Q1"], ["FY2016", "FY2017", "FY2018"]):
        assert _notes(reported_series(conn, "TST", periods, AS_OF)) == []


@pytest.mark.parametrize(
    ("spans", "expected"),
    [
        ([365], None),  # a year only
        ([273, 365], None),  # nine months and a year
        ([98, 365], -0.10),  # a 14-week quarter (53-week year) counts
        ([79, 365], None),
        ([101], None),
    ],
)
def test_largest_move_within_a_span(spans, expected):
    periods = [
        (date(2017, 1, 1), date(2017, 1, 1) + timedelta(days=d), 100.0, 90.0 if d < 300 else 95.0)
        for d in spans
    ]
    move = Recast("revenue", "a", "10-K", date(2019, 2, 15), periods).largest_move(80, 100)
    assert move == (pytest.approx(expected) if expected is not None else None)
