"""How the app shares Warren's SQLite database with the engine's commands (F2 design, Engine needs).

- Each route opens its own connection inside its body (`with get_db_connection(path) as conn:`),
  never one shared across requests: SQLite's connection keeps its same-thread check, and FastAPI
  runs plain route functions on worker threads.
- The app never applies migrations. At start it compares the migrations recorded in the
  database with the engine's migration files and refuses to start if they differ, naming the
  command that brings the database up to date.
- The app writes only when a student asks for something new (a what-if, a run on a date with
  none stored), never on a page view. Since v0.9.10 (backlog #176) the engine numbers runs inside
  its own write lock, so the app needs no lock of its own.
- A write that waits past SQLite's 10-second timeout (during a long ingest) shows the "busy"
  error page and can be retried (`app.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shared_kernel.database import applied_versions, get_db_connection, list_migrations

UPDATE_COMMAND = "python -m shared_kernel.snapshot restore --dir /mnt/project-files/warren-data/"


@dataclass(frozen=True)
class SchemaStatus:
    missing: list[int] = field(default_factory=list)  # in the code, not applied to the database
    unknown: list[int] = field(default_factory=list)  # applied, but not in this copy of the code

    @property
    def current(self) -> bool:
        return not self.missing and not self.unknown


class SchemaMismatch(RuntimeError):
    """The database and the engine's code disagree on the schema; the app will not start."""


def schema_status(conn) -> SchemaStatus:
    """Compare the migrations recorded in `conn` with the engine's migration files. Read only."""
    expected = {version for version, _ in list_migrations()}
    applied = applied_versions(conn)
    return SchemaStatus(missing=sorted(expected - applied), unknown=sorted(applied - expected))


def require_current_schema(db_path: Path) -> None:
    """Refuse to start on a missing or out-of-date database, with what to run instead."""
    if not Path(db_path).exists():
        raise SchemaMismatch(
            f"No Warren database at {db_path}. Restore the saved data first: {UPDATE_COMMAND}"
        )
    with get_db_connection(db_path) as conn:
        status = schema_status(conn)
    if status.missing:
        raise SchemaMismatch(
            f"The database at {db_path} lacks migrations {status.missing}. The app never applies "
            f"migrations; run {UPDATE_COMMAND} (or any engine command, which applies them), "
            "then start the app again."
        )
    if status.unknown:
        raise SchemaMismatch(
            f"The database at {db_path} has migrations {status.unknown} that this copy of the "
            "code does not know. Update the code (git pull) before starting the app."
        )
