from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from webapp.app import create_app

# 18:00 UTC on nov.04 is 13:00 in New York, so the last ended day is nov.03
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
LATEST = "2026-11-03"


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path=db_path, clock=lambda: NOW), follow_redirects=False)
