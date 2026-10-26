"""Bookkeeping shared by the market-data adapters: one market_fetches row per download."""

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any


class MarketDataError(RuntimeError):
    """Market data is missing, unusable, or older than the date a query asks about."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_sha256(rows: list[Any]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def record_fetch(
    conn: sqlite3.Connection, source: str, symbol: str, rows: list[dict], fetched_at: datetime
) -> int:
    """Insert the market_fetches row for a download (inside the caller's transaction)."""
    dates = [r["date"] for r in rows]
    cursor = conn.execute(
        "INSERT INTO market_fetches (source, symbol, fetched_at, first_date, last_date, "
        "row_count, content_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            source,
            symbol,
            fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            min(dates),
            max(dates),
            len(rows),
            content_sha256(rows),
        ),
    )
    return cursor.lastrowid


def latest_fetch(conn: sqlite3.Connection, source: str, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM market_fetches WHERE source = ? AND symbol = ? "
        "ORDER BY fetch_id DESC LIMIT 1",
        (source, symbol),
    ).fetchone()


def require_coverage(
    conn: sqlite3.Connection, source: str, symbol: str, as_of: date
) -> sqlite3.Row:
    """The fetch a query on `as_of` reads from; it must have been downloaded on or after as_of."""
    fetch = latest_fetch(conn, source, symbol)
    if fetch is None:
        raise MarketDataError(f"No {source} data for {symbol}: load it first")
    fetched_on = date.fromisoformat(fetch["fetched_at"][:10])
    if fetched_on < as_of:
        raise MarketDataError(
            f"{source} data for {symbol} was fetched {fetched_on}, before the as-of date "
            f"{as_of}: refresh it"
        )
    return fetch


def year_end_values(
    conn: sqlite3.Connection, sql: str, key: str, first_year: int, last_year: int, what: str
) -> dict[int, float]:
    """The last value of each calendar year first_year..last_year from (date, value) rows.

    Each year must end with an observation in its last week, so a year-end is never taken from a
    gap or from a partial year.
    """
    values: dict[int, tuple[str, float]] = {}
    for day, value in conn.execute(sql, (key, f"{first_year}-01-01", f"{last_year}-12-31")):
        values[int(day[:4])] = (day, value)
    out = {}
    for year in range(first_year, last_year + 1):
        if year not in values or values[year][0] < f"{year}-12-24":
            raise MarketDataError(f"{what}: no observation in the last week of {year}")
        out[year] = values[year][1]
    return out
