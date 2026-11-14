"""A run that can't be built says why as a code with params (backlog #376)."""

import ast
from datetime import date
from pathlib import Path

import pytest

from domains.analysis import coded
from domains.analysis.coded import (
    ENGINE_REFUSAL_CODES,
    REFUSAL_GROUP_ORDER,
    REFUSAL_GROUPS,
    SIMULATION_REFUSAL_CODES,
    Coded,
    refusal,
)
from domains.analysis.math_engine import EngineError, UserChoice, build_inputs, where_params
from domains.analysis.montecarlo import SimulationError
from domains.market.prices import MARKET_INDEX
from domains.market.store import MarketDataError
from tests.analysis.conftest import AS_OF, CHOICES

REPO = Path(__file__).resolve().parents[2]
SCANNED = (
    "domains/analysis/math_engine.py",
    "domains/market/store.py",
    "domains/market/prices.py",
    "domains/market/yields.py",
    "domains/market/erp.py",
)
# Raises a student can't reach by picking a company and a date, so they stay text only.
TEXT_ONLY = {
    ("domains/analysis/math_engine.py", "from_assumption"): "the owner's assumptions file",
    ("domains/analysis/math_engine.py", "load_user_assumptions"): "the owner's assumptions file",
    ("domains/analysis/math_engine.py", "_put"): "a sources guard: a programming error",
    ("domains/market/store.py", "selected_fetch"): "a pinned download (reproduce)",
    ("domains/market/store.py", "fetch_with_hash"): "a stored run's download (reproduce)",
    ("domains/market/prices.py", "yahoo_download"): "a download, run by an operator",
    ("domains/market/prices.py", "load_prices"): "a download, run by an operator",
    ("domains/market/yields.py", "fred_download"): "a download, run by an operator",
    ("domains/market/yields.py", "load_yields"): "a download, run by an operator",
}


def raises(path: str):
    """(function, code or None) for each `raise EngineError(...)` / `raise MarketDataError(...)`."""
    tree = ast.parse((REPO / path).read_text())
    out = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and getattr(node.exc.func, "id", None) in ("EngineError", "MarketDataError")
            ):
                code = next((k.value for k in node.exc.keywords if k.arg == "code"), None)
                out.append((func.name, code))
    return out


def literal_codes(code) -> set[str]:
    """The string literals a `code=` expression can give (a plain string or an if-else)."""
    if code is None:
        return set()
    return {n.value for n in ast.walk(code) if isinstance(n, ast.Constant)}


def test_every_raise_a_run_can_reach_carries_a_code_or_is_named_text_only():
    uncoded = [
        (path, name)
        for path in SCANNED
        for name, code in raises(path)
        if code is None and (path, name) not in TEXT_ONLY
    ]
    assert uncoded == []
    # and the text-only list names only functions that still raise without a code
    still = {(p, n) for p in SCANNED for n, code in raises(p) if code is None}
    assert set(TEXT_ONLY) <= still


def test_every_catalogued_code_is_raised_and_every_raised_code_is_catalogued():
    used = set()
    for path in SCANNED:
        for _name, code in raises(path):
            used |= literal_codes(code)
    assert used == ENGINE_REFUSAL_CODES


def test_every_code_has_a_group_in_the_screen_order():
    assert set(REFUSAL_GROUPS) == ENGINE_REFUSAL_CODES
    assert set(REFUSAL_GROUPS.values()) == set(REFUSAL_GROUP_ORDER)
    assert not ENGINE_REFUSAL_CODES & SIMULATION_REFUSAL_CODES


# -- the exceptions --------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [EngineError, MarketDataError])
def test_a_plain_refusal_is_text_only(cls):
    e = cls("something broke")
    assert e.code is None and e.params == {} and e.coded() is None and refusal(e) is None
    assert str(e) == "something broke"


@pytest.mark.parametrize("cls", [EngineError, MarketDataError])
def test_an_uncatalogued_code_is_refused(cls):
    with pytest.raises(AssertionError):
        cls("text", code="not_a_code")


def test_refusal_reads_any_coded_exception():
    engine = EngineError("e", code="no_share_count", params={"ticker": "TST"})
    market = MarketDataError("m", code="no_price_on_date", params={"ticker": "TST"})
    sim = SimulationError("s", code="wacc_set_with_risk_premium_shock", params={"wacc": 0.1})
    for e in (engine, market, sim):
        assert refusal(e) == e.coded() == Coded(e.code, e.params, str(e))
    assert refusal(ValueError("plain")) is None
    assert coded.refusal(KeyError("x")) is None


def test_where_params_split_the_period():
    assert where_params("FY2019") == {"fiscal_year": 2019, "quarter": None}
    assert where_params("FY2019 Q3") == {"fiscal_year": 2019, "quarter": 3}


# -- each refusal on Test Corp ---------------------------------------------------------------


def build(conn, as_of=AS_OF, ticker="TST", choices=CHOICES, today=AS_OF):
    return build_inputs(conn, ticker, as_of, choices=choices, today=today)


def refused(conn, cls=EngineError, **kw):
    with pytest.raises(cls) as caught:
        build(conn, **kw)
    e = caught.value
    assert e.code in ENGINE_REFUSAL_CODES and e.text == str(e)
    return e


def drop_where(pred):
    def edit(tag, row):
        return None if pred(tag, row) else row

    return edit


def test_a_date_before_the_first_supported_day(company):
    e = refused(company, as_of=date(2019, 2, 28))
    assert e.code == "as_of_too_early"
    assert e.params == {"as_of": "2019-02-28", "supported_from": "2019-03-01"}
    assert str(e) == "as-of date must be from 2019-03-01 to 2020-06-30, got 2019-02-28"


def test_a_date_after_today(company):
    e = refused(company, as_of=date(2020, 7, 1))
    assert e.code == "as_of_in_future"
    assert e.params == {"as_of": "2020-07-01", "today": "2020-06-30"}


def test_a_company_not_ingested(company):
    e = refused(company, ticker="zzz")
    assert (e.code, e.params, str(e)) == (
        "company_not_ingested",
        {"ticker": "ZZZ"},
        "zzz has not been ingested",
    )


def test_a_day_whose_download_was_made_before_it_ended(company):
    # the market data was fetched 2020-07-01 12:00 UTC, while that day was still going in New York
    e = refused(company, MarketDataError, as_of=date(2020, 7, 1), today=date(2020, 7, 1))
    assert e.code == "market_data_not_refreshed"
    assert e.params["as_of"] == "2020-07-01" and e.params["covered_through"] == "2020-06-30"
    assert e.params["source"] in ("yahoo", "fred") and "refresh it" in str(e)


def test_no_price_on_or_before_the_date(company):
    company.execute("DELETE FROM prices WHERE ticker = 'TST'")
    e = refused(company, MarketDataError)
    assert (e.code, e.params) == ("no_price_on_date", {"ticker": "TST", "as_of": "2020-06-30"})
    assert str(e) == "No price for TST on or before 2020-06-30"


def test_market_data_never_loaded(company):
    company.execute("DELETE FROM prices WHERE ticker = 'TST'")
    company.execute("DELETE FROM market_fetches WHERE symbol = 'TST'")
    e = refused(company, MarketDataError)
    assert (e.code, e.params) == ("market_data_not_loaded", {"source": "yahoo", "symbol": "TST"})


def test_too_few_weeks_of_returns_for_the_beta(company):
    company.execute("DELETE FROM prices WHERE ticker = 'TST' AND date < '2019-06-01'")
    e = refused(company, MarketDataError)
    assert e.code == "too_few_return_weeks"
    assert e.params["needed"] == 104 and 0 < e.params["found"] < 104


def test_too_few_years_for_the_risk_premium(company):
    choices = {**CHOICES, "erp_first_year": UserChoice("erp_first_year", "2015", "t", "x", "")}
    e = refused(company, MarketDataError, choices=choices)
    assert e.code == "erp_too_few_years"
    assert e.params == {
        "as_of": "2020-06-30",
        "first_year": 2015,
        "last_year": 2019,
        "min_years": 10,
    }


def test_no_risk_free_rate_before_the_date(company):
    company.execute("DELETE FROM yields")
    e = refused(company, MarketDataError)
    assert (e.code, e.params) == (
        "no_risk_free_rate",
        {"series": "DGS10", "as_of": "2020-06-30"},
    )


def test_a_missing_year_end_for_the_risk_premium(company):
    company.execute(
        "DELETE FROM prices WHERE ticker = ? AND date BETWEEN '2000-12-20' AND '2000-12-31'",
        (MARKET_INDEX,),
    )
    e = refused(company, MarketDataError)
    assert e.code == "market_year_end_missing" and e.params["year"] == 2000


def test_no_share_count_at_all(company):
    company.execute(
        "DELETE FROM financial_facts WHERE xbrl_concept IN "
        "('dei:EntityCommonStockSharesOutstanding', "
        "'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding')"
    )
    e = refused(company)
    assert (e.code, e.params) == ("no_share_count", {"ticker": "TST", "reason": "none_reported"})


def test_no_share_count_above_zero_names_the_counts_left_out(company):
    company.execute(
        "UPDATE financial_facts SET value = 0 WHERE xbrl_concept IN "
        "('dei:EntityCommonStockSharesOutstanding', "
        "'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding')"
    )
    e = refused(company)
    assert e.code == "no_share_count" and e.params["reason"] == "none_above_zero"
    assert e.params["skipped"] and all(s["value"] == 0 for s in e.params["skipped"])
    assert str(e) == "TST: no share count above zero reported"


@pytest.mark.parametrize(
    ("pred", "code", "params"),
    [
        (
            lambda t, r: t == "Revenues" and r["fp"] != "FY",
            "no_quarterly_revenue",
            {"ticker": "TST", "as_of": "2020-06-30"},
        ),
        (
            lambda t, r: t == "Revenues" and r["fp"] == "Q2" and r["fy"] == 2019,
            "seed_quarter_not_reported",
            {"ticker": "TST", "fiscal_year": 2019, "quarter": 2},
        ),
        (
            lambda t, r: r["form"] == "10-K" and r["fy"] in (2016, 2017),
            "too_few_comparatives",
            {"ticker": "TST", "needed": 3, "found": 2},
        ),
        (
            lambda t, r: t == "InterestExpense",
            "no_interest_with_debt",
            {"ticker": "TST", "fiscal_years": [2017, 2018, 2019]},
        ),
        (
            lambda t, r: t == "CashAndCashEquivalentsAtCarryingValue",
            "balance_item_not_reported",
            {"item": "cash", "fiscal_year": 2017, "quarter": None},
        ),
        (
            lambda t, r: t in ("OperatingIncomeLoss", "InterestExpense"),
            "flow_item_not_reported",
            None,
        ),
    ],
)
def test_a_figure_the_filings_lack(make_company, pred, code, params):
    e = refused(make_company(drop_where(pred)))
    assert e.code == code
    if params is not None:
        assert e.params == params
    else:
        assert e.params["item"] == "ebit" and e.params["quarter"] is None
        assert ["operating_income"] in e.params["tried"]


def test_a_negative_balance_item(company):
    company.execute(
        "UPDATE financial_facts SET value = -180 "
        "WHERE xbrl_concept = 'us-gaap:LongTermDebtNoncurrent'"
    )
    e = refused(company)
    assert e.code == "balance_item_negative"
    assert e.params == {
        "ticker": "TST",
        "item": "debt_noncurrent",
        "period_end": "2020-03-31",
        "value": -180,
        "currency": "USD",
    }


def insert_securities(conn, value):
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', "
        "'us-gaap:MarketableSecuritiesCurrent', NULL, '2020-03-31', 2020, 'Q1', ?, 'USD', "
        "'10-Q', '0000000123-20-000016', '2020-04-30')",
        (value,),
    )


@pytest.mark.parametrize(("value", "with_cash", "total"), [(400, False, 400), (250, True, 310)])
def test_securities_above_current_assets(company, value, with_cash, total):
    insert_securities(company, value)
    e = refused(company)
    assert e.code == "securities_exceed_current_assets"
    assert e.params == {
        "ticker": "TST",
        "period_end": "2020-03-31",
        "with_cash": with_cash,
        "securities": total,
        "current_assets": 300,
        "currency": "USD",
    }
