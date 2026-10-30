"""The equity risk premium, computed from market data (owner decision D7), not assumed.

ERP = E[R_m] − R_f, estimated as the realized premium of the S&P 500 total return (^SP500TR)
over the total return of a 10-year Treasury bond (from DGS10, the same rate CAPM uses as R_f),
in full calendar years from first_year to the last year that ended before as_of (an expanding
window). The owner sets first_year and the method; this module never defaults them.

Known limits (build plan, risks): with ~30-40 years the standard error is ~±3 points, the
estimate is procyclical, and it depends on the first year.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from domains.analysis.financial_math import RiskPremium, historical_premium
from domains.market.prices import MARKET_INDEX, annual_total_returns
from domains.market.store import MarketDataError, selected_fetch
from domains.market.yields import RISK_FREE_SERIES, annual_bond_returns

MIN_YEARS = 10
# A year counts once its year-end yield is published (next business day) with room for holidays.
YEAR_END_LAG = timedelta(days=7)


@dataclass(frozen=True)
class ERPEstimate:
    premium: RiskPremium
    first_year: int
    last_year: int
    price_fetch_sha256: str
    yield_fetch_sha256: str


def last_complete_year(as_of: date) -> int:
    """The last calendar year whose year-end data was public on as_of."""
    year = as_of.year - 1
    return year if as_of >= date(year + 1, 1, 1) + YEAR_END_LAG else year - 1


def equity_risk_premium(conn: sqlite3.Connection, as_of: date, first_year: int) -> ERPEstimate:
    last_year = last_complete_year(as_of)
    if last_year - first_year + 1 < MIN_YEARS:
        raise MarketDataError(
            f"equity risk premium as of {as_of}: {first_year}-{last_year} is fewer than "
            f"{MIN_YEARS} years"
        )
    equity = annual_total_returns(conn, MARKET_INDEX, first_year, last_year)
    bonds = annual_bond_returns(conn, first_year, last_year)
    years = range(first_year, last_year + 1)
    return ERPEstimate(
        premium=historical_premium([equity[y] for y in years], [bonds[y] for y in years]),
        first_year=first_year,
        last_year=last_year,
        price_fetch_sha256=selected_fetch(conn, "yahoo", MARKET_INDEX)["content_sha256"],
        yield_fetch_sha256=selected_fetch(conn, "fred", RISK_FREE_SERIES)["content_sha256"],
    )
