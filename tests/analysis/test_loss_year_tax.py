"""Backlog #393: a loss year inside the tax rate's three-year window, above the statutory floor."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis import coded, math_engine
from domains.analysis.text import WARNING_LESSONS
from tests.analysis.conftest import AS_OF, CHOICES

PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
TAX = "IncomeTaxExpenseBenefit"
SPAN = "FY2017-FY2019"
YEARS = (2017, 2018, 2019)
CODE = "tax_rate_loss_year_left_out"


def build(conn):
    return math_engine.build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def codes(result):
    return [n.code for n in result.notes]


def note(result):
    found = [n for n in result.notes if n.code == CODE]
    assert len(found) == 1, codes(result)
    assert result.warnings.count(found[0].text) == 1
    return found[0]


def year_value(result, item, year):
    return result.value_of(f"history:{item}", f"FY{year}")


def rows(result, name):
    return [a for a in result.assumptions if a.name == name]


def years_set(values: dict[int, tuple[float, float]]):
    """Set FY pretax and tax to `values[year] = (pretax, tax)` in every filing giving that year."""

    def edit(tag, row):
        year = int(row["end"][:4])
        if year in values and row["fp"] == "FY":
            pretax, tax = values[year]
            if tag.startswith(PRETAX):
                return {**row, "val": pretax}
            if tag == TAX:
                return {**row, "val": tax}
        return row

    return edit


@pytest.fixture
def base(company):
    result = build(company)
    return {y: (year_value(result, "pretax", y), year_value(result, "tax", y)) for y in YEARS}


def test_no_loss_year_keeps_the_window_rate(company):
    result = build(company)
    assert CODE not in codes(result)
    assert [a.value for a in rows(result, "tax_rate")] == pytest.approx([0.25] * 11)
    assert rows(result, "debt_tax_rate")[0].method == f"effective tax rate, {SPAN}"


def test_a_loss_year_is_left_out(make_company, base):
    p17, t17 = base[2017]
    p18, t18 = base[2018]
    # FY2019 a loss a third the size of FY2018's profit, with a small benefit (5%)
    loss = -p18 / 3
    values = {2017: (p17, t17 * 1.2), 2018: (p18, t18), 2019: (loss, 0.05 * loss)}
    result = build(make_company(years_set(values)))
    n = note(result)
    tax_sum = t17 * 1.2 + t18 + 0.05 * loss
    pretax_sum = p17 + p18 + loss
    rate = (t17 * 1.2 + t18) / (p17 + p18)
    assert n.params == {
        "period": SPAN,
        "loss_years": ["FY2019"],
        "kept_years": ["FY2017", "FY2018"],
        "tax_sum": pytest.approx(tax_sum),
        "pretax_sum": pytest.approx(pretax_sum),
        "effective_rate": pytest.approx(tax_sum / pretax_sum),
        "kept_tax_sum": pytest.approx(t17 * 1.2 + t18),
        "kept_pretax_sum": pytest.approx(p17 + p18),
        "rate": pytest.approx(rate),
        "rate_used": pytest.approx(rate),
        "clipped": False,
        "currency": "USD",
        "assumptions": ["tax_rate", "debt_tax_rate"],
    }
    assert n.text == (
        f"FY2019 was a loss year, so the tax rate is read from FY2017, FY2018 only: {rate:.1%} "
        f"instead of {tax_sum / pretax_sum:.1%} over {SPAN}"
    )
    method = "Σ income tax / Σ pretax income, FY2017, FY2018 (FY2019, a loss year, left out)"
    for name in ("tax_rate", "debt_tax_rate"):
        for a in rows(result, name):
            assert a.value == pytest.approx(rate)
            assert a.method == method
            found = result.sources[(a.name, a.period)]
            assert found[0]["kind"] == "derived"
            inputs = {(i["name"], i["period"]) for i in found[0]["inputs"]}
            assert inputs == {(f"history:{i}", f"FY{y}") for y in YEARS for i in ("tax", "pretax")}
    assert "tax_rate_statutory" not in codes(result)


def test_two_loss_years_read_the_one_profitable_year(make_company, base):
    p17, t17 = base[2017]
    values = {2018: (-p17 / 10, 0.0), 2019: (-p17 / 10, -p17 / 100)}
    result = build(make_company(years_set(values)))
    n = note(result)
    assert n.params["loss_years"] == ["FY2018", "FY2019"]
    assert n.params["kept_years"] == ["FY2017"]
    assert n.text.startswith("FY2018, FY2019 were loss years, so the tax rate is read from FY2017")
    assert [a.value for a in rows(result, "tax_rate")] == pytest.approx([t17 / p17] * 11)
    assert rows(result, "tax_rate")[0].method.endswith("(FY2018, FY2019, loss years, left out)")


def test_a_year_at_exactly_zero_pretax_is_left_out(make_company, base):
    p17, t17 = base[2017]
    p18, t18 = base[2018]
    result = build(make_company(years_set({2019: (0.0, 1_000_000.0)})))
    assert note(result).params["loss_years"] == ["FY2019"]
    assert rows(result, "tax_rate")[0].value == pytest.approx((t17 + t18) / (p17 + p18))


def test_the_floor_wins_over_a_loss_year(make_company, base):
    # the window's losses outweigh its profits: the statutory rate, and no loss-year note
    p17, t17 = base[2017]
    result = build(make_company(years_set({2019: (-2 * p17, -0.5 * p17)})))
    assert "tax_rate_statutory" in codes(result)
    assert CODE not in codes(result)
    assert {a.value for a in rows(result, "tax_rate")} == {0.21}


def test_a_kept_rate_above_the_bound_is_clipped_with_both_notes(make_company, base):
    p17, _ = base[2017]
    p18, _ = base[2018]
    values = {2017: (p17, 0.6 * p17), 2018: (p18, 0.6 * p18), 2019: (-p18 / 4, 0.0)}
    result = build(make_company(years_set(values)))
    params = note(result).params
    assert params["rate"] == pytest.approx(0.6)
    assert params["rate_used"] == math_engine.TAX_RATE_BOUNDS[1]
    assert params["clipped"] is True
    assert "tax_rate_clipped" in codes(result)
    assert codes(result).index(CODE) < codes(result).index("tax_rate_clipped")
    assert {a.value for a in rows(result, "tax_rate")} == {math_engine.TAX_RATE_BOUNDS[1]}


money = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)
revenue = st.floats(min_value=1.0, max_value=1e12, allow_nan=False, allow_infinity=False)


@given(st.lists(st.tuples(money, revenue), min_size=3, max_size=3))
def test_the_kept_years_are_above_the_floor_whenever_the_window_is(years):
    """The design's claim: a window above the floor that holds a loss year always keeps at least
    one year, and the kept years' margin is above the floor on their own revenue."""
    pretax_sum = sum(p for p, _ in years)
    revenue_sum = sum(r for _, r in years)
    if pretax_sum <= math_engine.PRETAX_MARGIN_FLOOR * revenue_sum:
        return
    kept = [(p, r) for p, r in years if p > 0]
    assert kept
    assert sum(p for p, _ in kept) > math_engine.PRETAX_MARGIN_FLOOR * sum(r for _, r in kept)


def test_the_lesson_is_catalogued():
    lesson = WARNING_LESSONS[CODE]
    assert lesson.group == "assumption"
    assert lesson.params == {}
    text = lesson.text()
    assert "loss" in text and "benefit" in text and "deduct" in text and "profitable" in text
    assert CODE in coded.RUN_NOTE_CODES
