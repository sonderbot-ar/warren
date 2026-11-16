"""Which as-of dates the stored market downloads can serve for a run (backlog #381).

A run reads three series: the company's prices, the market index and the risk-free yield. Each
download covers up to the last New York day that had ended when it was made, and a run can be
built on a date only if all three cover it, so the newest such date is the earliest of the three.
"""

import sqlite3
from datetime import date

from domains.market.prices import MARKET_INDEX
from domains.market.store import covered_through, selected_fetch
from domains.market.yields import RISK_FREE_SERIES

# (source, symbol) of every series a run reads; None stands for the company's own ticker
RUN_SERIES = (("yahoo", None), ("yahoo", MARKET_INDEX), ("fred", RISK_FREE_SERIES))


def run_series(ticker: str) -> list[tuple[str, str]]:
    """The (source, symbol) pairs a run of `ticker` reads."""
    return [(source, symbol or ticker.upper()) for source, symbol in RUN_SERIES]


def run_covered_through(conn: sqlite3.Connection, ticker: str) -> date | None:
    """The newest as-of date every series a run of `ticker` reads can serve, or None when one of
    them was never downloaded. Uses the downloads a query reads now (pins included)."""
    days = []
    for source, symbol in run_series(ticker):
        fetch = selected_fetch(conn, source, symbol)
        if fetch is None:
            return None
        days.append(covered_through(fetch))
    return min(days)
