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

WIDTHS = {"laptop": (1440, 900), "phone": (390, 844)}
THEMES = ("light", "dark")
# the pages to capture: (name, address with its fixed corte, whether the panel is open)
FIXED_CORTE = "2026-11-03"
PAGES = (
    ("inicio", f"/?corte={FIXED_CORTE}"),
    ("componentes", f"/componentes?corte={FIXED_CORTE}"),
    ("panel", f"/componentes?corte={FIXED_CORTE}&panel=ejemplo&pestana=fuente"),
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


def capture(out: Path, db_path: Path | None = None) -> list[Path]:
    from playwright.sync_api import sync_playwright

    from webapp.app import create_app

    out.mkdir(parents=True, exist_ok=True)
    clock = lambda: datetime(2026, 11, 4, 18, 0, tzinfo=UTC)  # noqa: E731 (fixed day for stable shots)
    saved = []
    with serve(create_app(db_path=db_path, clock=clock)) as base, sync_playwright() as p:
        browser = launch_chromium(p)
        for width_name, (width, height) in WIDTHS.items():
            for theme in THEMES:
                context = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=theme
                )
                page = context.new_page()
                for name, address in PAGES:
                    page.goto(base + address)
                    page.wait_for_load_state("networkidle")
                    path = out / f"{name}-{width_name}-{theme}.png"
                    page.screenshot(path=path, full_page=True)
                    saved.append(path)
                context.close()
        browser.close()
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp.screenshots", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    for path in capture(args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
