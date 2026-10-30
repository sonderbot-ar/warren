"""Properties every DCF formula must keep for any reasonable input (Hypothesis tries many).

The hand-computed examples in test_financial_math.py check single values; these check the rules
that must hold between values, so a change that breaks the economics fails even if no example
happens to cover it.
"""

import pytest
from hypothesis import given
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


@given(cash_flows, rate, growth, st.floats(min_value=0.0005, max_value=0.005))
def test_higher_terminal_growth_never_lowers_value(flows, r, g, step):
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
