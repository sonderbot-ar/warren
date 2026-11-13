"""0021 adds a run's warnings as codes (backlog #172); stored runs keep their text notes and
simply have no codes until the backfill."""

import sqlite3

import pytest

from shared_kernel.database import apply_migrations, get_db_connection
from tests.shared_kernel.test_migration_0019 import _dir, _insert_run


def test_0021_adds_the_table_and_keeps_stored_runs(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, _dir(tmp_path, "upto20", lambda v: v <= 20))
        _insert_run(conn)
        conn.execute("UPDATE runs SET notes = 'an older warning'")
        conn.commit()
        assert apply_migrations(conn) == [21, 22, 23]
        assert conn.execute("SELECT notes FROM runs").fetchone()[0] == "an older warning"
        assert conn.execute("SELECT COUNT(*) FROM run_notes").fetchone()[0] == 0

        def put(position=0, code="note_text", params="{}", run_id="TST_2020-06-30_1"):
            conn.execute(
                "INSERT INTO run_notes (run_id, position, code, params, text) "
                "VALUES (?, ?, ?, ?, 'an older warning')",
                (run_id, position, code, params),
            )

        put()
        put(position=1, code="fundamentals_stale", params='{"days": 200}')
        for bad in (
            lambda: put(position=0),  # same place twice
            lambda: put(position=-1),
            lambda: put(position=2, code=""),
            lambda: put(position=3, params="not json"),
            lambda: put(position=4, params="[1, 2]"),  # params are an object
            lambda: put(run_id="no such run"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                bad()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("DELETE FROM runs")
        assert conn.execute("SELECT COUNT(*) FROM run_notes").fetchone()[0] == 0
