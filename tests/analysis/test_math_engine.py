from datetime import date

import pytest

from domains.analysis import dcf
from domains.analysis.math_engine import (
    EngineError,
    build_inputs,
    fallback_backtest,
    load_user_assumptions,
    post_checks,
)
from domains.market.erp import equity_risk_premium
from tests.analysis.conftest import AS_OF, CHOICES, revenue


def build(conn, as_of=AS_OF):
    return build_inputs(conn, "TST", as_of, choices=CHOICES, today=AS_OF)


def by_key(result):
    return {(a.name, a.period): a for a in result.assumptions}


def test_drivers_follow_the_documented_rules(company):
    result = build(company)
    rows = by_key(result)
    assert sorted(p for n, p in rows if n == dcf.SEED) == [
        "FY2019Q2",
        "FY2019Q3",
        "FY2019Q4",
        "FY2020Q1",
    ]
    assert rows[(dcf.SEED, "FY2019Q4")].value == pytest.approx(revenue(2019, 4))
    # growth: 10% in every 10-K, fading to terminal growth (= risk-free 3%) by year 5
    assert rows[("revenue_growth", "FY2020Q2")].value == pytest.approx(0.10)
    assert rows[("revenue_growth", "FY2021Q2")].value == pytest.approx(0.10 - 0.07 / 4)
    assert rows[("revenue_growth", "Y3")].value == pytest.approx(0.065)
    assert rows[("revenue_growth", "Y5")].value == pytest.approx(0.03)
    assert rows[("operating_margin", "FY2020Q2")].value == pytest.approx(0.20)
    assert rows[("tax_rate", "Y4")].value == pytest.approx(0.25)
    assert rows[("da_pct", "Y4")].value == pytest.approx(0.05)
    assert rows[("capex_pct", "Y4")].value == pytest.approx(0.06)
    # working capital (300 − 60) − (150 − 20) = 110 at each year-end, over that year's revenue
    expected = sum(110 / (400 * 1.1 ** (y - 2015)) for y in (2017, 2018, 2019)) / 3
    assert rows[("nwc_pct", "Y4")].value == pytest.approx(expected)


def test_cost_of_capital_inputs(company):
    rows = by_key(build(company))
    assert rows[("risk_free", "-")].value == pytest.approx(0.03)
    assert rows[("terminal_growth", "-")].value == pytest.approx(0.03)
    assert rows[("beta", "-")].value == pytest.approx(2 / 3 * 1.5 + 1 / 3)  # Blume of 1.5
    erp = equity_risk_premium(company, AS_OF, 1989)
    assert rows[("erp", "-")].value == pytest.approx(erp.premium.geometric)
    assert rows[("erp_std_error", "-")].value == pytest.approx(erp.premium.std_error)
    assert rows[("cost_of_debt", "-")].value == pytest.approx(8 / 200)
    assert rows[("equity_market_value", "-")].value == pytest.approx(
        rows[("price", "-")].value * 100
    )


def test_net_debt_shares_and_roll_forward(company):
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 200
    assert rows[("cash_and_investments", "-")].value == 60
    assert rows[("minority_interest", "-")].value == 5
    assert rows[("shares", "-")].value == 100
    assert rows[("roll_years", "-")].value == pytest.approx(91 / 365.25)


def test_every_reported_input_names_its_tag_and_filing(company):
    for a in build(company).assumptions:
        if a.name.startswith("balance:") or a.name == dcf.SEED:
            assert "[" in a.method and "0000000123-" in a.method, a


def test_missing_components_are_zero_with_one_warning(company):
    result = build(company)
    zero = [w for w in result.warnings if w.startswith("Counted as zero")]
    assert len(zero) == 1 and "commercial_paper" in zero[0]


def test_a_baseline_can_be_valued_from_its_rows(company):
    valuation = dcf.value(build(company).assumptions)
    assert valuation.value_per_share > 0
    assert valuation.lines["revenue"][0] == pytest.approx(revenue(2019, 2) * 1.1)


def drop(tags):
    return lambda tag, row: None if tag in tags else row


def test_ebit_falls_back_to_pretax_plus_interest_only_when_missing(company, make_company):
    primary = by_key(build(company))[("history:ebit", "FY2019")]
    assert not primary.method.startswith("fallback")
    conn = make_company(drop({"OperatingIncomeLoss"}))
    fallback = by_key(build(conn))[("history:ebit", "FY2019")]
    assert fallback.method.startswith("fallback: pretax_income + interest_expense")
    assert fallback.value == pytest.approx(primary.value)  # pretax + interest = operating income


def test_an_item_and_its_fallback_both_missing_fails_naming_both(make_company):
    conn = make_company(drop({"OperatingIncomeLoss", "InterestExpense"}))
    with pytest.raises(EngineError, match="ebit for .*operating_income.*pretax_income"):
        build(conn)


def test_a_required_balance_item_missing_fails(make_company):
    conn = make_company(drop({"CashAndCashEquivalentsAtCarryingValue"}))
    with pytest.raises(EngineError, match="cash"):
        build(conn)


def insert_fact(conn, tag, value):
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', ?, NULL, "
        "'2020-03-31', 2020, 'Q1', ?, 'USD', '10-Q', '0000000123-20-000016', '2020-04-30')",
        (tag, value),
    )


def test_securities_above_current_assets_break_the_invariant(company):
    conn = company
    insert_fact(conn, "us-gaap:MarketableSecuritiesCurrent", 400)
    with pytest.raises(EngineError, match="exceed current assets"):
        build(conn)


def test_finance_leases_inside_the_debt_tag_are_not_counted_twice(company):
    conn = company
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = 'us-gaap:LongTermDebtAndCapitalLeaseObligations'"
        " WHERE xbrl_concept = 'us-gaap:LongTermDebtNoncurrent'"
    )
    insert_fact(conn, "us-gaap:FinanceLeaseLiability", 30)
    result = build(conn)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 200
    assert "finance leases skipped" in rows[("debt", "-")].method


def test_restated_year_seeds_quarters_with_the_year_times_their_share(make_company):
    def restate(tag, row):
        # the FY2019 10-K reports FY2019 revenue 10% higher (a restatement) ...
        if tag == "Revenues" and row["form"] == "10-K" and row["end"] == "2019-12-31":
            return {**row, "val": row["val"] * 1.1}
        return row

    conn = make_company(restate)
    # ... and its nine months on the new basis, while Q1-Q3 stay as first reported
    nine_months = 1.1 * sum(revenue(2019, q) for q in (1, 2, 3))
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', "
        "'us-gaap:Revenues', '2019-01-01', '2019-09-30', 2019, 'M9', ?, 'USD', '10-K', "
        "'0000000123-20-000015', '2020-02-15')",
        (nine_months,),
    )
    rows = by_key(build(conn))
    seed = rows[(dcf.SEED, "FY2019Q2")]
    year = 1.1 * sum(revenue(2019, q) for q in (1, 2, 3, 4))
    quarters = sum(revenue(2019, q) for q in (1, 2, 3)) + 1.1 * revenue(2019, 4)  # Q4 = FY − M9
    assert seed.value == pytest.approx(year * revenue(2019, 2) / quarters)
    assert "differ from the year" in seed.method
    # FY2020 Q1 is in a year without a full-year figure yet: as reported
    assert rows[(dcf.SEED, "FY2020Q1")].value == pytest.approx(revenue(2020, 1))


def test_as_of_outside_the_supported_range(company):
    with pytest.raises(EngineError, match="as-of date"):
        build(company, date(2019, 2, 28))
    with pytest.raises(EngineError, match="as-of date"):
        build(company, date(2020, 7, 1))


def test_user_assumptions_must_be_complete_and_valid(tmp_path):
    path = tmp_path / "user.csv"
    header = "name,value,set_by,set_on,note\n"
    path.write_text(header + "erp_method,historical_geometric,owner,2026-10-26,x\n")
    with pytest.raises(EngineError, match="has not set"):
        load_user_assumptions(path)
    path.write_text(header + "erp_method,arithmetic,owner,2026-10-26,x\n")
    with pytest.raises(EngineError, match="must be one of"):
        load_user_assumptions(path)
    path.write_text(header + "erp_first_year,1989,,2026-10-26,x\n")
    with pytest.raises(EngineError, match="set_by"):
        load_user_assumptions(path)


def test_the_shipped_user_assumptions_load():
    choices = load_user_assumptions()
    assert choices["erp_first_year"].value == "1989"


def test_fallback_backtest_compares_where_both_exist(company):
    checks = {(c.chain, c.fallback): c for c in fallback_backtest(company, AS_OF)}
    ebit = checks[("ebit", "pretax_income + interest_expense")]
    assert len(ebit.gaps) >= 3 and ebit.median == pytest.approx(0.0)
    assert not ebit.flagged
    assert checks[("interest", "interest_paid")].gaps == []


def test_shares_are_adjusted_only_for_splits_after_their_basis(company):
    # a 2:1 split on 2020-04-17: after the Q1 quarter end (03-31) but before the 10-Q filing
    # (04-30), whose share counts are therefore already restated, and before the cover date
    company.execute(
        "UPDATE prices SET split_ratio = 2 WHERE ticker = 'TST' AND date = '2020-04-17'"
    )
    result = build(company)
    assert by_key(result)[("shares", "-")].value == 100
    assert not any("differ from diluted" in w for w in result.warnings)


def wobbled(rows):
    """Test Corp's rows with reported quarterly margins of 19% and 21% in turn (sd about 1%)."""
    out, n = [], 0
    for a in rows:
        if a.name == "history:ebit" and "Q" in a.period:
            n += 1
            revenue_row = next(
                r for r in rows if (r.name, r.period) == ("history:revenue", a.period)
            )
            a = a.model_copy(update={"value": revenue_row.value * (0.19 if n % 2 else 0.21)})
        out.append(a)
    return out


def test_margin_check_reads_the_rows_so_shocked_drivers_pass_through_it(company):
    rows = wobbled(build(company).assumptions)
    assert not [w for w in post_checks(rows, dcf.run_outputs(rows)) if "margin" in w]
    # a shock that lifts one forecast quarter's margin to 30%, far outside 20% ± 2 × 1%
    period = sorted(a.period for a in rows if a.name == "operating_margin")[0]
    shocked = [
        a.model_copy(update={"value": 0.30})
        if (a.name, a.period) == ("operating_margin", period)
        else a
        for a in rows
    ]
    warnings = [w for w in post_checks(shocked, dcf.run_outputs(shocked)) if "margin" in w]
    assert len(warnings) == 1 and f"30.0% in {period}" in warnings[0]


def test_spread_warning_fires_below_three_points(company):
    rows = build(company).assumptions
    wacc = dcf.run_outputs(rows)[("wacc", "-")]
    for spread, fires in ((0.031, False), (0.029, True)):
        shifted = dcf.with_value(rows, "terminal_growth", wacc - spread)
        warnings = [w for w in post_checks(shifted, dcf.run_outputs(shifted)) if "WACC" in w]
        assert bool(warnings) is fires
    assert "2.90 points" in warnings[0] and "of enterprise value" in warnings[0]
