"""The number, date and formula rules of the design principles ("How Warren looks", principle 5)."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from webapp.formatting import (
    MINUS,
    REGIONS,
    NumberInputError,
    figure,
    format_date,
    parse_number,
    region_for,
    spreadsheet_formula,
)

MX, AR, US = REGIONS["es-MX"], REGIONS["es-AR"], REGIONS["en-US"]


@pytest.mark.parametrize(
    ("value", "kind", "region", "shown"),
    [
        (0.1234, "percent", MX, "12.3"),  # one decimal for percentages
        (0.1234, "percent", AR, "12,3"),
        (1_234_567_890.0, "millions", MX, "1,235"),  # none for millions
        (1_234_567_890.0, "millions", AR, "1.235"),
        (412.345, "per_share", MX, "412.35"),  # two per share, half up
        (412.345, "per_share", AR, "412,35"),
        (1.234, "beta", US, "1.23"),  # two for beta
        (12.34, "multiple", MX, "12.3×"),  # one for multiples, with ×
        (12.34, "multiple", AR, "12,3×"),
        (0.0025, "bp", MX, "25"),  # whole basis points
        (0.00255, "bp", MX, "26"),
        (1234.5, "per_share", US, "1,234.50"),
    ],
)
def test_figures_follow_the_principles_table(value, kind, region, shown):
    assert figure(value, kind, region) == shown


def test_negatives_take_a_minus_sign_or_parentheses():
    assert figure(-0.05, "percent", MX) == MINUS + "5.0"
    assert figure(-1_500_000_000, "millions", AR, negative="parentheses") == "(1.500)"


def test_a_value_that_rounds_to_zero_is_never_negative_zero():
    assert figure(-0.00001, "percent", MX) == "0.0"


def test_rounding_uses_the_decimal_value_not_its_binary_neighbour():
    # 1.005 is 1.00499999... in binary; the student sees 1.005 and rounds it to 1.01
    assert figure(1.005, "per_share", MX) == "1.01"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "12"])
def test_a_figure_must_be_a_finite_number(bad):
    with pytest.raises((TypeError, ValueError)):
        figure(bad, "percent", MX)


def test_unknown_kinds_fail_loudly():
    with pytest.raises(ValueError):
        figure(1, "ratio", MX)


@pytest.mark.parametrize(
    ("text", "region", "value"),
    [
        ("1.234,5", AR, Decimal("1234.5")),
        ("1,234.5", MX, Decimal("1234.5")),
        ("−2,5", AR, Decimal("-2.5")),  # the minus sign the app itself shows
        (" 25 ", MX, Decimal("25")),
    ],
)
def test_typed_numbers_are_read_with_the_regions_separators(text, region, value):
    assert parse_number(text, region) == value


@pytest.mark.parametrize(
    ("text", "region"),
    [("1.234,5", MX), ("1,234.5", AR), ("", MX), ("doce", MX), ("1,23,4", MX)],
)
def test_ambiguous_or_foreign_input_is_refused_not_guessed(text, region):
    with pytest.raises(NumberInputError):
        parse_number(text, region)


@given(st.decimals(min_value=-(10**9), max_value=10**9, places=2, allow_nan=False))
def test_a_shown_per_share_value_reads_back_to_itself(value):
    for region in (MX, AR, US):
        assert parse_number(figure(value, "per_share", region), region) == value


def test_dates_are_pinned():
    d = date(2026, 11, 15)
    assert format_date(d, MX) == "15 nov 2026"
    assert format_date(d, AR) == "15 nov 2026"
    assert format_date(d, US) == "Nov 15, 2026"
    # September follows each region's own usage (CLDR): "sep" in Mexico, "sept" further south
    assert format_date(date(2026, 9, 1), MX) == "1 sep 2026"
    assert format_date(date(2026, 9, 1), AR) == "1 sept 2026"


@pytest.mark.parametrize(
    ("region", "formula"),
    [(MX, "=SUMA(A1,0.5)"), (AR, "=SUMA(A1;0,5)"), (US, "=SUM(A1,0.5)")],
)
def test_spreadsheet_formulas_use_the_regions_separators(region, formula):
    assert spreadsheet_formula("SUM", ["A1", 0.5], region) == formula


def test_spreadsheet_function_names_are_translated():
    assert spreadsheet_formula("NPV", ["B1", "C2:C6"], AR) == "=VNA(B1;C2:C6)"
    with pytest.raises(ValueError):
        spreadsheet_formula("XNPV", [], MX)


def test_unknown_region_codes_fall_back_to_mexico():
    assert region_for(None) is MX
    assert region_for("pt-BR") is MX
