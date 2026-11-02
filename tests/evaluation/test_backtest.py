"""The M8 metrics on hand-made rows, with answers computed by hand (M8 Step 2)."""

import math

import pytest

from domains.evaluation import backtest as bt


def row(case, variant, error, period="FY2020Q1", item="revenue", horizon=1, forecast=None,
        actual=100.0, p10=None, p90=None, d_fc=1, d_act=1, status="ok"):  # fmt: skip
    return {"case_id": case, "variant": variant, "item": item, "period": period,
            "horizon": horizon, "error": error, "status": status,
            "forecast": forecast if forecast is not None else actual * (1 + error),
            "actual": actual, "actual_revenue": actual, "p10": p10, "p50": None, "p90": p90,
            "direction_forecast": d_fc, "direction_actual": d_act}  # fmt: skip


# -- populations ------------------------------------------------------------------------------


def three_cases():
    return [
        row("A", "baseline", 0.10, forecast=110),
        row("A", "llm_masked", 0.05, forecast=105),
        row("B", "baseline", 0.20, forecast=120),  # no masked row: the AI proposed nothing
        row("C", "baseline", 0.04, forecast=104),
        row("C", "llm_masked", 0.04, forecast=104),  # a row, but the forecast did not move
    ]


def test_all_cases_fill_a_missing_variant_with_the_baseline():
    ps = bt.pairs(three_cases(), "llm_masked")
    assert [(p.case_id, p.variant["error"], p.filled) for p in ps] == [
        ("A", 0.05, False), ("B", 0.20, True), ("C", 0.04, False)]  # fmt: skip


def test_moved_keeps_only_items_whose_p50_moved():
    assert [p.case_id for p in bt.pairs(three_cases(), "llm_masked", "moved")] == ["A"]


def test_no_scope_drops_the_scope_change_cases():
    ps = bt.pairs(three_cases(), "llm_masked", "no_scope", scope_cases={"A"})
    assert [p.case_id for p in ps] == ["B", "C"]


def test_guidance_shocks_are_judged_on_their_own_cases_only():
    rows = three_cases() + [row("A", "with_shocks", 0.02, forecast=102)]
    assert [p.case_id for p in bt.pairs(rows, "with_shocks")] == ["A"]


def test_missing_quarters_are_not_scored():
    rows = [row("A", "baseline", 0.1), row("A", "baseline", None, period="FY2020Q2",
                                           status="missing", forecast=1.0)]  # fmt: skip
    assert len(bt.pairs(rows, "llm_named")) == 1


def test_an_unknown_population_is_refused():
    with pytest.raises(ValueError, match="unknown population"):
        bt.pairs([], "llm_named", "acted")


# -- skill and the paired test ----------------------------------------------------------------


def test_skill_is_zero_when_equal_and_positive_when_better():
    ps = bt.pairs(three_cases(), "llm_masked")
    mean, median = bt.skill(ps)
    # mean errors 0.34/3 vs 0.29/3; medians 0.10 vs 0.05
    assert mean == pytest.approx(1 - 0.29 / 0.34)
    assert median == pytest.approx(0.5)
    same = [row("A", "baseline", 0.1), row("A", "llm_named", 0.1, forecast=110.0)]
    assert bt.skill(bt.pairs(same, "llm_named")) == (0.0, 0.0)
    assert bt.skill([]) is None


def test_skill_against_naive_on_matched_quarters():
    rows = three_cases() + [row("A", "naive_srw", 0.10), row("B", "naive_srw", 0.40)]
    naive = {(r["case_id"], r["item"], r["period"]): r for r in rows if r["variant"] == "naive_srw"}
    # matched: A (0.05 vs 0.10) and B (0.20 vs 0.40): 1 − 0.25/0.50
    assert bt.skill_against(bt.pairs(rows, "llm_masked"), naive) == pytest.approx(0.5)


def test_case_difference_is_the_mean_over_the_cases_quarters():
    rows = [row("A", "baseline", 0.10), row("A", "llm_named", 0.04, forecast=1),
            row("A", "baseline", 0.20, period="FY2020Q2", horizon=2),
            row("A", "llm_named", 0.30, period="FY2020Q2", horizon=2, forecast=1)]  # fmt: skip
    ds = bt.case_differences(bt.pairs(rows, "llm_named"))
    assert ds == {"A": pytest.approx((0.04 + 0.30) / 2 - (0.10 + 0.20) / 2)}
    assert bt.by_horizon(bt.pairs(rows, "llm_named")) == {
        1: (pytest.approx(-0.06), 1), 2: (pytest.approx(0.10), 1)}  # fmt: skip


def test_sign_test_five_of_five_is_0_0625_and_ties_are_left_out():
    t = bt.sign_test([-1, -2, -0.5, -3, -1, 0.0, 0.0])
    assert (t.better, t.worse, t.ties) == (5, 0, 2)
    assert t.p == pytest.approx(0.0625)


def test_sign_test_balanced_is_one_and_empty_is_none():
    assert bt.sign_test([-1, 1]).p == 1.0
    assert bt.sign_test([0.0, 0.0]).p is None
    # 2 of 8 worse: 2 × (C(8,0) + C(8,1) + C(8,2)) / 256
    assert bt.sign_test([-1] * 6 + [1] * 2).p == pytest.approx(2 * (1 + 8 + 28) / 256)


def test_three_cases_can_never_reach_significance():
    assert bt.sign_test([-1, -1, -1]).p == pytest.approx(0.25)


def test_bootstrap_reproduces_with_its_seed_and_collapses_on_equal_differences():
    ds = [-0.03, 0.01, -0.02, 0.0, -0.05, 0.02]
    first = bt.bootstrap_mean(ds)
    assert first == bt.bootstrap_mean(ds)
    lo, hi = first
    assert lo < sum(ds) / len(ds) < hi
    assert bt.bootstrap_mean([0.01] * 5) == pytest.approx((0.01, 0.01))
    assert bt.bootstrap_mean([]) is None


# -- direction --------------------------------------------------------------------------------


def test_direction_hit_rate_base_rate_and_unknowns():
    rows = [row("A", "baseline", 0, d_fc=1, d_act=1), row("B", "baseline", 0, d_fc=1, d_act=-1),
            row("C", "baseline", 0, d_fc=0, d_act=0), row("D", "baseline", 0, d_fc=1, d_act=0),
            row("E", "baseline", 0, d_fc=1, d_act=None)]  # fmt: skip
    d = bt.direction(rows)
    assert (d.hits, d.n, d.unknown, d.rose) == (2, 4, 1, 1)
    assert (d.rate, d.base_rate) == (0.5, 0.25)  # a flat actual is hit only by a flat forecast
    assert bt.direction([]).rate is None


# -- the band ---------------------------------------------------------------------------------


def test_coverage_counts_the_ends_as_inside():
    rows = [row("A", "llm_named", 0, actual=100, p10=100, p90=110),
            row("B", "llm_named", 0, actual=110, p10=100, p90=110),
            row("C", "llm_named", 0, actual=99.99, p10=100, p90=110),
            row("D", "llm_named", 0, actual=100)]  # no band: not counted  # fmt: skip
    c = bt.coverage(rows)
    assert (c.inside, c.n) == (2, 3)
    lo, hi = c.interval
    assert lo < 2 / 3 < hi


def test_wilson_interval_by_hand():
    # k = 8, n = 10, z = 1.96: (0.8 + 0.192) / 1.384 ± 1.96 √(0.016 + 0.009604) / 1.384
    lo, hi = bt.wilson(8, 10)
    centre = (0.8 + bt.Z95**2 / 20) / (1 + bt.Z95**2 / 10)
    half = bt.Z95 * math.sqrt(0.8 * 0.2 / 10 + bt.Z95**2 / 400) / (1 + bt.Z95**2 / 10)
    assert (lo, hi) == pytest.approx((centre - half, centre + half))
    assert bt.wilson(0, 0) is None


def test_interval_score_of_a_hit_is_its_width_and_of_a_miss_width_plus_ten_times_the_miss():
    assert bt.interval_score(90, 110, 100, scale=100) == pytest.approx(0.20)
    assert bt.interval_score(90, 110, 115, scale=100) == pytest.approx((20 + 10 * 5) / 100)
    assert bt.interval_score(90, 110, 80, scale=100) == pytest.approx((20 + 10 * 10) / 100)
    # a point forecast scores 10 × its miss
    assert bt.interval_score(104, 104, 100, scale=100) == pytest.approx(0.40)
    with pytest.raises(ValueError):
        bt.interval_score(1, 2, 1, scale=0)


def test_interval_scores_compare_band_and_point_on_the_same_wide_quarters():
    rows = [row("A", "baseline", 0.04, forecast=104, actual=100),
            row("A", "llm_named", 0.0, forecast=100, actual=100, p10=95, p90=105),
            row("B", "baseline", 0.02, forecast=102, actual=100),
            row("B", "llm_named", 0.02, forecast=102, actual=100, p10=102, p90=102)]  # fmt: skip
    var, base, n = bt.interval_scores(bt.pairs(rows, "llm_named"))
    assert n == 1  # B's band has no width
    assert (var, base) == (pytest.approx(0.10), pytest.approx(0.40))


# -- named against masked ---------------------------------------------------------------------


def test_opposite_moves_are_counted_per_case_and_item():
    rows = [row("A", "baseline", 0, forecast=100), row("A", "llm_named", 0, forecast=101),
            row("A", "llm_masked", 0, forecast=99),
            row("B", "baseline", 0, forecast=100), row("B", "llm_named", 0, forecast=101),
            row("B", "llm_masked", 0, forecast=102),
            row("C", "baseline", 0, forecast=100),
            row("C", "llm_named", 0, forecast=101)]  # fmt: skip
    assert bt.opposite_moves(rows) == [("A", "revenue")]
