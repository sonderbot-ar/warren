import sqlite3

import pytest

from shared_kernel.database import (
    apply_migrations,
    current_schema_version,
    get_db_connection,
    list_migrations,
)


def test_connection_uses_wal_and_foreign_keys(db_path):
    with get_db_connection(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1


def test_wal_mode_persists_in_the_file(db_path):
    with get_db_connection(db_path):
        pass
    raw = sqlite3.connect(db_path)  # plain connection, no PRAGMAs set
    try:
        assert raw.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
    finally:
        raw.close()


def test_migrations_apply_cleanly_to_empty_database(db_path):
    expected = [version for version, _ in list_migrations()]
    with get_db_connection(db_path) as conn:
        assert current_schema_version(conn) == 0
        assert apply_migrations(conn) == expected
        assert current_schema_version(conn) == expected[-1]


def test_migrations_are_idempotent(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        assert apply_migrations(conn) == []
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == len(list_migrations())


def test_failing_migration_rolls_back_and_keeps_earlier_ones(db_path, tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL);"
    )
    (migrations / "0002_broken.sql").write_text(
        "CREATE TABLE half_done (id INTEGER);\nTHIS IS NOT SQL;"
    )
    with get_db_connection(db_path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(conn, migrations)
        assert current_schema_version(conn) == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "half_done" not in tables


def test_badly_named_migration_is_rejected(tmp_path):
    (tmp_path / "init.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError):
        list_migrations(tmp_path)


def _parent_child(migrations):
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
        "CREATE TABLE parent (id INTEGER PRIMARY KEY, kind TEXT CHECK (kind IN ('a')));\n"
        "CREATE TABLE child (parent_id INTEGER REFERENCES parent (id));\n"
    )


def test_a_foreign_keys_off_migration_rebuilds_a_referenced_table(db_path, tmp_path):
    migrations = tmp_path / "migrations"
    _parent_child(migrations)
    (migrations / "0002_rebuild.sql").write_text(
        "-- foreign_keys: off\n"
        "CREATE TABLE parent_new (id INTEGER PRIMARY KEY, kind TEXT CHECK (kind IN ('a', 'b')));\n"
        "INSERT INTO parent_new SELECT * FROM parent;\n"
        "DROP TABLE parent;\nALTER TABLE parent_new RENAME TO parent;\n"
    )
    (migrations / "0002_rebuild.sql").rename(tmp_path / "0002_rebuild.sql")  # held back
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, migrations)
        conn.execute("INSERT INTO parent VALUES (1, 'a')")
        conn.execute("INSERT INTO child VALUES (1)")
        conn.commit()
        (tmp_path / "0002_rebuild.sql").rename(migrations / "0002_rebuild.sql")
        assert apply_migrations(conn, migrations) == [2]
        conn.execute("INSERT INTO parent VALUES (2, 'b')")
        assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1


def test_a_foreign_keys_off_migration_that_breaks_a_key_rolls_back(db_path, tmp_path):
    migrations = tmp_path / "migrations"
    _parent_child(migrations)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, migrations)
        conn.execute("INSERT INTO parent VALUES (1, 'a')")
        conn.execute("INSERT INTO child VALUES (1)")
        conn.commit()
        (migrations / "0002_lossy.sql").write_text("-- foreign_keys: off\nDELETE FROM parent;\n")
        with pytest.raises(sqlite3.IntegrityError, match="0002_lossy.sql"):
            apply_migrations(conn, migrations)
        assert current_schema_version(conn) == 1
        assert conn.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
