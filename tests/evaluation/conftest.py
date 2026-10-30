"""Test Corp (see tests/analysis/conftest.py) for the evaluation harness."""

import pytest

from tests.analysis.conftest import CHOICES, make_db  # noqa: F401  (CHOICES re-exported)


@pytest.fixture
def company(db_path):
    conn_cm, conn = make_db(db_path)
    yield conn
    conn_cm.__exit__(None, None, None)


@pytest.fixture
def make_company(tmp_path):
    """Build Test Corp with edited filings: make_company(edit) -> connection."""
    opened = []

    def build(edit):
        conn_cm, conn = make_db(tmp_path / f"edited_{len(opened)}.db", edit)
        opened.append(conn_cm)
        return conn

    yield build
    for conn_cm in opened:
        conn_cm.__exit__(None, None, None)
