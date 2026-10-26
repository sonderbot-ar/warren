"""Every formula against values small enough to check by hand (the comment shows the arithmetic)."""

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
