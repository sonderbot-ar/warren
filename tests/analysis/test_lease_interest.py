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
}
INSTANT = {"debt_noncurrent", "debt_current", "short_term_borrowings", "finance_lease_liabilities"}


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
