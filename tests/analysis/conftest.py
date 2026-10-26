"""A synthetic company with round numbers, ingested through the real pipeline, plus market data.

Test Corp (TST), calendar fiscal years. Quarterly revenue is 100 × 1.1^(year − 2015) × the
seasonal share (0.9, 1.0, 1.0, 1.1), so every year grows 10%. Operating margin 20%, interest 2 a
quarter, tax 25% of pretax, D&A 5% and capex 6% of revenue. Every balance sheet: current assets
300, cash 60, current liabilities 150, current debt 20, non-current debt 180, minority interest
5; 100 shares. The market index gains steadily with a wobble, TST moves 1.5× the index, and the
10-year yield is a flat 3%. Data runs to 2020-03-31 (the Q1 2020 10-Q, filed 2020-04-30).
"""

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from domains.analysis.math_engine import UserChoice
from domains.fundamentals.ingest import ingest_company
from domains.market.prices import MARKET_INDEX, load_prices
from domains.market.yields import load_yields
from shared_kernel.database import apply_migrations, get_db_connection
from tests.fundamentals.conftest import FakeEdgar

AS_OF = date(2020, 6, 30)
FETCHED = datetime(2020, 7, 1, 12, 0, tzinfo=UTC)
SEASON = (0.9, 1.0, 1.0, 1.1)
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
QUARTER_STARTS = ("01-01", "04-01", "07-01", "10-01")
BALANCE = {
    "AssetsCurrent": 300,
    "CashAndCashEquivalentsAtCarryingValue": 60,
    "LiabilitiesCurrent": 150,
    "LongTermDebtCurrent": 20,
    "LongTermDebtNoncurrent": 180,
    "MinorityInterest": 5,
}
CHOICES = {
    name: UserChoice(name, value, "test", "2026-10-26", "")
    for name, value in (
        ("erp_method", "historical_geometric"),
        ("erp_first_year", "1989"),
        ("terminal_growth_method", "risk_free"),
    )
}


def revenue(year: int, quarter: int) -> float:
    return 100 * 1.1 ** (year - 2015) * SEASON[quarter - 1]


def flows(revenue_value: float, quarters: int) -> dict[str, float]:
    operating = 0.2 * revenue_value
    pretax = operating - 2 * quarters
    return {
        "Revenues": revenue_value,
        "OperatingIncomeLoss": operating,
        "InterestExpense": 2 * quarters,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": pretax,  # noqa: E501
        "IncomeTaxExpenseBenefit": 0.25 * pretax,
        "DepreciationDepletionAndAmortization": 0.05 * revenue_value,
        "PaymentsToAcquirePropertyPlantAndEquipment": 0.06 * revenue_value,
        "WeightedAverageNumberOfDilutedSharesOutstanding": 100,
    }


def companyfacts(edit=None) -> dict:
    """The companyfacts document; `edit(tag, row)` may change a row's value or drop it (None)."""
    facts: dict[str, dict[str, list]] = {}

    def put(tag, value, end, accn, fy, fp, form, filed, start=None):
        unit = "shares" if "Shares" in tag else "USD"
        row = {"end": end, "val": value, "accn": accn, "fy": fy, "fp": fp, "form": form}
        row["filed"] = filed
        if start:
            row["start"] = start
        if edit is not None:
            row = edit(tag, row)
            if row is None:
                return
        facts.setdefault(tag, {}).setdefault(unit, []).append(row)

    filings = [(y, q) for y in range(2016, 2020) for q in (1, 2, 3, 4)] + [(2020, 1)]
    for n, (year, quarter) in enumerate(filings):
        end = f"{year}-{QUARTER_ENDS[quarter - 1]}"
        if quarter < 4:
            accn, form = f"0000000123-{year % 100:02d}-{n:06d}", "10-Q"
            filed = (date.fromisoformat(end) + timedelta(days=30)).isoformat()
            fp = f"Q{quarter}"
            for y in (year, year - 1):  # the quarter and its comparative a year earlier
                start = f"{y}-{QUARTER_STARTS[quarter - 1]}"
                for tag, value in flows(revenue(y, quarter), 1).items():
                    put(tag, value, f"{y}-{QUARTER_ENDS[quarter - 1]}", accn, year, fp, form,
                        filed, start)  # fmt: skip
            balance_dates = (end, f"{year - 1}-12-31")
        else:
            accn, form = f"0000000123-{(year + 1) % 100:02d}-{n:06d}", "10-K"
            filed, fp = f"{year + 1}-02-15", "FY"
            for y in (year, year - 1, year - 2):
                annual = sum(revenue(y, q) for q in (1, 2, 3, 4))
                for tag, value in flows(annual, 4).items():
                    put(tag, value, f"{y}-12-31", accn, year, fp, form, filed, f"{y}-01-01")
            balance_dates = (end, f"{year - 1}-12-31")
        for day in balance_dates:
            for tag, value in BALANCE.items():
                put(tag, value, day, accn, year, fp, form, filed)
        cover = (date.fromisoformat(filed) - timedelta(days=10)).isoformat()
        facts.setdefault("_dei", []).append(
            {"end": cover, "val": 100, "accn": accn, "fy": year, "fp": fp, "form": form,
             "filed": filed}
        )  # fmt: skip
    dei = facts.pop("_dei")
    return {
        "cik": 123,
        "entityName": "Test Corp",
        "facts": {
            "us-gaap": {tag: {"units": units} for tag, units in facts.items()},
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}},
        },
    }


def fridays(start: date, end: date) -> list[date]:
    day = start + timedelta(days=(4 - start.weekday()) % 7)
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(weeks=1)
    return out


def market_rows() -> tuple[list[dict], list[dict]]:
    days = fridays(date(1988, 1, 1), AS_OF)
    index, stock = [100.0], [50.0]
    for t in range(1, len(days)):
        move = 0.0015 + 0.02 * math.sin(t)
        index.append(index[-1] * (1 + move))
        stock.append(stock[-1] * (1 + 1.5 * move))

    def rows(values):
        return [
            {"date": d.isoformat(), "close": v, "adj_close": v, "volume": 1, "split_ratio": None}
            for d, v in zip(days, values, strict=True)
        ]

    return rows(index), rows(stock)


def load_market(conn, stock_ticker="TST"):
    index, stock = market_rows()
    load_prices(conn, MARKET_INDEX, download=lambda t, s: index, now=lambda: FETCHED)
    load_prices(conn, stock_ticker, download=lambda t, s: stock, now=lambda: FETCHED)
    yields = [{"date": d.isoformat(), "value": 3.0} for d in fridays(date(1987, 12, 1), AS_OF)]
    load_yields(conn, download=lambda s: yields, now=lambda: FETCHED)


def make_db(db_path, edit=None):
    """A connection to a fresh database holding Test Corp and the market data."""
    client = FakeEdgar()
    client.facts = companyfacts(edit)
    conn_cm = get_db_connection(db_path)
    conn = conn_cm.__enter__()
    apply_migrations(conn)
    ingest_company(conn, "TST", client=client)
    load_market(conn)
    return conn_cm, conn


@pytest.fixture
def company(db_path):
    conn_cm, conn = make_db(db_path)
    yield conn
    conn_cm.__exit__(None, None, None)


@pytest.fixture
def make_company(tmp_path):
    """Build Test Corp with edited filings: make_company(edit) -> connection."""
    opened = []

    def build(edit):
        conn_cm, conn = make_db(tmp_path / f"edited_{len(opened)}.db", edit)
        opened.append(conn_cm)
        return conn

    yield build
    for conn_cm in opened:
        conn_cm.__exit__(None, None, None)
