"""The cells behind the answer (F2 Step 4b part 2; `docs/designs/f2-input-charts.md`): one card
per cell the answer reaches, the engine's values only, the years switch changes only the history,
and every value opens its panel.

Runs on the engine's own bundle for AAPL_2026-10-30_1 (`fixtures/`), fetched at ten years.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from functools import partial

import pytest

from tests.webapp.test_answer import BUNDLE, ES, PAGE, client  # noqa: F401 (fixture)
from webapp import cells, formatting
from webapp.answer import answer_view
from webapp.text import translate


def view(years=cells.DEFAULT_YEARS, region=ES):
    return answer_view(BUNDLE, region, partial(translate, region.language), years)


def card(v, kind):
    return next(c for c in v.cells["cards"] if c["kind"] == kind)


def engine_cell(name):
    return next(c for c in BUNDLE["inputs"]["cells"] if c["name"] == name)


def pct(value):
    return Decimal(str(value * 100)).quantize(Decimal("0.1"), ROUND_HALF_UP)


# -- which cards -------------------------------------------------------------------------------


def test_every_cell_the_answer_reaches_has_one_card_and_no_other():
    reached = [c["name"] for c in BUNDLE["inputs"]["cells"]]
    assert reached == ["revenue_seed", "revenue_growth"]  # brief Q5: forecast = B × (1 + C)
    cards = view().cells["cards"]
    assert [c["kind"] for c in cards] == ["seed", "ratio"]
    assert [c["letter"] for c in cards] == ["B", "C"]


def test_a_cell_with_no_designed_card_still_gets_a_plain_one():
    bundle = {**BUNDLE, "inputs": {**BUNDLE["inputs"]}}
    extra = {"name": "operating_margin", "rows": [{"period": "FY2027Q1", "value": 0.3}],
             "history": [], "gap": None, "notes": []}  # fmt: skip
    bundle["inputs"]["cells"] = BUNDLE["inputs"]["cells"] + [extra]
    v = answer_view(bundle, ES, partial(translate, "es"))
    assert [c["kind"] for c in v.cells["cards"]] == ["seed", "ratio", "plain"]


# -- the years switch --------------------------------------------------------------------------


@pytest.mark.parametrize("years", cells.YEARS_OPTIONS)
def test_the_years_switch_changes_only_the_history(years):
    v, default = view(years), view()
    seed, ratio = card(v, "seed"), card(v, "ratio")
    assert all(len(m["table"]) == years for m in seed["minis"])
    annual = next(s for s in engine_cell("revenue_growth")["history"] if s["primary"])
    shown = len([p for p in annual["points"] if p["value"] is not None][-years:])
    assert shown == min(years, 9)  # growth needs the year before: nine growth years of ten
    assert len(ratio["annual"]["l"]["bars"]) == shown + 1  # the years, then the assumption
    assert len(ratio["quarter_rows"]) == 4 * years
    assert len(ratio["quarterly"]["l"]["bars"]) == 4 * years
    # the answer itself and the assumption do not move
    assert v.rows == default.rows
    assert v.figures[ratio["assumption_id"]].text == "1.9%"
    assert [m["forecast_id"] for m in seed["minis"]] == [
        f"pronostico-{p}" for p in ("FY2026Q4", "FY2027Q1", "FY2027Q2", "FY2027Q3")
    ]


def test_the_shown_history_is_the_last_years_of_the_engines_series():
    seed = engine_cell("revenue_seed")
    by_quarter = {s["fiscal_quarter"]: s["points"] for s in seed["history"]}
    for m in card(view(3), "seed")["minis"]:
        q = int(m["label"].removeprefix("T"))
        expected = [f"ingresos-{p['period']}" for p in by_quarter[q][-3:]]
        assert [c["id"] for c in m["table"]] == expected


@pytest.mark.parametrize("raw, years", [("3", 3), ("10", 10), ("7", 5), ("", 5), ("x", 5)])
def test_an_unknown_years_value_falls_back_to_five(raw, years):
    assert cells.years_from(raw) == years


# -- every value is the engine's ---------------------------------------------------------------


def test_each_base_and_history_value_is_the_engines_reported_revenue():
    v = view()
    seed = engine_cell("revenue_seed")
    values = {p["period"]: p["value"] for s in seed["history"] for p in s["points"]}
    for m in card(v, "seed")["minis"]:
        for c in m["table"]:
            period = c["id"].removeprefix("ingresos-")
            assert v.figures[c["id"]].text == formatting.figure(values[period], "millions", ES)
    # the four bases are the run's seed rows
    bases = [v.figures[m["base_id"]].text for m in card(v, "seed")["minis"]]
    assert bases == ["102,466", "143,756", "111,184", "109,417"]


def test_each_growth_figure_is_the_engines_and_its_formula_gives_it():
    v = view(10)
    growth = engine_cell("revenue_growth")
    points = {p["period"]: p for s in growth["history"] for p in s["points"]}
    ratio = card(v, "ratio")
    for row in ratio["annual_rows"] + ratio["quarter_rows"]:
        fig = v.figures[row["growth"]]
        point = points[row["growth"].removeprefix("crecimiento-")]
        assert fig.text == formatting.figure(point["value"], "percent", ES) + "%"
        now, before = re.fullmatch(r"=(\d+)/(\d+)-1", fig.formula).groups()
        assert pct(int(now) / int(before) - 1) == pct(point["value"])


def test_the_averaged_years_are_the_ones_the_engine_used():
    ratio = card(view(), "ratio")
    used = [r["label"] for r in ratio["annual_rows"] if r["used"]]
    assert used == ["Año fiscal 2023", "Año fiscal 2024", "Año fiscal 2025"]
    assert engine_cell("revenue_growth")["rows"][0]["used"] == ["FY2023", "FY2024", "FY2025"]
    bars = ratio["annual"]["l"]["bars"]
    assert [b["kind"] for b in bars] == ["old", "old", "used", "used", "used", "sup"]
    assert ratio["annual"]["l"]["bracket"]["label"] == "promedio → 1.9%"


def test_the_assumptions_formula_is_the_average_a_student_would_type():
    v = view()
    fig = v.figures["supuesto-revenue_growth"]
    args = re.fullmatch(r"=PROMEDIO\((.*)\)", fig.formula).group(1).split(",")
    mean = sum(float(a) for a in args) / len(args)
    assert pct(mean) == pct(engine_cell("revenue_growth")["rows"][0]["value"])


def test_argentina_types_the_average_with_semicolons():
    region = formatting.REGIONS["es-AR"]
    fig = view(region=region).figures["supuesto-revenue_growth"]
    assert fig.formula.startswith("=PROMEDIO(") and ";" in fig.formula and "0,0" in fig.formula


def test_the_note_names_the_latest_quarters_and_when_the_next_year_enters():
    ratio = card(view(), "ratio")
    assert ratio["note"] == (
        "Los tres trimestres más recientes crecieron 15.7%, 16.6% y 16.4%; el supuesto es 1.9%."
    )
    assert ratio["note_next"] == (
        "El año fiscal 2026 entrará en el promedio cuando Apple presente su reporte anual."
    )


def test_a_derived_fourth_quarter_is_marked():
    seed = card(view(), "seed")
    t4 = next(m for m in seed["minis"] if m["label"] == "T4")
    assert all(c["derived"] for c in t4["table"])
    assert seed["any_derived"]


def test_the_axes_are_whole_percents_with_a_true_minus():
    labels = [t["label"] for t in card(view(), "ratio")["quarterly"]["l"]["ticks"]]
    assert labels[0] == "−10%" and "0%" in labels


# -- the page ----------------------------------------------------------------------------------


def test_the_page_shows_the_cells_and_the_switch(client):  # noqa: F811
    html = client.get(PAGE).text
    assert 'id="celdas"' in html
    assert html.count('class="yrs-opt"') == 3
    assert re.search(r'class="yrs-opt"[^>]*aria-current="true"[^>]*>5</a>', html, re.S)
    assert "Próximamente:" in html


def test_the_switch_reloads_without_javascript_and_swaps_with_it(client):  # noqa: F811
    html = client.get(PAGE).text
    assert 'href="/respuesta?corte=2026-10-30&amp;empresa=AAPL&amp;anos=10"' in html
    assert (
        'hx-get="/respuesta/fragmentos/celdas?corte=2026-10-30&amp;empresa=AAPL&amp;anos=10"'
        in html
    )
    fragment = client.get("/respuesta/fragmentos/celdas?corte=2026-10-30&empresa=AAPL&anos=10")
    assert fragment.status_code == 200
    assert fragment.text.lstrip().startswith('<section class="cells"')
    assert "<html" not in fragment.text


def test_a_figure_opened_with_ten_years_keeps_ten_years(client):  # noqa: F811
    html = client.get(PAGE + "&anos=10").text
    assert "anos=10&amp;panel=crecimiento-FY2017" in html
    opened = client.get(PAGE + "&anos=10&panel=crecimiento-FY2017")
    assert opened.status_code == 200
    assert "anos=10" in re.search(r'data-close-url="([^"]*)"', opened.text).group(1)


def test_every_value_in_the_cells_opens_its_panel(client):  # noqa: F811
    html = client.get(PAGE).text
    section = html[html.index('id="celdas"') :]
    ids = sorted(set(re.findall(r'data-figura="([^"]+)"', section)))
    assert len(ids) > 40
    for fid in ids:
        r = client.get(f"/respuesta/fragmentos/panel?corte=2026-10-30&empresa=AAPL&figura={fid}")
        assert r.status_code == 200, fid


def test_the_cells_read_in_english_too(client):  # noqa: F811
    client.cookies.set("warren_region", "en-US")
    html = client.get(PAGE).text
    assert "The cells behind the answer" in html and "Years of history" in html
