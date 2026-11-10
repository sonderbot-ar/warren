"""A series of periods across a tag that changed meaning (backlog #297 item 2), on Test Corp
(tests/analysis/conftest.py) with `Revenues` 4% higher from its Q3 2019 10-Q (filed
2019-10-30), the old figures kept under the contract-revenue tag (`_redefine_revenues`). Its
FY2019 10-K refiles 2017 and 2018 on the new meaning, so FY2016 is the last year on the old one."""

import json
from datetime import date

import pytest

from domains.analysis import __main__ as cli
from domains.analysis.reported import (
    SERIES_MAX_PERIODS,
    ReportedError,
    reported_period,
    reported_series,
)
from tests.analysis.conftest import AS_OF
from tests.analysis.test_reported import CONTRACT, _redefine_revenues

# the ratios computed on revenue; Test Corp files no cost of revenue, so its gross margin is a
# coded gap with no `uses` and is not listed
REVENUE_RATIOS = [
    "capex_share",
    "da_share",
    "net_margin",
    "operating_margin",
    "revenue_growth_yoy",
]


def _note(series):
    notes = [n for n in series.notes if n.code == "series_mixes_meanings"]
    assert len(notes) <= 1
    return notes[0] if notes else None


def test_years_across_the_change_say_where_the_break_is(make_company):
    conn = make_company(_redefine_revenues)
    s = reported_series(conn, "TST", ["FY2016", "FY2017", "FY2018", "FY2019"], AS_OF)
    note = _note(s)
    assert note.params == {
        "item": "revenue",
        "tag": "us-gaap:Revenues",
        "other_tag": f"us-gaap:{CONTRACT}",
        "changed_on": "2019-10-30",
        "form": "10-Q",
        "accession_no": note.params["accession_no"],
        "old_periods": ["FY2016"],
        "new_periods": ["FY2017", "FY2018", "FY2019"],
        "mixed_periods": [],
        "other_tag_periods": [],
        "ratios": REVENUE_RATIOS,
    }
    assert "FY2016 carry the tag's earlier meaning" in note.text
    assert "FY2017, FY2018 and FY2019 the meaning the 10-Q filed 2019-10-30" in note.text
    assert (
        f"earlier meaning, under us-gaap:{CONTRACT}" in note.text
        and "not like for like" in note.text
    )
    assert "nothing about other changes within either side" in note.text


@pytest.mark.parametrize(
    "periods", [["FY2017", "FY2018", "FY2019"], ["FY2016"], ["FY2019Q3", "FY2020Q1"]]
)
def test_a_series_on_one_meaning_has_no_note(make_company, periods):
    conn = make_company(_redefine_revenues)
    assert reported_series(conn, "TST", periods, AS_OF).notes == []


def test_a_company_without_a_change_has_no_note(company):
    s = reported_series(company, "TST", ["FY2016", "FY2017", "FY2018", "FY2019"], AS_OF)
    assert s.notes == []


def test_periods_come_back_in_time_order_each_as_reported_period_gives_it(make_company):
    conn = make_company(_redefine_revenues)
    s = reported_series(conn, "TST", ["FY2019", "FY2016", "latest-year"][:2], AS_OF)
    assert [r.period for r in s.periods] == ["FY2016", "FY2019"]
    for r in s.periods:
        assert r == reported_period(conn, "TST", r.period, AS_OF)
    assert (s.ticker, s.as_of) == ("TST", AS_OF)


def test_quarters_name_old_new_and_mixed(make_company):
    """Q1 and Q2 2018 were never refiled (old); Q3 2018 was refiled in the Q3 2019 10-Q (new);
    Q4 2018 is the new 2018 year less old and new quarters (mixed); Q1 2019 was refiled in the
    Q1 2020 10-Q (new); Q2 2019 never was (old)."""
    conn = make_company(_redefine_revenues)
    asked = ["FY2018Q1", "FY2018Q2", "FY2018Q3", "FY2018Q4", "FY2019Q1", "FY2019Q2"]
    note = _note(reported_series(conn, "TST", asked, AS_OF))
    assert note.params["old_periods"] == ["FY2018Q1", "FY2018Q2", "FY2019Q2"]
    assert note.params["new_periods"] == ["FY2018Q3", "FY2019Q1"]
    assert note.params["mixed_periods"] == ["FY2018Q4"]
    assert "FY2018Q4 a mix of both" in note.text


def test_a_lone_mixed_quarter_is_noted(make_company):
    conn = make_company(_redefine_revenues)
    note = _note(reported_series(conn, "TST", ["FY2018Q4"], AS_OF))
    assert note.params["mixed_periods"] == ["FY2018Q4"]
    assert note.params["old_periods"] == note.params["new_periods"] == []


def test_the_note_waits_for_the_change_to_be_public(make_company):
    """On 2019-12-31 the FY2019 10-K has not been filed: only the Q3 2019 10-Q shows the change,
    and it refiles only Q3 2018, so the years are all on the old meaning."""
    conn = make_company(_redefine_revenues)
    years = ["FY2016", "FY2017", "FY2018"]
    assert reported_series(conn, "TST", years, date(2019, 12, 31)).notes == []
    assert _note(reported_series(conn, "TST", years, AS_OF)) is not None


@pytest.mark.parametrize(
    ("periods", "words"),
    [
        ([], "at least one period"),
        ([f"FY{y}Q1" for y in range(2000, 2000 + SERIES_MAX_PERIODS + 1)], "at most"),
        (["FY2018", "FY2018"], "asked twice: FY2018"),
        (["FY2019", "latest-year"], "asked twice: FY2019"),
        (["FY2018", "FY2018Q1"], "not both"),
    ],
)
def test_a_list_that_is_not_a_series_is_refused(company, periods, words):
    with pytest.raises(ReportedError, match=words):
        reported_series(company, "TST", periods, AS_OF)


def test_to_dict_is_plain_json(make_company):
    conn = make_company(_redefine_revenues)
    data = reported_series(conn, "TST", ["FY2016", "FY2017"], AS_OF).to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["as_of"] == AS_OF.isoformat()
    assert [p["period"] for p in data["periods"]] == ["FY2016", "FY2017"]
    assert data["notes"][0]["code"] == "series_mixes_meanings"


def _sales_tag_until_2017(tag, row):
    """Test Corp files its revenue as `SalesRevenueNet` in filings before 2019, then as
    `_redefine_revenues` does: FY2015's latest figure is under a tag the change never touched."""
    if tag == "Revenues" and row["filed"] < "2019-01-01":
        return [("SalesRevenueNet", row)]
    return _redefine_revenues(tag, row)


def test_a_period_under_another_tag_is_not_called_the_earlier_meaning(make_company):
    conn = make_company(_sales_tag_until_2017)
    s = reported_series(conn, "TST", ["FY2015", "FY2016", "FY2017"], AS_OF)
    assert s.periods[0].line("revenue").latest.xbrl_concept == "us-gaap:SalesRevenueNet"
    note = _note(s)
    assert note.params["other_tag_periods"] == ["FY2015"]
    assert (note.params["old_periods"], note.params["new_periods"]) == (["FY2016"], ["FY2017"])
    assert "FY2015 another tag, of unknown meaning" in note.text


def test_old_and_other_tags_without_the_new_meaning_have_no_note(make_company):
    conn = make_company(_sales_tag_until_2017)
    assert reported_series(conn, "TST", ["FY2015", "FY2016"], AS_OF).notes == []


def _cli(conn, monkeypatch, capsys, *args):
    class Same:
        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "get_db_connection", lambda: Same())
    code = cli.main(["series", "--ticker", "TST", "--as-of", AS_OF.isoformat(), *args])
    return code, capsys.readouterr().out


def test_cli_text_names_the_break_and_json_is_the_call(make_company, monkeypatch, capsys):
    conn = make_company(_redefine_revenues)
    years = ["--period", "FY2016", "--period", "FY2017"]
    code, out = _cli(conn, monkeypatch, capsys, *years)
    assert code == 0
    assert "FY2016" in out and "FY2017" in out and "20.0%" in out
    assert "NOTE: revenue in this series is us-gaap:Revenues" in out
    code, out = _cli(conn, monkeypatch, capsys, *years, "--json")
    assert code == 0
    expected = reported_series(conn, "TST", ["FY2016", "FY2017"], AS_OF).to_dict()
    assert json.loads(out) == json.loads(json.dumps(expected))


def test_cli_refuses_a_list_that_is_not_a_series(company, monkeypatch, capsys):
    code, out = _cli(company, monkeypatch, capsys, "--period", "FY2018", "--period", "FY2018Q1")
    assert code == 1
    assert "FAILED: a series is all fiscal years or all quarters" in out
