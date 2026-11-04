"""Run ids are numbered inside the write transaction (backlog #176): two requests at the same
moment, each on its own connection, never pick the same run id or store the same what-if twice.

Each writer gets a connection that pauses after every read of the runs table, which widens the
gap between "count the runs" and "insert the next one" far past what a real request would leave.
Without the write lock, the writers all count the same number and collide on the primary key."""

import sqlite3
import threading
import time

import pytest

from domains.analysis import dcf
from domains.analysis.math_engine import build_inputs, post_checks
from domains.analysis.runs import reproduce, run_baseline, save_run, write_lock
from domains.analysis.whatif import Change, revalue
from tests.analysis.conftest import AS_OF, CHOICES

WRITERS = 6
PAUSE = 0.05  # seconds after each read of the runs table


class SlowReads(sqlite3.Connection):
    def execute(self, sql, *args):
        cursor = super().execute(sql, *args)
        if "FROM runs" in sql:
            time.sleep(PAUSE)
        return cursor


def _connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0, factory=SlowReads, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _at_once(path, work) -> list:
    """Run work(conn, i) on WRITERS threads, each with its own connection, released together."""
    start = threading.Barrier(WRITERS)
    results: list = [None] * WRITERS

    def one(i):
        conn = _connect(path)
        try:
            start.wait()
            results[i] = work(conn, i)
        except Exception as error:  # noqa: BLE001 - the test reports every writer's failure
            results[i] = error
        finally:
            conn.close()

    threads = [threading.Thread(target=one, args=(i,)) for i in range(WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_runs_saved_at_once_get_distinct_ids_in_order(company, db_path):
    result = build_inputs(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    outputs, gaps = dcf.outputs_and_gaps(result.assumptions)
    notes = post_checks(result.assumptions, outputs)

    ids = _at_once(db_path, lambda conn, _i: save_run(conn, result, outputs, notes, gaps))

    errors = [r for r in ids if isinstance(r, Exception)]
    assert errors == []
    prefix = f"TST_{AS_OF.isoformat()}_"
    assert sorted(ids) == sorted(f"{prefix}{n}" for n in range(1, WRITERS + 1))
    for run_id in ids:
        assert reproduce(company, run_id).ok
    stored = company.execute("SELECT COUNT(*) FROM assumptions").fetchone()[0]
    assert stored == WRITERS * len(result.assumptions)


def test_the_same_what_if_asked_at_once_is_stored_once(company, db_path):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    change = [Change("operating_margin", delta=-0.01)]

    answers = _at_once(db_path, lambda conn, _i: revalue(conn, parent, change))

    errors = [a for a in answers if isinstance(a, Exception)]
    assert errors == []
    assert {a.run_id for a in answers} == {f"{parent}_whatif_1"}
    assert sorted(a.reused for a in answers) == [False] + [True] * (WRITERS - 1)
    children = company.execute(
        "SELECT COUNT(*) FROM runs WHERE parent_run_id = ?", (parent,)
    ).fetchone()[0]
    assert children == 1


def test_different_what_ifs_at_once_are_numbered_without_gaps(company, db_path):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)

    answers = _at_once(
        db_path,
        lambda conn, i: revalue(conn, parent, [Change("operating_margin", delta=-0.001 * (i + 1))]),
    )

    errors = [a for a in answers if isinstance(a, Exception)]
    assert errors == []
    assert not any(a.reused for a in answers)
    ids = sorted(a.run_id for a in answers)
    assert ids == sorted(f"{parent}_whatif_{n}" for n in range(1, WRITERS + 1))


def test_an_error_inside_the_lock_rolls_everything_back(company):
    company.execute("CREATE TABLE scratch (x INTEGER)")
    company.commit()
    with pytest.raises(RuntimeError):
        with write_lock(company):
            company.execute("INSERT INTO scratch VALUES (1)")
            raise RuntimeError("stop")
    assert company.execute("SELECT COUNT(*) FROM scratch").fetchone()[0] == 0
    assert not company.in_transaction


def test_a_transaction_left_open_by_the_caller_is_kept(company):
    company.execute("CREATE TABLE scratch (x INTEGER)")
    company.execute("INSERT INTO scratch VALUES (1)")
    assert company.in_transaction
    run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    assert company.execute("SELECT x FROM scratch").fetchall()[0][0] == 1
    assert not company.in_transaction


def test_the_lock_refuses_to_nest_and_keeps_the_first_error(company):
    company.execute("CREATE TABLE scratch (x INTEGER)")
    company.commit()
    with pytest.raises(RuntimeError, match="doesn't nest"):
        with write_lock(company):
            company.execute("INSERT INTO scratch VALUES (1)")
            with write_lock(company):
                pass
    assert company.execute("SELECT COUNT(*) FROM scratch").fetchone()[0] == 0
    with write_lock(company):  # usable again afterwards
        company.execute("INSERT INTO scratch VALUES (2)")
    assert company.execute("SELECT x FROM scratch").fetchall()[0][0] == 2
