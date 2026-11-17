"""The current portion of long-term debt is read on the non-current debt's basis (backlog #421):
Exxon tags its current portion with and without finance leases beside a lease-inclusive
non-current tag, and the plain current figure lost the leases due within a year."""

from datetime import date

import pytest

from domains.analysis.math_engine import debt_parts
from domains.fundamentals.concepts import concept_map_in_force
from domains.fundamentals.facts import (
    _merge_current,
    current_on_noncurrent_basis,
    get_facts,
    rounding_unit,
)
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import build, by_key

BEFORE_421 = "c621cb3eaf6ecc0fba17d01218f5fcd2a31a653ec2eb0731bcb2bd65d2f977f4"  # #408's map
WITH = "LongTermDebtAndCapitalLeaseObligationsCurrent"


def lease_inclusive(with_leases=24, noncurrent_tag="LongTermDebtAndCapitalLeaseObligations"):
    """Exxon's presentation: the non-current debt only under a lease-inclusive tag, and the
    current portion under both tags (the fixture's plain one is 20)."""

    def edit(tag, row):
        if tag == "LongTermDebtNoncurrent":
            return [(noncurrent_tag, row)]
        if tag == "LongTermDebtCurrent" and with_leases is not None:
            return [(tag, row), (WITH, {**row, "val": with_leases})]
        return row

    return edit


def test_a_lease_inclusive_noncurrent_reads_the_lease_inclusive_current(make_company):
    conn = make_company(lease_inclusive())
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 204  # 24 + 180, not 200
    assert rows[("balance:debt_current", "-")].value == 24
    assert WITH in rows[("balance:debt_current", "-")].method
    nwc = rows[("history:nwc", "FY2019")]
    assert nwc.value == pytest.approx((300 - 60) - (150 - 24))
    assert "FY2019 204" in rows[("cost_of_debt", "-")].method


def test_a_plain_noncurrent_keeps_the_plain_current(make_company):
    # Coca-Cola's presentation before 2024 (and any company counting finance leases on their
    # own line): the lease-inclusive current would count current leases twice
    conn = make_company(lease_inclusive(noncurrent_tag="LongTermDebtNoncurrent"))
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200
    assert WITH not in rows[("balance:debt_current", "-")].method


@pytest.mark.parametrize("with_leases", [20, 19, 180])
def test_equal_smaller_or_the_noncurrent_again_keeps_the_plain_current(make_company, with_leases):
    # equal: the plain tag already holds any leases (Exxon 2020-2024); smaller: can't hold
    # leases too; equal to the non-current debt: the long-term debt under the wrong tag (Exxon
    # 2010-12-31, 12,227M beside 345M)
    conn = make_company(lease_inclusive(with_leases))
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200
    assert WITH not in rows[("balance:debt_current", "-")].method


def test_the_lease_inclusive_current_alone_is_read_as_before(make_company):
    # Coca-Cola 2024+: only the lease-inclusive tags
    def only_with_leases(tag, row):
        if tag == "LongTermDebtNoncurrent":
            return [("LongTermDebtAndCapitalLeaseObligations", row)]
        if tag == "LongTermDebtCurrent":
            return [(WITH, {**row, "val": 22})]
        return row

    conn = make_company(only_with_leases)
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 202
    assert WITH in rows[("balance:debt_current", "-")].method


def test_a_map_before_421_reads_what_it_read_before(make_company):
    conn = make_company(lease_inclusive())
    with concept_map_in_force(conn, BEFORE_421, "TST"):
        rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200  # the plain tag ranked first, leases lost


def test_the_merged_fact_is_the_current_portion_and_nothing_else_is_returned(make_company):
    conn = make_company(lease_inclusive())
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, frequency="annual")
    assert {f.canonical_name for f in facts} == {"debt_current"}
    assert {f.xbrl_concept for f in facts} == {f"us-gaap:{WITH}"}
    assert all(f.value == 24 for f in facts)


def fact(item, value, tag):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{tag}",
        period_end=date(2019, 12, 31),
        value=value,
        unit="USD",
        accession_no="0000034088-20-000016",
        filed_at=date(2020, 2, 26),
    )


def test_xom_2019_year_end():
    # Exxon's 10-K for 2019: current portion 1,617M, with finance leases 1,701M, non-current
    # (lease-inclusive) 26,342M
    plain = fact("debt_current", 1_617e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 1_701e6, WITH)
    noncurrent = fact("debt_noncurrent", 26_342e6, "LongTermDebtAndCapitalLeaseObligations")
    current = current_on_noncurrent_basis(plain, with_leases, noncurrent)
    assert current.value == 1_701e6 and current.canonical_name == "debt_current"
    leases = fact("finance_lease_liabilities", 2_000e6, "FinanceLeaseLiability")
    by_item = {f.canonical_name: f for f in (current, noncurrent, leases)}
    total, _, _, notes = debt_parts(by_item.get)
    assert total == 1_701e6 + 26_342e6  # the lease line is skipped, the current leases kept
    assert "finance leases skipped" in notes
    # the filing's own total of debt due within one year adds up with the lease-inclusive
    # figure: bank loans 316 + commercial paper 18,561 + 1,701 = 20,578 (1,617 gives 20,494)
    assert 316 + 18_561 + current.value / 1e6 == 20_578


def test_a_large_lease_share_of_a_small_current_portion_is_kept():
    # Exxon's current portion was 181M at 2022-12-31: a lease portion near its size is real
    plain = fact("debt_current", 181e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 400e6, WITH)
    noncurrent = fact("debt_noncurrent", 40_559e6, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, with_leases, noncurrent).value == 400e6


def test_xom_2010_year_end_mistag_is_not_read():
    plain = fact("debt_current", 345e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 12_227e6, WITH)
    noncurrent = fact("debt_noncurrent", 12_227e6, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, with_leases, noncurrent) is plain


def test_none_without_either():
    assert current_on_noncurrent_basis(None, None, None) is None


# Backlog #427: pairing on the date alone, one fact per fiscal label, a rounded plain figure.

XOM_NONCURRENT = 26_342e6  # any lease-inclusive non-current debt


def choose(plain_value, with_leases_value, noncurrent_value=XOM_NONCURRENT):
    plain = fact("debt_current", plain_value, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", with_leases_value, WITH)
    noncurrent = fact("debt_noncurrent", noncurrent_value, "LongTermDebtAndCapitalLeaseObligations")
    return current_on_noncurrent_basis(plain, with_leases, noncurrent)


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        (6.2e9, 10**8),  # Exxon's "$6.2 billion" (decimals -8)
        (1.617e9, 10**6),
        (1_000e6 + 617e6, 10**6),  # a float sum is read in whole dollars
        (1.7e9, 10**8),  # precise, but looks rounded: the known limit
        (0, 0),  # no unit, so no margin
        (-5e6, 10**6),
        (1e15, 10**12),  # capped
    ],
)
def test_rounding_unit(value, unit):
    assert rounding_unit(value) == unit


def test_a_precise_lease_inclusive_figure_inside_a_rounded_plain_one_is_taken():
    # "$6.2 billion" stands for 6,150M to 6,250M, so a precise 6,180M with leases agrees with it
    current = choose(6_200e6, 6_180e6)
    assert current.value == 6_180e6 and current.xbrl_concept == f"us-gaap:{WITH}"
    assert current.canonical_name == "debt_current"


@pytest.mark.parametrize(
    ("plain", "with_leases"),
    [
        (6_200e6, 6_140e6),  # 60M below: outside half the 100M unit
        (6_200e6, 6_100e6),  # no more precise than the plain figure (both look rounded to 10^8)
        (1_617e6, 1_616e6),  # a plain figure precise to the million opens no margin
        (20, 19),  # nor one that looks rounded only below ten million (the fixture's 20)
        (0, -5e6),  # a plain zero (AAPL and MSFT file some) opens no margin
    ],
)
def test_outside_the_rounding_keeps_the_plain_figure(plain, with_leases):
    current = choose(plain, with_leases)
    assert current.value == plain and current.xbrl_concept == "us-gaap:LongTermDebtCurrent"


def test_a_precise_plain_figure_ending_in_zeros_looks_rounded():
    # the known limit (design doc): 1,700M exactly looks rounded to 10^8, so 1,660M is taken
    assert choose(1_700e6, 1_660e6).value == 1_660e6


def test_the_mistag_guard_beats_the_rounding_margin():
    # a lease-inclusive figure equal to the non-current debt is never taken, rounded plain or not
    assert choose(6_200e6, 6_180e6, noncurrent_value=6_180e6).value == 6_200e6


def test_a_rounded_plain_figure_alone_is_read_unchanged():
    plain = fact("debt_current", 6_200e6, "LongTermDebtCurrent")
    noncurrent = fact("debt_noncurrent", XOM_NONCURRENT, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, None, noncurrent) is plain


def relabel_with_leases(conn, years_back=1):
    """File every lease-inclusive current figure under a fiscal year `years_back` earlier, as if
    its filings had placed the same dates on another fiscal calendar."""
    conn.execute(
        "UPDATE financial_facts SET fiscal_year = fiscal_year - ? WHERE xbrl_concept = ?",
        (years_back, f"us-gaap:{WITH}"),
    )
    conn.commit()


@pytest.mark.parametrize("frequency", ["reported", "annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_two_fiscal_labels_at_one_date_give_one_current_portion(make_company, mode, frequency):
    conn = make_company(lease_inclusive())
    before = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    relabel_with_leases(conn)
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    dates = [f.period_end for f in facts]
    assert len(dates) == len(set(dates))  # one current portion per date
    assert all(f.value == 24 for f in facts)  # the lease-inclusive figure, paired with the plain
    # each date keeps the plain figure's fiscal labels, where it sat before the relabel
    assert [(f.period_end, f.fiscal_year, f.fiscal_period) for f in facts] == [
        (f.period_end, f.fiscal_year, f.fiscal_period) for f in before
    ]


def at(item, value, tag, end):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{tag}",
        period_end=end,
        fiscal_year=2019,
        fiscal_period="FY",
        value=value,
        unit="USD",
        accession_no="0000034088-20-000016",
        filed_at=date(2020, 2, 26),
    )


def test_two_dates_under_one_fiscal_label_give_one_current_portion_by_label():
    # the plain figure at the year end, a lone lease-inclusive one three days earlier under the
    # same label: annual and quarterly reads keep one per label (the later date), as any item
    year_end, earlier = date(2019, 12, 31), date(2019, 12, 28)
    facts = [
        at("debt_current", 1_617e6, "LongTermDebtCurrent", year_end),
        at("debt_current_with_leases", 1_650e6, WITH, earlier),
        at("debt_noncurrent", XOM_NONCURRENT, "LongTermDebtAndCapitalLeaseObligations", year_end),
    ]
    annual = _merge_current(facts, ["debt_current"], "annual")
    assert [(f.period_end, f.value) for f in annual] == [(year_end, 1_617e6)]
    reported = _merge_current(facts, ["debt_current"], "reported")
    assert [f.period_end for f in reported] == [earlier, year_end]  # one per date
