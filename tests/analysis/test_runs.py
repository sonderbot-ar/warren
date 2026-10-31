import sqlite3

import pytest

from domains.analysis import math_engine, runs
from domains.analysis.math_engine import (
    EngineError,
    UserChoice,
    build_inputs,
    load_user_assumptions,
)
from domains.analysis.runs import (
    load_assumptions,
    load_outputs,
    rebuild,
    reproduce,
    run_baseline,
    stored_choices,
)
from domains.analysis.schemas import Assumption
from domains.market.prices import load_prices
from tests.analysis.conftest import AS_OF, CHOICES, FETCHED, market_rows


def run(conn):
    return run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def test_a_run_reproduces_to_the_cent(company):
    run_id = run(company)
    assert run_id == "TST_2020-06-30_1"
    result = reproduce(company, run_id)
    assert result.ok and result.outputs_checked == len(load_outputs(company, run_id))
    assert run(company) == "TST_2020-06-30_2"


def test_the_run_records_its_data_snapshot(company):
    run_id = run(company)
    row = company.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["ingest_run_id"] == 1
    for column in ("concept_map_sha256", "price_fetch_sha256", "index_fetch_sha256"):
        assert len(row[column]) == 64
    assert row["code_version"]
    assert "Counted as zero" in row["notes"]


def test_editing_an_assumption_row_is_caught(company):
    run_id = run(company)
    company.execute(
        "UPDATE assumptions SET value = value + 0.01 WHERE run_id = ? AND name = 'erp'", (run_id,)
    )
    result = reproduce(company, run_id)
    assert not result.ok
    assert ("value_per_share", "-") in {(m[0], m[1]) for m in result.mismatches}


def test_assumption_source_must_be_one_of_three(company):
    run_id = run(company)
    with pytest.raises(sqlite3.IntegrityError):
        company.execute("INSERT INTO assumptions VALUES (?, 'x', '-', 1, 'guess', 'm')", (run_id,))


def test_building_twice_gives_identical_rows(company):
    first = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    second = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    assert first.assumptions == second.assumptions
    assert first.snapshot == second.snapshot


def test_a_run_rebuilds_from_the_downloads_it_used_after_a_refresh(company):
    run_id = run(company)
    assert rebuild(company, run_id, choices=CHOICES, today=AS_OF).ok
    # a revised download of TST: every price 2% higher, so the market value of equity changes
    _, stock = market_rows()
    revised = [{**r, "close": r["close"] * 1.02, "adj_close": r["adj_close"] * 1.02} for r in stock]
    load_prices(company, "TST", refresh=True, download=lambda t, s: revised, now=lambda: FETCHED)
    fresh = run(company)
    changed = {
        a.name
        for a, b in zip(
            load_assumptions(company, run_id), load_assumptions(company, fresh), strict=True
        )
        if a.value != b.value
    }
    assert "price" in changed and "equity_market_value" in changed
    result = rebuild(company, run_id, choices=CHOICES, today=AS_OF)
    assert result.ok and result.rows_checked == len(load_assumptions(company, run_id))
    assert rebuild(company, fresh, choices=CHOICES, today=AS_OF).ok


def test_rebuild_reports_a_changed_row(company):
    run_id = run(company)
    company.execute(
        "UPDATE assumptions SET value = value * 2 WHERE run_id = ? AND name = 'beta'", (run_id,)
    )
    result = rebuild(company, run_id, choices=CHOICES, today=AS_OF)
    assert result.mismatches == [("beta", "-", "value")] and not result.values_ok
    company.execute(
        "UPDATE assumptions SET value = value / 2, method = 'older wording' "
        "WHERE run_id = ? AND name = 'beta'",
        (run_id,),
    )
    result = rebuild(company, run_id, choices=CHOICES, today=AS_OF)
    assert result.mismatches == [("beta", "-", "method")] and result.values_ok


def test_rebuild_refuses_a_changed_concept_map(company, monkeypatch):
    run_id = run(company)
    monkeypatch.setattr(runs, "concept_map_sha256", lambda: "f" * 64)
    with pytest.raises(ValueError, match="concept_map.csv changed"):
        rebuild(company, run_id, choices=CHOICES, today=AS_OF)


def test_a_run_made_before_terminal_method_rebuilds_under_its_own_rule(company):
    run_id = run(company)
    company.execute(
        "DELETE FROM assumptions WHERE run_id = ? AND name = 'terminal_method'", (run_id,)
    )
    assert rebuild(company, run_id, choices=CHOICES, today=AS_OF).values_ok


def test_a_run_made_before_terminal_method_rebuilds_from_its_own_rows(company):
    run_id = run(company)
    company.execute(
        "DELETE FROM assumptions WHERE run_id = ? AND name = 'terminal_method'", (run_id,)
    )
    assert "terminal_method" not in stored_choices(load_assumptions(company, run_id))
    assert rebuild(company, run_id, today=AS_OF).values_ok


@pytest.mark.parametrize(
    "choice",
    [
        *load_user_assumptions().values(),  # the checked-in file
        *CHOICES.values(),  # an empty note
        UserChoice("erp_first_year", "1990", "owner (x)", "2026-11-02", "a: b. set on 2026-01-01."),
        UserChoice("erp_method", "historical_geometric", "o", "2026-11-02", "line one.\nline two"),
    ],
)
def test_a_stored_choice_reads_back_exactly(choice):
    assert UserChoice.from_assumption(choice.as_assumption()) == choice


@pytest.mark.parametrize(
    "row",
    [
        ("erp", 0.05, "computed", "1990: set by o on 2026-11-02. note"),
        ("erp_method", None, "user", "historical_geometric, set by hand"),
        ("erp_method", None, "user", "x: set by o on 2nd November. note"),
    ],
)
def test_a_row_that_is_not_a_stored_choice_is_refused(row):
    name, value, source, method = row
    row = Assumption(name=name, period="-", value=value, source=source, method=method)
    with pytest.raises(EngineError, match="not a stored choice"):
        UserChoice.from_assumption(row)


def test_a_numeric_choice_reads_back_from_its_text_not_its_value_column():
    row = CHOICES["erp_first_year"].as_assumption()
    assert row.value == 1989.0 and UserChoice.from_assumption(row).value == "1989"


def test_a_run_missing_a_choice_it_always_had_is_refused(company):
    run_id = run(company)
    company.execute("DELETE FROM assumptions WHERE run_id = ? AND name = 'erp_method'", (run_id,))
    with pytest.raises(EngineError, match="no choice for \\['erp_method'\\]"):
        rebuild(company, run_id, today=AS_OF)


def test_a_run_reads_back_the_choices_it_was_made_with(company):
    run_id = run(company)
    assert stored_choices(load_assumptions(company, run_id)) == CHOICES


def test_a_stored_choice_the_code_no_longer_supports_is_refused(company):
    run_id = run(company)
    company.execute(
        "UPDATE assumptions SET method = replace(method, 'historical_geometric', 'arithmetic') "
        "WHERE run_id = ? AND name = 'erp_method'",
        (run_id,),
    )
    with pytest.raises(EngineError, match="erp_method 'arithmetic' is no longer supported"):
        rebuild(company, run_id, today=AS_OF)


def test_editing_the_choices_file_after_a_run_does_not_change_its_rebuild(
    company, tmp_path, monkeypatch
):
    run_id = run(company)
    edited = {
        name: UserChoice(name, c.value, "owner", "2026-11-02", "edited later")
        for name, c in CHOICES.items()
    }
    edited["erp_first_year"] = UserChoice("erp_first_year", "1999", "owner", "2026-11-02", "")
    path = tmp_path / "user_assumptions.csv"
    path.write_text(
        "name,value,set_by,set_on,note\n"
        + "".join(f"{c.name},{c.value},{c.set_by},{c.set_on},{c.note}\n" for c in edited.values())
    )
    assert load_user_assumptions(path) == edited  # what a run made today would use
    monkeypatch.setattr(math_engine, "load_user_assumptions", lambda: edited)
    assert rebuild(company, run_id, today=AS_OF).ok  # the run's own choices, not the file's
    what_if = rebuild(company, run_id, choices=edited, today=AS_OF)  # explicitly different
    assert {name for name, _period, _what in what_if.mismatches} >= {"erp_first_year", "erp"}


# -- why an output has no value (backlog #9) ---------------------------------------------------

MINUS = ("value_per_share_erp_minus_1se", "-")


def _store_gap(conn, run_id, reason="growth_not_below_rate"):
    conn.execute("DELETE FROM run_outputs WHERE run_id = ? AND name = ?", (run_id, MINUS[0]))
    conn.execute(
        "INSERT INTO run_output_gaps (run_id, name, period, reason, detail) VALUES (?, ?, ?, ?, ?)",
        (run_id, *MINUS, reason, "terminal growth (0.04) must be below the discount rate (0.04)"),
    )


def test_a_run_with_values_stores_no_gap(company):
    run_id = run(company)
    assert runs.load_gaps(company, run_id) == {}
    assert reproduce(company, run_id).gap_mismatches == []


def test_save_run_stores_each_gap_and_its_note(company, monkeypatch):
    real = runs.dcf.outputs_and_gaps

    def with_gap(rows):
        out, _gaps = real(rows)
        out.pop(MINUS)
        return out, {MINUS: runs.dcf.Gap("rate_not_positive", "discount rate must be positive")}

    monkeypatch.setattr(runs.dcf, "outputs_and_gaps", with_gap)
    run_id = run(company)
    assert runs.load_gaps(company, run_id)[MINUS].reason == "rate_not_positive"
    notes = company.execute("SELECT notes FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert "No value per share at erp minus 1se: WACC ≤ 0" in notes
    assert "terminal growth" not in notes


def test_an_unknown_reason_is_refused_on_write_and_on_read(company):
    run_id = run(company)
    result = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    with pytest.raises(ValueError, match="unknown reason"):
        runs.save_run(company, result, {}, [], {MINUS: runs.dcf.Gap("made_up", "x")})
    _store_gap(company, run_id, reason="made_up")
    with pytest.raises(ValueError, match="unknown reason"):
        runs.load_gaps(company, run_id)


def test_reproduce_flags_a_stored_gap_the_code_no_longer_finds(company):
    # the run has a value at ERP − 1 SE; a stored gap saying otherwise is a mismatch
    run_id = run(company)
    _store_gap(company, run_id)
    result = reproduce(company, run_id)
    assert not result.ok
    assert result.gap_mismatches == [(*MINUS, "growth_not_below_rate", None)]
