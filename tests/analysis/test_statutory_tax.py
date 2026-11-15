"""Backlog #385: the statutory tax rate when three years of pretax income are at or near zero."""

import math
from datetime import date

import pytest

from domains.analysis import coded, math_engine, sources
from domains.analysis.statutory_tax import RATES, StatutoryRateError, statutory_rate
from domains.analysis.text import WARNING_LESSONS
from tests.analysis.conftest import AS_OF, CHOICES

PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
TAX = "IncomeTaxExpenseBenefit"
SPAN = "FY2017-FY2019"
YEARS = (2017, 2018, 2019)


def build(conn):
    return math_engine.build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def codes(result):
    return [n.code for n in result.notes]


def note(result):
    found = [n for n in result.notes if n.code == "tax_rate_statutory"]
    assert len(found) == 1, codes(result)
    assert result.warnings.count(found[0].text) == 1
    return found[0]


def annual(result, item):
    return sum(result.value_of(f"history:{item}", f"FY{y}") for y in YEARS)


def rows(result, name):
    return [a for a in result.assumptions if a.name == name]


def scaled(tag_prefix, factor, also=None):
    """Scale every annual (FY) row of the tags starting with `tag_prefix` (and of `also`)."""

    def edit(tag, row):
        if (tag.startswith(tag_prefix) or tag == also) and row["fp"] == "FY":
            return {**row, "val": row["val"] * factor}
        return row

    return edit


def margin(company):
    base = build(company)
    return annual(base, "pretax") / annual(base, "revenue")


# --- the rate table -------------------------------------------------------------------------


def test_the_rate_is_the_newest_law_enacted_by_the_date():
    assert statutory_rate("US", date(2017, 12, 21)).rate == 0.35
    assert statutory_rate("US", date(2017, 12, 22)).rate == 0.21  # signed, applies from 2018
    assert statutory_rate("US", date(2017, 12, 22)).applies_from == date(2018, 1, 1)
    assert statutory_rate("US", math_engine.SUPPORTED_FROM).rate == 0.21


def test_an_unknown_jurisdiction_or_a_date_before_every_law_is_refused():
    with pytest.raises(StatutoryRateError):
        statutory_rate("MX", date(2020, 1, 1))
    with pytest.raises(StatutoryRateError):
        statutory_rate("US", date(1990, 1, 1))


def test_every_rate_is_a_dated_sourced_fraction():
    for r in RATES:
        assert 0 < r.rate < 1
        assert r.applies_from <= r.enacted_on.replace(year=r.enacted_on.year + 1)
        assert r.law and r.source
    assert coded.TAX_JURISDICTIONS == {"US"}


# --- the fallback in a run ------------------------------------------------------------------


def test_a_normal_company_keeps_its_effective_rate(company):
    result = build(company)
    assert "tax_rate_statutory" not in codes(result)
    assert [a.value for a in rows(result, "tax_rate")] == pytest.approx([0.25] * 11)
    assert rows(result, "debt_tax_rate")[0].method == f"effective tax rate, {SPAN}"


def test_a_zero_pretax_sum_builds_with_the_statutory_rate(make_company):
    # #383 refused this run with zero_divisor; #385 builds it on the statutory rate
    zero = lambda t, r: {**r, "val": 0} if t.startswith(PRETAX) and r["fp"] == "FY" else r  # noqa: E731
    result = build(make_company(zero))
    n = note(result)
    tax_sum = annual(result, "tax")
    revenue = annual(result, "revenue")
    assert n.params == {
        "tax_sum": tax_sum,
        "pretax_sum": 0,
        "revenue_sum": revenue,
        "currency": "USD",
        "pretax_margin": 0.0,
        "effective_rate": None,
        "floor": 0.01,
        "period": SPAN,
        "rate": 0.21,
        "jurisdiction": "US",
        "law": "Pub. L. 115-97 (the Tax Cuts and Jobs Act)",
        "enacted_on": "2017-12-22",
        "applies_from": "2018-01-01",
        "source": RATES[1].source,
        "assumptions": ["tax_rate", "debt_tax_rate"],
    }
    assert n.text == (
        f"Pretax income over {SPAN} is 0.0% of revenue, at or below 1%, so the effective tax "
        "rate means little; the US federal statutory rate of 21% is used instead"
    )
    assert n.params["jurisdiction"] in coded.TAX_JURISDICTIONS
    for name in ("tax_rate", "debt_tax_rate"):
        for a in rows(result, name):
            assert a.value == 0.21
            assert a.method.startswith("US federal statutory rate (Pub. L. 115-97")


def test_the_statutory_rows_name_the_rule_and_the_sums_behind_it(make_company):
    zero = lambda t, r: {**r, "val": 0} if t.startswith(PRETAX) and r["fp"] == "FY" else r  # noqa: E731
    result = build(make_company(zero))
    expected = {(f"history:{i}", f"FY{y}") for y in YEARS for i in ("tax", "pretax", "revenue")}
    for name in ("tax_rate", "debt_tax_rate"):
        for a in rows(result, name):
            found = result.sources[(a.name, a.period)]
            assert found[0] == {"kind": "rule", "code": "statutory_tax_rate"}
            assert {(i["name"], i["period"]) for i in found[1]["inputs"]} == expected
    assert "statutory_tax_rate" in sources.RULES


def test_a_tiny_positive_pretax_sum_is_not_clipped(make_company, company):
    factor = 0.005 / margin(company)  # a 0.5% three-year pretax margin, taxes unchanged
    result = build(make_company(scaled(PRETAX, factor)))
    n = note(result)
    assert n.params["pretax_margin"] == pytest.approx(0.005)
    assert n.params["effective_rate"] == pytest.approx(0.25 / factor)  # far above 50%
    assert "tax_rate_clipped" not in codes(result)
    assert {a.value for a in rows(result, "tax_rate")} == {0.21}


def test_a_loss_takes_the_statutory_rate_whatever_the_tax_line(make_company):
    # losses with a tax benefit: the ratio is a normal-looking 25%, but it means nothing
    result = build(make_company(scaled(PRETAX, -1, also=TAX)))
    n = note(result)
    assert n.params["pretax_sum"] < 0
    assert n.params["effective_rate"] == pytest.approx(0.25)
    assert {a.value for a in rows(result, "tax_rate")} == {0.21}


def test_just_above_the_floor_keeps_the_effective_rate(make_company, company):
    factor = 0.0101 / margin(company)
    result = build(make_company(scaled(PRETAX, factor, also=TAX)))  # tax scaled too: still 25%
    assert "tax_rate_statutory" not in codes(result)
    assert [a.value for a in rows(result, "tax_rate")] == pytest.approx([0.25] * 11)


def test_just_below_the_floor_takes_the_statutory_rate(make_company, company):
    result = build(make_company(scaled(PRETAX, 0.0099 / margin(company), also=TAX)))
    assert note(result).params["pretax_margin"] == pytest.approx(0.0099)


def last_year_only(pretax):
    """FY2017 and FY2018 pretax set to 0 and FY2019's to `pretax`, so Σ pretax is `pretax`
    exactly (0 + 0 + x == x in floating point), in every filing that gives those years."""

    def edit(tag, row):
        if tag.startswith(PRETAX) and row["fp"] == "FY" and row["end"][:4] in {"2017", "2018"}:
            return {**row, "val": 0}
        if tag.startswith(PRETAX) and row["fp"] == "FY" and row["end"] == "2019-12-31":
            return {**row, "val": pretax}
        return row

    return edit


def test_exactly_at_the_floor_takes_the_statutory_rate(make_company, company):
    # the rule is "at or below" (backlog #395): Σ pretax equal to the floor × Σ revenue
    floor = math_engine.PRETAX_MARGIN_FLOOR * annual(build(company), "revenue")
    result = build(make_company(last_year_only(floor)))
    assert annual(result, "pretax") == floor  # the case is the one meant
    assert note(result).params["pretax_sum"] == floor
    assert {a.value for a in rows(result, "tax_rate")} == {0.21}


def test_one_step_above_the_floor_keeps_the_effective_rate(make_company, company):
    floor = math_engine.PRETAX_MARGIN_FLOOR * annual(build(company), "revenue")
    result = build(make_company(last_year_only(math.nextafter(floor, math.inf))))
    assert annual(result, "pretax") > floor
    assert "tax_rate_statutory" not in codes(result)


def test_zero_revenue_with_a_loss_has_no_margin():
    # the fallback test is a multiplication, so it can't divide by a zero revenue sum; the run
    # is refused later by the revenue ratios (zero_divisor), so the helper is tested directly

    result = math_engine.EngineResult("TST", "0000000123", AS_OF)
    rate, method = math_engine._statutory_tax(result, list(YEARS), SPAN, 1.0, -5.0, 0)
    assert rate == 0.21
    params = result.notes[0].params
    assert params["pretax_margin"] is None
    assert params["effective_rate"] == pytest.approx(-0.2)
    assert params["currency"] is None
    assert "with no revenue" in result.notes[0].text


def test_the_lesson_names_its_floor_and_its_gaps():
    lesson = WARNING_LESSONS["tax_rate_statutory"]
    assert lesson.group == "assumption"
    assert lesson.params["floor"] == math_engine.PRETAX_MARGIN_FLOOR
    text = lesson.text()
    assert "1% of revenue" in text
    assert "federal" in text and "abroad" in text and "losses" in text
    assert "tax_rate_statutory" in coded.RUN_NOTE_CODES
