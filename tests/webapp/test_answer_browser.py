"""The first screen's answer in a real browser (F2 Step 4b, part 1): a figure opens its source in
the side panel, focus comes back to it, and the phone layout neither cuts nor scrolls sideways.

Runs where test_browser.py runs (CI's Playwright step); skipped when no Chromium is installed.
"""

import os

import pytest

from tests.webapp.test_answer import BUNDLE, NOW, PAGE
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
def base():
    app = create_app(clock=lambda: NOW, bundle_loader=lambda ticker, corte: BUNDLE)
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


def test_a_forecast_opens_its_source_and_escape_returns_to_it(page, base):
    page.goto(base + PAGE)
    figure = page.locator('a.fig[data-figura="pronostico-FY2026Q4"]').first
    figure.click()
    dialog = page.locator("dialog[data-panel]")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("0000320193-25-000079")
    expect(page.locator("#pestana-fuente")).to_be_focused()
    assert "panel=pronostico-FY2026Q4" in page.url
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert "panel=" not in page.url


def test_nothing_scrolls_sideways_and_every_door_is_at_least_24_px(page, base):
    page.goto(base + PAGE)
    width = page.viewport_size["width"]
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    doors = page.locator("a.fig, .theme-switch, .language a")
    assert doors.count() >= 15
    for i in range(doors.count()):
        box = doors.nth(i).bounding_box()
        if box is None:  # hidden at this width (the range has its own column on a laptop)
            continue
        assert box["height"] >= 24 and box["width"] >= 24


def test_the_open_panel_fits_the_phone(browser, base):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(base + PAGE + "&panel=pronostico-FY2026Q4")
    box = page.locator("dialog[data-panel]").bounding_box()
    assert box["x"] == 0 and box["width"] == 390
    assert page.evaluate("document.querySelector('dialog').scrollWidth") <= 390
    context.close()
