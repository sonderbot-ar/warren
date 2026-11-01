"""Save and restore a snapshot of Warren's data, so a fresh machine skips downloads (backlog #98).

    python -m shared_kernel.snapshot save --dir DIR
    python -m shared_kernel.snapshot restore --dir DIR [--force]

A snapshot is one `warren-<UTC time>.tar.gz` holding a consistent copy of the database (made with
SQLite's backup, so the WAL is included), the raw EDGAR files and the pipelines' telemetry (M7),
next to a JSON manifest with the archive's SHA-256, its size, the schema version, the code commit
and row counts. `restore` picks the newest manifest, checks the hash, unpacks into `data/` and
applies newer migrations. Nothing in a snapshot changes point-in-time reads: every row keeps its
own filing, fetch and seen dates.
Callers still run the reproduce checks before trusting the data (the warren-run-track skill).
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from shared_kernel.config import DATA_DIR, DB_PATH, PROJECT_ROOT, RAW_EDGAR_DIR
from shared_kernel.database import apply_migrations, current_schema_version, get_db_connection

KEEP = 2  # snapshots kept in the folder; older ones are removed after a good save
DB_NAME, RAW_NAME, TELEMETRY_NAME = "warren.db", "raw/edgar", "telemetry"  # telemetry: M7


class SnapshotError(RuntimeError):
    """No usable snapshot: missing, corrupt, or newer than this code."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                             text=True, check=True)  # fmt: skip
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )]  # fmt: skip
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def manifests(folder: Path) -> list[Path]:
    """Manifests in the folder, newest first (names sort by their UTC time)."""
    return sorted(folder.glob("warren-*.json"), reverse=True)


def save(folder: Path, db_path: Path = DB_PATH, raw_dir: Path = RAW_EDGAR_DIR,
         now: datetime | None = None, telemetry_dir: Path | None = None) -> Path:  # fmt: skip
    """Write a snapshot and its manifest to `folder`; returns the manifest's path."""
    if not db_path.exists():
        raise SnapshotError(f"no database at {db_path}")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    archive = folder / f"warren-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / DB_NAME
        with closing(sqlite3.connect(db_path)) as src, closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(copy)) as conn:
            version, counts = current_schema_version(conn), _row_counts(conn)
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(copy, arcname=DB_NAME)
            if raw_dir.exists():
                tar.add(raw_dir, arcname=RAW_NAME)
            telemetry = telemetry_dir or db_path.parent / TELEMETRY_NAME
            if telemetry.exists():  # the pipelines' telemetry lines, which reports point to
                tar.add(telemetry, arcname=TELEMETRY_NAME)
        partial.rename(archive)  # a reader never sees a half-written archive
    manifest = {
        "archive": archive.name,
        "sha256": _sha256(archive),
        "bytes": archive.stat().st_size,
        "schema_version": version,
        "commit": _commit(),
        "created_at": stamp,
        "row_counts": counts,
    }
    path = folder / f"warren-{stamp}.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    for old in manifests(folder)[KEEP:]:
        (folder / json.loads(old.read_text())["archive"]).unlink(missing_ok=True)
        old.unlink()
    return path


def restore(folder: Path, data_dir: Path = DATA_DIR, force: bool = False) -> dict:
    """Unpack the newest good snapshot into `data_dir`; returns its manifest."""
    found = manifests(folder)
    if not found:
        raise SnapshotError(f"no snapshot in {folder}")
    manifest = json.loads(found[0].read_text())
    archive = folder / manifest["archive"]
    if not archive.exists() or _sha256(archive) != manifest["sha256"]:
        raise SnapshotError(f"{archive.name} is missing or does not match its SHA-256")
    db_path = data_dir / DB_NAME
    if db_path.exists() and not force:
        raise SnapshotError(f"{db_path} exists; pass --force to replace it")
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir) as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")  # refuses absolute paths and links out of tmp
        unpacked = Path(tmp)
        for name in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm"):
            (data_dir / name).unlink(missing_ok=True)
        shutil.move(unpacked / DB_NAME, db_path)
        for name in (RAW_NAME, TELEMETRY_NAME):
            if (unpacked / name).exists():
                target = data_dir / name
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(unpacked / name, target)
    with get_db_connection(db_path) as conn:
        if current_schema_version(conn) > manifest["schema_version"]:
            raise SnapshotError("the restored database is newer than its manifest")
        manifest["migrations_applied"] = apply_migrations(conn)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shared_kernel.snapshot")
    parser.add_argument("command", choices=("save", "restore"))
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "save":
            path = save(args.dir)
            m = json.loads(path.read_text())
            size = m["bytes"] / 1e6
            print(f"saved {m['archive']} ({size:,.0f} MB, schema {m['schema_version']})")
        else:
            m = restore(args.dir, force=args.force)
            applied = m["migrations_applied"] or "none"
            print(f"restored {m['archive']} (schema {m['schema_version']}, commit "
                  f"{m['commit'][:7]}; migrations applied: {applied})")  # fmt: skip
    except SnapshotError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
