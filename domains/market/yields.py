"""Treasury yields from FRED (Federal Reserve Bank of St. Louis), stored in the yields table.

DGS10 is the 10-year constant-maturity Treasury yield from the Fed's H.15 release, the risk-free
rate for the cost of equity (owner decision D5). FRED's CSV download needs no API key. H.15 is
published the next business day, so a query on `as_of` uses the latest observation dated before it.
"""

import csv
import io
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import requests

from domains.market.store import MarketDataError, record_fetch, require_coverage, utc_now

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
RISK_FREE_SERIES = "DGS10"
TIMEOUT_SECONDS = 30

Downloader = Callable[[str], list[dict]]


def fred_download(series: str) -> list[dict]:
    """Every observation of a FRED series: date and value (missing days, shown as '.', skipped)."""
    response = requests.get(FRED_CSV_URL.format(series=series), timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    if header[-1] != series:
        raise MarketDataError(f"Unexpected FRED CSV header for {series}: {header}")
    return [{"date": day, "value": float(value)} for day, value in reader if value not in ("", ".")]


def load_yields(
    conn: sqlite3.Connection,
    series: str = RISK_FREE_SERIES,
    refresh: bool = False,
    download: Downloader = fred_download,
    now: Callable[[], datetime] = utc_now,
) -> int:
    """Download a series unless it is stored already; returns the fetch id in use."""
    if not refresh:
        row = conn.execute(
            "SELECT fetch_id FROM yields WHERE series = ? LIMIT 1", (series,)
        ).fetchone()
        if row is not None:
            return row["fetch_id"]
    rows = download(series)
    if not rows:
        raise MarketDataError(f"No observations downloaded for {series}")
    with conn:
        fetch_id = record_fetch(conn, "fred", series, rows, now())
        conn.execute("DELETE FROM yields WHERE series = ?", (series,))
        conn.executemany(
            "INSERT INTO yields (series, date, value, fetch_id) VALUES (?, ?, ?, ?)",
            [(series, r["date"], r["value"], fetch_id) for r in rows],
        )
    return fetch_id


@dataclass(frozen=True)
class YieldPoint:
    series: str
    date: date  # the observation used (the latest before the as-of date)
    rate: float  # decimal (0.0425 = 4.25%)
    fetch_id: int


def risk_free_rate(
    conn: sqlite3.Connection, as_of: date, series: str = RISK_FREE_SERIES
) -> YieldPoint:
    fetch = require_coverage(conn, "fred", series, as_of)
    row = conn.execute(
        "SELECT date, value FROM yields WHERE series = ? AND date < ? ORDER BY date DESC LIMIT 1",
        (series, as_of.isoformat()),
    ).fetchone()
    if row is None:
        raise MarketDataError(f"No {series} observation before {as_of}")
    return YieldPoint(
        series, date.fromisoformat(row["date"]), row["value"] / 100, fetch["fetch_id"]
    )
