"""Words live in the catalogues and styles in the tokens (Decision 11, guardrail 5; principles)."""

import re
import string
from pathlib import Path

import pytest

from webapp.text import LANGUAGES, catalogue, translate

WEBAPP = Path(__file__).parents[2] / "webapp"
TEMPLATES = sorted((WEBAPP / "templates").glob("*.html"))
JINJA = re.compile(r"{{.*?}}|{%.*?%}|{#.*?#}", re.DOTALL)
TAG = re.compile(r"<[^>]*>", re.DOTALL)
# attributes a person reads or hears; their values must come from t(...)
READ_ATTRS = re.compile(r'\b(aria-label|title|alt|placeholder)="([^"]*)"')
ALLOWED_LEFTOVER = set(string.whitespace + string.punctuation + "·…×")


def test_both_languages_have_the_same_keys():
    assert set(catalogue("es")) == set(catalogue("en"))


def test_both_languages_keep_the_same_placeholders():
    for key, text in catalogue("es").items():
        assert re.findall(r"{(\w+)}", text) == re.findall(r"{(\w+)}", catalogue("en")[key]), key


def test_no_entry_is_empty():
    for language in LANGUAGES:
        assert all(text.strip() for text in catalogue(language).values()), language


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_hold_no_words_of_their_own(template):
    source = template.read_text(encoding="utf-8")
    for attr, value in READ_ATTRS.findall(source):
        assert JINJA.fullmatch(value), f"{template.name}: {attr} is hard-coded: {value!r}"
    leftover = TAG.sub(" ", JINJA.sub(" ", source))
    stray = {c for c in leftover if c not in ALLOWED_LEFTOVER}
    assert not stray, f"{template.name} has text outside the catalogue: {leftover.split()!r}"


def _keys_named_in(source: str) -> set[str]:
    """Whole keys: t("a.b") in templates, "..._key": "a.b" in the server."""
    return set(re.findall(r"""\bt\(\s*["']([a-z_.]*[a-z_])["']\s*\)""", source)) | set(
        re.findall(r'_key":\s*"([a-z_.]+)"', source)
    )


def test_every_key_the_app_names_exists():
    named = set()
    for path in [*TEMPLATES, WEBAPP / "app.py"]:
        named |= _keys_named_in(path.read_text(encoding="utf-8"))
    from webapp.app import PANEL_TABS

    named |= {f"panel.tab.{tab}" for tab in PANEL_TABS} | {f"panel.body.{t}" for t in PANEL_TABS}
    assert "error.busy.title" in named and "panel.close" in named  # the scan finds keys
    missing = sorted(key for key in named if key not in catalogue("es"))
    assert not missing


def test_a_missing_key_raises_instead_of_showing_the_key():
    with pytest.raises(KeyError):
        translate("es", "no.such.key")
    with pytest.raises(ValueError):
        catalogue("pt")


RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|lab)\(")
RAW_FONT_SIZE = re.compile(r"font-size:\s*[0-9.]+(?:px|rem|em)")


def test_styles_set_colours_and_type_sizes_only_through_tokens():
    css = (WEBAPP / "static" / "app.css").read_text(encoding="utf-8")
    assert not RAW_COLOUR.findall(css)
    assert not RAW_FONT_SIZE.findall(css)
    for template in TEMPLATES:
        assert "style=" not in template.read_text(encoding="utf-8"), template.name


def test_light_and_dark_define_the_same_colour_tokens():
    tokens = (WEBAPP / "static" / "tokens.css").read_text(encoding="utf-8")
    blocks = re.split(r"@media \(prefers-color-scheme: dark\)|:root\[data-theme=\"dark\"\]", tokens)
    light, media_dark, forced_dark = blocks
    names = [set(re.findall(r"(--color-[a-z-]+):", block)) for block in blocks]
    assert names[0] == names[1] == names[2]
    assert light and media_dark and forced_dark


def test_vendored_htmx_is_the_pinned_release():
    import hashlib

    data = (WEBAPP / "static" / "vendor" / "htmx-2.0.11.min.js").read_bytes()
    # sha256 of dist/htmx.min.js in htmx.org-2.0.11.tgz (npm integrity verified at download)
    assert (
        hashlib.sha256(data).hexdigest()
        == "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"
    )


# sha256 of fonts/complete/woff2/<file> in @ibm/plex-sans-1.1.0.tgz and @ibm/plex-mono-1.1.0.tgz
# (npm sha512 integrity of both tarballs verified at download, nov.19.2026)
PLEX_FACES = {
    "IBMPlexSans-Regular.woff2": "ba711a3085ff9f27440b6b9c4550cfc47c97bf36591d5da958b975bb3add8c1a",
    "IBMPlexSans-Medium.woff2": "5660f8a658f8bb50dbc005232f885eadffd2bc1c235c4f6fbb63469d1f9cde6d",
    "IBMPlexSans-SemiBold.woff2": (
        "f78048030eab62e860efa39a0df79e2e5581bf122eb95b9bc42c0b8a4988d205"
    ),
    "IBMPlexMono-Regular.woff2": "49ce58b41a0e1cb921c0f58d9a5b8b96a2cc21437c7066f3ba4f24873076d131",
    "IBMPlexMono-Medium.woff2": "8c2c290cbd998fa1f647e4572aca6ebbd72589551b0f3f9f8bb8628fbb8219d5",
}


def test_vendored_plex_faces_are_the_pinned_release_with_their_licence():
    import hashlib

    fonts = WEBAPP / "static" / "vendor" / "fonts"
    assert sorted(p.name for p in fonts.glob("*.woff2")) == sorted(PLEX_FACES)
    for name, digest in PLEX_FACES.items():
        assert hashlib.sha256((fonts / name).read_bytes()).hexdigest() == digest, name
    licence = (fonts / "IBM-Plex-LICENSE.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License, Version 1.1" in licence


def test_every_font_face_points_at_a_vendored_file_and_nothing_else():
    tokens = (WEBAPP / "static" / "tokens.css").read_text(encoding="utf-8")
    urls = re.findall(r'url\("([^"]+)"\)', tokens)
    assert sorted(u.rsplit("/", 1)[-1] for u in urls) == sorted(PLEX_FACES)
    assert all(u.startswith("/static/vendor/fonts/") for u in urls)
    assert tokens.count("@font-face") == len(PLEX_FACES)
    assert "font-display: swap;" in tokens
