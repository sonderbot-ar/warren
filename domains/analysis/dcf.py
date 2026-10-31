"""The baseline DCF as a pure function of a run's assumption rows (no I/O, no database).

Everything a valuation needs is an assumption row, including the base values taken from filings
(the revenue seed, net debt, shares), so a stored run can be valued again from its rows alone:
that is what makes it reproducible to the cent. math_engine builds the rows; every number here
comes from financial_math.

Period grid (build plan, M2): 8 quarters, then the three 12-month years after them (Y3-Y5), then
a Gordon terminal value on Y5's cash flow. Quarters grow from the same quarter a year earlier, so
the seed is the last 4 actual quarters. Cash flows are discounted from the end of the last actual
quarter (the base date), and the enterprise value is carried forward from there to the as-of date.
"""

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from domains.analysis import financial_math as fm
from domains.analysis.schemas import SINGLE, Assumption

QUARTERS = 8
YEARS = ("Y3", "Y4", "Y5")
SEED = "revenue_seed"
DRIVERS = ("revenue_growth", "operating_margin", "tax_rate", "da_pct", "capex_pct", "nwc_pct")
SINGLE_VALUES = (
    "risk_free",
    "beta",
    "erp",
    "cost_of_debt",
    "debt_tax_rate",
    "equity_market_value",
    "debt",
    "cash_and_investments",
    "minority_interest",
    "shares",
    "terminal_growth",
    "roll_years",
)
# terminal_method (a user row; its choice is in the method text). A run stored without the row
# predates it and keeps the Gordon rule on Y5's free cash flow, so it still reproduces.
VALUE_DRIVER = "value_driver_ronic_wacc"
GORDON = "gordon_fcff"
LINES = ("revenue", "ebit", "nopat", "d_and_a", "capex", "delta_nwc", "fcff", "discount_factor")


class DCFInputError(ValueError):
    """The assumption rows don't describe a complete run."""


@dataclass(frozen=True)
class Valuation:
    periods: list[str]
    lines: dict[str, list[float]]  # one value per forecast period, for each of LINES
    cost_of_equity: float
    wacc: float
    dcf: fm.DCFValue  # as of the base date
    enterprise_value_as_of: float
    net_debt: float
    minority_interest: float
    equity_value: float
    value_per_share: float

    def outputs(self) -> dict[tuple[str, str], float]:
        """Every computed number by (name, period): what a run stores and reproduce checks."""
        out = {
            (line, period): value
            for line, values in self.lines.items()
            for period, value in zip(self.periods, values, strict=True)
        }
        for name, value in [
            ("cost_of_equity", self.cost_of_equity),
            ("wacc", self.wacc),
            ("pv_explicit", self.dcf.pv_explicit),
            ("terminal_value", self.dcf.terminal_value),
            ("pv_terminal", self.dcf.pv_terminal),
            ("enterprise_value", self.dcf.enterprise_value),
            ("terminal_share", self.dcf.terminal_share),
            ("enterprise_value_as_of", self.enterprise_value_as_of),
            ("net_debt", self.net_debt),
            ("equity_value", self.equity_value),
            ("value_per_share", self.value_per_share),
        ]:
            out[(name, SINGLE)] = value
        return out


def _index(assumptions: Iterable[Assumption]) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    for a in assumptions:
        if a.period in rows.get(a.name, {}):
            raise DCFInputError(f"two rows for {a.name} {a.period}")
        rows.setdefault(a.name, {})[a.period] = a.value
    return rows


def forecast_periods(rows: dict[str, dict[str, float]]) -> tuple[list[str], list[str]]:
    """(seed quarters, forecast periods), in order; quarter labels sort as FY2024Q3 < FY2025Q1."""
    if SEED not in rows or len(rows[SEED]) != 4:
        raise DCFInputError(f"{SEED} needs the last 4 actual quarters")
    periods = sorted(rows.get("revenue_growth", {}))
    quarters = [p for p in periods if p not in YEARS]
    if len(quarters) != QUARTERS or periods[QUARTERS:] != list(YEARS):
        raise DCFInputError(f"forecast periods must be {QUARTERS} quarters then {YEARS}: {periods}")
    return sorted(rows[SEED]), periods


@dataclass(frozen=True)
class Inputs:
    """A run's rows as the valuation reads them. Driver values may be floats or, for the Monte
    Carlo (M4), numpy arrays with one value per sample: the arithmetic is the same."""

    seed: list[float]
    periods: list[str]
    driver: dict[str, list]  # one value per forecast period, for each of DRIVERS
    one: dict[str, float]  # each of SINGLE_VALUES
    cost_of_equity_shift: list | None = None  # added to the cost of equity per period (M4)
    terminal_method: str = GORDON

    def replace(self, **changes) -> "Inputs":
        return dataclasses.replace(self, **changes)


def terminal_method(assumptions: Iterable[Assumption]) -> str:
    for a in assumptions:
        if a.name == "terminal_method":
            choice = a.method.split(":")[0].strip()
            if choice not in (VALUE_DRIVER, GORDON):
                raise DCFInputError(f"unknown terminal_method {choice}")
            return choice
    return GORDON


def inputs(assumptions: Iterable[Assumption]) -> Inputs:
    assumptions = list(assumptions)
    rows = _index(assumptions)
    seed_periods, periods = forecast_periods(rows)
    missing = [n for n in DRIVERS if set(rows.get(n, {})) != set(periods)]
    missing += [n for n in SINGLE_VALUES if SINGLE not in rows.get(n, {})]
    if missing:
        raise DCFInputError(f"missing or incomplete assumptions: {missing}")
    return Inputs(
        seed=[rows[SEED][p] for p in seed_periods],
        periods=periods,
        driver={name: [rows[name][p] for p in periods] for name in DRIVERS},
        one={name: rows[name][SINGLE] for name in SINGLE_VALUES},
        terminal_method=terminal_method(assumptions),
    )


def value(assumptions: Iterable[Assumption]) -> Valuation:
    return compute(inputs(assumptions))


def _wacc_at(one: dict, cost_of_equity):
    return fm.wacc(
        one["equity_market_value"],
        one["debt"],
        cost_of_equity,
        one["cost_of_debt"],
        one["debt_tax_rate"],
    )


def base_wacc(inp: Inputs):
    """The run's WACC before any risk-premium shock."""
    one = inp.one
    return _wacc_at(one, fm.capm_cost_of_equity(one["risk_free"], one["beta"], one["erp"]))


def discount_rates(inp: Inputs) -> list:
    """WACC for each forecast period, with the period's cost-of-equity shift (M4) if any.

    Floats, or per-sample arrays in the Monte Carlo; the valuation and the sample checks both read
    the rates from here, so they can't disagree (backlog #90)."""
    if inp.cost_of_equity_shift is None:
        return [base_wacc(inp)] * len(inp.periods)
    one = inp.one
    cost_of_equity = fm.capm_cost_of_equity(one["risk_free"], one["beta"], one["erp"])
    return [_wacc_at(one, cost_of_equity + shift) for shift in inp.cost_of_equity_shift]


def compute(inp: Inputs) -> Valuation:
    periods, driver, one, seed = inp.periods, inp.driver, inp.one, inp.seed
    quarters = fm.compound(seed, driver["revenue_growth"][:QUARTERS], lag=4)
    revenue = list(quarters)
    year = sum(quarters[-4:])
    for growth in driver["revenue_growth"][QUARTERS:]:
        year = year * (1 + growth)
        revenue.append(year)

    # trailing-12-month revenue at each period end: working capital is a share of it
    history = seed + quarters
    ttm = [sum(history[i + 1 : i + 5]) for i in range(QUARTERS)] + revenue[QUARTERS:]
    nwc = [pct * r for pct, r in zip(driver["nwc_pct"], ttm, strict=True)]
    nwc_before = [driver["nwc_pct"][0] * sum(seed)] + nwc[:-1]
    delta_nwc = [now - before for now, before in zip(nwc, nwc_before, strict=True)]

    ebit = [r * m for r, m in zip(revenue, driver["operating_margin"], strict=True)]
    d_and_a = [r * p for r, p in zip(revenue, driver["da_pct"], strict=True)]
    capex = [r * p for r, p in zip(revenue, driver["capex_pct"], strict=True)]
    fcff = [
        fm.fcff(e, t, d, c, n)
        for e, t, d, c, n in zip(ebit, driver["tax_rate"], d_and_a, capex, delta_nwc, strict=True)
    ]
    nopat = [e * (1 - t) for e, t in zip(ebit, driver["tax_rate"], strict=True)]

    cost_of_equity = fm.capm_cost_of_equity(one["risk_free"], one["beta"], one["erp"])
    wacc = base_wacc(inp)
    rates = discount_rates(inp)
    year_fractions = [0.25] * QUARTERS + [1.0] * len(YEARS)
    dcf = fm.enterprise_value(
        fcff,
        rates,
        year_fractions,
        one["terminal_growth"],
        final_annual_nopat=nopat[-1] if inp.terminal_method == VALUE_DRIVER else None,
    )
    ev_as_of = fm.roll_forward(dcf.enterprise_value, wacc, one["roll_years"])
    net_debt = one["debt"] - one["cash_and_investments"]
    equity = fm.equity_value(ev_as_of, net_debt, one["minority_interest"])
    return Valuation(
        periods=periods,
        lines={
            "revenue": revenue,
            "ebit": ebit,
            "nopat": nopat,
            "d_and_a": d_and_a,
            "capex": capex,
            "delta_nwc": delta_nwc,
            "fcff": fcff,
            "discount_factor": fm.discount_factors(rates, year_fractions),
        },
        cost_of_equity=cost_of_equity,
        wacc=wacc,
        dcf=dcf,
        enterprise_value_as_of=ev_as_of,
        net_debt=net_debt,
        minority_interest=one["minority_interest"],
        equity_value=equity,
        value_per_share=fm.value_per_share(equity, one["shares"]),
    )


def with_value(assumptions: Iterable[Assumption], name: str, new: float) -> list[Assumption]:
    """The same rows with one single-valued assumption replaced (for sensitivities)."""
    rows = list(assumptions)
    if not any(a.name == name and a.period == SINGLE for a in rows):
        raise DCFInputError(f"no single-valued assumption {name}")
    return [
        a.model_copy(update={"value": new}) if a.name == name and a.period == SINGLE else a
        for a in rows
    ]


@dataclass(frozen=True)
class Gap:
    """Why an output has no value: a code from financial_math.REASONS and the error's message."""

    reason: str
    detail: str


# Reasons that mean "this output has no value" rather than "the inputs are wrong": only these
# leave a sensitivity out; any other FinancialMathError stops the run (backlog #9 review).
NO_VALUE_REASONS = frozenset(
    {"growth_not_below_rate", "rate_not_positive", "rate_not_above_minus_100"}
)


def outputs_and_gaps(
    assumptions: Iterable[Assumption],
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], Gap]]:
    """Everything a run stores: the valuation, plus value per share at ERP ± 1 standard error,
    and, for each of those that has no value, why (keys are (name, period) in both)."""
    rows = list(assumptions)
    out = value(rows).outputs()
    gaps: dict[tuple[str, str], Gap] = {}
    index = _index(rows)
    erp, std_error = index["erp"][SINGLE], index.get("erp_std_error", {}).get(SINGLE)
    if std_error is None:
        raise DCFInputError("missing assumption erp_std_error")
    for name, shifted in (("erp_minus_1se", erp - std_error), ("erp_plus_1se", erp + std_error)):
        key = (f"value_per_share_{name}", SINGLE)
        try:
            out[key] = value(with_value(rows, "erp", shifted)).value_per_share
        except fm.FinancialMathError as e:
            if e.reason not in NO_VALUE_REASONS:
                raise
            gaps[key] = Gap(e.reason, str(e))
    return out, gaps


def run_outputs(assumptions: Iterable[Assumption]) -> dict[tuple[str, str], float]:
    """The outputs of outputs_and_gaps, for callers that only need the numbers."""
    return outputs_and_gaps(assumptions)[0]
