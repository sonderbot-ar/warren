"""From classes to numbers: σ, sizes, timing and bounds (M6 Step 5)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis import dcf
from domains.analysis import shocks as m4
from domains.llm import scales
from tests.analysis.test_dcf import rows

TABLE = scales.load_scales()


def with_changes(points: list[float]) -> list[float]:
    """A series whose four-quarter changes are `points`, in points."""
    series = [0.0] * 4
    for p in points:
        series.append(series[-4] + p / 100)
    return series


def test_sigma_is_the_scaled_median_absolute_deviation_by_hand():
    # changes 1..12 points: median 6.5, absolute deviations 0.5..5.5, their median 3.0
    series = with_changes(list(range(1, 13)))
    s = scales.sigma("operating_margin", series, TABLE)
    assert s.value == pytest.approx(1.4826 * 3.0) and s.flag is None
    assert s.changes == pytest.approx(list(range(1, 13)))


def test_one_outlier_quarter_barely_moves_sigma():
    series = with_changes(list(range(1, 13)))
    spiked = with_changes([*range(1, 12), -60])  # a 60-point impairment quarter
    calm, odd = (scales.sigma("operating_margin", s, TABLE).value for s in (series, spiked))
    assert abs(odd - calm) / calm < 0.15


@pytest.mark.parametrize(
    ("series", "flag", "value"),
    [
        ([0.1] * 10, "fallback", 1.0),
        ([0.2] * 16, "floored", 0.2),
        (with_changes([60, -60] * 6), "capped", 5.0),
    ],  # fmt: skip
)
def test_fallback_floor_and_cap_are_flagged(series, flag, value):
    s = scales.sigma("operating_margin", series, TABLE)
    assert (s.flag, s.value) == (flag, value)


def test_risk_premium_sigma_is_the_stated_basis_points():
    assert scales.sigma("risk_premium", [], TABLE).value == 25


def test_sizes_and_ranges_follow_the_table():
    assert scales.magnitudes("down", "small", 2.0, TABLE) == (-2.5, -1.0, 0.5)  # crosses zero
    assert scales.magnitudes("up", "large", 2.0, TABLE) == (2.5, 4.0, 5.5)
    low, base, high = scales.magnitudes("down", "medium", 2.0, TABLE)
    assert high - low == pytest.approx(2 * 0.75 * 2.0)


def test_permanent_reaches_quarter_20_and_the_rest_follow_the_table():
    for start in range(1, 5):
        horizon, decay = scales.timing("permanent", start)
        assert start + horizon - 1 == 20 and decay == 1.0
    assert scales.timing("fading", 2) == (8, 0.7)
    assert scales.timing("one_quarter", 4) == (1, 1.0)


BASE = dcf.inputs(rows(growth=0.03))


@given(
    driver=st.sampled_from(["revenue_growth", "operating_margin", "capex_intensity",
                            "risk_premium"]),
    direction=st.sampled_from(["up", "down"]),
    size=st.sampled_from(["small", "medium", "large"]),
    duration=st.sampled_from(["one_quarter", "fading", "lasting", "permanent"]),
    start=st.integers(1, 4),
    value=st.floats(0.1, 10.0),
)  # fmt: skip
def test_every_class_combination_gives_a_valid_m4_shock(driver, direction, size, duration, start,
                                                         value):  # fmt: skip
    s = scales.Sigma(value, None, [])
    bounds = scales.Bounds(margin=(0.0, 0.4))
    sized = scales.size_shock(driver, direction, size, duration, start, s, BASE, bounds, TABLE)
    shock = sized.shock("p1", driver, start, "e1", "test")
    assert shock.basis == ("level" if driver == "revenue_growth" else "growth")
    shocked = m4.apply(BASE, [shock])
    if driver == "capex_intensity":
        assert min(shocked.driver["capex_pct"]) >= -1e-12


def test_a_capex_cut_that_would_go_below_zero_is_clipped_and_flagged():
    inp = dcf.inputs(rows())  # capex 5% of revenue
    s = scales.Sigma(3.0, "capped", [])
    sized = scales.size_shock("capex_intensity", "down", "large", "lasting", 1, s, inp,
                              scales.Bounds(), TABLE)  # fmt: skip
    assert sized.clipped and sized.base > -6.0
    reach = sized.base - scales.Z99_OVER_Z90 * (sized.base - sized.low)
    assert 5.0 + reach >= -1e-9  # the 1st percentile stays at zero or above


def test_a_small_shock_inside_the_bounds_is_not_clipped():
    sized = scales.size_shock("operating_margin", "down", "small", "fading", 1,
                              scales.Sigma(1.0, None, []), BASE, scales.Bounds(margin=(0.1, 0.3)),
                              TABLE)  # fmt: skip
    assert not sized.clipped and sized.base == -0.5


def test_a_down_shock_is_not_cut_by_its_upper_tail():
    # baseline margin 20%, band top at 20.1%: a medium cut only moves away from the top
    sized = scales.size_shock("operating_margin", "down", "medium", "lasting", 1,
                              scales.Sigma(1.0, None, []), BASE, scales.Bounds(margin=(0.0, 0.201)),
                              TABLE)  # fmt: skip
    assert not sized.clipped and sized.base == -1.0
