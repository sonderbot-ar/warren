"""A run that can't be built says why as a code with params (backlog #376)."""

import ast
from datetime import date
from pathlib import Path

import pytest

from domains.analysis import coded, math_engine
from domains.analysis.coded import (
    ENGINE_REFUSAL_CODES,
    FILING_REFUSAL_CODES,
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
from tests.analysis.conftest import AS_OF, CHOICES, revenue

REPO = Path(__file__).resolve().parents[2]
TST_10Q_2020Q1 = "0000000123-20-000016"


def filing(accession_no: str, form: str, filed_at: str) -> dict:
    """A refusal's filing (backlog #509): the #140 shape, with the EDGAR folder of the test CIK."""
    url = f"https://www.sec.gov/Archives/edgar/data/123/{accession_no.replace('-', '')}/"
    return {"accession_no": accession_no, "form": form, "filed_at": filed_at, "url": url}


SCANNED = (
    "domains/analysis/math_engine.py",
    "domains/market/store.py",
    "domains/market/prices.py",
    "domains/market/yields.py",
    "domains/market/erp.py",
    "domains/analysis/runs.py",
)
# Raises a student can't reach by picking a company and a date, so they stay text only.
TEXT_ONLY = {
    ("domains/analysis/math_engine.py", "from_assumption"): "the owner's assumptions file",
    ("domains/analysis/math_engine.py", "load_user_assumptions"): "the owner's assumptions file",
    ("domains/analysis/math_engine.py", "_put"): "a sources guard: a programming error",
    ("domains/analysis/runs.py", "stored_choices"): "a stored run's choices (rebuild)",
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
    with pytest.raises(RuntimeError, match="unknown engine refusal code"):  # backlog #519
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
    for bad in ("2019", "FY2019 Q5", "FY2019Q3"):  # a RuntimeError, kept by python -O (#522)
        with pytest.raises(RuntimeError, match="unreadable refusal period"):
            where_params(bad)


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
    assert e.params["all_covered_through"] == "2020-06-30"


@pytest.mark.parametrize("symbol", ["TST", MARKET_INDEX, "DGS10"])
def test_a_refused_date_names_one_date_all_three_series_serve(company, symbol):
    # one series was downloaded on Jun 20, the other two on Jul 1 (backlog #381)
    company.execute(
        "UPDATE market_fetches SET fetched_at = '2020-06-20T12:00:00Z' WHERE symbol = ?", (symbol,)
    )
    e = refused(company, MarketDataError, as_of=date(2020, 6, 25), today=AS_OF)
    assert e.code == "market_data_not_refreshed"
    assert e.params["all_covered_through"] == "2020-06-19"
    assert str(e).endswith("refresh it")  # the English is unchanged
    # the date offered passes every download check
    result = build(company, as_of=date(2020, 6, 19))
    assert result.as_of == date(2020, 6, 19)


def test_no_common_date_when_a_series_was_never_loaded(company):
    company.execute("UPDATE market_fetches SET fetched_at = '2020-06-20T12:00:00Z'")
    company.execute("DELETE FROM yields")
    company.execute("DELETE FROM market_fetches WHERE symbol = 'DGS10'")
    e = refused(company, MarketDataError, as_of=date(2020, 6, 25), today=AS_OF)
    assert e.code == "market_data_not_refreshed" and e.params["all_covered_through"] is None


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
        "first_as_of": "2025-01-08",
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
    assert (e.code, e.params) == (
        "no_share_count",
        {"ticker": "TST", "reason": "none_reported", "filings": []},
    )


def test_no_share_count_above_zero_names_the_counts_left_out(company):
    company.execute(
        "UPDATE financial_facts SET value = 0 WHERE xbrl_concept IN "
        "('dei:EntityCommonStockSharesOutstanding', "
        "'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding')"
    )
    e = refused(company)
    assert e.code == "no_share_count" and e.params["reason"] == "none_above_zero"
    assert e.params["skipped"] and all(s["value"] == 0 for s in e.params["skipped"])
    # each skipped count's filing once, joined to the count by `accession_no` (#509)
    accessions = list(dict.fromkeys(s["accession_no"] for s in e.params["skipped"]))
    assert [f["accession_no"] for f in e.params["filings"]] == accessions
    assert all(f["form"] and f["filed_at"] and f["url"] for f in e.params["filings"])
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
            # the newest balance sheet for FY2017 Warren read: the FY2018 10-K's comparative (#509)
            {
                "item": "cash",
                "fiscal_year": 2017,
                "quarter": None,
                "filings": [filing("0000000123-19-000011", "10-K", "2019-02-15")],
            },
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
        # FY2017's newest income statement Warren read: the FY2019 10-K's three years (#509)
        assert e.params["filings"] == [filing("0000000123-20-000015", "10-K", "2020-02-15")]


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
        "filings": [filing(TST_10Q_2020Q1, "10-Q", "2020-04-30")],
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
        # current assets, the securities (and cash) all come from the Q1 2020 10-Q (#509)
        "filings": [filing(TST_10Q_2020Q1, "10-Q", "2020-04-30")],
    }


@pytest.mark.parametrize("reason", ["growth_not_below_rate", "rate_not_positive"])
def test_a_base_case_without_a_value_is_refused_with_a_code(company, monkeypatch, reason):
    from domains.analysis import dcf, runs
    from domains.analysis.financial_math import FinancialMathError

    def no_value(rows):
        raise FinancialMathError("terminal growth 0.05 must be below the rate 0.04", reason)

    monkeypatch.setattr(dcf, "outputs_and_gaps", no_value)
    with pytest.raises(EngineError) as caught:
        runs.run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    e = caught.value
    assert e.code == "no_base_value"
    assert e.params == {"ticker": "TST", "as_of": "2020-06-30", "reason": reason}
    assert isinstance(e.__cause__, FinancialMathError)
    assert company.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_a_bad_argument_in_the_valuation_is_not_dressed_as_a_refusal(company, monkeypatch):
    from domains.analysis import dcf, runs
    from domains.analysis.financial_math import FinancialMathError

    def bad(rows):
        raise FinancialMathError("bad argument")  # invalid_input: a programming error

    monkeypatch.setattr(dcf, "outputs_and_gaps", bad)
    with pytest.raises(FinancialMathError):
        runs.run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)


# -- a zero divisor in the forecast ratios (backlog #383) ------------------------------------


def zero_where(pred):
    def edit(tag, row):
        return {**row, "val": 0} if pred(tag, row) else row

    return edit


def test_a_zero_quarterly_revenue_is_refused_with_a_code(make_company):
    # FY2018 Q3 as its own 10-Q files it and as the comparative in the FY2019 Q3 10-Q
    e = refused(
        make_company(
            zero_where(
                lambda t, r: t == "Revenues" and r["fp"] == "Q3" and r["end"] == "2018-09-30"
            )
        )
    )
    assert (e.code, e.params) == (
        "zero_divisor",
        {
            "ticker": "TST",
            "ratio": "operating_margin",
            "divisor": "revenue",
            "period": "FY2018Q3",
            "period_kind": "quarter",
            # the figure as the FY2019 Q3 10-Q compares it, the newest filing of it (#381)
            "period_end": "2018-09-30",
            "accession_no": "0000000123-19-000014",
            "inputs": [],
            "filings": [filing("0000000123-19-000014", "10-Q", "2019-10-30")],
        },
    )
    assert str(e) == "TST: revenue is zero in FY2018Q3, so operating_margin can't be computed"
    assert REFUSAL_GROUPS[e.code] == "company_data"


def test_a_zero_pretax_sum_is_no_longer_refused(make_company):
    # #383 refused it with zero_divisor; since #385 the run takes the statutory tax rate
    # (tests/analysis/test_statutory_tax.py has the note's params)
    pretax = "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
    conn = make_company(zero_where(lambda t, r: t.startswith(pretax) and r["fp"] == "FY"))
    result = build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    assert "tax_rate_statutory" in [n.code for n in result.notes]


def test_no_statutory_rate_for_the_country_is_a_setup_refusal(make_company, monkeypatch):
    # backlog #395: unreachable in Phase 1 (every company is US), so the country is patched
    monkeypatch.setattr(math_engine, "TAX_JURISDICTION", "MX")
    pretax = "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
    conn = make_company(zero_where(lambda t, r: t.startswith(pretax) and r["fp"] == "FY"))
    e = refused(conn)
    assert e.code == "no_statutory_rate"
    assert e.params == {"jurisdiction": "MX", "as_of": AS_OF.isoformat()}
    assert str(e) == (
        f"no statutory tax rate for 'MX' on {AS_OF}; the run's three-year pretax income is at "
        "or below 1% of revenue, so it needs the statutory rate"
    )
    assert REFUSAL_GROUPS[e.code] == "setup"


@pytest.mark.parametrize(
    ("year", "ratio", "accession", "filed_at"),
    [
        # the prior year of the FY2018 10-K's comparative
        (2017, "revenue_growth", "0000000123-19-000011", "2019-02-15"),
        # a seed year whose quarters are checked against it
        (2019, "revenue_seed", "0000000123-20-000015", "2020-02-15"),
    ],
)
def test_a_zero_annual_revenue_is_refused_with_a_code(
    make_company, year, ratio, accession, filed_at
):
    e = refused(
        make_company(
            zero_where(
                lambda t, r: t == "Revenues" and r["fp"] == "FY" and r["end"] == f"{year}-12-31"
            )
        )
    )
    assert (e.code, e.params) == (
        "zero_divisor",
        {
            "ticker": "TST",
            "ratio": ratio,
            "divisor": "revenue",
            "period": f"FY{year}",
            "period_kind": "year",
            "period_end": f"{year}-12-31",
            # FY2017 as the FY2018 10-K compares it; FY2019 from its own 10-K (#381)
            "accession_no": accession,
            "inputs": [],
            "filings": [filing(accession, "10-K", filed_at)],
        },
    )


class _Result:
    ticker = "TST"


def test_ratio_divides_or_refuses_a_zero_divisor():
    from domains.analysis.math_engine import _ratio

    args = ("da_pct", "revenue", "FY2017-FY2019", "years_sum")
    assert _ratio(_Result(), 3.0, 7.0, *args) == 3.0 / 7.0
    assert _ratio(_Result(), -3.0, 7.0, *args) == -3.0 / 7.0
    for divisor in (0, 0.0, -0.0):
        with pytest.raises(EngineError) as caught:
            _ratio(_Result(), 1.0, divisor, "revenue_seed", "revenue", "FY2018", "quarters_sum")
        assert caught.value.code == "zero_divisor"
        assert caught.value.params["period_kind"] == "quarters_sum"


def test_zero_divisor_params_come_from_closed_sets():
    from domains.analysis.math_engine import _nonzero

    for bad, match in (
        (
            ("gross_margin", "revenue", "FY2018", "year"),
            "unknown zero_divisor ratio 'gross_margin'",
        ),
        (("tax_rate", "ebit", "FY2018", "year"), "unknown zero_divisor item 'ebit'"),
        (("tax_rate", "pretax", "FY2018", "decade"), "unknown zero_divisor period kind 'decade'"),
        ((None, "pretax", "FY2018", "years_sum"), "unknown zero_divisor ratio None"),
    ):
        # a RuntimeError, not an assert, so python -O keeps it (backlog #522)
        with pytest.raises(RuntimeError, match=match):
            _nonzero(_Result(), 1.0, *bad)


def test_a_zero_derived_quarter_names_the_filings_it_comes_from(make_company):
    # FY2018 revenue filed equal to its first three quarters, so Q4 (the year less Q1-Q3) is zero
    nine_months = sum(revenue(2018, q) for q in (1, 2, 3))

    def edit(tag, row):
        if tag == "Revenues" and row["fp"] == "FY" and row["end"] == "2018-12-31":
            return {**row, "val": nine_months}
        return row

    e = refused(make_company(edit))
    assert e.code == "zero_divisor"
    assert {k: e.params[k] for k in ("ratio", "period", "period_kind", "period_end")} == {
        "ratio": "operating_margin",
        "period": "FY2018Q4",
        "period_kind": "quarter",
        "period_end": "2018-12-31",
    }
    assert e.params["accession_no"] is None  # Warren derived it: no one filing shows the zero
    # the FY2019 10-K's comparative year less the three quarters as the 2019 10-Qs compare them
    assert e.params["inputs"] == [
        "0000000123-20-000015",
        "0000000123-19-000012",
        "0000000123-19-000013",
        "0000000123-19-000014",
    ]
    # each input's filing, in the order of `inputs` (#509)
    assert e.params["filings"] == [
        filing("0000000123-20-000015", "10-K", "2020-02-15"),
        filing("0000000123-19-000012", "10-Q", "2019-04-30"),
        filing("0000000123-19-000013", "10-Q", "2019-07-30"),
        filing("0000000123-19-000014", "10-Q", "2019-10-30"),
    ]


def test_one_quarter_or_year_needs_its_fact_and_a_sum_takes_none():
    from domains.analysis.math_engine import _nonzero

    with pytest.raises(RuntimeError, match="'year' with fact=False"):
        _nonzero(_Result(), 0.0, "nwc_pct", "revenue", "FY2018", "year")
    with pytest.raises(RuntimeError, match="'quarter' with fact=False"):
        _nonzero(_Result(), 0.0, "nwc_pct", "revenue", "FY2018", "quarter")
    with pytest.raises(RuntimeError, match="'years_sum' with fact=True"):
        _nonzero(_Result(), 0.0, "nwc_pct", "revenue", "FY2018", "years_sum", object())


# -- refusals that name a filing carry its link (backlog #509) ---------------------------------


def test_the_filing_codes_are_engine_codes():
    assert FILING_REFUSAL_CODES <= ENGINE_REFUSAL_CODES


def test_only_the_filing_codes_carry_filings_and_they_survive_json(make_company, company):
    import json

    dropped = make_company(
        drop_where(lambda t, r: t in ("OperatingIncomeLoss", "InterestExpense"))
    )  # flow_item_not_reported
    negative = make_company(None)
    negative.execute(
        "UPDATE financial_facts SET value = -180 "
        "WHERE xbrl_concept = 'us-gaap:LongTermDebtNoncurrent'"
    )  # balance_item_negative
    company.execute("DELETE FROM prices WHERE ticker = 'TST'")  # no_price_on_date
    cases = [
        (dropped, {}),
        (negative, {}),
        (company, {}),
        (make_company(None), {"as_of": date(2019, 2, 28)}),  # as_of_too_early
    ]
    for conn, kw in cases:
        e = refused(conn, (EngineError, MarketDataError), **kw)
        assert ("filings" in e.params) == (e.code in FILING_REFUSAL_CODES), e.code
        assert json.loads(json.dumps(e.params)) == e.params


def test_a_quarter_missing_its_line_names_the_newest_10q_for_that_quarter(make_company):
    # FY2019 Q1's operating income and interest dropped from the FY2019 Q1 10-Q and from its
    # comparative in the FY2020 Q1 10-Q (#513): the quarter branch of `period_accessions`
    e = refused(
        make_company(
            drop_where(
                lambda t, r: (
                    t in ("OperatingIncomeLoss", "InterestExpense") and r["end"] == "2019-03-31"
                )
            )
        )
    )
    assert e.code == "flow_item_not_reported"
    assert (e.params["item"], e.params["fiscal_year"], e.params["quarter"]) == ("ebit", 2019, 1)
    # the newest filing that reported the quarter's flows, not the original 10-Q of 2019-04-30
    assert e.params["filings"] == [filing(TST_10Q_2020Q1, "10-Q", "2020-04-30")]


def test_a_refusal_carries_the_runs_cik_outside_its_params(make_company):
    conn = make_company(drop_where(lambda t, r: t == "CashAndCashEquivalentsAtCarryingValue"))
    e = refused(conn)
    assert e.cik == "0000000123" and "cik" not in e.params  # internal, like accessions (#513)


def test_filings_without_a_cik_are_a_programming_error(company):
    from domains.analysis.math_engine import refusal_filings

    assert refusal_filings(company, None, []) == []
    with pytest.raises(RuntimeError):
        refusal_filings(company, None, [TST_10Q_2020Q1])


def test_a_missing_line_never_names_a_filing_made_after_the_date(make_company):
    conn = make_company(drop_where(lambda t, r: t == "CashAndCashEquivalentsAtCarryingValue"))
    # an amended FY2018 10-K, filed after the run's date, that gives FY2017's balance sheet
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', "
        "'us-gaap:AssetsCurrent', NULL, '2017-12-31', 2017, 'FY', 300, 'USD', '10-K/A', "
        "'0000000123-20-000099', ?)",
        ("2020-08-01",),
    )
    e = refused(conn)
    assert e.code == "balance_item_not_reported"
    assert [f["accession_no"] for f in e.params["filings"]] == ["0000000123-19-000011"]


def test_a_period_with_no_reported_fact_lists_no_filing():
    from domains.analysis.math_engine import History, period_accessions

    empty = History(quarterly={}, annual={}, instants={})
    params = {"item": "cash", "fiscal_year": 2017, "quarter": None}
    assert period_accessions(empty, "balance_item_not_reported", params) == []
    params = {"item": "cash", "period_end": "2020-03-31"}
    assert period_accessions(empty, "balance_item_not_reported", params) == []


def test_the_balance_step_called_directly_keeps_its_params(company):
    # the input charts read `_balance`'s refusal params into a note: no `filings` there (#509)
    from domains.analysis.math_engine import EngineResult, _balance, load_history

    company.execute(
        "UPDATE financial_facts SET value = -180 "
        "WHERE xbrl_concept = 'us-gaap:LongTermDebtNoncurrent'"
    )
    history = load_history(company, "0000000123", AS_OF)
    with pytest.raises(EngineError) as caught:
        _balance(history, date(2020, 3, 31), EngineResult("TST", "0000000123", AS_OF))
    assert "filings" not in caught.value.params
    assert caught.value.accessions == [TST_10Q_2020Q1]
