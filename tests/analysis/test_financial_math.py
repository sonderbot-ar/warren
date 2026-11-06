"""Every formula against values small enough to check by hand (the comment shows the arithmetic)."""

import math

import pytest

from domains.analysis import financial_math as fm
from domains.analysis.financial_math import FinancialMathError


def test_compound_period_on_period():
    # 100 → ×1.10 → 110 → ×0.95 → 104.5
    assert fm.compound([100], [0.10, -0.05]) == pytest.approx([110, 104.5])


def test_compound_on_quarters_keeps_seasonality():
    # each quarter grows from the same quarter a year earlier
    seed = [10, 20, 30, 40]
    assert fm.compound(seed, [0.10] * 8, lag=4) == pytest.approx(
        [11, 22, 33, 44, 12.1, 24.2, 36.3, 48.4]
    )


def test_compound_needs_one_seed_value_per_lag():
    with pytest.raises(FinancialMathError, match="seed"):
        fm.compound([10, 20], [0.1], lag=4)


def test_fcff():
    # 100 × (1 − 0.25) + 20 − 30 − 5 = 60
    assert fm.fcff(ebit=100, tax_rate=0.25, d_and_a=20, capex=30, delta_nwc=5) == pytest.approx(60)


def test_discount_factors_constant_and_time_varying():
    assert fm.discount_factors([0.10, 0.10], [1, 1]) == pytest.approx([1 / 1.1, 1 / 1.21])
    # second year at 20%: 1 / (1.1 × 1.2)
    assert fm.discount_factors([0.10, 0.20], [1, 1]) == pytest.approx([1 / 1.1, 1 / 1.32])
    # four quarters at 10% a year compound to one year at 10%
    assert fm.discount_factors([0.10] * 4, [0.25] * 4)[-1] == pytest.approx(1 / 1.1)


def test_discount_factors_reject_bad_periods():
    with pytest.raises(FinancialMathError):
        fm.discount_factors([0.1], [0])
    with pytest.raises(FinancialMathError):
        fm.discount_factors([0.1, 0.1], [1])


def test_gordon_terminal_value():
    # 100 × 1.02 / (0.10 − 0.02) = 1275
    assert fm.gordon_terminal_value(100, 0.10, 0.02) == pytest.approx(1275)


@pytest.mark.parametrize("growth", [0.10, 0.12])
def test_terminal_growth_at_or_above_the_discount_rate_fails(growth):
    with pytest.raises(FinancialMathError, match="terminal growth"):
        fm.gordon_terminal_value(100, 0.10, growth)


def test_enterprise_value_by_hand():
    # explicit: 100/1.1 + 110/1.21 = 90.909 + 90.909 = 181.818
    # terminal at end of year 2: 110 × 1.02 / 0.08 = 1402.5, discounted /1.21 = 1159.091
    v = fm.enterprise_value([100, 110], [0.10, 0.10], [1, 1], terminal_growth=0.02)
    assert v.pv_explicit == pytest.approx(181.8182, abs=1e-4)
    assert v.terminal_value == pytest.approx(1402.5)
    assert v.pv_terminal == pytest.approx(1159.0909, abs=1e-4)
    assert v.enterprise_value == pytest.approx(1340.9091, abs=1e-4)
    assert v.terminal_share == pytest.approx(1159.0909 / 1340.9091)


def test_quarterly_cash_flows_use_an_annual_figure_for_the_terminal_value():
    v = fm.enterprise_value([25] * 4, [0.10] * 4, [0.25] * 4, 0.0, final_annual_cash_flow=100)
    assert v.terminal_value == pytest.approx(1000)


def test_zero_growth_and_zero_reinvestment_is_a_perpetuity():
    # a flat cash flow forever is worth CF / r, however the forecast years are split
    v = fm.enterprise_value([100] * 5, [0.08] * 5, [1] * 5, terminal_growth=0.0)
    assert v.enterprise_value == pytest.approx(100 / 0.08)


def test_a_higher_discount_rate_never_raises_value():
    values = [
        fm.enterprise_value([100, 105, 110], [r] * 3, [1, 1, 1], 0.02).enterprise_value
        for r in (0.05, 0.06, 0.08, 0.10, 0.15)
    ]
    assert values == sorted(values, reverse=True)


def test_equity_value_and_value_per_share():
    # 1000 − 200 net debt − 50 minority interest = 750; / 25 shares = 30
    equity = fm.equity_value(1000, net_debt=200, minority_interest=50)
    assert equity == 750
    assert fm.value_per_share(equity, 25) == 30
    # net cash raises equity above EV
    assert fm.equity_value(1000, net_debt=-300) == 1300


@pytest.mark.parametrize("shares", [0, -1])
def test_non_positive_shares_fail(shares):
    with pytest.raises(FinancialMathError, match="share count"):
        fm.value_per_share(100, shares)


def test_capm_and_wacc():
    # 4% + 1.2 × 5% = 10%
    assert fm.capm_cost_of_equity(0.04, 1.2, 0.05) == pytest.approx(0.10)
    # 0.8 × 10% + 0.2 × 5% × (1 − 0.25) = 8% + 0.75% = 8.75%
    assert fm.wacc(800, 200, 0.10, 0.05, 0.25) == pytest.approx(0.0875)
    assert fm.wacc(800, 0, 0.10, 0.05, 0.25) == pytest.approx(0.10)
    with pytest.raises(FinancialMathError):
        fm.wacc(0, 200, 0.10, 0.05, 0.25)


def test_cost_of_debt():
    assert fm.cost_of_debt(30, 600) == pytest.approx(0.05)
    with pytest.raises(FinancialMathError):
        fm.cost_of_debt(30, 0)


def test_ols_beta_and_blume_adjustment():
    market = [0.01, -0.02, 0.03, 0.00, -0.01]
    assert fm.ols_beta([2 * m for m in market], market) == pytest.approx(2.0)
    assert fm.ols_beta([m + 0.005 for m in market], market) == pytest.approx(1.0)
    # 2/3 × 2 + 1/3 = 5/3
    assert fm.blume_adjusted_beta(2.0) == pytest.approx(5 / 3)
    assert fm.blume_adjusted_beta(1.0) == pytest.approx(1.0)


def test_ols_beta_rejects_unusable_returns():
    with pytest.raises(FinancialMathError, match="same dates"):
        fm.ols_beta([0.1, 0.2, 0.3], [0.1, 0.2])
    with pytest.raises(FinancialMathError, match="at least 3"):
        fm.ols_beta([0.1, 0.2], [0.1, 0.2])
    with pytest.raises(FinancialMathError, match="variance"):
        fm.ols_beta([0.1, 0.2, 0.3], [0.01, 0.01, 0.01])


def test_bond_total_return():
    # yields unchanged: the price stays at par, so the return is the coupon
    assert fm.bond_total_return(0.05, 0.05) == pytest.approx(0.05)
    # 1-year maturity, 5% → 10%: price 1.05 / 1.10 = 0.954545, return 0.05 + 0.954545 − 1
    assert fm.bond_total_return(0.05, 0.10, maturity=1) == pytest.approx(0.004545, abs=1e-6)
    # yields fall to 0%: price = 10 coupons of 3% + par = 1.30, return 0.03 + 0.30
    assert fm.bond_total_return(0.03, 0.0) == pytest.approx(0.33)
    assert fm.bond_total_return(0.05, 0.06) < 0.05 < fm.bond_total_return(0.05, 0.04)


def test_historical_premium():
    # stocks +21%, −10%; bonds +10%, +10%
    premium = fm.historical_premium([0.21, -0.10], [0.10, 0.10])
    # geometric: √(1.21 × 0.90) − 1 = 0.043560 vs 0.10
    assert premium.geometric == pytest.approx(1.21**0.5 * 0.9**0.5 - 1 - 0.10)
    # excess 0.11 and −0.20: mean −0.045, stdev √((0.155² + 0.155²) / 1), SE stdev / √2
    assert premium.arithmetic == pytest.approx(-0.045)
    assert premium.std_error == pytest.approx(0.155)
    assert premium.years == 2


def test_historical_premium_rejects_mismatched_or_short_series():
    with pytest.raises(FinancialMathError, match="same years"):
        fm.historical_premium([0.1, 0.2], [0.05])
    with pytest.raises(FinancialMathError, match="at least 2"):
        fm.historical_premium([0.1], [0.05])


# -- why a formula has no value (backlog #9) ---------------------------------------------------


def _reason(call):
    with pytest.raises(FinancialMathError) as caught:
        call()
    return caught.value.reason


def test_each_no_value_case_carries_its_reason():
    # Gordon fails at g ≥ WACC; the value-driver form at WACC ≤ 0 first; discounting at ≤ −100%
    assert _reason(lambda: fm.gordon_terminal_value(100, 0.04, 0.04)) == "growth_not_below_rate"
    assert _reason(lambda: fm.value_driver_terminal_value(60, 0.0, 0.04)) == "rate_not_positive"
    assert _reason(lambda: fm.discount_factors([-1.0], [1])) == "rate_not_above_minus_100"


@pytest.mark.parametrize("wacc", [0.04, 0.03])
def test_the_value_driver_form_has_no_value_at_or_above_growth(wacc):
    # the perpetuity behind NOPAT × (1 + g) / WACC converges only for g < WACC (backlog #79)
    call = lambda: fm.value_driver_terminal_value(60, wacc, 0.04)  # noqa: E731
    assert _reason(call) == "growth_not_below_rate"


def test_the_value_driver_form_just_below_growth_by_hand():
    # WACC 4.1% > g 4%: 60 × 1.04 / 0.041 = 1521.95…
    assert fm.value_driver_terminal_value(60, 0.041, 0.04) == pytest.approx(60 * 1.04 / 0.041)


def test_the_value_driver_form_refuses_any_sample_at_or_above_growth():
    import numpy as np

    with pytest.raises(FinancialMathError, match="terminal growth"):
        fm.value_driver_terminal_value(60, np.array([0.08, 0.04]), 0.04)


def test_other_checks_say_invalid_input_and_unknown_codes_are_refused():
    assert _reason(lambda: fm.value_per_share(100, 0)) == "invalid_input"
    assert _reason(lambda: fm.discount_factors([0.1], [0])) == "invalid_input"
    with pytest.raises(ValueError, match="unknown"):
        FinancialMathError("x", "made_up")


# -- M9: forecast errors -----------------------------------------------------------------------


def test_log_ratio_and_margin_error_by_hand():
    assert fm.log_ratio(110.0, 100.0) == pytest.approx(0.0953101798, rel=1e-9)
    # actual EBIT 20 on revenue 110, forecast 25: 5 points of margin too high
    assert fm.margin_error(20.0, 25.0, 110.0) == pytest.approx(-5 / 110)
    assert fm.apply_margin_error(25.0, -5 / 110, 110.0) == pytest.approx(20.0)


@pytest.mark.parametrize("actual, forecast", [(0.0, 1.0), (1.0, 0.0), (-3.0, 2.0)])
def test_log_ratio_needs_positive_values(actual, forecast):
    with pytest.raises(fm.FinancialMathError):
        fm.log_ratio(actual, forecast)


def test_margin_error_needs_a_revenue():
    with pytest.raises(fm.FinancialMathError):
        fm.margin_error(1.0, 2.0, 0.0)


def test_errors_apply_to_sample_arrays():
    import numpy as np

    revenue = fm.apply_revenue_error(100.0, np.array([0.0, math.log(1.1)]))
    assert revenue == pytest.approx([100.0, 110.0])
    assert fm.apply_margin_error(10.0, np.array([0.01, -0.02]), revenue) == pytest.approx(
        [11.0, 7.8]
    )


# -- reported ratios (backlog #140) -----------------------------------------------------------


def test_ratio_is_a_fraction_of_a_positive_base():
    # 20 / 100 = 0.2 (20%)
    assert fm.ratio(20, 100) == pytest.approx(0.2)
    assert fm.ratio(-5, 100) == pytest.approx(-0.05)  # a loss gives a negative margin


@pytest.mark.parametrize("base", [0, -100])
def test_ratio_refuses_a_base_at_or_below_zero(base):
    with pytest.raises(FinancialMathError):
        fm.ratio(20, base)


def test_growth():
    # 110 / 100 − 1 = 0.10
    assert fm.growth(110, 100) == pytest.approx(0.10)
    assert fm.growth(90, 100) == pytest.approx(-0.10)
    with pytest.raises(FinancialMathError):
        fm.growth(110, 0)


def test_net_debt_can_be_net_cash():
    # 200 − 60 = 140; 50 − 80 = −30 (net cash)
    assert fm.net_debt(200, 60) == 140
    assert fm.net_debt(50, 80) == -30
    with pytest.raises(FinancialMathError):
        fm.net_debt(-1, 0)


# -- sensitivity grid (backlog #142) ---------------------------------------------------------


def test_reinvestment_rate_and_the_return_it_implies():
    # NOPAT 100, FCFF 60: 40% reinvested; 4% growth at that rate implies a 10% return
    assert fm.reinvestment_rate(60.0, 100.0) == pytest.approx(0.4)
    assert fm.implied_ronic(0.04, 0.4) == pytest.approx(0.10)
    assert fm.reinvestment_rate(120.0, 100.0) == pytest.approx(-0.2)  # takes capital out


@pytest.mark.parametrize(
    "call",
    [
        lambda: fm.reinvestment_rate(10.0, 0.0),
        lambda: fm.reinvestment_rate(10.0, -5.0),
        lambda: fm.implied_ronic(0.04, 0.0),
        lambda: fm.implied_ronic(0.04, -0.2),
        lambda: fm.change_per_point(1.0, 2.0, 1.0, 0.01, 0.01),
        lambda: fm.change_per_point(1.0, 2.0, 0.0, -0.01, 0.01),
    ],
)
def test_sensitivity_helpers_refuse_meaningless_inputs(call):
    with pytest.raises(FinancialMathError):
        call()


def test_change_per_point():
    # 90 to 110 on a base of 100 over 2 points of the input: 10% a point
    assert fm.change_per_point(90.0, 110.0, 100.0, -0.01, 0.01) == pytest.approx(0.10)
    assert fm.change_per_point(110.0, 90.0, 100.0, -0.01, 0.01) == pytest.approx(-0.10)


def test_after_tax_cost_of_debt_is_the_wacc_with_no_equity_weight():
    assert fm.after_tax_cost_of_debt(0.06, 0.25) == pytest.approx(0.045)
    # the debt-only limit of the WACC is debt's after-tax cost
    assert fm.wacc(1e-12, 1.0, 0.10, 0.06, 0.25) == pytest.approx(0.045)


def test_wacc_keeps_its_m2_expression_bit_for_bit():
    """Stored runs reproduce bit for bit only if the WACC's float order never changes (#171)."""
    cases = [(1000.0, 500.0, 0.117, 0.037, 0.21), (3.1e12, 9.7e10, 0.1130, 0.0291, 0.19)]
    for e, d, ke, kd, t in cases:
        total = e + d
        assert fm.wacc(e, d, ke, kd, t) == e / total * ke + d / total * kd * (1 - t)


# -- relevering beta (backlog #170) -------------------------------------------------------------


def test_hamada_by_hand():
    # βu = 1.2 / (1 + 0.75 × 50/100) = 1.2 / 1.375
    assert fm.unlevered_beta(1.2, 50.0, 100.0, 0.25) == pytest.approx(1.2 / 1.375)
    # relevered at D/E = 1: βu × 1.75
    assert fm.relevered_beta(0.8, 100.0, 100.0, 0.25) == pytest.approx(1.4)


def test_no_debt_leaves_beta_unchanged():
    assert fm.unlevered_beta(1.1, 0.0, 100.0, 0.21) == 1.1
    assert fm.relevered_beta(1.1, 0.0, 100.0, 0.21) == 1.1


@pytest.mark.parametrize(
    "debt, equity, tax",
    [(-1.0, 100.0, 0.2), (10.0, 0.0, 0.2), (10.0, -5.0, 0.2), (10.0, 100.0, 1.0), (1, 2, -0.1)],
)
def test_relevering_refuses_meaningless_inputs(debt, equity, tax):
    for f in (fm.unlevered_beta, fm.relevered_beta):
        with pytest.raises(fm.FinancialMathError):
            f(1.0, debt, equity, tax)


def test_relevering_works_on_arrays():
    np = pytest.importorskip("numpy")
    betas = np.array([0.8, 1.0, 1.2])
    out = fm.relevered_beta(fm.unlevered_beta(betas, 50.0, 100.0, 0.2), 50.0, 100.0, 0.2)
    assert np.allclose(out, betas)
