"""Daily prices from Yahoo Finance (yfinance), stored in the prices table.

Yahoo serves closes adjusted for every split up to the download date, so an old close is on
today's share basis, not the one of its own date. The stored split ratios undo that:
raw_close() puts a close back on the basis of its own date, and split_factor() moves a share
count from one date's basis to another's. Returns for beta come from the dividend-adjusted close:
later adjustments rescale all earlier prices by the same factor, so returns don't change.

All downloads go through one function (yahoo_download), so the provider can be swapped there.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from domains.market.store import (
    MarketDataError,
    record_fetch,
    require_coverage,
    utc_now,
    year_end_values,
)

HISTORY_START = date(2010, 1, 1)
# S&P 500 Total Return (dividends reinvested): the market for beta (D6) and the equity leg of the
# equity risk premium (D7). Total returns on both sides, as stock returns come from adj_close.
MARKET_INDEX = "^SP500TR"
MARKET_INDEX_HISTORY_START = date(1988, 1, 1)  # the first Yahoo serves for ^SP500TR

Downloader = Callable[[str, date], list[dict]]


def yahoo_download(ticker: str, start: date) -> list[dict]:
    """Daily history from `start` to today: date, close, adj_close, volume, split_ratio."""
    import yfinance as yf  # imported here so tests and other commands don't need the network stack

    history = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=False, actions=True)
    if history.empty:
        raise MarketDataError(f"Yahoo Finance returned no prices for {ticker}")
    return [
        {
            "date": ts.date().isoformat(),
            "close": float(row["Close"]),
            "adj_close": float(row["Adj Close"]),
            "volume": int(row["Volume"]),
            "split_ratio": float(row["Stock Splits"]) or None,
        }
        for ts, row in history.iterrows()
    ]


def load_prices(
    conn: sqlite3.Connection,
    ticker: str,
    refresh: bool = False,
    download: Downloader = yahoo_download,
    now: Callable[[], datetime] = utc_now,
    start: date = HISTORY_START,
) -> int:
    """Download a ticker's history unless it is stored already; returns the fetch id in use."""
    if not refresh:
        row = conn.execute(
            "SELECT fetch_id FROM prices WHERE ticker = ? LIMIT 1", (ticker,)
        ).fetchone()
        if row is not None:
            return row["fetch_id"]
    fetched_at = now()
    # a row dated on the download day may be a mid-session price, not a close: keep earlier days
    today = fetched_at.date().isoformat()
    rows = [r for r in download(ticker, start) if r["date"] < today]
    if not rows:
        raise MarketDataError(f"No prices downloaded for {ticker}")
    with conn:
        fetch_id = record_fetch(conn, "yahoo", ticker, rows, fetched_at)
        conn.execute("DELETE FROM prices WHERE ticker = ?", (ticker,))
        conn.executemany(
            "INSERT INTO prices (ticker, date, close, adj_close, volume, split_ratio, fetch_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    ticker,
                    r["date"],
                    r["close"],
                    r["adj_close"],
                    r["volume"],
                    r["split_ratio"],
                    fetch_id,
                )
                for r in rows
            ],
        )
    return fetch_id


@dataclass(frozen=True)
class PricePoint:
    ticker: str
    date: date  # the trading day the close is from (on or before the as-of date)
    close: float  # on the share basis of that day
    fetch_id: int


def split_factor(conn: sqlite3.Connection, ticker: str, after: date, through: date) -> float:
    """Product of the split ratios taking effect after `after`, up to and including `through`.

    A share count dated `after` times this factor is on the basis of `through` (e.g. ×4 across
    AAPL's 2020-08-31 split).
    """
    factor = 1.0
    for (ratio,) in conn.execute(
        "SELECT split_ratio FROM prices WHERE ticker = ? AND split_ratio IS NOT NULL "
        "AND date > ? AND date <= ?",
        (ticker, after.isoformat(), through.isoformat()),
    ):
        factor *= ratio
    return factor


def raw_close(conn: sqlite3.Connection, ticker: str, as_of: date) -> PricePoint:
    """The last close on or before as_of, on that day's share basis (as it traded)."""
    fetch = require_coverage(conn, "yahoo", ticker, as_of)
    row = conn.execute(
        "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (ticker, as_of.isoformat()),
    ).fetchone()
    if row is None:
        raise MarketDataError(f"No price for {ticker} on or before {as_of}")
    day = date.fromisoformat(row["date"])
    # undo the splits Yahoo applied after that day (up to the download)
    later = split_factor(conn, ticker, day, date.fromisoformat(fetch["last_date"]))
    return PricePoint(ticker, day, row["close"] * later, fetch["fetch_id"])


def weekly_returns(conn: sqlite3.Connection, ticker: str, as_of: date, weeks: int) -> pd.Series:
    """The last `weeks` weekly total returns up to as_of, indexed by week (ending Friday)."""
    require_coverage(conn, "yahoo", ticker, as_of)
    start = as_of - timedelta(weeks=weeks + 2)
    rows = conn.execute(
        "SELECT date, adj_close FROM prices WHERE ticker = ? AND date > ? AND date <= ? "
        "ORDER BY date",
        (ticker, start.isoformat(), as_of.isoformat()),
    ).fetchall()
    closes = pd.Series(
        [r["adj_close"] for r in rows], index=pd.to_datetime([r["date"] for r in rows])
    )
    returns = closes.resample("W-FRI").last().pct_change().dropna()
    return returns.iloc[-weeks:]


@dataclass(frozen=True)
class ReturnPairs:
    stock: list[float]
    market: list[float]
    first_week: date
    last_week: date


def aligned_weekly_returns(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date,
    weeks: int,
    market: str = MARKET_INDEX,
) -> ReturnPairs:
    """Weekly returns of a stock and the market over the same weeks, for a beta regression."""
    joined = pd.concat(
        [weekly_returns(conn, ticker, as_of, weeks), weekly_returns(conn, market, as_of, weeks)],
        axis=1,
        join="inner",
    )
    if len(joined) < weeks:
        raise MarketDataError(
            f"{ticker}: only {len(joined)} weeks of returns before {as_of}, {weeks} needed"
        )
    return ReturnPairs(
        stock=joined.iloc[:, 0].tolist(),
        market=joined.iloc[:, 1].tolist(),
        first_week=joined.index[0].date(),
        last_week=joined.index[-1].date(),
    )


def annual_total_returns(
    conn: sqlite3.Connection, ticker: str, first_year: int, last_year: int
) -> dict[int, float]:
    """Calendar-year total returns (from adj_close, year-end to year-end) for each year."""
    require_coverage(conn, "yahoo", ticker, date(last_year, 12, 31))
    closes = year_end_values(
        conn,
        "SELECT date, adj_close FROM prices WHERE ticker = ? AND date >= ? AND date <= ? "
        "ORDER BY date",
        ticker,
        first_year - 1,
        last_year,
        ticker,
    )
    return {y: closes[y] / closes[y - 1] - 1 for y in range(first_year, last_year + 1)}
