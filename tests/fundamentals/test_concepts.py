import pytest

from domains.fundamentals.concepts import (
    COLUMNS,
    ConceptMapError,
    load_concept_map,
    sync_concepts,
)
from shared_kernel.database import apply_migrations, get_db_connection

HEADER = ",".join(COLUMNS)


def write_map(tmp_path, *lines):
    path = tmp_path / "map.csv"
    path.write_text("\n".join([HEADER, *lines]) + "\n")
    return path


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        yield conn


def test_shipped_concept_map_is_valid():
    rows = load_concept_map()
    assert {"revenue", "operating_income", "cash", "diluted_shares"} <= {
        r.canonical_name for r in rows
    }


def test_duplicate_tag_is_rejected(tmp_path):
    path = write_map(
        tmp_path,
        "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,",
        "sales,us-gaap:Revenues,1,USD,duration,required,Top line.,",
    )
    with pytest.raises(ConceptMapError, match="mapped more than once"):
        load_concept_map(path)


def test_priority_gap_is_rejected(tmp_path):
    path = write_map(
        tmp_path,
        "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,",
        "revenue,us-gaap:SalesRevenueNet,3,USD,duration,required,Top line.,",
    )
    with pytest.raises(ConceptMapError, match="priorities"):
        load_concept_map(path)


def test_unknown_unit_and_mixed_period_type_are_rejected(tmp_path):
    path = write_map(
        tmp_path,
        "revenue,us-gaap:Revenues,1,EUR,duration,required,Top line.,",
        "revenue,us-gaap:SalesRevenueNet,2,USD,instant,required,Top line.,",
    )
    with pytest.raises(ConceptMapError) as err:
        load_concept_map(path)
    assert "unknown unit" in str(err.value)
    assert "period_type" in str(err.value)


def test_sync_is_idempotent(conn):
    rows = load_concept_map()
    first = sync_concepts(conn, rows)
    second = sync_concepts(conn, rows)
    assert first["inserted"] == len(rows)
    assert second == {"inserted": 0, "updated": 0, "deleted": 0}
    assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == len(rows)


def test_sync_reorders_priorities_and_deletes_removed_tags(conn, tmp_path):
    sync_concepts(
        conn,
        load_concept_map(
            write_map(
                tmp_path,
                "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,",
                "revenue,us-gaap:SalesRevenueNet,2,USD,duration,required,Top line.,",
                "cash,us-gaap:Cash,1,USD,instant,required,Cash.,",
            )
        ),
    )
    counts = sync_concepts(
        conn,
        load_concept_map(
            write_map(
                tmp_path,
                "revenue,us-gaap:SalesRevenueNet,1,USD,duration,required,Top line.,",
                "revenue,us-gaap:Revenues,2,USD,duration,required,Top line.,",
            )
        ),
    )
    assert counts == {"inserted": 0, "updated": 2, "deleted": 1}
    priority = dict(conn.execute("SELECT xbrl_concept, priority FROM concepts").fetchall())
    assert priority == {"us-gaap:SalesRevenueNet": 1, "us-gaap:Revenues": 2}


def test_sync_refuses_to_drop_a_tag_with_stored_facts(conn, tmp_path):
    sync_concepts(
        conn, load_concept_map(write_map(tmp_path, "cash,us-gaap:Cash,1,USD,instant,required,C.,"))
    )
    conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000001', 'TST', 'T')")
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_end, value, unit, form, "
        "accession_no, filed_at) VALUES ('0000000001', 'us-gaap:Cash', '2025-01-01', 1, 'USD', "
        "'10-K', 'a', '2025-02-01')"
    )
    other = write_map(tmp_path, "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,")
    with pytest.raises(ConceptMapError, match="still have stored facts"):
        sync_concepts(conn, load_concept_map(other))


def test_unquoted_comma_and_unknown_gate_are_rejected(tmp_path):
    path = write_map(
        tmp_path,
        "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,note, with a comma",
        "cash,us-gaap:Cash,1,USD,instant,sometimes,Cash.,",
    )
    with pytest.raises(ConceptMapError) as err:
        load_concept_map(path)
    assert "line 2: wrong number of fields" in str(err.value)
    assert "line 3: gate must be one of" in str(err.value)


def test_shipped_fallback_and_holding_items_are_optional():
    gates = {r.canonical_name: r.gate for r in load_concept_map()}
    assert gates["revenue"] == "required"
    assert gates["marketable_securities_current"] == gates["interest_paid"] == "optional"
