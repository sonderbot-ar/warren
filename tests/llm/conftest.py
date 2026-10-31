import pytest

from shared_kernel.database import apply_migrations, get_db_connection


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        yield conn
