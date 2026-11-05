"""0019 links a what-if run to its parent (backlog #141), and the runner applies a migration that
arrives after a higher one (M10's 0018 lands after 0019)."""

import shutil

from shared_kernel.database import (
    MIGRATIONS_DIR,
    applied_versions,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)


def _dir(tmp_path, name, keep):
    folder = tmp_path / name
    folder.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if keep(int(path.name[:4])):
            shutil.copy(path, folder / path.name)
    return folder


def _insert_run(conn):
    conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000123', 'TST', 'T')")
    conn.execute(
        "INSERT INTO ingest_runs (run_id, cik, companyfacts_sha256, concept_map_sha256, "
        "facts_kept, facts_new) VALUES (1, '0000000123', 'x', 'y', 0, 0)"
    )
    conn.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
        "VALUES ('TST_2020-06-30_1', '0000000123', 'TST', '2020-06-30', 'c', 1, 'a', 'b', 'c', 'd')"
    )
    conn.commit()


def test_0019_adds_a_null_parent_to_stored_runs(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, _dir(tmp_path, "upto17", lambda v: v <= 17))
        _insert_run(conn)
        assert apply_migrations(conn) == [18, 19, 20, 21]
        row = conn.execute("SELECT parent_run_id FROM runs").fetchone()
        assert row["parent_run_id"] is None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_migration_that_arrives_after_a_higher_one_still_applies(db_path, tmp_path):
    # main had 0017 then 0019-0021; M10's 0018 merged later (the real case on stored data)
    main_dir = _dir(tmp_path, "main", lambda v: v != 18)
    with get_db_connection(db_path) as conn:
        assert 18 not in apply_migrations(conn, main_dir)
        assert current_schema_version(conn) == 21  # the highest applied
        assert apply_migrations(conn) == [18]  # the other track's 0018 merges later
        assert {18, 19} <= applied_versions(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_results)")}
        assert "actual_filed_at" in cols
        assert apply_migrations(conn) == []  # nothing applies twice
