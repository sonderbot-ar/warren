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
from domains.analysis.math_engine import post_checks
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

# `debt` is left out on purpose (design review): one row is both the WACC's debt weight and the
# claim on the firm, and beta is not relevered, so more debt would lower WACC for free (Hamada
# 1972; Modigliani–Miller 1958). A leverage what-if needs its own design.
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
)
CHANGEABLE = dcf.DRIVERS + CHANGEABLE_SINGLE
# (low, high, low included, high included): checked before any arithmetic; None = no bound
BOUNDS = {
    "shares": (0.0, None, False, None),
    "cash_and_investments": (0.0, None, True, None),
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
_RATE = {"risk_free", "beta", "erp", "cost_of_debt", "debt_tax_rate"}
_VALUE = _CASH_FLOW | _RATE | {"terminal_growth"}
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
    "net_debt": {"cash_and_investments"},
    "minority_interest": {"minority_interest"},
    "equity_value": _VALUE | {"cash_and_investments", "minority_interest"},
    "value_per_share": _VALUE | {"cash_and_investments", "minority_interest", "shares"},
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


@dataclass(frozen=True)
class RowChange:
    name: str
    period: str
    before: float
    after: float
    how: str  # set, add, follows_risk_free, follows_terminal_growth


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


def _changed_rows(rows: list[Assumption], changes: list[Change]) -> list[RowChange]:
    index = {(a.name, a.period): a for a in rows}
    periods = dcf.forecast_periods(dcf._index(rows))[1]
    out: dict[tuple[str, str], RowChange] = {}
    for change in changes:
        for period in _targets(change, periods):
            key = (change.name, period)
            if key in out:
                raise _refuse(
                    "duplicate_change",
                    f"{change.name} {period} is changed twice",
                    name=change.name,
                    period=period,
                )
            before = index[key].value
            if change.value is not None:
                after, how = change.value, "set"
            else:
                after, how = before + change.delta, "add"
            _check_bounds(change.name, after)
            out[key] = RowChange(change.name, period, before, after, how)
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
    out = []
    for a in rows:
        c = by_key.get((a.name, a.period))
        if c is None:
            out.append(a)
            continue
        how = {
            "set": f"set to {c.after!r}",
            "add": f"{c.before!r} + {c.after - c.before!r}",
            "follows_risk_free": "follows the risk-free rate (terminal_growth_method risk_free)",
            "follows_terminal_growth": (
                f"{c.before!r} + {c.after - c.before!r}: the fade to terminal growth, "
                "with the new terminal growth"
            ),
        }[c.how]
        method = f"what-if on {parent}: {how} (was {c.before!r})"
        out.append(
            Assumption(name=a.name, period=a.period, value=c.after, source="user", method=method)
        )
    return out


def _value(rows: list[Assumption]):
    try:
        return dcf.outputs_and_gaps(rows)
    except fm.FinancialMathError as e:
        raise _refuse(e.reason, f"{REASON_WORDS[e.reason]}: {e}") from e


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
    moved = _changed_rows(rows, changes)
    child_rows = _child_rows(rows, moved, run_id)
    outputs, gaps = _value(child_rows)
    parent_rows_out = load_outputs(conn, run_id)

    notes_text = post_checks(child_rows, outputs)
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
            insert_rows(conn, run, child_rows, outputs, notes_text, gaps, child_id, run_id, version)
            if child_sources is not None:
                src.insert(conn, child_id, child_sources)
        else:
            child_id = reused_id

    parent_notes = set((run["notes"] or "").splitlines())
    notes = [Coded("run_warning", {"new": text not in parent_notes}, text) for text in notes_text]
    changed = {c.name for c in moved}
    if any(c.how == "follows_terminal_growth" for c in moved):
        notes.append(
            Coded(
                "growth_path_follows_terminal_growth",
                {},
                "Revenue growth in this run fades from its 3-year average to terminal growth, so "
                "years 2–5 moved with the new terminal growth; set revenue_growth to hold them.",
            )
        )
    if "risk_free" in changed and "cost_of_debt" not in changed:
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
    method = dcf.terminal_method(rows)
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


def _next_child_id(conn: sqlite3.Connection, parent: str) -> str:
    count = conn.execute("SELECT COUNT(*) FROM runs WHERE parent_run_id = ?", (parent,)).fetchone()[
        0
    ]
    return f"{parent}_whatif_{count + 1}"
