"""Backlog #172: the post-checks as codes with raw parameters; their texts are the sentences
stored in `runs.notes` before, unchanged."""

import pytest

from domains.analysis import dcf
from domains.analysis.coded import RUN_NOTE_CODES
from domains.analysis.math_engine import (
    MARGIN_SIGMAS,
    TERMINAL_SPREAD_WARNING,
    post_check_notes,
    post_checks,
)
from tests.analysis.test_math_engine import at_bound, build, gordon_rows, wobbled


def codes(notes, code):
    return [n for n in notes if n.code == code]


def test_margin_outside_history_carries_its_numbers(company):
    rows = wobbled(build(company).assumptions)
    period = sorted(a.period for a in rows if a.name == "operating_margin")[0]
    shocked = [
        a.model_copy(update={"value": 0.30})
        if (a.name, a.period) == ("operating_margin", period)
        else a
        for a in rows
    ]
    notes = post_check_notes(shocked, dcf.run_outputs(shocked))
    (note,) = codes(notes, "margin_outside_history")
    p = note.params
    assert p["period"] == period and p["margin"] == pytest.approx(0.30)
    assert p["mean"] == pytest.approx(0.20, abs=0.002) and 0 < p["sd"] < 0.02
    assert p["sigmas"] == MARGIN_SIGMAS and p["n_quarters"] > 1
    assert note.text == (
        f"Operating margin {0.30:.1%} in {period} is outside the historical range "
        f"({p['mean']:.1%} ± {MARGIN_SIGMAS} × {p['sd']:.1%}, {p['n_quarters']} quarters)"
    )


def test_thin_spread_carries_wacc_growth_and_a_fraction_threshold(company):
    rows = gordon_rows(company)
    wacc = dcf.run_outputs(rows)[("wacc", "-")]
    shifted = dcf.with_value(rows, "terminal_growth", wacc - 0.029)
    outputs = dcf.run_outputs(shifted)
    (note,) = codes(post_check_notes(shifted, outputs), "thin_terminal_spread")
    p = note.params
    assert p["threshold"] == TERMINAL_SPREAD_WARNING == 0.03  # a fraction, not 3 points
    assert p["spread"] == pytest.approx(0.029)
    assert p["wacc"] == pytest.approx(wacc) and p["terminal_growth"] == pytest.approx(wacc - 0.029)
    assert p["wacc"] - p["terminal_growth"] == pytest.approx(p["spread"])
    assert p["terminal_share"] == outputs[("terminal_share", "-")]
    assert "2.90 points" in note.text and f"{p['terminal_share']:.0%}" in note.text


def test_thin_spread_at_each_bound_names_the_bound(company):
    rows = gordon_rows(company)
    shifted = dcf.with_value(rows, "terminal_growth", at_bound(rows, 1).wacc - 0.02)
    notes = codes(
        post_check_notes(shifted, dcf.run_outputs(shifted)), "thin_terminal_spread_at_erp_bound"
    )
    by_bound = {n.params["bound"]: n for n in notes}
    assert set(by_bound) == {"erp_minus_1se", "erp_plus_1se"}
    for bound, sign, word in (("erp_minus_1se", -1, "lower"), ("erp_plus_1se", 1, "higher")):
        p, shifted_value = by_bound[bound].params, at_bound(shifted, sign)
        assert p["wacc"] == pytest.approx(shifted_value.wacc)
        assert p["terminal_share"] == pytest.approx(shifted_value.dcf.terminal_share)
        assert p["spread"] == pytest.approx(p["wacc"] - p["terminal_growth"])
        assert p["threshold"] == TERMINAL_SPREAD_WARNING
        assert f"{word} ERP" in by_bound[bound].text
    assert by_bound["erp_plus_1se"].params["spread"] == pytest.approx(0.02)


def test_post_checks_are_the_texts_of_the_codes_in_order(company):
    rows = gordon_rows(company)
    for spread in (0.05, 0.029, 0.01, 0.002):
        shifted = dcf.with_value(rows, "terminal_growth", at_bound(rows, -1).wacc - spread)
        outputs, _gaps = dcf.outputs_and_gaps(shifted)
        notes = post_check_notes(shifted, outputs)
        assert post_checks(shifted, outputs) == [n.text for n in notes]
        assert {n.code for n in notes} <= RUN_NOTE_CODES
