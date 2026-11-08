from datetime import date

import pytest

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


def test_first_reported_q4_is_the_version_public_first(ingested):
    conn, _ = ingested
    # the next 10-K reports Q4 2024 on its own, recast (as JNJ's FY2023 10-K did after Kenvue)
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, 'us-gaap:Revenues', "
        "'2024-10-01', '2024-12-31', 2024, 'Q4', 99, 'USD', '10-K', '0000000123-26-000001', "
        "'2026-02-15')",
        (TEST_CIK,),
    )
    first = quarters(conn, "revenue", "2026-03-01", mode="first_reported")["Q4"]
    assert (first.value, first.derived, first.filed_at) == (130, True, date(2025, 2, 15))
    assert quarters(conn, "revenue", "2026-03-01")["Q4"].value == 99  # latest: the recast


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


# -- one basis (backlog #264) -----------------------------------------------------------------

B3 = "0000000123-25-000030"  # Q3 2025 10-Q, filed 2025-11-01: recasts the 2024 nine months


def recast_nine_months(conn, value=300):
    """The next Q3 10-Q gives last year's nine months on a new basis (as JNJ's Q3 2023 10-Q did
    after Kenvue), while the year itself is still only in the old-basis 10-K."""
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, 'us-gaap:Revenues', "
        "'2024-01-01', '2024-09-30', 2024, 'M9', ?, 'USD', '10-Q', ?, '2025-11-01')",
        (TEST_CIK, value, B3),
    )


def one_basis_quarters(conn, as_of, fiscal_year=2024):
    facts = get_facts(conn, TEST_CIK, ["revenue"], as_of, frequency="quarterly", one_basis=True)
    return {f.fiscal_period: f for f in facts if f.fiscal_year == fiscal_year}


def test_old_year_minus_recast_nine_months_is_on_no_basis_without_one_basis(ingested):
    conn, _ = ingested
    recast_nine_months(conn)
    q4 = quarters(conn, "revenue", "2025-12-01")["Q4"]
    assert q4.value == 460 - 300  # the old year minus the recast nine months
    assert q4.mixed_vintage and not q4.one_basis
    assert q4.inputs == [K1, B3]


def test_one_basis_derives_the_old_year_minus_the_old_nine_months(ingested):
    conn, _ = ingested
    recast_nine_months(conn)
    q4 = one_basis_quarters(conn, "2025-12-01")["Q4"]
    assert (q4.value, q4.derived, q4.one_basis) == (130, True, True)
    assert not q4.restated and not q4.mixed_vintage
    assert q4.inputs == [K1, A3]
    assert q4.filed_at == date(2025, 2, 15)  # public by then: no later input is used


def test_one_basis_also_covers_a_restated_year_with_old_nine_months(ingested):
    conn, _ = ingested
    # the fixture's FY2025 10-K restates FY2024 to 455; the nine months stay as first reported
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    assert (q4.value, q4.one_basis) == (130, True)


def test_one_basis_keeps_a_derivation_whose_inputs_were_all_restated(ingested):
    conn, _ = ingested
    recast_nine_months(conn, value=320)
    # as of 2026-03-01 the year is restated (455) and so are the nine months (320)
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    assert (q4.value, q4.one_basis, q4.mixed_vintage) == (455 - 320, False, False)


def test_one_basis_changes_nothing_on_one_basis(ingested):
    conn, _ = ingested
    plain = get_facts(conn, TEST_CIK, ["revenue", "capex", "cash"], "2025-03-01",
                      frequency="quarterly")  # fmt: skip
    one = get_facts(conn, TEST_CIK, ["revenue", "capex", "cash"], "2025-03-01",
                    frequency="quarterly", one_basis=True)  # fmt: skip
    assert one == plain


def test_one_basis_is_for_latest_quarterly_facts_only(ingested):
    conn, _ = ingested
    for mode, frequency in (("first_reported", "quarterly"), ("latest", "annual")):
        with pytest.raises(ValueError, match="one_basis"):
            get_facts(conn, TEST_CIK, ["revenue"], "2025-03-01", mode, frequency, one_basis=True)


def test_one_basis_pairs_a_twice_restated_year_with_the_nine_months_vintage(ingested):
    conn, _ = ingested
    recast_nine_months(conn, value=320)  # Q3 2025 10-Q
    # the FY2026 10-K restates FY2024 a second time (KO's FY2017 operating income: 7,501 as
    # filed, 7,599 in the next 10-K, 7,755 in the one after; the nine months recast once)
    add_year(conn, 470, "0000000123-27-000001", "2027-02-15")
    plain = quarters(conn, "revenue", "2027-03-01")["Q4"]
    assert (plain.value, plain.restated, plain.mixed_vintage) == (470 - 320, True, False)
    q4 = one_basis_quarters(conn, "2027-03-01")["Q4"]
    # the year as the first 10-K after the recast nine months gave it (455), not the newest
    assert (q4.value, q4.one_basis) == (455 - 320, True)
    assert q4.filed_at == date(2026, 2, 15)


def test_one_basis_keeps_a_quarter_with_no_first_filed_derivation(ingested):
    from domains.fundamentals.facts import _Basis

    conn, _ = ingested
    recast_nine_months(conn)
    q = quarters(conn, "revenue", "2025-12-01")
    nine = get_facts(conn, TEST_CIK, ["revenue"], "2025-12-01")
    year = {f.fiscal_period: f for f in nine if f.fiscal_year == 2024}
    assert _Basis({}, {}).place(q["Q4"], year["FY"], [year["M9"]]) == q["Q4"]


def add_year(conn, value, accession, filed_at):
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, 'us-gaap:Revenues', "
        "'2024-01-01', '2024-12-31', 2024, 'FY', ?, 'USD', '10-K', ?, ?)",
        (TEST_CIK, value, accession, filed_at),
    )


def test_a_repeated_nine_months_keeps_its_first_filing_date(ingested):
    conn, _ = ingested
    # the Q3 2025 10-Q only repeats the old nine months (PG's FY2013 tax, 2,812 in both 10-Qs);
    # the FY2025 10-K then recasts the year (455): pairing with it would mix bases
    recast_nine_months(conn, value=330)
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    assert (q4.value, q4.one_basis) == (460 - 330, True)


def test_a_paired_year_of_the_opposite_sign_is_not_used(ingested):
    conn, _ = ingested
    recast_nine_months(conn, value=320)
    # a 10-K/A tags the year with the wrong sign; the FY2025 10-K corrects it (WMT's FY2009 tax)
    add_year(conn, -455, "0000000123-25-000090", "2025-12-01")
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    assert (q4.value, q4.one_basis) == (130, True)  # every input as first filed
