import sqlite3

import pytest

from domains.analysis.runs import load_outputs, reproduce, run_baseline
from tests.analysis.conftest import AS_OF, CHOICES


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
