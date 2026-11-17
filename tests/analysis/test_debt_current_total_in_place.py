"""The filing's total debt due within one year is counted in place of its parts when none of
the parts is filed for the balance date (backlog #415: Exxon's and P&G's quarter ends, where
only the total is tagged, and Exxon before 2011, when only the total was filed)."""

from datetime import date
from functools import partial

import pytest

from domains.analysis import coded, text
from domains.analysis.math_engine import debt_parts, total_in_place
from domains.fundamentals.concepts import concept_map_in_force
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import BEFORE_408, FY2019, Q1, build, by_key, put

# The fixture's balance sheet: current portion 20, non-current 180, current assets 300, cash 60,
# current liabilities 150, at every quarter and year end.
CODE = "debt_current_total_in_place"


def notes(result, code=CODE):
    return [n for n in result.notes if n.code == code]


def year_end_parts(make_company):
    """Exxon's and P&G's presentation: the current portion only in the 10-K, never at a quarter
    end (the fixture tags it at every quarter end)."""

    def edit(tag, row):
        if tag == "LongTermDebtCurrent" and row["form"] == "10-Q":
            return None
        return row

    return make_company(edit)


def test_a_quarter_end_total_replaces_the_year_end_parts(make_company):
    # Exxon at 2020-06-30: the year-end parts carried would add to 20,494M, the quarter's own
    # total is 22,952M
    conn = year_end_parts(make_company)
    put(conn, "ShortTermBankLoansAndNotesPayable", 10, FY2019)
    put(conn, "CommercialPaper", 70, FY2019)
    put(conn, "DebtCurrent", 100, FY2019)
    put(conn, "DebtCurrent", 140, Q1)
    result = build(conn)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 320  # 140 + 180, not 280 (year-end parts 20 + 10 + 70)
    assert rows[("balance:debt_current_total", "-")].value == 140
    for part in ("debt_current", "short_term_borrowings", "commercial_paper"):
        assert (f"balance:{part}", "-") not in rows
    assert "counted in place of its parts" in rows[("debt", "-")].method
    [note] = notes(result)
    assert note.params == {
        "period_end": "2020-03-31",
        "debt_current_total": 140,
        "currency": "USD",
        "accession_no": "0000000123-20-000016",
        "parts_left_out": [
            {"item": "debt_current", "value": 20, "period_end": "2019-12-31", "reason": "older"},
            {
                "item": "short_term_borrowings",
                "value": 10,
                "period_end": "2019-12-31",
                "reason": "older",
            },
            {
                "item": "commercial_paper",
                "value": 70,
                "period_end": "2019-12-31",
                "reason": "older",
            },
        ],
        "assumptions": ["debt", "cost_of_debt", "nwc_pct"],
    }
    # the year-end parts are neither judged nor carried forward
    assert notes(result, "commercial_paper_beside_short_term") == []
    carried = [i["item"] for n in notes(result, "balance_carried_forward") for i in
               n.params["items"]]  # fmt: skip
    assert not {"debt_current", "short_term_borrowings", "commercial_paper"} & set(carried)


def test_a_total_with_no_part_ever_filed_is_counted(make_company):
    # Exxon before February 2011: only the total was filed; its current debt counted as zero
    def no_current_portion(tag, row):
        return None if tag == "LongTermDebtCurrent" else row

    conn = make_company(no_current_portion)
    put(conn, "DebtCurrent", 40, Q1)
    result = build(conn)
    assert by_key(result)[("debt", "-")].value == 220  # 40 + 180, not 180
    [note] = notes(result)
    assert note.params["parts_left_out"] == []


def test_a_mistagged_part_at_the_balance_date_gives_way_to_the_total(company):
    # the fixture's current portion of 20 at 2020-03-31 is more than 1.5x that day's total of 12,
    # so it is a figure under the wrong tag, not one of the total's parts
    put(company, "DebtCurrent", 12, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 192  # 12 + 180, not 20 + 180
    [note] = notes(result)
    assert note.params["parts_left_out"] == [
        {
            "item": "debt_current",
            "value": 20,
            "period_end": "2020-03-31",
            "reason": "larger_than_total",
        }
    ]


def test_a_part_within_the_margin_keeps_the_parts(company):
    put(company, "DebtCurrent", 14, Q1)  # 20 is under 1.5 x 14: the parts are read as before
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 200
    assert notes(result) == []


def test_a_part_dated_at_the_balance_date_keeps_the_parts(company):
    # the fixture tags the current portion at every quarter end: the parts are read as before
    put(company, "DebtCurrent", 140, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 200  # 20 + 180
    assert notes(result) == []


def test_a_total_older_than_the_balance_date_is_not_used(make_company):
    conn = year_end_parts(make_company)
    put(conn, "DebtCurrent", 140, FY2019)  # no total at the 2020-03-31 balance date
    result = build(conn)
    assert by_key(result)[("debt", "-")].value == 200  # the year-end portion carried, as before
    assert notes(result) == []


def test_history_working_capital_takes_the_total_out(make_company):
    def no_current_portion(tag, row):
        return None if tag == "LongTermDebtCurrent" else row

    conn = make_company(no_current_portion)
    put(conn, "DebtCurrent", 40, FY2019)
    nwc = by_key(build(conn))[("history:nwc", "FY2019")]
    assert nwc.value == pytest.approx((300 - 60) - (150 - 40))
    assert "counted in place of its parts" in nwc.method
    assert "counted as zero: debt_current" not in nwc.method


def test_the_cost_of_debt_reads_the_total_at_a_year_end(make_company):
    def no_current_portion(tag, row):
        return None if tag == "LongTermDebtCurrent" else row

    conn = make_company(no_current_portion)
    put(conn, "DebtCurrent", 40, FY2019)
    cost = by_key(build(conn))[("cost_of_debt", "-")]
    assert "FY2019 220" in cost.method  # 40 + 180


def fact(item, value, day="2020-06-30"):
    return Fact(
        canonical_name=item,
        xbrl_concept="us-gaap:X",
        period_end=date.fromisoformat(day),
        value=value,
        unit="USD",
        accession_no="a",
        filed_at=date(2020, 8, 5),
    )


def getter(*facts):
    by_item = {f.canonical_name: f for f in facts}
    return lambda item: by_item.get(item)


def test_xom_2020_q2():
    # Exxon's 10-Q for 2020-06-30: Notes and loans payable 22,952M; parts from the 2019 10-K
    year_end = "2019-12-31"
    parts = (
        fact("debt_current", 1617, year_end),
        fact("short_term_borrowings", 316, year_end),
        fact("commercial_paper", 18561, year_end),
    )
    total, noncurrent = fact("debt_current_total", 22952), fact("debt_noncurrent", 47182)
    get = getter(*parts, total, noncurrent)
    in_place = total_in_place(get, date(2020, 6, 30))
    assert in_place is not None and in_place.left_out == parts
    debt, used, zero, _ = debt_parts(get, day=date(2020, 6, 30))
    assert debt == 22952 + 47182
    assert used == [total, noncurrent]
    assert "debt_current" not in zero


@pytest.mark.parametrize(
    "total_value, total_day, part_day, day",
    [
        (22952, "2020-06-30", "2020-06-30", "2020-06-30"),  # a part shares the date
        (22952, "2020-03-31", "2019-12-31", "2020-06-30"),  # the total isn't at the balance date
        (-1, "2020-06-30", "2019-12-31", "2020-06-30"),  # a negative total is not used
    ],
)
def test_not_in_place(total_value, total_day, part_day, day):
    paper = fact("commercial_paper", 18561, part_day)
    get = getter(paper, fact("debt_current_total", total_value, total_day))
    assert total_in_place(get, date.fromisoformat(day)) is None


def test_xom_2011_q1_a_part_far_above_the_total_is_not_one_of_its_parts():
    # Exxon's 10-Q for 2011-03-31 (0001193125-11-127973) tags its long-term debt, 12,316M, also
    # as the current portion; the total that day is 3,560M (design review of #415)
    day = "2011-03-31"
    wrong = fact("debt_current", 12316, day)
    short = fact("short_term_borrowings", 532, "2010-12-31")
    total, noncurrent = fact("debt_current_total", 3560, day), fact("debt_noncurrent", 12316, day)
    get = getter(wrong, short, total, noncurrent)
    in_place = total_in_place(get, date.fromisoformat(day))
    assert in_place is not None and in_place.left_out == (wrong, short)
    assert "larger than the total" in in_place.text
    debt, used, _, _ = debt_parts(get, day=date.fromisoformat(day))
    assert debt == 3560 + 12316  # not 12,316 + 12,316 + 532
    assert wrong not in used


def test_a_rounded_total_keeps_a_part_just_above_it():
    # JNJ at 2011-01-02: Loans and notes payable 7,617M, the total rounded to 7,600M
    day = "2011-01-02"
    get = getter(fact("short_term_borrowings", 7617, day), fact("debt_current_total", 7600, day))
    assert total_in_place(get, date.fromisoformat(day)) is None


def test_a_part_newer_than_the_total_keeps_the_parts():
    get = getter(
        fact("short_term_borrowings", 316, "2020-09-30"), fact("debt_current_total", 22952)
    )
    assert total_in_place(get) is None


def test_the_note_has_a_code_and_a_lesson():
    assert CODE in coded.RUN_NOTE_CODES
    assert text.WARNING_LESSONS[CODE].group == "data"


def test_the_reported_view_reads_debt_the_same_way(make_company):
    from domains.analysis.reported import reported_period

    conn = year_end_parts(make_company)
    put(conn, "CommercialPaper", 70, FY2019)
    put(conn, "DebtCurrent", 140, Q1)
    net_debt = reported_period(conn, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(320 - 60)  # as the run: debt 140 + 180
    assert "debt_current_total" in {u["line"] for u in net_debt.uses}
    assert "commercial_paper" not in {u["line"] for u in net_debt.uses}
    [note] = [n for n in net_debt.notes if n.code == CODE]
    assert "assumptions" not in note.params
    assert note.params["debt_current_total"] == 140


def test_a_map_without_the_total_reads_what_it_read_before(make_company):
    conn = year_end_parts(make_company)
    put(conn, "DebtCurrent", 140, Q1)
    with concept_map_in_force(conn, BEFORE_408, "TST"):
        result = build(conn)
    assert by_key(result)[("debt", "-")].value == 200  # the year-end portion carried
    assert notes(result) == []


# Tests the #415 reviews asked for (backlog #421 item 2 and the gatekeeper's ideas).
# the parts first filed as the comparative in the next annual report (P&G: the FY2010 10-K)
LATE_PARTS = ("2019-12-31", 2020, "FY", "10-K", "0000000123-20-000077", "2020-05-30")


def test_a_total_filed_before_its_parts_is_read_until_the_parts_are_public(make_company):
    # P&G FY2009: its total for 2009-06-30 was filed 2009-10-29, its parts first on 2010-08-13;
    # a history read between the two counts the total, and after the parts are public, the parts
    from domains.analysis.math_engine import load_history

    def no_year_end_portion(tag, row):
        return None if tag == "LongTermDebtCurrent" and row["end"] == "2019-12-31" else row

    conn = make_company(no_year_end_portion)
    put(conn, "DebtCurrent", 40, FY2019)  # filed 2020-02-15
    put(conn, "LongTermDebtCurrent", 20, LATE_PARTS)  # filed 2020-05-30
    day = date(2019, 12, 31)
    cases = ((date(2020, 3, 1), 40), (date(2020, 5, 29), 40), (date(2020, 5, 30), None))
    for as_of, counted in cases:
        history = load_history(conn, "0000000123", as_of)
        in_place = total_in_place(partial(history.latest_before, day=day), day)
        assert (in_place.total.value if in_place else None) == counted, as_of


def test_a_fiscal_years_total_dated_before_its_parts_is_not_used():
    # day None (a fiscal year's figures): the total's own date decides, and a part dated after
    # it keeps the parts
    total = fact("debt_current_total", 40, "2019-12-31")
    part = fact("debt_current", 20, "2020-03-31")
    assert total_in_place(getter(total, part)) is None


def test_a_zero_total_is_counted():
    # the filing says nothing is due within a year: zero is used, the older parts left out
    total = fact("debt_current_total", 0, "2020-06-30")
    part = fact("debt_current", 20, "2019-12-31")
    in_place = total_in_place(getter(total, part), date(2020, 6, 30))
    assert in_place is not None and in_place.total.value == 0
    total_debt, used, _, _ = debt_parts(getter(total, part, fact("debt_noncurrent", 180)))
    assert total_debt == 180
