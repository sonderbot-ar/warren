import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis.dcf import DCFInputError
from domains.analysis.schemas import SINGLE, Assumption

SEED_PERIODS = ["FY2023Q3", "FY2023Q4", "FY2024Q1", "FY2024Q2"]
QUARTERS = [
    "FY2024Q3",
    "FY2024Q4",
    "FY2025Q1",
    "FY2025Q2",
    "FY2025Q3",
    "FY2025Q4",
    "FY2026Q1",
    "FY2026Q2",
]
PERIODS = QUARTERS + list(dcf.YEARS)


def row(name, value, period=SINGLE):
    return Assumption(name=name, period=period, value=value, source="computed", method="test")


def rows(growth=0.0, seed=(100, 100, 100, 100), nwc_pct=0.0, **single):
    """No reinvestment (D&A = capex), 20% margin, 25% tax, a 10% cost of capital, no debt."""
    values = {
        "risk_free": 0.04,
        "beta": 1.0,
        "erp": 0.06,
        "cost_of_debt": 0.05,
        "debt_tax_rate": 0.25,
        "equity_market_value": 1000.0,
        "debt": 0.0,
        "cash_and_investments": 50.0,
        "minority_interest": 10.0,
        "shares": 10.0,
        "terminal_growth": 0.0,
        "roll_years": 0.0,
    } | single
    out = [row(dcf.SEED, v, p) for p, v in zip(SEED_PERIODS, seed, strict=True)]
    for period in PERIODS:
        out += [
            row("revenue_growth", growth, period),
            row("operating_margin", 0.20, period),
            row("tax_rate", 0.25, period),
            row("da_pct", 0.05, period),
            row("capex_pct", 0.05, period),
            row("nwc_pct", nwc_pct, period),
        ]
    return out + [row(name, v) for name, v in values.items()]


def test_no_growth_no_reinvestment_is_a_perpetuity_on_the_period_grid():
    valuation = dcf.value(rows())
    assert valuation.cost_of_equity == pytest.approx(0.10)  # 4% + 1.0 × 6%
    assert valuation.wacc == pytest.approx(0.10)  # no debt
    # each quarter: 100 × 20% × (1 − 25%) = 15; each year: 60; terminal value 60 / 10% = 600
    assert valuation.lines["fcff"] == pytest.approx([15] * 8 + [60] * 3)
    v = 1 / 1.1
    expected = sum(15 * v ** (k / 4) for k in range(1, 9)) + 60 * (v**3 + v**4 + v**5)
    expected += 600 * v**5
    assert valuation.dcf.enterprise_value == pytest.approx(expected)
    # equity = EV − (debt 0 − cash 50) − minority 10; per share over 10 shares
    assert valuation.equity_value == pytest.approx(expected + 50 - 10)
    assert valuation.value_per_share == pytest.approx((expected + 40) / 10)


def test_quarters_grow_from_the_same_quarter_a_year_earlier():
    valuation = dcf.value(rows(growth=0.10, seed=(80, 120, 90, 110)))
    revenue = valuation.lines["revenue"]
    assert revenue[:4] == pytest.approx([88, 132, 99, 121])
    assert revenue[4:8] == pytest.approx([96.8, 145.2, 108.9, 133.1])
    # Y3 is the last four quarters × 1.10
    assert revenue[8] == pytest.approx((96.8 + 145.2 + 108.9 + 133.1) * 1.1)


def test_working_capital_follows_trailing_revenue():
    valuation = dcf.value(rows(growth=0.10, nwc_pct=0.5))
    # Q1: trailing revenue 100 + 100 + 100 + 110 = 410 vs 400 before: ΔNWC = 0.5 × 10
    assert valuation.lines["delta_nwc"][0] == pytest.approx(5)
    # 8th quarter: trailing 4 × 121 = 484; Y3 = 484 × 1.1 = 532.4: ΔNWC = 0.5 × 48.4
    assert valuation.lines["delta_nwc"][8] == pytest.approx(0.5 * (532.4 - 484))


def test_a_higher_discount_rate_never_raises_value():
    low = dcf.value(rows(erp=0.04)).value_per_share
    high = dcf.value(rows(erp=0.08)).value_per_share
    assert high < low


def test_value_is_carried_forward_to_the_as_of_date():
    base = dcf.value(rows())
    later = dcf.value(rows(roll_years=0.5))
    assert later.enterprise_value_as_of == pytest.approx(base.dcf.enterprise_value * 1.1**0.5)


def test_with_value_replaces_one_assumption():
    changed = dcf.with_value(rows(), "erp", 0.08)
    assert dcf.value(changed).cost_of_equity == pytest.approx(0.12)
    with pytest.raises(DCFInputError, match="no single-valued"):
        dcf.with_value(rows(), "revenue_growth", 0.1)


def test_incomplete_rows_are_rejected():
    without_beta = [a for a in rows() if a.name != "beta"]
    with pytest.raises(DCFInputError, match="beta"):
        dcf.value(without_beta)
    short = [a for a in rows() if a.period != "Y5"]
    with pytest.raises(DCFInputError, match="forecast periods"):
        dcf.value(short)
    with pytest.raises(DCFInputError, match="two rows"):
        dcf.value(rows() + [row("beta", 1.2)])


def test_outputs_hold_every_line_and_the_bridge():
    outputs = dcf.value(rows()).outputs()
    assert outputs[("fcff", "Y5")] == pytest.approx(60)
    assert ("value_per_share", SINGLE) in outputs
    assert len(outputs) == len(dcf.LINES) * len(PERIODS) + 11


def test_run_outputs_add_the_erp_sensitivity():
    out = dcf.run_outputs(rows() + [row("erp_std_error", 0.02)])
    base = out[("value_per_share", SINGLE)]
    low, high = (
        out[("value_per_share_erp_minus_1se", SINGLE)],
        out[("value_per_share_erp_plus_1se", SINGLE)],
    )
    assert high < base < low
    assert low == pytest.approx(dcf.value(rows(erp=0.04)).value_per_share)
    with pytest.raises(DCFInputError, match="erp_std_error"):
        dcf.run_outputs(rows())


def test_a_sensitivity_without_a_value_is_left_out():
    # ERP − 1 SE = 0: cost of capital 4% = terminal growth 4%, so no terminal value
    out = dcf.run_outputs(rows(terminal_growth=0.04) + [row("erp_std_error", 0.06)])
    assert ("value_per_share_erp_minus_1se", SINGLE) not in out
    assert ("value_per_share_erp_plus_1se", SINGLE) in out


def test_value_driver_terminal_value_by_hand():
    # NOPAT in Y5 = 100 × 4 × 20% × (1 − 25%) = 60; g = 2%, WACC 10%: TV = 60 × 1.02 / 0.10 = 612
    method = Assumption(
        name="terminal_method",
        period=SINGLE,
        value=None,
        source="user",
        method="value_driver_ronic_wacc: set by test",
    )
    valuation = dcf.value(rows(terminal_growth=0.02) + [method])
    assert valuation.dcf.terminal_value == pytest.approx(612)
    # without the row (a run stored before M4), Gordon on FCFF: 60 × 1.02 / 0.08
    assert dcf.value(rows(terminal_growth=0.02)).dcf.terminal_value == pytest.approx(765)


def test_unknown_terminal_method_is_refused():
    bad = Assumption(name="terminal_method", period=SINGLE, value=None, source="user", method="x")
    with pytest.raises(DCFInputError, match="terminal_method"):
        dcf.value(rows() + [bad])


# -- why a sensitivity has no value (backlog #9) -----------------------------------------------

VALUE_DRIVER_ROW = Assumption(
    name="terminal_method",
    period=SINGLE,
    value=None,
    source="user",
    method="value_driver_ronic_wacc: set by test",
)
MINUS = ("value_per_share_erp_minus_1se", SINGLE)


def test_a_gordon_gap_says_wacc_at_terminal_growth():
    # ERP − 1 SE = 0: cost of capital 4% = terminal growth 4% under Gordon
    out, gaps = dcf.outputs_and_gaps(rows(terminal_growth=0.04) + [row("erp_std_error", 0.06)])
    assert MINUS not in out and set(gaps) == {MINUS}
    assert gaps[MINUS].reason == "growth_not_below_rate"
    assert "terminal growth" in gaps[MINUS].detail


def test_a_value_driver_gap_says_wacc_at_or_below_zero():
    # ERP − 1 SE = 0.06 − 0.12 = −6%: cost of equity 4% − 6% = −2%, no debt, so WACC −2%
    out, gaps = dcf.outputs_and_gaps(
        rows(terminal_growth=0.04) + [row("erp_std_error", 0.12), VALUE_DRIVER_ROW]
    )
    assert gaps[MINUS].reason == "rate_not_positive"
    assert ("value_per_share_erp_plus_1se", SINGLE) in out


def test_a_value_driver_gap_at_wacc_equal_to_growth():
    # ERP − 1 SE = 0: cost of capital 4% = terminal growth 4%; the value-driver perpetuity does
    # not converge there, so no value, as under Gordon (backlog #79)
    out, gaps = dcf.outputs_and_gaps(
        rows(terminal_growth=0.04) + [row("erp_std_error", 0.06), VALUE_DRIVER_ROW]
    )
    assert MINUS not in out and gaps[MINUS].reason == "growth_not_below_rate"
    assert ("value_per_share", SINGLE) in out


def test_no_gap_when_both_sensitivities_have_a_value():
    _out, gaps = dcf.outputs_and_gaps(rows() + [row("erp_std_error", 0.02)])
    assert gaps == {}


def test_a_bad_input_in_a_sensitivity_stops_instead_of_becoming_a_gap(monkeypatch):
    calls = []
    real = dcf.value

    def second_call_fails(assumptions):
        calls.append(1)
        if len(calls) == 2:
            raise fm.FinancialMathError("share count must be positive, got 0")
        return real(assumptions)

    monkeypatch.setattr(dcf, "value", second_call_fails)
    with pytest.raises(fm.FinancialMathError, match="share count"):
        dcf.outputs_and_gaps(rows() + [row("erp_std_error", 0.02)])


def test_discount_rates_are_the_wacc_per_period_with_its_shift():
    # equity 1000, debt 500: weights 2/3 and 1/3; cost of equity 4% + 1.0 × 6% = 10%;
    # debt 5% × (1 − 25%) = 3.75%, so WACC = 2/3 × 10% + 1/3 × 3.75% = 7.9167% (backlog #90)
    inp = dcf.inputs(rows(debt=500.0))
    by_hand = 2 / 3 * 0.10 + 1 / 3 * 0.05 * 0.75
    assert dcf.discount_rates(inp) == pytest.approx([by_hand] * 11)
    assert dcf.base_wacc(inp) == pytest.approx(by_hand)
    # +200 bp on the cost of equity in the second quarter only moves that quarter, by 2/3 × 2%
    shifted = inp.replace(cost_of_equity_shift=[0.0, 0.02] + [0.0] * 9)
    rates = dcf.discount_rates(shifted)
    assert rates[1] == pytest.approx(by_hand + 2 / 3 * 0.02)
    assert rates[:1] + rates[2:] == pytest.approx([by_hand] * 10)
    assert dcf.compute(shifted).wacc == pytest.approx(by_hand)  # the run's WACC is unshifted


# -- WACC set directly, in memory (the sensitivity grid, backlog #142) ------------------------


@pytest.mark.parametrize("method", [dcf.GORDON, dcf.VALUE_DRIVER])
def test_an_override_equal_to_the_runs_wacc_changes_nothing(method):
    inp = dcf.inputs(rows(growth=0.01, debt=500.0, roll_years=0.4)).replace(terminal_method=method)
    plain = dcf.compute(inp).outputs()
    same = dcf.compute(inp.replace(wacc_override=dcf.base_wacc(inp))).outputs()
    assert same == plain  # bit for bit, not approximately


@pytest.mark.parametrize("method", [dcf.GORDON, dcf.VALUE_DRIVER])
def test_an_override_replaces_every_rate_and_the_roll_forward(method):
    inp = dcf.inputs(rows(debt=500.0, roll_years=0.5)).replace(terminal_method=method)
    out = dcf.compute(inp.replace(wacc_override=0.12))
    assert dcf.discount_rates(inp.replace(wacc_override=0.12)) == [0.12] * 11
    assert out.wacc == 0.12
    assert out.cost_of_equity == dcf.compute(inp).cost_of_equity  # the cost of equity is held
    assert out.enterprise_value_as_of == pytest.approx(out.dcf.enterprise_value * 1.12**0.5)
    assert out.lines["fcff"] == dcf.compute(inp).lines["fcff"]  # cash flows are held


@pytest.mark.parametrize("method", [dcf.GORDON, dcf.VALUE_DRIVER])
def test_a_higher_override_lowers_value_per_share(method):
    inp = dcf.inputs(rows(growth=0.01)).replace(terminal_method=method)
    values = [dcf.compute(inp.replace(wacc_override=w)).value_per_share for w in (0.07, 0.09, 0.11)]
    assert values[0] > values[1] > values[2]


def test_an_override_and_a_cost_of_equity_shift_are_refused_together():
    inp = dcf.inputs(rows()).replace(wacc_override=0.1, cost_of_equity_shift=[0.0] * 11)
    with pytest.raises(DCFInputError, match="different questions"):
        dcf.compute(inp)


@settings(max_examples=60, deadline=None)
@given(
    st.floats(min_value=-0.05, max_value=0.15),
    st.floats(min_value=0.3, max_value=2.0),
    st.floats(min_value=0.0, max_value=2000.0),
    st.floats(min_value=0.0, max_value=0.03),
    st.sampled_from([dcf.GORDON, dcf.VALUE_DRIVER]),
)
def test_property_the_runs_own_wacc_as_override_is_the_run(growth, beta, debt, g, method):
    inp = dcf.inputs(rows(growth=growth, beta=beta, debt=debt, terminal_growth=g))
    inp = inp.replace(terminal_method=method)
    assert dcf.compute(inp.replace(wacc_override=dcf.base_wacc(inp))).outputs() == (
        dcf.compute(inp).outputs()
    )


# -- WACC set directly as a stored row (a what-if child, backlog #171) ---------------------------


@pytest.mark.parametrize("method", [dcf.GORDON, dcf.VALUE_DRIVER])
def test_a_wacc_row_values_as_the_in_memory_override(method):
    base = rows(growth=0.01, debt=500.0, roll_years=0.4)
    inp = dcf.inputs(base).replace(terminal_method=method)
    with_row = dcf.inputs(base + [row("wacc", 0.11)]).replace(terminal_method=method)
    assert with_row.wacc_override == 0.11
    assert dcf.compute(with_row).outputs() == dcf.compute(inp.replace(wacc_override=0.11)).outputs()


def test_rows_without_a_wacc_row_are_valued_as_before():
    base = rows(growth=0.01, debt=500.0, erp_std_error=0.02)
    assert dcf.inputs(base).wacc_override is None
    assert not dcf.wacc_is_set(base)
    out, _gaps = dcf.outputs_and_gaps(base)
    assert ("value_per_share_erp_minus_1se", SINGLE) in out
    # bit for bit: the stored row set without `wacc` values as the plain computed WACC
    assert dcf.compute(dcf.inputs(base)).outputs() == dcf.value(base).outputs()
    inp = dcf.inputs(base)
    one = inp.one
    expected = fm.wacc(
        one["equity_market_value"],
        one["debt"],
        fm.capm_cost_of_equity(one["risk_free"], one["beta"], one["erp"]),
        one["cost_of_debt"],
        one["debt_tax_rate"],
    )
    assert out[("wacc", SINGLE)] == expected


def test_with_wacc_set_the_erp_bounds_are_not_computed():
    base = rows(growth=0.01, debt=500.0, erp_std_error=0.02) + [row("wacc", 0.11)]
    out, gaps = dcf.outputs_and_gaps(base)
    assert gaps == {}
    assert not any(name.startswith("value_per_share_erp") for name, _ in out)
    assert out[("wacc", SINGLE)] == 0.11
    assert out[("value_per_share", SINGLE)] == dcf.value(base).value_per_share


def test_a_wacc_row_per_period_is_refused():
    with pytest.raises(DCFInputError, match="single value"):
        dcf.inputs(rows() + [row("wacc", 0.1, PERIODS[0])])


def test_a_wacc_row_and_a_cost_of_equity_shift_are_refused_together():
    inp = dcf.inputs(rows() + [row("wacc", 0.1)]).replace(cost_of_equity_shift=[0.01] * 11)
    with pytest.raises(DCFInputError, match="different questions"):
        dcf.compute(inp)
