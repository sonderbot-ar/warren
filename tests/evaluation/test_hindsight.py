"""A run's forecast against what was reported afterwards (backlog #128), on Test Corp: revenue
grows exactly 10% a year at a 20% margin, so the baseline's misses are zero unless a filing is
edited, and every miss must equal the M3 harness's score of the same quarter."""

import json
from datetime import date

import pytest

from domains.analysis.runs import run_baseline
from domains.evaluation import hindsight as HS
from domains.evaluation.harness import evaluate_case
from domains.evaluation.hindsight import FactReads, against_actuals
from tests.evaluation.conftest import CHOICES
from tests.evaluation.test_harness import TODAY, case

AS_OF = date(2019, 6, 30)


def run(conn):
    return run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=TODAY)


def items(h, period):
    (q,) = [q for q in h.quarters if q.period == period]
    return q, {i.name: i for i in q.items}


def test_reported_quarters_have_actuals_filings_and_zero_misses(company):
    h = against_actuals(company, run(company), TODAY)
    assert [q.period for q in h.quarters][:5] == [
        "FY2019Q2", "FY2019Q3", "FY2019Q4", "FY2020Q1", "FY2020Q2",
    ]  # fmt: skip
    assert [q.horizon for q in h.quarters] == list(range(1, len(h.quarters) + 1))
    assert [q.reported for q in h.quarters[:5]] == [True, True, True, True, False]
    q, it = items(h, "FY2019Q3")
    assert q.period_end == date(2019, 9, 30) and q.days == 92 and q.fiscal_period == "Q3"
    assert it["revenue"].actual == pytest.approx(100 * 1.1**4 * 1.0)
    assert it["ebit"].actual == pytest.approx(0.2 * it["revenue"].actual)
    assert it["revenue"].miss == pytest.approx(0, abs=1e-9)
    assert it["revenue"].miss_unit == "fraction_of_actual"
    assert it["ebit"].miss_unit == "fraction_of_actual_revenue"
    assert it["revenue"].unit == "USD"
    (filing,) = it["revenue"].filings
    assert filing.form == "10-Q" and filing.filed_at == date(2019, 10, 30)
    assert filing.url.startswith("https://www.sec.gov/Archives/edgar/data/123/")


def test_a_derived_q4_lists_the_filings_it_came_from(company):
    _, it = items(against_actuals(company, run(company), TODAY), "FY2019Q4")
    assert it["revenue"].derived and it["revenue"].miss == pytest.approx(0, abs=1e-9)
    assert {f.form for f in it["revenue"].filings} == {"10-K", "10-Q"}


def test_quarters_not_filed_by_the_date_are_coded_not_zero(company):
    h = against_actuals(company, run(company), date(2020, 4, 29))  # the Q1 10-Q came on 04-30
    q, it = items(h, "FY2020Q1")
    assert not q.reported and q.period_end is None and q.days is None
    for i in it.values():
        assert i.actual is None and i.miss is None and i.signed_miss is None
        assert i.missing.code == "not_reported"
        assert i.missing.params["actuals_on"] == "2020-04-29"
    assert "not yet in a 10-Q or 10-K by 2020-04-29" in it["revenue"].missing.text


def test_a_miss_equals_the_harness_score_of_the_same_quarter(make_company):
    def beat(tag, row):
        # the Q3 2019 10-Q reports that quarter's revenue 5% above the trend; prior year as known
        if tag == "Revenues" and row["end"] == "2019-09-30" and row["fp"] == "Q3":
            row = row | {"val": row["val"] * 1.05}
        return row

    conn = make_company(beat)
    run_id, rows = evaluate_case(conn, case(), CHOICES, actuals_as_of=TODAY, today=TODAY)
    h = against_actuals(conn, run_id, TODAY)
    for r in rows:
        if r["variant"] == "baseline":
            _, it = items(h, r["period"])
            assert it[r["item"]].signed_miss == pytest.approx(r["signed_error"], abs=1e-12)
    _, it = items(h, "FY2019Q3")
    assert it["revenue"].signed_miss == pytest.approx(1 / 1.05 - 1)  # the forecast was low
    assert it["revenue"].miss == pytest.approx(1 - 1 / 1.05)


def test_ebit_on_another_definition_is_coded_and_revenue_still_scored(make_company):
    def drop_q3_operating_income(tag, row):
        if tag == "OperatingIncomeLoss" and row["end"] == "2019-09-30" and row["fp"] == "Q3":
            return None
        return row

    conn = make_company(drop_q3_operating_income)
    _, it = items(against_actuals(conn, run(conn), TODAY), "FY2019Q3")
    assert it["revenue"].miss == pytest.approx(0, abs=1e-9)
    assert it["ebit"].actual is None and it["ebit"].missing.code == "other_ebit_definition"
    assert it["ebit"].missing.params["reported_as"]


@pytest.mark.parametrize(("factor", "flagged"), [(2.0, True), (1.05, True), (1.001, False)])
def test_a_recast_prior_year_is_a_change_of_basis_not_a_miss(make_company, factor, flagged):
    def recast(tag, row):
        # the Q3 2019 10-Q restates the year-earlier quarter's revenue
        if tag == "Revenues" and row["end"] == "2018-09-30" and row["fy"] == 2019:
            row = row | {"val": row["val"] * factor}
        return row

    conn = make_company(recast)
    _, it = items(against_actuals(conn, run(conn), TODAY), "FY2019Q3")
    rev = it["revenue"]
    assert rev.actual == pytest.approx(100 * 1.1**4)
    if flagged:
        assert rev.miss is None and rev.missing.code == "restated_basis"
        assert rev.missing.params["filing_value"] == pytest.approx(rev.missing.params["run_value"]
                                                                   * factor)  # fmt: skip
    else:
        assert rev.missing is None and rev.miss == pytest.approx(0, abs=1e-9)


def test_to_dict_round_trips_through_json(company):
    h = against_actuals(company, run(company), TODAY)
    d = json.loads(json.dumps(h.to_dict()))
    assert d["actuals_on"] == "2020-06-30" and d["as_of"] == "2019-06-30"
    q = d["quarters"][1]
    assert q["period"] == "FY2019Q3" and q["items"][0]["filings"][0]["form"] == "10-Q"
    assert d["quarters"][-1]["items"][0]["missing"]["code"] == "not_reported"


def test_quarters_past_the_first_year_use_the_run_s_definition_and_basis(make_company):
    # as of 2019-03-31 the forecast starts at FY2019Q1, so FY2020Q1 is quarter 5: its year-earlier
    # quarter was forecast, not history
    def recast(tag, row):
        # the Q1 2019 10-Q restates the year-earlier quarter's revenue by 5%
        if tag == "Revenues" and row["end"] == "2018-03-31" and row["fy"] == 2019:
            row = row | {"val": row["val"] * 1.05}
        return row

    for conn, flagged in ((make_company(None), False), (make_company(recast), True)):
        run_id = run_baseline(conn, "TST", date(2019, 3, 31), choices=CHOICES, today=TODAY)
        h = against_actuals(conn, run_id, TODAY)
        q5, it = items(h, "FY2020Q1")
        assert q5.horizon == 5 and it["ebit"].missing is None
        assert it["ebit"].actual == pytest.approx(0.2 * it["revenue"].actual)
        assert it["ebit"].miss is not None  # on the run's own definition, from its newest row
        _, first = items(h, "FY2019Q1")
        if flagged:  # the basis changed at FY2019Q1, so FY2020Q1 is not a miss either
            assert first["revenue"].missing.code == "restated_basis"
            assert it["revenue"].missing.code == "restated_basis"
            assert "changed at FY2019Q1" in it["revenue"].missing.text
        else:
            assert it["revenue"].missing is None and it["revenue"].miss is not None


def test_shared_reads_give_the_same_answer_and_read_each_filing_date_once(
    make_company, monkeypatch
):
    """Backlog #252: several runs of one company share one FactReads; the answer is unchanged
    (the recast fixture, so a restated_basis flag is in it) and each (date, mode) is read once."""

    def recast(tag, row):
        if tag == "Revenues" and row["end"] == "2018-09-30" and row["fy"] == 2019:
            row = row | {"val": row["val"] * 2.0}
        return row

    conn = make_company(recast)
    runs = [run_baseline(conn, "TST", d, choices=CHOICES, today=TODAY)
            for d in (date(2019, 3, 31), AS_OF)]  # fmt: skip
    alone = [against_actuals(conn, r, TODAY).to_dict() for r in runs]
    calls = []
    real = HS._quarterly
    monkeypatch.setattr(HS, "_quarterly", lambda *a: calls.append(a[1:]) or real(*a))
    reads = FactReads(conn)
    shared = [against_actuals(conn, r, TODAY, reads).to_dict() for r in runs]
    assert shared == alone
    assert any(i["missing"] and i["missing"]["code"] == "restated_basis"
               for q in shared[1]["quarters"] for i in q["items"])  # fmt: skip
    assert len(calls) == len(set(calls))  # each (cik, date, mode) once across both runs
    calls.clear()
    for r in runs:
        against_actuals(conn, r, TODAY)
    assert len(calls) > len(set(calls))  # without sharing, the second run reads them again
    cik = conn.execute("SELECT cik FROM runs").fetchone()[0]
    with pytest.raises(TypeError):  # read-only: one run can't change what the next one reads
        reads.quarterly(cik, TODAY, "first_reported")[("revenue", 1, "Q1")] = None
