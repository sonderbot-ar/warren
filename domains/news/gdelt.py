"""GDELT 2.0 Global Knowledge Graph (GKG 2.1): the news source adapter (M5).

This is the only module that knows GDELT's layout (Structure Guide Decision 11, guardrail 1).
It turns a 15-minute GKG file into `ArticleRecord`s; matching, clustering and queries never see a
GDELT column. Files are listed in `masterfilelist.txt` with their size and MD5, and each is checked
before use. Layout: the GKG 2.1 codebook, tab-separated, 27 columns per row.

The point-in-time rule lives here too, because it is about when GDELT saw an article: a sighting
counts on an as-of date if GDELT processed it before 24:00 New York time on that date
(`known_by`), the same day rule as `filed_at <= as_of` for fundamentals.
"""

import hashlib
import html
import io
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

MASTER_LIST_URL = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
CASE_TZ = ZoneInfo("America/New_York")  # the case calendar, a named setting (guardrail 3)
STEP = timedelta(minutes=15)
TIMEOUT_SECONDS = 60
GKG_COLUMNS = 27
# column positions in a GKG 2.1 row
DATE, SOURCE, URL, V2THEMES, V2ORGS, V2TONE, EXTRAS = 1, 3, 4, 8, 14, 15, 26

Downloader = Callable[[str], bytes]


class GdeltError(RuntimeError):
    """A GDELT file or row can't be used as it is."""


@dataclass(frozen=True)
class MasterEntry:
    url: str
    size: int
    md5: str

    @property
    def file_ts(self) -> datetime:
        return _file_ts(self.url)


@dataclass(frozen=True)
class ArticleRecord:
    url: str
    source: str  # the publisher's domain
    seen_at: datetime  # UTC, when GDELT processed the article
    title: str | None
    title_from_url: bool  # GDELT has no page titles before about October 2019: words of the URL
    tone: float | None  # average tone, the first V2Tone value
    themes: tuple[str, ...]  # distinct, in first-seen order
    organisations: tuple[str, ...]  # distinct, as GDELT wrote them
    file_url: str


def known_by(as_of: date, tz: ZoneInfo = CASE_TZ) -> datetime:
    """The UTC instant at which `as_of` ends in the case calendar: sightings before it count."""
    return datetime.combine(as_of + timedelta(days=1), time(0), tzinfo=tz).astimezone(UTC)


def window_bounds(
    case_date: date, days: int = 7, tz: ZoneInfo = CASE_TZ
) -> tuple[datetime, datetime]:
    """[start, end) in UTC for the `days` calendar days ending on the case date."""
    start = datetime.combine(case_date - timedelta(days=days - 1), time(0), tzinfo=tz)
    return start.astimezone(UTC), known_by(case_date, tz)


def _file_ts(url: str) -> datetime:
    match = re.search(r"/(\d{14})\.gkg\.csv\.zip$", url)
    if not match:
        raise GdeltError(f"not an English GKG file: {url}")
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def parse_master_list(text: str) -> dict[datetime, MasterEntry]:
    """English GKG files by their UTC timestamp (events, mentions and translations left out)."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3 or not parts[2].endswith(".gkg.csv.zip") or ".translation." in parts[2]:
            continue
        entry = MasterEntry(url=parts[2], size=int(parts[0]), md5=parts[1].lower())
        out[entry.file_ts] = entry
    return out


def window_files(
    master: dict[datetime, MasterEntry], start: datetime, end: datetime
) -> tuple[list[MasterEntry], list[datetime]]:
    """(files in [start, end), 15-minute slots the master list has no file for)."""
    slot = start.replace(minute=start.minute - start.minute % 15, second=0, microsecond=0)
    if slot < start:
        slot += STEP
    found, missing = [], []
    while slot < end:
        (found.append(master[slot]) if slot in master else missing.append(slot))
        slot += STEP
    return found, missing


def check_md5(content: bytes, entry: MasterEntry) -> None:
    digest = hashlib.md5(content).hexdigest()  # noqa: S324 - GDELT publishes MD5, not a security use
    if digest != entry.md5:
        raise GdeltError(f"{entry.url}: MD5 {digest} does not match the master list's {entry.md5}")


def _distinct(items: Iterator[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i for i in items if i))


def _without_offsets(field: str) -> tuple[str, ...]:
    """V2Themes and V2Organizations are `name,offset;name,offset`: names kept, offsets dropped."""
    return _distinct(part.rsplit(",", 1)[0].strip() for part in field.split(";") if part.strip())


def _title(extras: str) -> str | None:
    match = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", extras, re.DOTALL)
    return html.unescape(match.group(1)).strip() or None if match else None


def url_title(url: str) -> str | None:
    """Headline words from the URL's last path part (`/microsoft-cuts-forecast-123.html`), if 3+."""
    path = re.sub(r"[?#].*$", "", url.split("://", 1)[-1]).rstrip("/")
    last = path.rsplit("/", 1)[-1] if "/" in path else ""
    last = re.sub(r"\.(s?html?|php|aspx?)$", "", last.lower())
    words = [w for w in re.split(r"[-_+]+", last) if w.isalpha()]
    return " ".join(words) if len(words) >= 3 else None


def parse_row(line: str, file_url: str) -> ArticleRecord | None:
    """One GKG 2.1 row; None for a row that isn't a web article (no URL to key it by)."""
    cols = line.rstrip("\r\n").split("\t")
    if len(cols) != GKG_COLUMNS:
        raise GdeltError(f"{file_url}: a row has {len(cols)} columns, expected {GKG_COLUMNS}")
    url = cols[URL].strip()
    if not url.startswith(("http://", "https://")):
        return None
    tone = cols[V2TONE].split(",")[0].strip()
    page_title = _title(cols[EXTRAS])
    words = None if page_title else url_title(url)
    return ArticleRecord(
        url=url,
        source=cols[SOURCE].strip().lower(),
        seen_at=datetime.strptime(cols[DATE], "%Y%m%d%H%M%S").replace(tzinfo=UTC),
        title=page_title or words,
        title_from_url=words is not None,
        tone=float(tone) if tone else None,
        themes=_without_offsets(cols[V2THEMES]),
        organisations=_without_offsets(cols[V2ORGS]),
        file_url=file_url,
    )


def read_file(content: bytes, entry: MasterEntry) -> tuple[list[ArticleRecord], int]:
    """(every article in a zipped GKG file, rows that couldn't be parsed), after the MD5 check.

    A bad row is counted and skipped, never allowed to drop the rest of the file.
    """
    check_md5(content, entry)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        [name] = archive.namelist()
        text = archive.read(name).decode("utf-8", errors="replace")
    records, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = parse_row(line, entry.url)
        except (GdeltError, ValueError):
            bad += 1
            continue
        if record is not None:
            records.append(record)
    return records, bad


def fetch_url(url: str) -> str:
    """GDELT lists its files as http://; the same paths are served over https, which is used.

    The listed URL stays the file's name in the manifest, so nothing stored changes.
    """
    return "https://" + url.removeprefix("http://") if url.startswith("http://") else url


def http_download(url: str) -> bytes:
    response = requests.get(fetch_url(url), timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content
