"""The app reads the engine's database but never migrates it (F2 design, Engine needs)."""

import json

import pytest

from shared_kernel.database import apply_migrations, get_db_connection, list_migrations
from webapp.database import SchemaMismatch, require_current_schema, schema_status


def _migrated(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)


def test_a_current_database_passes(db_path):
    _migrated(db_path)
    require_current_schema(db_path)


def test_no_database_refuses_to_start_and_names_the_restore(db_path):
    with pytest.raises(SchemaMismatch, match="snapshot restore"):
        require_current_schema(db_path)
    assert not db_path.exists()  # the check created nothing


def test_a_missing_migration_refuses_to_start_and_the_app_does_not_apply_it(db_path):
    _migrated(db_path)
    last = list_migrations()[-1][0]
    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM schema_version WHERE version = ?", (last,))
        conn.commit()
    with pytest.raises(SchemaMismatch, match=str(last)):
        require_current_schema(db_path)
    with get_db_connection(db_path) as conn:
        assert schema_status(conn).missing == [last]  # still missing: nothing was applied


def test_a_migration_this_code_does_not_know_refuses_to_start(db_path):
    _migrated(db_path)
    with get_db_connection(db_path) as conn:
        conn.execute("INSERT INTO schema_version (version, name) VALUES (9999, '9999_future')")
        conn.commit()
    with pytest.raises(SchemaMismatch, match="git pull"):
        require_current_schema(db_path)


def test_the_health_check_reports_the_schema(client, db_path):
    assert client.get("/salud").status_code == 503  # no database yet
    _migrated(db_path)
    response = client.get("/salud")
    assert response.status_code == 200
    assert json.loads(response.text)["status"] == "ok"


def test_page_views_never_touch_the_database(client, db_path):
    client.get("/?corte=2026-11-03")
    client.get("/componentes?corte=2026-11-03&panel=ejemplo")
    assert not db_path.exists()


def test_main_refuses_to_start_on_a_stale_database(db_path, capsys):
    from webapp.__main__ import main

    assert main(["--db", str(db_path)]) == 1
    assert "snapshot restore" in capsys.readouterr().err
