import hashlib

import pytest

from domains.fundamentals import concepts
from domains.fundamentals.concepts import (
    COLUMNS,
    CONCEPT_MAP_PATH,
    CONCEPT_MAPS_DIR,
    ConceptMapError,
    archived_concept_map,
    concept_map_in_force,
    concept_map_sha256,
    load_concept_map,
    reported_only_names,
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


# -- the two files (backlog #157) -------------------------------------------------------------


def test_shipped_maps_load_together():
    names = {r.canonical_name for r in load_concept_map()}
    assert {"revenue", "net_income", "discontinued_operations"} <= names
    assert "net_income" not in {r.canonical_name for r in load_concept_map(CONCEPT_MAP_PATH)}
    assert reported_only_names() == {"net_income", "discontinued_operations"}


def test_the_fingerprint_is_the_valuation_map_alone():
    expected = hashlib.sha256(CONCEPT_MAP_PATH.read_bytes()).hexdigest()
    assert concept_map_sha256() == expected  # the reported-only file never enters it


def test_a_tag_in_both_files_is_rejected(tmp_path):
    main = write_map(tmp_path, "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,")
    other = tmp_path / "reported.csv"
    other.write_text(HEADER + "\nsales,us-gaap:Revenues,1,USD,duration,optional,Top line.,\n")
    with pytest.raises(ConceptMapError, match="mapped more than once"):
        load_concept_map(main, other)


def test_an_item_split_across_the_files_is_rejected(tmp_path):
    main = write_map(tmp_path, "revenue,us-gaap:Revenues,1,USD,duration,required,Top line.,")
    other = tmp_path / "reported.csv"
    other.write_text(
        HEADER + "\nrevenue,us-gaap:SalesRevenueNet,2,USD,duration,required,Top line.,\n"
    )
    with pytest.raises(ConceptMapError, match="one file"):
        load_concept_map(main, other)


def test_no_valuation_or_scoring_step_reads_a_reported_only_item():
    """An item that can change a valuation, a score or an AI proposal belongs in concept_map.csv,
    whose fingerprint every run stores; moving it there is a visible change of that fingerprint."""
    from domains.analysis import math_engine
    from domains.evaluation import harness
    from domains.llm import propose

    read = {*math_engine.ITEMS, *harness.ITEMS, *propose.ITEMS, "capex"}
    for chain in math_engine.CHAINS.values():
        read |= {item for alternative in chain for item in alternative}
    assert not read & reported_only_names()


# -- concept map versions (backlog #357) -------------------------------------------------------


def test_todays_map_has_its_copy():
    copy = CONCEPT_MAPS_DIR / f"{concept_map_sha256()}.csv"
    assert copy.is_file() and copy.read_bytes() == CONCEPT_MAP_PATH.read_bytes(), (
        "concept_map.csv changed: copy it to concept_maps/<its sha256>.csv and add a line to "
        "concept_maps/CHANGES.md in the same commit, so stored runs can still be rebuilt"
    )


def test_every_copy_is_named_by_its_fingerprint_and_valid():
    copies = sorted(CONCEPT_MAPS_DIR.glob("*.csv"))
    assert copies
    changes = (CONCEPT_MAPS_DIR / "CHANGES.md").read_text()
    for copy in copies:
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == copy.stem
        assert f"`{copy.stem[:12]}`" in changes  # each version says what changed and why
        rows = archived_concept_map(copy.stem)
        assert {"revenue", "net_income"} <= {r.canonical_name for r in rows}


def test_an_unknown_or_altered_copy_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(concepts, "CONCEPT_MAPS_DIR", tmp_path)
    with pytest.raises(ConceptMapError, match="No copy of concept map ffffffffffff"):
        archived_concept_map("f" * 64)
    (tmp_path / f"{'e' * 64}.csv").write_bytes(CONCEPT_MAP_PATH.read_bytes())
    with pytest.raises(ConceptMapError, match="eeeeeeeeeeee .* doesn't match its name"):
        archived_concept_map("e" * 64)


def _old_map(tmp_path, monkeypatch):
    """An older map with revenue's two first tags swapped, kept as a copy; returns its sha."""
    lines = CONCEPT_MAP_PATH.read_text().splitlines(keepends=True)
    revenue = [n for n, line in enumerate(lines) if line.startswith("revenue,")]
    first, second = revenue[0], revenue[1]
    a, b = lines[first].split(",", 3), lines[second].split(",", 3)
    lines[first] = ",".join([a[0], a[1], b[2], a[3]])
    lines[second] = ",".join([b[0], b[1], a[2], b[3]])
    lines[first], lines[second] = lines[second], lines[first]
    text = "".join(lines).encode()
    sha = hashlib.sha256(text).hexdigest()
    (tmp_path / f"{sha}.csv").write_bytes(text)
    monkeypatch.setattr(concepts, "CONCEPT_MAPS_DIR", tmp_path)
    return sha


def _priorities(conn, name):
    sql = "SELECT xbrl_concept FROM concepts WHERE canonical_name = ? ORDER BY priority"
    return [r[0] for r in conn.execute(sql, (name,))]


def test_an_older_map_is_in_force_only_inside_the_block(conn, tmp_path, monkeypatch):
    sync_concepts(conn, load_concept_map())
    today = _priorities(conn, "revenue")
    sha = _old_map(tmp_path, monkeypatch)
    with concept_map_in_force(conn, sha):
        assert _priorities(conn, "revenue") == [today[1], today[0], *today[2:]]
        assert _priorities(conn, "net_income")  # today's reported-only file comes along
    assert _priorities(conn, "revenue") == today
    assert not conn.execute("SELECT 1 FROM temp.sqlite_master WHERE name = 'concepts'").fetchone()


def test_the_older_map_is_dropped_when_the_block_raises(conn, tmp_path, monkeypatch):
    sync_concepts(conn, load_concept_map())
    sha = _old_map(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError), concept_map_in_force(conn, sha):
        raise RuntimeError("boom")
    assert not conn.execute("SELECT 1 FROM temp.sqlite_master WHERE name = 'concepts'").fetchone()


def test_todays_map_changes_nothing_and_maps_do_not_nest(conn, tmp_path, monkeypatch):
    sync_concepts(conn, load_concept_map())
    with concept_map_in_force(conn, concept_map_sha256()):
        assert not conn.execute("SELECT 1 FROM temp.sqlite_master").fetchone()
    sha = _old_map(tmp_path, monkeypatch)
    with concept_map_in_force(conn, sha):
        with pytest.raises(ConceptMapError, match="already in force"):
            with concept_map_in_force(conn, sha):
                pass
        assert _priorities(conn, "revenue")  # the outer block's map is still there
