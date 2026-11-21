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

import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from domains.analysis.coded import Coded, refusal
from domains.analysis.math_engine import SUPPORTED_FROM, EngineError
from domains.analysis.runs import run_baseline
from domains.market.store import MarketDataError
from shared_kernel.calendar import last_ended_day
from shared_kernel.config import DB_PATH
from shared_kernel.database import get_db_connection
from webapp import cells, formatting, question
from webapp.answer import NoRun, answer_view, bundle_for_run, find_run
from webapp.database import schema_status
from webapp.refusal import BUTTON_DATE, BUTTON_MENUS, refusal_view
from webapp.text import translate

HERE = Path(__file__).parent
REGION_COOKIE = "warren_region"
THEME_COOKIE = "warren_theme"
THEMES = {"oscuro": "dark", "claro": "light"}  # the address's word -> the page's data-theme
DEFAULT_THEME = "dark"  # the owner's choice on the first screen's mockup (nov.18.2026)
# the companies the answer covers (Phase 1's eight)
COMPANIES = ("AAPL", "MSFT", "WMT", "KO", "PG", "JNJ", "CAT", "XOM")
# the side panel's five tabs, in order (design principle 2); their names live in the catalogues
PANEL_TABS = ("fuente", "formula", "concepto", "ysi", "leer")
# figures the component bench can open; the first screen replaces this with engine figures
BENCH_FIGURES = ("ejemplo",)


class BadCorte(ValueError):
    """The address's fecha de corte is not a date."""


class UnknownCompany(LookupError):
    """The address names a company Warren does not cover."""


class UnknownPanel(LookupError):
    """The address names a figure or a tab the page does not have."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    db_path: Path | None = None,
    clock: Callable[[], datetime] = _utc_now,
    bundle_loader: Callable[[str, date], dict] | None = None,
    reader: Callable[[str, date], object] | None = None,
    runner: Callable[[str, date, date], str] | None = None,
) -> FastAPI:
    """The app. `db_path` defaults to the engine's database; `clock` is injectable for tests,
    and so are `bundle_loader(ticker, corte)`, the engine's answer for brief Q5 (`answer.py`),
    and `reader(question, last_ended_day)`, the question reader behind the card (Claude Haiku,
    Decision 9; `question.Reader`). Tests and screenshots pass `question.fixed_reader`, so no
    question leaves the machine. `runner(ticker, corte, today)` builds and stores a baseline
    when none is stored for the date (part 3b; the engine's `run_baseline`), and raises the
    engine's coded refusal when it can't; tests pass a fake one."""
    db = Path(db_path) if db_path is not None else DB_PATH
    read_question = reader or question.Reader(_claude_backend).read

    bundles: dict[str, dict] = {}  # by run_id: a stored run never changes (answer.py)

    def engine_bundle(ticker: str, corte: date) -> dict:
        with get_db_connection(db) as conn:
            run_id = find_run(conn, ticker, corte)
            if run_id is None:
                raise NoRun(f"{ticker} {corte}")
            if run_id not in bundles:
                bundles[run_id] = bundle_for_run(conn, run_id)
            return bundles[run_id]

    engine_or_test = bundle_loader or engine_bundle
    loaded: set[tuple[str, date]] = set()  # answers already worked out: no Calculando for them

    def bundle_for(ticker: str, corte: date) -> dict:
        bundle = engine_or_test(ticker, corte)
        loaded.add((ticker, corte))
        return bundle

    def engine_run(ticker: str, corte: date, today: date) -> str:
        with get_db_connection(db) as conn:
            return run_baseline(conn, ticker, corte, today=today)

    def no_runner(ticker: str, corte: date, today: date) -> str:
        raise NoRun(f"{ticker} {corte}")  # a test's answers with no runner: never the real DB

    run_or_test = runner or (engine_run if bundle_loader is None else no_runner)
    # The last refusal for a company and date, so the answer's address can say why after
    # Calculando sends the page there. A refused run stores nothing, so this lives only in the
    # server's memory; any new Calcular asks the engine again (data may have been loaded since).
    refused: dict[tuple[str, date], Coded | None] = {}
    run_locks: dict[tuple[str, date], threading.Lock] = {}
    locks_guard = threading.Lock()

    def lock_for(key: tuple[str, date]) -> threading.Lock:
        with locks_guard:
            return run_locks.setdefault(key, threading.Lock())

    def work_out(ticker: str, corte: date) -> None:
        """The answer for a company and date: the stored baseline, or a new one built now when
        none is stored (the app writes only here, after a student's Calcular). One run at a time
        per company and date, so a double click never stores two."""
        key = (ticker, corte)
        refused.pop(key, None)
        try:
            bundle_for(ticker, corte)
            return
        except NoRun:
            pass
        with lock_for(key):
            try:  # another request may have built it while this one waited
                bundle_for(ticker, corte)
                return
            except NoRun:
                pass
            try:
                run_or_test(ticker, corte, latest_corte())
            except (EngineError, MarketDataError) as exc:
                refused[key] = refusal(exc)
                return
            bundle_for(ticker, corte)

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
        theme = request.cookies.get(THEME_COOKIE, DEFAULT_THEME)
        base = {
            "theme": theme if theme in THEMES.values() else DEFAULT_THEME,
            "t": partial(translate, region.language),
            "region": region,
            "fmt_date": partial(formatting.format_date, region=region),
            "corte": latest_corte(),  # pages override it with the address's own
            "question": None,  # the student's question, in the header after Inicio
            "max_question": question.MAX_QUESTION,
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
        if "/fragmentos/" in request.url.path:
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

    @app.exception_handler(UnknownCompany)
    def _unknown_company(request: Request, exc: UnknownCompany) -> HTMLResponse:
        return render(
            request,
            "error.html",
            {
                "title_key": "error.company.title",
                "body_key": "error.company.body",
                "retry_url": _url_without(request, "empresa", "panel", "figura", "pestana"),
            },
            status_code=404,
        )

    @app.exception_handler(NoRun)
    def _no_run(request: Request, exc: NoRun) -> HTMLResponse:
        # No stored estimate for the date: a page view never writes, so the page offers
        # Calcular, which posts and runs one (part 3b).
        ticker = request.query_params.get("empresa", "").upper()
        corte = request.query_params.get("corte", "")
        day = date.fromisoformat(corte)
        if day < SUPPORTED_FROM:  # the engine would refuse it: don't make the student wait
            refused[(ticker, day)] = Coded(
                "as_of_too_early",
                {"as_of": corte, "supported_from": SUPPORTED_FROM.isoformat()},
                "before the first supported date",
            )
            return no_se_pudo(request, day, ticker)
        text = question.clean_question(request.query_params.get("pregunta"))
        language = region_of(request).language
        return render(
            request,
            "sin_estimacion.html",
            {
                "corte": day,
                "question": text or None,
                "change_url": page_url("/lectura", corte=corte, empresa=ticker, pregunta=text)
                if text
                else page_url("/", corte=corte),
                "company": translate(language, f"company.{ticker}"),
                "corte_text": formatting.format_date(day, region_of(request)).replace(
                    " ", "\u00a0"
                ),
                "calculate_fields": {"corte": corte, "empresa": ticker, "pregunta": text},
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
        t = partial(translate, region_of(request).language)

        def reading_url(text: str) -> str:
            return page_url("/lectura", corte=corte.isoformat(), pregunta=text)

        examples = [
            {"kind": kind, "text": t(f"inicio.example.{kind}")}
            for kind in ("estimacion", "dato", "cambio_de_supuesto")
        ]
        for example in examples:
            example["url"] = reading_url(example["text"])
        companies = [
            {
                "ticker": ticker,
                "url": reading_url(t("inicio.company_question", company=t(f"company.{ticker}"))),
            }
            for ticker in COMPANIES
        ]
        context = {
            "corte": corte,
            "today": question.today_after(latest_corte()),
            "examples": examples,
            "companies": companies,
        }
        return render(request, "inicio.html", context)

    # -- the question in front (part 3a): the reading card, the menus, Calculando ---------------

    @app.get("/lectura", response_class=HTMLResponse)
    def lectura(request: Request) -> Response:
        """The reading card for the address's question: what Warren read, the student's choices
        in place of the reader's, and Calcular only when nothing is left to answer."""
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        text = question.clean_question(request.query_params.get("pregunta"))
        if not text:
            return RedirectResponse(page_url("/", corte=corte.isoformat()), status_code=303)
        region = region_of(request)
        t = partial(translate, region.language)
        latest = latest_corte()
        choices = question.Choices.from_query(request.query_params, latest)
        qc = question.question_card(text, read_question(text, latest), choices, latest, region)
        base = {"corte": corte.isoformat(), "pregunta": text}

        def choose(**picked: str) -> str:
            return page_url("/lectura", **{**base, **choices.params(), **picked})

        asks = []
        for item in qc.asks:
            ask = {"text": t(question.ask_key(item), **question.item_params(item, t, region))}
            if item.code == "company_missing":  # the buttons name the eight; the text need not
                ask["text"] = t("question.ask.company_pick")
            if item.code in ("company_missing", "one_company"):
                ask["companies"] = [
                    {"ticker": c, "url": choose(empresa=c)} for c in item.params["companies"]
                ]
            asks.append(ask)
        notes = [
            t(question.note_key(n), **question.item_params(n, t, region)) for n in qc.card.notes
        ]
        later_url = None
        if qc.step == question.STEP_LATER and qc.company:
            name = t(f"company.{qc.company}")
            later_url = page_url(
                "/lectura",
                corte=corte.isoformat(),
                pregunta=t("inicio.company_question", company=name),
            )
        context = {
            "corte": qc.corte,
            "latest": latest,
            "question": text,
            "qc": qc,
            "asks": asks,
            "notes": notes,
            "screen_shows": qc.reading.kind in question.SCREENS,
            "company_only": all(a.code in ("company_missing", "one_company") for a in qc.asks),
            "menus_open": qc.show_menus or request.query_params.get("menus") == "1",
            "menus_url": choose(menus="1"),
            "menu_kinds": question.MENU_KINDS,
            "all_companies": COMPANIES,
            "later_url": later_url,
            "calculate_fields": {
                "corte": qc.corte.isoformat(),
                "empresa": qc.company or "",
                "pregunta": text,
            },
        }
        return render(request, "lectura.html", context)

    async def calculate_params(request: Request) -> tuple[date, str, str]:
        """The confirmed reading the card sent: corte, company and the question, checked again
        here (the form is the student's, so nothing in it is trusted)."""
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        raw = (form.get("corte") or [""])[0]
        try:
            corte = date.fromisoformat(raw)
        except ValueError:
            raise BadCorte(raw) from None
        if corte > latest_corte():
            raise BadCorte(raw)
        ticker = (form.get("empresa") or [""])[0].upper()
        if ticker not in COMPANIES:
            raise UnknownCompany(ticker)
        return corte, ticker, question.clean_question((form.get("pregunta") or [""])[0])

    def answer_address(corte: date, ticker: str, text: str) -> str:
        params = {"corte": corte.isoformat(), "empresa": ticker}
        if text:
            params["pregunta"] = text
        return page_url("/respuesta", **params)

    @app.post("/calcular", response_class=HTMLResponse)
    async def calcular(request: Request) -> Response:
        """Calcular on the card. An answer already worked out opens at once; otherwise
        Calculando shows the reading while the engine works, and htmx follows to the answer."""
        corte, ticker, text = await calculate_params(request)
        answer_url = answer_address(corte, ticker, text)
        if (ticker, corte) in loaded:
            return RedirectResponse(answer_url, status_code=303)
        fields = {"corte": corte.isoformat(), "empresa": ticker, "pregunta": text}
        context = {
            "corte": corte,
            "question": text or None,
            "company": translate(region_of(request).language, f"company.{ticker}"),
            "change_url": page_url("/lectura", **fields) if text else None,
            "answer_url": answer_url,
            "ready_url": "/calcular/listo",
            "ready_vals": json.dumps(fields),
        }
        return render(request, "calculando.html", context)

    @app.post("/calcular/listo")
    async def calcular_listo(request: Request) -> Response:
        """Works the answer out (htmx, from Calculando), running a baseline when none is stored
        for the date, then sends the page to the answer's address, which shows the answer or
        why the engine refused it (No se pudo)."""
        corte, ticker, text = await calculate_params(request)
        try:
            await run_in_threadpool(work_out, ticker, corte)
        except NoRun:  # nothing stored or built: the address says so and offers Calcular
            pass
        return Response(
            status_code=204, headers={"HX-Redirect": answer_address(corte, ticker, text)}
        )

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

    # -- the answer (brief Q5) -----------------------------------------------------------------

    def answer_params(request: Request) -> tuple[date, str] | RedirectResponse:
        corte = corte_or_redirect(request)
        if isinstance(corte, RedirectResponse):
            return corte
        ticker = request.query_params.get("empresa", "").upper()
        if ticker not in COMPANIES:
            raise UnknownCompany(ticker)
        return corte, ticker

    def answer_base(corte: date, ticker: str, years: int, text: str = "") -> dict:
        base = {"corte": corte.isoformat(), "empresa": ticker}
        if text:  # the student's question rides along, so the header and the card keep it
            base["pregunta"] = text
        if years != cells.DEFAULT_YEARS:  # the default stays out of the address
            base["anos"] = str(years)
        return base

    def answer_panel(
        view,
        corte: date,
        ticker: str,
        figura: str,
        pestana: str,
        full: bool,
        years: int,
        text: str = "",
    ):
        if figura not in view.figures or pestana not in PANEL_TABS:
            raise UnknownPanel(f"{figura}/{pestana}")
        base = answer_base(corte, ticker, years, text)
        return {
            "full_page": full,
            "corte": corte,
            "figura": figura,
            "figure": view.figures[figura],
            "title": view.figures[figura].title,
            "pestana": pestana,
            "close_url": page_url("/respuesta", **base),
            "tab_page_url": lambda tab: page_url("/respuesta", **base, panel=figura, pestana=tab),
            "tab_fragment_url": lambda tab: page_url(
                "/respuesta/fragmentos/pestana", **base, figura=figura, pestana=tab
            ),
            # the formula bar follows the open figure when htmx swaps the panel in (out of band)
            "formula": view.figures[figura].formula,
        }

    def answer_context(request: Request, corte: date, ticker: str):
        """The view and the links every part of the answer needs, for the address's years."""
        region = region_of(request)
        years = cells.years_from(request.query_params.get("anos"))
        view = answer_view(
            bundle_for(ticker, corte), region, partial(translate, region.language), years
        )
        text = question.clean_question(request.query_params.get("pregunta"))
        base = answer_base(corte, ticker, years, text)
        plain = answer_base(corte, ticker, cells.DEFAULT_YEARS, text)

        def with_years(n: int) -> dict:
            return {**plain, "anos": str(n)} if n != cells.DEFAULT_YEARS else plain

        context = {
            "corte": corte,
            "question": text or None,
            "change_url": page_url("/lectura", **plain) if text else None,
            "view": view,
            "panel": None,
            "open_figure": None,
            "formula": None,
            "figure_url": lambda f: page_url("/respuesta", **base, panel=f),
            "figure_fragment_url": lambda f: page_url(
                "/respuesta/fragmentos/panel", **base, figura=f
            ),
            "years_url": lambda n: page_url("/respuesta", **with_years(n)),
            "years_fragment_url": lambda n: page_url(
                "/respuesta/fragmentos/celdas", **with_years(n)
            ),
        }
        return view, years, context

    @app.get("/respuesta", response_class=HTMLResponse)
    def respuesta(request: Request) -> Response:
        """Brief Q5: the company's revenue for the next four quarters, its p10–p90 range and
        how often that range held, from the stored baseline dated the fecha de corte; below
        it, the cells behind the answer with 3, 5 or 10 years of history (`anos`)."""
        params = answer_params(request)
        if isinstance(params, RedirectResponse):
            return params
        corte, ticker = params
        if (ticker, corte) in refused:
            return no_se_pudo(request, corte, ticker)
        view, years, context = answer_context(request, corte, ticker)
        figura = request.query_params.get("panel")
        if figura is not None:
            pestana = request.query_params.get("pestana", PANEL_TABS[0])
            context["panel"] = answer_panel(
                view, corte, ticker, figura, pestana, True, years, context["question"] or ""
            )
            context["open_figure"] = figura
            context["formula"] = view.figures[figura].formula
        return render(request, "respuesta.html", context)

    def no_se_pudo(request: Request, corte: date, ticker: str) -> HTMLResponse:
        """Why the engine refused this company and date (brief, "When an estimate can't be
        built"): the group's title, the cause, one button, and the lesson under it."""
        region = region_of(request)
        t = partial(translate, region.language)
        company = t(f"company.{ticker}")
        view = refusal_view(refused[(ticker, corte)], company, corte, latest_corte(), region, t)
        text = question.clean_question(request.query_params.get("pregunta"))
        fields = {"corte": corte.isoformat(), "empresa": ticker, "pregunta": text}
        button_fields = None
        menus_url = None
        if view.button and view.button.kind == BUTTON_DATE:
            button_fields = {**fields, "corte": view.button.corte.isoformat()}
        elif view.button and view.button.kind == BUTTON_MENUS:
            menus_url = (
                page_url("/lectura", **fields, menus="1")
                if text
                else page_url("/", corte=corte.isoformat())
            )
        context = {
            "corte": corte,
            "question": text or None,
            "company": company,
            "change_url": page_url("/lectura", **fields) if text else None,
            "refusal": view,
            "button_fields": button_fields,
            "menus_url": menus_url,
        }
        return render(request, "no_se_pudo.html", context)

    @app.get("/respuesta/fragmentos/celdas", response_class=HTMLResponse)
    def respuesta_celdas(request: Request) -> Response:
        """The cells section alone, for the years switch (htmx swaps it in place)."""
        params = answer_params(request)
        if isinstance(params, RedirectResponse):
            return params
        corte, ticker = params
        _, _, context = answer_context(request, corte, ticker)
        return render(request, "_celdas.html", context)

    def answer_fragment(request: Request, template: str) -> Response:
        params = answer_params(request)
        if isinstance(params, RedirectResponse):
            return params
        corte, ticker = params
        figura = request.query_params.get("figura")
        if figura is None:
            raise UnknownPanel("")
        view, years, context = answer_context(request, corte, ticker)
        pestana = request.query_params.get("pestana", PANEL_TABS[0])
        panel = answer_panel(
            view, corte, ticker, figura, pestana, False, years, context["question"] or ""
        )
        return render(request, template, {"panel": panel, "corte": corte})

    @app.get("/respuesta/fragmentos/panel", response_class=HTMLResponse)
    def respuesta_panel(request: Request) -> Response:
        return answer_fragment(request, "_panel.html")

    @app.get("/respuesta/fragmentos/pestana", response_class=HTMLResponse)
    def respuesta_pestana(request: Request) -> Response:
        return answer_fragment(request, "_tab.html")

    @app.get("/tema")
    def tema(request: Request, modo: str = "", volver: str = "/") -> RedirectResponse:
        """Switch between dark (the default) and light, then go back to the same page."""
        if not volver.startswith("/") or volver.startswith("//") or "\\" in volver:
            volver = "/"  # only paths on this site: never an open redirect
        response = RedirectResponse(volver, status_code=303)
        if modo in THEMES:
            response.set_cookie(
                THEME_COOKIE, THEMES[modo], max_age=365 * 24 * 3600, samesite="lax", httponly=True
            )
        return response

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


def _claude_backend():
    """The reader's model: Claude Haiku through Anthropic's API (Decision 9, the owner's card of
    nov.08.2026). Made on the first question; without a key the reader is unavailable and the
    card opens its menus."""
    from webapp.reader.model import ClaudeBackend

    return ClaudeBackend()


def _redirect_with(request: Request, **params: str) -> RedirectResponse:
    query = dict(request.query_params)
    query.update(params)
    return RedirectResponse(f"{request.url.path}?{urlencode(query)}", status_code=307)


def _url_without(request: Request, *names: str) -> str:
    query = {k: v for k, v in request.query_params.items() if k not in names}
    return f"{request.url.path}?{urlencode(query)}" if query else request.url.path
