"""Data snapshots: a saved database and raw files restore exactly, and bad ones are refused."""

import json
from datetime import UTC, datetime

import pytest

from shared_kernel import snapshot
from shared_kernel.database import apply_migrations, current_schema_version, get_db_connection


@pytest.fixture
def data(tmp_path):
    """A migrated database with one row and one raw EDGAR file."""
    data_dir = tmp_path / "data"
    db = data_dir / "warren.db"
    with get_db_connection(db) as conn:
        apply_migrations(conn)
        conn.execute("CREATE TABLE probe (x INTEGER)")
        conn.execute("INSERT INTO probe VALUES (42)")
        conn.commit()
    raw = data_dir / "raw" / "edgar"
    raw.mkdir(parents=True)
    (raw / "CIK0000789019.json").write_text('{"facts": 1}')
    return data_dir


def _save(data, folder, minute=0):
    return snapshot.save(folder, data / "warren.db", data / "raw" / "edgar",
                         now=datetime(2026, 10, 31, 23, minute, tzinfo=UTC))  # fmt: skip


def test_a_snapshot_restores_the_database_and_raw_files(data, tmp_path):
    manifest = json.loads(_save(data, tmp_path / "snap").read_text())
    assert manifest["row_counts"]["probe"] == 1 and manifest["schema_version"] > 0
    fresh = tmp_path / "fresh"
    restored = snapshot.restore(tmp_path / "snap", fresh)
    assert restored["migrations_applied"] == []
    with get_db_connection(fresh / "warren.db") as conn:
        assert conn.execute("SELECT x FROM probe").fetchone()[0] == 42
        assert current_schema_version(conn) == manifest["schema_version"]
    assert (fresh / "raw" / "edgar" / "CIK0000789019.json").read_text() == '{"facts": 1}'


def test_a_corrupt_archive_or_an_empty_folder_is_refused(data, tmp_path):
    with pytest.raises(snapshot.SnapshotError, match="no snapshot"):
        snapshot.restore(tmp_path / "none", tmp_path / "fresh")
    manifest = json.loads(_save(data, tmp_path / "snap").read_text())
    archive = tmp_path / "snap" / manifest["archive"]
    archive.write_bytes(archive.read_bytes()[:-10])
    with pytest.raises(snapshot.SnapshotError, match="SHA-256"):
        snapshot.restore(tmp_path / "snap", tmp_path / "fresh")


def test_restore_never_overwrites_a_database_without_force(data, tmp_path):
    _save(data, tmp_path / "snap")
    with pytest.raises(snapshot.SnapshotError, match="--force"):
        snapshot.restore(tmp_path / "snap", data)
    assert snapshot.restore(tmp_path / "snap", data, force=True)["row_counts"]["probe"] == 1


def test_only_the_newest_two_are_kept_and_the_newest_is_restored(data, tmp_path):
    folder = tmp_path / "snap"
    for minute in (1, 2, 3):
        with get_db_connection(data / "warren.db") as conn:
            conn.execute("INSERT INTO probe VALUES (?)", (minute,))
            conn.commit()
        _save(data, folder, minute)
    assert len(snapshot.manifests(folder)) == 2 and len(list(folder.glob("*.tar.gz"))) == 2
    assert snapshot.restore(folder, tmp_path / "fresh")["row_counts"]["probe"] == 4


def test_the_pipelines_telemetry_is_kept(data, tmp_path):
    # M7: a report points to its pipeline's telemetry file, so a restored machine has it
    (data / "telemetry").mkdir()
    line = '{"pipeline_id": "TST_2020-06-30_p1", "node": "simulate", "status": "ok"}\n'
    (data / "telemetry" / "TST_2020-06-30_p1.jsonl").write_text(line)
    _save(data, tmp_path / "snap")
    fresh = tmp_path / "fresh"
    snapshot.restore(tmp_path / "snap", fresh)
    assert (fresh / "telemetry" / "TST_2020-06-30_p1.jsonl").read_text() == line
