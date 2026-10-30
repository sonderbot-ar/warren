"""Pure DCF formulas: no I/O, no database, no LLM (Decision 4).

Every function is plain arithmetic, so each argument may be a float or, for the Monte Carlo in M4,
a numpy array of samples; sequences are one element per forecast period. Rates are annual decimals
(0.08 = 8%). Invalid inputs raise FinancialMathError instead of returning NaN or infinity: a number
that can't be computed must stop the run, never flow silently into a valuation.

Discounting is end-of-period: a cash flow at the end of period t is discounted over the years
elapsed until then, each period at its own annual rate.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

Number = Any  # float, or a numpy array of samples (M4)

# Blume (1971): betas regress toward 1 over time; the adjusted beta weights the raw one by 2/3.
BLUME_WEIGHT = 2 / 3


class FinancialMathError(ValueError):
    """An input makes a formula meaningless (e.g. terminal growth at or above the discount rate)."""


def _any(condition: Number) -> bool:
    """True if the condition holds for the value, or for any sample in an array."""
    return bool(condition.any()) if hasattr(condition, "any") else bool(condition)


# -- projection -------------------------------------------------------------------------------


def compound(seed: Sequence[Number], growth: Sequence[Number], lag: int = 1) -> list[Number]:
    """Project a series forward: value[t] = value[t - lag] × (1 + growth[t]).

    lag=1 compounds period on period; lag=4 on quarters grows each quarter from the same quarter a
    year earlier, which keeps seasonality. `seed` holds the last `lag` actual values, oldest first.
    """
    if lag < 1 or len(seed) != lag:
        raise FinancialMathError(f"compound needs exactly lag={lag} seed values, got {len(seed)}")
    values = list(seed)
    for g in growth:
        values.append(values[-lag] * (1 + g))
    return values[lag:]


def fcff(
    ebit: Number, tax_rate: Number, d_and_a: Number, capex: Number, delta_nwc: Number
) -> Number:
    """Unlevered free cash flow: EBIT × (1 − tax) + D&A − capex − ΔNWC (capex is positive)."""
    return ebit * (1 - tax_rate) + d_and_a - capex - delta_nwc


# -- discounting ------------------------------------------------------------------------------


def discount_factors(rates: Sequence[Number], year_fractions: Sequence[float]) -> list[Number]:
    """End-of-period discount factors under a time-varying annual rate.

    Period i lasts year_fractions[i] years (0.25 for a quarter, 1 for a year) and is discounted at
    rates[i]: factor[t] = Π over i ≤ t of (1 + rates[i]) ** −year_fractions[i].
    """
    if len(rates) != len(year_fractions):
        raise FinancialMathError("rates and year_fractions must have one value per period")
    factors, factor = [], 1.0
    for rate, years in zip(rates, year_fractions, strict=True):
        if _any(rate <= -1):
            raise FinancialMathError(f"discount rate must be above -100%, got {rate}")
        if years <= 0:
            raise FinancialMathError(f"period length must be positive, got {years}")
        factor = factor * (1 + rate) ** -years
        factors.append(factor)
    return factors


def gordon_terminal_value(
    final_annual_cash_flow: Number, discount_rate: Number, terminal_growth: Number
) -> Number:
    """Value, at the end of the last forecast year, of the cash flows after it growing forever."""
    if _any(terminal_growth >= discount_rate):
        raise FinancialMathError(
            f"terminal growth ({terminal_growth}) must be below the discount rate ({discount_rate})"
        )
    return final_annual_cash_flow * (1 + terminal_growth) / (discount_rate - terminal_growth)


@dataclass(frozen=True)
class DCFValue:
    pv_explicit: Number  # present value of the forecast-period cash flows
    terminal_value: Number  # at the end of the last forecast period
    pv_terminal: Number
    enterprise_value: Number

    @property
    def terminal_share(self) -> Number:
        """Share of enterprise value that comes from the terminal value."""
        return self.pv_terminal / self.enterprise_value


def enterprise_value(
    cash_flows: Sequence[Number],
    rates: Sequence[Number],
    year_fractions: Sequence[float],
    terminal_growth: Number,
    final_annual_cash_flow: Number | None = None,
) -> DCFValue:
    """DCF enterprise value: forecast cash flows plus a Gordon terminal value, both discounted.

    The terminal value grows an annual cash flow; it defaults to the last period's cash flow, which
    is right when the last period is a year. It is discounted at the last period's rate.
    """
    if len(cash_flows) != len(rates):
        raise FinancialMathError("cash_flows and rates must have one value per period")
    if not cash_flows:
        raise FinancialMathError("at least one forecast period is required")
    factors = discount_factors(rates, year_fractions)
    pv_explicit = sum(cf * df for cf, df in zip(cash_flows, factors, strict=True))
    final = cash_flows[-1] if final_annual_cash_flow is None else final_annual_cash_flow
    terminal = gordon_terminal_value(final, rates[-1], terminal_growth)
    pv_terminal = terminal * factors[-1]
    return DCFValue(pv_explicit, terminal, pv_terminal, pv_explicit + pv_terminal)


# -- enterprise value to value per share ------------------------------------------------------


def roll_forward(value: Number, rate: Number, years: float) -> Number:
    """A value at one date carried `years` later at an annual rate: value × (1 + rate) ** years."""
    if years < 0:
        raise FinancialMathError(f"can only roll a value forward, got {years} years")
    return value * (1 + rate) ** years


def equity_value(enterprise: Number, net_debt: Number, minority_interest: Number = 0.0) -> Number:
    """Equity value attributable to shareholders: EV − net debt − noncontrolling interests."""
    return enterprise - net_debt - minority_interest


def value_per_share(equity: Number, shares: Number) -> Number:
    if _any(shares <= 0):
        raise FinancialMathError(f"share count must be positive, got {shares}")
    return equity / shares


# -- cost of capital --------------------------------------------------------------------------


def capm_cost_of_equity(risk_free: Number, beta: Number, equity_risk_premium: Number) -> Number:
    """CAPM: risk-free rate + beta × equity risk premium."""
    return risk_free + beta * equity_risk_premium


def wacc(
    equity_market_value: Number,
    debt: Number,
    cost_of_equity: Number,
    cost_of_debt: Number,
    tax_rate: Number,
) -> Number:
    """Weighted average cost of capital, with debt's cost after tax."""
    if _any(equity_market_value <= 0) or _any(debt < 0):
        raise FinancialMathError("equity value must be positive and debt non-negative")
    total = equity_market_value + debt
    return equity_market_value / total * cost_of_equity + debt / total * cost_of_debt * (
        1 - tax_rate
    )


def cost_of_debt(interest: Number, average_debt: Number) -> Number:
    """Pre-tax cost of debt: a year's interest over the average debt outstanding in that year."""
    if _any(average_debt <= 0):
        raise FinancialMathError(f"average debt must be positive, got {average_debt}")
    return interest / average_debt


def ols_beta(stock_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    """Slope of stock returns on market returns: cov(stock, market) / var(market)."""
    n = len(stock_returns)
    if n != len(market_returns):
        raise FinancialMathError("stock and market returns must cover the same dates")
    if n < 3:
        raise FinancialMathError(f"at least 3 returns are needed for a beta, got {n}")
    mean_s, mean_m = sum(stock_returns) / n, sum(market_returns) / n
    cov = sum(
        (s - mean_s) * (m - mean_m) for s, m in zip(stock_returns, market_returns, strict=True)
    )
    var = sum((m - mean_m) ** 2 for m in market_returns)
    if var == 0:
        raise FinancialMathError("market returns have no variance")
    return cov / var


def blume_adjusted_beta(raw_beta: Number) -> Number:
    return BLUME_WEIGHT * raw_beta + (1 - BLUME_WEIGHT)


# -- equity risk premium ----------------------------------------------------------------------


def bond_total_return(start_yield: float, end_yield: float, maturity: int = 10) -> float:
    """One year's total return on a par bond: the coupon plus the price change as yields move.

    Bought at par at start_yield (so its coupon is start_yield) and priced a year later at
    end_yield, as a bond of the same maturity (the standard approximation, as in Damodaran's
    historical returns).
    """
    if start_yield <= -1 or end_yield <= -1:
        raise FinancialMathError("yields must be above -100%")
    discount = (1 + end_yield) ** -maturity
    annuity = maturity if end_yield == 0 else (1 - discount) / end_yield
    price = start_yield * annuity + discount
    return start_yield + price - 1


@dataclass(frozen=True)
class RiskPremium:
    geometric: float  # geometric mean equity return − geometric mean bond return
    arithmetic: float  # mean of the yearly excess returns
    std_error: float  # of the arithmetic mean: stdev of yearly excess returns / √years
    years: int


def _geometric_mean(returns: Sequence[float]) -> float:
    return math.prod(1 + r for r in returns) ** (1 / len(returns)) - 1


def historical_premium(
    equity_returns: Sequence[float], bond_returns: Sequence[float]
) -> RiskPremium:
    """Realized premium of stocks over bonds, from yearly total returns over the same years."""
    n = len(equity_returns)
    if n != len(bond_returns):
        raise FinancialMathError("equity and bond returns must cover the same years")
    if n < 2:
        raise FinancialMathError(f"at least 2 years are needed for a premium, got {n}")
    excess = [e - b for e, b in zip(equity_returns, bond_returns, strict=True)]
    mean = sum(excess) / n
    stdev = math.sqrt(sum((x - mean) ** 2 for x in excess) / (n - 1))
    return RiskPremium(
        geometric=_geometric_mean(equity_returns) - _geometric_mean(bond_returns),
        arithmetic=mean,
        std_error=stdev / math.sqrt(n),
        years=n,
    )


# -- shocks (M4, Decision 6) ------------------------------------------------------------------

# z of the 90th percentile of a standard normal: low and high sit this many σ from the median
Z90 = 1.2815515655446004


def shock_shape(start: int, horizon: int, decay: float, quarters: int) -> list[float]:
    """Share of a shock's magnitude in force at each quarter h = 1…quarters.

    decay^(h − start) for start ≤ h < start + horizon, else 0 (Build Plan M4). decay = 1 keeps
    the effect constant over the horizon.
    """
    if not 0 < decay <= 1:
        raise FinancialMathError(f"decay must be in (0, 1], got {decay}")
    if horizon < 1 or start < 1 or start + horizon - 1 > quarters:
        raise FinancialMathError(
            f"a shock from quarter {start} lasting {horizon} must fit in {quarters} quarters"
        )
    return [
        decay ** (h - start) if start <= h < start + horizon else 0.0
        for h in range(1, quarters + 1)
    ]


def split_normal(low: float, base: float, high: float, z: Number) -> Number:
    """A magnitude whose p10, p50 and p90 are low, base and high, from standard normal draws z.

    Below the median it is a normal with σ = (base − low) / Z90, above it one with
    σ = (high − base) / Z90, each side with half the probability, so an asymmetric range keeps
    its three quantiles exactly. low = base = high gives a constant.
    """
    if not low <= base <= high:
        raise FinancialMathError(f"need low ≤ base ≤ high, got {low}, {base}, {high}")
    sigma_low, sigma_high = (base - low) / Z90, (high - base) / Z90
    if hasattr(z, "shape"):
        import numpy as np

        return base + z * np.where(z < 0, sigma_low, sigma_high)
    return base + z * (sigma_low if z < 0 else sigma_high)
