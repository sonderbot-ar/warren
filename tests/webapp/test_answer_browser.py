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
    expect(dialog).to_contain_text("0000320193\u201125\u2011000079")
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
        if box is None or box["height"] == 0:  # hidden: another width's copy, or a closed table
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


# -- part 2: the cells behind the answer -------------------------------------------------------


def test_the_years_switch_swaps_the_cells_in_place_and_keeps_the_address(page, base):
    page.goto(base + PAGE)
    page.locator(".yrs-opt", has_text="10").click()
    expect(page.locator('.yrs-opt[aria-current="true"]')).to_have_text("10")
    assert page.url.endswith("anos=10")
    tables = page.locator(".cellcard").first.locator("tbody tr").first.locator("td")
    expect(tables).to_have_count(11)  # ten years, the base the last of them, then the forecast


def test_the_cells_never_scroll_sideways_at_ten_years(page, base):
    page.goto(base + PAGE + "&anos=10")
    for summary in page.locator(".cellcard details summary").all():
        summary.click()
    width = page.viewport_size["width"]
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    for door in page.locator(".yrs-opt, .cellcard summary").all():
        box = door.bounding_box()
        assert box["height"] >= 44 and box["width"] >= 44


def test_a_value_in_the_cells_opens_its_source(page, base):
    page.goto(base + PAGE)
    page.locator('a.fig[data-figura="supuesto-revenue_growth"]').first.click()
    dialog = page.locator("dialog[data-panel]")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("2023")
    expect(page.locator(".fx code")).to_contain_text("=PROMEDIO(")


def test_the_years_switch_keeps_keyboard_focus_on_the_chosen_option(page, base):
    page.goto(base + PAGE)
    page.locator(".yrs-opt", has_text="10").focus()
    page.keyboard.press("Enter")
    expect(page.locator('.yrs-opt[aria-current="true"]')).to_have_text("10")
    expect(page.locator('.yrs-opt[aria-current="true"]')).to_be_focused()
