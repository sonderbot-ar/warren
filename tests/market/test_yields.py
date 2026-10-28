from datetime import date

import pytest

from domains.market import yields
from domains.market.store import MarketDataError, pin_fetches
from domains.market.yields import fred_download, load_yields, risk_free_rate
from tests.market.conftest import fixed_clock

OBSERVATIONS = [
    {"date": "2020-08-27", "value": 0.74},
    {"date": "2020-08-28", "value": 0.72},
    {"date": "2020-08-31", "value": 0.72},
    {"date": "2020-09-01", "value": 0.68},
]


def load(conn):
    return load_yields(conn, download=lambda series: OBSERVATIONS, now=fixed_clock)


def test_risk_free_rate_uses_the_observation_before_as_of(conn):
    load(conn)
    point = risk_free_rate(conn, date(2020, 9, 1))  # the 09-01 value is published on 09-02
    assert (point.date, point.rate) == (date(2020, 8, 31), pytest.approx(0.0072))
    assert risk_free_rate(conn, date(2020, 8, 30)).date == date(2020, 8, 28)


def test_risk_free_rate_needs_data_fetched_on_or_after_as_of(conn):
    load(conn)
    with pytest.raises(MarketDataError, match="refresh"):
        risk_free_rate(conn, date(2020, 9, 4))
    with pytest.raises(MarketDataError, match="before"):
        risk_free_rate(conn, date(2020, 8, 27))


def test_load_is_cached_until_refresh(conn):
    first = load(conn)
    assert load(conn) == first
    second = load_yields(conn, refresh=True, download=lambda s: OBSERVATIONS[:2], now=fixed_clock)
    assert second != first
    # both downloads are kept; queries read the latest unless a fetch is pinned
    assert conn.execute("SELECT COUNT(*) FROM yields").fetchone()[0] == 6
    assert risk_free_rate(conn, date(2020, 9, 1)).date == date(2020, 8, 28)
    with pin_fetches({("fred", "DGS10"): first}):
        assert risk_free_rate(conn, date(2020, 9, 1)).date == date(2020, 8, 31)


class FakeResponse:
    text = "observation_date,DGS10\n2020-08-28,0.72\n2020-09-07,\n2020-09-08,0.70\n"

    def raise_for_status(self):
        pass


def test_fred_csv_parsing_skips_missing_days(monkeypatch):
    monkeypatch.setattr(yields.requests, "get", lambda url, timeout: FakeResponse())
    assert fred_download("DGS10") == [
        {"date": "2020-08-28", "value": 0.72},
        {"date": "2020-09-08", "value": 0.70},
    ]
    with pytest.raises(MarketDataError, match="header"):
        fred_download("DGS30")
