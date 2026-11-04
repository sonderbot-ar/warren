"""Every page carries its fecha de corte; the panel's state lives in the address (F2 Step 1)."""

import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from tests.webapp.conftest import LATEST


@pytest.mark.parametrize("path", ["/", "/componentes"])
def test_a_page_without_a_corte_is_redirected_to_the_last_ended_day(client, path):
    response = client.get(path)
    assert response.status_code == 307
    assert parse_qs(urlparse(response.headers["location"]).query) == {"corte": [LATEST]}


def test_a_corte_in_the_future_is_redirected_back_to_the_last_ended_day(client):
    # nov.04 has not ended in New York at 13:00, so its data is not all public yet
    response = client.get("/componentes?corte=2026-11-04&panel=ejemplo")
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query == {"corte": [LATEST], "panel": ["ejemplo"]}  # other state is kept


def test_a_past_corte_is_kept_and_shown(client):
    response = client.get("/?corte=2025-06-30")
    assert response.status_code == 200
    assert '<time datetime="2025-06-30" data-corte>30 jun 2025</time>' in response.text


def test_an_unreadable_corte_gets_the_error_page_not_a_crash(client):
    response = client.get("/?corte=ayer")
    assert response.status_code == 400
    assert "La fecha de corte no es válida" in response.text
    assert 'role="alert"' in response.text


def test_the_panel_opens_from_the_address_on_the_tab_it_names(client):
    response = client.get(f"/componentes?corte={LATEST}&panel=ejemplo&pestana=formula")
    assert response.status_code == 200
    assert "<dialog" in response.text and "data-open" in response.text
    assert 'id="pestana-formula"' in response.text
    assert 'data-pestana="formula"' in response.text


def test_without_panel_in_the_address_the_page_has_no_panel(client):
    assert "<dialog" not in client.get(f"/componentes?corte={LATEST}").text


@pytest.mark.parametrize(
    "query", ["panel=otra", "panel=ejemplo&pestana=precio"], ids=["figure", "tab"]
)
def test_an_unknown_figure_or_tab_is_a_404_page(client, query):
    response = client.get(f"/componentes?corte={LATEST}&{query}")
    assert response.status_code == 404
    assert "No encontramos esa sección" in response.text


def test_fragments_return_only_the_panel_or_the_tab(client):
    panel = client.get(f"/fragmentos/panel?corte={LATEST}&figura=ejemplo")
    assert panel.status_code == 200
    assert panel.text.lstrip().startswith(("{#", "<dialog"))
    assert "<html" not in panel.text
    tab = client.get(f"/fragmentos/pestana?corte={LATEST}&figura=ejemplo&pestana=leer")
    assert tab.text.strip().startswith('<div class="tab-body" data-pestana="leer">')
    assert client.get(f"/fragmentos/pestana?corte={LATEST}").status_code == 404


def test_tab_links_keep_the_corte_and_update_the_address(client):
    text = client.get(f"/fragmentos/panel?corte={LATEST}&figura=ejemplo").text
    assert (
        f'hx-replace-url="/componentes?corte={LATEST}&amp;panel=ejemplo&amp;pestana=concepto"'
        in text
    )


def test_the_language_toggle_sets_the_region_and_returns_to_the_same_page(client):
    back = f"/componentes?corte={LATEST}&panel=ejemplo"
    response = client.get("/idioma", params={"region": "en-US", "volver": back})
    assert response.status_code == 303
    assert response.headers["location"] == back
    client.cookies.set("warren_region", "en-US")
    page = client.get(back).text
    assert '<html lang="en">' in page
    assert "Cut-off date" in page and "Nov 3, 2026" in page


@pytest.mark.parametrize("target", ["https://example.com/", "//example.com/", "/\\example.com"])
def test_the_language_toggle_never_redirects_off_the_site(client, target):
    response = client.get("/idioma", params={"region": "es-AR", "volver": target})
    assert response.headers["location"] == "/"


def test_an_unknown_region_sets_no_cookie(client):
    response = client.get("/idioma", params={"region": "xx", "volver": "/"})
    assert "set-cookie" not in response.headers


def test_a_busy_database_shows_the_retry_page(client):
    def locked():
        raise sqlite3.OperationalError("database is locked")  # SQLite's 10 s wait ran out

    client.app.add_api_route("/_locked", locked)
    response = client.get("/_locked")
    assert response.status_code == 503
    assert "Warren está guardando datos" in response.text


def test_any_other_database_error_is_not_dressed_up_as_busy(client):
    def broken():
        raise sqlite3.OperationalError("no such table: runs")

    client.app.add_api_route("/_broken", broken)
    with pytest.raises(sqlite3.OperationalError):
        client.get("/_broken")
