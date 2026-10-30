"""Bookkeeping shared by the market-data adapters: one market_fetches row per download.

Every download is kept (migration 0006). Queries read a symbol's latest fetch, unless the caller
pins fetches with pin_fetches(): rebuilding a stored run pins the downloads it was built from,
so later refreshes don't change what it sees.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

ROWS_TABLE = {"yahoo": ("prices", "ticker"), "fred": ("yields", "series")}

# (source, symbol) -> fetch_id, set only inside pin_fetches()
_pins: ContextVar[Mapping[tuple[str, str], int]] = ContextVar(
    "market_fetch_pins", default=MappingProxyType({})
)


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


@contextmanager
def pin_fetches(pins: Mapping[tuple[str, str], int]) -> Iterator[None]:
    """Inside the block, queries on a pinned (source, symbol) read that fetch, not the latest."""
    token = _pins.set({**_pins.get(), **pins})
    try:
        yield
    finally:
        _pins.reset(token)


def selected_fetch(conn: sqlite3.Connection, source: str, symbol: str) -> sqlite3.Row | None:
    """The fetch queries read: the pinned one if there is a pin, else the latest."""
    pinned = _pins.get().get((source, symbol))
    if pinned is None:
        return latest_fetch(conn, source, symbol)
    fetch = conn.execute(
        "SELECT * FROM market_fetches WHERE fetch_id = ? AND source = ? AND symbol = ?",
        (pinned, source, symbol),
    ).fetchone()
    if fetch is None:
        raise MarketDataError(f"Pinned fetch {pinned} is not a {source} download of {symbol}")
    return fetch


def fetch_with_hash(conn: sqlite3.Connection, source: str, symbol: str, sha256: str) -> sqlite3.Row:
    """The newest kept download of a symbol with this content hash (to rebuild a stored run)."""
    table, key = ROWS_TABLE[source]
    fetch = conn.execute(
        "SELECT * FROM market_fetches f WHERE source = ? AND symbol = ? AND content_sha256 = ? "
        f"AND EXISTS (SELECT 1 FROM {table} r WHERE r.{key} = f.symbol "
        "AND r.fetch_id = f.fetch_id) ORDER BY fetch_id DESC LIMIT 1",
        (source, symbol, sha256),
    ).fetchone()
    if fetch is None:
        raise MarketDataError(
            f"No kept {source} download of {symbol} with hash {sha256[:12]}: it was replaced "
            "before downloads were kept (migration 0006)"
        )
    return fetch


def require_coverage(
    conn: sqlite3.Connection, source: str, symbol: str, as_of: date
) -> sqlite3.Row:
    """The fetch a query on `as_of` reads from; it must have been downloaded on or after as_of."""
    fetch = selected_fetch(conn, source, symbol)
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
    conn: sqlite3.Connection,
    sql: str,
    keys: tuple,
    first_year: int,
    last_year: int,
    what: str,
) -> dict[int, float]:
    """The last value of each calendar year first_year..last_year from (date, value) rows.

    `sql` takes `keys`, then the first and last date. Each year must end with an observation in
    its last week, so a year-end is never taken from a gap or from a partial year.
    """
    values: dict[int, tuple[str, float]] = {}
    for day, value in conn.execute(sql, (*keys, f"{first_year}-01-01", f"{last_year}-12-31")):
        values[int(day[:4])] = (day, value)
    out = {}
    for year in range(first_year, last_year + 1):
        if year not in values or values[year][0] < f"{year}-12-24":
            raise MarketDataError(f"{what}: no observation in the last week of {year}")
        out[year] = values[year][1]
    return out
