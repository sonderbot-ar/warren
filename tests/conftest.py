import pytest


@pytest.fixture
def db_path(tmp_path):
    """Path to a fresh, not-yet-created SQLite file, isolated per test."""
    return tmp_path / "test_warren.db"
