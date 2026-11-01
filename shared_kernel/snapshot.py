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

The SHA-256 proves the archive is the one its manifest describes (integrity), not who made it
(origin): anyone who can write to the folder can write a matching pair. That is fine for the
project's shared folder, which only Warren's own runs write to; never restore from a folder others
can write to. A manifest's `archive` must be the bare name `warren-<stamp>.tar.gz` that matches the
manifest's own name, so a manifest can never point `restore` or the prune step at another path.
Needs Python 3.11.4 or later (`extractall(filter="data")`).
"""

import argparse
import hashlib
import json
import os
import re
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


_MANIFEST = re.compile(r"warren-(\d{8}T\d{6}Z)\.json")


def _archive_path(manifest_path: Path, manifest: dict) -> Path:
    """The archive a manifest names, refused unless it is the one beside it with the same stamp."""
    m = _MANIFEST.fullmatch(manifest_path.name)
    expected = f"warren-{m.group(1)}.tar.gz" if m else None
    if expected is None or manifest.get("archive") != expected:
        raise SnapshotError(
            f"{manifest_path.name} names archive {manifest.get('archive')!r}; "
            f"expected {expected!r} in the same folder"
        )
    return manifest_path.parent / expected


def _swap_in(new: Path, targets: list[Path], label: str) -> None:
    """Move `targets` that exist aside, move `new` to `targets[0]`, then drop the old ones.

    The old files go to a hidden folder of their own beside `targets[0]` (same disk, outside any
    temporary folder). If any step fails, they go back where they were; if putting them back fails
    too, they stay in that folder and the error names it, so a failed restore never deletes the
    only copy.
    """
    targets[0].parent.mkdir(parents=True, exist_ok=True)
    aside = Path(tempfile.mkdtemp(dir=targets[0].parent, prefix=f".old-{label}-"))
    moved, moving_new = [], False
    try:
        for t in targets:
            if t.exists():
                os.replace(t, aside / t.name)
                moved.append(t)
        moving_new = True
        shutil.move(new, targets[0])
    except BaseException as failure:
        try:
            if moving_new and (targets[0].exists() or targets[0].is_symlink()):
                _remove(targets[0])  # a half-moved new copy; the old one is safe in `aside`
            for t in moved:
                os.replace(aside / t.name, t)
            aside.rmdir()
        except OSError as e:
            raise SnapshotError(
                f"restore failed ({failure}); the old files are kept in {aside}"
            ) from e
        raise
    shutil.rmtree(aside, ignore_errors=True)  # the swap worked; a leftover folder harms nothing


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


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
        try:
            _archive_path(old, json.loads(old.read_text())).unlink(missing_ok=True)
        except (SnapshotError, ValueError):
            continue  # an unreadable or odd manifest is left alone, and so is what it names
        old.unlink()
    return path


def restore(folder: Path, data_dir: Path = DATA_DIR, force: bool = False) -> dict:
    """Unpack the newest good snapshot into `data_dir`; returns its manifest."""
    found = manifests(folder)
    if not found:
        raise SnapshotError(f"no snapshot in {folder}")
    manifest = json.loads(found[0].read_text())
    archive = _archive_path(found[0], manifest)
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
        # Swap first, delete after: the old files sit aside until the new ones are in place.
        db_files = [data_dir / n for n in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm")]
        _swap_in(unpacked / DB_NAME, db_files, "db")
        if (unpacked / RAW_NAME).exists():
            try:
                _swap_in(unpacked / RAW_NAME, [data_dir / RAW_NAME], "raw")
            except OSError as e:  # the old raw files are back; say the database is the new one
                raise SnapshotError(
                    f"the database was restored but the raw EDGAR files were not ({e}); "
                    "the old raw files are still in place, and ingest re-fetches what it needs"
                ) from e
        if (unpacked / TELEMETRY_NAME).exists():
            try:
                _swap_in(unpacked / TELEMETRY_NAME, [data_dir / TELEMETRY_NAME], "telemetry")
            except OSError as e:  # the old telemetry is back; the reports' trace may lag
                raise SnapshotError(
                    f"the database was restored but the telemetry files were not ({e}); "
                    "the old telemetry files are still in place"
                ) from e
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
