"""The student web app's server: FastAPI with Jinja2 pages that htmx updates in place (Decision 13).

Step 1 of F2 (`docs/designs/f2-web-app.md`): the skeleton, with no screens. It has the page
shell, the *fecha de corte* in every address, the language toggle, the side panel's behaviour
on a component bench, a health check and the error pages. Screens come after M10 merges.

Rules every route keeps:
- Point in time. Every page carries `?corte=YYYY-MM-DD`. A request without one, or with a date
  that has not ended yet in New York, is redirected to the last day that has
  (`shared_kernel.calendar.last_ended_day`), so every engine call gets an explicit `as_of`.
- No words in code. Every text comes from the catalogues (`webapp/text.py`).
- The engine is a library: the app imports it and never edits it (Decision 11, guardrail 4).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shared_kernel.calendar import last_ended_day
from shared_kernel.config import DB_PATH
from shared_kernel.database import get_db_connection
from webapp import formatting
from webapp.database import schema_status
from webapp.text import translate

HERE = Path(__file__).parent
REGION_COOKIE = "warren_region"
# the side panel's five tabs, in order (design principle 2); their names live in the catalogues
PANEL_TABS = ("fuente", "formula", "concepto", "ysi", "leer")
# figures the component bench can open; the first screen replaces this with engine figures
BENCH_FIGURES = ("ejemplo",)


class BadCorte(ValueError):
    """The address's fecha de corte is not a date."""


class UnknownPanel(LookupError):
    """The address names a figure or a tab the page does not have."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(db_path: Path | None = None, clock: Callable[[], datetime] = _utc_now) -> FastAPI:
    """The app. `db_path` defaults to the engine's database; `clock` is injectable for tests."""
    db = Path(db_path) if db_path is not None else DB_PATH
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["tabs"] = PANEL_TABS

    def region_of(request: Request) -> formatting.Region:
        return formatting.region_for(request.cookies.get(REGION_COOKIE))

    def latest_corte() -> date:
        return last_ended_day(clock())

    def corte_or_redirect(request: Request) -> date | RedirectResponse:
        """The address's fecha de corte, or a redirect to an address that has a valid one."""
        latest = latest_corte()
        raw = request.query_params.get("corte")
        if raw is None:
            return _redirect_with(request, corte=latest.isoformat())
        try:
            corte = date.fromisoformat(raw)
        except ValueError:
            raise BadCorte(raw) from None
        if corte > latest:  # nothing from the future: that day's data is not all public yet
            return _redirect_with(request, corte=latest.isoformat())
        return corte

    def render(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
        region = region_of(request)
        base = {
            "t": partial(translate, region.language),
            "region": region,
            "fmt_date": partial(formatting.format_date, region=region),
            "corte": latest_corte(),  # pages override it with the address's own
            "path": request.url.path,
            "query": str(request.url.query),
        }
        return templates.TemplateResponse(
            request, name, {**base, **context}, status_code=status_code
        )

    def page_url(path: str, **params: str) -> str:
        return f"{path}?{urlencode(params)}"

    def panel_context(corte: date, figura: str, pestana: str, full_page: bool = False) -> dict:
        corte_s = corte.isoformat()
        return {
            "full_page": full_page,
            "corte": corte,
            "figura": figura,
            "pestana": pestana,
            "close_url": page_url("/componentes", corte=corte_s),
            "tab_page_url": lambda tab: page_url(
                "/componentes", corte=corte_s, panel=figura, pestana=tab
            ),
            "tab_fragment_url": lambda tab: page_url(
                "/fragmentos/pestana", corte=corte_s, figura=figura, pestana=tab
            ),
        }

    def panel_params(request: Request) -> tuple[str, str] | None:
        """(figure, tab) from the address, None when no panel is open."""
        figura = request.query_params.get("panel") or request.query_params.get("figura")
        if figura is None:
            return None
        pestana = request.query_params.get("pestana", PANEL_TABS[0])
        if figura not in BENCH_FIGURES or pestana not in PANEL_TABS:
            raise UnknownPanel(f"{figura}/{pestana}")
        return figura, pestana

    def required_panel_params(request: Request) -> tuple[str, str]:
        params = panel_params(request)
        if params is None:
            raise UnknownPanel("")
        return params

    @app.exception_handler(BadCorte)
    def _bad_corte(request: Request, exc: BadCorte) -> HTMLResponse:
        return render(
            request,
            "error.html",
            {
                "title_key": "error.corte.title",
                "body_key": "error.corte.body",
                "retry_url": _url_without(request, "corte"),
            },
            status_code=400,
        )

    @app.exception_handler(UnknownPanel)
    def _unknown_panel(request: Request, exc: UnknownPanel) -> Response:
        if request.url.path.startswith("/fragmentos/"):
            return Response(status_code=404)
        return render(
            request,
            "error.html",
            {
                "title_key": "error.not_found.title",
                "body_key": "error.not_found.body",
                "retry_url": _url_without(request, "panel", "figura", "pestana"),
            },
            status_code=404,
        )

    @app.exception_handler(sqlite3.OperationalError)
    def _busy(request: Request, exc: sqlite3.OperationalError) -> HTMLResponse:
        # SQLite waited its 10 s for a lock (a long ingest is writing); the student can retry.
        # Any other database error is a bug: it is raised, and the server answers 500.
        if "locked" not in str(exc) and "busy" not in str(exc):
            raise exc
        return render(
            request,
            "error.html",
            {
                "title_key": "error.busy.title",
                "body_key": "error.busy.body",
                "retry_url": str(request.url),
            },
            status_code=503,
        )

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request) -> Response:
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        return render(request, "inicio.html", {"corte": corte})

    @app.get("/componentes", response_class=HTMLResponse)
    def componentes(request: Request) -> Response:
        """The component bench: the side panel's behaviour, with placeholder text, no figures."""
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        params = panel_params(request)
        context = {
            "corte": corte,
            "open_url": page_url("/componentes", corte=corte.isoformat(), panel="ejemplo"),
            "open_fragment_url": page_url(
                "/fragmentos/panel", corte=corte.isoformat(), figura="ejemplo"
            ),
            "panel": None,
        }
        if params is not None:
            context["panel"] = panel_context(corte, *params, full_page=True)
        return render(request, "componentes.html", context)

    @app.get("/fragmentos/panel", response_class=HTMLResponse)
    def fragmento_panel(request: Request) -> Response:
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        params = required_panel_params(request)
        return render(request, "_panel.html", {"panel": panel_context(corte, *params)})

    @app.get("/fragmentos/pestana", response_class=HTMLResponse)
    def fragmento_pestana(request: Request) -> Response:
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        params = required_panel_params(request)
        return render(request, "_tab.html", {"panel": panel_context(corte, *params)})

    @app.get("/idioma")
    def idioma(request: Request, region: str = "", volver: str = "/") -> RedirectResponse:
        """Switch language and region, then go back to the same page (same corte and panel)."""
        if not volver.startswith("/") or volver.startswith("//") or "\\" in volver:
            volver = "/"  # only paths on this site: never an open redirect
        response = RedirectResponse(volver, status_code=303)
        chosen = formatting.REGIONS.get(region)
        if chosen is not None:
            response.set_cookie(
                REGION_COOKIE, chosen.code, max_age=365 * 24 * 3600, samesite="lax", httponly=True
            )
        return response

    @app.get("/salud")
    def salud() -> JSONResponse:
        """Health check: the database's schema against the code. Read only, its own connection."""
        if not db.exists():
            return JSONResponse({"status": "no_database"}, status_code=503)
        with get_db_connection(db) as conn:
            status = schema_status(conn)
        body = {
            "status": "ok" if status.current else "schema_mismatch",
            "missing": status.missing,
            "unknown": status.unknown,
            "corte": latest_corte().isoformat(),
        }
        return JSONResponse(body, status_code=200 if status.current else 503)

    return app


def _redirect_with(request: Request, **params: str) -> RedirectResponse:
    query = dict(request.query_params)
    query.update(params)
    return RedirectResponse(f"{request.url.path}?{urlencode(query)}", status_code=307)


def _url_without(request: Request, *names: str) -> str:
    query = {k: v for k, v in request.query_params.items() if k not in names}
    return f"{request.url.path}?{urlencode(query)}" if query else request.url.path
