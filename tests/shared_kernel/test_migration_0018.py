"""0018 adds eval_results.actual_filed_at (M10) and changes no stored row."""

import shutil

from shared_kernel.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)


def test_0018_adds_the_filing_date_and_keeps_stored_rows(db_path, tmp_path):
    before = tmp_path / "migrations_0017"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 17:
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
            "VALUES ('R', '0000000123', 'TST', '2019-06-30', 'c', 1, 'b', 'p', 'i', 'y')"
        )
        conn.execute(
            "INSERT INTO eval_cases VALUES ('C', 'TST', '0000000123', '2019-06-30', 'guidance', "
            "'d', 4, 's', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO eval_batches (batch_id, code_version, cases_sha256) VALUES ('B', 'c', 's')"
        )
        conn.execute(
            "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
            "horizon, forecast, status) VALUES ('B', 'C', 'R', 'baseline', 'revenue', "
            "'FY2019Q3', 1, 101.5, 'ok')"
        )
        conn.commit()
        before_rows = [tuple(r) for r in conn.execute("SELECT * FROM eval_results")]
        assert apply_migrations(conn) == [18, 19, 20, 21]
        assert current_schema_version(conn) == 21
        after = [tuple(r) for r in conn.execute("SELECT * FROM eval_results")]
        assert [r[:-1] for r in after] == before_rows and after[0][-1] is None
        conn.execute("UPDATE eval_results SET actual_filed_at = '2019-10-30'")
        assert conn.execute("SELECT actual_filed_at FROM eval_results").fetchone()[0] == (
            "2019-10-30"
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
