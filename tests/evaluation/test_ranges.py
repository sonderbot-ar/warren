"""M9 honest ranges: origins and their errors on Test Corp, and the range on hand-made errors."""

import math
from datetime import date

import numpy as np
import pytest

from domains.evaluation import ranges as R
from tests.evaluation.conftest import CHOICES

TODAY = date(2020, 6, 30)


def pair(h=1, filed=date(2020, 1, 1), rev=0.0, ebit=0.0, ticker="AAA", n=0):
    return R.ErrorPair(f"{ticker}_{n}", ticker, h, f"P{n}", filed, rev, ebit)


# -- origins on Test Corp ----------------------------------------------------------------------


def test_origin_dates_are_the_first_of_each_month():
    assert R.origin_dates(date(2019, 11, 15), date(2020, 2, 1)) == [
        date(2019, 11, 1),
        date(2019, 12, 1),
        date(2020, 1, 1),
        date(2020, 2, 1),
    ]
    assert len(R.origin_dates()) == 91


def test_an_origin_stores_its_run_and_zero_errors_on_test_corp(company):
    assert R.build_origin(company, "TST", date(2019, 5, 1), TODAY, CHOICES, TODAY) == "built"
    origin = company.execute("SELECT * FROM forecast_origins").fetchone()
    assert origin["status"] == "ok" and origin["run_id"]
    rows = company.execute("SELECT * FROM baseline_errors ORDER BY horizon, item").fetchall()
    assert len(rows) == 8  # 4 quarters × revenue and EBIT
    ok = [r for r in rows if r["status"] == "ok"]
    assert ok and all(r["error"] == pytest.approx(0, abs=1e-9) for r in ok)
    # the h1 actual was filed after the origin: a run can't have seen it
    assert all(date.fromisoformat(r["actual_filed_at"]) > date(2019, 5, 1) for r in ok)
    # Q1 2020 is reported (filed 2020-04-30); later quarters are missing
    assert {r["status"] for r in rows if r["period"] > "FY2020Q1"} <= {"missing"}


def test_a_miss_gives_the_hand_computed_errors(make_company):
    def q3_revenue_up(tag, row):
        # Q3 2019 revenue 10% higher in its own 10-Q, operating income unchanged
        if tag == "Revenues" and row["end"] == "2019-09-30" and row["fp"] == "Q3":
            row = row | {"val": row["val"] * 1.1}
        return row

    conn = make_company(q3_revenue_up)
    R.build_origin(conn, "TST", date(2019, 5, 1), TODAY, CHOICES, TODAY)
    q3 = {
        r["item"]: r
        for r in conn.execute("SELECT * FROM baseline_errors WHERE period = 'FY2019Q3'")
    }
    assert q3["revenue"]["error"] == pytest.approx(math.log(1.1), rel=1e-9)
    ebit = q3["ebit"]
    expected = (ebit["actual"] - ebit["forecast"]) / ebit["actual_revenue"]
    assert ebit["error"] == pytest.approx(expected) and ebit["status"] == "ok"


def test_an_origin_before_the_engine_supports_is_stored_as_failed(company):
    assert R.build_origin(company, "TST", date(2019, 1, 1), TODAY, CHOICES, TODAY) == "failed"
    origin = company.execute("SELECT * FROM forecast_origins").fetchone()
    assert origin["status"] == "failed" and "as-of date" in origin["reason"]
    assert origin["run_id"] is None


def test_a_stored_origin_is_kept_and_its_missing_errors_rescored_later(company):
    d = date(2019, 5, 1)
    R.build_origin(company, "TST", d, date(2019, 9, 1), CHOICES, TODAY)
    before = company.execute("SELECT COUNT(*) FROM baseline_errors WHERE status = 'ok'")
    assert before.fetchone()[0] == 2  # only Q2 2019 (filed 2019-07-30) by 2019-09-01
    runs = company.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert R.build_origin(company, "TST", d, TODAY, CHOICES, TODAY) == "rescored"
    after = company.execute("SELECT COUNT(*) FROM baseline_errors WHERE status = 'ok'")
    assert after.fetchone()[0] == 8
    assert company.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs  # same run
    assert R.build_origin(company, "TST", d, TODAY, CHOICES, TODAY) == "kept"


def test_a_negative_revenue_excludes_both_items_of_the_quarter():
    rows = [
        {"variant": "baseline", "period": "P", "item": "revenue", "horizon": 1, "forecast": 10.0,
         "status": "ok", "actual": -1.0, "actual_revenue": -1.0, "actual_filed_at": "2020-01-01"},
        {"variant": "baseline", "period": "P", "item": "ebit", "horizon": 1, "forecast": 1.0,
         "status": "ok", "actual": 0.5, "actual_revenue": -1.0, "actual_filed_at": "2020-01-01"},
    ]  # fmt: skip
    out = R.error_rows("X_2020-01-01", "X", date(2020, 1, 1), rows)
    assert {r["status"] for r in out} == {"excluded"}


# -- known errors and ranges -------------------------------------------------------------------


def test_an_error_filed_after_the_date_is_not_known():
    on = date(2021, 3, 1)
    pairs = [pair(filed=on, n=1), pair(filed=date(2021, 3, 2), n=2), pair(h=2, filed=on, n=3)]
    assert [p.origin_id for p in R.known(pairs, on, 1, "pooled", "AAA")] == ["AAA_1"]


def test_the_own_pool_keeps_the_company_only():
    pairs = [pair(ticker="AAA", n=1), pair(ticker="BBB", n=2)]
    assert len(R.known(pairs, date(2021, 1, 1), 1, "pooled", "AAA")) == 2
    assert [p.ticker for p in R.known(pairs, date(2021, 1, 1), 1, "own", "AAA")] == ["AAA"]
    with pytest.raises(R.RangeError):
        R.known(pairs, date(2021, 1, 1), 1, "other", "AAA")


def forecasts(rev=100.0, ebit=20.0):
    return R.constant_samples({1: (rev, ebit)}, n=1000)


def test_below_the_minimum_there_is_no_range():
    pairs = [pair(n=i) for i in range(R.MIN_ERRORS["pooled"] - 1)]
    (r,) = R.ranges(forecasts(), pairs, date(2021, 1, 1), "pooled", "AAA", 1, n=1000).values()
    assert not r.ok and r.n_errors == R.MIN_ERRORS["pooled"] - 1


def test_one_repeated_error_gives_a_range_of_one_point_at_the_actual():
    e_rev, e_ebit = math.log(1.2), -0.05
    pairs = [pair(rev=e_rev, ebit=e_ebit, n=i) for i in range(25)]
    (r,) = R.ranges(forecasts(), pairs, date(2021, 1, 1), "pooled", "AAA", 7, n=1000).values()
    assert r.revenue == pytest.approx((120.0, 120.0, 120.0))
    assert r.ebit == pytest.approx((20.0 - 0.05 * 120,) * 3)
    assert r.n_quarters == 25


def test_the_same_seed_gives_the_same_range_and_another_seed_may_not():
    rng = np.random.default_rng(0)
    pairs = [
        pair(rev=float(x), ebit=float(x) / 10, n=i) for i, x in enumerate(rng.normal(0, 0.1, 40))
    ]
    a = R.ranges(forecasts(), pairs, date(2021, 1, 1), "pooled", "AAA", 11, n=1000)
    b = R.ranges(forecasts(), pairs, date(2021, 1, 1), "pooled", "AAA", 11, n=1000)
    c = R.ranges(forecasts(), pairs, date(2021, 1, 1), "pooled", "AAA", 12, n=1000)
    assert a == b and a != c
    lo, mid, hi = a[1].revenue
    assert lo < mid < hi


def test_revenue_and_ebit_share_one_draw():
    # errors move together: a revenue miss up always comes with an EBIT miss up, so the EBIT
    # p10 must come from the revenue p10's draws, never mix them
    pairs = [pair(rev=-0.1, ebit=-0.02, n=i) for i in range(20)]
    pairs += [pair(rev=0.1, ebit=0.02, n=20 + i) for i in range(20)]
    samples = R.constant_samples({1: (100.0, 20.0)}, n=2000)
    (r,) = R.ranges(samples, pairs, date(2021, 1, 1), "pooled", "AAA", 3, n=2000).values()
    low_rev = 100 * math.exp(-0.1)
    assert r.revenue[0] == pytest.approx(low_rev)
    assert r.ebit[0] == pytest.approx(20.0 - 0.02 * low_rev)


def test_shocked_samples_carry_the_error_on_top_of_the_shock():
    pairs = [pair(rev=math.log(1.1), ebit=0.0, n=i) for i in range(20)]
    shocked = {1: (np.array([90.0, 100.0, 110.0] * 100), np.full(300, 20.0))}
    (r,) = R.ranges(shocked, pairs, date(2021, 1, 1), "pooled", "AAA", 3, n=300).values()
    assert r.revenue == pytest.approx((99.0, 110.0, 121.0))


def test_range_seed_is_fixed_and_differs_by_pool():
    assert R.range_seed("KO_2021-01-01", "pooled") == R.range_seed("KO_2021-01-01", "pooled")
    assert R.range_seed("KO_2021-01-01", "pooled") != R.range_seed("KO_2021-01-01", "own")
