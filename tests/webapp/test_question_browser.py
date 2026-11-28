"""The question in front, in a real browser (F2 Step 4b, part 3a): a question typed on Inicio
reaches its reading card, Calcular shows Calculando and htmx follows it to the answer, and no
state scrolls sideways on a phone.

Runs where test_browser.py runs (CI's Playwright step); skipped when no Chromium is installed.
"""

import os
import time

import pytest

from tests.webapp.test_question import NOW, Q5, READINGS
from webapp.app import create_app
from webapp.question import fixed_reader
from webapp.screenshots import launch_chromium, serve

REQUIRED = os.environ.get("WARREN_BROWSER_TESTS") == "1"

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - CI installs it
    if REQUIRED:
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def slow_loader(ticker, corte):
    """The stored bundle, after a pause, so Calculando is on screen long enough to see."""
    from tests.webapp.test_answer import BUNDLE

    time.sleep(0.6)
    return BUNDLE


@pytest.fixture
def base():  # a fresh app per test: an answer already worked out skips Calculando
    app = create_app(clock=lambda: NOW, bundle_loader=slow_loader, reader=fixed_reader(READINGS))
    with serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = launch_chromium(p)
        except Exception as exc:  # no browser on this machine
            if REQUIRED:
                raise
            pytest.skip(f"no Chromium: {exc}")
        yield b
        b.close()


@pytest.fixture(params=[(1440, 900), (390, 844)], ids=["laptop", "phone"])
def page(browser, request):
    width, height = request.param
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    yield page
    context.close()


def no_sideways_scroll(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_a_typed_question_is_read_then_calculated_then_answered(page, base):
    page.goto(base + "/?corte=2026-10-30")
    no_sideways_scroll(page)
    page.fill("#pregunta", Q5)
    page.get_by_role("button", name="Leer mi pregunta").click()
    expect(page.locator("h1")).to_have_text("Así leí tu pregunta")
    no_sideways_scroll(page)
    page.get_by_role("button", name="Calcular").click()
    expect(page.locator('[role="status"]')).to_contain_text("Calculando")
    no_sideways_scroll(page)
    page.wait_for_url("**/respuesta?**", timeout=10_000)
    expect(page.locator("h1").first).to_contain_text("Apple")
    expect(page.locator("#header-ask-q")).to_have_value(Q5)
    no_sideways_scroll(page)


def test_a_company_pick_answers_the_ask(page, base):
    page.goto(base + "/?corte=2026-10-30")
    from urllib.parse import urlencode

    no_company = next(q for q, r in READINGS.items() if r.kind == "estimacion" and not r.companies)
    page.goto(base + "/lectura?" + urlencode({"corte": "2026-11-03", "pregunta": no_company}))
    expect(page.get_by_role("button", name="Calcular")).to_have_count(0)
    page.locator(".askbox").get_by_role("link", name="Walmart").click()
    expect(page.get_by_role("button", name="Calcular")).to_be_visible()
    no_sideways_scroll(page)


def test_the_menus_open_and_send_with_the_keyboard(page, base):
    from urllib.parse import urlencode

    page.goto(base + "/lectura?" + urlencode({"corte": "2026-11-03", "pregunta": "zzz"}))
    page.select_option("#m-tipo", "estimacion")
    page.select_option("#m-empresa", "AAPL")
    page.focus("#m-fecha")
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Calcular")).to_be_visible()
    no_sideways_scroll(page)
