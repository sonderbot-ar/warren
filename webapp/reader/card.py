"""What the reading card asks and says before anything is computed (F2 Step 3b; Decision 9).

The owner took Claude Haiku as the question reader behind this card at its measured error rate
(nov.08.2026), so the card is where a wrong or incomplete reading is caught. `card_for` turns a
checked `Reading` into the card's content as data: the value of each input read by code from
the span the reader copied, the questions the student must answer (`asks`) and the lines the
card must show (`notes`). Each ask and note is a code with params; their words live in the
catalogues under "card.ask.<code>" and "card.note.<code>", so this module holds none.

Nothing here computes a financial number. `parse_value` reads the student's own number from
their question, as `formatting.parse_number` reads a number they type; the engine computes the
answer only after the student confirms the card. No model is called.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from babel.numbers import get_decimal_symbol, get_group_symbol

from domains.analysis import dcf
from webapp.formatting import DEFAULT_REGION, Region, format_date
from webapp.reader.reading import Reading, tickers

# The units a copied value can carry. The amount is in that unit, as the student wrote it:
# "7,5%" is 7.5 percent, "25 pb" is 25 bp, "un punto" is 1 point, "doubled" is a multiple of 2,
# "US$5.000 millones" is 5,000,000,000 US dollars. Turning it into the input's own unit is the
# engine call's job, after the student confirms.
UNITS = ("percent", "bp", "points", "plain", "multiple", "money", "method")

# Kinds whose answer is about one company. An out-of-scope reading is answered as brief §4 says.
NEEDS_COMPANY = ("dato", "estimacion", "cambio_de_supuesto", "evento")

# Inputs that are rates: a "%" on a move of one is either points or a share of its level.
RATES = (
    *dcf.DRIVERS, "risk_free", "erp", "cost_of_debt", "debt_tax_rate", "terminal_growth", "wacc"
)  # fmt: skip
WACC_PARTS = ("risk_free", "beta", "erp", "cost_of_debt", "debt_tax_rate")

# In the order the student answers them.
ASKS = (
    "reader_unsure",
    "company_missing",
    "value_range",
    "value_missing",
    "value_missing_via",
    "value_currency",
    "value_ambiguous",
    "value_unreadable",
    "percent_or_points",
    "points_or_bp",
    "fed_surprise",
    "wacc_and_parts",
    "driver_periods",
    "method_unknown",
)
NOTES = (
    "corte_default",
    "corte_from_question",
    "fed_move_is_event",
    "relative_change",
    "cash_unchanged",
    "wacc_bypasses_parts",
    "usd_only",
    "intrinsic_value_offer",
    "intrinsic_value_offer_target",
)

_SURPRISE = ("sorpres", "inesperad", "imprevist", "surprise", "unexpected")
# Whole words or phrases only: "real" and "reales" are everyday words ("crecimiento real"),
# "pen" and "cop" English ones, so the Brazilian real is matched in a phrase.
_CURRENCIES = (
    "peso", "pesos", "reais", "en reales", "de reales", "reales brasilenos", "soles",
    "mxn", "ars", "clp", "brl", "uyu",
)  # fmt: skip
_TARGET_PRICE = ("precio objetivo", "target price", "price target")


@dataclass(frozen=True)
class Value:
    """A value read from the question. `amount` is None for a method word."""

    amount: Decimal | None
    unit: str
    text: str  # the span as copied, shown on the card beside what code read
    method: str | None = None  # "gordon" for a terminal method


@dataclass(frozen=True)
class Item:
    """One code with its params: a question the card asks, or a line it shows."""

    code: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Card:
    reading: Reading
    values: tuple[Value | None, ...]  # one per reading.inputs, in the same order
    asks: tuple[Item, ...]
    notes: tuple[Item, ...]

    @property
    def ready(self) -> bool:
        """True when Calcular may be offered: nothing left to answer, and something to compute.
        An out-of-scope card never computes; a price question links to an estimación instead."""
        return not self.asks and self.reading.kind != "fuera_de_alcance"


class Unreadable(ValueError):
    """The span is not a value code can read. `code` is the ask the card shows."""

    def __init__(self, code: str, text: str, **params):
        super().__init__(f"{code}: {text!r}")
        self.code = code
        self.text = text
        self.params = params


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", _fold(text))


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_RANGE_WORDS = ("entre", "between")
_DASH_RANGE = re.compile(r"\d\s*[-–—]\s*\d")
_NEGATIVE = re.compile(r"(?:^|\s)[-−]\s*\d|\(\s*\d[^)]*\)")

# Number words the reader's sets use, read only when the span has no digits. More than one
# (other than an article before a fraction, "un cuarto", "half a point") is unreadable, so
# "un punto y medio" is asked, never read as 0.5.
_ARTICLES = ("un", "una", "a")
_NUMBER_WORDS = {
    "zero": "0", "cero": "0",
    "un": "1", "una": "1", "uno": "1", "a": "1", "one": "1", "full": "1",
    "medio": "0.5", "media": "0.5", "half": "0.5",
    "cuarto": "0.25", "quarter": "0.25",
    "dos": "2", "two": "2", "tres": "3", "three": "3",
}  # fmt: skip
_MULTIPLES = {
    "doble": "2", "duplica": "2", "duplicar": "2", "duplicando": "2", "duplicado": "2",
    "double": "2", "doubled": "2", "doubles": "2", "doubling": "2",
    "mitad": "0.5", "halved": "0.5", "halve": "0.5", "halves": "0.5",
}  # fmt: skip
_SCALE_WORDS = {
    "millon": 6, "millones": 6, "million": 6, "millions": 6, "mm": 6, "m": 6,
    "billion": 9, "billions": 9, "bn": 9, "b": 9,
}  # fmt: skip
_BP_WORDS = {"pb", "pbs", "bp", "bps"}
_POINT_WORDS = {"punto", "puntos", "point", "points", "pp", "porcentual", "porcentuales"}
_PERCENT_WORDS = {"ciento", "percent", "pct"}
_DOLLAR_WORDS = {"usd", "dolar", "dolares", "dollar", "dollars"}


def _read_number(token: str, region: Region, count: bool) -> Decimal:
    """One number as typed. A lone separator with one or two digits after it is a decimal mark
    in any region. With exactly three, it is the region's group mark on an amount or a count
    ("5.000" in Argentina); it is asked when it is the region's decimal mark ("5.000" in
    Mexico), and always on a rate ("4,125%"), where a thousands group makes no sense."""
    decimal_mark = get_decimal_symbol(region.babel)
    group_mark = get_group_symbol(region.babel)
    marks = [ch for ch in token if ch in ".,"]
    try:
        if not marks:
            return Decimal(token)
        if len(set(marks)) == 2:  # both marks: the region's rule, strictly
            if token.rfind(decimal_mark) < token.rfind(group_mark):
                raise Unreadable("value_unreadable", token)
            return Decimal(token.replace(group_mark, "").replace(decimal_mark, "."))
        mark = marks[0]
        groups = token.split(mark)
        if len(groups) > 2:  # "1.234.567": only a group mark repeats
            if mark != group_mark or any(len(g) != 3 for g in groups[1:]):
                raise Unreadable("value_unreadable", token)
            return Decimal("".join(groups))
        whole, tail = groups
        if len(tail) != 3:
            return Decimal(f"{whole}.{tail}")
        as_decimal, as_group = Decimal(f"{whole}.{tail}"), Decimal(whole + tail)
        if mark == group_mark and count:
            return as_group
        raise Unreadable("value_ambiguous", token, readings=(as_decimal, as_group))
    except InvalidOperation:
        raise Unreadable("value_unreadable", token) from None


def is_range(text: str) -> bool:
    """Two numbers, or a range said in words or with a dash: never one level (part 3)."""
    folded = _fold(text)
    return (
        len(_NUMBER.findall(folded)) >= 2
        or bool(_DASH_RANGE.search(folded))
        or bool(set(_words(text)) & set(_RANGE_WORDS))
    )


def _unit(folded: str, words: set[str]) -> str | None:
    if "%" in folded or words & _PERCENT_WORDS:
        return "points" if words & {"porcentual", "porcentuales", "percentage"} else "percent"
    if words & _BP_WORDS or {"basicos", "puntos"} <= words or "basis" in words:
        return "bp"
    if words & _POINT_WORDS:
        return "points"
    return None


def parse_value(text: str, region: Region = DEFAULT_REGION) -> Value:
    """The number and unit in a span the reader copied from the question. Raises `Unreadable`
    with the card's ask: `value_range`, `value_currency`, `value_ambiguous` or
    `value_unreadable`. A leading minus or parentheses make the amount negative."""
    if is_range(text):
        raise Unreadable("value_range", text)
    folded = _fold(text)
    word_list = _words(text)
    words = set(word_list)
    if _has_word(text, _CURRENCIES):
        raise Unreadable("value_currency", text)
    if "gordon" in words:
        return Value(None, "method", text, method="gordon")
    for word in word_list:
        if word in _MULTIPLES:
            return Value(Decimal(_MULTIPLES[word]), "multiple", text)

    unit = _unit(folded, words)
    numbers = _NUMBER.findall(folded)
    if numbers:
        amount = _read_number(numbers[0], region, count=unit is None)
    else:
        at = [i for i, w in enumerate(word_list) if w in _NUMBER_WORDS]
        found = [word_list[i] for i in at]
        fraction = [Decimal(_NUMBER_WORDS[w]) < 1 for w in found]
        next_to = len(at) == 2 and at[1] == at[0] + 1  # "un cuarto", not "un punto y medio"
        if next_to and found[0] in _ARTICLES and (fraction[1] or found[1] == "full"):
            found = found[1:]  # "un cuarto", "a quarter", "a full point"
        elif len(at) == 2 and at[1] == at[0] + 1 and found[1] in _ARTICLES and fraction[0]:
            found = found[:1]  # "half a point"
        if len(found) != 1:
            raise Unreadable("value_unreadable", text)  # none, or "un punto y medio"
        amount = Decimal(_NUMBER_WORDS[found[0]])
        if unit is None and amount != 0:  # "a lot", "uno solo": a number word needs a unit
            raise Unreadable("value_unreadable", text)
    if _NEGATIVE.search(text):
        amount = -amount

    if unit is not None:
        return Value(amount, unit, text)
    scale = next((_SCALE_WORDS[w] for w in word_list if w in _SCALE_WORDS), None)
    if "mil" in words and scale == 6:  # "mil millones" is a billion
        scale = 9
    if scale is not None:
        amount = amount.scaleb(scale)
    if "$" in text or words & _DOLLAR_WORDS:
        return Value(amount, "money", text)
    return Value(amount, "plain", text)  # beta, a share count, debt with no currency named


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    """A whole word, or a phrase of whole words, in the text (case and accents aside)."""
    folded = f" {' '.join(_words(text))} "
    return any(f" {w} " in folded for w in words)


def _has_stem(text: str, stems: tuple[str, ...]) -> bool:
    """A word that starts with one of the stems ("inesperad" in "inesperada")."""
    return any(word.startswith(stems) for word in _words(text))


def _value_asks(item, value: Value) -> list[Item]:
    """What a value read cleanly still leaves open, given the input and how it moves."""
    if item.name == "terminal_method":
        return (
            [] if value.method == "gordon" else [Item("method_unknown", {"text": item.value_text})]
        )
    if value.method is not None:  # "Gordon" on any other input
        return [Item("value_unreadable", {"input": item.name, "text": item.value_text})]
    asks = []
    if item.name in RATES and item.how == "add" and value.unit == "percent":
        # "baja 10%": ten points, or a tenth of its level? The reader cannot tell; the student can
        asks.append(Item("percent_or_points", {"input": item.name, "text": item.value_text}))
    if item.name in RATES and value.unit == "points" and abs(value.amount) >= 10:
        # "sube 50 puntos": the Spanish financial press often means basis points
        asks.append(Item("points_or_bp", {"input": item.name, "text": item.value_text}))
    return asks


def card_for(
    reading: Reading,
    question: str,
    last_ended_day: date,
    region: Region = DEFAULT_REGION,
) -> Card:
    """The card for one checked reading. Asks come in the order the student answers them.

    `last_ended_day` is the default *fecha de corte* (`shared_kernel.calendar.last_ended_day`),
    the same day `reading.check` bounds dates by. `region` is the student's, from the address or
    the cookie (`formatting.region_for`). `question` is the student's text as typed; the notes
    that look at it (a surprise, a currency, a target price) match whole words, accents aside.
    """
    asks: list[Item] = []
    notes: list[Item] = []
    values: list[Value | None] = []

    if reading.unsure:
        asks.append(Item("reader_unsure", {"dropped": list(reading.dropped)}))

    if reading.kind == "fuera_de_alcance":
        # answered as brief §4 says, by the screen; no fecha de corte, nothing computed here
        if reading.out_of_scope == "precio_o_consejo":
            target = _has_word(question, _TARGET_PRICE)
            notes.append(
                Item("intrinsic_value_offer_target" if target else "intrinsic_value_offer")
            )
        return Card(reading, (), tuple(asks), tuple(notes))

    if reading.kind in NEEDS_COMPANY and not reading.companies:
        asks.append(Item("company_missing", {"companies": list(tickers())}))

    per_input: list[Item] = []
    for item in reading.inputs:
        value = None
        if item.value_text is None:  # never given, or dropped by the check: the same ask
            if item.via:  # a Fed move with no size: the card asks the move, not the rate
                per_input.append(Item("value_missing_via", {"input": item.name, "via": item.via}))
            else:
                per_input.append(Item("value_missing", {"input": item.name}))
        else:
            try:
                value = parse_value(item.value_text, region)
            except Unreadable as error:
                params = {"input": item.name, "text": item.value_text}
                if error.code == "value_ambiguous":
                    params["first"], params["second"] = error.params["readings"]
                code = "method_unknown" if item.name == "terminal_method" else error.code
                per_input.append(Item(code, params))
            else:
                follow = _value_asks(item, value)
                if any(a.code in ("method_unknown", "value_unreadable") for a in follow):
                    value = None
                per_input.extend(follow)
        values.append(value)
        if item.name in dcf.DRIVERS:
            per_input.append(Item("driver_periods", {"input": item.name}))
        if item.how == "scale" and value is not None and value.unit == "percent":
            if item.name in RATES:  # "un 20%" of a rate: a fifth of its level, not 20 points
                notes.append(Item("relative_change", {"input": item.name, "text": item.value_text}))

    names = {i.name for i in reading.inputs}
    if any(i.via for i in reading.inputs) and not _has_stem(question, _SURPRISE):
        # an expected move is already in the yield and changes nothing (brief §2; Kuttner
        # 2001), so the card asks before the move is pushed through the transmission
        per_input.append(Item("fed_surprise"))
    if "wacc" in names and names & {*WACC_PARTS}:
        # WACC set directly bypasses its parts, so a change to one of them would do nothing
        per_input.append(Item("wacc_and_parts", {"parts": sorted(names & {*WACC_PARTS})}))
    order = {code: i for i, code in enumerate(ASKS)}
    asks.extend(sorted(per_input, key=lambda a: order[a.code]))  # stable within a code

    corte = (
        Item("corte_default", {"date": format_date(last_ended_day, region)})
        if reading.as_of is None
        else Item(
            "corte_from_question",
            {"date": format_date(date.fromisoformat(reading.as_of), region)},
        )
    )
    notes.insert(0, corte)
    if any(i.via for i in reading.inputs):
        notes.append(Item("fed_move_is_event"))
    if "shares" in names and not names & {"debt", "cash_and_investments"}:
        notes.append(Item("cash_unchanged"))
    if "wacc" in names:
        notes.append(Item("wacc_bypasses_parts"))
    if _has_word(question, _CURRENCIES):
        notes.append(Item("usd_only"))
    rank = {code: i for i, code in enumerate(NOTES)}
    notes.sort(key=lambda n: rank[n.code])
    return Card(reading, tuple(values), tuple(asks), tuple(notes))
