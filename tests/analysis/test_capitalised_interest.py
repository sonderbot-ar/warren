"""ExxonMobil's cost of debt counts the interest it capitalises (backlog #533): its interest
expense is net of the interest it capitalises into projects, and it files the capitalised amount,
so the year's interest is expensed + capitalised, interest incurred (ASC 835-20), on the basis of
its debt, which already holds its finance leases."""

from datetime import date

import pytest

from domains.analysis import math_engine as me
from domains.analysis.math_engine import History, cost_of_debt_year
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF
from tests.analysis.test_lease_interest import (
    CIK,
    microsoft,
    store,
    walmart,
)

TAGS = {
    "interest_expense": "InterestExpense",
    "interest_paid": "InterestPaidNet",
    "interest_capitalized": "InterestPaidCapitalized",
    "interest_not_on_debt": "InterestExpenseOther",
    "debt_noncurrent": "LongTermDebtAndCapitalLeaseObligations",
    "debt_current": "LongTermDebtCurrent",
    "short_term_borrowings": "ShortTermBorrowings",
    "commercial_paper": "CommercialPaper",
}
INSTANT = {"debt_noncurrent", "debt_current", "short_term_borrowings", "commercial_paper"}


def fact(item, value, year, tag=None):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{tag or TAGS[item]}",
        period_end=date(year, 12, 31),
        period_start=None if item in INSTANT else date(year, 1, 1),
        value=value,
        unit="USD",
        accession_no=f"0000034088-{(year + 1) % 100:02d}-000045",
        filed_at=date(year + 1, 2, 18),
        fiscal_year=year,
        fiscal_period="FY",
    )


def exxon(capitalised=1_534, interest="interest_expense", non_debt=300):
    """ExxonMobil-like FY2024 and FY2025 figures (millions): debt whose average is 42,624M (the
    stored run's), interest expense 603M, of which 300M not on debt, and interest capitalised
    1,534M (FY2025 10-K, 0000034088-26-000045)."""
    rows = {
        2024: {"debt_noncurrent": 36_000, "debt_current": 5_710, interest: 996},
        2025: {"debt_noncurrent": 37_000, "debt_current": 6_537, interest: 603},
    }
    annual = {}
    for year, items in rows.items():
        for item, value in items.items():
            annual[(item, year)] = fact(item, value * 1e6, year)
    if capitalised is not None:
        annual[("interest_capitalized", 2025)] = fact(
            "interest_capitalized", capitalised * 1e6, 2025
        )
    if non_debt is not None:
        annual[("interest_not_on_debt", 2025)] = fact("interest_not_on_debt", non_debt * 1e6, 2025)
    return History(quarterly={}, annual=annual, instants={})


def test_exxon_fy2025_reads_interest_incurred_on_debt():
    kd, interest, (start, _), (end, _) = cost_of_debt_year(exxon(), 2025)
    assert (start + end) / 2 == pytest.approx(42_623.5e6)
    assert interest.value == pytest.approx(1_837e6)  # 603 expensed - 300 not on debt + 1,534
    assert kd == pytest.approx(1_837 / 42_623.5)  # 4.31%, not 1.41%
    assert [f.canonical_name for f in interest.facts] == [
        "interest_expense",
        "interest_not_on_debt",
        "interest_capitalized",
    ]
    assert interest.method.startswith("interest_expense")
    assert " - interest not on debt: " in interest.method
    assert "+ interest capitalised (interest incurred = expensed + capitalised, ASC 835-20): " in (
        interest.method
    )
    assert not interest.fallback


def test_capitalised_alone():
    _, interest, _, _ = cost_of_debt_year(exxon(non_debt=None), 2025)
    assert interest.value == pytest.approx(2_137e6)


def test_not_on_debt_alone():
    _, interest, _, _ = cost_of_debt_year(exxon(capitalised=None), 2025)
    assert interest.value == pytest.approx(303e6)


@pytest.mark.parametrize("non_debt", [-123, 603, 700])
def test_a_non_debt_figure_below_zero_or_not_below_the_expense_is_left_out(non_debt):
    """Exxon's FY2013 filed -123M; a figure as large as the expense would leave no interest."""
    history = exxon(capitalised=None, non_debt=non_debt)
    nd = history.annual[("interest_not_on_debt", 2025)]
    _, interest, _, _ = cost_of_debt_year(history, 2025)
    assert interest.value == pytest.approx(603e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]
    # backlog #540: the method says which figure was left out and why, with its trace
    why = "below zero" if non_debt < 0 else "not below the interest"
    assert interest.method.endswith(f"(interest not on debt left out, {why}: {me.trace(nd)})")


def test_a_used_figure_has_no_left_out_clause():
    _, interest, _, _ = cost_of_debt_year(exxon(), 2025)
    assert "left out" not in interest.method


def test_a_left_out_non_debt_figure_still_lets_the_capitalised_part_in():
    _, interest, _, _ = cost_of_debt_year(exxon(non_debt=-123), 2025)
    assert interest.value == pytest.approx(603e6 + 1_534e6)
    assert "(interest not on debt left out, below zero: " in interest.method
    assert interest.method.index("left out") < interest.method.index("+ interest capitalised")
    assert [f.canonical_name for f in interest.facts] == [
        "interest_expense",
        "interest_capitalized",
    ]


def test_the_older_tag_reads_the_same():
    """FY2017 to FY2020: `InterestCostsCapitalized`, the same figure as the cash-flow tag."""
    history = exxon(capitalised=None, non_debt=None)
    history.annual[("interest_capitalized", 2025)] = fact(
        "interest_capitalized", 1_534e6, 2025, tag="InterestCostsCapitalized"
    )
    _, interest, _, _ = cost_of_debt_year(history, 2025)
    assert interest.value == pytest.approx(2_137e6)


def test_a_year_without_the_line_keeps_its_interest():
    _, interest, _, _ = cost_of_debt_year(exxon(capitalised=None, non_debt=None), 2025)
    assert interest.value == pytest.approx(603e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


def test_zero_adds_nothing_and_a_negative_figure_is_left_out():
    _, zero, _, _ = cost_of_debt_year(exxon(capitalised=0, non_debt=None), 2025)
    assert zero.value == pytest.approx(603e6)
    assert "left out" not in zero.method
    history = exxon(capitalised=-5, non_debt=None)
    cap = history.annual[("interest_capitalized", 2025)]
    _, negative, _, _ = cost_of_debt_year(history, 2025)
    assert negative.value == pytest.approx(603e6)
    assert [f.canonical_name for f in negative.facts] == ["interest_expense"]
    assert negative.method.endswith(f"(interest capitalised left out, below zero: {me.trace(cap)})")


def test_never_added_to_cash_interest():
    """`InterestPaidNet` is already net of capitalising: adding the capitalised part would make it
    cash paid, a different basis, so the fallback stays as it is."""
    _, interest, _, _ = cost_of_debt_year(exxon(interest="interest_paid"), 2025)
    assert [f.canonical_name for f in interest.facts] == ["interest_paid"]
    assert interest.fallback
    assert interest.value == pytest.approx(603e6)


def test_commercial_paper_does_not_stop_it():
    """Unlike #527's cash figure, the expense accrues the paper's discount, so the sum holds with
    paper in the average debt."""
    history = exxon()
    history.annual[("commercial_paper", 2025)] = fact("commercial_paper", 3_059e6, 2025)
    _, interest, _, _ = cost_of_debt_year(history, 2025)
    assert interest.value == pytest.approx(1_837e6)


def test_cash_paid_on_debt_never_gets_it_added():
    """Microsoft's #527 path: cash paid is before capitalising, so a capitalised figure beside it
    is not added."""
    history = microsoft()
    history.annual[("interest_capitalized", 2026)] = fact("interest_capitalized", 999e6, 2026)
    _, interest, _, _ = cost_of_debt_year(history, 2026)
    assert interest.value == pytest.approx(4_047e6)


def test_walmart_and_microsoft_are_unchanged():
    assert cost_of_debt_year(walmart(), 2026)[1].value == pytest.approx(2_318e6 + 383e6)
    assert cost_of_debt_year(microsoft(), 2026)[1].value == pytest.approx(4_047e6)


def test_capitalised_interest_beside_a_debt_only_line_still_gets_the_lease_interest():
    """The lease rule asks whether the interest line is debt only, not the capitalised fact."""
    history = walmart()
    history.annual[("interest_capitalized", 2026)] = fact("interest_capitalized", 100e6, 2026)
    _, interest, _, _ = cost_of_debt_year(history, 2026)
    assert interest.value == pytest.approx(2_318e6 + 100e6 + 383e6)


def test_the_item_is_read_only_when_the_map_has_it():
    for item in (me.CAPITALISED, me.NON_DEBT):
        assert item in me.ITEMS and item in me.OPTIONAL_ITEMS


BEFORE_533 = "2b1a44897d8fa1d3a85096103ddeb3dcb486a51f5ad3b9a9e18322bc6acb9f89"  # #527's map


def test_today_s_map_reads_it_and_the_map_before_leaves_it_out(company):
    from domains.analysis.math_engine import load_history
    from domains.fundamentals.concepts import archived_concept_map, concept_map_in_force

    assert me.CAPITALISED not in {r.canonical_name for r in archived_concept_map(BEFORE_533)}
    assert me.NON_DEBT not in {r.canonical_name for r in archived_concept_map(BEFORE_533)}
    store(company, "InterestPaidCapitalized", 5, "2019-12-31", "2019-01-01")
    store(company, "InterestExpenseOther", 1, "2019-12-31", "2019-01-01")
    today = load_history(company, CIK, AS_OF)
    assert today.annual[(me.CAPITALISED, 2019)].value == 5
    assert today.annual[(me.NON_DEBT, 2019)].value == 1
    assert cost_of_debt_year(today, 2019)[1].value == pytest.approx(8 - 1 + 5)
    with concept_map_in_force(company, BEFORE_533, "TST"):
        before = load_history(company, CIK, AS_OF)
    assert (me.CAPITALISED, 2019) not in before.annual
    assert (me.NON_DEBT, 2019) not in before.annual
    assert cost_of_debt_year(before, 2019)[1].value == pytest.approx(8)


def jnj(year, expense, capitalised, opening, closing):
    """J&J-like figures (millions; backlog #540): its income statement's "Interest expense, net of
    portion capitalized" and the capitalised interest of its property note, tagged
    `InterestCostsCapitalized`; debt is long-term debt plus loans and notes payable, no leases."""

    def f(item, value, y, tag):
        return Fact(
            canonical_name=item,
            xbrl_concept=f"us-gaap:{tag}",
            period_end=date(y, 12, 31),
            period_start=None if item in INSTANT else date(y, 1, 1),
            value=value * 1e6,
            unit="USD",
            accession_no=f"0000200406-{(y + 1) % 100:02d}-000016",
            filed_at=date(y + 1, 2, 15),
            fiscal_year=y,
            fiscal_period="FY",
        )

    annual = {
        ("debt_noncurrent", year - 1): f(
            "debt_noncurrent", opening, year - 1, "LongTermDebtNoncurrent"
        ),
        ("debt_noncurrent", year): f("debt_noncurrent", closing, year, "LongTermDebtNoncurrent"),
        ("interest_expense", year): f(
            "interest_expense", expense, year, "InterestExpenseNonoperating"
        ),
    }
    if capitalised is not None:
        annual[("interest_capitalized", year)] = f(
            "interest_capitalized", capitalised, year, "InterestCostsCapitalized"
        )
    return History(quarterly={}, annual=annual, instants={})


@pytest.mark.parametrize(
    ("year", "expense", "capitalised", "opening", "closing", "rate"),
    [
        (2021, 183, 49, 35_266, 33_751, (183 + 49) / 34_508.5),  # 0.67%, was 0.53%
        (2025, 971, 114, 36_634, 47_933, (971 + 114) / 42_283.5),  # 2.57%, was 2.30%
    ],
)
def test_jnj_reads_expense_plus_capitalised(year, expense, capitalised, opening, closing, rate):
    kd, interest, _, _ = cost_of_debt_year(jnj(year, expense, capitalised, opening, closing), year)
    assert kd == pytest.approx(rate)
    assert interest.value == pytest.approx((expense + capitalised) * 1e6)
    assert [f.xbrl_concept for f in interest.facts] == [
        "us-gaap:InterestExpenseNonoperating",
        "us-gaap:InterestCostsCapitalized",
    ]
    assert "+ interest capitalised (interest incurred = expensed + capitalised, ASC 835-20): " in (
        interest.method
    )
    assert " - interest not on debt" not in interest.method


def test_jnj_without_the_figure_keeps_its_expense():
    kd, interest, _, _ = cost_of_debt_year(jnj(2021, 183, None, 35_266, 33_751), 2021)
    assert kd == pytest.approx(183 / 34_508.5)
    assert interest.method.startswith("interest_expense") and "capitalised" not in interest.method
