"""Ingesting GDELT files into SQLite (M5): the manifest, sightings and company matches.

A file is read once per alias set. Every Phase 1 company is matched on every pass, whatever case
asked for the file, so overlapping windows share files without losing rows. A file missing from
the master list or gone from the server is `missing` (GDELT's gap); one we failed to download is
`fetch_error` (ours, read again on the next run); one failing its MD5 is `bad_md5`. None is
skipped in silence. A file matched under an older alias set is read again and its rows replaced.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests

from domains.news import gdelt
from domains.news.gdelt import CASE_TZ, ArticleRecord, FileGone, GdeltError, MasterEntry
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
    status: str  # ok | missing | fetch_error | bad_md5 | skipped (read under this alias set)
    rows_total: int = 0
    rows_kept: int = 0
    rows_bad: int = 0


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
        # a subsidiary's start date is read in the case calendar, like every as-of date
        # titles made from URL words help clustering but don't match companies on their own
        page_title = None if r.title_from_url else r.title
        found = match(r.organisations, page_title, r.seen_at.astimezone(CASE_TZ).date(), aliases)
        if not found:
            continue
        aid = article_id(r.url)
        conn.execute(
            "INSERT INTO articles (article_id, url, source) VALUES (?, ?, ?) "
            "ON CONFLICT (article_id) DO NOTHING",
            (aid, r.url, r.source),
        )
        inserted = conn.execute(
            "INSERT INTO article_sightings (article_id, file_url, seen_at, title, title_from_url, "
            "tone, themes_json, orgs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (article_id, file_url) DO NOTHING",
            (aid, r.file_url, iso(r.seen_at), r.title, int(r.title_from_url), r.tone,
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


DOWNLOAD_WORKERS = 8  # GDELT files are fetched in parallel; a case window is ~670 files


def ingest_file(
    conn: sqlite3.Connection,
    entry: MasterEntry,
    aliases: AliasSet,
    download: gdelt.Downloader | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FileResult:
    """Read one file unless it was read under this alias set already. One transaction."""
    row = _file_row(conn, entry.url)
    if not _needs_read(row, aliases):
        return FileResult(entry.url, "skipped")
    content, failed = None, None
    try:
        content = (download or gdelt.http_download)(entry.url)
    except FileGone:
        failed = "missing"
    except requests.RequestException:
        failed = "fetch_error"
    if failed and row is not None and row["status"] == "ok":
        # read fine before, unreachable now: keep its rows; it stays stale for the next rematch
        return FileResult(entry.url, failed)
    with conn:
        _clear_file(conn, entry.url)
        if failed:
            _record_file(conn, entry.url, entry.file_ts, entry.md5, failed, None, None,
                         aliases, now())  # fmt: skip
            return FileResult(entry.url, failed)
        try:
            records, bad = gdelt.read_file(content, entry)
        except GdeltError:
            _record_file(conn, entry.url, entry.file_ts, entry.md5, "bad_md5", None, None,
                         aliases, now())  # fmt: skip
            return FileResult(entry.url, "bad_md5")
        _record_file(conn, entry.url, entry.file_ts, entry.md5, "ok", len(records), 0,
                     aliases, now())  # fmt: skip
        kept = store_records(conn, records, aliases)
        conn.execute(
            "UPDATE news_files SET rows_kept = ?, rows_bad = ? WHERE file_url = ?",
            (kept, bad, entry.url),
        )
    return FileResult(entry.url, "ok", len(records), kept, bad)


def _file_row(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT status, aliases_sha256 FROM news_files WHERE file_url = ?", (url,)
    ).fetchone()


def _needs_read(row: sqlite3.Row | None, aliases: AliasSet) -> bool:
    return row is None or row["status"] != "ok" or row["aliases_sha256"] != aliases.sha256


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
    download: gdelt.Downloader | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    workers: int = DOWNLOAD_WORKERS,
) -> list[FileResult]:
    """Files are downloaded `workers` at a time; the database is written here, in file order.

    Downloads run a chunk at a time so at most `workers` files sit in memory, and a file
    already read under this alias set is never downloaded again (a stopped run resumes).
    """
    found, missing = gdelt.window_files(master, start, end)
    fetch = download or gdelt.http_download
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(found), workers):
            chunk = found[i : i + workers]
            futures = {e.url: pool.submit(fetch, e.url) for e in chunk
                       if _needs_read(_file_row(conn, e.url), aliases)}  # fmt: skip
            for e in chunk:
                future = futures.get(e.url)
                got = (lambda _, f=future: f.result()) if future else fetch
                results.append(ingest_file(conn, e, aliases, got, now))
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
