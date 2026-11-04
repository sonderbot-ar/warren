"""Numbers, dates and spreadsheet formulas as a student in each region reads and types them.

Every figure the app shows goes through `figure()`, so the design principles' number rules
(`docs/product/design-principles.md`, "How Warren looks") live in one place:

- one decimal for percentages, none for millions, two for per-share values and beta, one for
  multiples, whole basis points;
- negatives with a minus sign, or in parentheses as the filings show them in a statement;
- separators by region (Mexico 1,234.5; Argentina, Colombia and Chile 1.234,5; English 1,234.5);
- dates as "15 nov 2026" in Spanish and "Nov 15, 2026" in English.

This module only formats and parses. It never computes a financial number: the engine does,
and the app shows what the engine returned (standing rule; Decision 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from babel.dates import format_date as _babel_date
from babel.numbers import NumberFormatError, format_decimal, parse_decimal

MINUS = "−"  # the true minus sign: screen readers say "minus", and it is as wide as "+"


@dataclass(frozen=True)
class Region:
    """A language and the region whose separators, dates and spreadsheet use it follows."""

    code: str  # as the address and the cookie carry it, e.g. "es-MX"
    babel: str  # Babel's locale name, e.g. "es_MX"
    language: str  # "es" or "en": picks the text catalogue and the spreadsheet's words


REGIONS: dict[str, Region] = {
    r.code: r
    for r in (
        Region("es-MX", "es_MX", "es"),
        Region("es-AR", "es_AR", "es"),
        Region("es-CO", "es_CO", "es"),
        Region("es-CL", "es_CL", "es"),
        Region("en-US", "en_US", "en"),
    )
}
DEFAULT_REGION = REGIONS["es-MX"]  # the owner's default until said otherwise (principles)

# kind -> (scale applied to the engine's value, decimals, suffix). The engine sends rates as
# fractions (0.123) and money in units; the screen shows 12.3 (%), 1,234 (millones), 25 (pb).
KINDS: dict[str, tuple[Decimal, int, str]] = {
    "percent": (Decimal(100), 1, ""),
    "millions": (Decimal("0.000001"), 0, ""),
    "per_share": (Decimal(1), 2, ""),
    "beta": (Decimal(1), 2, ""),
    "multiple": (Decimal(1), 1, "×"),
    "bp": (Decimal(10000), 0, ""),
}


class NumberInputError(ValueError):
    """What a student typed is not a number in their region. `code` keys the message."""

    def __init__(self, code: str, text: str):
        super().__init__(f"{code}: {text!r}")
        self.code = code
        self.text = text


def region_for(code: str | None) -> Region:
    """The region for a code from the address or a cookie; the default for anything unknown."""
    return REGIONS.get(code or "", DEFAULT_REGION)


def _decimal(value: float | int | Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"a figure must be a number, not {type(value).__name__}")
    # str() first, so 0.1 stays 0.1 and not its binary neighbour 0.1000000000000000055...
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if not d.is_finite():
        raise ValueError("a figure must be finite")
    return d


def figure(
    value: float | int | Decimal,
    kind: str,
    region: Region = DEFAULT_REGION,
    *,
    negative: str = "minus",
) -> str:
    """One figure as the screen shows it, without its unit (the unit sits in the column header).

    `negative` is "minus" (−12.3) or "parentheses" ((12.3)), the latter for statement lines as
    the filings print them. Rounding is half up on the shown digits, as a student rounds by hand.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown figure kind {kind!r}; known: {sorted(KINDS)}")
    if negative not in ("minus", "parentheses"):
        raise ValueError("negative must be 'minus' or 'parentheses'")
    scale, decimals, suffix = KINDS[kind]
    shown = (_decimal(value) * scale).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    if shown == 0:
        shown = abs(shown)  # never "−0.0"
    pattern = "#,##0" + ("." + "0" * decimals if decimals else "")
    body = format_decimal(abs(shown), pattern, locale=region.babel) + suffix
    if shown >= 0:
        return body
    return f"({body})" if negative == "parentheses" else MINUS + body


def parse_number(text: str, region: Region = DEFAULT_REGION) -> Decimal:
    """What a student typed, read with their region's separators ("1.234,5" in Argentina).

    Strict: a group separator in the wrong place, or the other region's decimal mark, is refused
    rather than guessed, so "1.234,5" typed under Mexico's settings is an error, not 1.2345.
    """
    cleaned = text.strip().replace(MINUS, "-").replace(" ", "").replace(" ", "")
    if not cleaned:
        raise NumberInputError("empty", text)
    try:
        value = parse_decimal(cleaned, locale=region.babel, strict=True)
    except (NumberFormatError, InvalidOperation):
        raise NumberInputError("not_a_number", text) from None
    if not value.is_finite():
        raise NumberInputError("not_a_number", text)
    return value


_DATE_PATTERNS = {"es": "d MMM y", "en": "MMM d, y"}


def format_date(d: date, region: Region = DEFAULT_REGION) -> str:
    """A date as the principles fix it: "15 nov 2026" in Spanish, "Nov 15, 2026" in English."""
    return _babel_date(d, _DATE_PATTERNS[region.language], locale=region.babel).replace(".", "")


# Spreadsheet function names by language (Excel's and Google Sheets' Spanish names). Only the
# functions a screen uses are listed; a missing one fails loudly rather than showing English.
SPREADSHEET_FUNCTIONS: dict[str, dict[str, str]] = {
    "SUM": {"es": "SUMA", "en": "SUM"},
    "AVERAGE": {"es": "PROMEDIO", "en": "AVERAGE"},
    "PRODUCT": {"es": "PRODUCTO", "en": "PRODUCT"},
    "POWER": {"es": "POTENCIA", "en": "POWER"},
    "NPV": {"es": "VNA", "en": "NPV"},
}


def _spreadsheet_decimal_mark(region: Region) -> str:
    return format_decimal(Decimal("1.5"), "0.0", locale=region.babel)[1]


def spreadsheet_formula(
    function: str, args: list[str | float | int | Decimal], region: Region = DEFAULT_REGION
) -> str:
    """The formula a student would type in their spreadsheet (design principle 5).

    Where the decimal mark is a comma the argument separator is a semicolon, as Excel and
    Google Sheets use there: Argentina =SUMA(A1;0,5), Mexico =SUMA(A1,0.5), English =SUM(A1,0.5).
    Cell references (strings) pass through; numbers take the region's decimal mark, no grouping.
    """
    if function not in SPREADSHEET_FUNCTIONS:
        raise ValueError(f"no spreadsheet name for {function!r}")
    name = SPREADSHEET_FUNCTIONS[function][region.language]
    mark = _spreadsheet_decimal_mark(region)
    separator = ";" if mark == "," else ","
    parts = []
    for arg in args:
        if isinstance(arg, str):
            parts.append(arg)
        else:
            parts.append(format(_decimal(arg), "f").replace(".", mark))
    return f"={name}({separator.join(parts)})"
