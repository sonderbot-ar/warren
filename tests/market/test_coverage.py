"""Backlog #381: the newest as-of date every series a run reads can serve."""

from datetime import UTC, date, datetime

from domains.market.coverage import RUN_SERIES, run_covered_through, run_series
from domains.market.prices import MARKET_INDEX
from domains.market.store import covered_through, record_fetch, require_coverage
from domains.market.yields import RISK_FREE_SERIES

ROWS = [{"date": "2020-01-14", "close": 1.0}]


def _fetched(conn, source, symbol, when: datetime):
    record_fetch(conn, source, symbol, ROWS, when)
    conn.commit()


def _all(conn, stock, index, rate):
    _fetched(conn, "yahoo", "TST", stock)
    _fetched(conn, "yahoo", MARKET_INDEX, index)
    _fetched(conn, "fred", RISK_FREE_SERIES, rate)


def test_a_run_reads_the_stock_the_index_and_the_risk_free_rate():
    assert run_series("tst") == [
        ("yahoo", "TST"),
        ("yahoo", MARKET_INDEX),
        ("fred", RISK_FREE_SERIES),
    ]
    assert len(RUN_SERIES) == 3


def test_the_earliest_of_the_three_downloads_wins_whichever_is_older(conn):
    late, early = datetime(2020, 7, 1, 12, tzinfo=UTC), datetime(2020, 6, 20, 12, tzinfo=UTC)
    for older in range(3):
        times = [early if i == older else late for i in range(3)]
        _all(conn, *times)
        assert run_covered_through(conn, "tst") == date(2020, 6, 19)


def test_none_when_a_series_was_never_downloaded(conn):
    _fetched(conn, "yahoo", "TST", datetime(2020, 7, 1, 12, tzinfo=UTC))
    _fetched(conn, "yahoo", MARKET_INDEX, datetime(2020, 7, 1, 12, tzinfo=UTC))
    assert run_covered_through(conn, "TST") is None


def test_a_download_at_new_york_midnight_covers_the_day_that_just_ended(conn):
    # 04:00 UTC on Jul 1 is midnight in New York (EDT): June 30 has just ended
    midnight = datetime(2020, 7, 1, 4, 0, tzinfo=UTC)
    _all(conn, midnight, midnight, midnight)
    assert run_covered_through(conn, "TST") == date(2020, 6, 30)
    for source, symbol in run_series("TST"):
        fetch = require_coverage(conn, source, symbol, date(2020, 6, 30))
        assert covered_through(fetch) == date(2020, 6, 30)
