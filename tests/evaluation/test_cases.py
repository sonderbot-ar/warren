"""The case file loader refuses rows that break a selection rule; migration 0007 is safe."""

import pytest

from domains.evaluation.cases import CASES_PATH, COLUMNS, CaseError, load_cases, store_cases
from shared_kernel.database import apply_migrations, get_db_connection

GOOD = {
    "case_id": "AAPL_2020-02-17",
    "ticker": "AAPL",
    "event_date": "2020-02-17",
    "event_type": "guidance",
    "description": "Apple says it will not meet its March-quarter revenue guidance",
    "horizon_quarters": "4",
    "selected_because": "event rule: company announcement",
    "source_url": "https://www.apple.com/newsroom/",
    "scope_change": "",
}


def write(tmp_path, *rows):
    path = tmp_path / "cases.csv"
    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(f'"{row[c]}"' for c in COLUMNS))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_good_case_loads(tmp_path):
    (case,) = load_cases(write(tmp_path, GOOD))
    assert case.case_id == "AAPL_2020-02-17" and case.horizon_quarters == 4
    assert not case.is_control


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"ticker": "TSLA", "case_id": "TSLA_2020-02-17"}, "not in the universe"),
        ({"event_date": "2019-01-02", "case_id": "AAPL_2019-01-02"}, "before 2019-03-01"),
        ({"event_type": "rumour"}, "unknown event type"),
        ({"horizon_quarters": "5"}, "horizon must be 1-4"),
        ({"case_id": "apple-guidance"}, "case_id must be"),
        ({"source_url": ""}, "needs a source URL"),
        ({"event_type": "control"}, "control rule"),
        ({"description": ""}, "required"),
        ({"event_date": "Feb 17"}, "bad date"),
    ],
)
def test_a_bad_case_is_refused(tmp_path, change, message):
    with pytest.raises(CaseError, match=message):
        load_cases(write(tmp_path, GOOD | change))


def test_a_duplicate_case_is_refused(tmp_path):
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(write(tmp_path, GOOD, GOOD))


def test_a_control_needs_no_source(tmp_path):
    control = GOOD | {
        "event_type": "control",
        "source_url": "",
        "selected_because": "control rule: 50 days after fiscal Q2 end, 2020",
    }
    (case,) = load_cases(write(tmp_path, control))
    assert case.is_control


def test_a_control_near_an_event_of_its_company_is_refused(tmp_path):
    control = GOOD | {
        "case_id": "AAPL_2020-04-01",
        "event_date": "2020-04-01",
        "event_type": "control",
        "source_url": "",
        "selected_because": "control rule: test",
    }
    with pytest.raises(CaseError, match="within 120 days"):
        load_cases(write(tmp_path, GOOD, control))


def test_wrong_columns_are_refused(tmp_path):
    path = tmp_path / "cases.csv"
    path.write_text("case_id,ticker\nA,B\n")
    with pytest.raises(CaseError, match="columns"):
        load_cases(path)


def test_the_checked_in_library_is_valid():
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 15
    assert sum(c.is_control for c in cases) == 8


def test_storing_cases_twice_updates_them(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000320193', 'AAPL', 'A')")
        cases = load_cases(write(tmp_path, GOOD))
        store_cases(conn, cases)
        store_cases(conn, load_cases(write(tmp_path, GOOD | {"horizon_quarters": "2"})))
        rows = conn.execute("SELECT case_id, cik, horizon_quarters FROM eval_cases").fetchall()
        assert [tuple(r) for r in rows] == [("AAPL_2020-02-17", "0000320193", 2)]


def test_storing_a_case_for_a_company_not_ingested_fails(db_path, tmp_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        with pytest.raises(CaseError, match="not been ingested"):
            store_cases(conn, load_cases(write(tmp_path, GOOD)))


def test_migration_0007_applies_on_an_existing_database(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"eval_cases", "eval_batches", "eval_results", "eval_failures"} <= tables
        assert apply_migrations(conn) == []
