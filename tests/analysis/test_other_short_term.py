"""P&G's "Other" short-term borrowings are read as its short-term borrowings (backlog #426), so
its debt due within one year at a year end adds up to the filing's own total (DebtCurrent).

The row is limited to P&G at ingest (`tests/fundamentals/test_ingest.py`); here the facts are
put straight into the fixture's table, which the map reads for any company."""

import pytest

from domains.analysis.reported import reported_period
from domains.fundamentals.concepts import concept_map_in_force
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import FY2019, Q1, build, by_key, put
from tests.analysis.test_debt_current_total_in_place import year_end_parts

# The fixture's balance sheet: current portion 20, non-current 180, current assets 300, cash 60,
# current liabilities 150, at every quarter and year end.
BEFORE_426 = "52635076391aa4bde68acff2f69a10751bb0259aaa0a197ebb1934918a9da7fb"  # #421's map
BESIDE = "commercial_paper_beside_short_term"


def notes(result, code):
    return [n for n in result.notes if n.code == code]


def pg_year_end(conn, when=Q1):
    # P&G at 2021-06-30: current portion 3,620M + commercial paper 5,171M + other 98M = 8,889M
    put(conn, "OtherShortTermBorrowings", 5, when)
    put(conn, "CommercialPaper", 70, when)
    put(conn, "DebtCurrent", 95, when)  # 20 + 70 + 5


def test_the_other_line_is_counted_beside_commercial_paper(company):
    pg_year_end(company)
    result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 275  # 180 + 20 + 5 + 70: the total 95 in full
    short = rows[("balance:short_term_borrowings", "-")]
    assert short.value == 5
    assert "[OtherShortTermBorrowings]" in short.method
    assert rows[("balance:commercial_paper", "-")].value == 70
    [note] = notes(result, BESIDE)
    assert note.params["short_term_borrowings"] == 5
    assert note.params["debt_current"] == 20
    assert note.params["short_term_left_out"] is None
    assert notes(result, "debt_current_inside_short_term") == []


def test_through_the_map_before_it_the_other_line_is_not_read(company):
    pg_year_end(company)
    with concept_map_in_force(company, BEFORE_426, "TST"):
        result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 270  # 180 + 20 + 70: what a stored run rebuilds to
    assert ("balance:short_term_borrowings", "-") not in rows
    assert notes(result, BESIDE) == []


def test_bank_loans_at_the_same_date_are_read_first(company):
    # P&G at 2017-06-30 and 2018-06-30 (the design doc's limit): bank loans, priority 2, are read
    # and the other line, priority 3, is not
    put(company, "ShortTermBankLoansAndNotesPayable", 10, Q1)
    put(company, "OtherShortTermBorrowings", 5, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 105, Q1)  # 20 + 10 + 70 + 5
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 280  # 180 + 20 + 10 + 70; the 5 stays out
    assert (
        "[ShortTermBankLoansAndNotesPayable]" in rows[("balance:short_term_borrowings", "-")].method
    )


def test_bank_loans_filed_after_the_as_of_date_leave_the_other_line_read(company):
    # P&G's 2017-06-30 (analyst): the FY2017 10-K tags only the other line (173M); bank loans
    # of 0 for the same date were first filed in the FY2018 10-K, a year later
    pg_year_end(company)
    later = ("2020-03-31", 2020, "Q1", "10-K", "0000000123-20-000077", "2020-08-01")
    put(company, "ShortTermBankLoansAndNotesPayable", 0, later)  # after AS_OF: not public yet
    rows = by_key(build(company))
    assert rows[("debt", "-")].value == 275  # 180 + 20 + 5 + 70, as in the first test
    assert "[OtherShortTermBorrowings]" in rows[("balance:short_term_borrowings", "-")].method


def test_a_quarter_end_total_lists_the_other_line_as_an_older_part(make_company):
    conn = year_end_parts(make_company)
    pg_year_end(conn, FY2019)
    put(conn, "DebtCurrent", 140, Q1)  # the 10-Q tags only the total
    result = build(conn)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 320  # 140 + 180
    [note] = notes(result, "debt_current_total_in_place")
    assert {
        "item": "short_term_borrowings",
        "value": 5,
        "period_end": "2019-12-31",
        "reason": "older",
    } in note.params["parts_left_out"]


def test_the_reported_view_reads_debt_the_same_way(company):
    pg_year_end(company)
    net_debt = reported_period(company, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(275 - 60)  # as the run: debt 275
    assert {"short_term_borrowings", "commercial_paper"} <= {u["line"] for u in net_debt.uses}
    [note] = [n for n in net_debt.notes if n.code == BESIDE]
    assert note.params["short_term_borrowings"] == 5
