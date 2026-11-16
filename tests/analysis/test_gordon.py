"""One rule for what a Gordon value assumes about year 5's reinvestment (backlog #216): the
sensitivity grid and the what-if read it from `gordon`, so they can't disagree on the same run."""

import math

import pytest

from domains.analysis import dcf, gordon
from domains.analysis import financial_math as fm
from domains.analysis.runs import load_assumptions, load_outputs, run_baseline
from domains.analysis.schemas import SINGLE
from domains.analysis.sensitivity import grid
from domains.analysis.whatif import Change, revalue
from tests.analysis.conftest import AS_OF, CHOICES


@pytest.mark.parametrize(
    ("fcff", "nopat", "rate"),
    [
        (80.0, 100.0, 0.2),  # reinvests a fifth of NOPAT
        (100.0, 100.0, 0.0),  # reinvests nothing
        (120.0, 100.0, -0.2),  # takes capital out
        (5.0, 0.0, None),  # no NOPAT: no rate
        (-5.0, -10.0, None),  # a loss: no rate
        (math.nan, 100.0, None),  # not a number: no rate
        (80.0, math.inf, None),
    ],
)
def test_year5_reinvestment(fcff, nopat, rate):
    got = gordon.year5_reinvestment(fcff, nopat)
    if rate is None:
        assert got is None
    else:
        assert got == pytest.approx(rate, abs=1e-15)
        assert got == fm.reinvestment_rate(fcff, nopat)  # the arithmetic is financial_math's


@pytest.mark.parametrize(
    ("rate", "reinvests"), [(0.2, True), (1e-12, True), (0.0, False), (-0.2, False), (None, False)]
)
def test_reinvests_and_the_implied_return(rate, reinvests):
    assert gordon.reinvests(rate) is reinvests
    ronic = gordon.implied_ronic(0.04, rate)
    assert ronic == (fm.implied_ronic(0.04, rate) if reinvests else None)


@pytest.mark.parametrize("rate", [0.2, 0.0, -0.2, None])
def test_the_notes_codes_params_and_order(rate):
    notes = gordon.reinvestment_notes(rate, "held", "not positive")
    expected = [(gordon.HOLDS, {"reinvestment_rate": rate}, "held")]
    if not gordon.reinvests(rate):
        expected.append((gordon.NOT_POSITIVE, {"reinvestment_rate": rate}, "not positive"))
    assert [(n.code, n.params, n.text) for n in notes] == expected


def test_the_grid_and_the_what_if_say_the_same_about_one_run(company):
    """On a value-driver run, the grid's Gordon contrast and a switch to Gordon on a what-if read
    the same year 5: the same reinvestment rate, exactly (stored outputs are not rounded), and the
    same implied return at the run's own WACC and growth."""
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    sheet = grid(company, parent)
    assert sheet.method.terminal_method == dcf.VALUE_DRIVER
    contrast = sheet.contrast
    switched = revalue(company, parent, [Change("terminal_method", method=dcf.GORDON)])
    by_code = {n.code: n for n in switched.notes}
    grid_notes = {n.code: n for n in sheet.notes}
    assert by_code[gordon.HOLDS].params == grid_notes[gordon.HOLDS].params
    assert by_code[gordon.HOLDS].params == {"reinvestment_rate": contrast.reinvestment_rate}
    assert (gordon.NOT_POSITIVE in by_code) is (gordon.NOT_POSITIVE in grid_notes)
    row, column = sheet.run_point["row"], sheet.run_point["column"]
    cell = contrast.cells[row][column]
    out = load_outputs(company, switched.run_id)
    rows = {(a.name, a.period): a for a in load_assumptions(company, parent)}
    assert cell.terminal_growth == rows[("terminal_growth", SINGLE)].value
    assert cell.implied_ronic is not None
    assert by_code["gordon_implied_ronic"].params["implied_ronic"] == cell.implied_ronic
    assert by_code["gordon_implied_ronic"].params["wacc"] == out[("wacc", SINGLE)]
