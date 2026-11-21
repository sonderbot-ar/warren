"""The first screen's answer, brief Q5 (F2 Step 4b, part 1): every figure is the engine's, every
figure opens its source, and the page follows the approved mockup's rules.

The bundle is the engine's own output for the stored run the mockup used, AAPL_2026-10-30_1,
saved by `webapp.answer.load_bundle` (public SEC data and Warren's outputs only), so these tests
run without the database. `test_find_run_*` use a fresh database.
"""

import json
import re
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shared_kernel.database import apply_migrations, get_db_connection
from webapp import formatting
from webapp.answer import NoRun, answer_view, find_run, quarter_closed, quarter_months
from webapp.app import create_app
from webapp.text import translate

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "answer_aapl_2026-10-30.json").read_text("utf-8")
)
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
PAGE = "/respuesta?corte=2026-10-30&empresa=AAPL"
ES = formatting.REGIONS["es-MX"]


def view(region=ES):
    return answer_view(BUNDLE, region, partial(translate, region.language))


@pytest.fixture
def client():
    def loader(ticker, corte):
        if (ticker, corte) != ("AAPL", date(2026, 10, 30)):
            raise NoRun(f"{ticker} {corte}")
        return BUNDLE

    return TestClient(create_app(clock=lambda: NOW, bundle_loader=loader), follow_redirects=False)


# -- labels ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fye, label, first, last",
    [
        ("0925", "FY2026Q4", date(2026, 7, 1), date(2026, 9, 1)),  # Apple: ends in September
        ("0925", "FY2027Q1", date(2026, 10, 1), date(2026, 12, 1)),
        ("1231", "FY2026Q1", date(2026, 1, 1), date(2026, 3, 1)),  # a calendar year
        ("1231", "FY2026Q4", date(2026, 10, 1), date(2026, 12, 1)),
        ("0131", "FY2026Q1", date(2025, 2, 1), date(2025, 4, 1)),  # Walmart: ends in January
        ("0630", "FY2027Q2", date(2026, 10, 1), date(2026, 12, 1)),  # Microsoft: ends in June
        ("0103", "FY2026Q1", date(2026, 1, 1), date(2026, 3, 1)),  # J&J: a 52/53-week year
    ],
)
def test_a_fiscal_quarter_names_its_calendar_months(fye, label, first, last):
    assert quarter_months(label, fye) == (first, last)


def test_a_quarter_that_ended_before_the_corte_is_marked_closed():
    assert quarter_closed("FY2026Q4", "0925", date(2026, 10, 30))
    assert not quarter_closed("FY2027Q1", "0925", date(2026, 10, 30))


# -- the numbers are the engine's --------------------------------------------------------------


def test_each_row_shows_the_engines_forecast_and_pooled_range_rounded_to_millions():
    v = view()
    assert [r.quarter for r in v.rows] == ["T4 2026", "T1 2027", "T2 2027", "T3 2027"]
    for row, q in zip(v.rows, BUNDLE["ranges"]["quarters"], strict=True):
        assert row.forecast.text == formatting.figure(q["revenue_forecast"], "millions", ES)
        assert row.p10.text == formatting.figure(q["band"]["revenue"]["p10"], "millions", ES)
        assert row.p90.text == formatting.figure(q["band"]["revenue"]["p90"], "millions", ES)
    # the approved mockup's figures, from the same run
    assert [r.forecast.text for r in v.rows] == ["104,395", "146,462", "113,277", "111,477"]
    assert (v.rows[0].p10.text, v.rows[0].p90.text) == ("88,100", "122,413")


def test_the_track_record_is_the_engines_share_for_all_companies_and_for_the_company():
    v = view()
    assert v.coverage_all.text == "83.1%" and v.coverage_company.text == "82.0%"
    assert v.coverage_counts["all"] == {"inside": "1,690", "n": "2,033"}
    assert v.coverage_counts["company"] == {"inside": "205", "n": "250"}


def test_the_forecast_source_lists_the_seed_quarter_and_the_three_averaged_years():
    fuente = view().figures["pronostico-FY2026Q4"].fuente
    labels = [item["label"] for item in fuente["items"]]
    assert labels[0] == "Ingresos del T4 2025: 102,466"
    assert labels[1:] == [
        "Año fiscal 2025 frente a 2024: 416,161 y 391,035 → 6.4%",
        "Año fiscal 2024 frente a 2023: 391,035 y 383,285 → 2.0%",
        f"Año fiscal 2023 frente a 2022: 383,285 y 394,328 → {formatting.MINUS}2.8%",
    ]
    # the derived fourth quarter names both filings it comes from, each with its link
    assert [form for form, _ in fuente["items"][0]["links"]] == ["10-K", "10-Q"]
    assert all(url.startswith("https://www.sec.gov/") for i in fuente["items"]
               for _, url in i["links"])  # fmt: skip


def test_the_formula_bar_shows_the_spreadsheet_formula_of_the_open_figure():
    assert view().figures["pronostico-FY2026Q4"].formula == (
        "=102466*(1+0.018823) · B = 102,466 · C = 1.9%"
    )
    # in Argentina's spreadsheet the decimal mark is a comma
    ar = view(formatting.REGIONS["es-AR"]).figures["pronostico-FY2026Q4"].formula
    assert ar.startswith("=102466*(1+0,018823)")


def test_the_spreadsheet_formula_gives_the_figure_on_screen():
    # 102466 × 1.018823 = 104,394.7, shown as 104,395: the student's sheet agrees with the screen
    assert round(102466 * (1 + 0.018823)) == 104395


def test_the_chart_draws_eight_reported_quarters_four_forecasts_and_their_band():
    for size in ("l", "s"):
        chart = view().chart[size]
        assert len(chart["actual"]) == 8 and len(chart["forecast_dots"]) == 4
        assert len(chart["whiskers"]) == 4 and len(chart["band"]) == 9
        # every point sits inside the plot area
        for x, y in chart["actual"] + chart["forecast_dots"] + chart["band"]:
            assert chart["left"] <= x <= chart["right"] and chart["top"] <= y <= chart["bottom"]


def test_argentina_gets_its_own_separators():
    v = view(formatting.REGIONS["es-AR"])
    assert v.rows[0].forecast.text == "104.395" and v.coverage_all.text == "83,1%"


# -- the page ----------------------------------------------------------------------------------


def test_the_answer_page_shows_every_figure_as_a_door_to_its_panel(client):
    response = client.get(PAGE)
    assert response.status_code == 200
    html = response.text
    doors = re.findall(r'<a class="fig[^"]*"[^>]*data-figura="([^"]+)"', html)
    assert set(doors) == set(view().figures)  # each figure the view knows is shown and opens
    assert "Ingresos de Apple: próximos cuatro trimestres" in html
    assert (
        "Ya cerró, pero Apple aún no publica la cifra" in html
    )  # the quarter ended, not yet reported
    assert "<dialog" not in html


def test_a_page_without_a_corte_is_redirected_and_keeps_the_company(client):
    response = client.get("/respuesta?empresa=AAPL")
    assert response.status_code == 307
    assert "empresa=AAPL" in response.headers["location"]


def test_the_panel_opens_on_the_source_with_the_filings_and_the_formula(client):
    html = client.get(PAGE + "&panel=pronostico-FY2026Q4").text
    assert "<dialog" in html and "Pronóstico, T4 2026" in html
    assert "0000320193\u201125\u2011000079" in html and "https://www.sec.gov/Archives/" in html
    assert "=102466*(1+0.018823)" in html
    assert 'class="fig on"' in html  # the open figure is marked in the sheet


@pytest.mark.parametrize("figura", ["p10-FY2027Q1", "p90-FY2026Q4", "cobertura-all",
                                    "cobertura-company"])  # fmt: skip
def test_range_and_track_record_figures_open_their_source_too(client, figura):
    fragment = client.get(
        f"/respuesta/fragmentos/panel?corte=2026-10-30&empresa=AAPL&figura={figura}"
    )
    assert fragment.status_code == 200
    assert fragment.text.lstrip().startswith("<dialog")
    assert "<html" not in fragment.text


def test_other_tabs_keep_their_placeholder_until_their_part(client):
    html = client.get(
        "/respuesta/fragmentos/pestana?corte=2026-10-30&empresa=AAPL"
        "&figura=pronostico-FY2026Q4&pestana=formula"
    ).text
    assert 'data-pestana="formula"' in html


@pytest.mark.parametrize("query, status", [
    ("&panel=otra", 404), ("&panel=pronostico-FY2026Q4&pestana=precio", 404),
])  # fmt: skip
def test_an_unknown_figure_or_tab_is_a_404_page(client, query, status):
    assert client.get(PAGE + query).status_code == status


def test_a_company_warren_does_not_cover_gets_a_plain_page(client):
    response = client.get("/respuesta?corte=2026-10-30&empresa=TSLA")
    assert response.status_code == 404
    assert "Warren no cubre esa empresa" in response.text


def test_a_date_with_no_stored_estimate_says_so(client):
    response = client.get("/respuesta?corte=2026-10-29&empresa=AAPL")
    assert response.status_code == 404
    assert "Warren aún no ha calculado esta estimación" in response.text


def test_the_page_reads_in_english_too(client):
    client.cookies.set("warren_region", "en-US")
    html = client.get(PAGE).text
    assert "Apple revenue: the next four quarters" in html and "Q4 2026" in html


# -- the theme: dark by default (the owner, nov.18.2026) ---------------------------------------


def test_the_page_is_dark_by_default_and_offers_light(client):
    html = client.get(PAGE).text
    assert '<html lang="es" data-theme="dark">' in html
    assert "Modo claro" in html


def test_the_theme_switch_sets_a_cookie_and_goes_back_to_the_same_page(client):
    response = client.get("/tema", params={"modo": "claro", "volver": PAGE})
    assert response.status_code == 303 and response.headers["location"] == PAGE
    assert "warren_theme=light" in response.headers["set-cookie"]
    client.cookies.set("warren_theme", "light")
    assert 'data-theme="light"' in client.get(PAGE).text


@pytest.mark.parametrize("volver", ["https://example.com/", "//example.com/", "/\\example.com"])
def test_the_theme_switch_never_leaves_the_site(client, volver):
    response = client.get("/tema", params={"modo": "claro", "volver": volver})
    assert response.headers["location"] == "/"


# -- which run --------------------------------------------------------------------------------


def _insert_run(conn, run_id, as_of, parent=None, seed=None, source="computed"):
    conn.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, seed, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256, "
        "parent_run_id) VALUES (?, '0000320193', 'AAPL', ?, ?, 'x', 1, 'x', 'x', 'x', 'x', ?)",
        (run_id, as_of, seed, parent),
    )
    conn.execute(
        "INSERT INTO assumptions (run_id, name, period, value, source, method) "
        "VALUES (?, 'revenue_growth', 'FY2026Q4', 0.02, ?, 'm')",
        (run_id, source),
    )


def test_find_run_takes_the_stored_baseline_never_a_what_if_or_an_llm_run(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        _insert_run(conn, "AAPL_2026-10-30_1", "2026-10-30")
        _insert_run(conn, "AAPL_2026-10-30_2", "2026-10-30", parent="AAPL_2026-10-30_1")
        _insert_run(conn, "AAPL_2026-10-30_3", "2026-10-30", source="llm_proposed")
        _insert_run(conn, "AAPL_2026-10-30_4", "2026-10-30", seed=7)
        assert find_run(conn, "aapl", date(2026, 10, 30)) == "AAPL_2026-10-30_1"
        assert find_run(conn, "AAPL", date(2026, 10, 29)) is None


def test_the_engines_answer_is_built_once_per_stored_run(monkeypatch, tmp_path):
    # opening each figure must not repeat the engine's ten-second calls (design critic)
    calls = []
    monkeypatch.setattr("webapp.app.find_run", lambda conn, ticker, corte: "AAPL_2026-10-30_1")
    monkeypatch.setattr(
        "webapp.app.bundle_for_run", lambda conn, run_id: calls.append(run_id) or BUNDLE
    )
    app_client = TestClient(create_app(db_path=tmp_path / "w.db", clock=lambda: NOW))
    app_client.get(PAGE)
    app_client.get(PAGE + "&panel=pronostico-FY2026Q4")
    app_client.get("/respuesta/fragmentos/panel?corte=2026-10-30&empresa=AAPL&figura=p10-FY2027Q1")
    assert calls == ["AAPL_2026-10-30_1"]
