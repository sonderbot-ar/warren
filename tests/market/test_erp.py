from datetime import date

import pytest

from domains.market.erp import equity_risk_premium, last_complete_year
from domains.market.prices import MARKET_INDEX, annual_total_returns, load_prices
from domains.market.store import MarketDataError
from domains.market.yields import annual_bond_returns, load_yields
from tests.market.conftest import fixed_clock

YEARS = range(1999, 2013)  # year-ends 1999-2012: returns for 2000-2012


def price_rows(years=YEARS):
    # the index gains 10% every year
    return [
        {
            "date": f"{y}-12-31",
            "close": 100 * 1.1 ** (y - 1999),
            "adj_close": 100 * 1.1 ** (y - 1999),
            "volume": 0,
            "split_ratio": None,
        }
        for y in years
    ]


def load(conn, prices=None, yield_pct=5.0):
    rows = price_rows() if prices is None else prices
    load_prices(conn, MARKET_INDEX, download=lambda t, s: rows, now=fixed_clock)
    # a flat 5% yield: the bond returns its 5% coupon every year
    load_yields(
        conn,
        download=lambda s: [{"date": f"{y}-12-31", "value": yield_pct} for y in YEARS],
        now=fixed_clock,
    )


def test_last_complete_year_waits_for_the_year_end_to_be_published():
    assert last_complete_year(date(2019, 6, 30)) == 2018
    assert last_complete_year(date(2020, 1, 3)) == 2018
    assert last_complete_year(date(2020, 1, 8)) == 2019


def test_annual_returns_of_both_legs(conn):
    load(conn)
    assert annual_total_returns(conn, MARKET_INDEX, 2000, 2002) == pytest.approx(
        {2000: 0.10, 2001: 0.10, 2002: 0.10}
    )
    assert annual_bond_returns(conn, 2000, 2001) == pytest.approx({2000: 0.05, 2001: 0.05})


def test_equity_risk_premium_over_the_expanding_window(conn):
    load(conn)
    estimate = equity_risk_premium(conn, date(2013, 6, 30), first_year=2000)
    assert (estimate.first_year, estimate.last_year) == (2000, 2012)
    # 10% stocks vs 5% bonds every year: a 5% premium, no spread across years
    assert estimate.premium.geometric == pytest.approx(0.05)
    assert estimate.premium.arithmetic == pytest.approx(0.05)
    assert estimate.premium.std_error == pytest.approx(0.0, abs=1e-12)
    assert estimate.premium.years == 13
    assert len(estimate.price_fetch_sha256) == len(estimate.yield_fetch_sha256) == 64


def test_equity_risk_premium_needs_ten_years(conn):
    load(conn)
    with pytest.raises(MarketDataError, match="fewer than 10 years"):
        equity_risk_premium(conn, date(2013, 6, 30), first_year=2004)


def test_a_year_without_a_year_end_observation_is_an_error(conn):
    prices = [r for r in price_rows() if r["date"] != "2005-12-31"]
    prices.append({**price_rows([2005])[0], "date": "2005-06-30"})
    load(conn, prices=prices)
    with pytest.raises(MarketDataError, match="last week of 2005"):
        equity_risk_premium(conn, date(2013, 6, 30), first_year=2000)


def test_equity_risk_premium_needs_data_fetched_after_the_last_year(conn):
    load(conn)  # fetched 2020-09-03, so the 2020 year-end isn't in it
    with pytest.raises(MarketDataError, match="refresh"):
        equity_risk_premium(conn, date(2021, 3, 1), first_year=2000)
