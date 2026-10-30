"""The harness on Test Corp, whose revenue grows exactly 10% a year at a 20% operating margin:
the baseline should forecast it without error, and the naive forecast should miss by 1/11."""

from datetime import date

import pytest

from domains.evaluation.cases import Case
from domains.evaluation.harness import (
    EvaluationError,
    direction,
    evaluate_case,
    guard_coverage,
    guard_look_ahead,
    run_batch,
    score,
)
from tests.evaluation.conftest import CHOICES

TODAY = date(2020, 6, 30)


def case(event_date=date(2019, 6, 30), horizon=4, ticker="TST") -> Case:
    return Case(
        case_id=f"{ticker}_{event_date}",
        ticker=ticker,
        event_date=event_date,
        event_type="guidance",
        description="test",
        horizon_quarters=horizon,
        selected_because="test",
        source_url="https://example.com",
        scope_change="",
    )


def evaluate(conn, c=None, actuals_as_of=TODAY):
    return evaluate_case(conn, c or case(), CHOICES, actuals_as_of=actuals_as_of, today=TODAY)


def by(rows, variant, item):
    return [r for r in rows if r["variant"] == variant and r["item"] == item]


def test_the_baseline_forecasts_test_corp_without_error(company):
    _, rows = evaluate(company)
    baseline = by(rows, "baseline", "revenue") + by(rows, "baseline", "ebit")
    assert [r["period"] for r in by(rows, "baseline", "revenue")] == [
        "FY2019Q2",
        "FY2019Q3",
        "FY2019Q4",
        "FY2020Q1",
    ]
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["error"] == pytest.approx(0, abs=1e-9) for r in baseline)
    assert all(r["direction_forecast"] == r["direction_actual"] == 1 for r in baseline)


def test_the_naive_forecast_misses_by_a_year_of_growth(company):
    _, rows = evaluate(company)
    for r in by(rows, "naive_srw", "revenue"):
        assert r["error"] == pytest.approx(1 - 1 / 1.1)  # last year's quarter vs 10% growth
        assert r["direction_forecast"] == 0  # naive always says "flat"
    for r in by(rows, "naive_srw", "ebit"):
        # EBIT error in margin points: 20% margin on the revenue gap, over actual revenue
        assert r["error"] == pytest.approx(0.2 * (1 - 1 / 1.1))


def test_a_derived_q4_is_flagged(company):
    _, rows = evaluate(company)
    flags = {r["period"]: r["derived"] for r in by(rows, "baseline", "revenue")}
    assert flags == {"FY2019Q2": 0, "FY2019Q3": 0, "FY2019Q4": 1, "FY2020Q1": 0}


def test_quarters_not_reported_yet_are_missing_not_zero(company):
    _, rows = evaluate(company, actuals_as_of=date(2019, 12, 31))
    status = {r["period"]: r["status"] for r in by(rows, "baseline", "revenue")}
    assert status == {"FY2019Q2": "ok", "FY2019Q3": "ok", "FY2019Q4": "missing",
                      "FY2020Q1": "missing"}  # fmt: skip
    assert all(r.get("error") is None for r in rows if r["status"] == "missing")


def test_the_horizon_limits_the_quarters(company):
    _, rows = evaluate(company, case(horizon=2))
    assert {r["horizon"] for r in rows} == {1, 2}


def test_the_look_ahead_guard_trips_on_a_filing_after_the_case_date(company):
    run_id, _ = evaluate(company)
    assert guard_look_ahead(company, run_id, date(2019, 6, 30)) > 0
    with pytest.raises(EvaluationError, match="look-ahead guard"):
        guard_look_ahead(company, run_id, date(2019, 4, 29))  # the Q1 10-Q came on 04-30


def test_the_actual_direction_uses_the_comparative_from_the_actuals_filing(make_company):
    def recast(tag, row):
        # the Q3 2019 10-Q restates the year-earlier quarter's revenue to double
        if tag == "Revenues" and row["end"] == "2018-09-30" and row["fy"] == 2019:
            row = row | {"val": row["val"] * 2}
        return row

    _, rows = evaluate(make_company(recast))
    (q3,) = [r for r in by(rows, "baseline", "revenue") if r["period"] == "FY2019Q3"]
    assert q3["comparative"] == pytest.approx(2 * q3["prior_year_known"])
    assert q3["direction_actual"] == -1 and q3["direction_forecast"] == 1


def test_a_derived_comparative_on_mixed_bases_leaves_the_direction_unknown(make_company):
    def recast_prior_year(tag, row):
        # the FY2019 10-K recasts FY2018 revenue (as JNJ's FY2022 10-K did FY2021 after Kenvue);
        # last year's nine months stay as first reported, so FY − M9 mixes two bases
        if tag == "Revenues" and row["end"] == "2018-12-31" and row["fy"] == 2019:
            row = row | {"val": row["val"] * 0.8}
        return row

    _, rows = evaluate(make_company(recast_prior_year))
    (q4,) = [r for r in by(rows, "baseline", "revenue") if r["period"] == "FY2019Q4"]
    assert q4["status"] == "ok" and q4["derived"] == 1
    assert q4["comparative"] is None and q4["direction_actual"] is None


def test_an_actual_on_another_ebit_definition_fails_the_case(make_company):
    def drop_q3_operating_income(tag, row):
        if tag == "OperatingIncomeLoss" and row["end"] == "2019-09-30" and row["fp"] == "Q3":
            return None
        return row

    with pytest.raises(EvaluationError, match="reported only as pretax_income"):
        evaluate(make_company(drop_q3_operating_income))


def test_a_batch_records_results_and_failures(company):
    cases = [case(), case(event_date=date(2019, 1, 15))]  # before the engine's first date
    batch_id = run_batch(company, cases, "abc", CHOICES, actuals_as_of=TODAY, today=TODAY)
    batch = company.execute("SELECT * FROM eval_batches").fetchone()
    assert batch["batch_id"] == batch_id and batch["cases_sha256"] == "abc"
    count = company.execute("SELECT COUNT(*) FROM eval_results").fetchone()[0]
    assert count == 4 * 2 * 2  # quarters × items × variants
    (failure,) = company.execute("SELECT case_id, reason FROM eval_failures").fetchall()
    assert failure["case_id"] == "TST_2019-01-15" and "as-of date" in failure["reason"]


def test_coverage_is_a_hard_error_past_a_companys_history():
    with pytest.raises(EvaluationError, match="coverage"):
        guard_coverage(case(event_date=date(2026, 3, 31), ticker="XOM"))
    guard_coverage(case(event_date=date(2024, 3, 31), ticker="XOM"))  # ends well before


def test_ebit_error_is_in_margin_points_even_when_ebit_is_negative():
    error, signed, pct = score("ebit", forecast=5, actual=-10, actual_revenue=100)
    assert (error, signed, pct) == pytest.approx((0.15, 0.15, 1.5))
    with pytest.raises(EvaluationError, match="zero"):
        score("revenue", forecast=5, actual=0, actual_revenue=0)


@pytest.mark.parametrize(
    ("value", "reference", "expected"),
    [(110, 100, 1), (90, 100, -1), (100.4, 100, 0), (99.6, 100, 0), (1, None, None), (1, 0, None)],
)
def test_direction(value, reference, expected):
    assert direction(value, reference) == expected
