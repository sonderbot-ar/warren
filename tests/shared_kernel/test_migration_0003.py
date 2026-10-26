import sqlite3

import pytest

from shared_kernel.database import apply_migrations, get_db_connection

FACT_SQL = """
INSERT INTO financial_facts
    (cik, xbrl_concept, period_end, value, unit, form, accession_no, filed_at)
VALUES ('0000000001', 'us-gaap:Cash', ?, 1, 'USD', '10-K', ?, ?)
"""


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000001', 'TST', 'T')")
        conn.execute(
            "INSERT INTO concepts VALUES ('cash', 'us-gaap:Cash', 1, 'USD', 'instant', 'Cash.')"
        )
        yield conn


def test_fact_ending_after_its_filing_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError, match="period_end is after filed_at"):
        conn.execute(FACT_SQL, ("2025-12-31", "a", "2025-03-01"))


def test_fact_ending_on_or_before_its_filing_is_accepted(conn):
    conn.execute(FACT_SQL, ("2025-03-01", "a", "2025-03-01"))
    conn.execute(FACT_SQL, ("2024-12-31", "b", "2025-03-01"))
    assert conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0] == 2


def test_ingest_runs_table_exists(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(ingest_runs)")}
    assert {"companyfacts_sha256", "companyfacts_fetched_at", "concept_map_sha256"} <= columns
