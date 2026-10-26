from datetime import UTC, datetime

import pytest

from shared_kernel.database import apply_migrations, get_db_connection

FETCHED = datetime(2020, 9, 3, 12, 0, tzinfo=UTC)


def fixed_clock():
    return FETCHED


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        yield conn
