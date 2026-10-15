import re
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from shared_kernel.config import DB_PATH

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# migration files are named NNNN_description.sql, e.g. 0001_init.sql
MIGRATION_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@contextmanager
def get_db_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Atomic context manager that ensures a connection is SAFELY closed even if an agent crashes.

    Every connection runs in WAL mode (readers are not blocked by a writer) with foreign keys on.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)  # seconds to wait for a lock before raising
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")  # persists in the file; cheap to repeat
        conn.execute("PRAGMA foreign_keys=ON;")  # per connection; SQLite defaults it to OFF
        yield conn
    finally:
        conn.close()


def list_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Return (version, path) for every migration file, sorted by version. Fails on bad names."""
    migrations = []
    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION_PATTERN.match(path.name)
        if match is None:
            raise ValueError(f"Migration file name must look like 0001_name.sql: {path.name}")
        migrations.append((int(match.group(1)), path))

    migrations.sort()
    versions = [version for version, _ in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError(f"Duplicate migration versions in {migrations_dir}")
    return migrations


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Highest applied migration version, or 0 for an empty database."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if table is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply every pending migration in order, each in its own transaction.

    Returns the versions applied (empty when the schema is already up to date).
    A failing migration is rolled back and re-raised; earlier migrations stay applied.
    """
    applied = []
    current = current_schema_version(conn)
    for version, path in list_migrations(migrations_dir):
        if version <= current:
            continue
        sql = path.read_text()
        # executescript() commits any open transaction before running, so BEGIN/COMMIT live
        # inside the script. path.stem is safe to inline: MIGRATION_PATTERN allows [a-z0-9_].
        script = (
            f"BEGIN;\n{sql}\n;"
            f"INSERT INTO schema_version (version, name) VALUES ({version}, '{path.stem}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        applied.append(version)
    return applied
