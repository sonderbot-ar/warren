"""0023 adds the reading rules' version to runs (backlog #365); stored runs keep NULL."""

from shared_kernel.database import apply_migrations, get_db_connection
from tests.shared_kernel.test_migration_0019 import _dir, _insert_run


def test_0023_leaves_stored_runs_without_a_version(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, _dir(tmp_path, "upto22", lambda v: v <= 22))
        _insert_run(conn)
        assert apply_migrations(conn) == [23]
        row = conn.execute("SELECT * FROM runs").fetchone()
        assert row["reading_rules_version"] is None and row["code_version"] == "c"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
