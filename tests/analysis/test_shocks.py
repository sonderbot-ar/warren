"""Shocked driver paths (M4 Step 2)."""

import pytest
from pydantic import ValidationError

from domains.analysis import dcf, shocks
from domains.analysis.shocks import Shock
from tests.analysis.test_dcf import rows


def shock(**fields):
    values = {
        "shock_id": "s1",
        "driver": "revenue_growth",
        "low": -5.0,
        "base": -5.0,
        "high": -5.0,
        "start_period": 1,
        "horizon": 1,
        "decay": 1.0,
        "source": "user",
        "rationale": "test",
    }
    return Shock(**values | fields)


def shocked(*items, base_rows=None):
    inp = dcf.inputs(base_rows or rows())
    return dcf.compute(shocks.apply(inp, list(items)))


def test_zero_magnitude_reproduces_the_baseline_to_the_cent():
    baseline = dcf.value(rows(growth=0.03)).outputs()
    for driver in ("revenue_growth", "operating_margin", "capex_intensity", "risk_premium"):
        zero = shock(driver=driver, low=0.0, base=0.0, high=0.0, horizon=20)
        out = shocked(zero, base_rows=rows(growth=0.03)).outputs()
        assert out.keys() == baseline.keys()
        for key, value in baseline.items():
            assert out[key] == pytest.approx(value, abs=0.005), (driver, key)


def test_growth_shock_is_a_lasting_level_shift():
    # −5 points of growth in quarter 1 only: that quarter is 5% lower, and the same quarter a
    # year later grows (at 0%) from the lower base; the other quarters are untouched
    revenue = shocked(shock()).lines["revenue"]
    assert revenue[:8] == pytest.approx([95, 100, 100, 100, 95, 100, 100, 100])
    assert revenue[8] == pytest.approx(395)  # Y3 = the last four quarters, still lower


def test_a_year_takes_the_mean_of_its_quarters():
    # a margin shock in quarter 9 alone moves Y3's margin by a quarter of its size
    inp = shocks.apply(dcf.inputs(rows()), [shock(driver="operating_margin", start_period=9)])
    assert inp.driver["operating_margin"][8] == pytest.approx(0.20 - 0.05 / 4)
    assert inp.driver["operating_margin"][:8] == pytest.approx([0.20] * 8)
    assert inp.driver["operating_margin"][9:] == pytest.approx([0.20] * 2)


def test_shocks_on_one_driver_add_up():
    a, b = shock(shock_id="a", base=-1, low=-1, high=-1), shock(shock_id="b", low=2, base=2, high=2)
    inp = shocks.apply(dcf.inputs(rows()), [a, b])
    assert inp.driver["revenue_growth"][0] == pytest.approx(0.01)


def test_risk_premium_moves_only_the_discount_rate():
    base = dcf.value(rows())
    out = shocked(shock(driver="risk_premium", low=100, base=100, high=100, horizon=20))
    assert out.lines["fcff"] == pytest.approx(base.lines["fcff"])
    assert out.lines["discount_factor"][0] == pytest.approx(1.11**-0.25)
    assert out.value_per_share < base.value_per_share


def test_capex_shock_lowers_free_cash_flow():
    out = shocked(shock(driver="capex_intensity", low=1, base=1, high=1, horizon=2))
    # 1 point more capex on revenue of 100: free cash flow 15 → 14 in quarters 1 and 2
    assert out.lines["fcff"][:3] == pytest.approx([14, 14, 15])


@pytest.mark.parametrize(
    "fields",
    [
        {"driver": "beta"},
        {"low": 1.0, "base": 0.0, "high": 2.0},
        {"start_period": 0},
        {"start_period": 18, "horizon": 4},
        {"decay": 0.0},
        {"decay": 1.2},
        {"rationale": ""},
    ],
)
def test_invalid_shocks_are_refused(fields):
    with pytest.raises(ValidationError):
        shock(**fields)


def test_hash_changes_with_any_field():
    assert shocks.shocks_sha256([shock()]) != shocks.shocks_sha256([shock(decay=0.9)])


# -- level basis (M6): a revenue shock that moves revenue itself ---------------------------------


def seasonal(growth=0.05):
    return rows(growth=growth, seed=(30.0, 22.0, 22.0, 26.0))


@pytest.mark.parametrize("duration", [(1, 1.0), (8, 0.7), (8, 1.0)])
@pytest.mark.parametrize("start", [1, 4])
def test_a_level_shock_that_ends_returns_revenue_to_the_baseline(start, duration):
    horizon, decay = duration
    baseline = dcf.compute(dcf.inputs(seasonal())).lines["revenue"]
    s = shock(basis="level", low=-20, base=-20, high=-20, start_period=start, horizon=horizon,
              decay=decay)  # fmt: skip
    revenue = shocked(s, base_rows=seasonal()).lines["revenue"]
    effects = shocks.period_effects(s)
    for i, (b, r) in enumerate(zip(baseline, revenue, strict=True)):
        assert r == pytest.approx(b * (1 - 0.20 * effects[i]), rel=1e-12), i
    assert revenue[-1] == pytest.approx(baseline[-1], abs=0.005)  # Y5, to the cent


def test_a_permanent_level_shock_keeps_revenue_lower_in_y5():
    baseline = dcf.compute(dcf.inputs(seasonal())).lines["revenue"]
    s = shock(basis="level", low=-10, base=-10, high=-10, horizon=20)
    revenue = shocked(s, base_rows=seasonal()).lines["revenue"]
    assert revenue[-1] == pytest.approx(baseline[-1] * 0.9)


def test_a_level_shock_on_samples_keeps_each_sample_exact():
    np = pytest.importorskip("numpy")
    inp = dcf.inputs(seasonal())
    baseline = dcf.compute(inp).lines["revenue"]
    s = shock(basis="level", low=-30, base=-10, high=5, start_period=2, horizon=8, decay=0.7)
    sizes = np.array([-30.0, -10.0, 0.0, 5.0])
    revenue = dcf.compute(shocks.apply(inp, [s], [sizes])).lines["revenue"]
    effects = shocks.period_effects(s)
    for i, b in enumerate(baseline):
        assert revenue[i] == pytest.approx(b * (1 + sizes / 100 * effects[i]), rel=1e-12)
    assert revenue[-1] == pytest.approx(np.full(4, baseline[-1]), abs=0.005)


def test_level_and_growth_shocks_combine():
    growth_only = shocked(shock(), base_rows=seasonal()).lines["revenue"]
    both = shocked(shock(), shock(shock_id="s2", basis="level", low=-10, base=-10, high=-10),
                   base_rows=seasonal()).lines["revenue"]  # fmt: skip
    assert both[0] == pytest.approx(growth_only[0] * 0.9)
    assert both[1:] == pytest.approx(growth_only[1:])


@pytest.mark.parametrize(
    "fields",
    [
        {"basis": "level", "driver": "operating_margin"},
        {"basis": "level", "low": -100},
        {"basis": "price"},
    ],  # fmt: skip
)
def test_invalid_level_shocks_are_refused(fields):
    with pytest.raises(ValidationError):
        shock(**fields)


def test_a_growth_shock_hashes_as_before_the_basis_existed():
    s = shock()
    old = shocks.json.dumps([s.model_dump(exclude={"basis"})], sort_keys=True)
    assert shocks.shocks_sha256([s]) == shocks.hashlib.sha256(old.encode()).hexdigest()
    assert shocks.shocks_sha256([shock(basis="level")]) != shocks.shocks_sha256([s])
