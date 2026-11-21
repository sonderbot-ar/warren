"""Screenshots for the design critic: `python -m webapp.screenshots --out DIR`.

Starts the app on a free local port and saves each page at laptop (1440 px) and phone (390 px)
widths, in light and dark, with the side panel closed and open (design principles, "The bar").
Set WARREN_CHROMIUM to a Chromium binary to use one already on the machine.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

WIDTHS = {"laptop": (1440, 900), "phone": (390, 844)}
THEMES = ("light", "dark")
# the pages to capture: (name, address with its fixed corte, whether the panel is open)
FIXED_CORTE = "2026-10-30"  # the last ended day on the fixed clock below, as in the mockup
# the questions the reading card is shown for, read by a fixed reader (no question leaves the
# machine); the first is the catalogue's own example, brief Q5
Q5 = "¿Cuánto venderá Apple en los próximos cuatro trimestres, y qué tan seguro es ese pronóstico?"
Q5_NO_COMPANY = (
    "¿Cuánto venderá en los próximos cuatro trimestres, y qué tan seguro es ese pronóstico?"
)
Q_CHANGE = (
    "Si el margen operativo de Walmart baja un punto porcentual, "
    "¿cuánto cambia su valor por acción?"
)


Q_EARLY = (
    "Con lo que se sabía el 15 de enero de 2018, ¿cuánto iba a vender Apple en los siguientes "
    "cuatro trimestres?"
)
EARLY = "/respuesta?" + urlencode({"corte": "2018-01-15", "empresa": "AAPL", "pregunta": Q_EARLY})


def _lectura(question: str, **extra: str) -> str:
    return "/lectura?" + urlencode({"corte": FIXED_CORTE, "pregunta": question, **extra})


PAGES = (
    ("inicio", f"/?corte={FIXED_CORTE}"),
    # part 3a: the reading card, ready; with an ask; corrected with the menus; a later screen
    ("lectura", _lectura(Q5)),
    ("lectura-falta", _lectura(Q5_NO_COMPANY)),
    ("lectura-menus", _lectura(Q5, menus="1")),
    ("lectura-pronto", _lectura(Q_CHANGE)),
    # Calculando: the card's Calcular, shot before the engine's answer arrives
    ("calculando", "click:" + _lectura(Q5)),
    ("componentes", f"/componentes?corte={FIXED_CORTE}"),
    ("panel", f"/componentes?corte={FIXED_CORTE}&panel=ejemplo&pestana=fuente"),
    # the first screen's answer (F2 Step 4b): brief Q5 on the stored run the mockup used
    ("respuesta", "/respuesta?corte=2026-10-30&empresa=AAPL"),
    ("respuesta-fuente", "/respuesta?corte=2026-10-30&empresa=AAPL&panel=pronostico-FY2026Q4"),
    # part 2: the cells behind the answer, at ten years, and a cell's figure opened
    ("respuesta-10-anos", "/respuesta?corte=2026-10-30&empresa=AAPL&anos=10"),
    (
        "respuesta-supuesto",
        "/respuesta?corte=2026-10-30&empresa=AAPL&panel=supuesto-revenue_growth",
    ),
    # part 3b: a date with no stored estimate offers Calcular; Calcular on a date the engine
    # refuses lands on No se pudo (mockup state 5), and its "¿Por qué?" opens in place
    ("sin-estimacion", EARLY),
    ("no-se-pudo", "calc:" + EARLY),
    ("no-se-pudo-porque", "calc+why:" + EARLY),
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve(app, port: int | None = None):
    """Run `app` with uvicorn on a background thread; yield its base address."""
    import uvicorn

    port = port or _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the app did not start within 10 s")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def launch_chromium(playwright):
    path = os.environ.get("WARREN_CHROMIUM")
    return (
        playwright.chromium.launch(executable_path=path) if path else playwright.chromium.launch()
    )


def readings() -> dict:
    """The fixed reader's readings for the screenshot questions (what Haiku reads for them)."""
    from webapp.reader.reading import NamedInput, Reading

    q5 = Reading(kind="estimacion", companies=("AAPL",), period="próximos cuatro trimestres")
    change = Reading(
        kind="cambio_de_supuesto",
        companies=("WMT",),
        inputs=(
            NamedInput(
                "operating_margin", how="add", direction="down", value_text="un punto porcentual"
            ),
        ),
    )
    return {
        Q5: q5,
        Q5_NO_COMPANY: Reading(kind="estimacion", period="próximos cuatro trimestres"),
        Q_CHANGE: change,
    }


def capture(out: Path, db_path: Path | None = None, only: str | None = None) -> list[Path]:
    from playwright.sync_api import sync_playwright

    from webapp.app import THEME_COOKIE, create_app
    from webapp.question import fixed_reader

    out.mkdir(parents=True, exist_ok=True)
    clock = lambda: datetime(2026, 10, 31, 18, 0, tzinfo=UTC)  # noqa: E731 (fixed day for stable shots)
    saved = []
    reader = fixed_reader(readings())
    app = create_app(db_path=db_path, clock=clock, reader=reader)
    with serve(app) as base, sync_playwright() as p:
        browser = launch_chromium(p)
        for width_name, (width, height) in WIDTHS.items():
            for theme in THEMES:
                context = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=theme
                )
                # the page's own switch (dark by default, the owner's choice), set as its cookie
                context.add_cookies([{"name": THEME_COOKIE, "value": theme, "url": base}])
                page = context.new_page()
                for name, address in PAGES:
                    if only and not name.startswith(only):
                        continue
                    path = out / f"{name}-{width_name}-{theme}.png"
                    if address.startswith("click:"):  # Calculando: shoot right after Calcular
                        # a fresh app, since an answer already worked out skips Calculando
                        fresh = create_app(db_path=db_path, clock=clock, reader=reader)
                        with serve(fresh) as other:
                            context.add_cookies(
                                [{"name": THEME_COOKIE, "value": theme, "url": other}]
                            )
                            shot = context.new_page()  # its held request dies with it
                            shot.route("**/calcular/listo", lambda route: None)  # never answers
                            shot.goto(other + address.removeprefix("click:"))
                            shot.get_by_role("button", name="Calcular").click()
                            shot.wait_for_selector('[aria-busy="true"]')
                            shot.screenshot(path=path, full_page=True)
                            shot.close()
                        saved.append(path)
                        continue
                    if address.startswith("calc"):  # Calcular posts, then htmx follows
                        how, _, address = address.partition(":")
                        page.goto(base + address)
                        # the same app keeps its refusal, so later shots land on it directly
                        if page.locator('[role="alert"]').count() == 0:
                            page.get_by_role("button", name="Calcular").click()
                        page.wait_for_selector('[role="alert"], .answer:not([hx-post])')
                        page.wait_for_load_state("networkidle")
                        if how == "calc+why":
                            page.locator("details.why summary").click()
                        page.screenshot(path=path, full_page=True)
                        saved.append(path)
                        continue
                    page.goto(base + address)
                    page.wait_for_load_state("networkidle")
                    # an open panel scrolls on its own over the page: shoot what is seen
                    page.screenshot(path=path, full_page="panel=" not in address)
                    saved.append(path)
                context.close()
        browser.close()
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp.screenshots", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", help="capture only the pages whose name starts with this")
    args = parser.parse_args(argv)
    for path in capture(args.out, only=args.only):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
