"""What-if revaluation: a stored run valued again with named inputs changed (backlog #141).

The query behind brief questions 7 and 8 (`docs/product/brief.md`): "if Walmart's operating
margin falls one point, how much does its value per share change?" The student (or the app)
names an input and its new value or shift; the engine copies the parent run's assumption rows,
replaces those, values them with the same `dcf.outputs_and_gaps` and stores the result as a child
run linked by `runs.parent_run_id`. A run's outputs are a pure function of its rows, so the child
reproduces to the cent with the ordinary `runs.reproduce`.

- No data is read: the parent's rows were point in time on its date, and the child keeps that
  date. No LLM is called: every number comes from `dcf` and `financial_math`.
- Terminal growth follows a changed risk-free rate when the run's choice says so
  (`terminal_growth_method = risk_free`), unless the student also sets terminal growth.
- Every refusal and note is a stable code with parameters; `text` is an English fallback, as in
  `reported.py`. A refused what-if stores nothing.
- Values are raw, in the row's own unit: fractions for rates and shares of revenue, whole
  currency units for money, a count for shares.
"""

import math
import sqlite3
from dataclasses import asdict, dataclass, field

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis import sources as src
from domains.analysis.math_engine import post_check_notes
from domains.analysis.montecarlo import _currency
from domains.analysis.reported import Coded
from domains.analysis.runs import (
    code_version,
    insert_rows,
    load_assumptions,
    load_outputs,
    write_lock,
)
from domains.analysis.schemas import SINGLE, Assumption
from domains.analysis.text import REASON_WORDS

# `debt` changes only with a use (backlog #170): one row is both the WACC's debt weight and the
# claim on the firm, so a debt change swaps debt with equity at the as-of price, relevers beta
# (Hamada 1972) and prices the debt at no less than the risk-free rate; see `_leverage_rows`.
DEBT = "debt"
DEBT_USES = ("buyback",)
# known uses that part 1 does not value, with why (design doc, What changes 1)
DEBT_USES_NOT_BUILT = ("cash_kept", "acquisition")
# rows a debt change computes, so the student can't also name them
SET_BY_DEBT = ("beta", "shares")
CHANGEABLE_SINGLE = (
    "risk_free",
    "beta",
    "erp",
    "cost_of_debt",
    "debt_tax_rate",
    "terminal_growth",
    "cash_and_investments",
    "minority_interest",
    "shares",
    DEBT,
    # WACC set directly (backlog #171): not a row of the parent, whose WACC is an output; the
    # child gets a `wacc` row that dcf reads in place of the computed rate
    dcf.WACC_SET,
)
CHANGEABLE = dcf.DRIVERS + CHANGEABLE_SINGLE
# The terminal formula, switched on a what-if only (backlog #171 part 2; owner decision
# nov.05.2026, Decision 4): a choice, not a number, so it comes as Change(method=...)
TERMINAL = "terminal_method"
TERMINAL_METHODS = (dcf.GORDON, dcf.VALUE_DRIVER)
# The inputs the computed WACC is built from: with WACC set they would move nothing but the
# cost-of-equity line, which a student would read as a result, so they are refused beside it
WACC_INPUTS = ("risk_free", "beta", "erp", "cost_of_debt", "debt_tax_rate", DEBT)
# (low, high, low included, high included): checked before any arithmetic; None = no bound
BOUNDS = {
    "shares": (0.0, None, False, None),
    dcf.WACC_SET: (0.0, None, False, None),
    "cash_and_investments": (0.0, None, True, None),
    DEBT: (0.0, None, True, None),
    "minority_interest": (0.0, None, True, None),
    "tax_rate": (0.0, 1.0, True, False),
    "debt_tax_rate": (0.0, 1.0, True, False),
    "cost_of_debt": (0.0, None, True, None),
    "revenue_growth": (-1.0, None, False, None),
}
SINGLE_LINES = (
    "cost_of_equity",
    "wacc",
    "terminal_growth",
    "pv_explicit",
    "terminal_value",
    "pv_terminal",
    "enterprise_value",
    "terminal_share",
    "enterprise_value_as_of",
    "net_debt",
    "minority_interest",
    "equity_value",
    "value_per_share",
)
PERIOD_LINES = (
    "revenue",
    "ebit",
    "operating_taxes",
    "nopat",
    "d_and_a",
    "capex",
    "delta_nwc",
    "fcff",
    "discount_factor",
)
FRACTIONS = {"cost_of_equity", "wacc", "terminal_growth", "terminal_share", "discount_factor"}

# Which inputs each line is computed from (dcf.compute), so every moved line names the changed
# inputs behind it (`driven_by`) and the app never guesses a cause (design principle 8).
_REVENUE = {"revenue_growth"}
_CASH_FLOW = set(dcf.DRIVERS)
_RATE = set(WACC_INPUTS) | {dcf.WACC_SET, "equity_market_value"}
_VALUE = _CASH_FLOW | _RATE | {"terminal_growth", TERMINAL}
DEPENDS = {
    "revenue": _REVENUE,
    "ebit": _REVENUE | {"operating_margin"},
    "operating_taxes": _REVENUE | {"operating_margin", "tax_rate"},
    "nopat": _REVENUE | {"operating_margin", "tax_rate"},
    "d_and_a": _REVENUE | {"da_pct"},
    "capex": _REVENUE | {"capex_pct"},
    "delta_nwc": _REVENUE | {"nwc_pct"},
    "fcff": _CASH_FLOW,
    "discount_factor": _RATE,
    "cost_of_equity": {"risk_free", "beta", "erp"},
    "wacc": _RATE,
    "terminal_growth": {"terminal_growth"},
    "pv_explicit": _CASH_FLOW | _RATE,
    "terminal_value": _VALUE,
    "pv_terminal": _VALUE,
    "enterprise_value": _VALUE,
    "terminal_share": _VALUE,
    "enterprise_value_as_of": _VALUE,
    "net_debt": {"cash_and_investments", DEBT},
    "minority_interest": {"minority_interest"},
    "equity_value": _VALUE | {"cash_and_investments", "minority_interest", DEBT},
    "value_per_share": _VALUE | {"cash_and_investments", "minority_interest", "shares", DEBT},
}
FADE = "fading linearly to terminal growth"  # math_engine's revenue growth rule, in its method
TERMINAL_FORMULAS = {
    dcf.GORDON: Coded(
        "gordon",
        {},
        "Terminal value = FCFF × (1 + g) / (WACC − g): growth and the discount rate both move it, "
        "and more the closer they are.",
    ),
    dcf.VALUE_DRIVER: Coded(
        "value_driver",
        {},
        "Terminal value = NOPAT × (1 + g) / WACC (return on new investment equal to WACC): growth "
        "past year 5 adds no value, so a rate change moves value mostly through WACC.",
    ),
}


class WhatIfError(ValueError):
    """A what-if that can't be valued: `code` and `params` say why; nothing was stored."""

    def __init__(self, code: str, params: dict, text: str):
        super().__init__(text)
        self.code, self.params, self.text = code, params, text

    def coded(self) -> Coded:
        return Coded(self.code, self.params, self.text)


@dataclass(frozen=True)
class Change:
    """One input to change: `value` sets it, `delta` is added to the stored value (exactly one).
    `period` is a forecast period label for a driver; None means every period (a driver) or the
    single value."""

    name: str
    value: float | None = None
    delta: float | None = None
    period: str | None = None
    method: str | None = None  # only for terminal_method: the formula to switch to
    use: str | None = None  # only for debt: what the money is for (DEBT_USES)


@dataclass(frozen=True)
class RowChange:
    name: str
    period: str
    before: float | str  # a method name for terminal_method
    after: float | str
    # set, add, follows_risk_free, follows_terminal_growth, switch; for a debt change (#170)
    # buyback (shares, equity_market_value), relevered (beta), floored_at_risk_free (cost_of_debt)
    how: str


@dataclass(frozen=True)
class Line:
    name: str
    period: str
    unit: str  # fraction, a currency, or per_share
    before: float | None
    after: float | None
    change: float | None
    change_pct: float | None
    driven_by: list[str] = field(default_factory=list)  # the changed inputs behind the move


@dataclass(frozen=True)
class WhatIf:
    run_id: str
    parent_run_id: str
    ticker: str
    as_of: str
    currency: str
    reused: bool
    terminal_method: str
    terminal_formula: Coded
    changes: list[RowChange]
    lines: list[Line]
    notes: list[Coded] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _refuse(code: str, text: str, **params) -> WhatIfError:
    return WhatIfError(code, params, text)


def _check_bounds(name: str, value: float) -> None:
    if not math.isfinite(value):  # NaN passes every comparison; infinity gives no valuation
        raise _refuse("invalid_input", f"{name} {value} is not a finite number", name=name)
    if name not in BOUNDS:
        return
    low, high, low_in, high_in = BOUNDS[name]
    below = low is not None and (value < low or (value == low and not low_in))
    above = high is not None and (value > high or (value == high and not high_in))
    if below or above:
        raise _refuse(
            "out_of_range",
            f"{name} {value} is outside its range",
            name=name,
            value=value,
            low=low,
            high=high,
        )


def _targets(change: Change, periods: list[str]) -> list[str]:
    """The periods a change touches, or a refusal for a name or period it can't have."""
    if change.name not in CHANGEABLE:
        if change.name in dcf.SINGLE_VALUES or change.name == dcf.SEED:
            raise _refuse(
                "not_changeable",
                f"{change.name} is a fact of the base date or a market price, not an input",
                name=change.name,
            )
        raise _refuse("unknown_input", f"no input {change.name}", name=change.name)
    if (change.value is None) == (change.delta is None):
        raise _refuse(
            "value_and_delta", f"{change.name}: give a value or a delta, not both or neither"
        )
    if change.name in CHANGEABLE_SINGLE:
        if change.period not in (None, SINGLE):
            raise _refuse(
                "period_on_single_value",
                f"{change.name} has one value for the whole run",
                name=change.name,
                period=change.period,
            )
        return [SINGLE]
    if change.period is None:
        return list(periods)
    if change.period not in periods:
        raise _refuse(
            "unknown_period",
            f"the run has no period {change.period}",
            name=change.name,
            period=change.period,
            periods=list(periods),
        )
    return [change.period]


def _changed_rows(
    rows: list[Assumption], changes: list[Change], parent_outputs: dict
) -> list[RowChange]:
    index = {(a.name, a.period): a for a in rows}
    # the parent has no `wacc` row: a set WACC starts from the WACC the parent computed
    before_of = {key: a.value for key, a in index.items()}
    before_of.setdefault((dcf.WACC_SET, SINGLE), parent_outputs[("wacc", SINGLE)])
    periods = dcf.forecast_periods(dcf._index(rows))[1]
    out: dict[tuple[str, str], RowChange] = {}
    for change in changes:
        if change.name == TERMINAL:
            key = (TERMINAL, SINGLE)
            if key in out:
                raise _refuse(
                    "duplicate_change", f"{TERMINAL} is changed twice", name=TERMINAL, period=SINGLE
                )
            out[key] = _switch(rows, change)
            continue
        if change.use is not None and change.name != DEBT:
            raise _refuse(
                "use_on_other_input",
                f"only {DEBT} takes a use; {change.name} does not",
                name=change.name,
            )
        if change.name == DEBT and change.use is None:
            raise _refuse(
                "debt_use_needed",
                f"say what the debt is for: one of {', '.join(DEBT_USES)}",
                supported=list(DEBT_USES),
            )
        if change.name == DEBT and change.use not in DEBT_USES:
            raise _refuse(
                "debt_use_not_supported",
                f"a debt change used for {change.use!r} is not valued yet",
                use=change.use,
                supported=list(DEBT_USES),
            )
        if change.method is not None:
            raise _refuse(
                "method_on_number",
                f"{change.name} takes a number; only {TERMINAL} takes a method",
                name=change.name,
            )
        for period in _targets(change, periods):
            key = (change.name, period)
            if key in out:
                raise _refuse(
                    "duplicate_change",
                    f"{change.name} {period} is changed twice",
                    name=change.name,
                    period=period,
                )
            before = before_of[key]
            if change.value is not None:
                after, how = change.value, "set"
            else:
                after, how = before + change.delta, "add"
            _check_bounds(change.name, after)
            out[key] = RowChange(change.name, period, before, after, how)
    if (dcf.WACC_SET, SINGLE) in out:
        for name in WACC_INPUTS:
            if (name, SINGLE) in out:
                raise _refuse(
                    "wacc_with_rate_input",
                    f"WACC is set directly, so {name} would not move it: change one or the other",
                    name=name,
                )
    if (DEBT, SINGLE) in out:
        out |= _leverage_rows(index, out)
    rf_key, tg_key = ("risk_free", SINGLE), ("terminal_growth", SINGLE)
    if rf_key in out and tg_key not in out and _follows_risk_free(rows):
        before = index[tg_key].value
        out[tg_key] = RowChange(*tg_key, before, out[rf_key].after, "follows_risk_free")
    touched_growth = any(c.name == "revenue_growth" for c in changes)
    if tg_key in out and not touched_growth and _fades(rows):
        shift = out[tg_key].after - out[tg_key].before
        for i, period in enumerate(periods):
            before = index[("revenue_growth", period)].value
            after = before + shift * (forecast_year(i) - 1) / 4
            if after != before:
                _check_bounds("revenue_growth", after)
                out[("revenue_growth", period)] = RowChange(
                    "revenue_growth", period, before, after, "follows_terminal_growth"
                )
    return list(out.values())


def _leverage_rows(
    index: dict[tuple[str, str], Assumption], out: dict[tuple[str, str], RowChange]
) -> dict[tuple[str, str], RowChange]:
    """The rows a debt change moves besides debt (backlog #170, use buyback): the change in debt
    is swapped with equity at the as-of price, so the share count and the market value of equity
    follow; beta is relevered by Hamada's rule (unlevered on the parent's structure and tax rate,
    relevered on the child's); and the cost of debt, when the student didn't set it, is held but
    never below the risk-free rate (a lender's floor, and Hamada's riskless debt: the run's book
    interest over book debt can be below it, and would make more debt cheaper than riskless)."""
    for name in SET_BY_DEBT:
        if (name, SINGLE) in out:
            raise _refuse(
                "set_by_debt_change",
                f"{name} follows the debt change (bought back at the as-of price, beta "
                "relevered); change debt or it, not both",
                name=name,
            )

    def child(name: str) -> float:
        c = out.get((name, SINGLE))
        return index[(name, SINGLE)].value if c is None else c.after

    debt = out[(DEBT, SINGLE)]
    price = index.get(("price", SINGLE))
    if price is None or price.value is None or not price.value > 0:
        raise _refuse("no_price", "the run has no positive as-of share price to trade at")
    d_before, d_after = debt.before, debt.after
    shares, equity = index[("shares", SINGLE)].value, index[("equity_market_value", SINGLE)].value
    shares_after = shares - (d_after - d_before) / price.value
    if not shares_after > 0:
        raise _refuse(
            "buyback_exceeds_market_value",
            "a buyback can't retire more than every share at the as-of price",
            debt_change=d_after - d_before,
            equity_market_value=equity,
        )
    equity_after = price.value * shares_after
    moved: dict[tuple[str, str], RowChange] = {}
    if d_after != d_before:
        moved[("shares", SINGLE)] = RowChange("shares", SINGLE, shares, shares_after, "buyback")
        moved[("equity_market_value", SINGLE)] = RowChange(
            "equity_market_value", SINGLE, equity, equity_after, "buyback"
        )
        beta = index[("beta", SINGLE)].value
        unlevered = fm.unlevered_beta(
            beta, d_before, equity, index[("debt_tax_rate", SINGLE)].value
        )
        relevered = fm.relevered_beta(unlevered, d_after, equity_after, child("debt_tax_rate"))
        moved[("beta", SINGLE)] = RowChange("beta", SINGLE, beta, relevered, "relevered")
        kd, rf = index[("cost_of_debt", SINGLE)].value, child("risk_free")
        if ("cost_of_debt", SINGLE) not in out and d_after > 0 and kd < rf:
            if d_before == 0:  # the stored 0 is a placeholder: no rate to hold
                raise _refuse(
                    "cost_of_debt_needed",
                    "the run had no debt, so it has no cost of debt: set cost_of_debt too",
                    debt_before=d_before,
                )
            moved[("cost_of_debt", SINGLE)] = RowChange(
                "cost_of_debt", SINGLE, kd, rf, "floored_at_risk_free"
            )
    if d_after > 0 and child("cost_of_debt") == 0 and ("cost_of_debt", SINGLE) not in moved:
        raise _refuse(
            "cost_of_debt_needed",
            "the run had no debt, so it has no cost of debt: set cost_of_debt too",
            debt_before=d_before,
        )
    return moved


def _switch(rows: list[Assumption], change: Change) -> RowChange:
    """The terminal formula switched to `change.method` (a what-if only, owner decision)."""
    if change.value is not None or change.delta is not None or change.method is None:
        raise _refuse("value_and_delta", f"{TERMINAL}: give a method, not a number")
    if change.period not in (None, SINGLE):
        raise _refuse(
            "period_on_single_value",
            f"{TERMINAL} has one value for the whole run",
            name=TERMINAL,
            period=change.period,
        )
    if change.method not in TERMINAL_METHODS:
        raise _refuse(
            "unknown_terminal_method",
            f"no terminal method {change.method!r}",
            method=change.method,
            allowed=list(TERMINAL_METHODS),
        )
    before = dcf.terminal_method(rows)
    if change.method == before:
        raise _refuse(
            "same_terminal_method",
            f"the run already uses {before}",
            method=before,
        )
    return RowChange(TERMINAL, SINGLE, before, change.method, "switch")


def forecast_year(i: int) -> int:
    """Forecast year 1–5 of the i-th forecast period (8 quarters, then Y3–Y5), as math_engine."""
    return i // 4 + 1 if i < dcf.QUARTERS else dcf.QUARTERS // 4 + 1 + (i - dcf.QUARTERS)


def _fades(rows: list[Assumption]) -> bool:
    """Was the run's revenue growth built by math_engine's fade to terminal growth?"""
    growth = [a for a in rows if a.name == "revenue_growth"]
    return bool(growth) and all(FADE in a.method for a in growth)


def _follows_risk_free(rows: list[Assumption]) -> bool:
    """Does the run tie terminal growth to the risk-free rate (the owner's choice)?"""
    for a in rows:
        if a.name == "terminal_growth_method" and a.source == "user":
            return a.method.split(":")[0].strip() == "risk_free"
    return False


def _child_rows(rows: list[Assumption], moved: list[RowChange], parent: str) -> list[Assumption]:
    by_key = {(c.name, c.period): c for c in moved}
    have = {(a.name, a.period) for a in rows}
    # a row the parent doesn't have (a set WACC) goes last, after the parent's rows
    new = [
        Assumption(
            name=c.name,
            period=c.period,
            value=None if c.how == "switch" else c.before,
            source="user",
            method="new",
        )
        for c in moved
        if (c.name, c.period) not in have
    ]
    out = []
    for a in rows + new:
        c = by_key.get((a.name, a.period))
        if c is None:
            out.append(a)
            continue
        if c.how == "switch":  # the choice is read before the first colon, as on every run
            method = (
                f"{c.after}: what-if on {parent}: switched from {c.before} (a student's contrast, "
                "allowed on what-ifs only, owner decision nov.05.2026)"
            )
            out.append(
                Assumption(name=a.name, period=a.period, value=None, source="user", method=method)
            )
            continue
        how = {
            "set": f"set to {c.after!r}",
            "add": f"{c.before!r} + {c.after - c.before!r}",
            "follows_risk_free": "follows the risk-free rate (terminal_growth_method risk_free)",
            "follows_terminal_growth": (
                f"{c.before!r} + {c.after - c.before!r}: the fade to terminal growth, "
                "with the new terminal growth"
            ),
            "buyback": f"{c.after!r}: follows the debt change, swapped with equity at the "
            "as-of price",
            "relevered": f"{c.after!r}: Hamada, unlevered at the run's debt and relevered at "
            "the new debt and market value of equity",
            "floored_at_risk_free": f"{c.after!r}: the risk-free rate, since the run's book "
            "cost of debt is below it and the debt changed",
        }[c.how]
        if a.name == DEBT and a.period == SINGLE:
            how += " (use buyback: swapped with equity at the as-of price)"
        method = f"what-if on {parent}: {how} (was {c.before!r})"
        out.append(
            Assumption(name=a.name, period=a.period, value=c.after, source="user", method=method)
        )
    return out


def _value(rows: list[Assumption]):
    try:
        return dcf.outputs_and_gaps(rows)
    except fm.FinancialMathError as e:
        params = {}
        if e.reason == "growth_not_below_rate":  # the two numbers, so the app can say them
            try:
                inp = dcf.inputs(rows)
                params = {"wacc": dcf.base_wacc(inp), "terminal_growth": inp.one["terminal_growth"]}
            except (dcf.DCFInputError, fm.FinancialMathError):
                params = {}  # never hide the refusal behind a second error
        raise _refuse(e.reason, f"{REASON_WORDS[e.reason]}: {e}", **params) from e


def _change_pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before <= 0:
        return None
    return fm.growth(after, before)


def _lines(
    parent: dict, child: dict, periods: list[str], currency: str, changed: set[str]
) -> list[Line]:
    keys = [(name, SINGLE) for name in SINGLE_LINES]
    keys += [(name, p) for name in PERIOD_LINES for p in periods]
    out = []
    for name, period in keys:
        before, after = parent.get((name, period)), child.get((name, period))
        unit = (
            "fraction"
            if name in FRACTIONS
            else ("per_share" if name == "value_per_share" else currency)
        )
        change = None if before is None or after is None else after - before
        driven_by = sorted(DEPENDS[name] & changed) if change else []
        # a rate's change is in points (`change`); a percent of a percent would mislead
        pct = None if unit == "fraction" else _change_pct(before, after)
        out.append(Line(name, period, unit, before, after, change, pct, driven_by))
    return out


def _shown(outputs: dict, rows: list[Assumption]) -> dict:
    """Outputs plus the lines a student follows that a run doesn't store as outputs: the terminal
    growth and minority interest it used, and operating taxes (EBIT − NOPAT)."""
    single = {a.name: a.value for a in rows if a.period == SINGLE}
    extra = {
        ("terminal_growth", SINGLE): single["terminal_growth"],
        ("minority_interest", SINGLE): single["minority_interest"],
    }
    for (name, period), ebit in outputs.items():
        if name == "ebit":
            extra[("operating_taxes", period)] = ebit - outputs[("nopat", period)]
    return outputs | extra


def _existing_child(conn: sqlite3.Connection, parent: str, rows: list[Assumption]) -> str | None:
    want = {(a.name, a.period, a.value, a.source, a.method) for a in rows}
    for r in conn.execute(
        "SELECT run_id FROM runs WHERE parent_run_id = ? ORDER BY run_id", (parent,)
    ):
        have = {
            (a.name, a.period, a.value, a.source, a.method)
            for a in load_assumptions(conn, r["run_id"])
        }
        if have == want:
            return r["run_id"]
    return None


def revalue(conn: sqlite3.Connection, run_id: str, changes: list[Change]) -> WhatIf:
    """Value `run_id` again with `changes` and store it as a linked child run (or return the
    child already stored with the same rows). Raises WhatIfError, storing nothing, when the
    changes can't be valued."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise _refuse("no_run", f"no run {run_id}", run_id=run_id)
    if run["parent_run_id"] is not None:
        raise _refuse(
            "parent_is_what_if",
            f"{run_id} is itself a what-if of {run['parent_run_id']}: send every change against "
            "the original run",
            run_id=run_id,
            parent_run_id=run["parent_run_id"],
        )
    if not changes:
        raise _refuse("no_change", "name at least one input to change")
    rows = load_assumptions(conn, run_id)
    parent_rows_out = load_outputs(conn, run_id)
    moved = _changed_rows(rows, changes, parent_rows_out)
    child_rows = _child_rows(rows, moved, run_id)
    outputs, gaps = _value(child_rows)

    checks = post_check_notes(child_rows, outputs)  # coded (backlog #172)
    version = code_version()  # a git call: kept outside the lock
    # the lookup for a stored copy and the numbering happen under one write lock, so two
    # identical requests at once store one child (backlog #176)
    parent_sources = src.load(conn, run_id)
    child_sources = None
    if parent_sources:  # a parent stored before sources were recorded leaves the child without
        child_sources = src.for_child(
            parent_sources, run_id, {(c.name, c.period): (c.before, c.how) for c in moved}
        )
        src.check(child_rows, child_sources, child=True)
    with write_lock(conn):
        reused_id = _existing_child(conn, run_id, child_rows)
        if reused_id is None:
            child_id = _next_child_id(conn, run_id)
            insert_rows(conn, run, child_rows, outputs, checks, gaps, child_id, run_id, version)
            if child_sources is not None:
                src.insert(conn, child_id, child_sources)
        else:
            child_id = reused_id

    parent_notes = set((run["notes"] or "").splitlines())
    notes = [
        Coded(
            "run_warning",
            {
                "new": check.text not in parent_notes,
                "warning_code": check.code,
                "warning_params": check.params,
            },
            check.text,
        )
        for check in checks
    ]
    changed = {c.name for c in moved}
    method = dcf.terminal_method(child_rows)
    switched = next((c for c in moved if c.how == "switch"), None)
    if switched is not None:
        notes.append(
            Coded(
                "terminal_method_switched",
                {"before": switched.before, "after": switched.after},
                f"A contrast: valued under {switched.after} instead of the run's "
                f"{switched.before}; a hypothetical, not Warren's value (Koller, Goedhart and "
                "Wessels, Valuation, ch. 14, on why the two differ).",
            )
        )
        if method == dcf.GORDON:
            notes += _gordon_notes(outputs, child_rows)
    wacc_set = next((c for c in moved if c.name == dcf.WACC_SET), None)
    if wacc_set is not None:
        notes.append(
            Coded(
                "wacc_set_on_what_if",
                {"before": wacc_set.before, "after": wacc_set.after},
                "WACC is set directly, as an override and not a weighted average: it is the "
                "discount rate in every period and carries the value to the as-of date; the cost "
                "of equity, beta, the ERP and the debt weights no longer drive it, and the cost "
                "of equity shown is the run's CAPM, for reference.",
            )
        )
        if method == dcf.VALUE_DRIVER:
            notes.append(
                Coded(
                    "ronic_follows_wacc",
                    {"terminal_method": dcf.VALUE_DRIVER},
                    "Under the value-driver formula new investment is assumed to earn exactly "
                    "WACC, so the return on new investment after year 5 moved with the WACC set "
                    "here.",
                )
            )
    if any(c.name == DEBT for c in moved):
        notes += _leverage_notes(rows, child_rows, parent_rows_out, outputs, moved)
    if any(c.how == "follows_terminal_growth" for c in moved):
        notes.append(
            Coded(
                "growth_path_follows_terminal_growth",
                {},
                "Revenue growth in this run fades from its 3-year average to terminal growth, so "
                "years 2–5 moved with the new terminal growth; set revenue_growth to hold them.",
            )
        )
    # with a debt change, cost_of_debt_held_on_leverage says it (one reason, product lead)
    if "risk_free" in changed and "cost_of_debt" not in changed and DEBT not in changed:
        notes.append(
            Coded(
                "cost_of_debt_held",
                {},
                "The cost of debt is the company's own interest over its debt and did not move "
                "with the risk-free rate; set cost_of_debt to move it too.",
            )
        )
    if "risk_free" in changed:
        notes.append(
            Coded(
                "cash_flows_held",
                {},
                "Only rates moved: if the risk-free rate moves because of inflation, nominal cash "
                "flows would move too, and this what-if holds them.",
            )
        )
    if any(c.how == "follows_risk_free" for c in moved):
        tg = next(c for c in moved if c.how == "follows_risk_free")
        notes.append(
            Coded(
                "terminal_growth_follows_risk_free",
                {"before": tg.before, "after": tg.after},
                "Terminal growth equals the risk-free rate in this run (the owner's "
                "terminal_growth_method), so it moved with it; set terminal_growth to keep it.",
            )
        )
    for (name, _period), gap in sorted(gaps.items()):
        notes.append(
            Coded(
                "no_value",
                {"name": name, "reason": gap.reason},
                f"No {name.replace('_', ' ')}: {REASON_WORDS[gap.reason]}",
            )
        )
    periods = dcf.forecast_periods(dcf._index(rows))[1]
    currency = _currency(conn)
    return WhatIf(
        run_id=child_id,
        parent_run_id=run_id,
        ticker=run["ticker"],
        as_of=run["as_of"],
        currency=currency,
        reused=reused_id is not None,
        terminal_method=method,
        terminal_formula=TERMINAL_FORMULAS[method],
        changes=moved,
        lines=_lines(
            _shown(parent_rows_out, rows), _shown(outputs, child_rows), periods, currency, changed
        ),
        notes=notes,
    )


def _leverage_notes(
    parent_rows: list[Assumption],
    child_rows: list[Assumption],
    parent_out: dict,
    child_out: dict,
    moved: list[RowChange],
) -> list[Coded]:
    """What a debt change did, with every number the app needs to say why WACC and value per
    share moved (product lead): the swap, the weights, beta relevered, the interest coverage, and
    value per share split into the swap at the parent's enterprise value and the rest."""
    before = {a.name: a.value for a in parent_rows if a.period == SINGLE}
    after = {a.name: a.value for a in child_rows if a.period == SINGLE}

    def weight(row: dict) -> float:
        return fm.ratio(row[DEBT], row[DEBT] + row["equity_market_value"])

    def coverage(row: dict, out: dict) -> float | None:
        """Year-1 forecast EBIT over the interest the debt costs (cost of debt × debt)."""
        quarters = dcf.forecast_periods(dcf._index(child_rows))[1][:4]
        ebit = sum(out[("ebit", p)] for p in quarters)
        interest = row["cost_of_debt"] * row[DEBT]
        return fm.ratio(ebit, interest) if interest > 0 else None

    unlevered = fm.unlevered_beta(
        before["beta"], before[DEBT], before["equity_market_value"], before["debt_tax_rate"]
    )
    params = {
        "use": "buyback",
        "debt_before": before[DEBT],
        "debt_after": after[DEBT],
        "shares_before": before["shares"],
        "shares_after": after["shares"],
        "price": before["price"],
        "beta_before": before["beta"],
        "beta_after": after["beta"],
        "unlevered_beta": unlevered,
        "debt_tax_rate_before": before["debt_tax_rate"],
        "debt_tax_rate_after": after["debt_tax_rate"],
        "cost_of_debt_before": before["cost_of_debt"],
        "cost_of_debt_after": after["cost_of_debt"],
        "debt_weight_before": weight(before),
        "debt_weight_after": weight(after),
        "interest_coverage_before": coverage(before, parent_out),
        "interest_coverage_after": coverage(after, child_out),
    }
    notes = [
        Coded(
            "leverage_changed",
            params,
            f"Debt went from {params['debt_before']:,.0f} to {params['debt_after']:,.0f}, swapped "
            f"with equity at the as-of price of {params['price']:,.2f} a share. Beta was "
            f"relevered by Hamada's rule, from {params['beta_before']:.3f} to "
            f"{params['beta_after']:.3f} (the business alone: {unlevered:.3f}); it starts from "
            "the run's Blume-adjusted beta and the run's effective tax rate, assumes the debt "
            "carries no market risk, and of the usual rules gives the largest tax saving. Debt is "
            "at book value as the run counts it (operating leases out).",
        )
    ]
    # value per share at the parent's enterprise value: what the swap alone does at the price
    swapped = fm.value_per_share(
        fm.equity_value(
            parent_out[("enterprise_value_as_of", SINGLE)],
            child_out[("net_debt", SINGLE)],
            after["minority_interest"],
        ),
        after["shares"],
    )
    vps_before = parent_out[("value_per_share", SINGLE)]
    vps_after = child_out[("value_per_share", SINGLE)]
    notes.append(
        Coded(
            "buyback_at_market_price",
            {
                "price": before["price"],
                "value_per_share_before": vps_before,
                "value_per_share_at_parent_enterprise_value": swapped,
                "swap_effect": swapped - vps_before,
                "enterprise_value_effect": vps_after - swapped,
            },
            "Shares are bought back (or issued) at the market price, not at Warren's value: when "
            "Warren's value per share is below the price, a buyback moves value away from the "
            "shareholders who stay, and above it, towards them. Of the change in value per share, "
            f"{swapped - vps_before:+,.2f} is the swap at the run's enterprise value and "
            f"{vps_after - swapped:+,.2f} the change in enterprise value (the new WACC and any "
            "other input changed).",
        )
    )
    floored = next((c for c in moved if c.how == "floored_at_risk_free"), None)
    if floored is not None:
        notes.append(
            Coded(
                "cost_of_debt_floored_at_risk_free",
                {"before": floored.before, "after": floored.after},
                "The run's cost of debt is past interest over book debt and is below the "
                "risk-free rate, which no lender charges on new borrowing; with debt changed, "
                "the whole debt is priced at the risk-free rate, the lowest a lender would ask. "
                "Set cost_of_debt to price it higher.",
            )
        )
    student_set = any(c.name == "cost_of_debt" and c.how in ("set", "add") for c in moved)
    if params["debt_after"] > params["debt_before"] and not student_set:
        notes.append(
            Coded(
                "cost_of_debt_held_on_leverage",
                {"cost_of_debt": params["cost_of_debt_after"]},
                "The cost of debt did not rise with the new debt, though lenders charge more "
                "as debt grows, and the what-if counts no cost of financial distress: the fall "
                "in WACC is the tax saving on interest, before those costs, so it overstates "
                "the gain (Damodaran, Applied Corporate Finance, ch. 8). Set cost_of_debt to "
                "price the new debt.",
            )
        )
    return notes


def _gordon_notes(outputs: dict, rows: list[Assumption]) -> list[Coded]:
    """What a Gordon value on this child assumes, with the sensitivity grid's codes and params so
    one screen string serves both (product lead): year 5's reinvestment is held while growth runs
    on, and, when year 5 reinvests nothing (or NOPAT isn't positive), its growth comes from no
    investment; otherwise the return on new investment it implies, g ÷ the reinvestment rate."""
    last = dcf.YEARS[-1]
    growth = next(a.value for a in rows if a.name == "terminal_growth" and a.period == SINGLE)
    try:
        reinvest = fm.reinvestment_rate(outputs[("fcff", last)], outputs[("nopat", last)])
    except fm.FinancialMathError:  # NOPAT at or below zero: no rate (as the grid)
        reinvest = None
    notes = [
        Coded(
            "gordon_holds_reinvestment",
            {"reinvestment_rate": reinvest},
            "The Gordon formula grows year 5's free cash flow, whose reinvestment is fixed, so "
            "more growth comes at no extra investment.",
        )
    ]
    if reinvest is None or reinvest <= 0:
        notes.append(
            Coded(
                "gordon_reinvestment_not_positive",
                {"reinvestment_rate": reinvest},
                "In year 5 this run reinvests nothing or takes capital out, so the Gordon "
                "formula's growth comes from no investment and implies no return: read its "
                "value as a formula, not a valuation.",
            )
        )
        return notes
    ronic = fm.implied_ronic(growth, reinvest)
    params = {
        "implied_ronic": ronic,
        "reinvestment_rate": reinvest,
        "terminal_growth": growth,
        "wacc": outputs[("wacc", SINGLE)],
    }
    notes.append(
        Coded(
            "gordon_implied_ronic",
            params,
            f"Under Gordon, growth of {growth:.2%} with {reinvest:.1%} of NOPAT reinvested "
            f"assumes new investment earns {ronic:.1%} forever, against a WACC of "
            f"{params['wacc']:.2%}.",
        )
    )
    return notes


def _next_child_id(conn: sqlite3.Connection, parent: str) -> str:
    count = conn.execute("SELECT COUNT(*) FROM runs WHERE parent_run_id = ?", (parent,)).fetchone()[
        0
    ]
    return f"{parent}_whatif_{count + 1}"
