"""Backlog #477 item 2: the track record's origin rows are built once per process and kept
while the misses, the sample count and the origin are unchanged; anything else builds afresh."""

from datetime import date

import pytest

from domains.evaluation import ranges as R
from domains.evaluation import run_ranges as RN
from tests.evaluation.test_run_ranges import D, N, add_origin, history, scored


@pytest.fixture(autouse=True)
def cold():
    RN.forget_kept_rows()
    yield
    RN.forget_kept_rows()


def _origins(conn):
    history(conn)
    add_origin(conn, "AAA", date(2021, 3, 15), [scored(1, "FY2021Q1", date(2021, 5, 15), 104.0)])
    add_origin(conn, "AAA", date(2021, 4, 15), [scored(1, "FY2021Q2", date(2021, 5, 20), 97.0)])


def _cold(conn, on, pairs, n=N):
    RN.forget_kept_rows()
    return RN.scored_origin_rows(conn, on, pairs, n)


def test_kept_rows_equal_rows_built_cold(company):
    _origins(company)
    pairs = R.load_pairs(company)
    first = RN.scored_origin_rows(company, D, pairs, N)
    assert RN._KEPT["rows"]  # kept
    again = RN.scored_origin_rows(company, D, pairs, N)
    assert again == first == _cold(company, D, pairs)
    assert len(first) == 8


def test_kept_rows_serve_another_date_as_a_cold_build_would(company):
    _origins(company)
    pairs = R.load_pairs(company)
    RN.scored_origin_rows(company, D, pairs, N)
    on = date(2021, 5, 16)  # the second origin's actual is not filed yet
    assert RN.scored_origin_rows(company, on, pairs, N) == _cold(company, on, pairs)


def test_changed_misses_or_count_build_afresh(company):
    _origins(company)
    pairs = R.load_pairs(company)
    RN.scored_origin_rows(company, D, pairs, N)
    moved = [*pairs[:-1], R.ErrorPair(*[*pairs[-1].__dict__.values()][:-1], pairs[-1].ebit + 1)]
    assert RN.scored_origin_rows(company, D, moved, N) == _cold(company, D, moved)
    assert RN._KEPT["pairs"] == tuple(moved)
    assert RN.scored_origin_rows(company, D, pairs, 200) == _cold(company, D, pairs, 200)


def test_a_changed_origin_builds_afresh(company):
    _origins(company)
    pairs = R.load_pairs(company)
    before = RN.scored_origin_rows(company, D, pairs, N)
    company.execute(
        "UPDATE baseline_errors SET forecast = 120.0 WHERE origin_id = ? AND item = 'revenue'",
        (R.origin_id("AAA", date(2021, 3, 15)),),
    )
    company.commit()
    after = RN.scored_origin_rows(company, D, pairs, N)
    assert after == _cold(company, D, pairs)
    assert after != before


def test_a_caller_changing_its_rows_leaves_the_kept_ones_alone(company):
    _origins(company)
    pairs = R.load_pairs(company)
    rows = RN.scored_origin_rows(company, D, pairs, N)
    rows[0]["p10"] = -1.0
    assert RN.scored_origin_rows(company, D, pairs, N) == _cold(company, D, pairs)


def test_a_request_with_other_misses_waits_for_a_build_in_progress(company, monkeypatch):
    """Analyst, design review: the app serves requests on threads. A request whose misses differ
    arrives while another builds; without the lock it would reset the kept rows and the first
    request would then write rows built from its own misses under the second's."""
    import threading

    _origins(company)
    pairs = R.load_pairs(company)
    moved = [*pairs[:-1], R.ErrorPair(*[*pairs[-1].__dict__.values()][:-1], pairs[-1].ebit + 1)]
    want_moved = _cold(company, D, moved)
    want = _cold(company, D, pairs)
    RN.forget_kept_rows()
    building, release = threading.Event(), threading.Event()
    real = R.subject_rows

    def slow(*args, **kwargs):
        if threading.current_thread().name == "first":
            building.set()
            release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(R, "subject_rows", slow)
    origin = [s for s in R.origin_subjects(company) if s.as_of == date(2021, 3, 15)][0]
    got: dict = {}
    first = threading.Thread(
        target=lambda: got.update(first=RN._origin_rows(origin, pairs, N)), name="first"
    )
    second = threading.Thread(
        target=lambda: got.update(second=RN._origin_rows(origin, moved, N)), name="second"
    )
    first.start()
    assert building.wait(5)
    second.start()
    second.join(0.2)
    assert second.is_alive()  # waits for the build in progress
    release.set()
    first.join(5)
    second.join(5)

    def mine(rows):
        return [
            {k: v for k, v in r.items() if k != "ticker"}
            for r in rows
            if r["subject_id"] == origin.subject_id
        ]

    assert got["first"] == mine(want)
    assert got["second"] == mine(want_moved)
    assert RN._origin_rows(origin, moved, N) == mine(want_moved)  # what is kept is the second's
