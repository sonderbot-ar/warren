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
    cover, diluted = _cell(answer, "shares").history
    assert cover.primary and not diluted.primary
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
