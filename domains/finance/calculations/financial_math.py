import pandas as pd
import numpy as np
from typing import Union, List
import numpy_financial as npf

Numeric = Union[float, pd.Series]

def _safe_divide(numerator: Numeric, denominator: Numeric) -> Numeric:
    if isinstance(denominator, pd.Series):
        denom_safe = denominator.replace(0, np.nan)
    else:
        denom_safe = np.nan if denominator == 0 else denominator

    return numerator / denom_safe

# =====================================================
# LIQUIDITY
# =====================================================

def calculate_current_ratio(current_assets: Numeric, current_liabilities: Numeric) -> Numeric:
    return _safe_divide(current_assets, current_liabilities)

def calculate_quick_ratio(current_assets: Numeric, inventory: Numeric, current_liabilities: Numeric) -> Numeric:
    return _safe_divide((current_assets - inventory), current_liabilities)

def calculate_cash_ratio(cash_and_equivalents: Numeric, current_liabilities: Numeric) -> Numeric:
    return _safe_divide(cash_and_equivalents, current_liabilities)

def calculate_operating_cash_flow_ratio(operating_cash_flow: Numeric, current_liabilities: Numeric) -> Numeric:
    return _safe_divide(operating_cash_flow, current_liabilities)

# =====================================================
# LEVERAGE AND SOLVENCY
# =====================================================

def calculate_debt_to_equity(total_debt: Numeric, total_equity: Numeric) -> Numeric:
    return _safe_divide(total_debt, total_equity)

def calculate_debt_to_assets(total_debt: Numeric, total_assets: Numeric) -> Numeric:
    return _safe_divide(total_debt, total_assets)

def calculate_equity_multiplier(total_assets: Numeric, total_equity: Numeric) -> Numeric:
    return _safe_divide(total_assets, total_equity)

def calculate_interest_coverage_ratio(ebit: Numeric, interest_expense: Numeric) -> Numeric:
    return _safe_divide(ebit, interest_expense)

def calculate_dscr(net_operating_income: Numeric, total_debt_service: Numeric) -> Numeric:
    return _safe_divide(net_operating_income, total_debt_service)

def calculate_fixed_charge_coverage(ebit: Numeric, fixed_charges: Numeric, interest_expense: Numeric) -> Numeric:
    return _safe_divide((ebit + fixed_charges), (interest_expense + fixed_charges))

# =====================================================
# EFFICIENCY & ACTIVITY RATIOS
# =====================================================

def calculate_inventory_turnover(cogs: Numeric, average_inventory: Numeric) -> Numeric:
    return _safe_divide(cogs, average_inventory)

def calculate_dsi(inventory_turnover: Numeric) -> Numeric:
    return _safe_divide(365, inventory_turnover)

def calculate_receivables_turnover(net_credit_sales: Numeric, average_accounts_receivable: Numeric) -> Numeric:
    return _safe_divide(net_credit_sales, average_accounts_receivable)

def calculate_dso(receivables_turnover: Numeric) -> Numeric:
    return _safe_divide(365, receivables_turnover)

def calculate_payables_turnover(cogs: Numeric, average_accounts_payable: Numeric) -> Numeric:
    return _safe_divide(cogs, average_accounts_payable)

def calculate_dpo(payables_turnover: Numeric) -> Numeric:
    return _safe_divide(365, payables_turnover)

def calculate_ccc(dsi: Numeric, dso: Numeric, dpo: Numeric) -> Numeric:
    return dsi + dso - dpo

def calculate_asset_turnover(revenue: Numeric, average_total_assets: Numeric) -> Numeric:
    return _safe_divide(revenue, average_total_assets)

# =====================================================
# PROFITABILITY RATIOS
# =====================================================

def calculate_gross_profit_margin(revenue: Numeric, cogs: Numeric) -> Numeric:
    gross_profit = revenue - cogs
    return _safe_divide(gross_profit, revenue)

def calculate_operating_profit_margin(operating_income: Numeric, revenue: Numeric) -> Numeric:
    return _safe_divide(operating_income, revenue)

def calculate_net_profit_margin(net_income: Numeric, revenue: Numeric) -> Numeric:
    return _safe_divide(net_income, revenue)

def calculate_roa(net_income: Numeric, total_assets: Numeric) -> Numeric:
    return _safe_divide(net_income, total_assets)

def calculate_roe(net_income: Numeric, total_equity: Numeric) -> Numeric:
    return _safe_divide(net_income, total_equity)

def calculate_roic(nopat: Numeric, invested_capital: Numeric) -> Numeric:
    return _safe_divide(nopat, invested_capital)

def calculate_dupont_analysis(net_profit_margin: Numeric, asset_turnover: Numeric, equity_multiplier: Numeric) -> Numeric:
    """Returns ROE calculated via the three-step DuPont decomposition."""
    return net_profit_margin * asset_turnover * equity_multiplier

# =====================================================
# MARKET & VALUATION
# =====================================================

def calculate_eps(net_income: Numeric, preferred_dividends: Numeric, outstanding_shares: Numeric) -> Numeric:
    return _safe_divide((net_income - preferred_dividends), outstanding_shares)

def calculate_pe_ratio(share_price: Numeric, eps: Numeric) -> Numeric:
    return _safe_divide(share_price, eps)

def calculate_pb_ratio(share_price: Numeric, book_value_per_share: Numeric) -> Numeric:
    return _safe_divide(share_price, book_value_per_share)

def calculate_ps_ratio(share_price: Numeric, sales_per_share: Numeric) -> Numeric:
    return _safe_divide(share_price, sales_per_share)

def calculate_enterprise_value(market_cap: Numeric, total_debt: Numeric, cash_and_equivalents: Numeric) -> Numeric:
    return market_cap + total_debt - cash_and_equivalents

def calculate_ev_to_ebitda(enterprise_value: Numeric, ebitda: Numeric) -> Numeric:
    return _safe_divide(enterprise_value, ebitda)

def calculate_ev_to_ebit(enterprise_value: Numeric, ebit: Numeric) -> Numeric:
    return _safe_divide(enterprise_value, ebit)

def calculate_dividend_yield(annual_dividends_per_share: Numeric, share_price: Numeric) -> Numeric:
    return _safe_divide(annual_dividends_per_share, share_price)

def calculate_dividend_payout_ratio(dividends_paid: Numeric, net_income: Numeric) -> Numeric:
    return _safe_divide(dividends_paid, net_income)

def calculate_retention_ratio(dividend_payout_ratio: Numeric) -> Numeric:
    return 1 - dividend_payout_ratio

def calculate_sustainable_growth_rate(roe: Numeric, retention_ratio: Numeric) -> Numeric:
    return roe * retention_ratio

# =====================================================
# CORPORATE FINANCE & DCF MODELING
# =====================================================

def calculate_capm(risk_free_rate: Numeric, beta: Numeric, market_return: Numeric) -> Numeric:
    """Calculates Expected Return (Cost of Equity) using CAPM."""
    market_risk_premium = market_return - risk_free_rate
    return risk_free_rate + (beta * market_risk_premium)

def calculate_unlevered_beta(levered_beta: Numeric, tax_rate: Numeric, total_debt: Numeric, total_equity: Numeric) -> Numeric:
    debt_to_equity = _safe_divide(total_debt, total_equity)
    return _safe_divide(levered_beta, (1 + (1 - tax_rate) * debt_to_equity))

def calculate_wacc(equity_weight: Numeric, cost_of_equity: Numeric, debt_weight: Numeric, cost_of_debt: Numeric, tax_rate: Numeric) -> Numeric:
    return (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt * (1 - tax_rate))

def calculate_fcff(ebit: Numeric, tax_rate: Numeric, depreciation_amortization: Numeric, cap_ex: Numeric, change_in_nwc: Numeric) -> Numeric:
    """Free Cash Flow to Firm (Unlevered FCF)"""
    nopat = ebit * (1 - tax_rate)
    return nopat + depreciation_amortization - cap_ex - change_in_nwc

def calculate_fcfe(fcff: Numeric, interest_expense: Numeric, tax_rate: Numeric, net_borrowing: Numeric) -> Numeric:
    """Free Cash Flow to Equity (Levered FCF)"""
    return fcff - (interest_expense * (1 - tax_rate)) + net_borrowing

def calculate_terminal_value(final_year_fcf: float, wacc: float, perpetual_growth_rate: float) -> float:
    if wacc <= perpetual_growth_rate:
        raise ValueError("WACC must be strictly greater than the perpetual growth rate.")
    return _safe_divide((final_year_fcf * (1 + perpetual_growth_rate)), (wacc - perpetual_growth_rate))

def calculate_npv(discount_rate: float, cash_flows: Union[List[float], pd.Series]) -> float:
    """Uses numpy_financial to evaluate a series of cash flows."""
    return npf.npv(discount_rate, cash_flows)

def calculate_irr(cash_flows: Union[List[float], pd.Series]) -> float:
    """Uses numpy_financial to find the internal rate of return."""
    return npf.irr(cash_flows)
