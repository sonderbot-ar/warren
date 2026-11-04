"""The side panel in a real browser: keyboard, focus, the address and phone width (F2 Step 1).

Runs in CI's Playwright step (WARREN_BROWSER_TESTS=1, where a missing browser is a failure).
Elsewhere it runs when Playwright and a Chromium are installed, and is skipped otherwise.
Set WARREN_CHROMIUM to use a Chromium already on the machine.
"""

import os
from urllib.parse import parse_qs, urlparse

import pytest

from tests.webapp.conftest import LATEST, NOW
from webapp.app import create_app
from webapp.screenshots import launch_chromium, serve

REQUIRED = os.environ.get("WARREN_BROWSER_TESTS") == "1"

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - CI installs it
    if REQUIRED:
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    app = create_app(db_path=tmp_path_factory.mktemp("db") / "w.db", clock=lambda: NOW)
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


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    yield page
    context.close()


def _query(page):
    return parse_qs(urlparse(page.url).query)


def _focused_id(page):
    return page.evaluate("document.activeElement && document.activeElement.id")


def _open_from_bench(page, base):
    page.goto(f"{base}/componentes?corte={LATEST}")
    page.get_by_role("link", name="Abrir el panel de ejemplo").click()
    expect(page.locator("dialog[data-panel]")).to_be_visible()
    expect(page.locator("#pestana-fuente")).to_be_focused()


def test_opening_the_panel_moves_focus_in_and_puts_it_in_the_address(page, base):
    _open_from_bench(page, base)
    assert page.evaluate("document.querySelector('dialog[data-panel]').matches(':modal')")
    assert _focused_id(page) == "pestana-fuente"
    assert _query(page) == {"corte": [LATEST], "panel": ["ejemplo"]}


def test_arrow_keys_home_and_end_move_between_tabs_and_show_them(page, base):
    _open_from_bench(page, base)
    live = page.locator("[data-panel-live]")
    page.keyboard.press("ArrowRight")
    expect(page.locator('.tab-body[data-pestana="formula"]')).to_be_visible()
    assert _focused_id(page) == "pestana-formula"
    expect(live).to_have_text("Mostrando: Fórmula")
    assert _query(page)["pestana"] == ["formula"]
    expect(page.locator('[role="tabpanel"]')).to_have_attribute(
        "aria-labelledby", "pestana-formula"
    )

    page.keyboard.press("End")
    expect(page.locator('.tab-body[data-pestana="leer"]')).to_be_visible()
    page.keyboard.press("Home")
    expect(page.locator('.tab-body[data-pestana="fuente"]')).to_be_visible()
    page.keyboard.press("ArrowLeft")  # wraps round to the last tab
    expect(page.locator('.tab-body[data-pestana="leer"]')).to_be_visible()
    assert _focused_id(page) == "pestana-leer"
    selected = page.locator('[role="tab"][aria-selected="true"]')
    expect(selected).to_have_count(1)
    expect(selected).to_have_attribute("tabindex", "0")


def test_escape_closes_returns_focus_to_the_figure_and_back_reopens(page, base):
    _open_from_bench(page, base)
    page.keyboard.press("ArrowRight")
    expect(page.locator('.tab-body[data-pestana="formula"]')).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("dialog[data-panel]")).to_have_count(0)
    assert page.evaluate("document.activeElement.dataset.figura") == "ejemplo"
    assert _query(page) == {"corte": [LATEST]}

    page.go_back()  # the address with the panel, on the tab it was left on
    expect(page.locator("#pestana-formula")).to_be_focused()
    expect(page.locator('.tab-body[data-pestana="formula"]')).to_be_visible()
    assert page.evaluate("document.querySelector('dialog[data-panel]').matches(':modal')")


def test_the_close_button_closes_too(page, base):
    _open_from_bench(page, base)
    page.get_by_role("button", name="Cerrar el panel").click()
    expect(page.locator("dialog[data-panel]")).to_have_count(0)
    assert _query(page) == {"corte": [LATEST]}


def test_a_copied_address_reopens_the_panel_on_its_tab(page, base):
    page.goto(f"{base}/componentes?corte={LATEST}&panel=ejemplo&pestana=concepto")
    expect(page.locator("#pestana-concepto")).to_be_focused()
    assert page.evaluate("document.querySelector('dialog[data-panel]').matches(':modal')")
    assert _focused_id(page) == "pestana-concepto"


def test_at_phone_width_the_panel_is_full_screen_and_nothing_scrolls_sideways(browser, base):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(f"{base}/componentes?corte={LATEST}&panel=ejemplo&pestana=ysi")
    box = page.locator("dialog[data-panel]").bounding_box()
    assert box["x"] == 0 and box["width"] == 390
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    context.close()


def test_touch_targets_are_at_least_24_px(page, base):
    page.goto(f"{base}/componentes?corte={LATEST}&panel=ejemplo")
    targets = page.locator('[role="tab"], .panel-close, .language a, .figure-door')
    assert targets.count() >= 9
    for i in range(targets.count()):
        box = targets.nth(i).bounding_box()
        if box is None:  # behind the modal: measured on the page without the panel below
            continue
        assert box["height"] >= 24 and box["width"] >= 24
