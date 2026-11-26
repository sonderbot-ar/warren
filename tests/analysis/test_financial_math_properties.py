"""Properties every DCF formula must keep for any reasonable input (Hypothesis tries many).

The hand-computed examples in test_financial_math.py check single values; these check the rules
that must hold between values, so a change that breaks the economics fails even if no example
happens to cover it.
"""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from domains.analysis import financial_math as fm

rate = st.floats(min_value=0.02, max_value=0.20)
growth = st.floats(min_value=-0.02, max_value=0.015)  # always below the lowest discount rate
cash_flow = st.floats(min_value=1.0, max_value=1e6)
cash_flows = st.lists(cash_flow, min_size=1, max_size=12)


@given(cash_flows, rate, st.floats(min_value=0.001, max_value=0.05), growth)
def test_higher_discount_rate_never_raises_value(flows, low, step, g):
    years = [1.0] * len(flows)
    low_value = fm.enterprise_value(flows, [low] * len(flows), years, g).enterprise_value
    high_rate = [low + step] * len(flows)
    high_value = fm.enterprise_value(flows, high_rate, years, g).enterprise_value
    assert high_value <= low_value


@given(cash_flows, rate, growth, st.floats(min_value=0.0005, max_value=0.004))
def test_higher_terminal_growth_never_lowers_value(flows, r, g, step):
    # growth tops out at 0.015 and the step at 0.004, so g + step stays below the lowest rate
    years = [1.0] * len(flows)
    rates = [r] * len(flows)
    low = fm.enterprise_value(flows, rates, years, g).enterprise_value
    high = fm.enterprise_value(flows, rates, years, g + step).enterprise_value
    assert high >= low


@given(cash_flow, rate, st.integers(min_value=1, max_value=10))
def test_zero_growth_constant_cash_flow_is_a_perpetuity(cf, r, n):
    # with no growth, any explicit horizon plus the terminal value adds up to CF / r
    value = fm.enterprise_value([cf] * n, [r] * n, [1.0] * n, 0.0).enterprise_value
    assert value == pytest.approx(cf / r, rel=1e-9)


@given(st.lists(st.tuples(rate, st.sampled_from([0.25, 1.0])), min_size=1, max_size=12))
def test_discount_factors_fall_and_stay_in_zero_one(periods):
    rates, years = zip(*periods, strict=True)
    factors = fm.discount_factors(list(rates), list(years))
    assert all(0 < f <= 1 for f in factors)
    assert all(later < earlier for earlier, later in zip(factors, factors[1:], strict=False))


@given(st.floats(min_value=1.0, max_value=1e9), rate, st.floats(0, 3), st.floats(0, 3))
def test_rolling_forward_in_two_steps_equals_one_step(value, r, a, b):
    two_steps = fm.roll_forward(fm.roll_forward(value, r, a), r, b)
    assert two_steps == pytest.approx(fm.roll_forward(value, r, a + b), rel=1e-9)


@given(
    st.floats(min_value=1.0, max_value=1e12),
    st.floats(min_value=0.0, max_value=1e12),
    st.floats(min_value=0.03, max_value=0.20),
    st.floats(min_value=0.0, max_value=0.15),
    st.floats(min_value=0.0, max_value=0.5),
)
def test_wacc_lies_between_its_two_costs(equity, debt, cost_equity, cost_debt, tax):
    after_tax_debt = cost_debt * (1 - tax)
    value = fm.wacc(equity, debt, cost_equity, cost_debt, tax)
    low, high = min(cost_equity, after_tax_debt), max(cost_equity, after_tax_debt)
    assert low - 1e-12 <= value <= high + 1e-12


@given(st.lists(cash_flow, min_size=4, max_size=4), st.integers(min_value=1, max_value=12))
def test_compound_with_zero_growth_repeats_the_seed(seed, n):
    projected = fm.compound(seed, [0.0] * n, lag=4)
    assert projected == pytest.approx([seed[i % 4] for i in range(n)])


@given(cash_flow, rate, growth)
def test_value_driver_form_is_the_perpetuity_it_comes_from(nopat, r, g):
    # with RONIC = WACC, g / WACC of NOPAT is reinvested; Gordon on what is left gives the same
    # value as NOPAT × (1 + g) / WACC (Koller, Goedhart and Wessels, ch. 14)
    free_cash_flow = nopat * (1 - g / r)
    gordon = fm.gordon_terminal_value(free_cash_flow, r, g)
    assert fm.value_driver_terminal_value(nopat, r, g) == pytest.approx(gordon, rel=1e-9)


@given(cash_flow, rate, st.floats(min_value=0.0, max_value=0.10))
def test_both_terminal_rules_refuse_growth_at_or_above_the_rate(cf, r, extra):
    # backlog #79: neither perpetuity converges at g ≥ WACC
    for formula in (fm.gordon_terminal_value, fm.value_driver_terminal_value):
        with pytest.raises(fm.FinancialMathError) as caught:
            formula(cf, r, r + extra)
        assert caught.value.reason == "growth_not_below_rate"


# -- M9: forecast errors and ranges ------------------------------------------------------------

money = st.floats(min_value=1.0, max_value=1e12)
signed_money = st.floats(min_value=-1e11, max_value=1e11)


@given(money, money)
def test_revenue_error_round_trips_to_the_actual(actual, forecast):
    error = fm.log_ratio(actual, forecast)
    assert fm.apply_revenue_error(forecast, error) == pytest.approx(actual, rel=1e-9)


@given(signed_money, signed_money, money, money)
def test_margin_error_round_trips_to_the_actual(actual_ebit, forecast_ebit, actual_rev, fc_rev):
    error = fm.margin_error(actual_ebit, forecast_ebit, actual_rev)
    revenue = fm.apply_revenue_error(fc_rev, fm.log_ratio(actual_rev, fc_rev))
    back = fm.apply_margin_error(forecast_ebit, error, revenue)
    assert back == pytest.approx(actual_ebit, rel=1e-9, abs=1e-3)


@given(money, st.floats(min_value=-5.0, max_value=5.0), st.floats(min_value=0.001, max_value=1.0))
def test_revenue_range_is_positive_and_monotone_in_the_error(forecast, error, step):
    low = fm.apply_revenue_error(forecast, error)
    assert low > 0
    assert fm.apply_revenue_error(forecast, error + step) > low


amount = st.floats(min_value=0.0, max_value=1e12)
positive = st.floats(min_value=1e-3, max_value=1e12)


@given(positive)
def test_growth_of_a_value_over_itself_is_zero(x):
    assert fm.growth(x, x) == pytest.approx(0.0)


@given(amount, positive)
def test_ratio_times_its_base_gives_the_numerator_back(part, whole):
    assert fm.ratio(part, whole) * whole == pytest.approx(part)


@given(amount, amount)
def test_net_debt_is_debt_less_cash(debt, cash):
    assert fm.net_debt(debt, cash) == pytest.approx(debt - cash)


def test_reported_ratios_work_on_sample_arrays():
    import numpy as np

    assert fm.ratio(np.array([1.0, 2.0]), np.array([4.0, 4.0])).tolist() == [0.25, 0.5]
    with pytest.raises(fm.FinancialMathError):
        fm.ratio(np.array([1.0]), np.array([0.0]))


beta = st.floats(min_value=0.2, max_value=2.5)
money = st.floats(min_value=1.0, max_value=1e12)
tax = st.floats(min_value=0.0, max_value=0.45)


@given(beta, st.floats(min_value=0.0, max_value=1e12), money, tax)
def test_unlever_then_relever_at_the_same_structure_gives_beta_back(b, d, e, t):
    assert fm.relevered_beta(fm.unlevered_beta(b, d, e, t), d, e, t) == pytest.approx(b, rel=1e-12)


@given(beta, st.floats(min_value=0.0, max_value=1e12), money, tax, st.floats(0.01, 1e11))
def test_more_debt_never_lowers_the_equity_beta(b, d, e, t, more):
    assert fm.relevered_beta(b, d + more, e, t) >= fm.relevered_beta(b, d, e, t)


@given(beta, st.floats(min_value=1.0, max_value=1e12), money, tax, st.floats(0.01, 0.4))
def test_a_higher_tax_rate_never_raises_the_relevered_beta(b, d, e, t, step):
    assert fm.relevered_beta(b, d, e, t + step) <= fm.relevered_beta(b, d, e, t)


@given(beta, st.floats(min_value=0.0, max_value=1e12), money, rate, rate)
def test_no_tax_and_riskless_debt_keep_wacc_whatever_the_debt(bu, d, e, rf, erp):
    """Modigliani–Miller without taxes, in Hamada's world (debt beta 0, so debt costs rf)."""
    unlevered_cost = fm.capm_cost_of_equity(rf, bu, erp)
    ke = fm.capm_cost_of_equity(rf, fm.relevered_beta(bu, d, e, 0.0), erp)
    assert fm.wacc(e, d, ke, rf, 0.0) == pytest.approx(unlevered_cost, rel=1e-9)


# -- pooled ratio and mean (backlog #477) ---------------------------------------------------------

base = st.floats(min_value=1.0, max_value=1e6)
share = st.floats(min_value=-0.5, max_value=0.9)
periods = st.lists(st.tuples(share, base), min_size=1, max_size=10)


@given(periods)
def test_a_pooled_ratio_lies_between_the_smallest_and_largest_period_ratio(rows):
    numerators = [r * b for r, b in rows]
    bases = [b for _r, b in rows]
    pooled = fm.pooled_ratio(numerators, bases)
    ratios = [n / b for n, b in zip(numerators, bases, strict=True)]
    assert min(ratios) - 1e-12 <= pooled <= max(ratios) + 1e-12


@given(periods, st.floats(min_value=0.01, max_value=100.0))
def test_a_pooled_ratio_does_not_depend_on_the_unit(rows, scale):
    numerators = [r * b for r, b in rows]
    bases = [b for _r, b in rows]
    scaled = fm.pooled_ratio([n * scale for n in numerators], [b * scale for b in bases])
    assert scaled == pytest.approx(fm.pooled_ratio(numerators, bases), rel=1e-9, abs=1e-12)


@given(st.lists(share, min_size=1, max_size=10), base)
def test_equal_bases_make_the_pooled_ratio_the_mean(ratios, b):
    pooled = fm.pooled_ratio([r * b for r in ratios], [b] * len(ratios))
    assert pooled == pytest.approx(fm.mean(ratios), rel=1e-9, abs=1e-12)


@given(share, base)
def test_one_period_pools_to_its_own_ratio(r, b):
    assert fm.pooled_ratio([r * b], [b]) == pytest.approx(r, rel=1e-12, abs=1e-15)


@given(st.lists(share, min_size=1, max_size=10))
def test_the_mean_lies_between_the_smallest_and_largest_value(values):
    assert min(values) - 1e-12 <= fm.mean(values) <= max(values) + 1e-12


@given(periods)
def test_a_pooled_ratio_is_the_ratios_weighted_by_each_periods_share_of_the_base(rows):
    # Σn/Σb = Σ (b_i/Σb)·(n_i/b_i): a larger base weighs more (Cochran 1977, ch. 6)
    numerators = [r * b for r, b in rows]
    bases = [b for _r, b in rows]
    total = sum(bases)
    weighted = sum(b / total * (n / b) for n, b in zip(numerators, bases, strict=True))
    assert fm.pooled_ratio(numerators, bases) == pytest.approx(weighted, rel=1e-9, abs=1e-12)


# -- beta's standard error (backlog #481) ---------------------------------------------------------

_returns = st.lists(st.floats(-0.2, 0.2, allow_nan=False), min_size=5, max_size=60)


def _spread(xs):
    return max(xs) - min(xs) > 1e-3


@given(_returns, _returns)
def test_beta_std_error_is_not_negative(stock, market):
    n = min(len(stock), len(market))
    stock, market = stock[:n], market[:n]
    if not _spread(market):
        return
    assert fm.ols_beta_std_error(stock, market) >= 0


@given(_returns, st.floats(-3, 3), st.floats(-0.01, 0.01))
def test_beta_std_error_is_zero_on_an_exact_line(market, beta, alpha):
    if not _spread(market):
        return
    stock = [alpha + beta * m for m in market]
    assert fm.ols_beta_std_error(stock, market) == pytest.approx(0, abs=1e-9)


@given(_returns, _returns, st.floats(-0.05, 0.05), st.floats(-0.05, 0.05))
def test_beta_std_error_ignores_a_constant_added_to_either_series(stock, market, a, b):
    n = min(len(stock), len(market))
    stock, market = stock[:n], market[:n]
    if not _spread(market):
        return
    se = fm.ols_beta_std_error(stock, market)
    shifted = fm.ols_beta_std_error([s + a for s in stock], [m + b for m in market])
    assert shifted == pytest.approx(se, rel=1e-6, abs=1e-9)


@given(_returns, _returns, st.floats(0.1, 10))
def test_beta_std_error_scales_with_the_stock_series(stock, market, k):
    n = min(len(stock), len(market))
    stock, market = stock[:n], market[:n]
    if not _spread(market):
        return
    se = fm.ols_beta_std_error(stock, market)
    assert fm.ols_beta_std_error([k * s for s in stock], market) == pytest.approx(
        k * se, rel=1e-6, abs=1e-9
    )


def test_beta_std_error_by_hand():
    # x = 1..5, y = 2, 4, 5, 4, 5: slope 0.6, residuals sum of squares 2.4,
    # Sxx 10, so se = sqrt(2.4 / 3 / 10) = sqrt(0.08)
    x, y = [1, 2, 3, 4, 5], [2, 4, 5, 4, 5]
    assert fm.ols_beta(y, x) == pytest.approx(0.6)
    assert fm.ols_beta_std_error(y, x) == pytest.approx(0.08**0.5)


def test_blume_std_error_is_the_weight_times_the_raw_one():
    assert fm.blume_adjusted_std_error(0.3) == pytest.approx(fm.BLUME_WEIGHT * 0.3)
    # the adjustment's slope, read off blume_adjusted_beta itself
    slope = fm.blume_adjusted_beta(1.3) - fm.blume_adjusted_beta(0.3)
    assert fm.blume_adjusted_std_error(1.0) == pytest.approx(slope)


def test_beta_std_error_refuses_what_ols_beta_refuses():
    with pytest.raises(fm.FinancialMathError):
        fm.ols_beta_std_error([0.1, 0.2], [0.1, 0.2])
    with pytest.raises(fm.FinancialMathError):
        fm.ols_beta_std_error([0.1, 0.2, 0.3], [0.0, 0.0, 0.0])


# -- a blend of two stated rates (backlog #543) ---------------------------------------------------

_stated = st.floats(min_value=0.0, max_value=0.15)
_amount = st.floats(min_value=0.0, max_value=1e6)


@given(_stated, _amount, _stated, _amount)
@example(0.125, 5e-324, 0.125, 0.0)  # rate × amount underflows to zero (CI, PR #609)
def test_a_blended_rate_lies_between_its_two_rates(long_rate, long_amount, short_rate, short):
    if long_amount + short <= 0:
        with pytest.raises(fm.FinancialMathError):
            fm.blended_rate(long_rate, long_amount, short_rate, short)
        return
    got = fm.blended_rate(long_rate, long_amount, short_rate, short)
    assert min(long_rate, short_rate) - 1e-12 <= got <= max(long_rate, short_rate) + 1e-12


@given(_stated, st.floats(min_value=1.0, max_value=1e6), _stated)
def test_a_blend_with_one_amount_zero_is_the_other_rate(long_rate, amount, short_rate):
    assert fm.blended_rate(long_rate, amount, short_rate, 0.0) == pytest.approx(long_rate)
    assert fm.blended_rate(long_rate, 0.0, short_rate, amount) == pytest.approx(short_rate)


@given(_stated, _amount, _stated, _amount, st.floats(min_value=0.001, max_value=1000))
def test_a_blend_does_not_depend_on_the_unit(long_rate, long_amount, short_rate, short, scale):
    if long_amount + short < 1.0:
        return
    assert fm.blended_rate(
        long_rate, long_amount * scale, short_rate, short * scale
    ) == pytest.approx(fm.blended_rate(long_rate, long_amount, short_rate, short), abs=1e-12)


def test_a_blend_refuses_a_negative_amount():
    with pytest.raises(fm.FinancialMathError):
        fm.blended_rate(0.03, -1.0, 0.01, 5.0)
