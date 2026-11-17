"""The current portion of long-term debt is counted once when short-term borrowings already
include it (backlog #408: JNJ's Loans and notes payable)."""

from datetime import date

import pytest

from domains.analysis import coded, text
from domains.analysis.math_engine import build_inputs, current_debt_inside
from domains.fundamentals.concepts import concept_map_in_force
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF, CHOICES

# The fixture's balance sheet: current portion 20, non-current 180, current assets 300, cash 60,
# current liabilities 150, at every quarter and year end.
BEFORE_408 = "91062f49b580d57a8e37d4ef0809694ea7f53764f6bb2372d2ea788f25da2754"  # #341's map
Q1 = ("2020-03-31", 2020, "Q1", "10-Q", "0000000123-20-000016", "2020-04-30")
FY2019 = ("2019-12-31", 2019, "FY", "10-K", "0000000123-20-000099", "2020-02-15")


def build(conn):
    return build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def by_key(result):
    return {(a.name, a.period): a for a in result.assumptions}


def notes(result, code="debt_current_inside_short_term"):
    return [n for n in result.notes if n.code == code]


def put(conn, tag, value, when):
    end, fy, fp, form, accn, filed = when
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES ('0000000123', ?, NULL, ?, ?, ?, ?, 'USD', ?, ?, ?)",
        (f"us-gaap:{tag}", end, fy, fp, value, form, accn, filed),
    )


def test_inside_at_the_balance_date_counts_the_current_portion_once(company):
    put(company, "ShortTermBorrowings", 50, Q1)
    put(company, "DebtCurrent", 50, Q1)  # = short-term alone, not 50 + 20
    result = build(company)
    rows = by_key(result)
    assert rows[("debt", "-")].value == 230  # 180 + 50, not 250
    assert "already inside short-term borrowings" in rows[("debt", "-")].method
    assert ("balance:debt_current", "-") not in rows
    [note] = notes(result)
    assert note.params == {
        "period_end": "2020-03-31",
        "debt_current": 20,
        "short_term_borrowings": 50,
        "debt_current_total": 50,
        "currency": "USD",
        "accession_no": "0000000123-20-000016",
        "assumptions": ["debt", "cost_of_debt", "nwc_pct"],
    }
    assert not [n for n in result.notes if n.code == "balance_counted_zero" and
                "debt_current" in n.params["items"]]  # fmt: skip


def test_a_total_that_holds_both_parts_keeps_the_current_portion(company):
    put(company, "ShortTermBorrowings", 50, Q1)
    put(company, "DebtCurrent", 70, Q1)  # 50 + 20: presented separately
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 250
    assert notes(result) == []


def test_without_the_total_nothing_is_judged(company):
    put(company, "ShortTermBorrowings", 50, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 250
    assert notes(result) == []


def test_commercial_paper_in_place_of_borrowings_keeps_the_current_portion(company):
    put(company, "CommercialPaper", 50, Q1)
    put(company, "DebtCurrent", 50, Q1)
    result = build(company)
    assert by_key(result)[("debt", "-")].value == 250
    assert notes(result) == []


def test_a_year_end_portion_carried_beside_quarter_end_borrowings_is_left_out(make_company):
    # JNJ's 2019 quarters: the current portion is tagged only at the year end, and the
    # quarter's Loans and notes payable already hold it
    def year_end_only(tag, row):
        if tag == "LongTermDebtCurrent" and row["end"] == "2020-03-31":
            return None
        return row

    conn = make_company(year_end_only)
    put(conn, "ShortTermBorrowings", 40, FY2019)
    put(conn, "DebtCurrent", 40, FY2019)
    put(conn, "ShortTermBorrowings", 50, Q1)
    result = build(conn)
    assert by_key(result)[("debt", "-")].value == 230
    [note] = notes(result)
    assert note.params["period_end"] == "2019-12-31"
    assert note.params["short_term_borrowings"] == 40
    carried = [n for n in result.notes if n.code == "balance_carried_forward"]
    assert all(i["item"] != "debt_current" for n in carried for i in n.params["items"])


def test_history_working_capital_takes_the_current_portion_out_once(company):
    put(company, "ShortTermBorrowings", 50, FY2019)
    put(company, "DebtCurrent", 50, FY2019)
    nwc = by_key(build(company))[("history:nwc", "FY2019")]
    # (300 - 60) - (150 - 50): the 20 is inside the 50, so it is not taken out again
    assert nwc.value == pytest.approx(140)
    assert "already inside short-term borrowings" in nwc.method


def fact(item, value, day="2018-12-30"):
    return Fact(
        canonical_name=item,
        xbrl_concept="us-gaap:X",
        period_end=date.fromisoformat(day),
        value=value,
        unit="USD",
        accession_no="a",
        filed_at=date(2019, 2, 20),
    )


def lookup(*facts):
    return lambda item, day: next(
        (f for f in facts if f.canonical_name == item and f.period_end == day), None
    )


def test_jnj_2018_year_end_is_inside():
    current, short = fact("debt_current", 2600), fact("short_term_borrowings", 2796)
    total = fact("debt_current_total", 2800)
    assert current_debt_inside(current, short, lookup(short, total)) is not None


@pytest.mark.parametrize(
    "current, total, short_day",
    [
        (0, 2796, "2018-12-30"),  # no current portion to count twice
        (2600, 2796 + 1300, "2018-12-30"),  # equally near both: not shown to be inside
        (2600, 2800, "2018-09-30"),  # short-term figure older than the current portion
        (2600, 1000, "2018-12-30"),  # total far below short-term borrowings: a broken figure
    ],
)
def test_not_inside(current, total, short_day):
    c, s = fact("debt_current", current), fact("short_term_borrowings", 2796, short_day)
    t = fact("debt_current_total", total)
    assert current_debt_inside(c, s, lookup(s, t)) is None


def test_the_note_has_a_code_and_a_lesson():
    assert "debt_current_inside_short_term" in coded.RUN_NOTE_CODES
    assert text.WARNING_LESSONS["debt_current_inside_short_term"].group == "data"


def test_the_reported_view_reads_debt_the_same_way(company):
    from domains.analysis.reported import reported_period

    put(company, "ShortTermBorrowings", 50, Q1)
    put(company, "DebtCurrent", 50, Q1)
    net_debt = reported_period(company, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(180 + 50 - 60)  # as the run: debt 230
    assert {u["line"] for u in net_debt.uses} == {
        "debt_noncurrent",
        "short_term_borrowings",
        "cash",
    }
    [note] = [n for n in net_debt.notes if n.code == "debt_current_inside_short_term"]
    assert note.params["debt_current_total"] == 50
    assert "finance_leases_in_debt_tag" not in {n.code for n in net_debt.notes}


def test_a_map_without_the_check_item_reads_what_it_read_before(company):
    # a rebuild through a map made before #408 (its concepts table has no debt_current_total)
    put(company, "ShortTermBorrowings", 50, Q1)
    put(company, "DebtCurrent", 50, Q1)
    with concept_map_in_force(company, BEFORE_408, "TST"):
        result = build(company)
    assert by_key(result)[("debt", "-")].value == 250
    assert notes(result) == []


def test_the_reported_view_agrees_on_a_carried_year_end_portion(make_company):
    from domains.analysis.reported import reported_period

    def year_end_only(tag, row):
        if tag == "LongTermDebtCurrent" and row["end"] == "2020-03-31":
            return None
        return row

    conn = make_company(year_end_only)
    put(conn, "ShortTermBorrowings", 40, FY2019)
    put(conn, "DebtCurrent", 40, FY2019)
    put(conn, "ShortTermBorrowings", 50, Q1)
    net_debt = reported_period(conn, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert net_debt.value == pytest.approx(180 + 50 - 60)
    assert [n.params["period_end"] for n in net_debt.notes
            if n.code == "debt_current_inside_short_term"] == ["2019-12-31"]  # fmt: skip
