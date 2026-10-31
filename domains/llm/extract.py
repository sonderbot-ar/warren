"""Event extraction (M6 Step A, LLM 1): each chosen event of a case gets a type, a materiality and
an about-the-company answer per headline.

The input is built from M5's stored event run as of the case date, so only sightings known by
that date are read (`cluster.items_as_of`). Each event is classified twice: `named`, and `masked`,
where the company's names and ticker become "the Company", source domains are dropped and dates
are relative to the as-of date. Masking reduces what the model can recall about what happened
next; it does not remove it (design doc, Look-ahead).
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from domains.llm import calls
from domains.llm.client import LLMClient
from domains.llm.taxonomy import NOT_ABOUT, load_event_types
from domains.news import cluster
from domains.news.matching import AliasSet, HeadlineRule

NODE = "extract_events"
PROMPT = "extract_event"
MIN_SOURCES = 2  # a single-source event is usually one outlet's angle on a bigger story
MAX_EVENTS = 15  # per case, the largest by source count
MAX_HEADLINES = 25  # per event
VARIANTS = ("named", "masked")
Variant = Literal["named", "masked"]


class HeadlineAbout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    about: bool


class EventClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    materiality: Literal["low", "medium", "high"]
    reasons: list[str] = Field(..., min_length=1, max_length=3)
    summary: str = Field(..., min_length=1, max_length=400)
    evidence: list[str]
    headlines: list[HeadlineAbout]


@dataclass(frozen=True)
class Headline:
    id: str  # h1, h2, … in the prompt
    article_id: str
    seen_at: datetime
    source: str
    title: str


@dataclass(frozen=True)
class Company:
    cik: str
    ticker: str
    name: str


def company(conn: sqlite3.Connection, ticker: str) -> Company:
    row = conn.execute("SELECT cik, ticker, name FROM companies WHERE ticker = ?", (ticker,))
    row = row.fetchone()
    if row is None:
        raise ValueError(f"unknown ticker {ticker}")
    return Company(row["cik"], row["ticker"], row["name"])


def choose_events(events: list[dict]) -> list[dict]:
    """Events with at least `MIN_SOURCES` sources, the `MAX_EVENTS` largest, earliest on ties."""
    kept = [e for e in events if e["source_count"] >= MIN_SOURCES]
    kept.sort(key=lambda e: (-e["source_count"], e["first_seen"], e["event_id"]))
    return kept[:MAX_EVENTS]


def choose_headlines(items: list[cluster.Item]) -> list[cluster.Item]:
    """Up to `MAX_HEADLINES`: one per source first, earliest first, then the earliest rest."""
    items = sorted(items, key=lambda i: (i.seen_at, i.article_id))
    first, rest, seen = [], [], set()
    for i in items:
        (rest if i.source in seen else first).append(i)
        seen.add(i.source)
    chosen = (first + rest)[:MAX_HEADLINES]
    return sorted(chosen, key=lambda i: (i.seen_at, i.article_id))


def mask_pattern(aliases: AliasSet, co: Company) -> re.Pattern:
    """Every include or subsidiary alias, the company's name and its ticker, as whole words."""
    names = {a.alias for a in aliases.aliases if a.cik == co.cik and a.kind != "exclude"}
    names.add(" ".join(re.findall(r"[a-z0-9]+", co.name.lower())))
    names.add(co.ticker.lower())
    parts = [r"[^a-z0-9]+".join(map(re.escape, n.split())) for n in names if n]
    parts.sort(key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])", re.IGNORECASE)


def mask(title: str, pattern: re.Pattern) -> str:
    return pattern.sub("the Company", title)


def _when(seen_at: datetime, as_of: date, tz: ZoneInfo, variant: Variant) -> str:
    local = seen_at.astimezone(tz)
    if variant == "named":
        return local.strftime("%Y-%m-%d %H:%M")
    return f"day {(local.date() - as_of).days:+d} {local:%H:%M}"


def render_headlines(
    headlines: list[Headline], as_of: date, tz: ZoneInfo, variant: Variant, pattern: re.Pattern
) -> str:
    lines = []
    for h in headlines:
        when = _when(h.seen_at, as_of, tz, variant)
        if variant == "named":
            lines.append(f"{h.id} | {when} | {h.source} | {h.title}")
        else:
            lines.append(f"{h.id} | {when} | {mask(h.title, pattern)}")
    return "\n".join(lines)


def event_headlines(event: dict, items: dict[str, cluster.Item]) -> list[Headline]:
    """The event's chosen headlines, each its earliest sighting known by the run's as-of date."""
    chosen = choose_headlines([items[a] for a in event["articles"] if a in items])
    return [Headline(f"h{n}", i.article_id, i.seen_at, i.source, i.title or "")
            for n, i in enumerate(chosen, start=1)]  # fmt: skip


def checker(headlines: list[Headline], types: dict[str, str]):
    """Rules on an answer that its schema can't hold; a broken rule is an invalid answer."""
    ids = [h.id for h in headlines]

    def check(value: EventClassification) -> None:
        if value.event_type not in types:
            raise ValueError(f"event_type {value.event_type!r} is not in the taxonomy")
        answered = [h.id for h in value.headlines]
        if sorted(answered) != sorted(ids):
            raise ValueError(f"headlines must list each of {', '.join(ids)} once")
        about = {h.id for h in value.headlines if h.about}
        unknown = [e for e in value.evidence if e not in ids]
        if unknown:
            raise ValueError(f"evidence cites unknown headlines: {', '.join(unknown)}")
        if any(e not in about for e in value.evidence):
            raise ValueError("evidence cites a headline marked about = false")
        if about and value.event_type == NOT_ABOUT:
            raise ValueError(f"{NOT_ABOUT} while some headline is about the company")
        if about and not value.evidence:
            raise ValueError("evidence is empty")

    return check


def _stored(conn, event_id, variant, model, prompt_sha):
    return conn.execute(
        "SELECT * FROM event_classifications WHERE event_id = ? AND variant = ? AND model = ? "
        "AND prompt_sha256 = ?",
        (event_id, variant, model, prompt_sha),
    ).fetchone()


def event_slots(co, as_of, tz, event, items, variant, pattern, types):
    """The headlines of an event and the prompt's slots for one variant."""
    headlines = event_headlines(event, items)
    slots = {
        "types": "\n".join(f"  - {t}: {d}" for t, d in types.items()),
        "company": f"{co.name} ({co.ticker})" if variant == "named" else "the Company",
        "as_of": as_of.isoformat() if variant == "named" else "day 0",
        "headlines": render_headlines(headlines, as_of, tz, variant, pattern),
    }
    return headlines, slots


def classify_event(
    conn: sqlite3.Connection,
    client: LLMClient,
    co: Company,
    as_of: date,
    tz: ZoneInfo,
    event: dict,
    items: dict[str, cluster.Item],
    variant: Variant,
    pattern: re.Pattern,
    batch_id: str,
    budget: int = calls.DEFAULT_BUDGET,
    prompt: calls.Prompt | None = None,
    types: dict[str, str] | None = None,
) -> int:
    """Classify one event in one variant and store it; a stored `ok` answer is reused."""
    prompt = prompt or calls.latest_prompt(PROMPT)
    types = types or load_event_types()
    model = calls.node_model(NODE).model
    stored = _stored(conn, event["event_id"], variant, model, prompt.sha256)
    if stored is not None and stored["status"] == "ok":
        return stored["classification_id"]
    if stored is not None:  # a failed answer is tried again
        conn.execute("DELETE FROM event_classifications WHERE classification_id = ?",
                     (stored["classification_id"],))  # fmt: skip
    headlines, slots = event_slots(co, as_of, tz, event, items, variant, pattern, types)
    key = (event["event_id"], variant, model, prompt.sha256)
    try:
        result = calls.structured_call(
            conn, client, NODE, prompt, slots, EventClassification,
            f"{event['event_id']}:{variant}", batch_id, budget, checker(headlines, types),
        )  # fmt: skip
    except calls.LLMRejected:
        cur = conn.execute(
            "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, status) "
            "VALUES (?, ?, ?, ?, 'failed')",
            key,
        )
        conn.commit()
        return cur.lastrowid
    value: EventClassification = result.value
    by_id = {h.id: h.article_id for h in headlines}
    about = {by_id[h.id]: h.about for h in value.headlines}
    event_type = value.event_type if any(about.values()) else NOT_ABOUT
    cur = conn.execute(
        "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, call_id, "
        "status, event_type, model_event_type, materiality, reasons, summary, evidence_json, "
        "about_json) VALUES (?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?)",
        (*key, result.call_id, event_type, value.event_type, value.materiality,
         json.dumps(value.reasons), value.summary,
         json.dumps(sorted(by_id[e] for e in value.evidence)),
         json.dumps(about, sort_keys=True)),
    )  # fmt: skip
    conn.commit()
    return cur.lastrowid


def classify_case(
    conn: sqlite3.Connection,
    client: LLMClient,
    case_id: str,
    ticker: str,
    as_of: date,
    aliases: AliasSet,
    rule: HeadlineRule,
    variants: tuple[str, ...] = VARIANTS,
    batch_id: str = "classify",
    budget: int = calls.DEFAULT_BUDGET,
    tz: ZoneInfo = cluster.CASE_TZ,
) -> dict[str, list[int]]:
    """Classify a case's chosen events in each variant; returns classification ids per variant."""
    co = company(conn, ticker)
    run_id = cluster.run_events(conn, co.cik, as_of, aliases, tz, rule=rule)
    events = cluster.stored_events(conn, run_id)
    chosen = choose_events(events)
    items = {i.article_id: i for i in cluster.items_as_of(conn, co.cik, as_of, tz, rule)}
    pattern = mask_pattern(aliases, co)
    prompt, types = calls.latest_prompt(PROMPT), load_event_types()
    out: dict[str, list[int]] = {}
    for variant in variants:
        conn.execute(
            "INSERT OR REPLACE INTO case_llm_status (case_id, event_run_id, variant, events_total, "
            "events_chosen) VALUES (?, ?, ?, ?, ?)",
            (case_id, run_id, variant, len(events), len(chosen)),
        )
        conn.commit()
        out[variant] = [
            classify_event(
                conn,
                client,
                co,
                as_of,
                tz,
                e,
                items,
                variant,
                pattern,
                batch_id,
                budget,
                prompt,
                types,
            )  # fmt: skip
            for e in chosen
        ]
    return out


# -- stability (M6 Step 8) ------------------------------------------------------------------------

STABILITY_CASES = 10  # the first ten cases by case id that have a chosen event
STABILITY_RUNS = 3
STABILITY_PASS = 9  # of 10 events with the same type in all three runs


@dataclass(frozen=True)
class Stability:
    case_id: str
    event_id: str
    types: tuple[str, ...]  # one per run; "failed" when a run gave no valid answer

    @property
    def same(self) -> bool:
        return "failed" not in self.types and len(set(self.types)) == 1


def stability(
    conn: sqlite3.Connection,
    client: LLMClient,
    cases: list,
    aliases: AliasSet,
    rule: HeadlineRule,
    batch_id: str,
    budget: int = calls.DEFAULT_BUDGET,
    tz: ZoneInfo = cluster.CASE_TZ,
) -> list[Stability]:
    """The largest event of each of the first ten cases that have one, classified three times
    (named variant). Answers are logged as calls, never stored as classifications.

    Current models take no temperature setting, so the runs use the model's default sampling: a
    harder test than the temperature 0 the design first planned."""
    prompt, types = calls.latest_prompt(PROMPT), load_event_types()
    out = []
    for case in sorted(cases, key=lambda c: c.case_id):
        if len(out) == STABILITY_CASES:
            break
        co = company(conn, case.ticker)
        run_id = cluster.run_events(conn, co.cik, case.event_date, aliases, tz, rule=rule)
        chosen = choose_events(cluster.stored_events(conn, run_id))
        if not chosen:
            continue
        event = chosen[0]
        items = {i.article_id: i for i in cluster.items_as_of(conn, co.cik, case.event_date, tz,
                                                              rule)}  # fmt: skip
        pattern = mask_pattern(aliases, co)
        headlines, slots = event_slots(co, case.event_date, tz, event, items, "named", pattern,
                                       types)  # fmt: skip
        found = []
        for k in range(1, STABILITY_RUNS + 1):
            try:
                result = calls.structured_call(
                    conn, client, NODE, prompt, slots, EventClassification,
                    f"{event['event_id']}:stability:{k}", batch_id, budget,
                    checker(headlines, types),
                )  # fmt: skip
                found.append(result.value.event_type)
            except calls.LLMRejected:
                found.append("failed")
        out.append(Stability(case.case_id, event["event_id"], tuple(found)))
    return out
