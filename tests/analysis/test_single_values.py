"""History for the single values behind an answer (backlog #476)."""

from datetime import date, timedelta

import pytest

from domains.analysis.inputs import inputs_behind
from domains.analysis.math_engine import UserChoice
from domains.analysis.runs import run_baseline
from domains.analysis.schemas import SINGLE
from domains.analysis.single_values import (
    BALANCE_NOTES,
    CELL_NOTES,
    MISSING_REASONS,
    NOT_COMPUTABLE,
    POINT_NOTES,
    SERIES_NOTES,
)
from tests.analysis.conftest import AS_OF, BALANCE, CHOICES

VPS = [("value_per_share", SINGLE)]
SINGLE_CELLS = (
    "risk_free",
    "beta",
    "erp",
    "debt",
    "cash_and_investments",
    "minority_interest",
    "cost_of_debt",
    "shares",
    "terminal_growth",
)


@pytest.fixture
def run(company):
    return company, run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _cell(answer, name):
    return next(c for c in answer.cells if c.name == name)


def _primary(cell):
    return next(s for s in cell.history if s.primary)


def test_each_single_value_has_history_and_its_used_point_is_the_row(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    for name in SINGLE_CELLS:
        cell = _cell(answer, name)
        assert cell.gap is None and cell.history, name
        (used,) = [p for p in _primary(cell).points if p.used]
        assert used.value == pytest.approx(cell.rows[0].value, rel=1e-12, abs=1e-12), name
        assert not any(n.code == "run_read_differently" for n in used.notes), name


def test_every_code_is_from_the_closed_lists(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS, years=10)
    point_codes = {*BALANCE_NOTES, *POINT_NOTES}
    for name in SINGLE_CELLS:
        cell = _cell(answer, name)
        assert {n.code for n in cell.notes} <= set(CELL_NOTES)
        for series in cell.history:
            assert {n.code for n in series.notes} <= set(SERIES_NOTES)
            for p in series.points:
                assert {n.code for n in p.notes} <= point_codes, (name, p.period)
                if p.missing is not None:
                    assert p.missing.code == NOT_COMPUTABLE
                    assert p.missing.params["reason"] in MISSING_REASONS


def test_market_series_are_monthly_and_end_at_the_run_date(run):
    conn, run_id = run
    for years in (3, 5):
        answer = inputs_behind(conn, run_id, VPS, years=years)
        for name in ("risk_free", "beta"):
            points = _primary(_cell(answer, name)).points
            assert len(points) == years * 12 + 1
            assert points[-1].period == AS_OF.isoformat() and points[-1].used
            expected = ["beta_std_error", "run_date"] if name == "beta" else ["run_date"]
            assert [n.code for n in points[-1].notes] == expected
            assert points[-2].period == "2020-06-01" and points[0].fiscal_year is None
            assert sum(p.used for p in points) == 1


def test_a_market_point_reads_nothing_on_or_after_its_own_date(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    for p in _primary(_cell(answer, "risk_free")).points:
        assert p.period_end < date.fromisoformat(p.period)  # the last yield before the date
    for p in _primary(_cell(answer, "beta")).points:
        assert p.period_end <= date.fromisoformat(p.period)  # the last return week
        (raw,) = p.parts
        assert raw.name == "raw_beta"
        assert raw.period.split("/")[1] == p.period_end.isoformat()


def test_terminal_growth_follows_the_risk_free_card(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    growth, rate = _cell(answer, "terminal_growth"), _cell(answer, "risk_free")
    assert [n.code for n in growth.notes] == ["follows_risk_free"]
    assert growth.history == rate.history


def test_cells_computed_from_others_point_to_them(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    value = _cell(answer, "equity_market_value")
    assert value.gap.code == "computed_from_other_cells" and not value.history
    assert [i["name"] for i in value.gap.params["inputs"]] == ["price", "shares"]
    assert _cell(answer, "roll_years").gap.code == "computed_from_other_cells"


def test_the_erp_adds_one_year_per_point(company):
    choices = {**CHOICES, "erp_first_year": UserChoice("erp_first_year", "2008", "test", "", "")}
    run_id = run_baseline(company, "TST", AS_OF, choices=choices, today=AS_OF)
    erp = _cell(inputs_behind(company, run_id, VPS), "erp")
    points = _primary(erp).points
    assert [p.period for p in points] == ["2015", "2016", "2017", "2018", "2019"]
    assert [p.used for p in points] == [False] * 4 + [True]
    # from 2008 a window needs ten years: 2015 and 2016 are too short
    for p in points[:2]:
        assert p.value is None and p.missing.params["reason"] == "erp_too_few_years"
    names = [q.name for q in points[-1].parts]
    assert names == ["^SP500TR_total_return", "DGS10_bond_total_return", "erp_std_error"]
    assert _primary(erp).notes[0].params == {"first_year": 2008}


def test_balance_points_are_the_engines_balance_step(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    debt = _primary(_cell(answer, "debt"))
    assert debt.notes[0].code == "book_value"
    (used,) = [p for p in debt.points if p.used]
    assert used.period == "2020-03-31"  # the run's balance date
    for p in debt.points:
        assert p.period_end < AS_OF
        assert p.value == sum(q.value for q in p.parts)
        assert p.value == BALANCE["LongTermDebtCurrent"] + BALANCE["LongTermDebtNoncurrent"]
        assert all(q.filing["accession_no"] for q in p.parts)
    minority = _primary(_cell(answer, "minority_interest"))
    assert all(p.value == BALANCE["MinorityInterest"] for p in minority.points)


def test_cost_of_debt_by_year_with_its_parts(run):
    conn, run_id = run
    answer = inputs_behind(conn, run_id, VPS)
    cell = _cell(answer, "cost_of_debt")
    points = _primary(cell).points
    (used,) = [p for p in points if p.used]
    assert used.period == "FY2019"
    assert {q.name for q in used.parts} == {
        "interest_expense",
        "debt_current",
        "debt_noncurrent",
    }
    last = points[-1]
    assert last.period == "FY2020" and last.value is None
    # FY2020 is in progress on 2020-06-30: its 10-K is not filed yet, not "reports no interest"
    assert last.missing.params == {
        "reason": "not_filed_yet",
        "fiscal_year": 2020,
        "period_end": "2020-12-31",
    }
    assert all(
        p.missing is None or p.missing.params["reason"] != "not_filed_yet" for p in points[:-1]
    )


def test_shares_are_split_adjusted_to_the_run_price_date(make_company):
    conn = make_company(None)
    # a 4-for-1 split between two cover-page counts
    conn.execute(
        "UPDATE prices SET split_ratio = 4 WHERE ticker = 'TST' AND date = "
        "(SELECT MIN(date) FROM prices WHERE ticker = 'TST' AND date >= '2019-06-01')"
    )
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = inputs_behind(conn, run_id, VPS)
    cover, diluted, yearly = _cell(answer, "shares").history
    assert cover.primary and not diluted.primary and not yearly.primary
    before = [p for p in cover.points if p.period_end < date(2019, 6, 1)]
    after = [p for p in cover.points if p.period_end >= date(2019, 6, 1)]
    assert before and after
    for p in before:
        assert p.value == 400 and p.parts[0].value == 100
        (note,) = p.notes
        assert note.code == "split_adjusted" and note.params["factor"] == 4
    assert all(p.value == 100 and not p.notes for p in after)
    (used,) = [p for p in cover.points if p.used]
    assert used is after[-1]


def test_a_run_read_differently_is_marked_on_a_single_value(run):
    conn, run_id = run
    conn.execute(
        "UPDATE assumptions SET value = value * 1.1 WHERE run_id = ? AND name = 'beta'",
        (run_id,),
    )
    answer = inputs_behind(conn, run_id, VPS)
    (used,) = [p for p in _primary(_cell(answer, "beta")).points if p.used]
    (note,) = [n for n in used.notes if n.code == "run_read_differently"]
    assert note.params["run_value"] == pytest.approx(1.1 * used.value)


def test_a_balance_filed_after_the_run_date_is_never_read(make_company):
    late = "0000000123-99-999999"

    def late_debt(tag, row):
        if tag == "LongTermDebtNoncurrent" and row["end"] == "2019-12-31" and row["form"] == "10-K":
            return [(tag, row), (tag, {**row, "val": 999, "accn": late, "filed": "2020-08-01"})]
        return row

    conn = make_company(late_debt)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    debt = _primary(_cell(inputs_behind(conn, run_id, VPS), "debt"))
    assert all(p.value == 200 for p in debt.points)
    assert late not in {q.filing["accession_no"] for p in debt.points for q in p.parts}


def test_an_unlisted_market_failure_keeps_the_list_closed():
    from domains.analysis.single_values import _not_computable
    from domains.market.store import MarketDataError

    known = _not_computable(MarketDataError("x", code="market_year_end_missing", params={}))
    assert known.params["reason"] == "market_year_end_missing"
    other = _not_computable(MarketDataError("y", params={"a": 1}))  # e.g. a code-less failure
    assert other.params == {"reason": "market_data_error", "a": 1, "error_code": None}
    assert other.params["reason"] in MISSING_REASONS


# -- backlog #481: beta's standard error, a cost of debt below the yield, the what-if floor -------


def test_every_computed_beta_point_says_how_loose_it_is(run):
    from domains.analysis import financial_math as fm

    conn, run_id = run
    points = _primary(_cell(inputs_behind(conn, run_id, VPS), "beta")).points
    computed = [p for p in points if p.value is not None]
    assert computed
    for p in computed:
        (note,) = [n for n in p.notes if n.code == "beta_std_error"]
        assert note.params["std_error"] == pytest.approx(
            fm.BLUME_WEIGHT * note.params["raw_std_error"]
        )
        assert note.params["raw_std_error"] > 0 and note.params["weeks"] == 104
    assert all(not any(n.code == "beta_std_error" for n in p.notes) for p in points if p.missing)


def test_a_book_cost_of_debt_above_the_yield_has_no_note(run):
    conn, run_id = run  # Test Corp: 4% book cost against a 3% yield
    points = _primary(_cell(inputs_behind(conn, run_id, VPS), "cost_of_debt")).points
    assert not any(n.code == "below_risk_free" for p in points for n in p.notes)


def test_a_book_cost_of_debt_below_the_yield_says_so(make_company):
    def cheap_interest(tag, row):  # half the interest: a 2% book cost against a 3% yield
        if tag == "InterestExpense":
            return {**row, "val": row["val"] / 2}
        return row

    conn = make_company(cheap_interest)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = inputs_behind(conn, run_id, VPS, years=5)
    rf_row = _cell(answer, "risk_free").rows[0].value
    points = [p for p in _primary(_cell(answer, "cost_of_debt")).points if p.value is not None]
    assert points
    for p in points:
        (note,) = [n for n in p.notes if n.code == "below_risk_free"]
        assert note.params["cost_of_debt"] == p.value < note.params["risk_free"]
        assert date.fromisoformat(note.params["risk_free_date"]) < AS_OF
        if p.used:
            assert note.params["against"] == "run_risk_free"
            assert note.params["risk_free"] == rf_row
        else:
            assert note.params["against"] == "year_average_yield"
            first = date.fromisoformat(note.params["risk_free_from"])
            last = date.fromisoformat(note.params["risk_free_date"])
            # the fiscal year's own dates: Test Corp's calendar years start on 1 January (#499)
            assert date(p.period_end.year, 1, 1) <= first <= last <= p.period_end
            assert note.params["observations"] >= 50  # weekly yields over a year
            assert note.params["risk_free"] == pytest.approx(0.03)


def _floored_child(conn, parent):
    from domains.analysis.whatif import Change, revalue

    changes = [Change("debt", delta=100.0, use="buyback"), Change("risk_free", value=0.05)]
    return revalue(conn, parent, changes).run_id


def test_a_floored_what_if_says_its_cost_of_debt_is_the_floor(run):
    conn, parent = run
    child = _floored_child(conn, parent)
    answer = inputs_behind(conn, child, VPS)
    cell = _cell(answer, "cost_of_debt")
    (note,) = [n for n in cell.notes if n.code == "floored_at_risk_free"]
    parent_kd = _cell(inputs_behind(conn, parent, VPS), "cost_of_debt").rows[0].value
    assert note.params["value"] == cell.rows[0].value == _cell(answer, "risk_free").rows[0].value
    assert note.params["book_cost_of_debt"] == pytest.approx(parent_kd)
    assert note.params["book_year"] == "FY2019" and note.params["parent_run_id"] == parent
    assert note.params["cell"] == "risk_free" and note.params["risk_free_changed"] is True
    points = _primary(cell).points
    assert not any(p.used for p in points)
    assert any(p.period == "FY2019" and p.value == pytest.approx(parent_kd) for p in points)


def test_a_what_if_that_does_not_floor_has_no_floor_note(run):
    from domains.analysis.whatif import Change, revalue

    conn, parent = run
    child = revalue(conn, parent, [Change("debt", delta=100.0, use="buyback")]).run_id
    cell = _cell(inputs_behind(conn, child, VPS), "cost_of_debt")
    assert not any(n.code == "floored_at_risk_free" for n in cell.notes)


def test_the_used_years_note_agrees_with_the_what_if_floor(run):
    """An older run whose stored cost of debt differs from today's read: the note on the used
    year compares the run's own two rows, as the what-if floor does (analyst, #481)."""
    from domains.analysis.whatif import Change, revalue

    conn, run_id = run
    conn.execute(  # the run read 2.5%: below the 3% yield, though the year now reads 4%
        "UPDATE assumptions SET value = 0.025 WHERE run_id = ? AND name = 'cost_of_debt'",
        (run_id,),
    )
    cell = _cell(inputs_behind(conn, run_id, VPS), "cost_of_debt")
    (used,) = [p for p in _primary(cell).points if p.used]
    (note,) = [n for n in used.notes if n.code == "below_risk_free"]
    assert note.params["cost_of_debt"] == 0.025
    assert any(n.code == "run_read_differently" for n in used.notes)
    child = revalue(conn, run_id, [Change("debt", delta=100.0, use="buyback")])
    assert {c.name: c.how for c in child.changes}["cost_of_debt"] == "floored_at_risk_free"


# -- diluted shares by fiscal year, and the fourth quarters (backlog #481 item 4) ------------------

DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"
NO_COVER = date(2020, 3, 15)  # after the FY2019 10-K (2020-02-15), before the Q1 10-Q


def _without_cover(conn):
    conn.execute(
        "DELETE FROM financial_facts WHERE xbrl_concept LIKE '%EntityCommonStockSharesOutstanding'"
    )


def test_diluted_counts_come_by_quarter_and_by_year_with_each_fourth_quarter_coded(run):
    conn, run_id = run
    cover, diluted, yearly = _cell(inputs_behind(conn, run_id, VPS), "shares").history
    assert (diluted.measure, diluted.frequency) == ("diluted_shares", "quarter")
    assert (yearly.measure, yearly.frequency) == ("diluted_shares", "year")
    assert cover.primary and not diluted.primary and not yearly.primary
    assert [p.period for p in yearly.points] == [f"FY{y}" for y in range(2015, 2020)]
    for p in yearly.points:
        assert p.value == 100 and p.fiscal_period == "FY" and not p.used
        assert p.period_end == date(p.fiscal_year, 12, 31)
        assert p.parts[0].filing["form"] == "10-K"
    gaps = [p for p in diluted.points if p.missing is not None]
    assert [p.period for p in gaps] == [f"FY{y}Q4" for y in range(2015, 2020)]
    for p in gaps:
        assert p.value is None and not p.used and p.fiscal_period == "Q4"
        assert p.missing.code == NOT_COMPUTABLE
        assert p.missing.params == {
            "reason": "no_fourth_quarter_count",
            "fiscal_year": p.fiscal_year,
            "annual_period": f"FY{p.fiscal_year}",
        }
        assert p.period_end == date(p.fiscal_year, 12, 31)
    # every other quarter has its count, in fiscal order, ending at the newest 10-Q
    filed = [p for p in diluted.points if p.missing is None]
    assert all(p.value == 100 and p.fiscal_period in ("Q1", "Q2", "Q3") for p in filed)
    assert diluted.points[-1].period == "FY2020Q1"
    assert diluted.points == sorted(diluted.points, key=lambda p: (p.fiscal_year, p.period[-2:]))


def test_a_year_with_no_quarter_in_the_window_opens_no_gap():
    from types import SimpleNamespace as Fact

    from domains.analysis.single_values import _fourth_quarter_gaps

    def fact(year, period):
        return Fact(fiscal_year=year, fiscal_period=period, period_end=date(year, 12, 31))

    # the window holds FY2021's count but none of its quarters (they end before the window), then
    # FY2022 in full and FY2023 open; Exxon-like FY2022 count missing in a second case
    quarterly = [fact(2022, q) for q in ("Q1", "Q2", "Q3")] + [fact(2023, "Q1")]
    gaps = _fourth_quarter_gaps(quarterly, [fact(2021, "FY"), fact(2022, "FY")])
    assert [(g.period, g.missing.params["annual_period"]) for g in gaps] == [("FY2022Q4", "FY2022")]
    (gap,) = _fourth_quarter_gaps(quarterly, [fact(2021, "FY")])
    assert gap.period == "FY2022Q4" and gap.missing.params["annual_period"] is None
    assert gap.period_end is None and "read no count" in gap.missing.text


def test_the_fallback_on_the_years_count_is_the_used_point_of_the_yearly_series(make_company):
    conn = make_company(None)
    _without_cover(conn)
    run_id = run_baseline(conn, "TST", NO_COVER, choices=CHOICES, today=AS_OF)
    cell = _cell(inputs_behind(conn, run_id, VPS), "shares")
    cover, diluted, yearly = cell.history
    assert not cover.points and not cover.primary
    assert not diluted.primary and not any(p.used for p in diluted.points)
    assert yearly.primary
    (used,) = [p for p in yearly.points if p.used]
    assert used.period == "FY2019" and used.value == pytest.approx(cell.rows[0].value)
    # the year has ended, but its 10-K files no fourth-quarter count
    (q4,) = [p for p in diluted.points if p.period == "FY2019Q4"]
    assert q4.missing.params["annual_period"] == "FY2019"


def test_a_fourth_quarter_count_filed_beside_the_year_is_its_own_point(make_company):
    def edit(tag, row):
        if tag == DILUTED and row["form"] == "10-K" and row["end"] == f"{row['fy']}-12-31":
            q4 = {**row, "start": f"{row['fy']}-10-01", "val": 99}
            return [(tag, row), (tag, q4)]
        return row

    conn = make_company(edit)
    _without_cover(conn)
    run_id = run_baseline(conn, "TST", NO_COVER, choices=CHOICES, today=AS_OF)
    cell = _cell(inputs_behind(conn, run_id, VPS), "shares")
    _cover, diluted, yearly = cell.history
    # FY2015's 10-K is older than the fixture's filings, so only its fourth quarter stays a gap
    assert [p.period for p in diluted.points if p.missing] == ["FY2015Q4"]
    q4s = {p.period: p.value for p in diluted.points if p.fiscal_period == "Q4" and not p.missing}
    assert q4s == {f"FY{y}Q4": 99 for y in range(2016, 2020)}
    # one used point across the two series, though the year and its fourth quarter share the
    # filing and the date
    used = [p for s in (diluted, yearly) for p in s.points if p.used]
    assert len(used) == 1 and used[0].value == pytest.approx(cell.rows[0].value)
    # the engine takes the quarter's count on a tie of dates (its quarterly counts come first)
    assert used[0].period == "FY2019Q4" and diluted.primary and not yearly.primary
    assert diluted.primary != yearly.primary


def test_an_open_year_without_its_count_has_no_fourth_quarter_gap(run):
    conn, run_id = run
    _cover, diluted, _yearly = _cell(inputs_behind(conn, run_id, VPS), "shares").history
    assert "FY2020Q4" not in {p.period for p in diluted.points}


# -- the diluted series' order and a year with no annual count (backlog #502) --------------------


def test_the_quarterly_series_sorts_on_the_quarters_number():
    from domains.analysis.single_values import _quarter_number

    assert [_quarter_number(p) for p in ("Q1", "Q2", "Q3", "Q4")] == [1, 2, 3, 4]
    # a label that is not a fiscal quarter is refused, never placed by its spelling
    for label in ("FY", "Q5", "q1", "H1", ""):
        with pytest.raises(ValueError, match="not a fiscal quarter"):
            _quarter_number(label)


def test_a_year_whose_10k_count_is_not_read_gets_a_gap_without_a_year(make_company):
    """Exxon's FY2009 and FY2010 on real data: a filed 10-K whose diluted count no mapped tag
    reads. End to end on Test Corp with FY2017's annual count dropped from every filing."""

    def edit(tag, row):
        year_long = row.get("start") == "2017-01-01" and row["end"] == "2017-12-31"
        return None if tag == DILUTED and year_long else row

    conn = make_company(edit)
    run_id = run_baseline(conn, "TST", NO_COVER, choices=CHOICES, today=AS_OF)
    _cover, diluted, yearly = _cell(inputs_behind(conn, run_id, VPS), "shares").history
    assert "FY2017" not in {p.period for p in yearly.points}
    assert {"FY2016", "FY2018", "FY2019"} <= {p.period for p in yearly.points}
    (gap,) = [p for p in diluted.points if p.period == "FY2017Q4"]
    assert gap.value is None and not gap.used and gap.period_end is None
    assert gap.missing.code == NOT_COMPUTABLE
    assert gap.missing.params == {
        "reason": "no_fourth_quarter_count",
        "fiscal_year": 2017,
        "annual_period": None,
    }
    assert "read no count for FY2017" in gap.missing.text
    assert "did not file" not in gap.missing.text
    # the neighbouring years keep their own year's count
    for year in (2016, 2018, 2019):
        (q4,) = [p for p in diluted.points if p.period == f"FY{year}Q4"]
        assert q4.missing.params["annual_period"] == f"FY{year}"
    # FY2017's three filed quarters stay in place, in fiscal order around the gap
    periods = [p.period for p in diluted.points]
    i = periods.index("FY2017Q4")
    assert periods[i - 3 : i + 2] == ["FY2017Q1", "FY2017Q2", "FY2017Q3", "FY2017Q4", "FY2018Q1"]


# -- the fair value of long-term debt beside the book debt (backlog #481 item 3) ---------------


def _fair_value(value=190, extra=()):
    """An edit filing `LongTermDebtFairValue` beside each non-current debt row, plus `extra`
    rows: (end, value, accn, filed)."""

    def edit(tag, row):
        if tag != "LongTermDebtNoncurrent":
            return row
        pairs = [(tag, row), ("LongTermDebtFairValue", {**row, "val": value})]
        if row["end"] == "2019-12-31" and row["form"] == "10-K":
            for end, val, accn, filed in extra:
                pairs.append(("LongTermDebtFairValue", {**row, "end": end, "val": val,
                                                        "accn": accn, "filed": filed}))  # fmt: skip
        return pairs

    return edit


def _fair_series(conn, run_id):
    debt = _cell(inputs_behind(conn, run_id, VPS), "debt")
    book, fair = debt.history
    return book, fair


def test_the_debt_card_has_an_empty_fair_value_series_when_none_is_filed(run):
    conn, run_id = run
    book, fair = _fair_series(conn, run_id)
    assert book.primary and book.measure == "debt"
    assert not fair.primary and fair.measure == "debt_fair_value" and fair.points == []
    (note,) = fair.notes
    assert note.code == "fair_value_not_read"
    assert note.params == {
        "known_on": AS_OF.isoformat(),
        "tag": "us-gaap:LongTermDebtFairValue",
        "left_out_dates": [],
    }
    for name in ("cash_and_investments", "minority_interest"):
        assert len(_cell(inputs_behind(conn, run_id, VPS), name).history) == 1


def test_the_filed_fair_value_sits_beside_the_book_debt_and_is_never_used(run, make_company):
    plain_conn, plain_id = run
    conn = make_company(_fair_value())
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    book, fair = _fair_series(conn, run_id)
    plain_book, _ = _fair_series(plain_conn, plain_id)
    assert book == plain_book  # the book series does not move
    assert fair.notes[0].code == "fair_value_as_filed"
    assert [p.period for p in fair.points] == [p.period for p in book.points]
    for p in fair.points:
        assert p.value == 190 and not p.used and p.fiscal_year is None
        (part,) = p.parts
        assert part.name == "debt_fair_value" and part.value == 190
        assert part.filing["accession_no"]
    # the valuation reads none of it: every answer to the value per share is the same
    plain = inputs_behind(plain_conn, plain_id, VPS)
    fair_answer = inputs_behind(conn, run_id, VPS)
    assert fair_answer.outputs == plain.outputs
    for c, d in zip(fair_answer.cells, plain.cells, strict=True):
        assert [r.value for r in c.rows] == [r.value for r in d.rows], c.name


def test_a_fair_value_is_read_point_in_time(make_company):
    before, after = "0000000123-99-000001", "0000000123-99-000002"
    conn = make_company(
        _fair_value(
            extra=[
                ("2019-12-31", 185, before, "2020-05-01"),  # restated before the run's date
                ("2019-12-31", 999, after, "2020-08-01"),  # and again after it
            ]
        )
    )
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _, fair = _fair_series(conn, run_id)
    (year_end,) = [p for p in fair.points if p.period == "2019-12-31"]
    assert year_end.value == 185
    assert year_end.parts[0].filing["accession_no"] == before
    accessions = {q.filing["accession_no"] for p in fair.points for q in p.parts}
    assert after not in accessions


def test_a_fair_value_off_the_balance_dates_is_left_out_and_listed(make_company):
    # Coca-Cola's 9,345M at 2010-10-02, the CCE deal's debt, beside its 2010-10-01 quarter end
    conn = make_company(_fair_value(extra=[("2019-11-15", 50, "0000000123-99-000003",
                                            "2020-02-15")]))  # fmt: skip
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    book, fair = _fair_series(conn, run_id)
    assert "2019-11-15" not in {p.period for p in fair.points}
    assert {p.period for p in fair.points} <= {p.period for p in book.points}
    assert fair.notes[0].params["left_out_dates"] == ["2019-11-15"]


# -- an interest line net of swap gains (backlog #542) ----------------------------------------

RATE_TAG = "DebtInstrumentInterestRateEffectivePercentage"
HEDGE = "interest_net_of_hedge_gains"
LATE_ACCESSION = "0000000123-20-000099"  # filed 2020-08-01, after AS_OF
FY2018_10K = "0000000123-19-000011"  # Test Corp's FY2018 10-K, filed 2019-02-15


def _hedged(
    make_company, monkeypatch, rates, first=2017, cheap=False, late=(), evidence="test filings"
):
    """Test Corp with a stated effective rate at each listed year end (filed in that year's
    10-K, or after `AS_OF` under its own accession `LATE_ACCESSION` for a year in `late`), the
    rate item read for TST and an interest caveat for TST from `first` citing `evidence`.
    `cheap` halves the interest (2% book cost, below the 3% yield)."""
    import dataclasses

    from domains.analysis import interest_caveats
    from domains.fundamentals import ingest

    real_map = ingest.load_concept_map

    def with_tst():
        return [
            dataclasses.replace(r, companies=r.companies | {"TST"})
            if r.canonical_name == "debt_effective_rate"
            else r
            for r in real_map()
        ]

    monkeypatch.setattr(ingest, "load_concept_map", with_tst)
    caveat = interest_caveats.InterestCaveat(
        "TST", HEDGE, first, None, "debt_effective_rate", evidence, ""
    )
    monkeypatch.setattr(
        interest_caveats,
        "caveat_for",
        lambda ticker, year: caveat if ticker == "TST" and caveat.covers(year) else None,
    )

    def edit(tag, row):
        if cheap and tag == "InterestExpense":
            row = {**row, "val": row["val"] / 2}
        if (
            tag == "LongTermDebtNoncurrent"
            and row["form"] == "10-K"
            and row["end"] == f"{row['fy']}-12-31"
            and row["fy"] in rates
        ):
            rate = {**row, "val": rates[row["fy"]]}
            if row["fy"] in late:
                rate |= {"filed": "2020-08-01", "accn": LATE_ACCESSION}
            return [(tag, row), (RATE_TAG, rate)]
        return row

    conn = make_company(edit)
    return conn, run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _cost_points(conn, run_id):
    cell = _cell(inputs_behind(conn, run_id, VPS, years=5), "cost_of_debt")
    return cell, [p for p in _primary(cell).points if p.value is not None]


def test_covered_years_carry_the_hedge_note_with_their_own_stated_rate(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2016: 0.05, 2017: 0.051, 2018: 0.052})
    _, points = _cost_points(conn, run_id)
    by_year = {p.fiscal_year: p for p in points}
    assert not any(n.code == HEDGE for n in by_year[2016].notes)  # before the caveat's first year
    for year in (2017, 2018):
        (note,) = [n for n in by_year[year].notes if n.code == HEDGE]
        params = note.params
        assert (params["fiscal_year"], params["from_fiscal_year"]) == (year, 2017)
        assert params["to_fiscal_year"] is None
        assert params["cost_of_debt"] == by_year[year].value
        assert params["effective_rate"] == {2017: 0.051, 2018: 0.052}[year]
        assert params["effective_rate_period"] == f"{year}-12-31"
        assert params["effective_rate_fiscal_year"] == year
        assert params["effective_rate_older"] is False
        assert params["effective_rate_filing"]["form"] == "10-K"
        assert params["below_effective_rate"] is True  # 4% book cost against about 5%
        assert params["below_risk_free"] is None  # 4% is above the 3% yield
        assert "currency swaps" in note.text and "since FY2017" in note.text


def test_a_missing_year_end_rate_falls_back_one_year_and_no_further(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2016: 0.05, 2018: 0.052})
    _, points = _cost_points(conn, run_id)
    by_year = {p.fiscal_year: p for p in points}
    (fy2019,) = [n for n in by_year[2019].notes if n.code == HEDGE]
    assert fy2019.params["effective_rate"] == 0.052
    assert fy2019.params["effective_rate_fiscal_year"] == 2018
    assert fy2019.params["effective_rate_older"] is True and "a year older" in fy2019.text
    (fy2017,) = [n for n in by_year[2017].notes if n.code == HEDGE]  # FY2016's rate is one older
    assert fy2017.params["effective_rate_fiscal_year"] == 2016
    conn, run_id = _hedged(make_company, monkeypatch, {2016: 0.05})
    _, points = _cost_points(conn, run_id)
    (fy2019,) = [n for p in points if p.fiscal_year == 2019 for n in p.notes if n.code == HEDGE]
    for key in ("effective_rate", "effective_rate_period", "effective_rate_filing"):
        assert fy2019.params[key] is None, key
    assert fy2019.params["below_effective_rate"] is None


def test_a_rate_filed_after_the_run_date_is_never_read(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052, 2019: 0.06}, late={2019})
    _, points = _cost_points(conn, run_id)
    (fy2019,) = [n for p in points if p.fiscal_year == 2019 for n in p.notes if n.code == HEDGE]
    assert fy2019.params["effective_rate"] == 0.052  # FY2018's, not the late-filed 6%
    assert date.fromisoformat(fy2019.params["effective_rate_filing"]["filed_at"]) <= AS_OF


def test_below_the_yield_the_comparison_moves_inside_the_hedge_note(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2017: 0.05, 2018: 0.05}, cheap=True)
    _, points = _cost_points(conn, run_id)
    by_year = {p.fiscal_year: p for p in points}
    # FY2016 is not covered: the generic note, as before
    assert [n.code for n in by_year[2016].notes] == ["below_risk_free"]
    for year in (2017, 2018, 2019):
        p = by_year[year]
        assert not any(n.code == "below_risk_free" for n in p.notes)
        (note,) = [n for n in p.notes if n.code == HEDGE]
        inner = note.params["below_risk_free"]
        assert inner["cost_of_debt"] == p.value < inner["risk_free"]
        assert inner["against"] == ("run_risk_free" if p.used else "year_average_yield")


def test_the_cell_carries_the_note_when_the_runs_own_year_is_covered(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052, 2019: 0.05})
    cell, points = _cost_points(conn, run_id)
    (used,) = [p for p in points if p.used]
    (on_cell,) = [n for n in cell.notes if n.code == HEDGE]
    (on_point,) = [n for n in used.notes if n.code == HEDGE]
    assert on_cell == on_point
    assert on_cell.params["cost_of_debt"] == cell.rows[0].value  # the run's own row
    assert set(n.code for n in cell.notes) <= set(CELL_NOTES)
    conn, run_id = _hedged(make_company, monkeypatch, {2019: 0.05}, first=2020)
    cell = _cell(inputs_behind(conn, run_id, VPS), "cost_of_debt")
    assert not any(n.code == HEDGE for n in cell.notes)


def test_a_floored_what_if_has_no_hedge_note_on_its_cell(make_company, monkeypatch):
    conn, parent = _hedged(make_company, monkeypatch, {2018: 0.052, 2019: 0.05})
    child = _floored_child(conn, parent)
    cell = _cell(inputs_behind(conn, child, VPS), "cost_of_debt")
    assert [n.code for n in cell.notes] == ["floored_at_risk_free"]
    assert any(n.code == HEDGE for p in _primary(cell).points for n in p.notes)


def test_hedge_note_codes_stay_in_the_closed_lists(make_company, monkeypatch):
    assert HEDGE in POINT_NOTES and HEDGE in CELL_NOTES
    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052}, cheap=True)
    answer = inputs_behind(conn, run_id, VPS, years=10)
    point_codes = {*BALANCE_NOTES, *POINT_NOTES}
    for name in SINGLE_CELLS:
        cell = _cell(answer, name)
        assert {n.code for n in cell.notes} <= set(CELL_NOTES)
        for series in cell.history:
            for p in series.points:
                assert {n.code for n in p.notes} <= point_codes


# -- a concepts table older than the map (backlog #548) ------------------------------------------


def _unsync(conn, item):
    """Drop an item's rows from the concepts table, as a database synced before it was added."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DELETE FROM concepts WHERE canonical_name = ?", (item,))
    conn.commit()


def test_a_stale_table_refuses_the_hedge_years_with_one_code(make_company, monkeypatch):
    from domains.analysis.inputs import InputsError

    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052})
    _unsync(conn, "debt_effective_rate")
    with pytest.raises(InputsError) as e:
        inputs_behind(conn, run_id, VPS)
    assert e.value.code == "concepts_not_synced"
    assert e.value.params == {"missing": ["debt_effective_rate"]}
    assert "ingest --all" in str(e.value)


def test_a_stale_table_refuses_the_fair_value_series_with_one_code(run):
    from domains.analysis.inputs import InputsError

    conn, run_id = run
    _unsync(conn, "debt_fair_value")
    with pytest.raises(InputsError) as e:
        inputs_behind(conn, run_id, VPS)
    assert (e.value.code, e.value.params) == (
        "concepts_not_synced",
        {"missing": ["debt_fair_value"]},
    )


def test_the_stale_table_refusal_reads_as_setup():
    from domains.analysis.coded import (
        ENGINE_REFUSAL_CODES,
        OTHER_REFUSAL_GROUPS,
        REFUSAL_GROUP_ORDER,
    )
    from domains.analysis.text import REFUSAL_GROUP_LESSONS, refusal_lesson

    assert not set(OTHER_REFUSAL_GROUPS) & ENGINE_REFUSAL_CODES
    assert set(OTHER_REFUSAL_GROUPS.values()) <= set(REFUSAL_GROUP_ORDER)
    assert refusal_lesson("concepts_not_synced") == REFUSAL_GROUP_LESSONS["setup"]


# -- a company with no caveat row keeps its notes (backlog #549) ---------------------------------


def _uncaveated_tickers():
    from domains.analysis.interest_caveats import load_interest_caveats
    from domains.fundamentals.universe import load_universe

    caveated = {c.ticker for c in load_interest_caveats()}
    return sorted(c.ticker for c in load_universe() if c.ticker not in caveated)


def _cost_notes(conn, run_id):
    cell = _cell(inputs_behind(conn, run_id, VPS, years=10), "cost_of_debt")
    return [cell.notes, *([s.notes, *(p.notes for p in s.points)] for s in cell.history)]


@pytest.mark.parametrize("ticker", _uncaveated_tickers())
def test_a_company_with_no_caveat_row_gets_the_notes_it_had_before(
    ticker, make_company, monkeypatch
):
    from domains.analysis import interest_caveats

    def cheap(tag, row):  # a 2% book cost below the 3% yield, so the years carry notes
        return {**row, "val": row["val"] / 2} if tag == "InterestExpense" else row

    conn = make_company(cheap)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    shipped = interest_caveats.caveat_for
    monkeypatch.setattr(interest_caveats, "caveat_for", lambda _t, year: shipped(ticker, year))
    with_file = _cost_notes(conn, run_id)
    monkeypatch.setattr(interest_caveats, "caveat_for", lambda _t, _year: None)
    without = _cost_notes(conn, run_id)
    assert with_file == without
    assert any(n.code == "below_risk_free" for p in with_file[1][1:] for n in p)


# -- the hedge note's evidence filings (backlog #551) -----------------------------------------


def _hedge_notes(conn, run_id):
    cell, points = _cost_points(conn, run_id)
    return [n for p in points for n in p.notes if n.code == HEDGE] + [
        n for n in cell.notes if n.code == HEDGE
    ]


def test_the_hedge_note_lists_only_evidence_filings_known_on_the_run_date(
    make_company, monkeypatch
):
    never = "0000000123-25-000001"  # an accession Warren has never ingested
    evidence = f"FY2018 10-K ({FY2018_10K}); later 10-K ({LATE_ACCESSION}); {never}; {FY2018_10K}"
    conn, run_id = _hedged(
        make_company, monkeypatch, {2018: 0.052, 2019: 0.06}, late={2019}, evidence=evidence
    )
    notes = _hedge_notes(conn, run_id)
    assert len(notes) >= 3  # FY2017–FY2019 points and the cell
    for note in notes:
        [filing] = note.params["evidence_filings"]  # the late and the unknown ones left out
        assert filing["accession_no"] == FY2018_10K
        assert (filing["form"], filing["filed_at"]) == ("10-K", "2019-02-15")
        assert "000012319000011" in filing["url"]
        assert date.fromisoformat(filing["filed_at"]) <= AS_OF


def test_evidence_without_an_accession_lists_no_filing(make_company, monkeypatch):
    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052})
    notes = _hedge_notes(conn, run_id)
    assert notes and all(n.params["evidence_filings"] == [] for n in notes)


# -- one year's cost-of-debt notes without the whole answer (backlog #550) ---------------------


def _same_as_chart(conn, run_id, years=5):
    """Every chart year's point and the cell's notes, through the helper, equal the chart's."""
    from domains.analysis.single_values import cost_of_debt_notes

    cell = _cell(inputs_behind(conn, run_id, VPS, years=years), "cost_of_debt")
    points = _primary(cell).points
    assert points
    for p in points:
        got = cost_of_debt_notes(conn, run_id, p.fiscal_year, years=years)
        assert got.run_id == run_id and got.fiscal_year == p.fiscal_year
        assert got.point == p, p.period
        assert got.cell_notes == cell.notes
    return cell, points


def test_each_years_notes_equal_the_charts(run):
    conn, run_id = run
    _same_as_chart(conn, run_id)


def test_no_year_means_the_runs_own_year(run):
    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = run
    _, points = _same_as_chart(conn, run_id)
    (used,) = [p for p in points if p.used]
    got = cost_of_debt_notes(conn, run_id)
    assert got.fiscal_year == used.fiscal_year == 2019 and got.point == used


def test_below_the_yield_notes_equal_the_charts(make_company):
    def cheap_interest(tag, row):
        return {**row, "val": row["val"] / 2} if tag == "InterestExpense" else row

    conn = make_company(cheap_interest)
    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _, points = _same_as_chart(conn, run_id)
    assert any(n.code == "below_risk_free" for p in points for n in p.notes)


def test_hedge_notes_equal_the_charts_on_the_points_and_the_cell(make_company, monkeypatch):
    for cheap in (False, True):
        rates = {2017: 0.05, 2018: 0.052, 2019: 0.05}
        conn, run_id = _hedged(make_company, monkeypatch, rates, cheap=cheap)
        cell, points = _same_as_chart(conn, run_id)
        assert any(n.code == HEDGE for n in cell.notes)
        assert sum(any(n.code == HEDGE for n in p.notes) for p in points) == 3


def test_a_year_the_run_read_differently_says_so_as_the_chart_does(run):
    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = run
    conn.execute(
        "UPDATE assumptions SET value = 0.025 WHERE run_id = ? AND name = 'cost_of_debt'",
        (run_id,),
    )
    _same_as_chart(conn, run_id)
    codes = [n.code for n in cost_of_debt_notes(conn, run_id).point.notes]
    assert codes == ["below_risk_free", "run_read_differently"]


def test_a_floored_what_if_has_no_own_year_and_its_cell_notes_are_the_charts(run):
    from domains.analysis.single_values import cost_of_debt_notes

    conn, parent = run
    child = _floored_child(conn, parent)
    cell, _ = _same_as_chart(conn, child)
    got = cost_of_debt_notes(conn, child)
    assert got.fiscal_year is None and got.point is None
    assert (
        [n.code for n in got.cell_notes] == ["floored_at_risk_free"] == [n.code for n in cell.notes]
    )


def test_a_year_with_no_interest_gives_its_reason(run):
    """Chart years with no cost of debt give the chart's reason (an eight-year chart reaches back
    to FY2013, with no interest, and FY2014, with no average debt)."""
    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = run
    _same_as_chart(conn, run_id, years=8)
    for year, reason in ((2013, "no_interest_reported"), (2014, "average_debt_not_positive")):
        got = cost_of_debt_notes(conn, run_id, year, years=8)
        assert got.point.value is None and got.point.notes == [] and not got.point.used
        assert got.point.missing.code == NOT_COMPUTABLE
        assert got.point.missing.params == {"reason": reason, "fiscal_year": year}


# -- a year outside the chart is refused (backlog #561) -----------------------------------------


def _outside(conn, run_id, year, years=None):
    from domains.analysis.inputs import InputsError
    from domains.analysis.single_values import cost_of_debt_notes

    with pytest.raises(InputsError) as e:
        cost_of_debt_notes(conn, run_id, year, years=years)
    assert e.value.code == "year_outside_window"
    return e.value.params


@pytest.mark.parametrize("years", [3, 5, 8, 10])
def test_the_window_is_the_charts_and_the_years_on_either_side_are_refused(run, years):
    conn, run_id = run
    _, points = _same_as_chart(conn, run_id, years=years)
    first, last = points[0].fiscal_year, points[-1].fiscal_year
    assert [p.fiscal_year for p in points] == list(range(first, last + 1))
    window = {"first_year": first, "last_year": last, "years": years}
    assert _outside(conn, run_id, first - 1, years) == {"fiscal_year": first - 1, **window}
    assert _outside(conn, run_id, last + 1, years) == {"fiscal_year": last + 1, **window}


def test_a_year_after_the_newest_filing_is_refused_not_read_as_no_interest(run):
    conn, run_id = run
    params = _outside(conn, run_id, 2021)
    assert params == {"fiscal_year": 2021, "first_year": 2016, "last_year": 2020, "years": 5}
    assert _outside(conn, run_id, 1990)["fiscal_year"] == 1990


def test_the_runs_own_year_is_answered_outside_the_window(run, monkeypatch):
    """The chart adds the run's own year when it is older than the window, so the call does."""
    from domains.analysis import single_values

    conn, run_id = run
    monkeypatch.setattr(single_values, "_cost_of_debt_used_year", lambda singles: 2015)
    got = single_values.cost_of_debt_notes(conn, run_id, 2015, years=3)
    assert got.fiscal_year == 2015 and got.point.used
    assert _outside(conn, run_id, 2016, years=3)["first_year"] == 2018


def test_a_history_with_no_revenue_has_no_window(run, monkeypatch):
    from domains.analysis import single_values

    conn, run_id = run
    monkeypatch.setattr(single_values, "_cost_of_debt_window", lambda singles: None)
    params = _outside(conn, run_id, 2018)
    assert params == {"fiscal_year": 2018, "first_year": None, "last_year": None, "years": 5}
    assert single_values.cost_of_debt_notes(conn, run_id).fiscal_year == 2019


@pytest.mark.parametrize("years", [2, 11])
def test_a_history_length_out_of_range_is_refused_as_inputs_behind_does(run, years):
    from domains.analysis.inputs import InputsError
    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = run
    with pytest.raises(InputsError) as e:
        cost_of_debt_notes(conn, run_id, years=years)
    with pytest.raises(InputsError) as f:
        inputs_behind(conn, run_id, VPS, years=years)
    assert e.value.code == f.value.code == "years_out_of_range"
    assert e.value.params == f.value.params


def test_one_year_reads_no_fiscal_calendar_and_no_other_cell(run, monkeypatch):
    from domains.analysis import inputs, single_values

    conn, run_id = run

    def refuse(*args, **kwargs):
        raise AssertionError("built more than the cost of debt")

    builders = (
        "_balances",
        "_balance_series",
        "_debt_fair_value",
        "_derived_cell",
        "_risk_free",
        "_beta",
        "_erp",
        "_shares",
        "_cost_of_debt",
    )
    for name in builders:
        monkeypatch.setattr(single_values, name, refuse)
    monkeypatch.setattr(inputs._Reader, "latest", refuse)
    monkeypatch.setattr(inputs._Reader, "period", refuse)
    got = single_values.cost_of_debt_notes(conn, run_id, 2018)
    assert got.point.value is not None


def test_an_unknown_run_is_refused_with_a_code(run):
    from domains.analysis.inputs import InputsError
    from domains.analysis.single_values import cost_of_debt_notes

    conn, _ = run
    with pytest.raises(InputsError) as e:
        cost_of_debt_notes(conn, "no-such-run")
    assert e.value.code == "run_not_found" and e.value.params == {"run_id": "no-such-run"}


def test_a_stale_concepts_table_is_refused_with_one_code(run, monkeypatch):
    from domains.analysis import math_engine
    from domains.analysis.inputs import InputsError
    from domains.analysis.single_values import cost_of_debt_notes
    from domains.fundamentals.facts import ConceptsNotSyncedError

    conn, run_id = run

    def stale(*args, **kwargs):
        raise ConceptsNotSyncedError(["debt_effective_rate"])

    monkeypatch.setattr(math_engine, "load_history", stale)
    with pytest.raises(InputsError) as e:
        cost_of_debt_notes(conn, run_id)
    assert e.value.code == "concepts_not_synced"


def test_a_what_if_on_the_risk_free_rate_compares_with_its_own_row(run):
    """A child that raises only the risk-free rate keeps the book cost of debt: its own year is
    compared with the child's 5% row, below which the 4% book cost now sits (analyst, #550)."""
    from domains.analysis.single_values import cost_of_debt_notes
    from domains.analysis.whatif import Change, revalue

    conn, parent = run
    child = revalue(conn, parent, [Change("risk_free", value=0.05)]).run_id
    _same_as_chart(conn, child)
    got = cost_of_debt_notes(conn, child)
    (note,) = [n for n in got.point.notes if n.code == "below_risk_free"]
    assert note.params["risk_free"] == 0.05 and note.params["against"] == "run_risk_free"


def test_the_answer_is_plain_json(make_company, monkeypatch):
    import json

    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = _hedged(make_company, monkeypatch, {2018: 0.052, 2019: 0.05})
    plain = cost_of_debt_notes(conn, run_id).to_dict()
    json.dumps(plain, allow_nan=False)
    assert plain["fiscal_year"] == 2019 and plain["point"]["period"] == "FY2019"
    assert [n["code"] for n in plain["cell_notes"]] == [HEDGE]
    assert isinstance(plain["point"]["period_end"], str)


# -- a year whose 10-K is not filed yet (backlog #564) -------------------------------------------


def test_the_year_in_progress_reads_not_filed_yet_on_the_notes_call_too(run):
    from domains.analysis.single_values import cost_of_debt_notes

    conn, run_id = run
    for years in (3, 5, 10):
        _, points = _same_as_chart(conn, run_id, years=years)
        reasons = [p.missing.params["reason"] for p in points if p.missing is not None]
        assert reasons.count("not_filed_yet") == 1 and points[-1].period == "FY2020"
    got = cost_of_debt_notes(conn, run_id, 2020)
    assert got.point.value is None and got.point.notes == [] and not got.point.used
    assert got.point.missing.code == NOT_COMPUTABLE
    assert got.point.missing.params["reason"] == "not_filed_yet"
    assert got.point.missing.params["period_end"] == "2020-12-31"
    assert "not filed" in got.point.missing.text


def _years(*ends, days=None):
    """(start, end) filed years from their end dates; a year starts the day after the one before
    (the first is given `days` days, as long as the second)."""
    ends = [date.fromisoformat(e) for e in ends]
    first = (ends[1] - ends[0]).days if days is None else days
    starts = [ends[0] - timedelta(days=first - 1)] + [e + timedelta(days=1) for e in ends[:-1]]
    return list(zip(starts, ends, strict=True))


# Apple's filed ends (the Saturday nearest 27 September) and Johnson & Johnson's (the Sunday
# nearest 31 December), from their 10-Ks
APPLE = ("2011-09-24", "2012-09-29", "2013-09-28", "2014-09-27", "2015-09-26", "2016-09-24",
         "2017-09-30", "2018-09-29", "2019-09-28", "2020-09-26", "2021-09-25", "2022-09-24",
         "2023-09-30", "2024-09-28", "2025-09-27")  # fmt: skip
JNJ = ("2008-12-28", "2010-01-03", "2011-01-02", "2012-01-01", "2012-12-30", "2013-12-29",
       "2014-12-28", "2016-01-03", "2017-01-01", "2017-12-31", "2018-12-30", "2019-12-29",
       "2021-01-03", "2022-01-02", "2023-01-01", "2023-12-31", "2024-12-29",
       "2025-12-28")  # fmt: skip


@pytest.mark.parametrize(
    ("ends", "ahead", "expected"),
    [
        # Apple, a 52-week FY2026, then a 53-week FY2023 seen from FY2022 and the year after it
        (APPLE, 1, "2026-09-26"),
        (APPLE[:12], 1, "2023-09-30"),
        (APPLE[:13], 1, "2024-09-28"),
        # Johnson & Johnson: FY2026 has 53 weeks and ends 3 January 2027; FY2020 too
        (JNJ, 1, "2027-01-03"),
        (JNJ[:12], 1, "2021-01-03"),
        (JNJ, 2, "2028-01-02"),
        # calendar years, two years ahead, June years, Walmart's 31 January, a mid-month end
        (("2018-12-31", "2019-12-31"), 1, "2020-12-31"),
        (("2018-12-31", "2019-12-31"), 2, "2021-12-31"),
        (("2025-06-30", "2026-06-30"), 1, "2027-06-30"),
        (("2025-01-31", "2026-01-31"), 1, "2027-01-31"),
        (("2024-10-15", "2025-10-15"), 1, "2026-10-15"),
        # a month's end stays one: 29 February then 28 February, and back
        (("2023-02-28", "2024-02-29"), 1, "2025-02-28"),
        (("2022-02-28", "2023-02-28"), 1, "2024-02-29"),
    ],
)
def test_expected_year_end(ends, ahead, expected):
    from domains.analysis.single_values import expected_year_end

    assert expected_year_end(_years(*ends), ahead) == date.fromisoformat(expected)


def test_one_52_week_year_alone_reads_forward_a_year():
    """One filed year on the last weekday of a month, and not in its last four days, reads that
    rule (backlog #574): Apple's FY2022 alone gives 30 September 2023, the date it filed (before
    #574, a week early). An end both rules fit (27 September) or neither (a Saturday near 15
    October) still reads from the newest end alone, a week early if the next year has 53 weeks."""
    from domains.analysis.single_values import expected_year_end

    assert expected_year_end(_years("2022-09-24", days=364), 1) == date(2023, 9, 30)
    assert expected_year_end(_years("2025-09-27", days=364), 1) == date(2026, 9, 26)
    assert expected_year_end(_years("2022-10-15", days=364), 1) == date(2023, 10, 14)


@pytest.mark.parametrize("ends", [APPLE, JNJ])
def test_every_filed_apple_and_jnj_end_is_expected_from_the_years_before_it(ends):
    """From every run of two or more filed years, one year and two years ahead (backlog #574).
    One year alone is a guess where both rules fit: Johnson & Johnson's 28 December 2008 sits in
    December's last four days, and reads 27 December 2009 for an end of 3 January 2010."""
    from domains.analysis.single_values import expected_year_end

    for k in range(2, len(ends)):
        filed = _years(*ends[:k])
        for ahead in (1, 2):
            if k - 1 + ahead < len(ends):
                assert expected_year_end(filed, ahead).isoformat() == ends[k - 1 + ahead]


@pytest.mark.parametrize(
    ("ends", "ahead", "expected"),
    [
        # the last Saturday of January, six days before the month's end (pandas FY5253 "last")
        (("2024-01-27", "2025-01-25"), 1, "2026-01-31"),
        (("2024-01-27", "2025-01-25"), 2, "2027-01-30"),
        # the last Friday of February, in and out of a leap year
        (("2022-02-25", "2023-02-24"), 1, "2024-02-23"),
        (("2023-02-24", "2024-02-23"), 1, "2025-02-28"),
    ],
)
def test_a_year_on_the_last_weekday_of_a_month(ends, ahead, expected):
    """The last given weekday of a month (26 U.S.C. §441(f)) can end a year six days before
    the month's end: read exactly, not from a band three days either side (backlog #574)."""
    from domains.analysis.single_values import expected_year_end

    assert expected_year_end(_years(*ends), ahead) == date.fromisoformat(expected)


def _fy5253(weekday, month, variation, first_year, n):
    """n consecutive fiscal year ends under pandas' 52/53-week rule, an independent oracle."""
    import pandas as pd
    from pandas.tseries.offsets import FY5253

    step = FY5253(weekday=weekday, startingMonth=month, variation=variation)
    ends, day = [], pd.Timestamp(first_year, 1, 1)
    for _ in range(n):
        day = day + step
        ends.append(day.date())
    return ends


@pytest.mark.parametrize("variation", ["nearest", "last"])
def test_week_years_against_pandas_once_the_rule_shows(variation):
    """Against pandas' FY5253 on every weekday, month and start year 1995-2029, with one, two
    and six filed years (backlog #574): a wrong answer only where every filed end sits in its
    month's last four days, so both rules fit, or, for the weekday nearest the end of February,
    whose leap days shift the band; the last weekday of a month is right from six years."""
    from domains.analysis.single_values import expected_year_end

    wrong = []
    for k in (1, 2, 6):
        for weekday in range(7):
            for month in range(1, 13):
                for first in range(1995, 2030):
                    ends = _fy5253(weekday, month, variation, first, k + 2)
                    filed = [(ends[0] - timedelta(days=363), ends[0])] + [
                        (ends[i - 1] + timedelta(days=1), ends[i]) for i in range(1, k)
                    ]
                    for ahead in (1, 2):
                        if expected_year_end(filed, ahead) != ends[k - 1 + ahead]:
                            wrong.append((k, month, ends[:k]))
    for k, month, filed_ends in wrong:
        both_fit = all((e + timedelta(days=4)).month != e.month for e in filed_ends)
        february = variation == "nearest" and month == 2
        assert both_fit or february, (k, month, filed_ends)
        assert variation == "nearest" or k < 6, (k, month, filed_ends)


def test_a_changed_calendar_falls_back_to_the_newest_end():
    """Ends no single anchor allows (a company that moved its year end) read from the newest."""
    from domains.analysis.single_values import expected_year_end

    filed = _years("2019-06-29", "2020-06-27", "2020-12-26", "2021-12-25")
    filed[-1] = (filed[-1][1] - timedelta(days=363), filed[-1][1])  # a 52-week year
    assert expected_year_end(filed, 1) == date(2022, 12, 24)


def test_expected_year_end_needs_a_filed_year_and_a_year_ahead():
    from domains.analysis.single_values import expected_year_end

    with pytest.raises(ValueError):
        expected_year_end(_years("2018-12-31", "2019-12-31"), 0)
    with pytest.raises(ValueError):
        expected_year_end([], 1)


# -- the chart's edges: window, newest filed year, week years (backlog #565, #569) ---------------


def _fact(name, start, end, fiscal_year, period="FY", value=100.0):
    from domains.fundamentals.schemas import Fact

    return Fact(
        canonical_name=name,
        xbrl_concept="Revenues",
        period_start=None if start is None else date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        fiscal_year=fiscal_year,
        fiscal_period=period,
        value=value,
        unit="USD",
        accession_no="0000000123-20-000001",
        filed_at=date(2020, 2, 15),
    )


def _window(quarterly=(), annual=(), instants=None, years=5):
    from types import SimpleNamespace

    from domains.analysis.math_engine import History
    from domains.analysis.single_values import _cost_of_debt_window

    history = History(
        {(f.canonical_name, f.fiscal_year, f.fiscal_period): f for f in quarterly},
        {(f.canonical_name, f.fiscal_year): f for f in annual},
        instants or {},
    )
    return _cost_of_debt_window(SimpleNamespace(history=history, years=years))


QUARTER = _fact("revenue", "2020-01-01", "2020-03-31", 2020, "Q1")
YEAR = _fact("revenue", "2019-01-01", "2019-12-31", 2019)


def test_the_window_runs_on_a_real_history_with_no_mock():
    assert _window() is None
    assert _window([QUARTER], [YEAR]) == (2016, 2020)
    assert _window([QUARTER], [YEAR], years=3) == (2018, 2020)
    # the newer of the two frequencies' years sets the last year
    older_quarter = _fact("revenue", "2019-07-01", "2019-09-30", 2019, "Q3")
    assert _window([older_quarter], [YEAR]) == (2015, 2019)


def test_the_window_needs_revenue_in_both_frequencies_as_the_chart_does():
    """The chart's reader refuses when the quarters or the years have no revenue (#565)."""
    assert _window(annual=[YEAR]) is None
    assert _window(quarterly=[QUARTER]) is None
    # other items or balance-sheet revenue do not count
    interest = _fact("interest_expense", "2019-01-01", "2019-12-31", 2019)
    assert _window([QUARTER], [interest]) is None
    instant = _fact("revenue", None, "2019-12-31", 2019)
    assert _window([QUARTER], annual=[], instants={"revenue": [instant]}) is None


def _singles_on(conn, as_of):
    from types import SimpleNamespace

    from domains.analysis.math_engine import load_history

    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    history = load_history(conn, cik, as_of)
    return SimpleNamespace(
        conn=conn, run={"cik": cik}, as_of=as_of, history=history, years=5, cache={}
    )


def _drop_fy2019_annual(*tags):
    """An edit dropping the FY2019 annual figure of each tag from every filing (the 10-K's own
    and its later comparatives): as if Warren could not read that tag for the year."""

    def edit(tag, row):
        whole_2019 = row.get("start") == "2019-01-01" and row["end"] == "2019-12-31"
        return None if tag in tags and whole_2019 else row

    return edit


def test_a_10k_whose_revenue_warren_does_not_read_still_counts_as_filed(make_company):
    """Exxon's FY2009-2010 revenue arrives only as later comparatives (#569 item 1): the 10-K
    forms known on the date say the year is filed, so it is never `not_filed_yet`."""
    from domains.analysis.single_values import _cost_of_debt_point, _newest_filed_year

    conn = make_company(_drop_fy2019_annual("Revenues", "InterestExpense"))
    singles = _singles_on(conn, AS_OF)
    assert _newest_filed_year(singles) == (2019, 2018)
    point = _cost_of_debt_point(singles, 2019, False)
    assert point.missing.params == {"reason": "no_interest_reported", "fiscal_year": 2019}
    # the year after is still not filed, its end read forward from the revenue years
    point = _cost_of_debt_point(singles, 2020, False)
    assert point.missing.params == {
        "reason": "not_filed_yet",
        "fiscal_year": 2020,
        "period_end": "2020-12-31",
    }


def test_the_newest_filed_year_is_read_once_per_answer(make_company):
    """`_newest_filed_year` queries `filing_labels`; its answer is fixed for a run, so several
    refused years read it once and share it (#575)."""
    from domains.analysis import single_values
    from domains.analysis.single_values import _cost_of_debt_point

    conn = make_company(_drop_fy2019_annual("Revenues", "InterestExpense"))
    singles = _singles_on(conn, AS_OF)
    calls = []
    real = single_values._newest_filed_year

    def counted(s):
        calls.append(s)
        return real(s)

    single_values._newest_filed_year = counted
    try:
        points = [_cost_of_debt_point(singles, y, False) for y in (2019, 2020, 2021)]
    finally:
        single_values._newest_filed_year = real
    assert len(calls) == 1
    assert [p.missing.params["reason"] for p in points] == [
        "no_interest_reported",
        "not_filed_yet",
        "not_filed_yet",
    ]
    assert singles.cache["newest_filed_year"] == (2019, 2018)


def test_only_10ks_filed_by_the_run_date_count(company):
    from domains.analysis.single_values import _newest_filed_year

    # the FY2019 10-K is filed 2020-02-15; the Q1 2020 10-Q (2020-04-30) never counts
    assert _newest_filed_year(_singles_on(company, AS_OF)) == (2019, 2019)
    assert _newest_filed_year(_singles_on(company, date(2020, 2, 15))) == (2019, 2019)
    assert _newest_filed_year(_singles_on(company, date(2020, 2, 14))) == (2018, 2018)


def test_the_filed_years_and_the_newest_share_one_order():
    """Two periods with one end (Caterpillar FY2009-2010): one sort, end then start (#569)."""
    from types import SimpleNamespace

    from domains.analysis.math_engine import History
    from domains.analysis.single_values import _filed_years, _newest_filed_year

    short = _fact("revenue", "2019-07-01", "2019-12-31", 2019)
    full = _fact("revenue", "2019-01-01", "2019-12-31", 2020)
    history = History({}, {("revenue", 2019): short, ("revenue", 2020): full}, {})
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: (None,)))
    singles = SimpleNamespace(conn=conn, run={"cik": "1"}, as_of=AS_OF, history=history)
    assert _filed_years(history)[-1] == (date(2019, 7, 1), date(2019, 12, 31))
    assert _newest_filed_year(singles) == (2019, 2019)


def _tagged_from_prior_end(ends, first_days=364):
    """Filed years whose start is tagged as the previous year's end (365 or 372 days, counting
    both ends), as some 52/53-week filers tag them (#569 item 2)."""
    ends = [date.fromisoformat(e) for e in ends]
    starts = [ends[0] - timedelta(days=first_days)] + ends[:-1]
    return list(zip(starts, ends, strict=True))


@pytest.mark.parametrize(
    ("ends", "expected"),
    [
        (APPLE, "2026-09-26"),
        (APPLE[:12], "2023-09-30"),
        (APPLE[:13], "2024-09-28"),
        (JNJ, "2027-01-03"),
        (JNJ[:12], "2021-01-03"),
    ],
)
def test_week_years_tagged_from_the_prior_end_read_as_week_years(ends, expected):
    from domains.analysis.single_values import expected_year_end

    filed = _tagged_from_prior_end(ends)
    assert (filed[-1][1] - filed[-1][0]).days + 1 in (365, 372)
    assert expected_year_end(filed, 1) == date.fromisoformat(expected)
    # the same answer as with the start the day after the prior end
    assert expected_year_end(filed, 1) == expected_year_end(_years(*ends), 1)


def test_a_week_year_with_one_year_missing_between_still_reads_as_one():
    from domains.analysis.single_values import expected_year_end

    filed = _tagged_from_prior_end(APPLE)
    del filed[-2]  # FY2024 not read: the gap is 728 days, still whole weeks
    assert expected_year_end(filed, 1) == date(2026, 9, 26)


def test_calendar_years_tagged_the_same_way_stay_calendar_years():
    from domains.analysis.single_values import expected_year_end

    # 1 January to 31 December, 365 days counting both ends, ends 365 or 366 days apart
    filed = [(date(y, 1, 1), date(y, 12, 31)) for y in (2017, 2018, 2019)]
    assert expected_year_end(filed, 1) == date(2020, 12, 31)
    # one 365-day year alone has no previous end to compare: a calendar year
    assert expected_year_end(filed[-1:], 1) == date(2020, 12, 31)
    # ends tagged from the prior end, a leap year between (366 days apart)
    filed = _tagged_from_prior_end(("2019-12-31", "2020-12-31"), first_days=365)
    assert expected_year_end(filed, 1) == date(2021, 12, 31)


def test_a_run_after_the_year_ends_and_before_its_10k_reads_not_filed_yet(company):
    """FY2019 ended 2019-12-31 and its 10-K is filed 2020-02-15: a run on 2020-02-10 shows the
    year as not filed, with the end it already had, and reads its own cost of debt from FY2018
    (#569 item 4; Apple's 2026-10-30 run is the real case)."""
    from domains.analysis.single_values import cost_of_debt_notes

    as_of = date(2020, 2, 10)
    run_id = run_baseline(company, "TST", as_of, choices=CHOICES, today=as_of)
    for years in (3, 5):
        answer = inputs_behind(company, run_id, VPS, years=years)
        points = _primary(_cell(answer, "cost_of_debt")).points
        last = points[-1]
        assert last.period == "FY2019" and last.value is None
        assert last.missing.params == {
            "reason": "not_filed_yet",
            "fiscal_year": 2019,
            "period_end": "2019-12-31",
        }
        assert not any(p.missing and p.missing.params["reason"] == "not_filed_yet"
                       for p in points[:-1])  # fmt: skip
        (used,) = [p for p in points if p.used]
        assert used.period == "FY2018"
        got = cost_of_debt_notes(company, run_id, 2019, years=years)
        assert got.point == last


def test_the_week_year_gap_is_to_the_previous_distinct_end():
    """Two periods can share an end (Caterpillar FY2009-2010): the gap skips the shorter one."""
    from domains.analysis.single_values import expected_year_end

    filed = _tagged_from_prior_end(APPLE)
    end = filed[-1][1]
    filed.insert(-1, (end - timedelta(days=90), end))  # another period ending on the same day
    assert expected_year_end(filed, 1) == date(2026, 9, 26)


# -- backlog #499: the year-average yield over the fiscal year's own dates -----------------------


@pytest.fixture
def yields_db(db_path):
    """Make a fresh database holding one 10-year yield download, `rates` mapping each weekday
    to a percent; returns what `_below_risk_free` reads of a `Singles`."""
    from contextlib import nullcontext
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from domains.market.yields import load_yields
    from shared_kernel.database import apply_migrations, get_db_connection

    managers = []

    def make(rates):
        cm = get_db_connection(db_path)
        managers.append(cm)
        conn = cm.__enter__()
        apply_migrations(conn)
        rows = [{"date": d.isoformat(), "value": v} for d, v in sorted(rates.items())]
        load_yields(conn, download=lambda s: rows, now=lambda: datetime(2024, 1, 2, tzinfo=UTC))
        return SimpleNamespace(
            conn=conn, as_of=date(2024, 1, 2), pins=nullcontext, yield_pinned=lambda: True
        )

    yield make
    for cm in managers:
        cm.__exit__(None, None, None)


def _weekdays(first, last):
    days = (first + timedelta(days=k) for k in range((last - first).days + 1))
    return [d for d in days if d.weekday() < 5]


@pytest.mark.parametrize(
    "start, end, first_trading_day",
    [
        # Apple's 53-week FY2023: Sunday 25 September 2022 to Saturday 30 September 2023
        (date(2022, 9, 25), date(2023, 9, 30), date(2022, 9, 26)),
        # Johnson & Johnson's 53-week FY2020: Monday 30 December 2019 to Sunday 3 January 2021
        (date(2019, 12, 30), date(2021, 1, 3), date(2019, 12, 30)),
    ],
)
def test_the_year_average_yield_covers_a_53_week_year(yields_db, start, end, first_trading_day):
    from domains.analysis.single_values import _below_risk_free

    days = _weekdays(start, end)
    first_week = [d for d in days if d < start + timedelta(days=7)]
    singles = yields_db({d: 5.0 if d in first_week else 2.0 for d in days})
    (note,) = _below_risk_free(singles, 0.01, False, end, start)
    # on main the window began 364 days before the end and left the first week out
    assert note.params["risk_free_from"] == first_trading_day.isoformat()
    assert note.params["observations"] == len(days)
    expected = (len(first_week) * 0.05 + (len(days) - len(first_week)) * 0.02) / len(days)
    assert note.params["risk_free"] == pytest.approx(expected)


def test_the_year_average_yield_reads_no_day_before_the_year(yields_db):
    from domains.analysis.single_values import _below_risk_free

    # a 52-week year on made-up dates (a real one starts on a weekend, so 364 days before
    # its end has no yield): Thursday 2 January 2020 to Wednesday 30 December 2020
    start, end = date(2020, 1, 2), date(2020, 12, 30)
    rates = {d: 2.0 for d in _weekdays(start, end)}
    rates[start - timedelta(days=1)] = 10.0  # the year before's last day
    singles = yields_db(rates)
    (note,) = _below_risk_free(singles, 0.01, False, end, start)
    assert note.params["risk_free_from"] == start.isoformat()
    assert note.params["risk_free"] == pytest.approx(0.02)


def _year_average_notes(conn, run_id):
    points = _primary(_cell(inputs_behind(conn, run_id, VPS, years=5), "cost_of_debt")).points
    return [
        n
        for p in points
        for n in p.notes
        if n.code == "below_risk_free" and n.params["against"] == "year_average_yield"
    ]


@pytest.fixture
def cheap_run(make_company):
    def cheap_interest(tag, row):  # a 1% book cost against a 3% yield: every year has the note
        if tag == "InterestExpense":
            return {**row, "val": row["val"] / 4}
        return row

    conn = make_company(cheap_interest)
    return conn, run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def test_the_year_average_yield_says_it_read_the_runs_own_download(cheap_run):
    notes = _year_average_notes(*cheap_run)
    assert notes and all(n.params["yield_fetch_pinned"] is True for n in notes)


def test_a_replaced_yield_download_is_flagged_and_still_point_in_time(cheap_run):
    conn, run_id = cheap_run
    before = _year_average_notes(conn, run_id)
    # the run names a yield download that is no longer stored (replaced before migration 0006)
    conn.execute("UPDATE runs SET yield_fetch_sha256 = ? WHERE run_id = ?", ("0" * 64, run_id))
    after = _year_average_notes(conn, run_id)
    assert len(after) == len(before) > 0
    for n in after:
        assert n.params["yield_fetch_pinned"] is False
        assert date.fromisoformat(n.params["risk_free_date"]) < AS_OF


def test_a_replaced_price_download_leaves_the_yield_flag_true(cheap_run):
    conn, run_id = cheap_run
    conn.execute("UPDATE runs SET price_fetch_sha256 = ? WHERE run_id = ?", ("0" * 64, run_id))
    notes = _year_average_notes(conn, run_id)
    assert notes and all(n.params["yield_fetch_pinned"] is True for n in notes)


def test_a_floored_child_of_a_parent_without_sources_has_no_floor_note(run):
    """A parent stored before sources were recorded gives a child with none, so the floor note
    cannot be written; the cell still shows the floor, the child's own row (backlog #499)."""
    conn, parent = run
    conn.execute("DELETE FROM assumption_sources WHERE run_id = ?", (parent,))
    child = _floored_child(conn, parent)
    assert not conn.execute(
        "SELECT 1 FROM assumption_sources WHERE run_id = ?", (child,)
    ).fetchone()
    answer = inputs_behind(conn, child, VPS)
    cell = _cell(answer, "cost_of_debt")
    assert cell.rows[0].value == _cell(answer, "risk_free").rows[0].value == 0.05
    assert not any(n.code == "floored_at_risk_free" for n in cell.notes)


# -- downloads that are not the run's own (backlog #601) ---------------------------------------

UNPINNED_SERIES = ("risk_free", "terminal_growth", "beta", "erp", "shares")


def _unpinned_by_cell(conn, run_id):
    """{cell: [the `download_not_pinned` notes' roles, one list per series]}."""
    answer = inputs_behind(conn, run_id, VPS, years=5)
    out = {}
    for name in UNPINNED_SERIES:
        out[name] = [
            sorted(d["role"] for n in s.notes if n.code == "download_not_pinned"
                   for d in n.params["downloads"])
            for s in _cell(answer, name).history
        ]  # fmt: skip
    return answer, out


def _newest_fetch_time(conn, source):
    from domains.market.store import fetch_time

    row = conn.execute(
        "SELECT * FROM market_fetches WHERE source = ? ORDER BY fetch_id DESC LIMIT 1", (source,)
    ).fetchone()
    return fetch_time(row).isoformat()


def _no_market_date_after_the_run(answer):
    for name in ("risk_free", "beta"):
        for p in _primary(_cell(answer, name)).points:
            assert p.period_end is None or p.period_end <= AS_OF


def test_no_download_note_when_every_download_is_the_runs_own(run):
    _answer, by_cell = _unpinned_by_cell(*run)
    assert all(roles == [] for series in by_cell.values() for roles in series)


def test_a_replaced_yield_download_is_named_on_the_yield_series_only(run):
    conn, run_id = run
    conn.execute("UPDATE runs SET yield_fetch_sha256 = ? WHERE run_id = ?", ("0" * 64, run_id))
    answer, by_cell = _unpinned_by_cell(conn, run_id)
    assert by_cell["risk_free"] == [["yield"]]
    assert by_cell["terminal_growth"] == [["yield"]]  # the same series, shown on that card too
    assert by_cell["erp"] == [["yield"]]
    assert by_cell["beta"] == [[]]
    assert all(roles == [] for roles in by_cell["shares"])
    note = next(n for n in _primary(_cell(answer, "risk_free")).notes
                if n.code == "download_not_pinned")  # fmt: skip
    (d,) = note.params["downloads"]
    assert d["source"] == "fred" and d["covers_run_date"] is True
    assert d["read_fetched_at"] == _newest_fetch_time(conn, "fred")
    _no_market_date_after_the_run(answer)


def test_a_replaced_price_download_is_named_on_beta_and_the_share_series(run):
    conn, run_id = run
    conn.execute("UPDATE runs SET price_fetch_sha256 = ? WHERE run_id = ?", ("0" * 64, run_id))
    answer, by_cell = _unpinned_by_cell(conn, run_id)
    assert by_cell["beta"] == [["price"]]
    assert by_cell["shares"] == [["price"], ["price"], ["price"]]
    assert by_cell["risk_free"] == [[]] and by_cell["erp"] == [[]]
    (d,) = next(n for n in _primary(_cell(answer, "beta")).notes
                if n.code == "download_not_pinned").params["downloads"]  # fmt: skip
    assert (d["source"], d["symbol"], d["covers_run_date"]) == ("yahoo", "TST", True)
    _no_market_date_after_the_run(answer)


def test_a_price_download_made_before_the_run_date_ended_says_so(run):
    """`split_factor` reads the newest price download without a coverage check, so a download
    that stops before the run's date could miss a split: the note says it does not cover the
    run's date (analyst, backlog #601)."""
    conn, run_id = run
    conn.execute("UPDATE runs SET price_fetch_sha256 = ? WHERE run_id = ?", ("0" * 64, run_id))
    conn.execute(
        "UPDATE market_fetches SET fetched_at = ? WHERE source = 'yahoo' AND symbol = 'TST'",
        ((AS_OF - timedelta(days=30)).isoformat() + "T22:00:00+00:00",),
    )
    answer, by_cell = _unpinned_by_cell(conn, run_id)
    assert by_cell["beta"] == [["price"]]
    for s in _cell(answer, "shares").history:
        (d,) = next(n for n in s.notes if n.code == "download_not_pinned").params["downloads"]
        assert d["covers_run_date"] is False
    _no_market_date_after_the_run(answer)


def test_two_replaced_downloads_are_both_named_on_a_series_reading_both(run):
    conn, run_id = run
    conn.execute(
        "UPDATE runs SET price_fetch_sha256 = ?, index_fetch_sha256 = ? WHERE run_id = ?",
        ("0" * 64, "1" * 64, run_id),
    )
    _answer, by_cell = _unpinned_by_cell(conn, run_id)
    assert by_cell["beta"] == [["index", "price"]]
    assert by_cell["erp"] == [["index"]]
