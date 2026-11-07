"""Sensitivity grid: value per share over WACC and terminal growth on a stored run (backlog #142).

The query behind brief question 9 (`docs/product/brief.md`): "how sensitive is Coca-Cola's value
to WACC and terminal growth?" Each cell values the run's stored rows again with WACC set directly
(`dcf.Inputs.wacc_override`, in memory) and terminal growth moved; the explicit forecast is held.
Each cell is valued twice: under the run's own terminal method and under the other one, labelled
as a contrast.

- No data is read and nothing is stored: the grid is a pure function of the run's rows and the
  two step lists, so the same call returns the same numbers. No LLM is called: every number comes
  from `dcf` and `financial_math`.
- Every refusal, gap and note is a stable code with parameters; `text` is an English fallback, as
  in `reported.py` and `whatif.py`.
- Values are raw: fractions for rates and shares, currency per share for value per share.
"""

import math
import sqlite3
from dataclasses import asdict, dataclass, field

from domains.analysis import dcf, gordon
from domains.analysis import financial_math as fm
from domains.analysis.math_engine import _thin
from domains.analysis.montecarlo import _currency
from domains.analysis.reported import Coded
from domains.analysis.runs import load_assumptions, load_outputs
from domains.analysis.schemas import SINGLE
from domains.analysis.text import REASON_WORDS
from domains.analysis.whatif import TERMINAL_FORMULAS, _follows_risk_free

# shifts from the run's own value, in fractions (0.01 = one point)
WACC_STEPS = (-0.02, -0.01, 0.0, 0.01, 0.02)
GROWTH_STEPS = (-0.01, -0.005, 0.0, 0.005, 0.01)
MIN_STEPS, MAX_STEPS = 2, 9  # per axis, counted after the run's own 0 is added
# the default WACC axis leaves out a step whose WACC is not at least this far above the run's
# terminal growth: on Coca-Cola, Johnson & Johnson and Exxon (WACC 1.5–2 points above growth)
# the −2 point row would be nearly all "no value" (design review, analyst)
DEFAULT_MIN_GAP = 0.005
OTHER = {dcf.VALUE_DRIVER: dcf.GORDON, dcf.GORDON: dcf.VALUE_DRIVER}
CONTRAST_WORDS = {
    dcf.GORDON: "Gordon on free cash flow is the formula Warren used before it tied "
    "reinvestment to growth (Structure Guide Decision 4, oct.30.2026).",
    dcf.VALUE_DRIVER: "The value-driver formula is the one Warren has used since oct.30.2026; "
    "this run was stored before it.",
}


class GridError(ValueError):
    """A grid that can't be valued: `code` and `params` say why."""

    def __init__(self, code: str, params: dict, text: str):
        super().__init__(text)
        self.code, self.params, self.text = code, params, text

    def coded(self) -> Coded:
        return Coded(self.code, self.params, self.text)


@dataclass(frozen=True)
class Cell:
    wacc: float
    terminal_growth: float
    wacc_step: float
    growth_step: float
    value_per_share: float | None
    change_pct: float | None  # against the run's point in the same block
    change_pct_gap: str | None  # no_value (this cell or the run's point), base_not_positive
    terminal_share: float | None  # None when there is no value or the enterprise value is ≤ 0
    terminal_base: float | None  # Y5 NOPAT (value driver) or Y5 FCFF (Gordon)
    terminal_value: float | None
    pv_explicit: float | None
    pv_terminal: float | None
    enterprise_value_as_of: float | None
    equity_value: float | None
    implied_ronic: float | None  # Gordon only: growth ÷ the Y5 reinvestment rate
    thin_spread: bool  # WACC − growth under the run warning's 3 points: the terminal value rules
    gap: Coded | None


@dataclass(frozen=True)
class Spread:
    """Value along one axis line through the run's point, between its lowest and highest steps
    that have a value."""

    axis: str  # wacc or terminal_growth
    low_step: float | None
    high_step: float | None
    low_value: float | None
    high_value: float | None
    low_change_pct: float | None
    high_change_pct: float | None
    per_point: float | None  # change as a fraction of the run's value per point of the input
    gap: str | None  # fewer_than_two_values, base_not_positive


@dataclass(frozen=True)
class Block:
    terminal_method: str
    terminal_formula: Coded
    reinvestment_rate: float | None  # Gordon: 1 − FCFF ÷ NOPAT in Y5; None for value driver
    cells: list[list[Cell]]  # rows by WACC, columns by terminal growth
    wacc_spread: Spread
    growth_spread: Spread
    growth_to_wacc: float | None  # |growth per point| ÷ |WACC per point|


@dataclass(frozen=True)
class Grid:
    run_id: str
    ticker: str
    as_of: str
    currency: str
    wacc_steps: list[float]
    growth_steps: list[float]
    wacc_values: list[float]
    growth_values: list[float]
    run_point: dict  # row, column
    method: Block
    contrast: Block
    notes: list[Coded] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _refuse(code: str, text: str, **params) -> GridError:
    return GridError(code, params, text)


def _axis(name: str, steps) -> list[float]:
    steps = [float(s) for s in steps]
    for s in steps:
        if not math.isfinite(s):
            raise _refuse("invalid_input", f"{name} step {s} is not a finite number", axis=name)
    if len(set(steps)) != len(steps):
        raise _refuse("duplicate_step", f"a {name} step is given twice", axis=name, steps=steps)
    out = sorted(set(steps) | {0.0})
    if len(out) < MIN_STEPS:
        raise _refuse(
            "too_few_steps",
            f"the {name} axis needs at least {MIN_STEPS} values with the run's own",
            axis=name,
            count=len(out),
            min=MIN_STEPS,
            max=MAX_STEPS,
        )
    if len(out) > MAX_STEPS:
        raise _refuse(
            "too_many_steps",
            f"the {name} axis takes at most {MAX_STEPS} values with the run's own",
            axis=name,
            count=len(out),
            min=MIN_STEPS,
            max=MAX_STEPS,
        )
    return out


def _gap(reason: str, wacc: float, growth: float) -> Coded:
    return Coded(reason, {"wacc": wacc, "terminal_growth": growth}, REASON_WORDS[reason])


def _value(inp: dcf.Inputs, wacc: float, growth: float, method: str):
    """The valuation at one cell, or the reason it has none. The grid checks WACC ≤ 0 itself:
    the Gordon formula has no such check (financial_math.gordon_terminal_value), and a cell must
    not get a value there under one method and none under the other."""
    if wacc <= 0:
        return None, _gap("rate_not_positive", wacc, growth)
    cell = inp.replace(
        wacc_override=wacc, one=inp.one | {"terminal_growth": growth}, terminal_method=method
    )
    try:
        return dcf.compute(cell), None
    except fm.FinancialMathError as e:
        if e.reason not in dcf.NO_VALUE_REASONS:
            raise
        return None, _gap(e.reason, wacc, growth)


def _block(inp, method, waccs, growths, wacc_steps, growth_steps, run_point) -> Block:
    valued = [
        [_value(inp, w, g, method) for g in growths] for w in waccs
    ]  # rows by WACC, columns by growth
    r0, c0 = run_point["row"], run_point["column"]
    base = valued[r0][c0][0]
    base_value = base.value_per_share if base is not None else None
    reinvest = None
    if method == dcf.GORDON:
        plain = dcf.compute(inp)  # cash flows don't depend on WACC or growth on this grid
        reinvest = gordon.year5_reinvestment(plain.lines["fcff"][-1], plain.lines["nopat"][-1])
    cells = []
    for i, row in enumerate(valued):
        out = []
        for j, (v, gap) in enumerate(row):
            out.append(
                _cell(
                    v,
                    gap,
                    waccs[i],
                    growths[j],
                    wacc_steps[i],
                    growth_steps[j],
                    base_value,
                    method,
                    reinvest,
                )
            )
        cells.append(out)
    wacc_line = [(wacc_steps[i], cells[i][c0].value_per_share) for i in range(len(waccs))]
    growth_line = [(growth_steps[j], cells[r0][j].value_per_share) for j in range(len(growths))]
    wacc_spread = _spread("wacc", wacc_line, base_value)
    growth_spread = _spread("terminal_growth", growth_line, base_value)
    ratio = None
    if wacc_spread.per_point and growth_spread.per_point is not None:
        ratio = fm.ratio(abs(growth_spread.per_point), abs(wacc_spread.per_point))
    return Block(
        terminal_method=method,
        terminal_formula=TERMINAL_FORMULAS[method],
        reinvestment_rate=reinvest,
        cells=cells,
        wacc_spread=wacc_spread,
        growth_spread=growth_spread,
        growth_to_wacc=ratio,
    )


def _cell(v, gap, wacc, growth, wacc_step, growth_step, base_value, method, reinvest) -> Cell:
    thin = _thin(wacc - growth)
    if v is None:
        empty = dict.fromkeys(
            ("value_per_share", "change_pct", "terminal_share", "terminal_base", "terminal_value")
            + ("pv_explicit", "pv_terminal", "enterprise_value_as_of", "equity_value")
            + ("implied_ronic",)
        )
        return Cell(
            wacc=wacc,
            terminal_growth=growth,
            wacc_step=wacc_step,
            growth_step=growth_step,
            change_pct_gap="no_value",
            thin_spread=thin,
            gap=gap,
            **empty,
        )
    vps = v.value_per_share
    if base_value is None:
        change, change_gap = None, "no_value"
    elif base_value <= 0:
        change, change_gap = None, "base_not_positive"
    else:
        change, change_gap = fm.growth(vps, base_value), None
    ev = v.dcf.enterprise_value
    share = v.dcf.terminal_share if ev > 0 else None
    terminal_base = v.lines["nopat"][-1] if method == dcf.VALUE_DRIVER else v.lines["fcff"][-1]
    ronic = gordon.implied_ronic(growth, reinvest) if method == dcf.GORDON else None
    return Cell(
        wacc=wacc,
        terminal_growth=growth,
        wacc_step=wacc_step,
        growth_step=growth_step,
        value_per_share=vps,
        change_pct=change,
        change_pct_gap=change_gap,
        terminal_share=share,
        terminal_base=terminal_base,
        terminal_value=v.dcf.terminal_value,
        pv_explicit=v.dcf.pv_explicit,
        pv_terminal=v.dcf.pv_terminal,
        enterprise_value_as_of=v.enterprise_value_as_of,
        equity_value=v.equity_value,
        implied_ronic=ronic,
        thin_spread=thin,
        gap=None,
    )


def _spread(axis: str, line: list[tuple[float, float | None]], base_value) -> Spread:
    have = [(s, v) for s, v in line if v is not None]
    if len(have) < 2 or base_value is None:
        return Spread(axis, None, None, None, None, None, None, None, "fewer_than_two_values")
    (lo_s, lo_v), (hi_s, hi_v) = have[0], have[-1]
    if base_value <= 0:
        return Spread(axis, lo_s, hi_s, lo_v, hi_v, None, None, None, "base_not_positive")
    return Spread(
        axis,
        lo_s,
        hi_s,
        lo_v,
        hi_v,
        fm.growth(lo_v, base_value),
        fm.growth(hi_v, base_value),
        fm.change_per_point(lo_v, hi_v, base_value, lo_s, hi_s),
        None,
    )


def _default_wacc_steps(wacc: float, growth: float) -> tuple[list[float], list[float]]:
    kept = [s for s in WACC_STEPS if s == 0 or wacc + s - growth >= DEFAULT_MIN_GAP]
    return kept, [s for s in WACC_STEPS if s not in kept]


def grid(
    conn: sqlite3.Connection,
    run_id: str,
    wacc_steps=None,
    growth_steps=GROWTH_STEPS,
) -> Grid:
    """Value per share over WACC × terminal growth on `run_id`'s stored rows. Raises GridError,
    storing nothing, when the axes can't be used. `wacc_steps` None takes the default axis,
    leaving out steps too close to the run's terminal growth (a note lists them)."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise _refuse("no_run", f"no run {run_id}", run_id=run_id)
    rows = load_assumptions(conn, run_id)
    inp = dcf.inputs(rows)
    run_wacc = dcf.base_wacc(inp)
    run_growth = inp.one["terminal_growth"]
    left_out: list[float] = []
    if wacc_steps is None:
        wacc_steps, left_out = _default_wacc_steps(run_wacc, run_growth)
    w_steps, g_steps = _axis("wacc", wacc_steps), _axis("terminal_growth", growth_steps)
    waccs = [run_wacc + s for s in w_steps]
    growths = [run_growth + s for s in g_steps]
    point = {"row": w_steps.index(0.0), "column": g_steps.index(0.0)}
    method = dcf.terminal_method(rows)
    args = (waccs, growths, w_steps, g_steps, point)
    own, other = _block(inp, method, *args), _block(inp, OTHER[method], *args)

    stored = load_outputs(conn, run_id).get(("value_per_share", SINGLE))
    mine = own.cells[point["row"]][point["column"]].value_per_share
    if stored is not None and mine != stored:  # reproduce forbids this; never show a grid off it
        raise _refuse(
            "run_does_not_reproduce",
            f"{run_id}'s stored value per share {stored} is not its rows' {mine}",
            run_id=run_id,
        )
    notes = _notes(own, other, method, rows, g_steps, left_out, run_wacc, run_growth)
    notes[1:1] = [_wacc_note(run_wacc, run_wacc_set=dcf.wacc_is_set(rows))]
    return Grid(
        run_id=run_id,
        ticker=run["ticker"],
        as_of=run["as_of"],
        currency=_currency(conn),
        wacc_steps=w_steps,
        growth_steps=g_steps,
        wacc_values=waccs,
        growth_values=growths,
        run_point=point,
        method=own,
        contrast=other,
        notes=notes,
    )


def _wacc_note(run_wacc: float, run_wacc_set: bool) -> Coded:
    """`wacc_set_directly`: the grid sets WACC as an override. `run_wacc_set` says the run's own
    rate was set too, by a what-if (backlog #171), so it does not come from CAPM and the capital
    weights either (backlog #212); the app picks its sentence from that param."""
    if run_wacc_set:
        text = (
            "WACC is set directly here, as a teaching override. This run's own WACC was set "
            "directly too, by a what-if, so neither it nor any row of this grid comes from CAPM "
            "and the capital weights; the cost of equity is shown for reference only."
        )
    else:
        text = (
            "WACC is set directly here, as a teaching override: in the company's own valuation "
            "it comes from CAPM and the capital weights, which this grid holds."
        )
    return Coded("wacc_set_directly", {"run_wacc": run_wacc, "run_wacc_set": run_wacc_set}, text)


def _notes(own, other, method, rows, g_steps, left_out, run_wacc, run_growth) -> list[Coded]:
    notes = [
        Coded(
            "sensitivity_not_range",
            {},
            "A sensitivity: what value per share would be at other inputs, not a range of "
            "likely outcomes.",
        ),
        Coded(
            "growth_path_held",
            {"what_if": "whatif"},
            "Terminal growth moves the terminal value only; the five-year forecast is unchanged. "
            "The what-if also moves the forecast's fade to terminal growth.",
        ),
        Coded(
            "contrast_method",
            {"terminal_method": other.terminal_method},
            "The contrast table uses the other terminal formula; it is not this run's value. "
            + CONTRAST_WORDS[other.terminal_method],
        ),
    ]
    vd = own if own.terminal_method == dcf.VALUE_DRIVER else other
    notes.append(
        Coded(
            "ronic_follows_wacc",
            {"terminal_method": vd.terminal_method},
            "Under the value-driver formula new investment is assumed to earn exactly WACC, so "
            "growth after year 5 adds almost nothing: the table is flat along growth by that "
            "assumption, not by a finding about the company. Each WACC row moves that assumed "
            "return with it.",
        )
    )
    gordon_block = own if own.terminal_method == dcf.GORDON else other
    notes += gordon.reinvestment_notes(
        gordon_block.reinvestment_rate,
        "The Gordon formula grows year 5's free cash flow, whose reinvestment is fixed, so "
        "more growth comes at no extra investment: part of its steepness along growth is "
        "growth that costs nothing. Each cell shows the return on new investment it implies.",
        "In year 5 this run reinvests nothing or takes capital out, so the Gordon "
        "formula's growth comes from no investment and implies no return: read its "
        "table as a formula, not a valuation.",
    )
    if any(s > 0 for s in g_steps) and _follows_risk_free(rows):
        notes.append(
            Coded(
                "growth_above_risk_free",
                {"risk_free_growth": run_growth},
                "This run sets terminal growth to the risk-free rate; columns to its right assume "
                "the company grows faster than the economy's risk-free rate forever.",
            )
        )
    if left_out:
        notes.append(
            Coded(
                "default_step_left_out",
                {"steps": left_out, "min_gap": DEFAULT_MIN_GAP},
                "WACC steps within half a point of terminal growth were left out of the default "
                "grid; ask for them to see where the value stops existing.",
            )
        )
    notes.append(_lesson(own, other))
    return notes


def _lesson(own: Block, other: Block) -> Coded:
    """The brief's lesson, judged by a stated rule: the value-driver table is flatter along growth
    relative to WACC than the Gordon table when its growth-to-WACC ratio is the smaller one."""
    vd = own if own.terminal_method == dcf.VALUE_DRIVER else other
    gordon = other if vd is own else own
    params = {"value_driver": vd.growth_to_wacc, "gordon": gordon.growth_to_wacc}
    if vd.growth_to_wacc is None or gordon.growth_to_wacc is None:
        return Coded(
            "lesson_not_shown",
            params,
            "One table has too few values along an axis to compare the two formulas.",
        )
    if vd.growth_to_wacc < gordon.growth_to_wacc:
        return Coded(
            "flatter_along_growth",
            params,
            "Relative to WACC, value moves less with growth under the value-driver formula than "
            "under Gordon.",
        )
    return Coded(
        "not_flatter_along_growth",
        params,
        "On this run the value-driver table is not flatter along growth than Gordon's.",
    )
