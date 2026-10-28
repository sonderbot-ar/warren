import sqlite3

import pytest

from domains.analysis import runs
from domains.analysis.math_engine import build_inputs
from domains.analysis.runs import load_assumptions, load_outputs, rebuild, reproduce, run_baseline
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
