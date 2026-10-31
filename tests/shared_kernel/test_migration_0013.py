"""0013 adds run_output_gaps to a database that already holds runs, and keeps every row."""

import shutil

from domains.analysis.runs import load_gaps, load_outputs
from shared_kernel.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)


def test_0013_upgrades_a_database_holding_a_run(db_path, tmp_path):
    before = tmp_path / "migrations_0012"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 12:
            shutil.copy(path, before / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, before)
        assert current_schema_version(conn) == 12
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
            "INSERT INTO run_outputs VALUES ('TST_2019-06-30_1', 'value_per_share', '-', 12.34)"
        )
        conn.commit()

    with get_db_connection(db_path) as conn:
        assert 13 in apply_migrations(conn)
        assert load_outputs(conn, "TST_2019-06-30_1") == {("value_per_share", "-"): 12.34}
        assert load_gaps(conn, "TST_2019-06-30_1") == {}  # stored before 0013: no reasons
        columns = [r[1] for r in conn.execute("PRAGMA table_info(run_output_gaps)")]
        assert columns == ["run_id", "name", "period", "reason", "detail"]
