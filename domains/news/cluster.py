"""Grouping a company's articles into events, as of a date (M5).

Single-pass clustering from Topic Detection and Tracking (Allan, Papka & Lavrenko 1998): articles
are read in the order GDELT saw them, and each joins the open event it is most similar to, or
starts a new one. Similarity is Jaccard on title words; shared themes help only alongside some
title overlap, so a busy week can't chain into one event. Only sightings known by the as-of date
are read, and an article is its earliest such sighting, with that sighting's own title.

An event run stores its parameters and a hash of the sightings it read, so `rebuild` can cluster
the same stored sightings again and check every event, the news analogue of reproducing a run
to the cent.
"""

import hashlib
import json
import re
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from domains.analysis.runs import code_version
from domains.news.gdelt import CASE_TZ, known_by
from domains.news.matching import AliasSet
from domains.news.store import iso

STOPWORDS = frozenset(
    line.strip()
    for line in (Path(__file__).parent / "stopwords.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)
GENERIC_THEME_PREFIXES = (
    "TAX_", "WB_", "GENERAL_", "EPU_", "USPEC_", "CRISISLEX_", "UNGP_", "SOC_", "MANMADE_",
    "ECON_STOCKMARKET",
)  # fmt: skip
PARAMS = {"window_hours": 48, "title_jaccard": 0.30, "joint_jaccard": 0.15, "shared_themes": 3}
SEED_ARTICLES = 5  # an event's words and themes come from its first five articles


@dataclass(frozen=True)
class Item:
    article_id: str
    file_url: str
    source: str
    seen_at: datetime
    title: str | None
    tone: float | None
    themes: frozenset[str]


@dataclass
class Event:
    items: list[Item] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    themes: set[str] = field(default_factory=set)
    joined_by_themes: int = 0  # joins that needed the theme branch (reported in Step 5)

    @property
    def last_seen(self) -> datetime:
        return self.items[-1].seen_at


def tokens(title: str | None, company_words: frozenset[str]) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in STOPWORDS and w not in company_words}


def specific_themes(themes: list[str]) -> frozenset[str]:
    return frozenset(t for t in themes if not t.startswith(GENERIC_THEME_PREFIXES))


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def company_words(aliases: AliasSet, cik: str) -> frozenset[str]:
    return frozenset(
        w for a in aliases.aliases if a.cik == cik and a.kind != "exclude" for w in a.alias.split()
    )


def items_as_of(
    conn: sqlite3.Connection, cik: str, as_of: date, tz: ZoneInfo = CASE_TZ
) -> list[Item]:
    """Each article matched to the company, as its earliest sighting known by `as_of`."""
    rows = conn.execute(
        """
        SELECT s.article_id, s.file_url, a.source, s.seen_at, s.title, s.tone, s.themes_json
        FROM article_sightings s
        JOIN articles a USING (article_id)
        JOIN article_companies c ON c.article_id = s.article_id AND c.file_url = s.file_url
        WHERE c.cik = ? AND s.seen_at < ?
        ORDER BY s.article_id, s.seen_at, s.file_url
        """,
        (cik, iso(known_by(as_of, tz))),
    )
    earliest: dict[str, Item] = {}
    for r in rows:
        if r["article_id"] not in earliest:
            earliest[r["article_id"]] = Item(
                r["article_id"], r["file_url"], r["source"],
                datetime.fromisoformat(r["seen_at"]), r["title"], r["tone"],
                specific_themes(json.loads(r["themes_json"])),
            )  # fmt: skip
    return sorted(earliest.values(), key=lambda i: (i.seen_at, i.article_id))


def cluster(items: list[Item], words: frozenset[str], params: dict = PARAMS) -> list[Event]:
    events: list[Event] = []
    window = timedelta(hours=params["window_hours"])
    for item in sorted(items, key=lambda i: (i.seen_at, i.article_id)):
        mine = tokens(item.title, words)
        best, best_score, by_themes = None, -1.0, False
        for event in events:
            if item.seen_at - event.last_seen > window:
                continue
            score = jaccard(mine, event.tokens)
            joins = score >= params["title_jaccard"]
            themed = (
                not joins
                and score >= params["joint_jaccard"]
                and len(item.themes & event.themes) >= params["shared_themes"]
            )
            if (joins or themed) and score > best_score:
                best, best_score, by_themes = event, score, themed
        if best is None:
            best = Event()
            events.append(best)
        elif by_themes:
            best.joined_by_themes += 1
        best.items.append(item)
        if len(best.items) <= SEED_ARTICLES:
            best.tokens |= mine
            best.themes |= item.themes
    return events


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def input_sha256(items: list[Item]) -> str:
    rows = sorted([i.article_id, i.file_url, iso(i.seen_at)] for i in items)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def describe(event: Event, cik: str, as_of: date) -> dict:
    """The stored fields of an event."""
    first = event.items[0]
    by_domain = Counter(i.source for i in event.items)
    top = min(by_domain, key=lambda d: (-by_domain[d], d))
    tones = [i.tone for i in event.items if i.tone is not None]
    return {
        "event_id": _sha(cik, as_of.isoformat(), first.article_id),
        "first_seen": iso(first.seen_at),
        "last_seen": iso(event.last_seen),
        "article_count": len(event.items),
        "source_count": len(by_domain),
        "label": next(i.title for i in event.items if i.source == top),
        "themes_json": json.dumps(sorted(event.themes)),
        "median_tone": statistics.median(tones) if tones else None,
        "articles": sorted(i.article_id for i in event.items),
    }


def run_events(
    conn: sqlite3.Connection,
    cik: str,
    as_of: date,
    aliases: AliasSet,
    tz: ZoneInfo = CASE_TZ,
    params: dict = PARAMS,
) -> str:
    """Cluster as of a date and store the run; the same input returns the stored run."""
    items = items_as_of(conn, cik, as_of, tz)
    digest = input_sha256(items)
    # the alias set decides which words are dropped from titles, so it is part of the run
    params_json = json.dumps(params | {"aliases_sha256": aliases.sha256}, sort_keys=True)
    run_id = _sha(cik, as_of.isoformat(), str(tz), params_json, digest)
    if conn.execute("SELECT 1 FROM event_runs WHERE event_run_id = ?", (run_id,)).fetchone():
        return run_id
    events = [describe(e, cik, as_of) for e in cluster(items, company_words(aliases, cik), params)]
    with conn:
        conn.execute(
            "INSERT INTO event_runs (event_run_id, cik, as_of, tz, params_json, input_sha256, "
            "code_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, cik, as_of.isoformat(), str(tz), params_json, digest, code_version()),
        )
        for e in events:
            conn.execute(
                "INSERT INTO events (event_id, event_run_id, cik, first_seen, last_seen, "
                "article_count, source_count, label, themes_json, median_tone) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{e['event_id']}:{run_id[:12]}", run_id, cik, e["first_seen"], e["last_seen"],
                 e["article_count"], e["source_count"], e["label"], e["themes_json"],
                 e["median_tone"]),
            )  # fmt: skip
            conn.executemany(
                "INSERT INTO event_articles (event_id, article_id) VALUES (?, ?)",
                [(f"{e['event_id']}:{run_id[:12]}", a) for a in e["articles"]],
            )
    return run_id


def stored_events(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    out = []
    for r in conn.execute(
        "SELECT * FROM events WHERE event_run_id = ? ORDER BY first_seen, event_id", (run_id,)
    ):
        articles = [
            a[0]
            for a in conn.execute(
                "SELECT article_id FROM event_articles WHERE event_id = ? ORDER BY article_id",
                (r["event_id"],),
            )
        ]
        out.append({k: r[k] for k in r.keys()} | {"articles": articles})
    return out


def rebuild(conn: sqlite3.Connection, run_id: str, aliases: AliasSet) -> list[str]:
    """Differences between a stored run and clustering its sightings again; empty means equal."""
    run = conn.execute("SELECT * FROM event_runs WHERE event_run_id = ?", (run_id,)).fetchone()
    if run is None:
        return [f"no event run {run_id}"]
    as_of, tz = date.fromisoformat(run["as_of"]), ZoneInfo(run["tz"])
    items = items_as_of(conn, run["cik"], as_of, tz)
    if input_sha256(items) != run["input_sha256"]:
        return ["input changed: the stored sightings known by the as-of date are not the same"]
    params = json.loads(run["params_json"])
    if params.get("aliases_sha256") != aliases.sha256:
        return ["aliases changed: the run used another alias set"]
    fresh = [
        describe(e, run["cik"], as_of)
        for e in cluster(items, company_words(aliases, run["cik"]), params)
    ]
    stored = stored_events(conn, run_id)
    fields = ("first_seen", "last_seen", "article_count", "source_count", "label", "themes_json",
              "median_tone", "articles")  # fmt: skip
    problems = []
    fresh_by_id = {f"{e['event_id']}:{run_id[:12]}": e for e in fresh}
    if set(fresh_by_id) != {s["event_id"] for s in stored}:
        problems.append("result changed: the events are not the same")
    for s in stored:
        e = fresh_by_id.get(s["event_id"])
        if e is not None:
            problems += [f"result changed: {s['event_id']} {f}" for f in fields if e[f] != s[f]]
    return problems


def search(
    conn: sqlite3.Connection, query: str, as_of: date, cik: str | None = None, tz=CASE_TZ
) -> list[sqlite3.Row]:
    """Full-text search over titles known by `as_of`: one row per article, its earliest match."""
    sql = (
        "SELECT s.article_id, MIN(s.seen_at) AS seen_at, s.title FROM sightings_fts f "
        "JOIN article_sightings s ON s.sighting_id = f.rowid "
        "WHERE sightings_fts MATCH ? AND s.seen_at < ?"
    )
    args: list = [query, iso(known_by(as_of, tz))]
    if cik is not None:
        sql += (
            " AND EXISTS (SELECT 1 FROM article_companies c WHERE c.article_id = s.article_id "
            "AND c.file_url = s.file_url AND c.cik = ?)"
        )
        args.append(cik)
    return conn.execute(
        sql + " GROUP BY s.article_id ORDER BY seen_at, s.article_id", args
    ).fetchall()
