"""Coca-Cola only: the gain or loss on paying debt off early read inside interest (backlog #618).

Coca-Cola books that gain or loss in its interest expense line, so its cost of debt takes it out
(backlog #610). Another company's `GainsLossesOnExtinguishmentOfDebt` may sit outside interest,
or be mis-tagged: EDGAR's company-concept API gives Walmart -3,136M for FY2018 (its own loss on
extinguishment line, outside interest) and -8,368M for FY2019 (a year with no such charge in the
10-K's text that the #613 analyst found; read from the API, not checked against the filing). Taking
those out of Walmart's interest would be wrong. Under ASC 470-50 the gain or loss is recognised in
income, and where a company presents it is its own choice, so each company's line must be read in
its own filings before the item is widened.
"""

from domains.analysis.math_engine import EXTINGUISHMENT
from domains.fundamentals.concepts import load_concept_map

WHY = (
    "debt_extinguishment_in_interest is read for Coca-Cola only (backlog #610, #618): another "
    "company's GainsLossesOnExtinguishmentOfDebt may sit outside interest or be mis-tagged "
    "(Walmart: -3,136M FY2018, its own line outside interest; -8,368M FY2019, no such charge). "
    "Check the company's interest line in its own 10-K text before widening the row."
)


def test_the_extinguishment_item_is_limited_to_coca_cola():
    rows = [r for r in load_concept_map() if r.canonical_name == EXTINGUISHMENT]
    assert rows, "the map has no debt_extinguishment_in_interest row"
    for row in rows:
        assert row.companies == frozenset({"KO"}), WHY


def test_no_other_company_reads_the_item():
    from domains.fundamentals.universe import load_universe

    rows = [r for r in load_concept_map() if r.canonical_name == EXTINGUISHMENT]
    for company in load_universe():
        reads = any(r.applies_to(company.ticker) for r in rows)
        assert reads == (company.ticker == "KO"), f"{company.ticker}: {WHY}"
