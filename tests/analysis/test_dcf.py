import pytest

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
