from datetime import UTC, date, datetime

from domains.news import gdelt
from shared_kernel import calendar


def test_known_by_is_new_york_midnight_in_utc():
    assert calendar.known_by(date(2020, 6, 30)) == datetime(2020, 7, 1, 4, 0, tzinfo=UTC)  # EDT
    assert calendar.known_by(date(2020, 1, 15)) == datetime(2020, 1, 16, 5, 0, tzinfo=UTC)  # EST


def test_news_and_market_share_one_rule():
    assert gdelt.known_by is calendar.known_by and gdelt.CASE_TZ is calendar.CASE_TZ
