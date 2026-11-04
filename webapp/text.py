"""The text catalogues: every word a student reads, apart from the code (Decision 11, guardrail 5).

One JSON file per language in `webapp/text/` (`es.json`, `en.json`), flat keys such as
"panel.tab.fuente". Templates never hold words of their own; they call `t("key")`. A test
keeps both catalogues on the same keys and every template free of hard-coded text, so adding
Portuguese later is one more file.

The engine's coded notes and refusals (`{code, params, text}`, backlog #140 and #172) get their
words here too, under "engine.<code>", when the first screen shows them.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

TEXT_DIR = Path(__file__).parent / "text"
LANGUAGES = ("es", "en")


@cache
def catalogue(language: str) -> dict[str, str]:
    """The catalogue for one language. Unknown languages are an error, never a silent fallback."""
    if language not in LANGUAGES:
        raise ValueError(f"no catalogue for {language!r}")
    return json.loads((TEXT_DIR / f"{language}.json").read_text(encoding="utf-8"))


def translate(language: str, key: str, **params: object) -> str:
    """The text for `key`, with {name} placeholders filled. A missing key raises, so a screen
    can never show a raw key or fall back to the other language without a test noticing."""
    try:
        text = catalogue(language)[key]
    except KeyError:
        raise KeyError(f"text key {key!r} missing from {language}.json") from None
    return text.format(**params) if params else text
