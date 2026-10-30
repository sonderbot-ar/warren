"""The GDELT GKG 2.1 adapter and the point-in-time cut-off (M5 Step 1)."""

import hashlib
import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import requests

from domains.news import gdelt
from domains.news.gdelt import GdeltError, MasterEntry

FIXTURES = Path(__file__).parent / "fixtures"
GKG = FIXTURES / "20220602150000.gkg.csv"
FILE_URL = "http://data.gdeltproject.org/gdeltv2/20220602150000.gkg.csv.zip"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def zipped(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("20220602150000.gkg.csv", text)
    return buffer.getvalue()


def entry_for(content: bytes) -> MasterEntry:
    return MasterEntry(FILE_URL, len(content), hashlib.md5(content).hexdigest())  # noqa: S324


def test_a_row_becomes_an_article_record():
    first = GKG.read_text().splitlines()[0]
    record = gdelt.parse_row(first, FILE_URL)
    assert record.url == "https://www.reuters.com/technology/microsoft-cuts-forecast-2022-06-02/"
    assert record.source == "reuters.com"
    assert record.seen_at == utc(2022, 6, 2, 15)
    assert record.title == "Microsoft cuts quarterly forecast on strong dollar & FX"
    assert record.tone == pytest.approx(-2.31)
    # offsets dropped, repeats removed, order kept
    assert record.themes == (
        "ECON_CURRENCY",
        "TAX_FNCACT_ANALYST",
        "WB_1104_MACROECONOMIC_VULNERABILITY_AND_DEBT",
    )
    assert record.organisations == ("microsoft corp", "federal reserve")


def test_a_row_without_a_url_is_skipped_and_a_short_row_refused():
    lines = GKG.read_text().splitlines()
    assert gdelt.parse_row(lines[2], FILE_URL) is None
    with pytest.raises(GdeltError, match="columns"):
        gdelt.parse_row("a\tb\tc", FILE_URL)


def test_a_file_is_read_only_when_its_md5_matches():
    content = zipped(GKG.read_text())
    records, bad = gdelt.read_file(content, entry_for(content))
    assert [r.source for r in records] == ["reuters.com", "example.com"] and bad == 0
    wrong = MasterEntry(FILE_URL, len(content), "0" * 32)
    with pytest.raises(GdeltError, match="MD5"):
        gdelt.read_file(content, wrong)


def test_a_bad_row_is_counted_and_the_rest_of_the_file_kept():
    lines = GKG.read_text().splitlines()
    broken = lines[0].replace("\t20220602150000\t", "\t2022-06-02\t", 1)  # bad DATE
    content = zipped("\n".join([broken, "short\trow", lines[1]]) + "\n")
    records, bad = gdelt.read_file(content, entry_for(content))
    assert [r.source for r in records] == ["example.com"] and bad == 2


def test_the_master_list_keeps_english_gkg_files_only():
    master = gdelt.parse_master_list((FIXTURES / "masterfilelist.txt").read_text())
    assert sorted(master) == [utc(2022, 6, 2, 15), utc(2022, 6, 2, 15, 15), utc(2022, 6, 2, 15, 45)]
    assert master[utc(2022, 6, 2, 15)].md5 == "a" * 32


def test_a_missing_slot_is_reported_not_skipped():
    master = gdelt.parse_master_list((FIXTURES / "masterfilelist.txt").read_text())
    found, missing = gdelt.window_files(master, utc(2022, 6, 2, 15), utc(2022, 6, 2, 16))
    times = [utc(2022, 6, 2, 15), utc(2022, 6, 2, 15, 15), utc(2022, 6, 2, 15, 45)]
    assert [e.file_ts for e in found] == times
    assert missing == [utc(2022, 6, 2, 15, 30)]


@pytest.mark.parametrize(
    ("as_of", "cutoff"),
    [
        (date(2022, 6, 2), utc(2022, 6, 3, 4)),  # summer: New York is UTC−4
        (date(2022, 1, 18), utc(2022, 1, 19, 5)),  # winter: UTC−5
    ],
)
def test_known_by_is_the_end_of_the_day_in_new_york(as_of, cutoff):
    assert gdelt.known_by(as_of) == cutoff


def test_a_sighting_late_in_the_new_york_evening_counts_and_the_next_morning_does_not():
    cutoff = gdelt.known_by(date(2022, 6, 2))
    assert utc(2022, 6, 3, 1) < cutoff  # 21:00 on jun.02 in New York
    assert not utc(2022, 6, 3, 4) < cutoff  # 00:00 on jun.03 in New York


def test_the_window_covers_seven_new_york_days_including_the_next_utc_morning():
    start, end = gdelt.window_bounds(date(2022, 6, 2))
    assert start == utc(2022, 5, 27, 4) and end == utc(2022, 6, 3, 4)
    master = {
        start + i * gdelt.STEP: MasterEntry(f"x/{i}.gkg.csv.zip", 1, "0" * 32)
        for i in range(-4, 7 * 96 + 4)
    }
    found, missing = gdelt.window_files(master, start, end)
    assert len(found) == 7 * 96 and not missing
    assert found[-1].url == f"x/{7 * 96 - 1}.gkg.csv.zip"  # 03:45 UTC on jun.03
    assert end - start == timedelta(days=7)


def test_files_listed_as_http_are_fetched_over_https():
    assert gdelt.fetch_url(FILE_URL) == FILE_URL.replace("http://", "https://")
    assert gdelt.fetch_url("https://x.org/a") == "https://x.org/a"


def test_without_a_page_title_the_url_gives_the_headline_words():
    assert (
        gdelt.url_title(
            "https://www.reuters.com/business/microsoft-cuts-revenue-forecast-2022-06-02/"
        )
        == "microsoft cuts revenue forecast"
    )  # noqa: E501
    assert gdelt.url_title("https://x.com/story.php?id=7") is None  # too few words
    line = GKG.read_text().splitlines()[0]
    no_title = line.rsplit("\t", 1)[0] + "\t"
    record = gdelt.parse_row(no_title, FILE_URL)
    assert record.title == "microsoft cuts forecast" and record.title_from_url
    cols = no_title.split("\t")
    cols[gdelt.URL] = "https://x.com/story.php?id=7"
    bare = gdelt.parse_row("\t".join(cols), FILE_URL)
    assert bare.title is None and not bare.title_from_url  # flagged only when words were used


class FakeResponse:
    def __init__(self, status: int, content: bytes = b"", headers: dict | None = None):
        self.status_code, self.content, self.headers = status, content, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def scripted(*outcomes):
    """A stand-in for requests.get that returns or raises each outcome in turn."""
    calls = []

    def get(url, timeout):
        calls.append(url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return get, calls


def test_a_503_is_retried_after_a_pause_and_the_file_returned():
    get, calls = scripted(FakeResponse(503), FakeResponse(200, b"zip"))
    waits = []
    assert gdelt.http_download(FILE_URL, get, waits.append) == b"zip"
    assert waits == [2.0]
    assert calls == [gdelt.fetch_url(FILE_URL)] * 2


def test_retry_after_is_followed_and_capped():
    get, _ = scripted(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, b"z"))
    waits = []
    gdelt.http_download(FILE_URL, get, waits.append)
    assert waits == [7.0]
    get, _ = scripted(FakeResponse(429, headers={"Retry-After": "600"}), FakeResponse(200, b"z"))
    waits = []
    gdelt.http_download(FILE_URL, get, waits.append)
    assert waits == [gdelt.MAX_WAIT_SECONDS]


def test_connection_errors_back_off_and_the_last_one_is_raised():
    get, calls = scripted(*[requests.ConnectionError("offline")] * gdelt.ATTEMPTS)
    waits = []
    with pytest.raises(requests.ConnectionError):
        gdelt.http_download(FILE_URL, get, waits.append)
    assert len(calls) == gdelt.ATTEMPTS
    assert waits == [2.0, 4.0]


def test_three_503s_raise_an_http_error():
    get, calls = scripted(*[FakeResponse(503)] * gdelt.ATTEMPTS)
    with pytest.raises(requests.HTTPError):
        gdelt.http_download(FILE_URL, get, lambda _: None)
    assert len(calls) == gdelt.ATTEMPTS


@pytest.mark.parametrize("status", [404, 410])
def test_a_file_gone_from_the_server_is_not_retried(status):
    get, calls = scripted(FakeResponse(status))
    waits = []
    with pytest.raises(gdelt.FileGone):
        gdelt.http_download(FILE_URL, get, waits.append)
    assert (len(calls), waits) == (1, [])


def test_a_403_is_not_retried():
    get, calls = scripted(FakeResponse(403))
    with pytest.raises(requests.HTTPError):
        gdelt.http_download(FILE_URL, get, lambda _: None)
    assert len(calls) == 1
