"""The question reader's labelled set, its code check and its scorer (F2 Step 3)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

import pytest

from webapp.reader import score as scoring
from webapp.reader.reading import (
    INPUTS,
    KINDS,
    NamedInput,
    Reading,
    check,
    copied_from,
    tickers,
)

TODAY = date(2026, 11, 4)
ROWS = scoring.load_set()


# --- the set itself -------------------------------------------------------------------------


def test_at_least_100_questions_with_unique_ids():
    assert len(ROWS) >= 100
    assert len({r["id"] for r in ROWS}) == len(ROWS)


def test_about_half_in_each_language():
    langs = Counter(r["lang"] for r in ROWS)
    assert set(langs) == {"es", "en"}
    assert 0.4 <= langs["es"] / len(ROWS) <= 0.6


def test_every_kind_and_source_is_represented():
    kinds = Counter(r["expected"]["kind"] for r in ROWS)
    assert set(kinds) == set(KINDS)
    assert all(n >= 10 for n in kinds.values()), kinds
    sources = {r["source"].split("-")[0] for r in ROWS}
    assert {"brief", "variant", "student"} <= sources
    # all fifteen brief questions, in both languages
    for n in range(1, 16):
        assert {r["lang"] for r in ROWS if r["source"] == f"brief-{n}"} == {"es", "en"}


def test_no_duplicate_questions():
    texts = Counter(r["text"].casefold() for r in ROWS)
    assert max(texts.values()) == 1


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_every_label_passes_the_code_check(row):
    """A label the code check would change is a bad label: values and periods are copied
    from the question, names are in the vocabularies, and only cambios change inputs."""
    label = Reading.from_dict(row["expected"])
    checked = check(label, row["text"], TODAY)
    assert checked.dropped == (), checked.dropped
    assert not checked.unsure


def test_labels_cover_the_tricky_edges():
    """The bar means little unless the set holds the cases the brief calls hard."""
    labels = [r["expected"] for r in ROWS]
    assert any(len(lab["companies"]) == 2 for lab in labels)
    assert any(lab["as_of"] for lab in labels)
    assert any(len(lab["inputs"]) == 2 for lab in labels)
    assert any(i["via"] for lab in labels for i in lab["inputs"])
    assert any(i["value_text"] is None for lab in labels for i in lab["inputs"])
    reasons = {lab["out_of_scope"] for lab in labels if lab["kind"] == "fuera_de_alcance"}
    assert reasons == {"precio_o_consejo", "otra_empresa", "concepto"}


# --- the code check -------------------------------------------------------------------------


def test_vocabularies_follow_the_engine():
    assert "equity_market_value" not in INPUTS and "roll_years" not in INPUTS
    assert {"wacc", "terminal_method", "operating_margin", "risk_free"} <= set(INPUTS)
    assert tickers() == ("AAPL", "MSFT", "WMT", "KO", "PG", "JNJ", "CAT", "XOM")


def test_copied_from_ignores_case_accents_and_filler():
    q = "Si el margen operativo de Walmart baja un punto porcentual, ¿cuánto cambia?"
    assert copied_from("un punto porcentual", q)
    assert copied_from("Un Punto Porcentual", q)
    assert not copied_from("1 punto porcentual", q)
    assert copied_from("7,5%", "Si fijo el CPPC en 7,5% directamente")
    assert not copied_from("7.5%", "Si fijo el CPPC en 7,5% directamente")
    assert copied_from("último trimestre", "en su ultimo trimestre")
    assert not copied_from("", q)


def test_a_value_not_in_the_question_is_dropped_and_unsure():
    q = "¿Y si la beta de Apple fuera 1,2?"
    got = check(
        Reading("cambio_de_supuesto", ("AAPL",), inputs=(NamedInput("beta", "set", None, "1.3"),)),
        q,
        TODAY,
    )
    assert got.inputs == (NamedInput("beta", "set", None, None),)
    assert got.unsure and "inputs.value_text" in got.dropped


def test_unknown_names_companies_and_future_dates_are_dropped():
    got = check(
        Reading(
            "estimacion",
            ("AAPL", "TSLA"),
            as_of="2027-01-01",
            inputs=(NamedInput("price"),),
            out_of_scope="concepto",
        ),
        "¿Cuánto vale Apple?",
        TODAY,
    )
    assert got.companies == ("AAPL",)
    assert got.as_of is None and got.inputs == () and got.out_of_scope is None
    assert set(got.dropped) == {"companies", "as_of", "inputs", "out_of_scope"}
    assert got.unsure


def test_a_transmission_must_reach_its_own_input():
    q = "si la Fed sube 25 pb por sorpresa"
    ok = NamedInput("risk_free", "add", "up", "25 pb", "fed_policy_surprise")
    bad = NamedInput("beta", "add", "up", "25 pb", "fed_policy_surprise")
    assert check(Reading("cambio_de_supuesto", inputs=(ok,)), q, TODAY).inputs == (ok,)
    assert check(Reading("cambio_de_supuesto", inputs=(bad,)), q, TODAY).inputs == ()


def test_malformed_model_output_becomes_unsure_not_an_error():
    reading = Reading.from_dict({"kind": 3, "companies": "AAPL", "inputs": [{"name": 1}]})
    assert reading.unsure
    assert set(reading.dropped) == {"kind", "companies", "inputs"}
    assert check(reading, "x", TODAY).kind == ""


def test_round_trip():
    row = next(r for r in ROWS if r["expected"]["inputs"])
    reading = Reading.from_dict(row["expected"])
    assert Reading.from_dict(reading.to_dict()) == reading


# --- the scorer -----------------------------------------------------------------------------


def _answers(rows):
    return {r["id"]: r["expected"] for r in rows}


def test_the_labels_themselves_score_perfectly():
    report = scoring.score(ROWS, _answers(ROWS), TODAY)
    assert report["passes"]
    assert report["overall"]["right"] == 1.0 and report["overall"]["unsure"] == 0.0


def test_no_answers_fails_the_bar_as_all_unsure():
    report = scoring.score(ROWS, {}, TODAY)
    assert not report["passes"]
    assert report["overall"]["unsure"] == 1.0 and report["overall"]["wrong_unflagged"] == 0.0


def test_confidently_wrong_readings_are_counted():
    answers = _answers(ROWS)
    first = ROWS[0]["id"]
    answers[first] = {**answers[first], "kind": "evento", "period": None}
    report = scoring.score(ROWS, answers, TODAY)
    q = next(q for q in report["questions"] if q["id"] == first)
    assert not q["right"] and not q["unsure"]
    assert report["overall"]["wrong_unflagged"] == pytest.approx(1 / len(ROWS))


def test_the_same_mistake_flagged_unsure_is_not_confidently_wrong():
    answers = _answers(ROWS)
    first = ROWS[0]["id"]
    answers[first] = {**answers[first], "kind": "evento", "period": None, "unsure": True}
    report = scoring.score(ROWS, answers, TODAY)
    assert report["overall"]["wrong_unflagged"] == 0.0


def test_value_spans_compare_after_normalising():
    row = next(r for r in ROWS if r["source"] == "brief-8" and r["lang"] == "es")
    answer = json.loads(json.dumps(row["expected"]))
    answer["inputs"][0]["value_text"] = "UN PUNTO porcentual"
    report = scoring.score([row], {row["id"]: answer}, TODAY)
    assert report["questions"][0]["fields"]["inputs"]


def test_the_bar_is_the_one_set_before_any_run():
    assert scoring.BAR == {
        "kind": 0.95,
        "companies": 0.95,
        "date": 0.95,
        "inputs": 0.90,
        "kind_each_language": 0.90,
        "wrong_unflagged_max": 0.02,
        "unsure_max": 0.15,
    }


def test_command_line(tmp_path, capsys):
    path = tmp_path / "answers.jsonl"
    path.write_text(
        "\n".join(json.dumps({"id": r["id"], "reading": r["expected"]}) for r in ROWS),
        encoding="utf-8",
    )
    assert scoring.main(["--answers", str(path), "--today", "2026-11-04"]) == 0
    assert "CLEARS THE BAR" in capsys.readouterr().out
