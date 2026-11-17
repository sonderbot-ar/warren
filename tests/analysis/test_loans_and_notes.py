"""Coca-Cola's "Loans and notes payable" is read as its short-term borrowings (backlog #432):
the balance-sheet line holds its commercial paper and other short-term borrowings, so paper is
not counted beside it, and a quarter end reads its own line instead of a year end's figure.

The rows are limited to KO at ingest (`tests/fundamentals/test_ingest.py`); here the facts are
put straight into the fixture's table, which the map reads for any company."""

import pytest

from domains.analysis.reported import reported_period
from domains.fundamentals.concepts import concept_map_in_force
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import FY2019, Q1, build, by_key, put

# The fixture's balance sheet: current portion 20, non-current 180, current assets 300, cash 60,
# current liabilities 150, at every quarter and year end.
BEFORE_432 = "86f87e48e967e8eea964fb81e4acfc274db61be015fa155e1cde0c4fde82ad96"  # #426's map
BESIDE = "commercial_paper_beside_short_term"
LATER = ("2020-03-31", 2020, "Q1", "10-Q", "0000000123-20-000078", "2020-08-01")  # after AS_OF


def ko_quarter(conn, when=Q1):
    # Coca-Cola at 2023-12-31: commercial paper 4,209M + other 348M = the line 4,557M
    put(conn, "CommercialPaper", 70, when)
    put(conn, "NotesAndLoansPayable", 75, when)


def test_the_line_is_read_and_paper_not_added_beside_it(company):
    ko_quarter(company)
    result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 275  # 180 + 20 + 75: paper is inside the line
    short = rows[("balance:short_term_borrowings", "-")]
    assert short.value == 75
    assert "[NotesAndLoansPayable]" in short.method
    assert ("balance:commercial_paper", "-") not in rows
    assert [n for n in result.notes if n.code == BESIDE] == []


def test_through_the_map_before_it_paper_counts_in_place(company):
    ko_quarter(company)
    with concept_map_in_force(company, BEFORE_432, "TST"):
        rows = by_key(build(company))
    assert rows[("debt", "-")].value == 270  # 180 + 20 + 70: what a stored run rebuilds to
    assert ("balance:short_term_borrowings", "-") not in rows


def test_the_older_tag_is_read_too(company):
    # 2017-12-31 to 2019-09-27: the line is tagged NotesAndLoansPayableCurrent
    put(company, "CommercialPaper", 70, Q1)
    put(company, "NotesAndLoansPayableCurrent", 75, Q1)
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 275
    assert "[NotesAndLoansPayableCurrent]" in rows[("balance:short_term_borrowings", "-")].method


def test_a_quarter_end_reads_its_own_line_not_the_year_ends(company):
    # 2020-03-27: the line 13,657M; the year end's ShortTermBorrowings 10,994M was carried
    put(company, "ShortTermBorrowings", 40, FY2019)
    put(company, "NotesAndLoansPayable", 90, Q1)
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 290  # 180 + 20 + 90
    assert rows[("balance:short_term_borrowings", "-")].value == 90


def test_short_term_borrowings_of_the_same_date_are_read_first(company):
    # year ends 2019-2022: ShortTermBorrowings (priority 1) equals the line
    put(company, "ShortTermBorrowings", 75, Q1)
    put(company, "NotesAndLoansPayable", 76, Q1)
    put(company, "CommercialPaper", 70, Q1)
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 275
    assert "[ShortTermBorrowings]" in rows[("balance:short_term_borrowings", "-")].method


def test_a_line_filed_after_the_as_of_date_is_not_read(company):
    # 2017-12-31: the line was first tagged in a 10-Q ten months later
    put(company, "CommercialPaper", 70, Q1)
    put(company, "NotesAndLoansPayableCurrent", 75, LATER)
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 270  # paper in place, as before the rows
    assert ("balance:short_term_borrowings", "-") not in rows


def test_history_working_capital_takes_the_line_out_once(company):
    ko_quarter(company)
    with concept_map_in_force(company, BEFORE_432, "TST"):
        before = by_key(build(company))
    after = by_key(build(company))
    # the line is debt, so 5 more of current liabilities leave operating working capital
    nwc = [k for k in after if k[0] == "history:nwc"]
    assert nwc
    moved = [k for k in nwc if after[k].value != before[k].value]
    assert all(after[k].value == pytest.approx(before[k].value + 5) for k in moved)


def test_the_reported_view_reads_debt_the_same_way(company):
    ko_quarter(company)
    net_debt = reported_period(company, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(275 - 60)  # as the run: debt 275
    lines = {u["line"] for u in net_debt.uses}
    assert "short_term_borrowings" in lines and "commercial_paper" not in lines


def test_a_year_end_reads_its_line_not_last_years_borrowings(company):
    # analyst, design review: at 2023-12-31 the run read 2022-12-31's ShortTermBorrowings
    # (2,373M), carried within a year, and neither the paper (4,209M) nor the line (4,557M)
    a_year_before = ("2019-04-01", 2019, "Q1", "10-Q", "0000000123-19-000016", "2019-05-01")
    put(company, "ShortTermBorrowings", 40, a_year_before)
    ko_quarter(company)
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 275  # 180 + 20 + 75
    assert rows[("balance:short_term_borrowings", "-")].value == 75
