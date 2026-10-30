"""Which Phase 1 company an article is about (M5): aliases as data, one rule, no model.

Aliases come from two places: the EDGAR names stored in `companies.aliases_json` and the
hand-kept `aliases.csv` (common names, consolidated subsidiaries, and exclusions for different
companies that share words). Every alias is normalised the same way as the text it is compared
with. Methods, strongest first:

1. `org_exact`: a GDELT organisation equals an include alias.
2. `org_subsidiary`: it equals a subsidiary alias in force on the sighting's date.
3. `title_alias`: no organisation matched, and the title contains an include alias as a whole
   phrase once every exclude phrase in it is masked ("Apple Daily" is not Apple).

An exclusion acts on the string it names, never on the article: a Coca-Cola story that mentions
Coca-Cola FEMSA still matches Coca-Cola.

A match says the company is mentioned, not that the article is about it. The headline rule
(`about_headline`, Step 6) decides which matched articles feed events: the headline names the
company and isn't boilerplate (a holdings notice, a market wrap, a shopping list, a research
listing). It reads stored titles, so it never changes a match and never re-reads a file.
"""

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ALIASES_PATH = Path(__file__).parent / "aliases.csv"
HEADLINES_PATH = Path(__file__).parent / "headlines.csv"
HEADLINE_EXCLUDES_PATH = Path(__file__).parent / "headline_excludes.txt"
HEADLINE_RULE_VERSION = 1  # part of the rule's hash: change it when `about_headline` changes
MIN_ALIAS_LENGTH = 4  # keeps `pg`, `ko`, `cat` out: they are common words
LEGAL_SUFFIXES = {"inc", "corp", "corporation", "co", "company", "ltd", "plc", "et", "al"}
METHODS = ("org_exact", "org_subsidiary", "title_alias")  # strongest first


class AliasError(ValueError):
    """The alias file can't be used as it is."""


def normalise(text: str) -> str:
    """Lowercase; `&` is `and`; punctuation a space; legal suffixes and a leading `the` off."""
    words = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    if words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


@dataclass(frozen=True)
class Alias:
    cik: str
    alias: str  # normalised
    kind: str  # include | subsidiary | exclude
    start: date | None = None  # a subsidiary counts from this date


@dataclass(frozen=True)
class AliasSet:
    aliases: tuple[Alias, ...]
    sha256: str  # changes when any alias changes: files matched under another set are re-read

    def of_kind(self, kind: str) -> list[Alias]:
        return [a for a in self.aliases if a.kind == kind]


def load_aliases(conn: sqlite3.Connection, path: Path = ALIASES_PATH) -> AliasSet:
    ciks = {r["ticker"]: r["cik"] for r in conn.execute("SELECT ticker, cik FROM companies")}
    out: dict[tuple[str, str, str], Alias] = {}
    for row in conn.execute("SELECT cik, aliases_json FROM companies ORDER BY cik"):
        for name in json.loads(row["aliases_json"]):
            alias = normalise(name)
            if len(alias) >= MIN_ALIAS_LENGTH:
                out[(row["cik"], alias, "include")] = Alias(row["cik"], alias, "include")
    with open(path, newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            ticker, kind = row["ticker"].strip(), row["kind"].strip()
            alias = normalise(row["alias"])
            if ticker not in ciks:
                raise AliasError(f"{path.name} line {line}: {ticker} is not an ingested company")
            if kind not in ("include", "subsidiary", "exclude"):
                raise AliasError(f"{path.name} line {line}: unknown kind {kind!r}")
            if len(alias) < MIN_ALIAS_LENGTH:
                raise AliasError(f"{path.name} line {line}: {alias!r} is too short to match safely")
            start = date.fromisoformat(row["from"]) if row["from"].strip() else None
            out[(ciks[ticker], alias, kind)] = Alias(ciks[ticker], alias, kind, start)
    aliases = tuple(sorted(out.values(), key=lambda a: (a.cik, a.kind, a.alias)))
    digest = hashlib.sha256(
        json.dumps([[a.cik, a.alias, a.kind, str(a.start)] for a in aliases]).encode()
    ).hexdigest()
    return AliasSet(aliases, digest)


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def match(
    organisations: tuple[str, ...], title: str | None, seen_on: date, aliases: AliasSet
) -> dict[str, str]:
    """{cik: strongest method} for one sighting."""
    found: dict[str, str] = {}

    def add(cik: str, method: str) -> None:
        if cik not in found or METHODS.index(method) < METHODS.index(found[cik]):
            found[cik] = method

    orgs = {normalise(o) for o in organisations}
    for a in aliases.of_kind("include"):
        if a.alias in orgs:
            add(a.cik, "org_exact")
    for a in aliases.of_kind("subsidiary"):
        if a.alias in orgs and (a.start is None or seen_on >= a.start):
            add(a.cik, "org_subsidiary")
    if title:
        text = normalise(title)
        for a in aliases.of_kind("exclude"):
            text = re.sub(rf"(?<![a-z0-9]){re.escape(a.alias)}(?![a-z0-9])", " ", text)
        for a in aliases.of_kind("include"):
            if a.cik not in found and _contains(text, a.alias):
                add(a.cik, "title_alias")
    return found


@dataclass(frozen=True)
class HeadlineRule:
    names: dict[str, tuple[tuple[str, date | None], ...]]  # cik: (name, counts from)
    excludes: tuple[str, ...]
    sha256: str  # stored with each event run, so a changed rule can't pass as the same run


def load_headline_rule(
    conn: sqlite3.Connection,
    aliases: AliasSet,
    path: Path = HEADLINES_PATH,
    excludes_path: Path = HEADLINE_EXCLUDES_PATH,
) -> HeadlineRule:
    """Each company's headline names (include and subsidiary aliases, short forms) and the
    boilerplate phrases."""
    ciks = {r["ticker"]: r["cik"] for r in conn.execute("SELECT ticker, cik FROM companies")}
    names: dict[str, set[tuple[str, date | None]]] = {}
    for a in aliases.aliases:
        if a.kind in ("include", "subsidiary"):
            names.setdefault(a.cik, set()).add((a.alias, a.start))
    with open(path, newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            ticker, name = row["ticker"].strip(), normalise(row["name"])
            if ticker not in ciks:
                raise AliasError(f"{path.name} line {line}: {ticker} is not an ingested company")
            if len(name) < 2:
                raise AliasError(f"{path.name} line {line}: {name!r} is too short")
            names.setdefault(ciks[ticker], set()).add((name, None))
    excludes = sorted(
        {
            normalise(line)
            for line in excludes_path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        - {""}
    )
    frozen = {cik: tuple(sorted(v, key=lambda n: (n[0], str(n[1])))) for cik, v in names.items()}
    digest = hashlib.sha256(
        json.dumps(
            [HEADLINE_RULE_VERSION, aliases.sha256, excludes,
             sorted([cik, n, str(d)] for cik, v in frozen.items() for n, d in v)]
        ).encode()
    ).hexdigest()  # fmt: skip
    return HeadlineRule(frozen, tuple(excludes), digest)


def about_headline(rule: HeadlineRule, cik: str, title: str | None, seen_on: date) -> bool:
    """The headline names the company (an `s` may follow: possessives, URL plurals) and isn't
    boilerplate. An article with no headline fails."""
    text = normalise(title or "")
    if not text or any(_contains(text, phrase) for phrase in rule.excludes):
        return False
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(name)}s?(?![a-z0-9])", text)
        for name, start in rule.names.get(cik, ())
        if start is None or seen_on >= start
    )
