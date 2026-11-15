"""Backlog #400: a profitable year whose own tax rate is outside the bounds, in the tax window."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis import coded, math_engine
from domains.analysis.text import WARNING_LESSONS
from tests.analysis.test_loss_year_tax import SPAN, YEARS, base, build, codes, rows, years_set

assert base  # the fixture, imported for its name

CODE = "tax_rate_outside_year_left_out"
LOSS = "tax_rate_loss_year_left_out"
LOW, HIGH = math_engine.TAX_RATE_BOUNDS


def note(result, code=CODE):
    found = [n for n in result.notes if n.code == code]
    assert len(found) == 1, codes(result)
    assert result.warnings.count(found[0].text) == 1
    return found[0]


def test_a_year_above_the_bound_is_left_out(make_company, base):
    p17, t17 = base[2017]
    p18, t18 = base[2018]
    p19, _ = base[2019]
    # FY2019 booked a one-off charge: 92.6% on its own
    values = {2019: (p19, 0.926 * p19)}
    result = build(make_company(years_set(values)))
    n = note(result)
    tax_sum = t17 + t18 + 0.926 * p19
    pretax_sum = p17 + p18 + p19
    rate = (t17 + t18) / (p17 + p18)
    assert n.params == {
        "period": SPAN,
        "outside_years": ["FY2019"],
        "outside_rates": [pytest.approx(0.926)],
        "low": LOW,
        "high": HIGH,
        "outside_left_out": True,
        "kept_years": ["FY2017", "FY2018"],
        "tax_sum": pytest.approx(tax_sum),
        "pretax_sum": pytest.approx(pretax_sum),
        "effective_rate": pytest.approx(tax_sum / pretax_sum),
        "kept_tax_sum": pytest.approx(t17 + t18),
        "kept_pretax_sum": pytest.approx(p17 + p18),
        "rate": pytest.approx(rate),
        "rate_used": pytest.approx(rate),
        "clipped": False,
        "currency": "USD",
        "assumptions": ["tax_rate", "debt_tax_rate"],
    }
    assert n.text == (
        f"FY2019's own tax rate was 92.6%, outside 0% to 50%, so the tax rate is read from "
        f"FY2017, FY2018 only: {rate:.1%} instead of {tax_sum / pretax_sum:.1%} over {SPAN}"
    )
    method = (
        "Σ income tax / Σ pretax income, FY2017, FY2018 (FY2019, own rate outside 0% to 50%, "
        "left out)"
    )
    for name in ("tax_rate", "debt_tax_rate"):
        for a in rows(result, name):
            assert a.value == pytest.approx(rate)
            assert a.method == method
            found = result.sources[(a.name, a.period)]
            assert found[0]["kind"] == "derived"
            inputs = {(i["name"], i["period"]) for i in found[0]["inputs"]}
            assert inputs == {(f"history:{i}", f"FY{y}") for y in YEARS for i in ("tax", "pretax")}
    assert LOSS not in codes(result)
    assert "tax_rate_clipped" not in codes(result)


def test_a_profitable_year_with_a_tax_benefit_is_left_out(make_company, base):
    p17, t17 = base[2017]
    p18, _ = base[2018]
    p19, t19 = base[2019]
    result = build(make_company(years_set({2018: (p18, -0.05 * p18)})))
    n = note(result)
    assert n.params["outside_years"] == ["FY2018"]
    assert n.params["outside_rates"] == [pytest.approx(-0.05)]
    assert n.text.startswith("FY2018's own tax rate was -5.0%, outside 0% to 50%")
    assert rows(result, "tax_rate")[0].value == pytest.approx((t17 + t19) / (p17 + p19))


@pytest.mark.parametrize("own", [LOW, HIGH])
def test_a_rate_exactly_on_a_bound_stays_in(make_company, base, own):
    p17, t17 = base[2017]
    p18, t18 = base[2018]
    p19, _ = base[2019]
    result = build(make_company(years_set({2019: (p19, own * p19)})))
    assert CODE not in codes(result)
    expected = (t17 + t18 + own * p19) / (p17 + p18 + p19)
    assert rows(result, "tax_rate")[0].value == pytest.approx(expected)
    assert rows(result, "debt_tax_rate")[0].method == f"effective tax rate, {SPAN}"


def test_two_outside_years_read_the_third(make_company, base):
    p17, t17 = base[2017]
    p18, _ = base[2018]
    p19, _ = base[2019]
    result = build(make_company(years_set({2018: (p18, 1.38 * p18), 2019: (p19, 0.82 * p19)})))
    n = note(result)
    assert n.params["outside_years"] == ["FY2018", "FY2019"]
    assert n.params["outside_rates"] == [pytest.approx(1.38), pytest.approx(0.82)]
    assert n.params["kept_years"] == ["FY2017"]
    assert n.text.startswith("FY2018, FY2019's own tax rates were 138.0%, 82.0%, outside")
    assert [a.value for a in rows(result, "tax_rate")] == pytest.approx([t17 / p17] * 11)


def test_every_year_outside_keeps_them_all_and_clips(make_company, base):
    values = {y: (base[y][0], 0.6 * base[y][0]) for y in YEARS}
    result = build(make_company(years_set(values)))
    n = note(result)
    assert n.params["outside_left_out"] is False
    assert n.params["kept_years"] == ["FY2017", "FY2018", "FY2019"]
    assert n.params["rate"] == pytest.approx(0.6)
    assert n.params["rate_used"] == HIGH
    assert n.params["clipped"] is True
    assert "but they are every profitable year, so none is left out" in n.text
    assert codes(result).index(CODE) < codes(result).index("tax_rate_clipped")
    assert {a.value for a in rows(result, "tax_rate")} == {HIGH}
    assert rows(result, "tax_rate")[0].method.startswith(
        "Σ income tax / Σ pretax income, FY2017, FY2018, FY2019; 60.00% clipped"
    )


def test_a_loss_year_and_an_outside_year_give_both_notes(make_company, base):
    p17, t17 = base[2017]
    p18, _ = base[2018]
    values = {2018: (p18, 0.9 * p18), 2019: (-p17 / 10, -p17 / 100)}
    result = build(make_company(years_set(values)))
    loss, outside = note(result, LOSS), note(result, CODE)
    assert codes(result).index(LOSS) < codes(result).index(CODE)
    for n in (loss, outside):
        assert n.params["kept_years"] == ["FY2017"]
        assert n.params["rate"] == pytest.approx(t17 / p17)
    assert loss.text.startswith(
        "FY2019 was a loss year, so the tax rate is read from FY2017 only (FY2018 is also left "
        "out, see the next note): "
    )
    assert rows(result, "tax_rate")[0].method == (
        "Σ income tax / Σ pretax income, FY2017 (FY2019, a loss year, left out; FY2018, own rate "
        "outside 0% to 50%, left out)"
    )


def test_the_floor_wins_over_an_outside_year(make_company, base):
    p17, _ = base[2017]
    p18, _ = base[2018]
    # losses outweigh profits; the one profitable year is also at 90%
    values = {2017: (p17, 0.9 * p17), 2018: (-p17, 0.0), 2019: (-p18, 0.0)}
    result = build(make_company(years_set(values)))
    assert "tax_rate_statutory" in codes(result)
    assert CODE not in codes(result) and LOSS not in codes(result)


money = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)
rate = st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False)


@given(st.lists(st.tuples(money, rate), min_size=3, max_size=3))
def test_tax_years_always_keeps_a_profitable_year(years):
    """For any window with a profitable year (which every window above the floor has, #393), the
    kept years are non-empty, all profitable, and kept + loss + outside left out is the window."""
    pretax_tax = {2017 + i: (p, p * r) for i, (p, r) in enumerate(years)}
    if all(p <= 0 for p, _ in pretax_tax.values()):
        return
    t = math_engine.tax_years(pretax_tax)
    assert t.kept and all(pretax_tax[y][0] > 0 for y in t.kept)
    assert sum(pretax_tax[y][0] for y in t.kept) > 0
    left_out = t.outside if t.outside_left_out else []
    assert sorted(t.kept + t.loss + left_out) == sorted(pretax_tax)
    assert not set(t.kept) & set(left_out)
    if t.outside and not t.outside_left_out:
        assert sorted(t.outside) == sorted(t.kept)


def test_the_lesson_is_catalogued():
    lesson = WARNING_LESSONS[CODE]
    assert lesson.group == "assumption"
    assert lesson.params == {"low": LOW, "high": HIGH}
    text = lesson.text()
    assert "0% to 50%" in text and "one-off" in text and "tax reform" in text and "screen" in text
    assert "2017" in lesson.reference
    assert CODE in coded.RUN_NOTE_CODES
    assert "thinner base" in WARNING_LESSONS[LOSS].text()
