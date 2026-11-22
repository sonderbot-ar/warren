"""Walmart's cost of debt counts its finance-lease interest (backlog #497): its interest line
(`InterestExpenseDebt`) is debt only, while its debt includes the finance-lease liability, so the
year's finance-lease interest is added wherever that year-end debt counted the leases."""

from datetime import date

import pytest

from domains.analysis import math_engine as me
from domains.analysis.math_engine import History, cost_of_debt_year
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF

TAGS = {
    "interest_expense": "InterestExpenseDebt",
    "interest_paid": "InterestPaidNet",
    "finance_lease_interest": "FinanceLeaseInterestExpense",
    "debt_noncurrent": "LongTermDebtNoncurrent",
    "debt_current": "LongTermDebtCurrent",
    "short_term_borrowings": "ShortTermBorrowings",
    "finance_lease_liabilities": "FinanceLeaseLiability",
    "debt_current_with_leases": "LongTermDebtAndCapitalLeaseObligationsCurrent",
    "commercial_paper": "CommercialPaper",
}
INSTANT = {
    "debt_noncurrent",
    "debt_current",
    "short_term_borrowings",
    "finance_lease_liabilities",
    "commercial_paper",
}


def fact(item, value, year):
    end = date(year, 1, 31)
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{TAGS[item]}",
        period_end=end,
        period_start=None if item in INSTANT else date(year - 1, 2, 1),
        value=value,
        unit="USD",
        accession_no=f"0000104169-{year % 100:02d}-000010",
        filed_at=date(year, 3, 20),
        fiscal_year=year,
        fiscal_period="FY",
    )


def walmart(lease_interest=True, leases=True, interest="interest_expense"):
    """Walmart's FY2025 and FY2026 10-K figures (millions)."""
    rows = {
        2025: {
            "debt_noncurrent": 33_401,
            "debt_current": 2_598,
            "short_term_borrowings": 3_068,
            "finance_lease_liabilities": 6_723,
            interest: 2_249,
            "finance_lease_interest": 381,
        },
        2026: {
            "debt_noncurrent": 34_624,
            "debt_current": 3_542,
            "short_term_borrowings": 6_596,
            "finance_lease_liabilities": 6_761,
            interest: 2_318,
            "finance_lease_interest": 383,
        },
    }
    annual = {}
    for year, items in rows.items():
        for item, value in items.items():
            if item == "finance_lease_interest" and not lease_interest:
                continue
            if item == "finance_lease_liabilities" and not leases:
                continue
            annual[(item, year)] = fact(item, value * 1e6, year)
    return History(quarterly={}, annual=annual, instants={})


def test_walmart_fy2026_adds_its_finance_lease_interest():
    kd, interest, (start, _), (end, closing) = cost_of_debt_year(walmart(), 2026)
    assert interest.value == pytest.approx(2_701e6)  # 2,318 debt + 383 finance lease
    assert start == pytest.approx(45_790e6) and end == pytest.approx(51_523e6)
    assert kd == pytest.approx(2_701 / 48_656.5)  # 5.55%, not 4.76%
    assert [f.canonical_name for f in interest.facts] == [
        "interest_expense",
        "finance_lease_interest",
    ]
    assert interest.method.endswith("+ finance lease interest: " + me.trace(interest.facts[1]))
    assert not interest.fallback
    assert any(f.canonical_name == "finance_lease_liabilities" for f in closing)


def test_a_year_without_the_line_keeps_its_interest():
    kd, interest, _, _ = cost_of_debt_year(walmart(lease_interest=False), 2026)
    assert interest.value == pytest.approx(2_318e6)
    assert kd == pytest.approx(2_318 / 48_656.5)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


def test_the_lease_interest_follows_the_lease_debt():
    """With no finance-lease liability counted in the year-end debt, its interest stays out."""
    _, interest, _, (_, closing) = cost_of_debt_year(walmart(leases=False), 2026)
    assert interest.value == pytest.approx(2_318e6)
    assert not any(f.canonical_name == "finance_lease_liabilities" for f in closing)


def test_the_lease_interest_stays_out_when_a_debt_tag_already_holds_the_leases():
    history = walmart()
    current = history.annual.pop(("debt_current", 2026))
    history.annual[("debt_current", 2026)] = Fact(
        **{**current.__dict__, "xbrl_concept": f"us-gaap:{TAGS['debt_current_with_leases']}"}
    )
    _, interest, _, (_, closing) = cost_of_debt_year(history, 2026)
    assert not any(f.canonical_name == "finance_lease_liabilities" for f in closing)
    assert interest.value == pytest.approx(2_318e6)


def test_a_year_whose_opening_debt_has_no_leases_keeps_its_interest():
    """Walmart's FY2020: the leases reach the balance sheet at its closing year end only, so the
    average debt is half on the old basis and the year keeps its debt-only interest."""
    history = walmart()
    del history.annual[("finance_lease_liabilities", 2025)]
    _, interest, (_, opening), _ = cost_of_debt_year(history, 2026)
    assert opening and interest.value == pytest.approx(2_318e6)


def test_with_no_opening_debt_the_closing_debt_decides():
    history = walmart()
    for key in [k for k in history.annual if k[1] == 2025]:
        del history.annual[key]
    kd, interest, (_, opening), (end, _) = cost_of_debt_year(history, 2026)
    assert opening == [] and interest.value == pytest.approx(2_701e6)
    assert kd == pytest.approx(2_701e6 / end)


def test_never_added_to_cash_interest():
    """The `interest_paid` fallback is cash paid; the lease line is not added to it."""
    _, interest, _, _ = cost_of_debt_year(walmart(interest="interest_paid"), 2026)
    assert interest.fallback and interest.value == pytest.approx(2_318e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_paid"]


def test_the_lease_interest_is_read_only_when_the_map_has_it():
    assert me.LEASE_INTEREST in me.ITEMS and me.LEASE_INTEREST in me.OPTIONAL_ITEMS


# -- through the database: the map in force decides (backlog #528) ----------------------------

BEFORE_497 = "91c71ab5c1f89b7942d4d2674664ee591ef61d88a8cbf770cb1c234ae2a4c782"  # #522's map
CIK = "0000000123"
TEN_K = {2018: ("0000000123-19-000098", "2019-02-15"), 2019: ("0000000123-20-000099", "2020-02-15")}


def store(conn, tag, value, end, start=None):
    """A fact as ingest stores it for Walmart (the row is scoped to WMT, so Test Corp's ingest
    would skip it; the gate under test is the map's, not the ingest's)."""
    year = int(end[:4])
    accn, filed = TEN_K[year]
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES (?, ?, ?, ?, ?, 'FY', ?, 'USD', '10-K', ?, ?)",
        (CIK, f"us-gaap:{tag}", start, end, year, value, accn, filed),
    )


def with_leases(conn):
    # Test Corp's interest filed as Walmart's is, debt only (`InterestExpenseDebt`): the lease line
    # is added only to a debt-only interest tag (backlog #527)
    conn.execute(
        "UPDATE financial_facts SET xbrl_concept = 'us-gaap:InterestExpenseDebt' "
        "WHERE cik = ? AND xbrl_concept = 'us-gaap:InterestExpense'",
        (CIK,),
    )
    store(conn, "FinanceLeaseLiability", 40, "2018-12-31")
    store(conn, "FinanceLeaseLiability", 40, "2019-12-31")
    store(conn, "FinanceLeaseInterestExpense", 3, "2019-12-31", "2019-01-01")
    return conn


def items(history):
    return {k[0] for k in history.annual}


def test_today_s_map_reads_the_lease_interest(company):
    from domains.analysis.math_engine import load_history

    history = load_history(with_leases(company), CIK, AS_OF)
    assert history.annual[(me.LEASE_INTEREST, 2019)].value == 3
    _, interest, _, _ = cost_of_debt_year(history, 2019)
    assert interest.value == pytest.approx(8 + 3)  # Test Corp's 2 a quarter, plus the lease line


def test_a_map_without_the_row_leaves_it_out(company):
    """A rebuild through the map in force before #497 reads what that map read: the stored lease
    interest is not in the history, every other item is, and the year keeps its own interest."""
    from domains.analysis.math_engine import load_history
    from domains.fundamentals.concepts import archived_concept_map, concept_map_in_force

    assert me.LEASE_INTEREST not in {r.canonical_name for r in archived_concept_map(BEFORE_497)}
    conn = with_leases(company)
    today = load_history(conn, CIK, AS_OF)
    with concept_map_in_force(conn, BEFORE_497, "TST"):
        before = load_history(conn, CIK, AS_OF)
    assert me.LEASE_INTEREST not in items(before)
    assert items(before) == items(today) - {me.LEASE_INTEREST}
    assert before.annual[("finance_lease_liabilities", 2019)].value == 40
    _, interest, _, _ = cost_of_debt_year(before, 2019)
    assert interest.value == pytest.approx(8)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


# -- Microsoft: interest paid on debt in place of an expense net of capitalised interest (#527) --

MSFT_TAGS = {
    **TAGS,
    "interest_expense": "InterestExpenseNonoperating",
    "interest_paid_on_debt": "InterestPaid",
}


def msft_fact(item, value, year):
    end = date(year, 6, 30)
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{MSFT_TAGS[item]}",
        period_end=end,
        period_start=None if item in INSTANT else date(year - 1, 7, 1),
        value=value,
        unit="USD",
        accession_no=f"0000950170-{year % 100:02d}-000100",
        filed_at=date(year, 7, 30),
        fiscal_year=year,
        fiscal_period="FY",
    )


def microsoft(paid=True, lease_interest=True, leases=(True, True)):
    """Microsoft's FY2025 and FY2026 10-K figures (millions): debt, finance-lease liability,
    interest expense (net of capitalised interest, lease interest inside), lease interest and
    cash paid for interest on debt."""
    rows = {
        2025: {
            "debt_noncurrent": 40_152,
            "debt_current": 2_999,
            "finance_lease_liabilities": 46_172,
            "interest_expense": 2_385,
            "finance_lease_interest": 1_417,
            "interest_paid_on_debt": 1_600,
        },
        2026: {
            "debt_noncurrent": 31_670,
            "debt_current": 9_250,
            "finance_lease_liabilities": 65_968,
            "interest_expense": 3_051,
            "finance_lease_interest": 2_547,
            "interest_paid_on_debt": 1_500,
        },
    }
    annual = {}
    for (year, items), with_leases in zip(rows.items(), leases, strict=True):
        for item, value in items.items():
            if item == "interest_paid_on_debt" and not paid:
                continue
            if item == "finance_lease_interest" and not lease_interest:
                continue
            if item == "finance_lease_liabilities" and not with_leases:
                continue
            annual[(item, year)] = msft_fact(item, value * 1e6, year)
    return History(quarterly={}, annual=annual, instants={})


def test_microsoft_fy2026_reads_interest_paid_on_debt_plus_lease_interest():
    kd, interest, (start, _), (end, _) = cost_of_debt_year(microsoft(), 2026)
    assert start == pytest.approx(89_323e6) and end == pytest.approx(106_888e6)
    assert interest.value == pytest.approx(4_047e6)  # 1,500 paid on debt + 2,547 lease interest
    assert kd == pytest.approx(4_047 / 98_105.5)  # 4.13%, not 3.11%
    assert [f.canonical_name for f in interest.facts] == [
        "interest_paid_on_debt",
        "finance_lease_interest",
    ]
    assert interest.method.startswith("interest paid on debt (cash, before capitalised interest): ")
    assert "in place of interest_expense" in interest.method
    assert not interest.fallback


def test_no_leases_at_either_year_end_keeps_its_interest():
    """Microsoft's FY2016 and earlier: the 10-Ks name no capitalising before the leases, so the
    accrual interest stays (analyst, #527 design review)."""
    _, interest, _, _ = cost_of_debt_year(microsoft(leases=(False, False)), 2026)
    assert interest.value == pytest.approx(3_051e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


@pytest.mark.parametrize("year", [2025, 2026])
def test_commercial_paper_at_either_year_end_keeps_its_interest(year):
    """Microsoft's FY2024 and FY2025: commercial paper (6,693M at 2024-06-30) is in the average
    debt, but its interest is paid as a discount at maturity, not in the cash paid for interest on
    debt, so the year keeps its accrual interest (analyst, #527 design review)."""
    history = microsoft()
    history.annual[("commercial_paper", year)] = msft_fact("commercial_paper", 6_693e6, year)
    _, interest, _, _ = cost_of_debt_year(history, 2026)
    assert interest.value == pytest.approx(3_051e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


def test_commercial_paper_of_zero_does_not_count():
    history = microsoft()
    history.annual[("commercial_paper", 2025)] = msft_fact("commercial_paper", 0.0, 2025)
    _, interest, _, _ = cost_of_debt_year(history, 2026)
    assert interest.value == pytest.approx(4_047e6)


@pytest.mark.parametrize("leases", [(False, True), (True, False)])
def test_a_straddle_year_keeps_its_interest(leases):
    """Microsoft's FY2017: the leases are in one year-end debt only, so no basis is mixed."""
    _, interest, _, _ = cost_of_debt_year(microsoft(leases=leases), 2026)
    assert interest.value == pytest.approx(3_051e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


def test_lease_debt_without_lease_interest_keeps_its_interest():
    _, interest, _, _ = cost_of_debt_year(microsoft(lease_interest=False), 2026)
    assert interest.value == pytest.approx(3_051e6)


def test_a_total_that_holds_lease_interest_never_gets_it_added():
    """A Microsoft year without interest paid on debt: its total already holds the lease interest
    (10-K Item 7), so the Walmart rule does not add it again."""
    _, interest, _, _ = cost_of_debt_year(microsoft(paid=False), 2026)
    assert interest.value == pytest.approx(3_051e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


def test_the_lease_interest_is_added_only_to_a_debt_only_tag():
    assert me.DEBT_ONLY_INTEREST_TAGS == {"us-gaap:InterestExpenseDebt"}
    history = walmart()
    interest = history.annual.pop(("interest_expense", 2026))
    history.annual[("interest_expense", 2026)] = Fact(
        **{**interest.__dict__, "xbrl_concept": "us-gaap:InterestExpenseNonoperating"}
    )
    _, resolved, _, _ = cost_of_debt_year(history, 2026)
    assert resolved.value == pytest.approx(2_318e6)


def test_interest_paid_on_debt_is_read_only_when_the_map_has_it():
    assert me.PAID_ON_DEBT in me.ITEMS and me.PAID_ON_DEBT in me.OPTIONAL_ITEMS
