"""Shock time shape and magnitude sampling (M4, Build Plan tests)."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis import financial_math as fm
from domains.analysis.financial_math import FinancialMathError


def test_decay_one_is_constant_over_the_horizon_and_zero_after():
    assert fm.shock_shape(start=2, horizon=3, decay=1.0, quarters=6) == [0, 1, 1, 1, 0, 0]


def test_decay_half_halves_each_quarter():
    assert fm.shock_shape(start=1, horizon=4, decay=0.5, quarters=5) == [1, 0.5, 0.25, 0.125, 0]


@pytest.mark.parametrize(
    "start, horizon, decay", [(0, 1, 1.0), (1, 0, 1.0), (3, 3, 1.0), (1, 1, 0.0), (1, 1, 1.5)]
)
def test_invalid_shapes_are_refused(start, horizon, decay):
    with pytest.raises(FinancialMathError):
        fm.shock_shape(start, horizon, decay, quarters=4)


def test_split_normal_quantiles_are_low_base_high():
    # the 10th, 50th and 90th percentiles of z map exactly to low, base and high
    z = np.array([-fm.Z90, 0.0, fm.Z90])
    assert fm.split_normal(-6.0, -2.0, -1.0, z) == pytest.approx([-6.0, -2.0, -1.0])


def test_split_normal_sampled_percentiles_match_within_tolerance():
    z = np.random.default_rng(7).standard_normal(10_000)
    p10, p50, p90 = np.percentile(fm.split_normal(-6.0, -2.0, -1.0, z), [10, 50, 90])
    assert (p10, p50, p90) == pytest.approx((-6.0, -2.0, -1.0), abs=0.06)


def test_split_normal_point_range_is_constant():
    z = np.array([-3.0, 0.0, 2.0])
    assert list(fm.split_normal(1.5, 1.5, 1.5, z)) == [1.5, 1.5, 1.5]


def test_split_normal_refuses_unordered_range():
    with pytest.raises(FinancialMathError, match="low"):
        fm.split_normal(1.0, 0.0, 2.0, 0.5)


ordered = st.lists(st.floats(min_value=-500, max_value=500), min_size=3, max_size=3).map(sorted)
zs = st.lists(st.floats(min_value=-5, max_value=5), min_size=2, max_size=2).map(sorted)


@given(ordered, zs)
def test_split_normal_is_monotone_in_z(range_, pair):
    low, base, high = range_
    a, b = (fm.split_normal(low, base, high, z) for z in pair)
    assert a <= b


@given(ordered, st.floats(min_value=-5, max_value=5))
def test_split_normal_float_and_array_agree(range_, z):
    low, base, high = range_
    assert fm.split_normal(low, base, high, np.array([z]))[0] == pytest.approx(
        fm.split_normal(low, base, high, z)
    )
