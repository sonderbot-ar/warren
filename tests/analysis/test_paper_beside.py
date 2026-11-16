"""Commercial paper is counted beside short-term borrowings when the filing's own total shows it
is a separate line (backlog #412: Exxon's and P&G's short-term bank loans beside commercial
paper)."""

from datetime import date

import pytest

from domains.analysis import coded, text
from domains.analysis.math_engine import debt_parts, paper_beside
from domains.fundamentals.concepts import concept_map_in_force
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import (
    BEFORE_408,
    FY2019,
    Q1,
    build,
    by_key,
    put,
)

# The fixture's balance sheet: current portion 20, non-current 180, current assets 300, cash 60,
# current liabilities 150, at every quarter and year end.
CODE = "commercial_paper_beside_short_term"


def notes(result):
    return [n for n in result.notes if n.code == CODE]


def test_paper_beside_bank_loans_is_counted(company):
    put(company, "ShortTermBankLoansAndNotesPayable", 10, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 100, Q1)  # 10 + 20 + 70: a line of its own
    result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 280  # 20 + 180 + 10 + 70, not 210
    assert rows[("balance:commercial_paper", "-")].value == 70
    assert "commercial paper counted beside" in rows[("debt", "-")].method
    [note] = notes(result)
    assert note.params == {
        "period_end": "2020-03-31",
        "commercial_paper": 70,
        "short_term_borrowings": 10,
        "debt_current": 20,
        "debt_current_total": 100,
        "currency": "USD",
        "accession_no": "0000000123-20-000016",
        "short_term_left_out": None,
        "short_term_left_out_period_end": None,
        "assumptions": ["debt", "cost_of_debt", "nwc_pct"],
    }


def test_short_term_borrowings_of_zero_beside_paper(company):
    # P&G at 2017-06-30: short-term bank loans tagged 0, commercial paper 11,705M
    put(company, "ShortTermBankLoansAndNotesPayable", 0, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 90, Q1)
    assert by_key(build(company))[("debt", "-")].value == 270


def test_paper_inside_short_term_borrowings_is_not_added(company):
    # Microsoft's or Coca-Cola's presentation: commercial paper is a part of short-term borrowings
    put(company, "ShortTermBorrowings", 80, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 100, Q1)  # 80 + 20: the paper is inside the 80
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 280
    assert ("balance:commercial_paper", "-") not in by_key(result)
    assert notes(result) == []


def test_without_the_total_paper_counts_only_in_place_of_borrowings(company):
    put(company, "ShortTermBankLoansAndNotesPayable", 10, Q1)
    put(company, "CommercialPaper", 70, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 210
    assert notes(result) == []


def test_paper_alone_is_still_counted_in_place_of_borrowings(company):
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 90, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 270
    assert notes(result) == []


def test_working_capital_takes_the_paper_out_too(company):
    put(company, "ShortTermBankLoansAndNotesPayable", 10, FY2019)
    put(company, "CommercialPaper", 70, FY2019)
    put(company, "DebtCurrent", 100, FY2019)
    nwc = by_key(build(company))[("history:nwc", "FY2019")]
    # (300 - 60) - (150 - 20 - 10 - 70)
    assert nwc.value == pytest.approx(190)
    assert "commercial paper counted beside" in nwc.method


def test_a_year_end_judgement_carries_to_a_quarter(make_company):
    # Exxon's quarters: the parts are tagged only at the year end, the total at every quarter
    def year_end_only(tag, row):
        if tag == "LongTermDebtCurrent" and row["end"] == "2020-03-31":
            return None
        return row

    conn = make_company(year_end_only)
    put(conn, "ShortTermBankLoansAndNotesPayable", 10, FY2019)
    put(conn, "CommercialPaper", 70, FY2019)
    put(conn, "DebtCurrent", 100, FY2019)
    put(conn, "DebtCurrent", 140, Q1)
    result = build(conn)
    assert by_key(result)[("debt", "-")].value == 280
    [note] = notes(result)
    assert note.params["period_end"] == "2019-12-31"


def test_an_older_short_term_line_gives_way_to_this_dates_paper(company):
    # P&G at 2019-06-30: bank loans last tagged at the 2018 year end, paper at every year end;
    # the 2019 total holds only paper and the current portion (review of #412)
    put(company, "ShortTermBankLoansAndNotesPayable", 10, FY2019)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 90, Q1)  # 20 + 70, no bank loans
    result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 270  # 20 + 180 + 70, not 210 (10 carried, paper dropped)
    assert ("balance:short_term_borrowings", "-") not in rows
    assert "left out: not tagged at 2020-03-31" in rows[("debt", "-")].method
    [note] = notes(result)
    assert note.params["short_term_borrowings"] == 0
    assert note.params["short_term_left_out"] == 10
    assert note.params["short_term_left_out_period_end"] == "2019-12-31"
    carried = [n for n in result.notes if n.code == "balance_carried_forward"]
    assert all(i["item"] != "short_term_borrowings" for n in carried for i in n.params["items"])


def test_an_older_short_term_line_stays_when_the_total_holds_it(company):
    put(company, "ShortTermBankLoansAndNotesPayable", 10, FY2019)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 30, Q1)  # fits neither sum with paper: not judged
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 210
    assert notes(result) == []


def fact(item, value, day="2018-06-30"):
    return Fact(
        canonical_name=item,
        xbrl_concept="us-gaap:X",
        period_end=date.fromisoformat(day),
        value=value,
        unit="USD",
        accession_no="a",
        filed_at=date(2018, 8, 7),
    )


def lookup(*facts):
    return lambda item, day: next(
        (f for f in facts if f.canonical_name == item and f.period_end == day), None
    )


def test_pg_2018_year_end_is_beside():
    # P&G's 10-K for FY2018 (0000080424-18-000055), in millions
    short, paper = fact("short_term_borrowings", 800), fact("commercial_paper", 7761)
    current, total = fact("debt_current", 1772), fact("debt_current_total", 10423)
    beside = paper_beside(short, paper, lookup(current, total))
    assert beside is not None and beside.current == 1772
    debt, _, _, _ = debt_parts(lookup_get(short, paper, current, total))
    assert debt == 800 + 7761 + 1772


def lookup_get(*facts):
    by_item = {f.canonical_name: f for f in facts}
    return lambda item: by_item.get(item)


def test_pg_2019_year_end_reads_this_years_paper():
    # P&G's 10-K for FY2019 (0000080424-19-000050): no bank loans tagged; 800 carried from 2018
    day = "2019-06-30"
    short, paper = fact("short_term_borrowings", 800), fact("commercial_paper", 6183, day)
    current, total = fact("debt_current", 3388, day), fact("debt_current_total", 9697, day)
    beside = paper_beside(short, paper, lookup(current, total))
    assert beside is not None and beside.stale
    debt, used, _, _ = debt_parts(lambda i: {f.canonical_name: f for f in (short, paper, current,
                                  total)}.get(i), lookup(current, total))  # fmt: skip
    assert debt == 3388 + 6183
    assert short not in used


def test_xom_2019_year_end_is_beside():
    day = "2019-12-31"
    short, paper = fact("short_term_borrowings", 316, day), fact("commercial_paper", 18561, day)
    current, total = fact("debt_current", 1617, day), fact("debt_current_total", 20578, day)
    assert paper_beside(short, paper, lookup(current, total)) is not None


@pytest.mark.parametrize(
    "paper, total, paper_day",
    [
        (0, 2572, "2018-06-30"),  # no paper to add
        (7761, 2572 + 7761 / 2, "2018-06-30"),  # equally near both sums: not shown
        (7761, 10423, "2018-03-31"),  # paper older than the short-term figure
        (7761, 2572 + 7761 * 3, "2018-06-30"),  # total far above both: a broken figure
    ],
)
def test_not_beside(paper, total, paper_day):
    short, p = fact("short_term_borrowings", 800), fact("commercial_paper", paper, paper_day)
    current, t = fact("debt_current", 1772), fact("debt_current_total", total)
    assert paper_beside(short, p, lookup(current, t)) is None


def test_the_note_has_a_code_and_a_lesson():
    assert CODE in coded.RUN_NOTE_CODES
    assert text.WARNING_LESSONS[CODE].group == "data"


def test_the_reported_view_reads_debt_the_same_way(company):
    from domains.analysis.reported import reported_period

    put(company, "ShortTermBankLoansAndNotesPayable", 10, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 100, Q1)
    net_debt = reported_period(company, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(280 - 60)  # as the run: debt 280
    assert "commercial_paper" in {u["line"] for u in net_debt.uses}
    [note] = [n for n in net_debt.notes if n.code == CODE]
    assert "assumptions" not in note.params
    assert note.params["commercial_paper"] == 70


def test_a_map_without_the_check_item_reads_what_it_read_before(company):
    put(company, "ShortTermBankLoansAndNotesPayable", 10, Q1)
    put(company, "CommercialPaper", 70, Q1)
    put(company, "DebtCurrent", 100, Q1)
    with concept_map_in_force(company, BEFORE_408, "TST"):
        result = build(company)
    assert by_key(result)[("debt", "-")].value == 210
    assert notes(result) == []
