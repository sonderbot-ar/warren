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
    assert last.missing.params["reason"] == "no_interest_reported"  # not filed yet


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
            assert p.period_end - timedelta(days=364) <= first <= last <= p.period_end
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


def _hedged(make_company, monkeypatch, rates, first=2017, cheap=False, late=()):
    """Test Corp with a stated effective rate at each listed year end (filed in that year's
    10-K, or after `AS_OF` for a year in `late`), the rate item read for TST and an interest
    caveat for TST from `first`. `cheap` halves the interest (2% book cost, below the 3% yield)."""
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
        "TST", HEDGE, first, None, "debt_effective_rate", "test filings", ""
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
            filed = "2020-08-01" if row["fy"] in late else row["filed"]
            return [(tag, row), (RATE_TAG, {**row, "val": rates[row["fy"]], "filed": filed})]
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
