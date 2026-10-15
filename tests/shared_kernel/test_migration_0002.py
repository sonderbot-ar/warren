import sqlite3

import pytest

from shared_kernel.database import apply_migrations, current_schema_version, get_db_connection

FACT_SQL = """
INSERT OR IGNORE INTO financial_facts
    (cik, xbrl_concept, period_start, period_end, value, unit, form, accession_no, filed_at)
VALUES (?, ?, ?, ?, ?, 'USD', '10-K', ?, '2025-10-31')
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


def test_migration_applies_on_top_of_0001(conn):
    assert current_schema_version(conn) >= 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"companies", "concepts", "financial_facts"} <= tables


def test_duplicate_instant_fact_is_ignored(conn):
    row = ("0000000001", "us-gaap:Cash", None, "2025-09-27", 1.0, "acc-1")
    conn.execute(FACT_SQL, row)
    conn.execute(FACT_SQL, row)
    assert conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0] == 1


def test_same_fact_in_a_later_filing_is_kept(conn):
    conn.execute(FACT_SQL, ("0000000001", "us-gaap:Cash", None, "2025-09-27", 1.0, "acc-1"))
    conn.execute(FACT_SQL, ("0000000001", "us-gaap:Cash", None, "2025-09-27", 2.0, "acc-2"))
    assert conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0] == 2


def test_unmapped_concept_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(FACT_SQL, ("0000000001", "us-gaap:Made", None, "2025-09-27", 1.0, "acc-1"))


def test_two_canonical_names_cannot_share_a_tag(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO concepts VALUES ('money', 'us-gaap:Cash', 1, 'USD', 'instant', 'Dup.')"
        )
