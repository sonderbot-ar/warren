import json
from pathlib import Path

import pytest

from domains.fundamentals.ingest import ingest_company
from shared_kernel.database import apply_migrations, get_db_connection

FIXTURES = Path(__file__).parent / "fixtures"
TEST_CIK = "0000000123"


class FakeEdgar:
    """Stands in for EdgarClient: serves the saved fixture, never touches the network."""

    def __init__(self, sic="3571"):
        self.facts = json.loads((FIXTURES / "companyfacts_test.json").read_text())
        self.submissions = {
            "cik": TEST_CIK,
            "name": "Test Corp",
            "sic": sic,
            "fiscalYearEnd": "1231",
            "formerNames": [{"name": "Test Holdings"}],
        }

    def lookup_cik(self, ticker, refresh=False):
        return TEST_CIK

    def get_submissions(self, cik, refresh=False):
        return self.submissions

    def get_company_facts(self, cik, refresh=False):
        return self.facts

    def company_facts_fetched_at(self, cik):
        return "2026-10-26T12:00:00Z"


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        yield conn


@pytest.fixture
def ingested(conn):
    """A database holding the fixture company, plus the ingest result."""
    result = ingest_company(conn, "TST", client=FakeEdgar())
    return conn, result
