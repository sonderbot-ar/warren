"""No se pudo and the run on demand (F2 Step 4b, part 3b).

The refusal screen turns the engine's coded refusal (`coded.refusal`, backlog #376) into the
brief's title, sentence, button and lesson ("When an estimate can't be built"); the run on demand
builds a baseline only after a student's Calcular. The runner here is a fake, so nothing is
written; the answer is the engine's stored bundle for AAPL_2026-10-30_1.
"""

import dataclasses
import json
import re
import threading
import time
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from domains.analysis.coded import (
    ENGINE_REFUSAL_CODES,
    REFUSAL_GROUP_ORDER,
    REFUSAL_GROUPS,
    ZERO_DIVISOR_ITEMS,
    ZERO_DIVISOR_PERIOD_KINDS,
    ZERO_DIVISOR_RATIOS,
    Coded,
)
from domains.analysis.math_engine import EngineError
from domains.analysis.text import REFUSAL_LESSONS
from domains.market.store import MarketDataError
from webapp import formatting
from webapp.answer import NoRun
from webapp.app import create_app
from webapp.refusal import BUTTON_DATE, BUTTON_MENUS, BUTTON_WHY, GENERIC, refusal_view
from webapp.text import LANGUAGES, catalogue, translate

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "answer_aapl_2026-10-30.json").read_text("utf-8")
)
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)  # the last ended day is nov.03
LATEST = date(2026, 11, 3)
CORTE = date(2018, 1, 15)
MX = formatting.REGIONS["es-MX"]
ES = catalogue("es")
t = partial(translate, "es")

# One params set per code as the engine raises it (math_engine, market.store, runs), with each
# variant a sentence branches on.
SAMPLES: dict[str, list[dict]] = {
    "as_of_too_early": [{"as_of": "2018-01-15", "supported_from": "2019-03-01"}],
    "no_quarterly_revenue": [{"ticker": "AAPL", "as_of": "2018-01-15"}],
    "history_too_short": [
        {"ticker": "AAPL", "needed": 3, "found_years": [2017, 2018]},
        {"ticker": "AAPL", "needed": 3, "found_years": []},
    ],
    "too_few_comparatives": [{"ticker": "AAPL", "needed": 3, "found": 2}],
    "too_few_quarters": [{"ticker": "AAPL", "quarter": 2, "needed": 3, "found": 1, "window": 20}],
    "no_price_on_date": [{"ticker": "AAPL", "as_of": "2018-01-15"}],
    "too_few_return_weeks": [{"ticker": "AAPL", "as_of": "2018-01-15", "found": 80, "needed": 104}],
    "erp_too_few_years": [
        {
            "as_of": "2018-01-15",
            "min_years": 10,
            "first_year": 2010,
            "last_year": 2017,
            "first_as_of": "2020-01-01",
        },  # fmt: skip
        {
            "as_of": "2018-01-15",
            "min_years": 10,
            "first_year": 2010,
            "last_year": 2017,
            "first_as_of": "2027-01-01",
        },  # fmt: skip
    ],
    "as_of_in_future": [{"as_of": "2026-11-04", "today": "2026-11-03"}],
    "market_data_not_refreshed": [
        {
            "as_of": "2026-11-03",
            "symbol": "AAPL",
            "source": "yahoo",
            "covered_through": "2026-10-29",
            "fetched_at": "x",
            "all_covered_through": "2026-10-28",
        },  # fmt: skip
        {
            "as_of": "2026-11-03",
            "symbol": "AAPL",
            "source": "yahoo",
            "covered_through": "2026-10-29",
            "fetched_at": "x",
            "all_covered_through": None,
        },  # fmt: skip
    ],
    "seed_quarter_not_reported": [{"ticker": "AAPL", "fiscal_year": 2017, "quarter": 4}],
    "flow_item_not_reported": [
        {"item": "capex", "fiscal_year": 2017, "quarter": None, "tried": [["capex"]]},
        {"item": "ebit", "fiscal_year": 2017, "quarter": 3, "tried": [["ebit"]]},
    ],
    "no_balance_sheet": [{"ticker": "AAPL", "as_of": "2018-01-15"}],
    "balance_item_not_reported": [
        {"ticker": "AAPL", "item": "current_assets", "period_end": "2017-12-30"},
        {"item": "receivables", "fiscal_year": 2017, "quarter": None},
        {"item": "receivables", "fiscal_year": 2017, "quarter": 2},
    ],
    "no_share_count": [
        {"ticker": "AAPL", "reason": "none_reported", "skipped": []},
        {"ticker": "AAPL", "reason": "none_above_zero", "skipped": []},
    ],
    "no_interest_with_debt": [{"ticker": "AAPL", "fiscal_years": [2015, 2016, 2017]}],
    "zero_divisor": [
        {
            "ticker": "AAPL",
            "ratio": "operating_margin",
            "divisor": "revenue",
            "period": "FY2017Q3",
            "period_kind": "quarter",
            "period_end": "2017-07-01",
            "accession_no": "0000320193-17-000009",
            "inputs": [],
        },  # fmt: skip
        {
            "ticker": "AAPL",
            "ratio": "revenue_seed",
            "divisor": "revenue",
            "period": "FY2017",
            "period_kind": "year",
            "period_end": "2017-09-30",
            "accession_no": None,
            "inputs": ["0000320193-17-000070"],
        },  # fmt: skip
        {
            "ticker": "AAPL",
            "ratio": "revenue_seed",
            "divisor": "revenue",
            "period": "FY2017",
            "period_kind": "quarters_sum",
        },  # fmt: skip
        {
            "ticker": "AAPL",
            "ratio": "capex_pct",
            "divisor": "revenue",
            "period": "FY2015-FY2017",
            "period_kind": "years_sum",
        },  # fmt: skip
        {
            "ticker": "AAPL",
            "ratio": "tax_rate",
            "divisor": "pretax",
            "period": "FY2015-FY2017",
            "period_kind": "years_sum",
        },  # fmt: skip
    ],
    "balance_item_negative": [
        {
            "ticker": "AAPL",
            "item": "cash",
            "period_end": "2017-12-30",
            "value": -1.5e9,
            "currency": "USD",
        },  # fmt: skip
    ],
    "securities_exceed_current_assets": [
        {
            "ticker": "AAPL",
            "period_end": "2017-12-30",
            "with_cash": False,
            "securities": 2e9,
            "current_assets": 1e9,
            "currency": "USD",
        },  # fmt: skip
        {
            "ticker": "AAPL",
            "period_end": "2017-12-30",
            "with_cash": True,
            "securities": 2e9,
            "current_assets": 1e9,
            "currency": "USD",
        },  # fmt: skip
    ],
    "company_not_ingested": [{"ticker": "AAPL"}],
    "no_ingest_run": [{"ticker": "AAPL"}],
    "market_data_not_loaded": [{"source": "yahoo", "symbol": "AAPL"}],
    "no_risk_free_rate": [{"series": "DGS10", "as_of": "2018-01-15"}],
    "market_year_end_missing": [{"what": "^GSPC", "year": 2016}],
    "no_statutory_rate": [{"jurisdiction": "US", "as_of": "2018-01-15"}],
    "no_base_value": [
        {"ticker": "AAPL", "as_of": "2018-01-15", "reason": r}
        for r in ("growth_not_below_rate", "rate_not_positive", "rate_not_above_minus_100")
    ],
}


def view(code, params, corte=CORTE, language="es"):
    region = formatting.REGIONS["es-MX" if language == "es" else "en-US"]
    v = refusal_view(
        Coded(code, params, "English the app never shows"),
        "Apple",
        corte,
        LATEST,
        region,
        partial(translate, language),
    )
    return plain(v)


NBSP = "\u00a0"


def plain(v):
    """The view as read: dates never break across lines on screen (non-breaking spaces), and
    the tests compare the words."""
    fix = lambda s: s.replace(NBSP, " ") if isinstance(s, str) else s  # noqa: E731
    button = v.button and dataclasses.replace(v.button, label=fix(v.button.label))
    return dataclasses.replace(v, title=fix(v.title), sentence=fix(v.sentence), button=button)


# -- the catalogue covers the engine -------------------------------------------------------------


def test_the_samples_cover_every_refusal_code_the_engine_has():
    assert set(SAMPLES) == ENGINE_REFUSAL_CODES


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    "code, params", [(c, p) for c, ps in SAMPLES.items() for p in ps], ids=lambda x: str(x)[:40]
)
def test_every_code_and_variant_has_its_own_sentence_in_both_languages(language, code, params):
    v = view(code, params, language=language)
    assert v.group == REFUSAL_GROUPS[code] and v.code == code  # never the generic fallback
    assert "{" not in v.sentence and "_" not in v.sentence  # no engine name, no placeholder
    assert "English the app never shows" not in v.sentence


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_group_has_its_title_button_and_lesson(language):
    words = catalogue(language)
    for group in REFUSAL_GROUP_ORDER:
        assert f"refusal.group.{group}.title" in words
        assert f"refusal.lesson.{group}" in words
        if group != "setup":  # setup has no button (brief)
            assert f"refusal.group.{group}.button" in words
    for code in REFUSAL_LESSONS:
        assert f"refusal.lesson.{code}" in words
    for value in ZERO_DIVISOR_RATIOS:
        assert f"refusal.ratio.{value}" in words
    for value in ZERO_DIVISOR_ITEMS:
        assert f"refusal.divisor.{value}" in words
    for kind in ZERO_DIVISOR_PERIOD_KINDS - {"years_sum"}:
        assert f"refusal.code.zero_divisor.{kind}" in words
    for item in ZERO_DIVISOR_ITEMS:
        assert f"refusal.code.zero_divisor.years_sum.{item}" in words


# -- what the screen says ------------------------------------------------------------------------


def test_too_early_reads_as_the_mockup_and_offers_the_first_date():
    v = view("as_of_too_early", SAMPLES["as_of_too_early"][0])
    assert v.title == "Para esa fecha, Warren aún no tiene los datos que necesita"
    assert v.sentence.startswith("Warren calcula estimaciones solo desde el 1 mar 2019,")
    assert v.sentence.endswith("la fecha de corte de tu pregunta es el 15 ene 2018.")
    assert v.button.kind == BUTTON_DATE and v.button.corte == date(2019, 3, 1)
    assert v.button.label == "Probar el 1 mar 2019"  # the button names where it goes
    raw = refusal_view(Coded("as_of_too_early", SAMPLES["as_of_too_early"][0], ""), "Apple",
                       CORTE, LATEST, MX, t)  # fmt: skip
    assert "1\u00a0mar\u00a02019" in raw.sentence  # a date never splits across lines
    assert v.lesson.source == ES["refusal.own_rule"]  # a Warren rule, said as such


def test_the_risk_premium_offers_its_first_date_only_once_it_has_ended():
    ready, later = (view("erp_too_few_years", p) for p in SAMPLES["erp_too_few_years"])
    assert ready.button.label == "Probar el 1 ene 2020" and ready.button.corte == date(2020, 1, 1)
    assert later.button is None
    assert "20%" in ready.lesson.why and "error estándar de unos 6 puntos" in ready.lesson.why
    assert "Damodaran" in ready.lesson.source and ES["refusal.own_rule"] in ready.lesson.source


def test_stale_prices_offer_the_one_date_the_sentence_names():
    both, one = (view("market_data_not_refreshed", p) for p in SAMPLES["market_data_not_refreshed"])
    assert "28 oct 2026" in both.sentence and both.button.corte == date(2026, 10, 28)
    assert "29 oct 2026" in one.sentence and one.button.corte == date(2026, 10, 29)
    assert both.button.label == "Usar el 28 oct 2026"


def test_company_data_and_inconsistent_data_reopen_the_card():
    for code in ("seed_quarter_not_reported", "balance_item_negative"):
        v = view(code, SAMPLES[code][0])
        assert v.button.kind == BUTTON_MENUS


def test_a_negative_balance_line_shows_no_amount_until_its_filing_is_linked():
    v = view("balance_item_negative", SAMPLES["balance_item_negative"][0])
    assert "millones" not in v.sentence and "1,500" not in v.sentence  # #509 first
    assert "30 dic 2017" in v.sentence and "tal como Warren la leyó" in v.sentence
    assert "FASB" in v.lesson.source and v.lesson.why.startswith("¿Por qué importa? Cada línea")


def test_a_derived_fourth_quarter_says_how_warren_got_it():
    quarter, derived = (view("zero_divisor", p) for p in SAMPLES["zero_divisor"][:2])
    assert quarter.extra == [] and derived.extra == [ES["refusal.code.zero_divisor.derived"]]
    assert "el margen operativo de Apple" in quarter.sentence
    assert "trimestre que cerró el 1 jul 2017" in quarter.sentence
    years = view("zero_divisor", SAMPLES["zero_divisor"][3])
    assert "años fiscales 2015 a 2017 suman cero" in years.sentence


def test_no_value_opens_the_lesson_and_titles_with_the_date():
    v = view("no_base_value", SAMPLES["no_base_value"][0])
    assert v.title == "Con los supuestos de Warren al 15 ene 2018, el modelo no da un valor"
    assert v.button.kind == BUTTON_WHY and v.button.label == "Ver por qué"
    assert "Gordon y Shapiro" in v.lesson.source


def test_setup_says_it_is_not_the_students_doing_with_no_button_or_lesson():
    v = view("company_not_ingested", {"ticker": "AAPL"})
    assert v.button is None and v.lesson is None
    assert v.setup_note == ES["refusal.group.setup.note"]


@pytest.mark.parametrize(
    "refused",
    [None, Coded("a_code_from_the_future", {}, "x"), Coded("no_share_count", {}, "x")],
    ids=["no code", "unknown code", "params it can't read"],
)
def test_a_refusal_the_app_cannot_word_gets_the_generic_sentence(refused):
    v = refusal_view(refused, "Apple", CORTE, LATEST, MX, t)
    assert v.group == GENERIC and v.sentence == ES["refusal.generic.sentence"]
    assert v.title == ES["refusal.group.generic.title"] and v.button.kind == BUTTON_MENUS


# -- the run on demand ---------------------------------------------------------------------------


class FakeEngine:
    """A stored answer for AAPL on nov.03 once run; a coded refusal for any date before 2019."""

    def __init__(self, delay: float = 0.0):
        self.stored: set[tuple[str, date]] = set()
        self.runs: list[tuple[str, date, date]] = []
        self.delay = delay

    def load(self, ticker, corte):
        if (ticker, corte) not in self.stored:
            raise NoRun(f"{ticker} {corte}")
        return BUNDLE

    def run(self, ticker, corte, today):
        self.runs.append((ticker, corte, today))
        time.sleep(self.delay)
        if corte < date(2019, 3, 1):
            raise EngineError(
                "as-of date too early",
                code="as_of_too_early",
                params={"as_of": corte.isoformat(), "supported_from": "2019-03-01"},
            )
        if ticker == "XOM":
            raise MarketDataError("stale", code="no_price_on_date",
                                  params={"ticker": "XOM", "as_of": corte.isoformat()})  # fmt: skip
        self.stored.add((ticker, corte))
        return f"{ticker}_{corte}_1"


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(engine):
    app = create_app(clock=lambda: NOW, bundle_loader=engine.load, runner=engine.run)
    return TestClient(app, follow_redirects=False)


def post(client, path="/calcular/listo", **fields):
    body = {"corte": LATEST.isoformat(), "empresa": "AAPL", "pregunta": "", **fields}
    return client.post(path, content=urlencode(body),
                       headers={"Content-Type": "application/x-www-form-urlencoded"})  # fmt: skip


def answer(client, corte=LATEST, ticker="AAPL"):
    return client.get(f"/respuesta?{urlencode({'corte': corte.isoformat(), 'empresa': ticker})}")


def test_a_date_before_the_first_supported_one_is_refused_without_a_wait(client, engine):
    page = answer(client, corte=CORTE)
    assert 'data-code="as_of_too_early"' in page.text and engine.runs == []
    assert 'action="/calcular"' in page.text and 'value="2019-03-01"' in page.text


def test_a_page_view_never_runs_the_engine_and_offers_calcular(client, engine):
    page = answer(client)
    assert page.status_code == 404 and engine.runs == []
    assert ES["no_run.title"] in page.text and 'action="/calcular"' in page.text
    assert (
        "Warren puede calcularla ahora con los reportes de Apple publicados hasta el "
        "3\u00a0nov\u00a02026" in page.text
    )


def test_calcular_runs_a_baseline_once_then_the_answer_shows(client, engine):
    done = post(client)
    assert done.status_code == 204 and done.headers["HX-Redirect"].startswith("/respuesta?")
    assert engine.runs == [("AAPL", LATEST, LATEST)]  # today is the last ended day
    assert answer(client).status_code == 200
    post(client)  # stored now: no second run
    assert len(engine.runs) == 1


def test_a_refused_run_lands_on_no_se_pudo_with_its_button(client, engine):
    done = post(client, corte=CORTE.isoformat(), pregunta="¿Cuánto vendía Apple en 2018?")
    page = client.get(done.headers["HX-Redirect"])
    assert page.status_code == 200 and 'role="alert"' in page.text
    assert 'data-code="as_of_too_early"' in page.text
    assert "Warren calcula estimaciones solo desde el 1\u00a0mar\u00a02019" in page.text
    assert 'name="corte" value="2019-03-01"' in page.text  # the button computes on that date
    assert ES["refusal.why"] in page.text and "<details" in page.text
    assert ES["answer.reading.change"] in page.text  # the reading stays, as chips


def test_a_market_data_refusal_is_coded_too(client, engine):
    done = post(client, empresa="XOM")
    page = client.get(done.headers["HX-Redirect"])
    assert 'data-code="no_price_on_date"' in page.text
    assert "Warren no encontró un precio de ExxonMobil el 3\u00a0nov\u00a02026" in page.text


def test_a_new_calcular_asks_the_engine_again(client, engine):
    post(client, corte=CORTE.isoformat())
    post(client, corte=CORTE.isoformat())
    assert len(engine.runs) == 2  # a refusal is not kept against a new Calcular


def test_two_calcular_at_once_store_one_run():
    slow = FakeEngine(delay=0.2)
    app = create_app(clock=lambda: NOW, bundle_loader=slow.load, runner=slow.run)
    c = TestClient(app, follow_redirects=False)
    threads = [threading.Thread(target=post, args=(c,)) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(slow.runs) == 1


def test_menus_button_keeps_the_question_and_opens_the_menus(client, engine):
    def refuse(ticker, corte, today):
        raise EngineError("x", code="seed_quarter_not_reported",
                          params={"ticker": ticker, "fiscal_year": 2025, "quarter": 4})  # fmt: skip

    app = create_app(clock=lambda: NOW, bundle_loader=engine.load, runner=refuse)
    c = TestClient(app, follow_redirects=False)
    done = post(c, pregunta="¿Cuánto venderá Apple?")
    html = c.get(done.headers["HX-Redirect"]).text
    hrefs = [h.replace("&amp;", "&") for h in re.findall(r'href="([^"]+)"', html)]
    menus = next(h for h in hrefs if "menus=1" in h)
    assert menus.startswith("/lectura?") and "pregunta=" in menus
    assert "T4 del año fiscal 2025" in html


def test_without_a_runner_a_test_app_never_touches_the_real_database(engine):
    app = create_app(clock=lambda: NOW, bundle_loader=engine.load)
    c = TestClient(app, follow_redirects=False)
    done = post(c)
    assert done.status_code == 204 and c.get(done.headers["HX-Redirect"]).status_code == 404
