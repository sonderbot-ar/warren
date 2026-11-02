"""Backlog #112: a market download counts on an as-of date only after that day ended in New York."""

from datetime import UTC, date, datetime

import pytest

from domains.market.store import MarketDataError, record_fetch, require_coverage

ROWS = [{"date": "2020-01-14", "close": 1.0}]


def _fetched(conn, when: datetime, source="yahoo", symbol="TST"):
    record_fetch(conn, source, symbol, ROWS, when)
    conn.commit()


def test_a_download_made_during_the_as_of_day_is_refused(conn):
    # 15:00 UTC is 11:00 in New York: the last row could be a mid-session price
    _fetched(conn, datetime(2020, 6, 30, 15, 0, tzinfo=UTC))
    with pytest.raises(MarketDataError, match="before the as-of date 2020-06-30 ended in New York"):
        require_coverage(conn, "yahoo", "TST", date(2020, 6, 30))
    assert require_coverage(conn, "yahoo", "TST", date(2020, 6, 29))["fetch_id"] == 1


@pytest.mark.parametrize(
    ("as_of", "just_before", "at_midnight"),
    [
        # summer: New York is on EDT (UTC-4), so midnight is 04:00 UTC
        (date(2020, 6, 30), datetime(2020, 7, 1, 3, 59, 59), datetime(2020, 7, 1, 4, 0, 0)),
        # winter: EST (UTC-5), midnight is 05:00 UTC
        (date(2020, 1, 15), datetime(2020, 1, 16, 4, 59, 59), datetime(2020, 1, 16, 5, 0, 0)),
    ],
)
def test_the_cut_off_is_new_york_midnight_in_both_seasons(conn, as_of, just_before, at_midnight):
    _fetched(conn, just_before.replace(tzinfo=UTC))
    with pytest.raises(MarketDataError, match="ended in New York"):
        require_coverage(conn, "yahoo", "TST", as_of)
    _fetched(conn, at_midnight.replace(tzinfo=UTC))  # the newer download is the one read
    assert require_coverage(conn, "yahoo", "TST", as_of)["fetch_id"] == 2


def test_the_rule_holds_for_fred_too(conn):
    _fetched(conn, datetime(2020, 1, 15, 22, 0, tzinfo=UTC), source="fred", symbol="DGS10")
    with pytest.raises(MarketDataError, match="ended in New York"):
        require_coverage(conn, "fred", "DGS10", date(2020, 1, 15))
    assert require_coverage(conn, "fred", "DGS10", date(2020, 1, 14))["fetch_id"] == 1


def test_a_download_days_later_is_used(conn):
    _fetched(conn, datetime(2026, 11, 2, 5, 0, tzinfo=UTC))
    assert require_coverage(conn, "yahoo", "TST", date(2020, 6, 30))["fetch_id"] == 1
