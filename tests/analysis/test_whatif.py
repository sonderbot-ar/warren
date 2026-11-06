"""What-if revaluation (backlog #141): a stored run valued again with named inputs changed."""

import inspect
import json
from types import SimpleNamespace

import pytest

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis.runs import load_assumptions, load_outputs, rebuild, reproduce, run_baseline
from domains.analysis.schemas import SINGLE
from domains.analysis.whatif import Change, WhatIfError, forecast_year, revalue
from domains.llm import __main__ as llm_main
from domains.orchestration import nodes
from tests.analysis.conftest import AS_OF, CHOICES


@pytest.fixture
def parent(company):
    return run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def _rows(conn, run_id):
    return {(a.name, a.period): a for a in load_assumptions(conn, run_id)}


def _line(result, name, period=SINGLE):
    return next(x for x in result.lines if x.name == name and x.period == period)


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def test_margin_down_one_point_equals_hand_edited_rows(company, parent):
    result = revalue(company, parent, [Change("operating_margin", delta=-0.01)])
    rows = load_assumptions(company, parent)
    edited = [
        a.model_copy(update={"value": a.value - 0.01}) if a.name == "operating_margin" else a
        for a in rows
    ]
    expected = dcf.value(edited).value_per_share
    assert abs(_line(result, "value_per_share").after - expected) < 0.005
    assert result.run_id == f"{parent}_whatif_1" and result.parent_run_id == parent
    stored = company.execute(
        "SELECT parent_run_id, as_of FROM runs WHERE run_id = ?", (result.run_id,)
    ).fetchone()
    assert stored["parent_run_id"] == parent and stored["as_of"] == AS_OF.isoformat()


def test_the_child_reproduces_and_differs_only_where_changed(company, parent):
    result = revalue(company, parent, [Change("beta", value=1.5)])
    assert reproduce(company, result.run_id).ok
    before, after = _rows(company, parent), _rows(company, result.run_id)
    assert before.keys() == after.keys()
    differ = {k for k in before if before[k] != after[k]}
    assert differ == {("beta", SINGLE)}
    assert after[("beta", SINGLE)].source == "user"
    assert f"what-if on {parent}" in after[("beta", SINGLE)].method


def test_set_and_add_give_the_same_values(company, parent):
    beta = _rows(company, parent)[("beta", SINGLE)].value
    a = revalue(company, parent, [Change("beta", value=beta + 0.2)])
    b = revalue(company, parent, [Change("beta", delta=0.2)])
    assert abs(_line(a, "value_per_share").after - _line(b, "value_per_share").after) < 1e-9


def test_one_period_margin_moves_only_that_periods_cash_flow(company, parent):
    periods = dcf.forecast_periods(dcf._index(load_assumptions(company, parent)))[1]
    result = revalue(company, parent, [Change("operating_margin", delta=0.02, period=periods[2])])
    moved = {x.period for x in result.lines if x.name == "fcff" and x.change}
    assert moved == {periods[2]}
    assert _line(result, "revenue", periods[2]).change == 0


@pytest.mark.parametrize("name", ["revenue_growth", "nwc_pct"])
def test_growth_and_working_capital_ripple_past_their_period(company, parent, name):
    periods = dcf.forecast_periods(dcf._index(load_assumptions(company, parent)))[1]
    result = revalue(company, parent, [Change(name, delta=0.02, period=periods[0])])
    moved = [x.period for x in result.lines if x.name == "fcff" and x.change]
    assert periods[0] in moved and len(moved) > 1  # lag-4 compounding, or next period's ΔNWC


def test_risk_free_moves_terminal_growth_and_the_fade(company, parent):
    rows = _rows(company, parent)
    result = revalue(company, parent, [Change("risk_free", delta=0.0025)])
    hows = {(c.name, c.period): c.how for c in result.changes}
    assert hows[("terminal_growth", SINGLE)] == "follows_risk_free"
    tg = next(c for c in result.changes if c.name == "terminal_growth")
    assert abs(tg.after - tg.before - 0.0025) < 1e-15
    periods = dcf.forecast_periods(dcf._index(list(rows.values())))[1]
    child = _rows(company, result.run_id)
    for i, period in enumerate(periods):
        shift = child[("revenue_growth", period)].value - rows[("revenue_growth", period)].value
        assert abs(shift - 0.0025 * (forecast_year(i) - 1) / 4) < 1e-15
    # year 5 ends at the new terminal growth, as the run's own rule says
    assert abs(child[("revenue_growth", "Y5")].value - child[("terminal_growth", SINGLE)].value) < (
        1e-12
    )
    codes = {n.code for n in result.notes}
    assert {
        "terminal_growth_follows_risk_free",
        "growth_path_follows_terminal_growth",
        "cost_of_debt_held",
        "cash_flows_held",
    } <= codes
    assert reproduce(company, result.run_id).ok


def test_terminal_growth_set_by_the_student_wins(company, parent):
    result = revalue(
        company, parent, [Change("risk_free", delta=0.0025), Change("terminal_growth", value=0.01)]
    )
    tg = next(c for c in result.changes if c.name == "terminal_growth")
    assert tg.how == "set" and tg.after == 0.01


def test_revenue_growth_set_by_the_student_is_not_refaded(company, parent):
    result = revalue(
        company, parent, [Change("risk_free", delta=0.0025), Change("revenue_growth", value=0.03)]
    )
    assert all(c.how != "follows_terminal_growth" for c in result.changes)
    assert all(c.after == 0.03 for c in result.changes if c.name == "revenue_growth")


def test_terminal_formula_is_named(company, parent):
    result = revalue(company, parent, [Change("erp", delta=0.01)])
    assert result.terminal_method == dcf.VALUE_DRIVER
    assert result.terminal_formula.code == "value_driver"


def test_gordon_runs_name_their_formula(company):
    choices = {k: v for k, v in CHOICES.items() if k != "terminal_method"}
    run_id = run_baseline(company, "TST", AS_OF, choices=choices, today=AS_OF)
    result = revalue(company, run_id, [Change("erp", delta=-0.005)])
    assert result.terminal_method == dcf.GORDON and result.terminal_formula.code == "gordon"
    assert reproduce(company, result.run_id).ok


def test_lines_name_the_inputs_behind_them_and_use_financial_math(company, parent):
    result = revalue(company, parent, [Change("shares", delta=-1.0)])
    vps = _line(result, "value_per_share")
    assert vps.driven_by == ["shares"]
    assert vps.change == vps.after - vps.before
    assert vps.change_pct == fm.growth(vps.after, vps.before)
    assert _line(result, "wacc").change == 0 and _line(result, "wacc").driven_by == []
    names = {x.name for x in result.lines}
    assert {"revenue", "ebit", "operating_taxes", "nopat", "net_debt", "minority_interest"} <= names
    assert {"enterprise_value_as_of", "equity_value", "terminal_value"} <= names


def test_cash_moves_the_bridge_not_the_enterprise_value(company, parent):
    result = revalue(company, parent, [Change("cash_and_investments", delta=100.0)])
    assert _line(result, "enterprise_value_as_of").change == 0
    assert abs(_line(result, "net_debt").change + 100.0) < 1e-9
    assert abs(_line(result, "equity_value").change - 100.0) < 1e-6


def test_asking_again_returns_the_stored_child(company, parent):
    first = revalue(company, parent, [Change("beta", delta=0.1)])
    count = _count(company)
    again = revalue(company, parent, [Change("beta", delta=0.1)])
    assert again.reused and not first.reused and again.run_id == first.run_id
    assert _count(company) == count
    other = revalue(company, parent, [Change("beta", delta=0.2)])
    assert other.run_id == f"{parent}_whatif_2"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ([Change("nonsense", value=1)], "unknown_input"),
        ([Change("equity_market_value", value=1)], "not_changeable"),
        # debt is changeable since #170, but only with what the money is for
        ([Change("debt", delta=1e9)], "debt_use_needed"),
        ([Change("revenue_seed", value=1)], "not_changeable"),
        ([Change("roll_years", value=0)], "not_changeable"),
        ([Change("beta", value=1, period="FY2021Q1")], "period_on_single_value"),
        ([Change("operating_margin", value=0.1, period="FY1999Q1")], "unknown_period"),
        ([Change("beta", value=1), Change("beta", delta=0.1)], "duplicate_change"),
        ([Change("beta", value=1, delta=0.1)], "value_and_delta"),
        ([Change("beta")], "value_and_delta"),
        ([Change("shares", value=0)], "out_of_range"),
        ([Change("tax_rate", value=1.0)], "out_of_range"),
        ([Change("cash_and_investments", value=-1)], "out_of_range"),
        ([Change("cost_of_debt", value=-0.5)], "out_of_range"),
        ([Change("beta", value=float("nan"))], "invalid_input"),
        ([Change("shares", value=float("inf"))], "invalid_input"),
        ([Change("erp", delta=float("-inf"))], "invalid_input"),
        ([Change("terminal_growth", value=0.5)], "growth_not_below_rate"),
        ([], "no_change"),
    ],
)
def test_refusals_have_a_code_and_store_nothing(company, parent, changes, code):
    count = _count(company)
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, changes)
    assert e.value.code == code
    assert _count(company) == count


def test_a_what_if_of_a_what_if_and_an_unknown_run_are_refused(company, parent):
    child = revalue(company, parent, [Change("beta", delta=0.1)]).run_id
    with pytest.raises(WhatIfError) as e:
        revalue(company, child, [Change("beta", delta=0.1)])
    assert e.value.code == "parent_is_what_if"
    with pytest.raises(WhatIfError) as e:
        revalue(company, "NOPE_2020-01-01_1", [Change("beta", delta=0.1)])
    assert e.value.code == "no_run"


def test_a_child_is_not_rebuilt(company, parent):
    child = revalue(company, parent, [Change("beta", delta=0.1)]).run_id
    with pytest.raises(ValueError, match="rebuild the parent"):
        rebuild(company, child, today=AS_OF)


def test_children_stay_out_of_baseline_lookups_and_numbering(company, parent):
    revalue(company, parent, [Change("beta", delta=0.1)])
    assert run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF) == "TST_2020-06-30_2"
    # the pipeline's and the AI steps' baseline lookups skip what-ifs
    for function in (nodes.build_baseline, llm_main._baseline_run):
        assert "parent_run_id IS NULL" in inspect.getsource(function)


def test_outputs_match_the_stored_child_and_json_round_trips(company, parent):
    result = revalue(company, parent, [Change("erp", delta=0.005)])
    stored = load_outputs(company, result.run_id)
    assert _line(result, "value_per_share").after == stored[("value_per_share", SINGLE)]
    data = result.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["currency"] == "USD"


def test_the_ai_baseline_lookup_returns_the_baseline_not_a_newer_child(company, parent):
    revalue(company, parent, [Change("beta", delta=0.1)])
    case = SimpleNamespace(ticker="TST", event_date=AS_OF)
    assert llm_main._baseline_run(company, case) == parent


def test_rates_change_in_points_not_percent(company, parent):
    result = revalue(company, parent, [Change("erp", delta=0.01)])
    wacc = _line(result, "wacc")
    assert wacc.unit == "fraction" and wacc.change > 0 and wacc.change_pct is None


# -- WACC set directly (backlog #171) -------------------------------------------------------------


def _wacc(conn, run_id):
    return load_outputs(conn, run_id)[("wacc", SINGLE)]


def test_wacc_set_and_added_give_the_same_child_and_reproduce(company, parent):
    wacc = _wacc(company, parent)
    a = revalue(company, parent, [Change("wacc", value=wacc + 0.01)])
    b = revalue(company, parent, [Change("wacc", delta=0.01)])
    assert abs(_line(a, "value_per_share").after - _line(b, "value_per_share").after) < 1e-9
    (change,) = a.changes
    assert (change.name, change.period, change.before) == ("wacc", SINGLE, wacc)
    assert reproduce(company, a.run_id).ok and reproduce(company, b.run_id).ok


def test_a_set_wacc_is_one_new_row_and_values_as_the_override(company, parent):
    result = revalue(company, parent, [Change("wacc", value=0.12)])
    before, after = _rows(company, parent), _rows(company, result.run_id)
    assert after.keys() - before.keys() == {("wacc", SINGLE)}
    assert all(after[k] == before[k] for k in before)
    row = after[("wacc", SINGLE)]
    assert row.value == 0.12 and row.source == "user" and f"what-if on {parent}" in row.method
    inp = dcf.inputs(load_assumptions(company, parent)).replace(wacc_override=0.12)
    assert _line(result, "value_per_share").after == dcf.compute(inp).value_per_share
    assert _line(result, "wacc").after == 0.12


def test_the_parents_own_wacc_set_directly_changes_no_value(company, parent):
    result = revalue(company, parent, [Change("wacc", value=_wacc(company, parent))])
    assert _line(result, "value_per_share").change == 0
    assert all(not x.change for x in result.lines)


def test_with_wacc_set_the_cost_of_equity_is_held_and_the_erp_range_is_not_computed(
    company, parent
):
    result = revalue(company, parent, [Change("wacc", delta=0.01)])
    coe = _line(result, "cost_of_equity")
    assert coe.change == 0 and coe.driven_by == []
    assert "wacc" in _line(result, "value_per_share").driven_by
    assert "wacc" in _line(result, "discount_factor", result.lines[-1].period).driven_by
    outputs = load_outputs(company, result.run_id)
    assert not any(name.startswith("value_per_share_erp") for name, _ in outputs)
    codes = [n.code for n in result.notes]
    warnings = [n.params["warning_code"] for n in result.notes if n.code == "run_warning"]
    assert "wacc_set_on_what_if" in codes and "erp_bounds_not_computed" in warnings
    assert "no_value" not in codes
    note = next(n for n in result.notes if n.code == "wacc_set_on_what_if")
    assert note.params == {"before": _wacc(company, parent), "after": _wacc(company, parent) + 0.01}


def test_terminal_growth_may_be_changed_beside_a_set_wacc(company, parent):
    result = revalue(
        company, parent, [Change("wacc", value=0.12), Change("terminal_growth", delta=0.005)]
    )
    assert reproduce(company, result.run_id).ok
    assert {c.name for c in result.changes} >= {"wacc", "terminal_growth"}


@pytest.mark.parametrize("name", ["risk_free", "beta", "erp", "cost_of_debt", "debt_tax_rate"])
def test_a_set_wacc_beside_an_input_it_is_built_from_is_refused(company, parent, name):
    count = _count(company)
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, [Change("wacc", value=0.1), Change(name, delta=0.001)])
    assert (e.value.code, e.value.params) == ("wacc_with_rate_input", {"name": name})
    assert _count(company) == count


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (Change("wacc", value=0.0), "out_of_range"),
        (Change("wacc", value=-0.02), "out_of_range"),
        (Change("wacc", value=float("nan")), "invalid_input"),
        (Change("wacc", value=0.1, period="FY2021Q1"), "period_on_single_value"),
        (Change("wacc", value=0.001), "growth_not_below_rate"),
    ],
)
def test_a_set_wacc_out_of_range_is_refused(company, parent, change, code):
    count = _count(company)
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, [change])
    assert e.value.code == code
    assert _count(company) == count


def test_a_set_wacc_asked_again_is_reused_and_has_sources(company, parent):
    from domains.analysis import sources as src

    first = revalue(company, parent, [Change("wacc", value=0.11)])
    again = revalue(company, parent, [Change("wacc", value=0.11)])
    assert again.reused and again.run_id == first.run_id
    sources = src.load(company, first.run_id)
    (item,) = sources[("wacc", SINGLE)]
    assert item["kind"] == "what_if" and item["before"] == _wacc(company, parent)
    src.check(load_assumptions(company, first.run_id), sources, child=True)
    trace = src.run_sources(company, first.run_id).to_dict()["outputs"]
    wacc_out = next(o for o in trace if o["name"] == "wacc")
    assert wacc_out["formula"] == "wacc_as_set"


def test_a_set_wacc_at_growth_is_refused_with_both_numbers(company, parent):
    growth = _rows(company, parent)[("terminal_growth", SINGLE)].value
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, [Change("wacc", value=growth)])
    assert e.value.code == "growth_not_below_rate"
    assert e.value.params == {"wacc": growth, "terminal_growth": growth}


def test_a_set_wacc_outside_its_parts_says_so_and_inside_does_not(company, parent):
    outputs = load_outputs(company, parent)
    rows = _rows(company, parent)
    coe = outputs[("cost_of_equity", SINGLE)]
    kd = fm.after_tax_cost_of_debt(
        rows[("cost_of_debt", SINGLE)].value, rows[("debt_tax_rate", SINGLE)].value
    )
    low, high = sorted((kd, coe))

    def warning_codes(wacc):
        result = revalue(company, parent, [Change("wacc", value=wacc)])
        return {n.params["warning_code"]: n for n in result.notes if n.code == "run_warning"}

    above = warning_codes(high + 0.01)["wacc_outside_its_parts"]
    assert above.params["warning_params"] == {
        "wacc": high + 0.01,
        "cost_of_equity": coe,
        "after_tax_cost_of_debt": kd,
    }
    assert "wacc_outside_its_parts" not in warning_codes((low + high) / 2)


def test_a_set_wacc_on_a_value_driver_run_says_ronic_follows(company, parent):
    result = revalue(company, parent, [Change("wacc", delta=0.005)])
    assert result.terminal_method == dcf.VALUE_DRIVER
    assert "ronic_follows_wacc" in [n.code for n in result.notes]


# -- the terminal formula switched on a what-if (backlog #171 part 2, owner decision) ------------


def _gordon_parent(company):
    """A run stored before M4: no terminal_method row, so Gordon on FCFF."""
    choices = {k: v for k, v in CHOICES.items() if k != "terminal_method"}
    return run_baseline(company, "TST", AS_OF, choices=choices, today=AS_OF)


def test_a_switch_to_gordon_values_as_dcf_under_gordon_and_reproduces(company, parent):
    result = revalue(company, parent, [Change("terminal_method", method=dcf.GORDON)])
    inp = dcf.inputs(load_assumptions(company, parent)).replace(terminal_method=dcf.GORDON)
    assert _line(result, "value_per_share").after == dcf.compute(inp).value_per_share
    assert reproduce(company, result.run_id).ok
    assert result.terminal_method == dcf.GORDON and result.terminal_formula.code == "gordon"
    (change,) = result.changes
    assert (change.before, change.after, change.how) == (dcf.VALUE_DRIVER, dcf.GORDON, "switch")
    row = _rows(company, result.run_id)[("terminal_method", SINGLE)]
    assert row.source == "user" and row.value is None
    assert row.method.startswith(f"{dcf.GORDON}: what-if on {parent}")
    assert dcf.terminal_method(load_assumptions(company, parent)) == dcf.VALUE_DRIVER


def test_a_switch_moves_only_the_terminal_value_and_what_follows(company, parent):
    result = revalue(company, parent, [Change("terminal_method", method=dcf.GORDON)])
    moved = {x.name for x in result.lines if x.change}
    assert moved <= {
        "terminal_value",
        "pv_terminal",
        "enterprise_value",
        "terminal_share",
        "enterprise_value_as_of",
        "equity_value",
        "value_per_share",
    }
    assert "value_per_share" in moved
    assert _line(result, "value_per_share").driven_by == ["terminal_method"]
    assert _line(result, "wacc").change == 0 and _line(result, "pv_explicit").change == 0


def test_a_run_stored_before_m4_can_be_seen_under_the_value_driver(company):
    gordon = _gordon_parent(company)
    result = revalue(company, gordon, [Change("terminal_method", method=dcf.VALUE_DRIVER)])
    rows = _rows(company, result.run_id)
    assert ("terminal_method", SINGLE) in rows and ("terminal_method", SINGLE) not in _rows(
        company, gordon
    )
    assert result.terminal_method == dcf.VALUE_DRIVER
    assert reproduce(company, result.run_id).ok
    from domains.analysis import sources as src

    (item,) = src.load(company, result.run_id)[("terminal_method", SINGLE)]
    assert item["kind"] == "what_if" and item["before"] == dcf.GORDON and item["how"] == "switch"
    src.check(load_assumptions(company, result.run_id), src.load(company, result.run_id), True)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (Change("terminal_method", method="nonsense"), "unknown_terminal_method"),
        (Change("terminal_method", method=dcf.VALUE_DRIVER), "same_terminal_method"),
        (Change("terminal_method", value=1.0), "value_and_delta"),
        (Change("terminal_method", method=dcf.GORDON, value=1.0), "value_and_delta"),
        (Change("beta", method=dcf.GORDON), "method_on_number"),
        (Change("terminal_method", method=dcf.GORDON, period="FY2021Q1"), "period_on_single_value"),
    ],
)
def test_switch_refusals_have_a_code_and_store_nothing(company, parent, change, code):
    count = _count(company)
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, [change])
    assert e.value.code == code
    assert _count(company) == count


def test_a_switch_to_gordon_names_what_it_assumes_with_the_grids_codes(company, parent):
    result = revalue(company, parent, [Change("terminal_method", method=dcf.GORDON)])
    by_code = {n.code: n for n in result.notes}
    assert "terminal_method_switched" in by_code
    out = load_outputs(company, result.run_id)
    g = _rows(company, parent)[("terminal_growth", SINGLE)].value
    reinvest = fm.reinvestment_rate(out[("fcff", "Y5")], out[("nopat", "Y5")])
    assert by_code["gordon_holds_reinvestment"].params == {"reinvestment_rate": reinvest}
    if reinvest > 0:
        assert by_code["gordon_implied_ronic"].params == {
            "implied_ronic": fm.implied_ronic(g, reinvest),
            "reinvestment_rate": reinvest,
            "terminal_growth": g,
            "wacc": out[("wacc", SINGLE)],
        }
    else:
        assert "gordon_reinvestment_not_positive" in by_code


@pytest.mark.parametrize(
    ("fcff", "nopat", "codes"),
    [
        (80.0, 100.0, {"gordon_holds_reinvestment", "gordon_implied_ronic"}),
        (120.0, 100.0, {"gordon_holds_reinvestment", "gordon_reinvestment_not_positive"}),
        (100.0, 100.0, {"gordon_holds_reinvestment", "gordon_reinvestment_not_positive"}),
        (-5.0, -10.0, {"gordon_holds_reinvestment", "gordon_reinvestment_not_positive"}),
    ],
)
def test_gordon_notes_cover_negative_reinvestment_and_negative_nopat(fcff, nopat, codes):
    from domains.analysis.schemas import Assumption
    from domains.analysis.whatif import _gordon_notes

    rows = [
        Assumption(name="terminal_growth", period=SINGLE, value=0.04, source="computed", method="t")
    ]
    outputs = {("fcff", "Y5"): fcff, ("nopat", "Y5"): nopat, ("wacc", SINGLE): 0.09}
    notes = _gordon_notes(outputs, rows)
    assert {n.code for n in notes} == codes
    if nopat <= 0:
        assert notes[0].params == {"reinvestment_rate": None}


def test_a_switch_beside_a_set_wacc_reproduces_and_follows_the_childs_method(company, parent):
    result = revalue(
        company,
        parent,
        [Change("terminal_method", method=dcf.GORDON), Change("wacc", delta=0.01)],
    )
    assert reproduce(company, result.run_id).ok
    assert "ronic_follows_wacc" not in [n.code for n in result.notes]  # the child is Gordon
    back = revalue(
        company,
        _gordon_parent(company),
        [Change("terminal_method", method=dcf.VALUE_DRIVER), Change("wacc", delta=0.01)],
    )
    assert "ronic_follows_wacc" in [n.code for n in back.notes]  # the child is value-driver


def test_a_gordon_child_stores_the_thin_spread_warning(company, parent):
    rows = _rows(company, parent)
    wacc = load_outputs(company, parent)[("wacc", SINGLE)]
    g = rows[("terminal_growth", SINGLE)].value
    result = revalue(
        company,
        parent,
        [
            Change("terminal_method", method=dcf.GORDON),
            Change("terminal_growth", value=wacc - 0.02),
        ],
    )
    warnings = [n.params["warning_code"] for n in result.notes if n.code == "run_warning"]
    assert "thin_terminal_spread" in warnings
    assert g != wacc - 0.02


# -- a leverage what-if (backlog #170) ----------------------------------------------------------


def _single(conn, run_id):
    return {a.name: a.value for a in load_assumptions(conn, run_id) if a.period == SINGLE}


def _note(result, code):
    return next(n for n in result.notes if n.code == code)


def _buyback(delta, *more):
    return [Change("debt", delta=delta, use="buyback"), *more]


def test_more_debt_equals_hand_edited_rows_with_hamada_beta(company, parent):
    p = _single(company, parent)
    result = revalue(company, parent, _buyback(100.0))
    shares = p["shares"] - 100.0 / p["price"]
    equity = p["price"] * shares
    unlevered = p["beta"] / (1 + (1 - p["debt_tax_rate"]) * p["debt"] / p["equity_market_value"])
    beta = unlevered * (1 + (1 - p["debt_tax_rate"]) * (p["debt"] + 100.0) / equity)
    edited = {"debt": p["debt"] + 100.0, "shares": shares, "equity_market_value": equity}
    edited["beta"] = beta
    rows = [
        a.model_copy(update={"value": edited[a.name]})
        if a.period == SINGLE and a.name in edited
        else a
        for a in load_assumptions(company, parent)
    ]
    expected = dcf.value(rows).value_per_share
    assert _line(result, "value_per_share").after == pytest.approx(expected, abs=1e-9)
    child = _single(company, result.run_id)
    assert child["beta"] == pytest.approx(beta, rel=1e-12)
    assert child["equity_market_value"] == pytest.approx(p["equity_market_value"] - 100.0)


def test_a_debt_child_reproduces_and_moves_exactly_four_rows(company, parent):
    result = revalue(company, parent, _buyback(100.0))
    assert reproduce(company, result.run_id).ok
    before, after = _rows(company, parent), _rows(company, result.run_id)
    assert before.keys() == after.keys()
    differ = {k[0] for k in before if before[k] != after[k]}
    # the fixture's cost of debt (4%) is above its risk-free rate (3%), so it is held
    assert differ == {"debt", "shares", "equity_market_value", "beta"}
    assert {c.how for c in result.changes} == {"add", "buyback", "relevered"}
    assert "use buyback" in after[("debt", SINGLE)].method


def test_no_change_in_debt_changes_no_value(company, parent):
    result = revalue(company, parent, _buyback(0.0))
    vps = _line(result, "value_per_share")
    assert abs(vps.after - vps.before) < 0.005
    assert [c.name for c in result.changes] == ["debt"]


def test_set_and_add_debt_give_the_same_values(company, parent):
    debt = _single(company, parent)["debt"]
    a = revalue(company, parent, [Change("debt", value=debt + 80.0, use="buyback")])
    b = revalue(company, parent, _buyback(80.0))
    assert _line(a, "value_per_share").after == pytest.approx(_line(b, "value_per_share").after)


def test_more_debt_raises_beta_and_the_cost_of_equity_and_less_lowers_them(company, parent):
    up, down = revalue(company, parent, _buyback(100.0)), revalue(company, parent, _buyback(-100.0))
    assert _line(up, "cost_of_equity").change > 0 > _line(down, "cost_of_equity").change
    assert _line(up, "cost_of_equity").driven_by == ["beta"]
    beta = {c.name: c for c in up.changes}["beta"]
    assert beta.after > beta.before
    # with the cost of debt held and a tax saving on interest, more debt lowers WACC
    assert _line(up, "wacc").change < 0
    assert "debt" in _line(up, "wacc").driven_by and "debt" in _line(up, "net_debt").driven_by


def test_modigliani_miller_no_tax_and_riskless_debt_keep_wacc(company, parent):
    rf = _single(company, parent)["risk_free"]
    mm = [Change("debt_tax_rate", value=0.0), Change("cost_of_debt", value=rf)]
    low, high = (
        revalue(company, parent, _buyback(50.0, *mm)),
        revalue(company, parent, _buyback(250.0, *mm)),
    )
    assert _line(low, "wacc").after == pytest.approx(_line(high, "wacc").after, rel=1e-12)
    # with a tax saving, riskless debt lowers WACC and raises the enterprise value
    taxed = [Change("cost_of_debt", value=rf)]
    a, b = (
        revalue(company, parent, _buyback(50.0, *taxed)),
        revalue(company, parent, _buyback(250.0, *taxed)),
    )
    assert _line(b, "wacc").after < _line(a, "wacc").after
    assert _line(b, "enterprise_value_as_of").after > _line(a, "enterprise_value_as_of").after


def test_a_book_cost_of_debt_below_the_risk_free_rate_is_floored(company, parent):
    result = revalue(company, parent, _buyback(100.0, Change("risk_free", value=0.05)))
    kd = {c.name: c for c in result.changes}["cost_of_debt"]
    assert (kd.before, kd.after, kd.how) == (pytest.approx(0.04), 0.05, "floored_at_risk_free")
    codes = [n.code for n in result.notes]
    assert "cost_of_debt_floored_at_risk_free" in codes
    assert "cost_of_debt_held_on_leverage" in codes
    assert "cost_of_debt_held" not in codes  # one reason for one held number (product lead)
    assert reproduce(company, result.run_id).ok


def test_a_cost_of_debt_set_by_the_student_is_used_and_not_called_held(company, parent):
    result = revalue(company, parent, _buyback(100.0, Change("cost_of_debt", value=0.07)))
    assert _single(company, result.run_id)["cost_of_debt"] == 0.07
    codes = [n.code for n in result.notes]
    assert "cost_of_debt_held_on_leverage" not in codes
    assert "cost_of_debt_floored_at_risk_free" not in codes


def test_the_leverage_notes_carry_the_numbers_behind_the_move(company, parent):
    p = _single(company, parent)
    result = revalue(company, parent, _buyback(100.0))
    lev = _note(result, "leverage_changed").params
    assert lev["debt_weight_before"] == pytest.approx(
        p["debt"] / (p["debt"] + p["equity_market_value"])
    )
    assert lev["debt_weight_after"] > lev["debt_weight_before"]
    assert lev["interest_coverage_after"] < lev["interest_coverage_before"]
    assert lev["price"] == p["price"] and lev["use"] == "buyback"
    split = _note(result, "buyback_at_market_price").params
    vps = _line(result, "value_per_share")
    assert split["swap_effect"] + split["enterprise_value_effect"] == pytest.approx(vps.change)
    json.dumps(result.to_dict())  # every param is plain data


@pytest.mark.parametrize(
    ("changes", "code", "params"),
    [
        (
            [Change("debt", delta=10.0, use="cash_kept")],
            "debt_use_not_supported",
            {"use": "cash_kept"},
        ),
        ([Change("beta", value=1.0, use="buyback")], "use_on_other_input", {"name": "beta"}),
        (_buyback(10.0, Change("beta", value=1.0)), "set_by_debt_change", {"name": "beta"}),
        (_buyback(10.0, Change("shares", value=90.0)), "set_by_debt_change", {"name": "shares"}),
        (_buyback(10.0, Change("wacc", value=0.09)), "wacc_with_rate_input", {"name": "debt"}),
        (_buyback(-1e6), "out_of_range", {"name": "debt"}),
        (_buyback(1e9), "buyback_exceeds_market_value", {"debt_change": 1e9}),
    ],
)
def test_leverage_refusals_have_a_code_and_store_nothing(company, parent, changes, code, params):
    count = _count(company)
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, changes)
    assert e.value.code == code
    assert params.items() <= e.value.params.items()
    assert _count(company) == count


def test_new_debt_on_a_run_with_none_needs_a_cost_of_debt(company, parent):
    # a run with no debt stores cost of debt 0 as a placeholder (math_engine._cost_of_debt)
    for name in ("debt", "cost_of_debt"):
        company.execute(
            "UPDATE assumptions SET value = 0 WHERE run_id = ? AND name = ? AND period = ?",
            (parent, name, SINGLE),
        )
    with pytest.raises(WhatIfError) as e:
        revalue(company, parent, _buyback(50.0))
    assert e.value.code == "cost_of_debt_needed" and e.value.params == {"debt_before": 0.0}
    result = revalue(company, parent, _buyback(50.0, Change("cost_of_debt", value=0.06)))
    assert _single(company, result.run_id)["cost_of_debt"] == 0.06


def test_a_debt_change_asked_again_is_reused_and_has_sources(company, parent):
    first = revalue(company, parent, _buyback(100.0))
    again = revalue(company, parent, _buyback(100.0))
    assert again.reused and again.run_id == first.run_id
    from domains.analysis import sources as src

    stored = src.load(company, first.run_id)
    hows = {k[0]: v[0].get("how") for k, v in stored.items() if v[0]["kind"] == "what_if"}
    assert hows == {
        "debt": "add",
        "shares": "buyback",
        "equity_market_value": "buyback",
        "beta": "relevered",
    }
