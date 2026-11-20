"""The question in front of the answer (F2 Step 4b, part 3a): Inicio, the reading card with its
asks and menus, and Calculando. The reader is a fixed one (`question.fixed_reader`), so no
question leaves the machine; the answer is the engine's stored bundle for AAPL_2026-10-30_1.
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from webapp import formatting
from webapp.answer import NoRun
from webapp.app import COMPANIES, create_app
from webapp.question import (
    MAX_QUESTION,
    STEP_ASK,
    STEP_CALCULATE,
    STEP_LATER,
    STEP_OUT,
    Choices,
    Reader,
    apply_choices,
    clean_question,
    fixed_reader,
    question_card,
)
from webapp.reader.reading import NamedInput, Reading
from webapp.text import catalogue

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "answer_aapl_2026-10-30.json").read_text("utf-8")
)
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)  # the last ended day is nov.03
LATEST = date(2026, 11, 3)
MX = formatting.REGIONS["es-MX"]
ES = catalogue("es")

Q5 = ES["inicio.example.estimacion"]
NO_COMPANY = (
    "¿Cuánto venderá en los próximos cuatro trimestres, y qué tan seguro es ese pronóstico?"
)
TWO = "¿Cuánto venderán Apple y Microsoft el próximo año?"
DATED = "Con lo que se sabía a fines de octubre de 2026, ¿cuánto venderá Apple?"
CAMBIO = ES["inicio.example.cambio_de_supuesto"]
PRICE = "¿Va a subir la acción de Apple?"
READINGS = {
    Q5: Reading(kind="estimacion", companies=("AAPL",), period="próximos cuatro trimestres"),
    NO_COMPANY: Reading(kind="estimacion", period="próximos cuatro trimestres"),
    TWO: Reading(kind="estimacion", companies=("AAPL", "MSFT"), period="el próximo año"),
    DATED: Reading(
        kind="estimacion",
        companies=("AAPL",),
        as_of="2026-10-30",
        period="a fines de octubre de 2026",
    ),
    CAMBIO: Reading(
        kind="cambio_de_supuesto",
        companies=("WMT",),
        inputs=(
            NamedInput(
                "operating_margin", how="add", direction="down", value_text="un punto porcentual"
            ),
        ),
    ),
    PRICE: Reading(kind="fuera_de_alcance", out_of_scope="precio_o_consejo"),
}


def loader(ticker, corte):
    if (ticker, corte) != ("AAPL", date(2026, 10, 30)):
        raise NoRun(f"{ticker} {corte}")
    return BUNDLE


@pytest.fixture
def client():
    app = create_app(clock=lambda: NOW, bundle_loader=loader, reader=fixed_reader(READINGS))
    return TestClient(app, follow_redirects=False)


def lectura(client, text, **params):
    query = urlencode({"corte": LATEST.isoformat(), "pregunta": text, **params})
    return client.get(f"/lectura?{query}")


def links(html: str) -> list[str]:
    return [h.replace("&amp;", "&") for h in re.findall(r'href="([^"]+)"', html)]


def card(text, **choices):
    reading = fixed_reader(READINGS)(text, LATEST)
    return question_card(text, reading, Choices(**choices), LATEST, MX)


# -- Inicio --------------------------------------------------------------------------------------


def test_inicio_puts_the_question_box_first_and_names_the_corte(client):
    html = client.get(f"/?corte={LATEST}").text
    assert html.index('name="pregunta"') < html.index(ES["inicio.examples"])
    assert 'action="/lectura"' in html and f'value="{LATEST}"' in html
    assert "Fecha de corte: 3 nov 2026" in html and "(hoy es 4 nov 2026)" in html


def test_every_example_and_company_opens_its_reading_card(client):
    html = client.get(f"/?corte={LATEST}").text
    readings = [u for u in links(html) if u.startswith("/lectura?")]
    assert len(readings) == 3 + len(COMPANIES)
    questions = [parse_qs(urlsplit(u).query)["pregunta"][0] for u in readings]
    assert Q5 in questions and CAMBIO in questions
    assert ES["inicio.company_question"].format(company="Caterpillar") in questions


# -- the reading card ----------------------------------------------------------------------------


def test_an_empty_question_goes_back_to_inicio(client):
    response = lectura(client, "   ")
    assert response.status_code == 303 and response.headers["location"].startswith("/?corte=")


def test_a_clear_estimate_shows_what_was_read_and_offers_calcular(client):
    html = lectura(client, Q5).text
    assert ES["reading.title"] in html and f"«{Q5}»" in html
    assert "Estimación" in html and "Apple" in html
    assert ES["reading.shows.estimacion"] in html
    assert 'action="/calcular" method="post"' in html
    assert 'name="empresa" value="AAPL"' in html and 'name="corte" value="2026-11-03"' in html
    assert 'id="menus"' not in html  # the menus are one click away, not open
    assert ES["reading.ai_note"] in html


def test_no_company_asks_with_the_eight_and_offers_no_calcular(client):
    html = lectura(client, NO_COMPANY).text
    assert ES["reading.no_company"] in html
    assert "¿De qué empresa hablas?" in html
    assert "/calcular" not in html
    picks = [u for u in links(html) if "empresa=" in u]
    assert {parse_qs(urlsplit(u).query)["empresa"][0] for u in picks} == set(COMPANIES)
    chosen = client.get(next(u for u in picks if "empresa=KO" in u)).text
    assert 'name="empresa" value="KO"' in chosen and 'action="/calcular"' in chosen


def test_two_companies_ask_which_one_first():
    qc = card(TWO)
    assert qc.step == STEP_ASK and [a.code for a in qc.asks] == ["one_company"]
    assert card(TWO, empresa="MSFT").step == STEP_CALCULATE


def test_a_date_in_the_question_is_the_corte_and_said_so():
    qc = card(DATED)
    assert qc.corte == date(2026, 10, 30)
    assert qc.card.notes[0].code == "corte_from_question"


def test_a_date_from_the_menus_is_the_corte_and_said_to_be_the_students():
    qc = card(Q5, fecha=date(2025, 6, 2))
    assert qc.corte == date(2025, 6, 2)
    assert qc.card.notes[0].code == "corte_chosen"
    assert qc.card.notes[0].params == {"date": "2 jun 2025"}


def test_a_change_question_is_read_and_confirmed_but_its_screen_comes_later(client):
    assert card(CAMBIO, empresa="WMT").step in (STEP_ASK, STEP_LATER)
    html = lectura(client, CAMBIO).text
    assert "Cambio de supuesto" in html and "el margen operativo" in html
    assert "«un punto porcentual»" in html
    assert "/calcular" not in html


def test_a_change_question_with_its_asks_answered_says_the_screen_is_not_ready(client):
    reading = Reading(kind="dato", companies=("AAPL",))
    qc = question_card("x", reading, Choices(), LATEST, MX)
    assert qc.step == STEP_LATER
    html = lectura(client, Q5, tipo="dato", corregido="1").text
    assert ES["reading.later.title"] in html and "/calcular" not in html
    assert ES["reading.later.try"].format(company="Apple") in html


def test_a_price_question_is_out_of_scope_with_no_calcular(client):
    assert card(PRICE).step == STEP_OUT
    html = lectura(client, PRICE).text
    assert ES["question.out.precio_o_consejo"] in html
    assert "valor intrínseco" in html
    assert "/calcular" not in html


def test_an_unread_question_opens_the_menus_by_itself(client):
    html = lectura(client, "una pregunta que el lector no conoce").text
    assert 'id="menus"' in html
    assert "No estoy seguro de haber entendido tu pregunta" in html
    assert "/calcular" not in html


def test_the_menus_make_the_reading_the_students(client):
    html = lectura(
        client, "una pregunta que el lector no conoce", tipo="estimacion", empresa="JNJ",
        fecha="2026-10-30", corregido="1",
    ).text  # fmt: skip
    assert "No estoy seguro" not in html
    assert 'name="empresa" value="JNJ"' in html and 'name="corte" value="2026-10-30"' in html
    assert "la que elegiste" in html


def test_choices_from_a_stale_or_edited_link_are_ignored_not_an_error():
    choices = Choices.from_query(
        {"empresa": "AMZN", "tipo": "precio", "fecha": "2030-01-01", "corregido": "si"}, LATEST
    )
    assert choices == Choices()
    assert Choices.from_query({"fecha": "no-es-fecha"}, LATEST).fecha is None


def test_a_picked_kind_drops_inputs_unless_it_is_a_change():
    reading = Reading(kind="cambio_de_supuesto", inputs=(NamedInput("beta"),), unsure=True)
    assert apply_choices(reading, Choices(tipo="estimacion")).inputs == ()
    kept = apply_choices(reading, Choices(tipo="cambio_de_supuesto", corregido=True))
    assert kept.inputs and not kept.unsure


def test_a_long_question_is_cut_before_the_reader_sees_it():
    assert len(clean_question("a " * 1000)) == MAX_QUESTION
    assert clean_question("  dos   espacios \n ") == "dos espacios"


# -- the reader behind the card ------------------------------------------------------------------


class CountingBackend:
    name = "test"

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def complete(self, system, user, schema):
        self.calls += 1
        return self.answer


def test_the_same_question_on_the_same_day_is_read_once():
    backend = CountingBackend(json.dumps({"kind": "estimacion", "companies": ["AAPL"]}))
    reader = Reader(lambda: backend)
    first = reader.read(Q5, LATEST)
    assert reader.read(Q5, LATEST) == first and backend.calls == 1
    reader.read(Q5, date(2026, 11, 4))
    assert backend.calls == 2


def test_no_key_means_the_menus_never_a_crash():
    def broken():
        raise RuntimeError("no key")

    reading = Reader(broken).read(Q5, LATEST)
    assert reading.unsure and "reader" in reading.dropped


def test_an_unavailable_reader_is_tried_again_next_time():
    backend = CountingBackend("not json")
    reader = Reader(lambda: backend)
    reader.read(Q5, LATEST)
    reader.read(Q5, LATEST)
    assert backend.calls == 2


# -- Calcular and Calculando ---------------------------------------------------------------------


def calcular(client, path="/calcular", **fields):
    body = {"corte": "2026-10-30", "empresa": "AAPL", "pregunta": Q5, **fields}
    return client.post(
        path, content=urlencode(body),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )  # fmt: skip


def test_calcular_shows_the_reading_while_the_engine_works(client):
    html = calcular(client).text
    assert 'aria-busy="true"' in html and 'role="status"' in html
    assert "Calculando con los reportes de Apple presentados hasta el 30 oct 2026" in html
    assert 'hx-post="/calcular/listo"' in html and 'hx-trigger="load"' in html
    assert ES["answer.reading.change"] in html  # the reading, collapsed to its chips
    answer = next(u for u in links(html) if u.startswith("/respuesta?"))
    assert parse_qs(urlsplit(answer).query)["pregunta"] == [Q5]  # works without JavaScript


def test_listo_works_the_answer_out_then_calcular_opens_it_at_once(client):
    done = calcular(client, "/calcular/listo")
    assert done.status_code == 204
    assert done.headers["HX-Redirect"].startswith("/respuesta?corte=2026-10-30&empresa=AAPL")
    again = calcular(client)
    assert again.status_code == 303 and again.headers["location"].startswith("/respuesta?")


def test_a_date_with_no_estimate_still_lands_on_the_answers_address(client):
    done = calcular(client, "/calcular/listo", corte="2026-10-29")
    assert done.status_code == 204
    assert client.get(done.headers["HX-Redirect"]).status_code == 404  # says so, plainly


@pytest.mark.parametrize(
    "fields, status", [({"empresa": "AMZN"}, 404), ({"corte": "2030-01-01"}, 400)]
)
def test_calcular_checks_what_the_form_sent(client, fields, status):
    assert calcular(client, **fields).status_code == status


def test_the_answer_keeps_the_question_in_the_header_and_every_link(client):
    query = urlencode({"corte": "2026-10-30", "empresa": "AAPL", "pregunta": Q5})
    html = client.get(f"/respuesta?{query}").text
    assert 'class="header-ask"' in html and f'value="{Q5}"' in html
    change = next(u for u in links(html) if u.startswith("/lectura?"))
    assert parse_qs(urlsplit(change).query)["pregunta"] == [Q5]
    figures = [u for u in links(html) if "panel=" in u]
    assert figures and all("pregunta=" in u for u in figures)


def test_the_answer_without_a_question_has_no_header_box(client):
    html = client.get("/respuesta?corte=2026-10-30&empresa=AAPL").text
    assert 'class="header-ask"' not in html and ES["answer.reading.change"] not in html
