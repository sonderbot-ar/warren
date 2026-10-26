from datetime import date

from domains.fundamentals.facts import get_facts
from tests.fundamentals.conftest import TEST_CIK

K1 = "0000000123-25-000001"  # FY2024 10-K, filed 2025-02-15
A3 = "0000000123-24-000030"  # Q3 2024 10-Q, filed 2024-11-01


def quarters(conn, name, as_of, fiscal_year=2024, mode="latest"):
    facts = get_facts(conn, TEST_CIK, [name], as_of, mode, frequency="quarterly")
    return {f.fiscal_period: f for f in facts if f.fiscal_year == fiscal_year}


def test_q4_is_fy_minus_nine_months(ingested):
    conn, _ = ingested
    q = quarters(conn, "revenue", "2025-03-01")
    assert {p: f.value for p, f in q.items()} == {"Q1": 100, "Q2": 110, "Q3": 120, "Q4": 130}
    q4 = q["Q4"]
    assert q4.derived and not q["Q3"].derived
    assert (q4.period_start, q4.period_end) == (date(2024, 10, 1), date(2024, 12, 31))
    assert q4.inputs == [K1, A3]


def test_derived_value_is_public_only_when_its_last_input_is(ingested):
    conn, _ = ingested
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].filed_at == date(2025, 2, 15)
    # nine months were public in November, but the full year wasn't: no Q4 yet
    assert "Q4" not in quarters(conn, "revenue", "2025-02-14")


def test_ytd_only_cash_flow_items_become_standalone_quarters(ingested):
    conn, _ = ingested
    q = quarters(conn, "capex", "2025-03-01")
    assert {p: f.value for p, f in q.items()} == {"Q1": 10, "Q2": 12, "Q3": 11, "Q4": 12}
    assert [p for p, f in q.items() if f.derived] == ["Q2", "Q3", "Q4"]
    assert q["Q2"].filed_at == date(2024, 8, 1)


def test_restated_full_year_flows_into_q4_and_is_flagged_as_mixed_vintage(ingested):
    conn, _ = ingested
    q4 = quarters(conn, "revenue", "2026-03-01")["Q4"]
    assert q4.value == 455 - 330
    assert q4.restated and q4.mixed_vintage


def test_first_reported_q4_uses_first_reported_inputs(ingested):
    conn, _ = ingested
    q4 = quarters(conn, "revenue", "2026-03-01", mode="first_reported")["Q4"]
    assert q4.value == 130
    assert not q4.mixed_vintage


def test_q4_falls_back_to_fy_minus_three_quarters_without_nine_months(ingested):
    conn, _ = ingested
    conn.execute("DELETE FROM financial_facts WHERE fiscal_period = 'M9'")
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert q4.value == 460 - 100 - 110 - 120


def test_balance_sheet_quarters_are_reported_values_with_q4_from_year_end(ingested):
    conn, _ = ingested
    q = quarters(conn, "cash", "2025-03-01")
    assert {p: f.value for p, f in q.items()} == {"Q1": 50, "Q2": 55, "Q3": 60, "Q4": 70}
    assert not any(f.derived for f in q.values())


def test_weighted_average_shares_are_never_derived(ingested):
    conn, _ = ingested
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES "
        "(?, 'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding', '2024-01-01', "
        "'2024-09-30', 2024, 'M9', 10, 'shares', '10-Q', ?, '2024-11-01'), "
        "(?, 'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding', '2024-01-01', "
        "'2024-12-31', 2024, 'FY', 11, 'shares', '10-K', ?, '2025-02-15')",
        (TEST_CIK, A3, TEST_CIK, K1),
    )
    assert "Q4" not in quarters(conn, "diluted_shares", "2025-03-01")


def test_one_value_per_period_when_two_dates_share_a_label(ingested):
    conn, _ = ingested
    # the 10-K cover and a later 10-K/A cover both carry FY2024 shares outstanding
    for end, value, accession, filed in [
        ("2025-02-01", 990, K1, "2025-02-15"),
        ("2025-03-10", 985, "0000000123-25-000077", "2025-03-20"),
    ]:
        conn.execute(
            "INSERT INTO financial_facts (cik, xbrl_concept, period_end, fiscal_year, "
            "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, "
            "'dei:EntityCommonStockSharesOutstanding', ?, 2024, 'FY', ?, 'shares', '10-K', ?, ?)",
            (TEST_CIK, end, value, accession, filed),
        )
    q = quarters(conn, "shares_outstanding", "2025-04-01")
    assert (q["Q4"].value, q["Q4"].period_end) == (985, date(2025, 3, 10))
    annual = get_facts(conn, TEST_CIK, ["shares_outstanding"], "2025-04-01", frequency="annual")
    assert [f.value for f in annual] == [985]


def test_annual_returns_fiscal_years_only(ingested):
    conn, _ = ingested
    facts = get_facts(conn, TEST_CIK, ["revenue", "cash"], "2025-03-01", frequency="annual")
    assert {f.fiscal_period for f in facts} == {"FY"}
    assert {(f.canonical_name, f.fiscal_year) for f in facts} == {
        ("revenue", 2022),
        ("revenue", 2023),
        ("revenue", 2024),
        ("cash", 2022),
        ("cash", 2023),
        ("cash", 2024),
    }
