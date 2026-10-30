"""Ingesting GDELT files into SQLite (M5): the manifest, sightings and company matches.

A file is read once per alias set. Every Phase 1 company is matched on every pass, whatever case
asked for the file, so overlapping windows share files without losing rows. A file missing from
the master list, gone from the server, or failing its MD5 is recorded with that status, never
skipped in silence. A file matched under an older alias set is read again and its rows replaced.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests

from domains.news import gdelt
from domains.news.gdelt import ArticleRecord, GdeltError, MasterEntry
from domains.news.matching import AliasSet, match

FILE_URL = "http://data.gdeltproject.org/gdeltv2/{ts:%Y%m%d%H%M%S}.gkg.csv.zip"
TRACKING = re.compile(r"^(utm_.*|fbclid|ocid|gclid)$")


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise_url(url: str) -> str:
    """Scheme, `www.`, tracking parameters and the fragment dropped; the rest kept as written."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k)])
    return host + parts.path + (f"?{query}" if query else "")


def article_id(url: str) -> str:
    return hashlib.sha256(normalise_url(url).encode()).hexdigest()


@dataclass(frozen=True)
class FileResult:
    file_url: str
    status: str  # ok | missing | bad_md5 | skipped (already read under this alias set)
    rows_total: int = 0
    rows_kept: int = 0


def _record_file(conn, url, ts, md5, status, total, kept, aliases: AliasSet, now) -> None:
    conn.execute(
        "INSERT INTO news_files (file_url, file_ts, md5, status, rows_total, rows_kept, "
        "aliases_sha256, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (file_url) DO UPDATE SET md5 = excluded.md5, status = excluded.status, "
        "rows_total = excluded.rows_total, rows_kept = excluded.rows_kept, "
        "aliases_sha256 = excluded.aliases_sha256, fetched_at = excluded.fetched_at",
        (url, iso(ts), md5, status, total, kept, aliases.sha256, iso(now)),
    )


def _clear_file(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("DELETE FROM article_companies WHERE file_url = ?", (url,))
    conn.execute("DELETE FROM article_sightings WHERE file_url = ?", (url,))


def store_records(conn: sqlite3.Connection, records: list[ArticleRecord], aliases: AliasSet) -> int:
    """Sightings of the records that match a company, with their matches; returns rows kept."""
    kept = 0
    for r in records:
        found = match(r.organisations, r.title, r.seen_at.date(), aliases)
        if not found:
            continue
        aid = article_id(r.url)
        conn.execute(
            "INSERT INTO articles (article_id, url, source) VALUES (?, ?, ?) "
            "ON CONFLICT (article_id) DO NOTHING",
            (aid, r.url, r.source),
        )
        inserted = conn.execute(
            "INSERT INTO article_sightings (article_id, file_url, seen_at, title, tone, "
            "themes_json, orgs_json) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (article_id, file_url) DO NOTHING",
            (aid, r.file_url, iso(r.seen_at), r.title, r.tone,
             json.dumps(r.themes), json.dumps(r.organisations)),
        ).rowcount  # fmt: skip
        if not inserted:  # the same URL twice in one file: the first row stands
            continue
        conn.executemany(
            "INSERT INTO article_companies (article_id, file_url, cik, method) VALUES (?, ?, ?, ?)",
            [(aid, r.file_url, cik, method) for cik, method in sorted(found.items())],
        )
        kept += 1
    return kept


def ingest_file(
    conn: sqlite3.Connection,
    entry: MasterEntry,
    aliases: AliasSet,
    download: gdelt.Downloader = gdelt.http_download,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FileResult:
    """Read one file unless it was read under this alias set already. One transaction."""
    row = conn.execute(
        "SELECT status, aliases_sha256 FROM news_files WHERE file_url = ?", (entry.url,)
    ).fetchone()
    if row is not None and row["status"] == "ok" and row["aliases_sha256"] == aliases.sha256:
        return FileResult(entry.url, "skipped")
    try:
        content = download(entry.url)
    except requests.HTTPError:
        content = None
    with conn:
        _clear_file(conn, entry.url)
        if content is None:
            _record_file(conn, entry.url, entry.file_ts, entry.md5, "missing", None, None,
                         aliases, now())  # fmt: skip
            return FileResult(entry.url, "missing")
        try:
            records = list(gdelt.read_file(content, entry))
        except GdeltError:
            _record_file(conn, entry.url, entry.file_ts, entry.md5, "bad_md5", None, None,
                         aliases, now())  # fmt: skip
            return FileResult(entry.url, "bad_md5")
        _record_file(conn, entry.url, entry.file_ts, entry.md5, "ok", len(records), 0,
                     aliases, now())  # fmt: skip
        kept = store_records(conn, records, aliases)
        conn.execute("UPDATE news_files SET rows_kept = ? WHERE file_url = ?", (kept, entry.url))
    return FileResult(entry.url, "ok", len(records), kept)


def record_missing_slot(
    conn: sqlite3.Connection, ts: datetime, aliases: AliasSet, now: datetime
) -> FileResult:
    """A 15-minute slot the master list has no file for."""
    url = FILE_URL.format(ts=ts)
    with conn:
        _record_file(conn, url, ts, None, "missing", None, None, aliases, now)
    return FileResult(url, "missing")


def ingest_window(
    conn: sqlite3.Connection,
    master: dict[datetime, MasterEntry],
    start: datetime,
    end: datetime,
    aliases: AliasSet,
    download: gdelt.Downloader = gdelt.http_download,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[FileResult]:
    found, missing = gdelt.window_files(master, start, end)
    results = [ingest_file(conn, e, aliases, download, now) for e in found]
    return results + [record_missing_slot(conn, ts, aliases, now()) for ts in missing]


def stale_files(conn: sqlite3.Connection, aliases: AliasSet) -> list[str]:
    """Files read under another alias set: `rematch` reads them again."""
    return [
        r["file_url"]
        for r in conn.execute(
            "SELECT file_url FROM news_files WHERE status = 'ok' AND aliases_sha256 != ? "
            "ORDER BY file_url",
            (aliases.sha256,),
        )
    ]
