"""The inputs behind an answer (backlog #471): each reached row with its history."""

import json
from contextlib import contextmanager

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis import __main__ as cli
from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis import sources as src
from domains.analysis.inputs import InputsError, inputs_behind, reached_rows
from domains.analysis.reported import reported_period
from domains.analysis.runs import load_assumptions, run_baseline
from domains.analysis.schemas import SINGLE
from tests.analysis.conftest import AS_OF, CHOICES, revenue


@pytest.fixture
def run(company):
    return company, run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _q5(conn, run_id):
    """The revenue of the first four forecast quarters (brief Q5)."""
    rows = load_assumptions(conn, run_id)
    _seed, periods = dcf.forecast_periods(dcf.index_rows(rows))
    return [("revenue", p) for p in periods[:4]]


def _cell(answer, name):
    return next(c for c in answer.cells if c.name == name)


def test_a_q5_answer_reaches_the_seed_and_growth_only(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, _q5(conn, run_id))
    assert [c.name for c in answer.cells] == [dcf.SEED, "revenue_growth"]
    assert [o["name"] for o in answer.outputs] == ["revenue"] * 4
    assert all(o["value"] > 0 for o in answer.outputs)  # the forecast values, from the run


def test_the_cells_are_the_rows_sources_reaches_gives(run):
    conn, run_id = run
    trace = src.output_trace(load_assumptions(conn, run_id))
    key = ("value_per_share", SINGLE)
    assert set(reached_rows(trace, [key])) == src.reaches(trace, key)
    answer = inputs_behind(conn, run_id, [key])
    assert {c.name for c in answer.cells} == {n for n, _p in src.reaches(trace, key)}
    gaps = {c.name: c.gap.code for c in answer.cells if c.gap}
    assert gaps["risk_free"] == "history_not_built"
    assert gaps["shares"] == "history_not_built"
    assert gaps["terminal_method"] == "owner_choice"
    for name in dcf.DRIVERS:
        assert _cell(answer, name).gap is None and _cell(answer, name).history


def test_used_is_read_from_the_stored_sources(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    years = ["FY2017", "FY2018", "FY2019"]
    growth = _cell(answer, "revenue_growth")
    assert {r.method_code for r in growth.rows} == {"same_filing_average_fading"}
    assert all(r.used == years for r in growth.rows)
    for name in ("da_pct", "capex_pct", "nwc_pct", "tax_rate"):
        assert all(r.used == years for r in _cell(answer, name).rows), name
    margin = _cell(answer, "operating_margin")
    q2 = next(r for r in margin.rows if r.period == "FY2020Q2")
    assert q2.method_code == "same_quarter_average"
    assert q2.used == ["FY2017Q2", "FY2018Q2", "FY2019Q2"]
    y3 = next(r for r in margin.rows if r.period == "Y3")
    assert y3.method_code == "years_sum_ratio" and y3.used == years
    seed = _cell(answer, dcf.SEED)
    assert all(r.used == [r.period] for r in seed.rows)


def test_every_point_is_the_reported_figure_on_the_run_date(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    margin = _cell(answer, "operating_margin")
    for series in margin.history:
        for p in series.points:
            if p.value is None:
                continue
            want = reported_period(conn, "TST", p.period, AS_OF).ratio("operating_margin").value
            assert p.value == want
            assert p.value == pytest.approx(0.2)
    seed = _cell(answer, dcf.SEED)
    q1 = next(s for s in seed.history if s.fiscal_quarter == 1)
    assert [p.period for p in q1.points] == [f"FY{y}Q1" for y in range(2016, 2021)]
    assert [p.value for p in q1.points] == pytest.approx([revenue(y, 1) for y in range(2016, 2021)])
    assert [p.used for p in q1.points] == [False] * 4 + [True]
    assert q1.points[-1].parts[0].filing["accession_no"]


def test_the_measures_match_the_assumptions(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    growth = _cell(answer, "revenue_growth")
    same, latest, quarterly = growth.history
    assert (same.basis, same.frequency, same.primary) == ("same_filing", "year", True)
    assert (latest.basis, latest.frequency, latest.primary) == ("latest", "year", False)
    assert (quarterly.basis, quarterly.frequency) == ("latest", "quarter")
    used = [p for p in same.points if p.used]
    assert [p.period for p in used] == ["FY2017", "FY2018", "FY2019"]
    first = next(r for r in growth.rows if r.period == "FY2020Q2")
    assert sum(p.value for p in used) / 3 == pytest.approx(first.value)
    tax = _cell(answer, "tax_rate").history[0]
    assert tax.measure == "effective_tax_rate"
    assert all(p.value == pytest.approx(0.25) for p in tax.points if p.value is not None)
    nwc = _cell(answer, "nwc_pct")
    row = nwc.rows[0]
    points = [p for p in nwc.history[0].points if p.used]
    assert sum(p.value for p in points) / len(points) == pytest.approx(row.value, abs=1e-12)
    assert not any(n.code == "run_read_differently" for p in points for n in p.notes)


def test_contributions_add_up_to_the_years_growth(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    latest = _cell(answer, "revenue_growth").history[1]
    year = next(p for p in latest.points if p.period == "FY2019")
    shares = [q.contribution for q in year.parts if q.name == "revenue_quarter_contribution"]
    assert len(shares) == 4
    assert sum(shares) == pytest.approx(year.value) == pytest.approx(0.1)
    assert not any(n.code == "quarters_do_not_sum" for n in year.notes)


def test_a_year_not_yet_filed_is_a_coded_gap(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    same = _cell(answer, "revenue_growth").history[0]
    last = same.points[-1]
    assert last.period == "FY2020"  # the latest quarter's year, filed only as a 10-Q
    assert last.value is None and last.missing.code == "period_not_reported"


def test_years_sets_the_window_and_is_bounded(run):
    conn, run_id = run
    for years in (3, 5, 10):
        answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)], years=years)
        da = _cell(answer, "da_pct").history[0]
        labels = [p.period for p in da.points]
        assert labels[-1] == "FY2020"
        # the used years are always shown: at 3 years FY2018-FY2020 plus FY2017, which is used
        assert len(labels) == max(years, 4)
        assert {"FY2017", "FY2018", "FY2019"} <= set(labels)
        quarterly = _cell(answer, "revenue_growth").history[2]
        assert len(quarterly.points) == years * 4
    for years in (2, 11):
        with pytest.raises(InputsError) as e:
            inputs_behind(conn, run_id, [("value_per_share", SINGLE)], years=years)
        assert e.value.code == "years_out_of_range"


def test_unknown_outputs_and_runs_are_refused(run):
    conn, run_id = run
    with pytest.raises(InputsError) as e:
        inputs_behind(conn, run_id, [("revenue", "FY1999Q1")])
    assert e.value.code == "output_not_in_run"
    with pytest.raises(InputsError) as e:
        inputs_behind(conn, "NOPE_1", [("value_per_share", SINGLE)])
    assert e.value.code == "run_not_found"


def test_a_figure_filed_after_the_run_date_is_never_read(make_company):
    late = "0000000123-99-999999"

    def restate_late(tag, row):
        if tag == "Revenues" and row["end"] == "2019-03-31" and row["form"] == "10-Q":
            return [(tag, row), (tag, {**row, "val": row["val"] * 2, "accn": late,
                                       "filed": "2020-08-01"})]  # fmt: skip
        return row

    conn = make_company(restate_late)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    accessions = {
        q.filing["accession_no"]
        for c in answer.cells
        for s in c.history
        for p in s.points
        for q in p.parts
        if q.filing
    }
    assert late not in accessions
    seed = _cell(answer, dcf.SEED)
    q1 = next(s for s in seed.history if s.fiscal_quarter == 1)
    assert next(p for p in q1.points if p.period == "FY2019Q1").value == pytest.approx(
        revenue(2019, 1)
    )


def test_a_run_that_read_a_figure_differently_says_so(run):
    conn, run_id = run
    conn.execute(
        "UPDATE assumptions SET value = value * 1.5 WHERE run_id = ? AND name = 'history:nwc' "
        "AND period = 'FY2018'",
        (run_id,),
    )
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    point = next(p for p in _cell(answer, "nwc_pct").history[0].points if p.period == "FY2018")
    (note,) = [n for n in point.notes if n.code == "run_read_differently"]
    assert note.params["run_value"] == pytest.approx(1.5 * point.value)


def test_the_command_prints_json_and_text(run, capsys, monkeypatch):
    conn, run_id = run

    @contextmanager
    def same_connection(*args):
        yield conn

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    outputs = sum((["--output", f"revenue:{p}"] for _n, p in _q5(conn, run_id)), [])
    assert cli.main(["inputs", "--run-id", run_id, *outputs, "--years", "3", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in data["cells"]] == [dcf.SEED, "revenue_growth"]
    assert cli.main(["inputs", "--run-id", run_id, "--output", "value_per_share"]) == 0
    text = capsys.readouterr().out
    assert "nwc_pct [year_end_average_ratio]" in text and "history_not_built" in text
    assert cli.main(["inputs", "--run-id", run_id, "--output", "nope:X"]) == 1
    assert "output_not_in_run" in capsys.readouterr().out


@given(
    st.lists(st.floats(min_value=1.0, max_value=1e6), min_size=4, max_size=4),
    st.lists(st.floats(min_value=1.0, max_value=1e6), min_size=4, max_size=4),
)
def test_quarter_contributions_sum_to_growth_when_quarters_sum_to_the_year(now, before):
    total_now, total_before = sum(now), sum(before)
    shares = [fm.growth_contribution(a, b, total_before) for a, b in zip(now, before, strict=True)]
    assert sum(shares) == pytest.approx(fm.growth(total_now, total_before), abs=1e-9)


def test_a_contribution_needs_a_positive_prior_total():
    with pytest.raises(fm.FinancialMathError):
        fm.growth_contribution(1.0, 1.0, 0.0)


def test_same_filing_and_latest_growth_differ_after_a_restatement(make_company):
    def restate_2018(tag, row):  # the FY2019 10-K restates FY2018's revenue up 10%
        if tag == "Revenues" and row["form"] == "10-K" and row["fy"] == 2019:
            if row["end"] == "2018-12-31":
                return {**row, "val": row["val"] * 1.1}
        return row

    conn = make_company(restate_2018)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    same, latest, _quarterly = _cell(answer, "revenue_growth").history
    by = {s.basis: {p.period: p for p in s.points} for s in (same, latest)}
    # FY2018 as its own 10-K filed it grew 10%; on the restated year it grew 21%
    assert by["same_filing"]["FY2018"].value == pytest.approx(0.1)
    assert by["latest"]["FY2018"].value == pytest.approx(0.21)
    # the restated year no longer equals its four quarters: the quarters' bars say by how much
    point = by["latest"]["FY2018"]
    (note,) = [n for n in point.notes if n.code == "quarters_do_not_sum"]
    residual = next(q for q in point.parts if q.name == "not_in_quarters")
    shares = [q.contribution for q in point.parts if q.contribution is not None]
    assert sum(shares) == pytest.approx(point.value)
    assert residual.contribution == pytest.approx(point.value - note.params["sum_of_contributions"])


def test_a_longer_year_carries_the_length_note(make_company):
    def long_2018(tag, row):  # FY2018 runs 53 weeks: it starts a week early
        if row.get("start") == "2018-01-01" and row["end"] == "2018-12-31":
            return {**row, "start": "2017-12-25"}
        return row

    conn = make_company(long_2018)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = inputs_behind(conn, run_id, [("value_per_share", SINGLE)])
    same = _cell(answer, "revenue_growth").history[0]
    noted = {
        p.period for p in same.points if any(n.code == "period_length_differs" for n in p.notes)
    }
    assert noted == {"FY2018", "FY2019"}
