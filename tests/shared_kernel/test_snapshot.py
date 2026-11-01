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


ODD_NAMES = ["../outside.tar.gz", "/etc/passwd", "warren-20261031T230000Z.tar",
             "warren-20261031T225900Z.tar.gz", "sub/warren-20261031T230000Z.tar.gz"]  # fmt: skip


@pytest.mark.parametrize("name", ODD_NAMES)
def test_restore_refuses_a_manifest_that_names_another_archive(data, tmp_path, name):
    path = _save(data, tmp_path / "snap")
    manifest = json.loads(path.read_text())
    manifest["archive"] = name
    path.write_text(json.dumps(manifest))
    with pytest.raises(snapshot.SnapshotError, match="expected 'warren-20261031T230000Z.tar.gz'"):
        snapshot.restore(tmp_path / "snap", tmp_path / "fresh")
    assert not (tmp_path / "fresh" / "warren.db").exists()


def test_prune_never_deletes_a_file_an_odd_manifest_names(data, tmp_path):
    folder = tmp_path / "snap"
    victim = tmp_path / "keep-me.txt"
    victim.write_text("precious")
    first = _save(data, folder, 1)
    manifest = json.loads(first.read_text())
    manifest["archive"] = "../keep-me.txt"
    first.write_text(json.dumps(manifest))
    _save(data, folder, 2)
    _save(data, folder, 3)
    assert victim.read_text() == "precious"
    assert first.exists()  # left alone for a person to look at
    assert (folder / "warren-20261031T230100Z.tar.gz").exists()


def test_a_failed_raw_move_keeps_the_old_raw_files_and_says_so(data, tmp_path, monkeypatch):
    _save(data, tmp_path / "snap")
    with get_db_connection(data / "warren.db") as conn:
        conn.execute("INSERT INTO probe VALUES (7)")
        conn.commit()
    (data / "raw" / "edgar" / "only-local.json").write_text("{}")
    real_move = snapshot.shutil.move

    def failing_move(src, dst, *a, **k):
        if str(dst).endswith("edgar"):
            real_move(src, dst, *a, **k)  # a half-done copy is left behind...
            raise OSError("disk full")  # ...and then the move fails
        return real_move(src, dst, *a, **k)

    monkeypatch.setattr(snapshot.shutil, "move", failing_move)
    with pytest.raises(snapshot.SnapshotError, match="database was restored.*disk full"):
        snapshot.restore(tmp_path / "snap", data, force=True)
    assert (data / "raw" / "edgar" / "only-local.json").read_text() == "{}"
    assert (data / "raw" / "edgar" / "CIK0000789019.json").exists()
    with get_db_connection(data / "warren.db") as conn:  # by design the database is the new one
        assert sorted(r[0] for r in conn.execute("SELECT x FROM probe")) == [42]
    assert not list(data.glob("tmp*")) and not list(data.rglob(".old-*"))


def test_a_failed_database_move_keeps_the_old_database(data, tmp_path, monkeypatch):
    _save(data, tmp_path / "snap")
    with get_db_connection(data / "warren.db") as conn:
        conn.execute("INSERT INTO probe VALUES (7)")
        conn.commit()

    def failing_move(src, dst, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(snapshot.shutil, "move", failing_move)
    with pytest.raises(OSError, match="disk full"):
        snapshot.restore(tmp_path / "snap", data, force=True)
    with get_db_connection(data / "warren.db") as conn:
        assert sorted(r[0] for r in conn.execute("SELECT x FROM probe")) == [7, 42]
    assert not list(data.rglob(".old-*"))


def _old_db_with_wal(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir()
    for name, text in (("warren.db", "old"), ("warren.db-wal", "wal"), ("new.db", "new")):
        (folder / name).write_text(text)
    return folder, [folder / n for n in ("warren.db", "warren.db-wal", "warren.db-shm")]


def test_a_failed_second_move_aside_puts_the_first_back(tmp_path, monkeypatch):
    folder, targets = _old_db_with_wal(tmp_path)
    real_replace, calls = snapshot.os.replace, []

    def flaky_replace(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("busy")
        return real_replace(src, dst)

    monkeypatch.setattr(snapshot.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="busy"):
        snapshot._swap_in(folder / "new.db", targets, "db")
    assert (folder / "warren.db").read_text() == "old"
    assert (folder / "warren.db-wal").read_text() == "wal"
    assert not list(folder.glob(".old-*"))


def test_a_failed_rollback_keeps_the_old_files_aside_and_names_the_folder(tmp_path, monkeypatch):
    folder, targets = _old_db_with_wal(tmp_path)
    real_replace, calls = snapshot.os.replace, []

    def flaky_replace(src, dst):
        calls.append(src)
        if len(calls) >= 3:  # both moved aside; the swap and every move back fail
            raise OSError("busy")
        return real_replace(src, dst)

    monkeypatch.setattr(snapshot.os, "replace", flaky_replace)
    monkeypatch.setattr(
        snapshot.shutil, "move", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    with pytest.raises(snapshot.SnapshotError, match="old files are kept in .*old-db-"):
        snapshot._swap_in(folder / "new.db", targets, "db")
    [aside] = folder.glob(".old-db-*")
    assert (aside / "warren.db").read_text() == "old"
    assert (aside / "warren.db-wal").read_text() == "wal"
