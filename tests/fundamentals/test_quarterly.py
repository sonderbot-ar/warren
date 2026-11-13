from datetime import date

import pytest

from domains.fundamentals.facts import get_facts
from domains.fundamentals.schemas import OwnTagCheck
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
    # skipped: the corrected year (455) pairs with the recast nine months, as the plain one does
    assert (q4.value, q4.one_basis) == (455 - 320, False)


def test_a_year_first_filed_with_the_wrong_sign_pairs_with_the_corrected_one(ingested):
    conn, _ = ingested
    # WMT's FY2010 tax: −7,579 in the first 10-K, 7,579 later; the nine months never restated
    conn.execute(
        "UPDATE financial_facts SET value = -value WHERE accession_no = ? AND fiscal_period = 'FY' "
        "AND period_start = '2024-01-01'",
        (K1,),
    )
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    assert (q4.value, q4.one_basis) == (455 - 330, False)  # the corrected year, as plain


def test_no_fallback_to_a_first_filed_year_of_the_wrong_sign(ingested):
    conn, _ = ingested
    conn.execute(
        "UPDATE financial_facts SET value = -value WHERE accession_no = ? AND fiscal_period = 'FY' "
        "AND period_start = '2024-01-01'",
        (K1,),
    )
    add_year(conn, 455, "0000000123-25-000060", "2025-06-01")  # a 10-K/A corrects the sign
    recast_nine_months(conn, value=320)
    q4 = one_basis_quarters(conn, "2025-12-01")["Q4"]  # no 10-K after the recast nine months yet
    assert (q4.value, q4.one_basis) == (455 - 320, False)  # kept as plain: no first-filed fallback


def test_the_method_note_is_true_on_the_pairing_path(ingested):
    from domains.analysis.math_engine import trace

    conn, _ = ingested
    recast_nine_months(conn, value=320)
    add_year(conn, 470, "0000000123-27-000001", "2027-02-15")
    q4 = one_basis_quarters(conn, "2027-03-01")["Q4"]  # rule 2: the year's second version
    text = trace(q4)
    assert "taken on one basis" in text and "first filed" not in text
    assert "0000000123-26-" in text and "0000000123-27-" not in text


def test_a_derived_quarter_uses_the_year_with_the_right_sign(ingested):
    # backlog #280: WMT's FY2008 Q4 tax was -12,319 million, from a year tagged -7,133 in its
    # newest 10-K against 7,145 first filed; the year with the right sign gives the real quarter
    conn, _ = ingested
    add_year(conn, -455, "0000000123-27-000001", "2027-02-15")
    q4 = quarters(conn, "revenue", "2027-03-01")["Q4"]
    assert (q4.value, q4.inputs[0]) == (455 - 330, "0000000123-26-000001")
    # with one basis, the restated year (455) beside the old nine months falls back to the
    # quarter as first filed (#264), as it did before the flipped version came out
    assert one_basis_quarters(conn, "2027-03-01")["Q4"].value == 130


# -- backlog #290: a change of tag is not a change of basis -----------------------------------

CONTRACT = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"  # ranked below Revenues


def tag_switch(conn):
    """Apple's FY2017 D&A: the 10-Qs tag the nine months under one tag; the 10-K gives the year
    under that tag (10,157) and under a higher-ranked one holding another figure (8,200); later
    10-Ks give the higher-ranked tag the full figure (10,157). Here the nine months move to the
    lower tag, the first 10-K adds the year under it (460) and holds 400 under Revenues, and the
    next 10-K gives Revenues 460."""
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = ? WHERE xbrl_concept = 'us-gaap:Revenues' "
        "AND period_start = '2024-01-01' AND fiscal_period = 'M9'",
        (CONTRACT,),
    )
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, ?, '2024-01-01', "
        "'2024-12-31', 2024, 'FY', 460, 'USD', '10-K', ?, '2025-02-15')",
        (TEST_CIK, CONTRACT, K1),
    )
    conn.execute(
        "UPDATE financial_facts SET value = 400 WHERE xbrl_concept = 'us-gaap:Revenues' "
        "AND accession_no = ? AND fiscal_period = 'FY' AND period_start = '2024-01-01'",
        (K1,),
    )
    conn.execute(
        "UPDATE financial_facts SET value = 460 WHERE xbrl_concept = 'us-gaap:Revenues' "
        "AND accession_no != ? AND fiscal_period = 'FY' AND period_start = '2024-01-01'",
        (K1,),
    )


def test_one_basis_reads_a_filing_under_the_nine_months_tag(ingested):
    conn, _ = ingested
    tag_switch(conn)
    plain = quarters(conn, "revenue", "2026-03-01")["Q4"]
    assert (plain.value, plain.restated) == (460 - 330, True)  # Revenues went 400 -> 460
    q4 = one_basis_quarters(conn, "2026-03-01")["Q4"]
    # the first 10-K gives the year as 460 under the nine months' own tag: no change of basis,
    # so the quarter stays the plain one (before #290 it was 400 - 330 = 70, "on one basis")
    assert (q4.value, q4.one_basis) == (460 - 330, False)


# -- backlog #324: a reported quarter under a narrower tag than its year ----------------------

NARROW = "us-gaap:SalesRevenueNet"  # third for revenue, below Revenues


def narrow_quarter(conn, period="Q4", start="2024-10-01", end="2024-12-31", value=125, tag=NARROW):
    """Walmart's 10-Ks of 2011 and 2012: the quarterly note gives Q4 only as net sales, while the
    year and the 10-Qs use total revenues. Here the 10-K gives Q4 2024 as 125 under `tag`."""
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, ?, ?, ?, 2024, ?, ?, "
        "'USD', '10-K', ?, '2025-02-15')",
        (TEST_CIK, tag, start, end, period, value, K1),
    )


@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_a_quarter_under_a_narrower_tag_is_derived_on_the_years_tag(ingested, mode):
    conn, _ = ingested
    narrow_quarter(conn)
    q4 = quarters(conn, "revenue", "2025-03-01", mode=mode)["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (460 - 330, True, NARROW)
    assert q4.xbrl_concept == "us-gaap:Revenues"
    assert q4.inputs == [K1, A3]
    assert sum(f.value for f in quarters(conn, "revenue", "2025-03-01", mode=mode).values()) == 460


def test_one_basis_also_derives_a_narrower_quarter(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    q4 = one_basis_quarters(conn, "2025-03-01")["Q4"]
    assert (q4.value, q4.narrower_tag) == (130, NARROW)


def test_the_reported_view_lists_the_narrow_figure_as_reported(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    reported = get_facts(conn, TEST_CIK, ["revenue"], "2025-03-01")
    assert [f.value for f in reported if f.fiscal_period == "Q4" and f.fiscal_year == 2024] == [125]


def test_a_quarter_on_the_years_tag_is_kept_as_reported(ingested):
    conn, _ = ingested
    narrow_quarter(conn, tag="us-gaap:Revenues")
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)


def test_a_quarter_on_a_higher_ranked_tag_than_the_years_is_kept(ingested):
    conn, _ = ingested
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = ? WHERE xbrl_concept = 'us-gaap:Revenues' "
        "AND period_start = '2024-01-01'",
        (NARROW,),
    )
    narrow_quarter(conn, tag="us-gaap:Revenues")
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)


def test_inputs_on_two_tags_keep_the_reported_quarter(ingested):
    conn, _ = ingested
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = ? WHERE xbrl_concept = 'us-gaap:Revenues' "
        "AND period_start = '2024-01-01' AND fiscal_period = 'M9'",
        (CONTRACT,),
    )
    narrow_quarter(conn)
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)


def test_a_narrow_third_quarter_is_nine_months_less_the_first_two(ingested):
    conn, _ = ingested
    # the 10-Q gives the quarter only under the narrower tag, the nine months under Revenues
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = ?, value = 118 WHERE xbrl_concept = "
        "'us-gaap:Revenues' AND period_start = '2024-07-01' AND period_end = '2024-09-30'",
        (NARROW,),
    )
    q3 = quarters(conn, "revenue", "2025-03-01")["Q3"]
    assert (q3.value, q3.derived, q3.narrower_tag) == (120, True, NARROW)


def test_no_narrow_replacement_before_the_year_is_public(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    assert "Q4" not in quarters(conn, "revenue", "2025-02-14")


def test_a_later_filing_on_the_years_tag_gives_the_quarter_back_as_reported(ingested):
    """Walmart's FY2012Q4: the 10-K of 2012-03-27 gives it only as net sales, the next 10-K
    under total revenues as the year less the nine months; from then on it is reported."""
    conn, _ = ingested
    narrow_quarter(conn)
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, 'us-gaap:Revenues', "
        "'2024-10-01', '2024-12-31', 2024, 'Q4', 130, 'USD', '10-K', '0000000123-26-000001', "
        "'2026-02-15')",
        (TEST_CIK,),
    )
    before = quarters(conn, "revenue", "2026-02-14")["Q4"]
    after = quarters(conn, "revenue", "2026-02-15")["Q4"]
    assert (before.value, before.derived, before.narrower_tag) == (130, True, NARROW)
    assert (after.value, after.derived, after.narrower_tag) == (130, False, None)
    # as first reported, the derivation was public first and stays
    first = quarters(conn, "revenue", "2026-03-01", mode="first_reported")["Q4"]
    assert (first.value, first.derived, first.narrower_tag) == (130, True, NARROW)


# -- backlog #329: the quarter's own tag must agree before it moves to the year's ------------


def narrow_inputs(conn, year=None, nine_months=None):
    """The 10-K also gives the year, and the Q3 10-Q the nine months, under the narrow tag."""
    rows = [
        ("2024-01-01", "2024-12-31", "FY", year, K1, "10-K", "2025-02-15"),
        ("2024-01-01", "2024-09-30", "M9", nine_months, A3, "10-Q", "2024-11-01"),
    ]
    for start, end, period, value, accession, form, filed in rows:
        if value is None:
            continue
        conn.execute(
            "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, "
            "fiscal_year, fiscal_period, value, unit, form, accession_no, filed_at) "
            "VALUES (?, ?, ?, ?, 2024, ?, ?, 'USD', ?, ?, ?)",
            (TEST_CIK, NARROW, start, end, period, value, form, accession, filed),
        )


@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_a_narrow_quarter_that_agrees_on_its_own_tag_moves_to_the_years(ingested, mode):
    """Walmart FY2010Q4: 405,132 - 292,306 = 112,826 on net sales, the 10-K's own quarter."""
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, year=450, nine_months=325)  # 450 - 325 = 125, the reported quarter
    q4 = quarters(conn, "revenue", "2025-03-01", mode=mode)["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (460 - 330, True, NARROW)
    q4 = one_basis_quarters(conn, "2025-03-01")["Q4"]
    assert (q4.value, q4.narrower_tag) == (130, NARROW)


@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_a_narrow_quarter_that_disagrees_on_its_own_tag_is_kept_as_reported(ingested, mode):
    """The narrow quarter (125) is not the narrow year less the narrow nine months (140): it was
    revised on its own tag, so its year's tag is no longer the same line on the same basis."""
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, year=450, nine_months=310)
    kept = OwnTagCheck(
        year_tag="us-gaap:Revenues", on_year_tag=130, on_own_tag=140, inputs=[K1, A3]
    )
    q4 = quarters(conn, "revenue", "2025-03-01", mode=mode)["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)
    assert q4.kept_on_own_tag == kept  # backlog #336: says why
    q4 = one_basis_quarters(conn, "2025-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)
    assert q4.kept_on_own_tag == kept


def test_a_quarter_that_moves_or_is_not_checked_carries_no_kept_note(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].kept_on_own_tag is None  # no check
    narrow_inputs(conn, year=450, nine_months=325)
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].kept_on_own_tag is None  # agrees
    assert all(q.kept_on_own_tag is None for q in quarters(conn, "revenue", "2025-03-01").values())


def scale_revenues(conn, factor):
    """Multiply the fixture's Revenues rows, so a narrow year or nine months well above 460 or 330
    stays within twice the Revenues figure in its filing and is not read as the whole of which
    Revenues is a part (backlog #322)."""
    conn.execute(
        "UPDATE financial_facts SET value = value * ? WHERE xbrl_concept = 'us-gaap:Revenues'",
        (factor,),
    )


def test_a_move_within_the_recast_threshold_still_agrees(ingested):
    conn, _ = ingested
    scale_revenues(conn, 10)
    narrow_quarter(conn, value=1000)
    narrow_inputs(conn, year=1324, nine_months=330)  # 994, 0.6% off: disagrees
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].narrower_tag is None
    conn.execute("UPDATE financial_facts SET value = 1326 WHERE value = 1324")  # 996, 0.4% off
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].narrower_tag == NARROW


def test_without_every_narrow_input_there_is_no_check(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, year=450)  # no nine months under the narrow tag in the 10-Q
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert (q4.value, q4.narrower_tag) == (130, NARROW)


def test_a_narrow_input_from_another_filing_is_not_used(ingested):
    """Each input is read from the filing that gave it: a narrow year in a later 10-K/A does not
    stand in for the 10-K's own."""
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, nine_months=310)
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, ?, '2024-01-01', "
        "'2024-12-31', 2024, 'FY', 450, 'USD', '10-K/A', '0000000123-25-000009', '2025-02-20')",
        (TEST_CIK, NARROW),
    )
    q4 = quarters(conn, "revenue", "2025-03-01")["Q4"]
    assert (q4.value, q4.narrower_tag) == (130, NARROW)


def test_a_quarter_near_zero_is_checked_against_an_average_quarter(ingested):
    """Tolerance is 0.5% of the larger of the quarter and a quarter of the year: a quarter of 2
    off by 1 in a year of 1,000 still agrees (1 <= 0.005 * 250)."""
    conn, _ = ingested
    scale_revenues(conn, 10)
    narrow_quarter(conn, value=2)
    narrow_inputs(conn, year=1000, nine_months=997)  # 3, against 2 reported
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].narrower_tag == NARROW
    conn.execute("UPDATE financial_facts SET value = 995 WHERE value = 997")  # 5: 3 off
    assert quarters(conn, "revenue", "2025-03-01")["Q4"].narrower_tag is None


# -- backlog #336: inputs from different years' filings ---------------------------------------

# FY2025 10-K, filed 2026-02-15: the fixture's own, repeating FY2024 revenue as 455 (Revenues),
# so latest mode reads the year from it on 2026-03-01
K2 = "0000000123-26-000001"


def later_10k(conn, narrow_year):
    """The next 10-K also gives FY2024 under the narrow tag, as Walmart's 10-K of 2012-03-27 did
    for FY2010."""
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, "
        "fiscal_year, fiscal_period, value, unit, form, accession_no, filed_at) VALUES "
        "(?, ?, '2024-01-01', '2024-12-31', 2025, 'FY', ?, 'USD', '10-K', ?, '2026-02-15')",
        (TEST_CIK, NARROW, narrow_year, K2),
    )


def test_a_narrow_recast_in_a_later_filing_does_not_fail_the_check(ingested):
    """The quarter's own 10-K gives the narrow year as 450 (450 - 325 = 125, the quarter); the
    next 10-K, where latest mode reads the year, recast the narrow year to 470. Read from the
    year input's filing the check fails (470 - 325 = 145); read from the quarter's own filing,
    where quarter and year sit side by side, it agrees, so the quarter moves."""
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, year=450, nine_months=325)
    later_10k(conn, narrow_year=470)
    q4 = quarters(conn, "revenue", "2026-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag, q4.kept_on_own_tag) == (
        455 - 330,
        True,
        NARROW,
        None,
    )
    assert K2 in q4.inputs  # the year still comes from the newest filing


def test_without_the_narrow_year_in_the_quarters_filing_the_first_pairing_decides(ingested):
    """Only the later 10-K gives the narrow year (470): no second pairing, so the check fails and
    the quarter is kept, saying the own-tag derivation came from the year input's filing."""
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, nine_months=325)
    later_10k(conn, narrow_year=470)
    q4 = quarters(conn, "revenue", "2026-03-01")["Q4"]
    assert (q4.value, q4.derived, q4.narrower_tag) == (125, False, None)
    assert q4.kept_on_own_tag == OwnTagCheck(
        year_tag="us-gaap:Revenues", on_year_tag=455 - 330, on_own_tag=145, inputs=[K2, A3]
    )


def test_both_pairings_failing_keeps_the_quarter(ingested):
    conn, _ = ingested
    narrow_quarter(conn)
    narrow_inputs(conn, year=440, nine_months=325)  # 115 in its own filing
    later_10k(conn, narrow_year=470)  # 145 from the year input's filing
    q4 = quarters(conn, "revenue", "2026-03-01")["Q4"]
    assert (q4.value, q4.narrower_tag) == (125, None)
    # both figures, so a reader can see the year moved, not the quarter (analyst, #336)
    assert (q4.kept_on_own_tag.on_own_tag, q4.kept_on_own_tag.on_own_filing) == (145, 115)
    assert q4.kept_on_own_tag.minuend == "FY"


def test_a_kept_third_quarter_names_the_nine_months(ingested):
    conn, _ = ingested
    # the 10-Q gives Q3 only under the narrow tag (118), and the nine months under both: on the
    # narrow tag the nine months less Q1 and Q2 is not 118
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = ?, value = 118 WHERE xbrl_concept = "
        "'us-gaap:Revenues' AND period_start = '2024-07-01' AND period_end = '2024-09-30'",
        (NARROW,),
    )
    narrow_inputs(conn, nine_months=300)  # 300 - 200 = 100, not 118
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, ?, '2024-01-01', "
        "'2024-06-30', 2024, 'Q2', 200, 'USD', '10-Q', '0000000123-24-000020', '2024-08-01')",
        (TEST_CIK, NARROW),
    )
    q3 = quarters(conn, "revenue", "2025-03-01")["Q3"]
    assert (q3.value, q3.derived, q3.narrower_tag) == (118, False, None)
    assert q3.kept_on_own_tag.minuend == "M9"
