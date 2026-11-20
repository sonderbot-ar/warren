"""Backlog #477 item 2: the reads a caller keeps between periods (`_shared`) give the same
answers as reading afresh, on Test Corp across a recast and a change of meaning together, so
every kept read (views, filings, newest-filing disagreements, sign flips, parts, meaning
changes, recasts, version dates) is on a path the answers depend on."""

from dataclasses import asdict

from domains.analysis.reported import (
    _series_meaning_notes,
    _series_recast_notes,
    reported_period,
)
from tests.analysis.conftest import AS_OF
from tests.analysis.test_reported import _redefine_revenues
from tests.analysis.test_series_recast import _recast_revenues

YEARS = ["FY2015", "FY2016", "FY2017", "FY2018", "FY2019"]
QUARTERS = ["FY2017Q1", "FY2017Q4", "FY2018Q1", "FY2018Q2", "FY2019Q1"]


def _both(tag, row):
    return _redefine_revenues(tag, _recast_revenues(tag, row))


def _read(conn, labels, shared):
    return [reported_period(conn, "TST", x, AS_OF, _shared=shared) for x in labels]


def test_periods_read_with_kept_reads_equal_periods_read_afresh(make_company):
    conn = make_company(_both)
    shared: dict = {}
    for labels in (YEARS, QUARTERS):
        kept = _read(conn, labels, shared)
        fresh = _read(conn, labels, None)
        assert [asdict(a) for a in kept] == [asdict(b) for b in fresh]
    # the newest-filing disagreements are kept too, once per set of line names
    assert any(k[0] == "newest" for k in shared)


def test_series_notes_with_kept_reads_equal_notes_read_afresh(make_company):
    conn = make_company(_both)
    shared: dict = {}
    for labels in (YEARS, QUARTERS):
        answers = sorted(_read(conn, labels, shared), key=lambda a: a.period_end)
        for notes_of in (_series_meaning_notes, _series_recast_notes):
            kept = notes_of(conn, answers, AS_OF, shared)
            again = notes_of(conn, answers, AS_OF, shared)  # read from what was kept
            fresh = notes_of(conn, answers, AS_OF)
            assert kept == again == fresh
    codes = {n.code for n in _series_meaning_notes(conn, answers, AS_OF, shared)}
    codes |= {n.code for n in _series_recast_notes(conn, answers, AS_OF, shared)}
    assert codes  # the case reaches the notes, so the kept reads are exercised
    assert {"recasts", "versions", "changes"} <= {k[0] for k in shared}


def test_a_date_past_the_history_warns_on_every_period_with_kept_reads(make_company, monkeypatch):
    """Analyst, design review: once every read is kept, a later period made no read that warns,
    so `reported_period` says it itself (Exxon on 2026-10-30, past its 2026-08-03 cut-off)."""
    from domains.fundamentals import universe

    conn = make_company(_both)
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    fields = {"ticker": "TST", "cik": cik, "as_of": AS_OF.isoformat(),
              "history_ends": "2019-01-01", "reason": None, "successor_cik": None,
              "successor_name": None, "note": ""}  # fmt: skip
    monkeypatch.setattr(universe, "coverage_gap", lambda c, d: ("past history", fields))
    shared: dict = {}
    kept = _read(conn, YEARS, shared)
    fresh = _read(conn, YEARS, None)
    assert [[w.code for w in a.warnings] for a in kept] == [["beyond_history"]] * len(YEARS)
    assert [a.warnings for a in kept] == [b.warnings for b in fresh]
