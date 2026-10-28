from datetime import date, timedelta

import pytest

from domains.market.prices import (
    aligned_weekly_returns,
    load_prices,
    raw_close,
    split_factor,
    weekly_returns,
)
from domains.market.store import (
    MarketDataError,
    fetch_with_hash,
    pin_fetches,
    selected_fetch,
)
from tests.market.conftest import fixed_clock


def row(day, close, adj=None, split=None):
    return {
        "date": day,
        "close": close,
        "adj_close": adj or close,
        "volume": 1,
        "split_ratio": split,
    }


# AAPL around its 4-for-1 split on 2020-08-31, as Yahoo serves it: closes before the split are
# already divided by 4 (it traded near $500 on 2020-08-28).
AAPL = [
    row("2020-08-27", 125.0),
    row("2020-08-28", 124.8),
    row("2020-08-31", 129.0, split=4.0),
    row("2020-09-01", 134.2),
    row("2020-09-02", 131.4),
]


class FakeYahoo:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def __call__(self, ticker, start):
        self.calls += 1
        return self.rows


def test_load_is_cached_until_refresh(conn):
    fake = FakeYahoo(AAPL)
    first = load_prices(conn, "AAPL", download=fake, now=fixed_clock)
    assert load_prices(conn, "AAPL", download=fake, now=fixed_clock) == first
    assert fake.calls == 1
    fake.rows = AAPL[:-1]
    second = load_prices(conn, "AAPL", refresh=True, download=fake, now=fixed_clock)
    assert second != first
    assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 9  # both kept
    fetch = conn.execute("SELECT * FROM market_fetches WHERE fetch_id = ?", (second,)).fetchone()
    assert (fetch["source"], fetch["row_count"], fetch["last_date"]) == ("yahoo", 4, "2020-09-01")
    assert len(fetch["content_sha256"]) == 64


def test_raw_close_is_on_the_share_basis_of_its_own_day(conn):
    load_prices(conn, "AAPL", download=FakeYahoo(AAPL), now=fixed_clock)
    before = raw_close(conn, "AAPL", date(2020, 8, 28))
    assert (before.date, before.close) == (date(2020, 8, 28), pytest.approx(499.2))
    assert raw_close(conn, "AAPL", date(2020, 8, 31)).close == pytest.approx(129.0)
    # a weekend as-of date takes Friday's close, never a later one
    assert raw_close(conn, "AAPL", date(2020, 8, 30)).date == date(2020, 8, 28)


def test_split_factor_moves_a_share_count_across_the_split(conn):
    load_prices(conn, "AAPL", download=FakeYahoo(AAPL), now=fixed_clock)
    # cover-page shares dated before the split, used on a date after it, are multiplied by 4
    assert split_factor(conn, "AAPL", date(2020, 7, 17), date(2020, 9, 1)) == 4.0
    assert split_factor(conn, "AAPL", date(2020, 7, 17), date(2020, 8, 30)) == 1.0
    assert split_factor(conn, "AAPL", date(2020, 8, 31), date(2020, 9, 1)) == 1.0


def test_queries_after_the_download_date_fail(conn):
    load_prices(conn, "AAPL", download=FakeYahoo(AAPL), now=fixed_clock)
    with pytest.raises(MarketDataError, match="refresh"):
        raw_close(conn, "AAPL", date(2020, 9, 4))
    with pytest.raises(MarketDataError, match="No yahoo data"):
        raw_close(conn, "MSFT", date(2020, 9, 1))


def fridays(n, end=date(2020, 8, 28)):
    return [end - timedelta(weeks=n - 1 - i) for i in range(n)]


def test_aligned_weekly_returns_regress_to_the_known_beta(conn):
    market_moves = [0.01, -0.02, 0.03, 0.0, -0.01, 0.02]
    market, stock = [100.0], [100.0]
    for m in market_moves:
        market.append(market[-1] * (1 + m))
        stock.append(stock[-1] * (1 + 2 * m))
    days = fridays(len(market))
    load_prices(
        conn,
        "^SP500TR",
        download=FakeYahoo([row(d.isoformat(), p) for d, p in zip(days, market, strict=True)]),
        now=fixed_clock,
    )
    load_prices(
        conn,
        "TST",
        download=FakeYahoo([row(d.isoformat(), p) for d, p in zip(days, stock, strict=True)]),
        now=fixed_clock,
    )
    pairs = aligned_weekly_returns(conn, "TST", date(2020, 8, 28), weeks=6)
    assert pairs.market == pytest.approx(market_moves)
    assert pairs.stock == pytest.approx([2 * m for m in market_moves])
    assert pairs.last_week == date(2020, 8, 28)
    with pytest.raises(MarketDataError, match="weeks"):
        aligned_weekly_returns(conn, "TST", date(2020, 8, 28), weeks=10)


def test_weekly_returns_never_use_a_price_after_as_of(conn):
    days = fridays(4)
    load_prices(
        conn,
        "TST",
        download=FakeYahoo([row(d.isoformat(), 100.0 + i) for i, d in enumerate(days)]),
        now=fixed_clock,
    )
    returns = weekly_returns(conn, "TST", date(2020, 8, 27), weeks=3)  # Thursday before last Friday
    assert len(returns) == 2
    assert returns.index[-1].date() == date(2020, 8, 21)


def test_a_row_dated_on_the_download_day_is_dropped(conn):
    # fetched 2020-09-03 12:00 UTC, mid-session in New York: that day's "close" isn't final yet
    load_prices(
        conn, "AAPL", download=FakeYahoo([*AAPL, row("2020-09-03", 120.9)]), now=fixed_clock
    )
    assert raw_close(conn, "AAPL", date(2020, 9, 3)).date == date(2020, 9, 2)


def test_queries_read_the_latest_fetch_unless_one_is_pinned(conn):
    fake = FakeYahoo(AAPL)
    first = load_prices(conn, "AAPL", download=fake, now=fixed_clock)
    # a revised download: every close 1% higher
    fake.rows = [
        {**r, "close": r["close"] * 1.01, "adj_close": r["adj_close"] * 1.01} for r in AAPL
    ]
    second = load_prices(conn, "AAPL", refresh=True, download=fake, now=fixed_clock)
    day = date(2020, 9, 1)
    assert raw_close(conn, "AAPL", day).close == pytest.approx(134.2 * 1.01)
    assert raw_close(conn, "AAPL", day).fetch_id == second
    with pin_fetches({("yahoo", "AAPL"): first}):
        assert raw_close(conn, "AAPL", day).close == pytest.approx(134.2)
        assert selected_fetch(conn, "yahoo", "AAPL")["fetch_id"] == first
        assert split_factor(conn, "AAPL", date(2020, 7, 17), day) == 4.0
    assert selected_fetch(conn, "yahoo", "AAPL")["fetch_id"] == second  # the pin is gone


def test_a_fetch_is_found_by_its_content_hash(conn):
    first = load_prices(conn, "AAPL", download=FakeYahoo(AAPL), now=fixed_clock)
    sha = selected_fetch(conn, "yahoo", "AAPL")["content_sha256"]
    load_prices(conn, "AAPL", refresh=True, download=FakeYahoo(AAPL[:-1]), now=fixed_clock)
    assert fetch_with_hash(conn, "yahoo", "AAPL", sha)["fetch_id"] == first
    with pytest.raises(MarketDataError, match="No kept"):
        fetch_with_hash(conn, "yahoo", "AAPL", "0" * 64)


def test_a_pin_must_name_a_download_of_that_symbol(conn):
    first = load_prices(conn, "AAPL", download=FakeYahoo(AAPL), now=fixed_clock)
    load_prices(conn, "MSFT", download=FakeYahoo(AAPL), now=fixed_clock)
    with pin_fetches({("yahoo", "MSFT"): first}), pytest.raises(MarketDataError, match="Pinned"):
        raw_close(conn, "MSFT", date(2020, 9, 1))
