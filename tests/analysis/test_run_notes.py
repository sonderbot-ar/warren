"""A run's warnings stored as codes with parameters (backlog #172): `run_notes`, the backfill
for runs stored before them, the what-if's `run_warning` and the `notes` command."""

import json
from contextlib import contextmanager

import pytest

from domains.analysis import __main__ as cli
from domains.analysis import dcf
from domains.analysis.coded import RUN_NOTE_CODES, Coded
from domains.analysis.math_engine import UserChoice, build_inputs, post_check_notes
from domains.analysis.runs import (
    backfill_notes,
    load_assumptions,
    reproduce,
    run_baseline,
    run_notes,
    save_run,
    valuation_notes,
)
from domains.analysis.whatif import Change, revalue
from tests.analysis.conftest import AS_OF, CHOICES


def _baseline(conn):
    return run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _stored_text(conn, run_id):
    return conn.execute("SELECT notes FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]


def _forget(conn, run_id):
    """Make `run_id` look stored before 0021."""
    conn.execute("DELETE FROM run_notes WHERE run_id = ?", (run_id,))
    conn.commit()


def test_a_baseline_stores_its_codes_and_the_same_text(company):
    run_id = _baseline(company)
    notes = run_notes(company, run_id)
    assert notes.recorded and notes.notes
    assert "\n".join(n.text for n in notes.notes) == _stored_text(company, run_id)
    built = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    assert notes.notes[: len(built.notes)] == built.notes  # build warnings first, params kept
    assert {n.code for n in notes.notes} <= RUN_NOTE_CODES - {"note_text"}
    assert reproduce(company, run_id).ok


def test_params_round_trip_through_json(company):
    result = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    notes = [
        Coded(
            "margin_outside_history", {"period": "FY2020Q2", "margin": 0.3, "n_quarters": 7}, "a"
        ),
        Coded(
            "balance_carried_forward", {"items": [{"item": "x", "period_end": "2019-12-31"}]}, "b"
        ),
        "plain text from an older caller",
    ]
    run_id = save_run(company, result, dcf.run_outputs(result.assumptions), notes)
    got = run_notes(company, run_id)
    assert got.notes[:2] == notes[:2]
    assert got.notes[2] == Coded("note_text", {}, "plain text from an older caller")
    assert _stored_text(company, run_id) == "a\nb\nplain text from an older caller"
    assert json.loads(json.dumps(got.to_dict()))["notes"][0]["params"]["margin"] == 0.3


def test_an_unknown_code_or_a_line_break_is_refused_and_nothing_stored(company):
    result = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    outputs = dcf.run_outputs(result.assumptions)
    count = company.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    for bad in (Coded("made_up", {}, "x"), Coded("note_text", {}, "two\nlines")):
        with pytest.raises(ValueError):
            save_run(company, result, outputs, [bad])
    assert company.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == count


def test_a_run_stored_before_the_codes_answers_its_lines_as_text(company):
    run_id = _baseline(company)
    lines = _stored_text(company, run_id).split("\n")
    _forget(company, run_id)
    got = run_notes(company, run_id)
    assert not got.recorded
    assert got.notes == [Coded("note_text", {}, line) for line in lines]
    with pytest.raises(ValueError):
        run_notes(company, "nope")


def test_a_missing_bound_is_coded_with_its_bound_and_reason(company):
    rows = [a for a in load_assumptions(company, _baseline(company)) if a.name != "terminal_method"]
    erp, se = (next(a.value for a in rows if a.name == n) for n in ("erp", "erp_std_error"))
    low_wacc = dcf.value(dcf.with_value(rows, "erp", erp - se)).wacc
    shifted = dcf.with_value(rows, "terminal_growth", low_wacc)
    outputs, gaps = dcf.outputs_and_gaps(shifted)
    notes = valuation_notes(shifted, outputs, gaps)
    (missing,) = [n for n in notes if n.code == "no_value_per_share"]
    assert missing.params == {"bound": "erp_minus_1se", "reason": "growth_not_below_rate"}
    assert missing.text == "No value per share at erp minus 1se: WACC ≤ terminal growth"
    assert notes[: len(notes) - 1] == post_check_notes(shifted, outputs)


def test_the_backfill_gives_an_older_run_the_same_codes_back(company):
    run_id = _baseline(company)
    before = run_notes(company, run_id)
    _forget(company, run_id)
    assert backfill_notes(company, run_id, today=AS_OF) == ("filled", "")
    assert run_notes(company, run_id) == before
    assert backfill_notes(company, run_id) == ("already_recorded", "")


def test_the_backfill_leaves_a_run_whose_text_differs(company):
    run_id = _baseline(company)
    _forget(company, run_id)
    company.execute(
        "UPDATE runs SET notes = notes || char(10) || 'written by older code' WHERE run_id = ?",
        (run_id,),
    )
    company.commit()
    status, detail = backfill_notes(company, run_id, today=AS_OF)
    assert status == "text_differs" and detail
    assert not run_notes(company, run_id).recorded


def test_the_backfill_codes_a_what_if_from_its_rows(company):
    parent = _baseline(company)
    child = revalue(company, parent, [Change("terminal_growth", value=0.07)]).run_id
    before = run_notes(company, child)
    _forget(company, child)
    status, _ = backfill_notes(company, child)
    assert status in ("filled", "no_notes")
    assert run_notes(company, child) == before


def test_the_what_if_warning_carries_the_code_and_params(company):
    gordon = CHOICES | {
        "terminal_method": UserChoice("terminal_method", dcf.GORDON, "t", "2026-10-26", "")
    }
    parent = run_baseline(company, "TST", AS_OF, choices=gordon, today=AS_OF)
    wacc = dcf.run_outputs(load_assumptions(company, parent))[("wacc", "-")]
    for reused in (False, True):  # the second answer is the stored child: same codes
        result = revalue(company, parent, [Change("terminal_growth", value=wacc - 0.02)])
        assert result.reused is reused
        warnings = [n for n in result.notes if n.code == "run_warning"]
        stored = run_notes(company, result.run_id).notes
        assert "thin_terminal_spread" in [w.params["warning_code"] for w in warnings]
        assert [w.params["warning_code"] for w in warnings] == [n.code for n in stored]
        assert [w.params["warning_params"] for w in warnings] == [n.params for n in stored]
        assert [w.text for w in warnings] == [n.text for n in stored]
        assert all(set(w.params) == {"new", "warning_code", "warning_params"} for w in warnings)


def test_the_notes_command(company, monkeypatch, capsys):
    run_id = _baseline(company)

    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    assert cli.main(["notes", "--run-id", run_id, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"] == run_id and out["recorded"] is True
    assert {"code", "params", "text", "group"} == set(out["notes"][0])
    assert cli.main(["notes", "--run-id", run_id]) == 0
    assert "[balance_counted_zero]" in capsys.readouterr().out
    _forget(company, run_id)
    assert cli.main(["notes", "--backfill", "--all"]) == 0
    assert "filled 1" in capsys.readouterr().out
    assert cli.main(["notes", "--backfill"]) == 2
    assert cli.main(["notes", "--run-id", "nope"]) == 1


# -- backlog #196: a stored coverage note gets its reason and successor on read --------------

XOM_FIELDS = {
    "ticker": "XOM",
    "cik": "0000034088",
    "as_of": "2026-09-30",
    "history_ends": "2026-08-03",
    "note": "the universe file's English note",
}


def _store_coverage_note(conn, params):
    result = build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    note = Coded("beyond_history", params, "XOM is beyond its history")
    run_id = save_run(conn, result, dcf.run_outputs(result.assumptions), [note])
    return run_id


def _stored_params(conn, run_id):
    row = conn.execute("SELECT params FROM run_notes WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row[0])


def test_a_coverage_note_stored_before_196_gets_its_fields_on_read(company):
    run_id = _store_coverage_note(company, XOM_FIELDS)
    (note,) = run_notes(company, run_id).notes
    assert note.params == {
        **XOM_FIELDS,
        "reason": "holding_company_reorganisation",
        "successor_cik": "0002115436",
        "successor_name": "ExxonMobil Holdings Corp",
        "filled_on_read": True,
    }
    assert note.text == "XOM is beyond its history"
    assert _stored_params(company, run_id) == XOM_FIELDS  # the stored row is unchanged


def test_a_coverage_note_with_its_fields_is_returned_as_stored(company):
    params = {
        **XOM_FIELDS,
        "reason": "holding_company_reorganisation",
        "successor_cik": "0002115436",
        "successor_name": "ExxonMobil Holdings Corp",
    }
    run_id = _store_coverage_note(company, params)
    assert run_notes(company, run_id).notes[0].params == params


@pytest.mark.parametrize(
    "change",
    [{"cik": "0000000123"}, {"history_ends": "2026-07-01"}, {"cik": None}],
    ids=["unknown cik", "cut-off since corrected", "no cik"],
)
def test_a_coverage_note_matching_no_row_gets_nulls(company, change):
    run_id = _store_coverage_note(company, {**XOM_FIELDS, **change})
    params = run_notes(company, run_id).notes[0].params
    assert (params["reason"], params["successor_cik"], params["successor_name"]) == (
        None,
        None,
        None,
    )
    assert params["filled_on_read"] is True


def test_each_note_carries_its_group_and_free_text_none(company):
    """Backlog #197: the group a screen sorts a note under, from `text.WARNING_LESSONS`."""
    from domains.analysis.text import WARNING_LESSONS

    run_id = _baseline(company)
    notes = run_notes(company, run_id).to_dict()["notes"]
    assert notes and all(n["group"] == WARNING_LESSONS[n["code"]].group for n in notes)
    assert {"code": "balance_counted_zero", "group": "data"}.items() <= next(
        n for n in notes if n["code"] == "balance_counted_zero"
    ).items()
    _forget(company, run_id)
    stored_as_text = run_notes(company, run_id).to_dict()["notes"]
    assert stored_as_text and all(
        n["code"] == "note_text" and n["group"] is None for n in stored_as_text
    )


def test_the_notes_command_names_the_group(company, monkeypatch, capsys):
    run_id = _baseline(company)

    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    assert cli.main(["notes", "--run-id", run_id]) == 0
    assert "- [The figures the run reads] [balance_counted_zero]" in capsys.readouterr().out
    _forget(company, run_id)
    assert cli.main(["notes", "--run-id", run_id]) == 0
    assert "- [Not coded] [note_text]" in capsys.readouterr().out
