"""The reading card's rules (F2 Step 3b): what it asks and says before anything is computed."""

import json
import string
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from webapp.formatting import REGIONS
from webapp.reader import card as card_module
from webapp.reader.card import ASKS, NOTES, Unreadable, card_for, is_range, parse_value
from webapp.reader.reading import INPUTS, NamedInput, Reading, check
from webapp.text import LANGUAGES, catalogue, translate

READER = Path(__file__).parents[2] / "webapp" / "reader"
TODAY = date(2026, 11, 8)
MX, AR, US = REGIONS["es-MX"], REGIONS["es-AR"], REGIONS["en-US"]


def _row(set_name: str, row_id: str) -> dict:
    for line in (READER / set_name).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] == row_id:
            return row
    raise LookupError(row_id)


def _labelled(row: dict) -> Reading:
    return check(Reading.from_dict(row["expected"]), row["text"], TODAY)


def _codes(items) -> list[str]:
    return [i.code for i in items]


# --- parsing a copied value ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text, amount, unit",
    [
        ("25 puntos básicos", "25", "bp"),
        ("100 puntos basicos", "100", "bp"),
        ("75bps", "75", "bp"),
        ("50pb", "50", "bp"),
        ("un punto porcentual", "1", "points"),
        ("one percentage point", "1", "points"),
        ("medio punto", "0.5", "points"),
        ("half a point", "0.5", "points"),
        ("a full point", "1", "points"),
        ("un cuarto de punto", "0.25", "points"),
        ("1.5 points", "1.5", "points"),
        ("7,5%", "7.5", "percent"),
        ("7.5%", "7.5", "percent"),
        ("un 20%", "20", "percent"),
        ("5 por ciento", "5", "percent"),
        ("1,2", "1.2", "plain"),
        ("zero", "0", "plain"),
        ("doubled", "2", "multiple"),
        ("duplicando", "2", "multiple"),
        ("la mitad", "0.5", "multiple"),
        ("450 millones", "450000000", "plain"),
        ("500 millones de dólares", "500000000", "money"),
        ("$1B", "1000000000", "money"),
        ("1 mil millones de dólares", "1000000000", "money"),
    ],
)
def test_parse_value_reads_amount_and_unit(text, amount, unit):
    value = parse_value(text, MX)
    assert (value.amount, value.unit) == (Decimal(amount), unit)
    assert value.text == text


def test_gordon_is_a_method_with_no_amount():
    value = parse_value("Gordon", MX)
    assert (value.amount, value.unit, value.method) == (None, "method", "gordon")


@pytest.mark.parametrize("region", [MX, AR, US])
def test_one_or_two_digits_after_a_mark_are_decimals_everywhere(region):
    assert parse_value("7,5%", region).amount == Decimal("7.5")
    assert parse_value("7.25%", region).amount == Decimal("7.25")


def test_three_digits_after_the_regions_group_mark_are_thousands():
    assert parse_value("US$5.000 millones", AR).amount == Decimal("5000E6")
    assert parse_value("1,250 million", MX).amount == Decimal("1250E6")


def test_three_digits_after_the_regions_decimal_mark_are_asked():
    with pytest.raises(Unreadable) as mx:
        parse_value("US$5.000 millones", MX)
    assert mx.value.code == "value_ambiguous"
    assert mx.value.params["readings"] == (Decimal("5.000"), Decimal("5000"))
    with pytest.raises(Unreadable) as ar:
        parse_value("1,250", AR)
    assert ar.value.code == "value_ambiguous"


def test_both_marks_follow_the_region_strictly():
    assert parse_value("1.234,5", AR).amount == Decimal("1234.5")
    assert parse_value("1,234.5", MX).amount == Decimal("1234.5")
    with pytest.raises(Unreadable) as error:
        parse_value("1.234,5", MX)
    assert error.value.code == "value_unreadable"


@pytest.mark.parametrize(
    "text",
    ["entre 6% y 9%", "between 6% and 9%", "6%-9%", "6 – 9%", "from 18% to 21%", "6% o 7%"],
)
def test_a_range_is_never_a_level(text):
    assert is_range(text)
    with pytest.raises(Unreadable) as error:
        parse_value(text, MX)
    assert error.value.code == "value_range"


@pytest.mark.parametrize("text", ["mucho", "a lot", ""])
def test_no_number_is_unreadable(text):
    with pytest.raises(Unreadable) as error:
        parse_value(text, MX)
    assert error.value.code == "value_unreadable"


# --- the asks -------------------------------------------------------------------------------


def test_haikus_range_reading_of_f010_asks_for_a_level():
    """Part 3's confident error: "WACC entre 6% y 9%" read as set to the range."""
    row = _row("fresh_set.jsonl", "f010")
    wrong = Reading(
        kind="cambio_de_supuesto",
        companies=("PG",),
        inputs=(NamedInput("wacc", how="set", value_text="6% y 9%"),),
    )
    reading = check(wrong, row["text"], TODAY)
    card = card_for(reading, row["text"], TODAY, MX)
    assert _codes(card.asks) == ["value_range"]
    assert card.values == (None,)
    assert not card.ready


def test_the_labelled_grid_f010_asks_a_value_or_the_grid_for_each_input():
    row = _row("fresh_set.jsonl", "f010")
    card = card_for(_labelled(row), row["text"], TODAY, MX)
    assert _codes(card.asks) == ["value_missing", "value_missing"]
    assert [a.params["input"] for a in card.asks] == ["terminal_growth", "wacc"]
    assert "wacc_bypasses_parts" in _codes(card.notes)


def test_a_share_count_change_alone_says_the_cash_is_unchanged():
    row = _row("labelled_set.jsonl", "q083")
    card = card_for(_labelled(row), row["text"], TODAY, MX)
    assert card.ready
    assert card.values[0].amount == Decimal("450E6")
    assert "cash_unchanged" in _codes(card.notes)


def test_shares_with_debt_do_not_get_the_cash_note():
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("CAT",),
        inputs=(NamedInput("debt", "add", "up", None), NamedInput("shares", "add", "down", None)),
    )
    assert "cash_unchanged" not in _codes(card_for(reading, "x", TODAY).notes)


def test_a_fed_move_with_no_size_asks_the_move_and_says_both_fed_lines():
    question = "¿Qué pasa con el WACC de Apple si la Fed sube tasas?"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("AAPL",),
        inputs=(NamedInput("risk_free", direction="up", via="fed_policy_surprise"),),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert _codes(card.asks) == ["value_missing_via", "fed_surprise"]
    assert _codes(card.notes)[1:] == ["fed_move_is_event"]


def test_a_fed_move_without_surprise_asks_whether_it_was_expected():
    question = "¿Y si la Fed sube 50pb? ¿Cuánto cambia el valor de Coca-Cola?"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("KO",),
        inputs=(NamedInput("risk_free", "add", "up", "50pb", "fed_policy_surprise"),),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert _codes(card.asks) == ["fed_surprise"]
    assert not card.ready


def test_a_surprise_fed_move_is_ready():
    question = "¿Y si la Fed sube 25 pb por sorpresa? ¿Cómo cambia el valor de Apple?"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("AAPL",),
        inputs=(NamedInput("risk_free", "add", "up", "25 pb", "fed_policy_surprise"),),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert card.ready
    assert (card.values[0].amount, card.values[0].unit) == (Decimal(25), "bp")
    assert "fed_move_is_event" in _codes(card.notes)
    assert "fed_surprise" not in _codes(card.asks)


def test_an_exit_multiple_is_a_method_warren_does_not_have():
    question = "What is Caterpillar worth with an exit multiple terminal value?"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("CAT",),
        inputs=(NamedInput("terminal_method", "set", None, "exit multiple"),),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert _codes(card.asks) == ["method_unknown"]


def test_a_driver_change_asks_which_years():
    question = "¿Y si el margen operativo de Walmart baja un punto?"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("WMT",),
        inputs=(NamedInput("operating_margin", "add", "down", "un punto"),),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert _codes(card.asks) == ["driver_periods"]
    assert (card.values[0].amount, card.values[0].unit) == (Decimal(1), "points")


def test_unsure_and_no_company_come_first():
    question = "¿y si fuera 3%?"
    reading = Reading(kind="evento", unsure=True)
    card = card_for(reading, question, TODAY)
    assert _codes(card.asks) == ["reader_unsure", "company_missing"]


def test_asks_follow_the_listed_order():
    question = "y si el WACC de Apple esta entre 6% y 9% y el crecimiento sube"
    reading = Reading(
        kind="cambio_de_supuesto",
        companies=("AAPL",),
        inputs=(
            NamedInput("revenue_growth", direction="up"),
            NamedInput("wacc", "set", None, "entre 6% y 9%"),
        ),
    )
    card = card_for(check(reading, question, TODAY), question, TODAY)
    assert _codes(card.asks) == ["value_range", "value_missing", "driver_periods"]
    positions = [ASKS.index(c) for c in _codes(card.asks)]
    assert positions == sorted(positions)


# --- the notes ------------------------------------------------------------------------------


def test_the_corte_is_the_last_ended_day_unless_the_question_sets_one():
    question = "¿Cuánto valía Apple por acción a fines de 2024?"
    plain = card_for(Reading(kind="estimacion", companies=("AAPL",)), "x", TODAY, MX)
    assert plain.notes[0].code == "corte_default"
    assert plain.notes[0].params == {"date": "8 nov 2026"}
    dated = Reading(
        kind="estimacion", companies=("AAPL",), as_of="2024-12-31", period="a fines de 2024"
    )
    card = card_for(check(dated, question, TODAY), question, TODAY, MX)
    assert card.notes[0].code == "corte_from_question"
    assert card.notes[0].params == {"date": "31 dic 2024"}


@pytest.mark.parametrize(
    "question, expected",
    [
        ("¿Cuánto vale Apple en pesos?", True),
        ("How much is Coca-Cola worth in reais?", True),
        ("valor de Microsoft en MXN", True),
        ("¿Cuál es el crecimiento real de Walmart?", False),
        ("¿Solo el margen de Apple?", False),
    ],
)
def test_a_latin_american_currency_says_warren_reports_dollars(question, expected):
    card = card_for(Reading(kind="estimacion", companies=("AAPL",)), question, TODAY)
    assert ("usd_only" in _codes(card.notes)) is expected


def test_a_price_question_offers_intrinsic_value_and_names_a_target_price():
    reading = Reading(kind="fuera_de_alcance", out_of_scope="precio_o_consejo")
    plain = card_for(reading, "¿Va a subir la acción de Apple?", TODAY)
    assert _codes(plain.notes) == ["intrinsic_value_offer"]
    assert plain.asks == () and plain.values == ()
    assert not plain.ready  # nothing is computed on an out-of-scope card
    target = card_for(reading, "¿Cuál es el precio objetivo de Apple?", TODAY)
    assert _codes(target.notes) == ["intrinsic_value_offer_target"]


def test_other_out_of_scope_readings_have_no_asks_and_no_corte():
    reading = Reading(kind="fuera_de_alcance", out_of_scope="concepto")
    card = card_for(reading, "¿Qué es la deuda neta?", TODAY)
    assert card.asks == () and card.notes == ()


# --- words and the whole set ----------------------------------------------------------------


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


PARAMS = {
    "card.ask.reader_unsure": set(),
    "card.ask.company_missing": {"companies"},
    "card.ask.value_range": {"text", "input"},
    "card.ask.value_missing": {"input"},
    "card.ask.value_missing_via": set(),
    "card.ask.value_ambiguous": {"text", "first", "second"},
    "card.ask.value_currency": {"text"},
    "card.ask.percent_or_points": {"text", "input"},
    "card.ask.points_or_bp": {"text", "input"},
    "card.ask.fed_surprise": set(),
    "card.ask.wacc_and_parts": set(),
    "card.note.relative_change": {"text", "input"},
    "card.ask.value_unreadable": {"text", "input"},
    "card.ask.driver_periods": {"input"},
    "card.ask.method_unknown": set(),
    "card.note.corte_default": {"date"},
    "card.note.corte_from_question": {"date"},
}


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_code_and_input_has_words_in_both_languages(language):
    words = catalogue(language)
    for code in ASKS:
        assert f"card.ask.{code}" in words
    for code in NOTES:
        assert f"card.note.{code}" in words
    for name in INPUTS:
        assert f"input.{name}" in words
    for key, params in PARAMS.items():
        assert _fields(words[key]) <= params, key


def _all_rows():
    for name in ("labelled_set.jsonl", "fresh_set.jsonl"):
        for line in (READER / name).read_text(encoding="utf-8").splitlines():
            yield json.loads(line)


@pytest.mark.parametrize("region", [MX, AR, US])
def test_every_stored_label_makes_a_card_with_words(region):
    rows = list(_all_rows())
    assert len(rows) == 405
    for row in rows:
        reading = _labelled(row)
        card = card_for(reading, row["text"], TODAY, region)
        assert len(card.values) == len(reading.inputs)
        assert card.ready == (not card.asks and reading.kind != "fuera_de_alcance")
        for item, value in zip(reading.inputs, card.values, strict=True):
            if item.value_text is None:
                assert value is None
            elif is_range(item.value_text):
                assert value is None
            else:  # a value is read, or the card asks about it
                asked = {a.params.get("input") for a in card.asks}
                assert value is not None or item.name in asked or item.name == "terminal_method"
        for entry in (*card.asks, *card.notes):
            kind = "ask" if entry in card.asks else "note"
            params = dict(entry.params)
            if "companies" in params:
                params["companies"] = ", ".join(params["companies"])
            if "input" in params:
                params["input"] = translate(region.language, f"input.{params['input']}")
            translate(region.language, f"card.{kind}.{entry.code}", **params)


def test_every_labelled_value_reads_in_the_owners_default_region_bar_one():
    """In Mexico only "US$5.000 millones" is asked, since Mexico's decimal mark is the point."""
    asked = []
    for row in _all_rows():
        for item in _labelled(row).inputs:
            if item.value_text is None:
                continue
            try:
                parse_value(item.value_text, MX)
            except Unreadable as error:
                asked.append((item.value_text, error.code))
    assert asked == [("US$5.000 millones", "value_ambiguous")]


def test_the_card_module_holds_no_student_words():
    source = Path(card_module.__file__).read_text(encoding="utf-8")
    for language in LANGUAGES:
        for key, text in catalogue(language).items():
            if key.startswith("card."):
                assert text not in source


# --- the review's cases (nov.09.2026) ------------------------------------------------------


@pytest.mark.parametrize("text", ["un punto y medio", "one and a half points", "tres cuartos"])
def test_two_number_words_are_asked_never_half_read(text):
    with pytest.raises(Unreadable) as error:
        parse_value(text, MX)
    assert error.value.code == "value_unreadable"


@pytest.mark.parametrize("region, text", [(MX, "4,125%"), (AR, "4.125%"), (MX, "4.125%")])
def test_three_decimals_on_a_rate_are_asked_in_every_region(region, text):
    with pytest.raises(Unreadable) as error:
        parse_value(text, region)
    assert error.value.code == "value_ambiguous"


@pytest.mark.parametrize("text", ["-2%", "−0,2", "(2%)"])
def test_a_minus_or_parentheses_make_the_amount_negative(text):
    assert parse_value(text, AR).amount < 0


def test_a_value_in_another_currency_is_asked_in_dollars():
    with pytest.raises(Unreadable) as error:
        parse_value("500 millones de pesos", MX)
    assert error.value.code == "value_currency"


def _cambio(question, *inputs, company="WMT"):
    reading = Reading(kind="cambio_de_supuesto", companies=(company,), inputs=inputs)
    return card_for(check(reading, question, TODAY), question, TODAY, MX)


def test_a_percent_move_on_a_rate_asks_points_or_share_of_level():
    card = _cambio(
        "¿y si el margen operativo baja 10%?", NamedInput("operating_margin", "add", "down", "10%")
    )
    assert _codes(card.asks) == ["percent_or_points", "driver_periods"]


def test_a_proportional_percent_on_a_rate_says_it_is_relative():
    card = _cambio("¿y si el capex sube un 20%?", NamedInput("capex_pct", "scale", "up", "un 20%"))
    assert "relative_change" in _codes(card.notes)
    assert _codes(card.asks) == ["driver_periods"]


def test_fifty_points_on_a_rate_asks_points_or_basis_points():
    card = _cambio(
        "¿y si la tasa libre de riesgo sube 50 puntos?",
        NamedInput("risk_free", "add", "up", "50 puntos"),
    )
    assert _codes(card.asks) == ["points_or_bp"]
    small = _cambio(
        "¿y si el margen operativo sube 2 puntos?",
        NamedInput("operating_margin", "add", "up", "2 puntos"),
    )
    assert "points_or_bp" not in _codes(small.asks)


def test_wacc_set_with_one_of_its_parts_asks_which_wins():
    card = _cambio(
        "¿y si el WACC es 8% y la beta 1,2?",
        NamedInput("wacc", "set", None, "8%"),
        NamedInput("beta", "set", None, "1,2"),
    )
    assert _codes(card.asks) == ["wacc_and_parts"]
    assert card.asks[0].params == {"parts": ["beta"]}


def test_the_cash_note_fires_on_an_issuance_too():
    card = _cambio("¿y si emiten 10% más acciones?", NamedInput("shares", "scale", "up", "10%"))
    assert "cash_unchanged" in _codes(card.notes)
    for language in LANGUAGES:  # the words hold for a buyback and an issuance alike
        text = translate(language, "card.note.cash_unchanged")
        assert "sube" not in text and "rises" not in text


def test_any_terminal_method_but_gordon_is_unknown():
    for text, question in [
        (
            "múltiplo de salida",
            "¿Y con un múltiplo de salida para el valor terminal de Caterpillar?",
        ),
        ("10x", "¿Y si el valor terminal de Caterpillar es 10x EBITDA?"),
    ]:
        card = _cambio(question, NamedInput("terminal_method", "set", None, text), company="CAT")
        assert _codes(card.asks) == ["method_unknown"]
        assert card.values == (None,)


def test_the_company_ask_names_the_eight():
    card = card_for(Reading(kind="estimacion"), "¿cuánto vale?", TODAY)
    assert card.asks[0].code == "company_missing"
    assert len(card.asks[0].params["companies"]) == 8


def test_haikus_seven_confident_errors_on_the_fresh_exam():
    """What the card does with each of part 3's seven confidently wrong readings: the three
    ranges are asked; f133 asks for a company; f118 gets the event answer; f169 and f199 (read
    as another company, labelled as a price question) are out of scope either way. None of the
    seven reaches Calcular with a number the student did not confirm."""
    from webapp.reader import score as scoring

    run = READER / "runs" / "2026-11-07-claude-haiku-5-5-prompt3-fresh.jsonl"
    lines = run.read_text(encoding="utf-8").splitlines()[1:]
    answers = {json.loads(x)["id"]: json.loads(x)["reading"] for x in lines}
    rows = [json.loads(x) for x in (READER / "fresh_set.jsonl").read_text("utf-8").splitlines()]
    day = date(2026, 11, 6)
    report = scoring.score(rows, answers, day)
    texts = {r["id"]: r["text"] for r in rows}
    seen = {}
    for q in report["questions"]:
        if q["right"] or q["unsure"]:
            continue
        card = card_for(Reading.from_dict(q["reading"]), texts[q["id"]], day, MX)
        seen[q["id"]] = (card.reading.kind, _codes(card.asks), card.ready)
    assert seen == {
        "f010": ("cambio_de_supuesto", ["value_range", "value_range"], False),
        "f118": ("evento", [], True),
        "f133": ("evento", ["company_missing"], False),
        "f135": ("cambio_de_supuesto", ["value_range", "value_range"], False),
        "f169": ("fuera_de_alcance", [], False),
        "f177": (
            "cambio_de_supuesto",
            ["value_range", "value_range", "driver_periods", "driver_periods"],
            False,
        ),
        "f199": ("fuera_de_alcance", [], False),
    }
    for row_id in ("f010", "f135", "f177"):
        assert all(
            v is None
            for v in card_for(Reading.from_dict(answers[row_id]), texts[row_id], day, MX).values
        )


# --- the gatekeeper's cases (nov.09.2026) --------------------------------------------------


@pytest.mark.parametrize(
    "text, amount",
    [("US$ 500 mil", "500E3"), ("500 mil dólares", "500E3"), ("US$ 2 millardos", "2E9")],
)
def test_mil_alone_is_thousands_and_millardos_billions(text, amount):
    value = parse_value(text, AR)
    assert (value.amount, value.unit) == (Decimal(amount), "money")


def test_billones_is_asked_never_left_unscaled():
    with pytest.raises(Unreadable) as error:
        parse_value("US$ 2 billones", MX)
    assert error.value.code == "value_ambiguous"
    assert error.value.params["readings"] == (Decimal("2E9"), Decimal("2E12"))


@pytest.mark.parametrize("text", ["–1%", "—1%", "– 1%"])
def test_an_en_or_em_dash_is_a_minus(text):
    assert parse_value(text, MX).amount == Decimal(-1)


def test_three_decimals_on_beta_are_asked():
    card = _cambio(
        "¿y si la beta de Apple es 1,250?", NamedInput("beta", "set", None, "1,250"), company="AAPL"
    )
    assert _codes(card.asks) == ["value_ambiguous"]
