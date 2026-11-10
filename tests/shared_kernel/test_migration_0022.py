"""0022 adds each filing's own label beside Warren's (backlog #310); stored facts are kept and
the table stays empty until the next ingest."""

import sqlite3

import pytest

from shared_kernel.database import apply_migrations, get_db_connection
from tests.shared_kernel.test_migration_0019 import _dir

CIK = "0000000123"


def test_0022_adds_the_table_and_keeps_stored_facts(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, _dir(tmp_path, "upto21", lambda v: v <= 21))
        conn.execute(
            "INSERT INTO companies (cik, ticker, name, sic, fiscal_year_end, aliases_json) "
            "VALUES (?, 'TST', 'Test Corp', '3571', '1231', '[]')",
            (CIK,),
        )
        conn.execute(
            "INSERT INTO concepts (canonical_name, xbrl_concept, priority, unit, period_type, "
            "definition) VALUES ('revenue', 'us-gaap:Revenues', 1, 'USD', 'duration', 'Sales.')"
        )
        conn.execute(
            "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, "
            "fiscal_year, fiscal_period, value, unit, form, accession_no, filed_at) VALUES "
            "(?, 'us-gaap:Revenues', '2024-01-01', '2024-12-31', 2024, 'FY', 10, 'USD', "
            "'10-K', 'a-1', '2025-02-01')",
            (CIK,),
        )
        conn.commit()
        assert apply_migrations(conn) == [22]
        assert conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM filing_labels").fetchone()[0] == 0

        def put(accn="a-1", form="10-K", end="2024-12-31", fy=2024, fp="FY", wy=2024, wp="FY"):
            conn.execute(
                "INSERT INTO filing_labels (cik, accession_no, form, filed_at, period_end, "
                "filed_fiscal_year, filed_fiscal_period, fiscal_year, fiscal_period) "
                "VALUES (?, ?, ?, '2025-02-01', ?, ?, ?, ?, ?)",
                (CIK, accn, form, end, fy, fp, wy, wp),
            )

        put()
        put(accn="cover", form="10-Q/A", end=None, fy=2025, fp="Q1", wy=None, wp=None)
        for bad in (
            lambda: put(),  # one row per filing
            lambda: put(accn="b", form="8-K"),
            lambda: put(accn="c", end="2025-03-01"),  # an own period after the filing
            lambda: put(accn="d", fp="H1"),
            lambda: put(accn="e", wp="M9"),
            lambda: put(accn="f", wy=None),  # a year without a period
        ):
            with pytest.raises(sqlite3.IntegrityError):
                bad()
