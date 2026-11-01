"""0014 adds the extraction prompt to proposal sets' key and keeps every set and its shocks."""

import shutil
import sqlite3

import pytest

from shared_kernel.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)

INSERT_SET = (
    "INSERT INTO proposal_sets (case_id, event_run_id, variant, model, prompt_sha256, "
    "extract_prompt_sha256, run_id, status) VALUES ('C', 'r1', 'named', 'm', 'p', 'x', "
    "'TST_2019-06-30_1', 'ok')"
)


def test_0014_keeps_sets_and_their_shocks_and_marks_the_prompt_unknown(db_path, tmp_path):
    before = tmp_path / "migrations_0013"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 13:
            shutil.copy(path, before / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, before)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000123', 'TST', 'T')")
        conn.execute(
            "INSERT INTO ingest_runs (run_id, cik, companyfacts_sha256, concept_map_sha256, "
            "facts_kept, facts_new) VALUES (1, '0000000123', 'a', 'b', 0, 0)"
        )
        conn.execute(
            "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
            "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
            "VALUES ('TST_2019-06-30_1', '0000000123', 'TST', '2019-06-30', 'c', 1, 'b', 'p', "
            "'i', 'y')"
        )
        conn.execute(
            "INSERT INTO event_runs (event_run_id, cik, as_of, tz, params_json, input_sha256, "
            "code_version) VALUES ('r1', '0000000123', '2019-06-30', 'America/New_York', '{}', "
            "'x', 't')"
        )
        conn.execute(
            "INSERT INTO proposal_sets (set_id, case_id, event_run_id, variant, model, "
            "prompt_sha256, run_id, status, no_impact) VALUES (7, 'C', 'r1', 'named', 'm', 'p', "
            "'TST_2019-06-30_1', 'ok', 0)"
        )
        conn.execute(
            "INSERT INTO shock_proposals (set_id, driver, direction, size, duration, "
            "start_quarter, rationale, evidence_json, sigma, low, base, high, horizon, decay, "
            "status) VALUES (7, 'revenue_growth', 'down', 'small', 'fading', 1, 'r', '[]', 0.01, "
            "-0.02, -0.01, 0, 4, 0.5, 'auto_approved')"
        )
        conn.commit()

    with get_db_connection(db_path) as conn:
        assert apply_migrations(conn) == [14]
        assert current_schema_version(conn) == 14
        row = conn.execute("SELECT * FROM proposal_sets WHERE set_id = 7").fetchone()
        assert row["extract_prompt_sha256"] == "" and row["prompt_sha256"] == "p"
        assert conn.execute("SELECT set_id FROM shock_proposals").fetchone()[0] == 7
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute(INSERT_SET)  # the same set under another extraction prompt is a new row
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(INSERT_SET)
