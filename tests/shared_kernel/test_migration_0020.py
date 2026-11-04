"""0020 adds a structured source for each assumption row (backlog #175); stored runs keep their
rows and simply have no sources."""

import sqlite3

import pytest

from shared_kernel.database import apply_migrations, get_db_connection
from tests.shared_kernel.test_migration_0019 import _dir, _insert_run


def test_0020_adds_the_table_and_keeps_stored_runs(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, _dir(tmp_path, "upto19", lambda v: v <= 19))
        _insert_run(conn)
        conn.execute(
            "INSERT INTO assumptions (run_id, name, period, value, source, method) "
            "VALUES ('TST_2020-06-30_1', 'beta', '-', 1.1, 'computed', 'm')"
        )
        conn.commit()
        assert apply_migrations(conn) == [20]
        assert conn.execute("SELECT COUNT(*) FROM assumptions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assumption_sources").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        def put(name, kind, detail="{}", position=0):
            conn.execute(
                "INSERT INTO assumption_sources (run_id, name, period, position, kind, detail) "
                "VALUES ('TST_2020-06-30_1', ?, '-', ?, ?, ?)",
                (name, position, kind, detail),
            )

        put("beta", "market")
        put("beta", "what_if", position=1)  # all six kinds are allowed
        for bad in (
            lambda: put("beta", "guess", position=2),  # unknown kind
            lambda: put("beta", "market", detail="not json", position=3),
            lambda: put("beta", "market", position=-1),
            lambda: put("erp", "market"),  # no such row
            lambda: put("beta", "market", position=0),  # same place twice
        ):
            with pytest.raises(sqlite3.IntegrityError):
                bad()
        conn.execute("DELETE FROM assumptions WHERE name = 'beta'")
        assert conn.execute("SELECT COUNT(*) FROM assumption_sources").fetchone()[0] == 0
