"""0017 adds the M9 range tables and changes no stored row."""

import shutil

from shared_kernel.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)


def test_0017_adds_tables_and_keeps_stored_rows(db_path, tmp_path):
    before = tmp_path / "migrations_0016"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 16:
            shutil.copy(path, before / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, before)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000123', 'TST', 'T')")
        conn.commit()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert apply_migrations(conn) == [17, 18]
        assert current_schema_version(conn) == 18
        after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - tables == {
            "forecast_origins",
            "baseline_errors",
            "range_builds",
            "range_results",
        }
        assert conn.execute("SELECT ticker FROM companies").fetchone()[0] == "TST"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
