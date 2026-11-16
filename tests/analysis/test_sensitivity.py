"""Sensitivity grid (backlog #142): value per share over WACC × terminal growth on a stored run."""

import json

import pytest

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis.runs import load_assumptions, load_outputs, run_baseline
from domains.analysis.schemas import SINGLE
from domains.analysis.sensitivity import (
    GROWTH_STEPS,
    WACC_STEPS,
    GridError,
    grid,
)
from domains.analysis.whatif import Change, revalue
from tests.analysis.conftest import AS_OF, CHOICES


@pytest.fixture
def run(company):
    return run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)


@pytest.fixture
def gordon_run(company):
    choices = {k: v for k, v in CHOICES.items() if k != "terminal_method"}
    return run_baseline(company, "TST", AS_OF, choices=choices, today=AS_OF)


def _inputs(conn, run_id):
    return dcf.inputs(load_assumptions(conn, run_id))


def _point(g, block):
    return block.cells[g.run_point["row"]][g.run_point["column"]]


def _counts(conn):
    tables = ("runs", "assumptions", "run_outputs", "run_output_gaps")
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def _wide(conn, run_id, steps=WACC_STEPS):
    """Explicit WACC steps: the default axis may leave some out on the test company."""
    return grid(conn, run_id, wacc_steps=steps)


def test_the_runs_point_is_its_stored_value_per_share(company, run):
    g = grid(company, run)
    stored = load_outputs(company, run)[("value_per_share", SINGLE)]
    assert _point(g, g.method).value_per_share == stored  # exactly, not approximately
    assert _point(g, g.method).change_pct == 0.0
    assert g.method.terminal_method == dcf.VALUE_DRIVER
    assert g.contrast.terminal_method == dcf.GORDON
    assert g.method.terminal_formula.code == "value_driver"
    assert g.contrast.terminal_formula.code == "gordon"


def test_a_gordon_run_has_value_driver_as_its_contrast(company, gordon_run):
    g = grid(company, gordon_run)
    assert g.method.terminal_method == dcf.GORDON
    assert g.contrast.terminal_method == dcf.VALUE_DRIVER
    stored = load_outputs(company, gordon_run)[("value_per_share", SINGLE)]
    assert _point(g, g.method).value_per_share == stored


def test_explicit_steps_give_a_five_by_five_grid_with_the_point_in_the_middle(company, run):
    g = _wide(company, run)
    assert len(g.method.cells) == 5 and all(len(row) == 5 for row in g.method.cells)
    assert g.run_point == {"row": 2, "column": 2}
    assert g.wacc_steps == list(WACC_STEPS) and g.growth_steps == list(GROWTH_STEPS)
    inp = _inputs(company, run)
    assert g.wacc_values == [dcf.base_wacc(inp) + s for s in WACC_STEPS]
    assert g.growth_values == [inp.one["terminal_growth"] + s for s in GROWTH_STEPS]


def test_a_missing_zero_is_added_and_steps_are_sorted(company, run):
    g = grid(company, run, wacc_steps=[0.02, -0.01], growth_steps=[0.005])
    assert g.wacc_steps == [-0.01, 0.0, 0.02] and g.growth_steps == [0.0, 0.005]
    assert g.run_point == {"row": 1, "column": 0}


@pytest.mark.parametrize(
    "wacc_steps, growth_steps, code",
    [
        ([0.0], GROWTH_STEPS, "too_few_steps"),
        ([], GROWTH_STEPS, "too_few_steps"),
        ([i / 100 for i in range(1, 10)], GROWTH_STEPS, "too_many_steps"),
        ([0.01, float("nan")], GROWTH_STEPS, "invalid_input"),
        (WACC_STEPS, [0.01, float("inf")], "invalid_input"),
        ([0.01, 0.01], GROWTH_STEPS, "duplicate_step"),
    ],
)
def test_bad_axes_are_refused_with_a_code(company, run, wacc_steps, growth_steps, code):
    with pytest.raises(GridError) as e:
        grid(company, run, wacc_steps=wacc_steps, growth_steps=growth_steps)
    assert e.value.code == code and "axis" in e.value.params


def test_an_unknown_run_is_refused(company):
    with pytest.raises(GridError) as e:
        grid(company, "NOPE_1")
    assert e.value.code == "no_run"


@pytest.mark.parametrize("block", ["method", "contrast"])
def test_a_cell_is_the_valuation_with_wacc_and_growth_set(company, run, block):
    g = _wide(company, run)
    b = getattr(g, block)
    inp = _inputs(company, run)
    i, j = 4, 0  # highest WACC, lowest growth: every method has a value there
    by_hand = dcf.compute(
        inp.replace(
            wacc_override=g.wacc_values[i],
            one=inp.one | {"terminal_growth": g.growth_values[j]},
            terminal_method=b.terminal_method,
        )
    )
    cell = b.cells[i][j]
    assert abs(cell.value_per_share - by_hand.value_per_share) < 0.005
    assert cell.terminal_value == pytest.approx(by_hand.dcf.terminal_value)
    assert cell.equity_value == pytest.approx(by_hand.equity_value)
    base = _point(g, b).value_per_share
    assert cell.change_pct == pytest.approx(fm.growth(cell.value_per_share, base))


def test_the_explicit_forecast_is_held_in_every_cell(company, run):
    g = _wide(company, run)
    pv = {c.pv_explicit for row in g.method.cells for c in row if c.value_per_share is not None}
    by_wacc = {}
    for i, row in enumerate(g.method.cells):
        by_wacc[i] = {c.pv_explicit for c in row if c.pv_explicit is not None}
    # along a row (same WACC) only the terminal value moves
    assert all(len(v) == 1 for v in by_wacc.values() if v)
    assert len(pv) > 1  # WACC moves the explicit years' discounting
    bases = {c.terminal_base for row in g.method.cells for c in row if c.terminal_base}
    assert len(bases) == 1  # year 5 NOPAT is the stored one everywhere


def test_value_driver_is_flatter_along_growth_than_gordon(company, run):
    g = _wide(company, run)
    vd, gordon = g.method, g.contrast
    assert abs(vd.growth_spread.per_point) < abs(gordon.growth_spread.per_point)
    assert vd.growth_to_wacc < gordon.growth_to_wacc
    lesson = g.notes[-1]
    assert lesson.code == "flatter_along_growth"
    assert lesson.params == {"value_driver": vd.growth_to_wacc, "gordon": gordon.growth_to_wacc}


def test_growth_at_wacc_has_no_value_under_both_methods_never_zero(company, run):
    inp = _inputs(company, run)
    spread = dcf.base_wacc(inp) - inp.one["terminal_growth"]
    g = grid(company, run, wacc_steps=[-spread], growth_steps=[0.0, 0.001])
    for block in (g.method, g.contrast):
        for cell in block.cells[0]:
            assert cell.value_per_share is None and cell.gap.code == "growth_not_below_rate"
            assert cell.change_pct is None and cell.change_pct_gap == "no_value"
            assert cell.thin_spread


def test_a_wacc_at_or_below_zero_has_no_value_under_both_methods(company, run):
    inp = _inputs(company, run)
    wacc = dcf.base_wacc(inp)
    g = grid(company, run, wacc_steps=[-wacc, -wacc - 0.01], growth_steps=[-0.2])
    for block in (g.method, g.contrast):
        for row in block.cells[:2]:
            assert row[0].value_per_share is None and row[0].gap.code == "rate_not_positive"


def test_a_spread_uses_the_ends_that_have_a_value(company, run):
    inp = _inputs(company, run)
    spread = dcf.base_wacc(inp) - inp.one["terminal_growth"]
    g = grid(company, run, wacc_steps=[-spread, 0.01, 0.02])
    s = g.method.wacc_spread
    assert s.low_step == 0.0 and s.high_step == 0.02  # the row at growth = WACC has no value
    assert s.per_point == pytest.approx(
        fm.change_per_point(s.low_value, s.high_value, _point(g, g.method).value_per_share, 0, 0.02)
    )


def test_a_spread_with_one_value_has_none_and_the_lesson_is_not_shown(company, run):
    inp = _inputs(company, run)
    spread = dcf.base_wacc(inp) - inp.one["terminal_growth"]
    g = grid(company, run, wacc_steps=[-spread])
    assert g.method.wacc_spread.per_point is None
    assert g.method.wacc_spread.gap == "fewer_than_two_values"
    assert g.notes[-1].code == "lesson_not_shown"


def test_the_default_axis_leaves_out_steps_too_close_to_growth(company, run):
    inp = _inputs(company, run)
    gap = dcf.base_wacc(inp) - inp.one["terminal_growth"]
    g = grid(company, run)
    kept = [s for s in WACC_STEPS if s == 0 or gap + s >= 0.005]
    assert g.wacc_steps == kept
    left = [n for n in g.notes if n.code == "default_step_left_out"]
    if kept != list(WACC_STEPS):
        assert left[0].params["steps"] == [s for s in WACC_STEPS if s not in kept]
    else:
        assert not left


def test_gordon_cells_show_the_return_their_growth_implies(company, run):
    g = _wide(company, run)
    reinvest = g.contrast.reinvestment_rate
    inp = _inputs(company, run)
    plain = dcf.compute(inp)
    assert reinvest == fm.reinvestment_rate(plain.lines["fcff"][-1], plain.lines["nopat"][-1])
    cell = g.contrast.cells[4][0]
    if reinvest > 0:
        assert cell.implied_ronic == pytest.approx(cell.terminal_growth / reinvest)
    assert all(c.implied_ronic is None for row in g.method.cells for c in row)


def test_the_notes_say_what_the_grid_holds(company, run):
    codes = [n.code for n in grid(company, run).notes]
    for code in (
        "sensitivity_not_range",
        "wacc_set_directly",
        "growth_path_held",
        "contrast_method",
        "ronic_follows_wacc",
        "gordon_holds_reinvestment",
    ):
        assert code in codes


def test_nothing_is_stored_and_the_same_call_gives_the_same_numbers(company, run):
    before = _counts(company)
    first, second = grid(company, run).to_dict(), grid(company, run).to_dict()
    assert first == second
    assert _counts(company) == before
    assert json.loads(json.dumps(first)) == first


def test_a_what_if_child_can_be_the_grids_run(company, run):
    child = revalue(company, run, [Change("operating_margin", delta=-0.01)]).run_id
    g = grid(company, child)
    stored = load_outputs(company, child)[("value_per_share", SINGLE)]
    assert _point(g, g.method).value_per_share == stored


def test_the_wacc_note_says_when_the_runs_own_wacc_was_set(company, run):
    # backlog #212: on a baseline the run's rate comes from CAPM; on a child with WACC set it
    # does not, and the note's param and text say so
    base = next(n for n in grid(company, run).notes if n.code == "wacc_set_directly")
    assert base.params["run_wacc_set"] is False and "comes from CAPM" in base.text
    child = revalue(company, run, [Change("wacc", delta=0.01)]).run_id
    g = grid(company, child)
    note = next(n for n in g.notes if n.code == "wacc_set_directly")
    set_rate = dcf.inputs(load_assumptions(company, child)).wacc_override
    assert note.params == {"run_wacc": set_rate, "run_wacc_set": True}
    assert "own WACC was set directly too" in note.text
    assert [n.code for n in g.notes].count("wacc_set_directly") == 1
    centre = g.method.cells[g.run_point["row"]][g.run_point["column"]].value_per_share
    assert centre == load_outputs(company, child)[("value_per_share", SINGLE)]
