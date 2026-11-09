from datetime import date

import pytest

from domains.fundamentals.facts import get_reported_facts, newest_filing_disagreements
from tests.fundamentals.conftest import TEST_CIK

FY2024 = (date(2024, 1, 1), date(2024, 12, 31))
FY2023 = (date(2023, 1, 1), date(2023, 12, 31))
FY2022 = (date(2022, 1, 1), date(2022, 12, 31))


def revenue_for(conn, period, as_of, mode="latest"):
    facts = get_reported_facts(conn, TEST_CIK, ["revenue"], as_of, mode)
    matches = [f for f in facts if (f.period_start, f.period_end) == period]
    assert len(matches) <= 1
    return matches[0] if matches else None


def add_fact(conn, tag, value, accession, filed_at, period=FY2024):
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES (?, ?, ?, ?, 2024, 'FY', ?, 'USD', '10-K', ?, ?)",
        (TEST_CIK, f"us-gaap:{tag}", *(d.isoformat() for d in period), value, accession, filed_at),
    )


def test_nothing_is_visible_before_it_was_filed(ingested):
    conn, _ = ingested
    # the 8-K earnings release on 2025-01-30 is not a source; the 10-K is filed 2025-02-15
    assert revenue_for(conn, FY2024, "2025-02-14") is None


def test_as_of_is_inclusive(ingested):
    conn, _ = ingested
    fact = revenue_for(conn, FY2024, "2025-02-15")
    assert fact.value == 460
    assert fact.accession_no == "0000000123-25-000001"
    assert fact.restated is False


def test_restatement_is_invisible_before_its_filing_and_visible_after(ingested):
    conn, _ = ingested
    assert revenue_for(conn, FY2024, "2026-02-14").value == 460
    restated = revenue_for(conn, FY2024, "2026-02-15")
    assert restated.value == 455
    assert restated.restated is True
    assert restated.filed_at == date(2026, 2, 15)


def test_first_reported_keeps_the_original_value(ingested):
    conn, _ = ingested
    fact = revenue_for(conn, FY2024, "2026-12-31", mode="first_reported")
    assert fact.value == 460
    assert fact.accession_no == "0000000123-25-000001"


def test_old_tag_is_used_until_a_later_filing_reports_the_period_under_the_new_one(ingested):
    conn, _ = ingested
    assert revenue_for(conn, FY2023, "2024-03-01").xbrl_concept == "us-gaap:SalesRevenueNet"
    assert revenue_for(conn, FY2023, "2025-03-01").xbrl_concept == "us-gaap:Revenues"


def test_priority_decides_between_tags_in_the_same_filing(ingested):
    conn, _ = ingested
    add_fact(conn, "SalesRevenueNet", 999, "0000000123-25-000001", "2025-02-15")
    fact = revenue_for(conn, FY2024, "2025-03-01")
    assert (fact.value, fact.xbrl_concept) == (460, "us-gaap:Revenues")


def test_newer_filing_under_a_lower_priority_tag_is_definition_drift_not_a_restatement(ingested):
    conn, _ = ingested
    # e.g. a later filing repeats the period only under a broader or narrower measure
    add_fact(conn, "SalesRevenueNet", 450, "0000000123-26-000099", "2026-06-01")
    fact = revenue_for(conn, FY2024, "2026-07-01")
    assert (fact.value, fact.xbrl_concept) == (455, "us-gaap:Revenues")


def test_restatement_under_a_higher_ranked_tag_wins(ingested):
    conn, _ = ingested
    # FY2022 was first reported as SalesRevenueNet 350; a later filing restates it as Revenues
    add_fact(conn, "Revenues", 340, "0000000123-25-000001", "2025-02-15", period=FY2022)
    fact = revenue_for(conn, FY2022, "2025-03-01")
    assert (fact.value, fact.xbrl_concept, fact.restated) == (340, "us-gaap:Revenues", True)
    assert revenue_for(conn, FY2022, "2025-03-01", mode="first_reported").value == 350


def test_balance_sheet_items_have_no_start(ingested):
    conn, _ = ingested
    cash = get_reported_facts(conn, TEST_CIK, ["cash"], "2025-03-01")
    year_end = [f for f in cash if f.period_end == date(2024, 12, 31)][0]
    assert year_end.period_start is None
    assert (year_end.value, year_end.fiscal_period) == (70, "FY")


def test_unknown_canonical_name_is_rejected(ingested):
    conn, _ = ingested
    with pytest.raises(ValueError, match="Not in the concept map"):
        get_reported_facts(conn, TEST_CIK, ["revenues"], "2025-03-01")


def test_newest_filing_under_a_lower_ranked_tag_is_listed_as_a_disagreement(ingested):
    conn, _ = ingested
    # a later filing repeats FY2024 only under the ASC 606 tag, with a different value
    add_fact(
        conn, "RevenueFromContractWithCustomerExcludingAssessedTax", 450, "a-27-1", "2027-02-15"
    )
    assert revenue_for(conn, FY2024, "2027-03-01").value == 455  # best tag still wins
    pairs = newest_filing_disagreements(conn, TEST_CIK, ["revenue"], "2027-03-01")
    assert [(s.value, n.value, n.accession_no) for s, n in pairs if s.period_end == FY2024[1]] == [
        (455, 450, "a-27-1")
    ]
    # not yet public on the earlier date
    assert not [
        p
        for p in newest_filing_disagreements(conn, TEST_CIK, ["revenue"], "2026-12-31")
        if p[0].period_end == FY2024[1]
    ]


# -- sign-tagging errors (backlog #280) ---------------------------------------------------------

FY2021 = (date(2021, 1, 1), date(2021, 12, 31))


def tax_for(conn, period, as_of, mode="latest"):
    facts = get_reported_facts(conn, TEST_CIK, ["income_tax_expense"], as_of, mode)
    return next((f for f in facts if (f.period_start, f.period_end) == period), None)


def add_tax(conn, value, accession, filed_at, period=FY2021):
    add_fact(conn, "IncomeTaxExpenseBenefit", value, accession, filed_at, period)


def test_a_newest_version_with_the_flipped_sign_is_skipped_on_the_usual_sign(ingested):
    conn, _ = ingested
    # WMT's FY2008 tax: 7,145 million first filed, -7,133 in a later 10-K, and no third version;
    # tax is positive in the company's other periods, so the flipped one is the tagging error
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, 60, "t-24-1", "2024-02-15", FY2023)
    add_tax(conn, 7145, "t-22-1", "2022-02-15")
    add_tax(conn, -7133, "t-24-2", "2024-02-20")
    fact = tax_for(conn, FY2021, "2024-03-01")
    assert (fact.value, fact.accession_no, fact.restated) == (7145, "t-22-1", False)


def test_a_flipped_first_version_is_corrected_by_the_newer_one(ingested):
    conn, _ = ingested
    # CAT's 2009 cost of revenue: -12,779 million first filed, 12,779 a year later
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, -100, "t-22-1", "2022-02-15")
    add_tax(conn, 100, "t-23-2", "2023-02-20")
    assert tax_for(conn, FY2021, "2024-03-01").value == 100


def test_the_sign_most_versions_take_wins_over_the_usual_sign(ingested):
    conn, _ = ingested
    # WMT's FY2009 tax: 7,139, then -7,156 in one 10-K, then 7,156: the middle one is the error
    add_tax(conn, -50, "t-23-1", "2023-02-15", FY2022)  # the usual sign alone would say negative
    add_tax(conn, -60, "t-24-1", "2024-02-15", FY2023)
    add_tax(conn, 7139, "t-22-1", "2022-02-15")
    add_tax(conn, -7156, "t-23-2", "2023-02-20")
    add_tax(conn, 7156, "t-24-2", "2024-02-20")
    # two versions, one each way: the tie goes to the usual sign (negative here)
    assert tax_for(conn, FY2021, "2024-02-19").value == -7156
    # a third version: two of three are positive, so the negative one is the error
    assert tax_for(conn, FY2021, "2024-03-01").value == 7156


def test_no_usual_sign_keeps_the_newest_version(ingested):
    conn, _ = ingested
    add_tax(conn, 100, "t-22-1", "2022-02-15")  # the item's only period: nothing breaks the tie
    add_tax(conn, -100, "t-23-2", "2023-02-20")
    assert tax_for(conn, FY2021, "2024-03-01").value == -100


def test_a_sign_change_with_a_new_size_is_a_restatement_not_a_flip(ingested):
    conn, _ = ingested
    # MSFT's FY2016 domestic pretax income: -325 million twice, then 5,125 after a recast
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, -325, "t-22-1", "2022-02-15")
    add_tax(conn, -325, "t-23-2", "2023-02-20")
    add_tax(conn, 5125, "t-24-2", "2024-02-20")
    fact = tax_for(conn, FY2021, "2024-03-01")
    assert (fact.value, fact.restated) == (5125, True)


def test_the_size_tolerance_is_one_percent(ingested):
    from domains.fundamentals.facts import SIGN_FLIP_TOLERANCE

    conn, _ = ingested
    assert SIGN_FLIP_TOLERANCE == 0.01
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, 1000, "t-22-1", "2022-02-15")
    add_tax(conn, -1010, "t-23-2", "2023-02-20")  # 1.0% of the other: a flip
    assert tax_for(conn, FY2021, "2024-03-01").value == 1000
    add_tax(conn, -1011, "t-24-2", "2024-02-20")  # 1.1% from 1,000: not a flip of it
    assert tax_for(conn, FY2021, "2025-03-01").value == -1011


def test_a_flip_is_judged_only_on_versions_public_by_as_of(ingested):
    conn, _ = ingested
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, -100, "t-22-1", "2022-02-15")
    add_tax(conn, 100, "t-23-2", "2023-02-20")
    # before the corrected version is filed, the only version is the one there is
    assert tax_for(conn, FY2021, "2023-02-19").value == -100
    assert tax_for(conn, FY2021, "2023-02-20").value == 100


def test_first_reported_keeps_a_flipped_first_version(ingested):
    conn, _ = ingested
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, -100, "t-22-1", "2022-02-15")
    add_tax(conn, 100, "t-23-2", "2023-02-20")
    assert tax_for(conn, FY2021, "2024-03-01", mode="first_reported").value == -100


def test_a_skipped_flip_is_listed_apart_from_tag_disagreements(ingested):
    from domains.fundamentals.facts import skipped_sign_flips

    conn, _ = ingested
    add_tax(conn, 50, "t-23-1", "2023-02-15", FY2022)
    add_tax(conn, 7145, "t-22-1", "2022-02-15")
    add_tax(conn, -7133, "t-24-2", "2024-02-20")
    names = ["income_tax_expense"]
    assert not newest_filing_disagreements(conn, TEST_CIK, names, "2024-03-01")
    pairs = skipped_sign_flips(conn, TEST_CIK, names, "2024-03-01")
    assert [(s.value, s.accession_no, k.value, k.accession_no) for s, k in pairs] == [
        (7145, "t-22-1", -7133, "t-24-2")
    ]
    assert not skipped_sign_flips(conn, TEST_CIK, names, "2024-02-19")
