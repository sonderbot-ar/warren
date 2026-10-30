"""Migration 0009, aliases, company matching and ingestion with a manifest (M5 Step 2)."""

import hashlib
import io
import json
import shutil
import zipfile
from datetime import UTC, date, datetime

import pytest

from domains.news import matching, store
from domains.news.gdelt import ArticleRecord, MasterEntry
from domains.news.matching import AliasError, normalise
from shared_kernel.database import MIGRATIONS_DIR, apply_migrations, get_db_connection

COMPANIES = [
    ("0000320193", "AAPL", ["Apple Inc.", "APPLE INC"]),
    ("0000789019", "MSFT", ["MICROSOFT CORP"]),
    ("0000104169", "WMT", ["Walmart Inc.", "WAL MART STORES INC"]),
    ("0000021344", "KO", ["COCA COLA CO"]),
    ("0000080424", "PG", ["PROCTER & GAMBLE Co"]),
    ("0000200406", "JNJ", ["JOHNSON & JOHNSON"]),
    ("0000018230", "CAT", ["CATERPILLAR INC"]),
    ("0000034088", "XOM", ["EXXON MOBIL CORP"]),
]
AAPL, MSFT, WMT, KO = "0000320193", "0000789019", "0000104169", "0000021344"
NOW = datetime(2026, 10, 30, tzinfo=UTC)
T0 = datetime(2022, 6, 2, 15, tzinfo=UTC)


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        for cik, ticker, names in COMPANIES:
            conn.execute(
                "INSERT INTO companies (cik, ticker, name, aliases_json) VALUES (?, ?, ?, ?)",
                (cik, ticker, names[0], json.dumps(names)),
            )
        conn.commit()
        yield conn


@pytest.fixture
def aliases(conn):
    return matching.load_aliases(conn)


def record(url="https://www.reuters.com/a", orgs=("microsoft corp",), title="x", ts=T0, file="f1"):
    return ArticleRecord(url, "reuters.com", ts, title, -1.0, ("ECON_CURRENCY",), orgs, file)


def gkg_line(url, orgs, title, ts="20220602150000") -> str:
    cols = [""] * 27
    cols[1], cols[3], cols[4] = ts, "reuters.com", url
    cols[14] = ";".join(f"{o},1" for o in orgs)
    cols[15] = "-1.0,1,2,3,4,5,6"
    cols[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(cols)


def gkg_file(url: str, lines: list[str]) -> tuple[MasterEntry, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("f.gkg.csv", "\n".join(lines) + "\n")
    content = buffer.getvalue()
    return MasterEntry(url, len(content), hashlib.md5(content).hexdigest()), content  # noqa: S324


URL1 = "http://data.gdeltproject.org/gdeltv2/20220602150000.gkg.csv.zip"
URL2 = "http://data.gdeltproject.org/gdeltv2/20220602151500.gkg.csv.zip"


def test_migration_0009_applies_to_an_existing_database(tmp_path, db_path):
    older = tmp_path / "older"
    older.mkdir()
    for path in MIGRATIONS_DIR.glob("000[1-8]_*.sql"):
        shutil.copy(path, older / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, older)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000001', 'TST', 'T')")
        conn.commit()
        assert apply_migrations(conn) == [9]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"news_files", "articles", "article_sightings", "events", "sightings_fts"} <= tables
        assert conn.execute("SELECT ticker FROM companies").fetchone()[0] == "TST"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PROCTER & GAMBLE Co", "procter and gamble"),
        ("P&G", "p and g"),
        ("The Coca-Cola Company", "coca cola"),
        ("JOHNSON & JOHNSON ET AL", "johnson and johnson"),
        ("Wal-Mart Stores, Inc.", "wal mart stores"),
    ],
)
def test_normalise(text, expected):
    assert normalise(text) == expected


def test_aliases_come_from_edgar_and_the_file_and_short_ones_are_refused(conn, aliases, tmp_path):
    names = {(a.cik, a.alias, a.kind) for a in aliases.aliases}
    assert (MSFT, "microsoft", "include") in names  # aliases.csv
    assert (WMT, "wal mart stores", "include") in names  # EDGAR's former name
    bad = tmp_path / "aliases.csv"
    bad.write_text("ticker,alias,kind,from,note\nPG,P&G Co,include,,\n")
    assert matching.load_aliases(conn, bad)  # `p and g` is long enough
    bad.write_text("ticker,alias,kind,from,note\nPG,PG,include,,\n")
    with pytest.raises(AliasError, match="too short"):
        matching.load_aliases(conn, bad)


def test_an_excluded_name_is_not_the_company(aliases):
    day = date(2021, 6, 23)
    assert matching.match(("apple daily",), "Apple Daily shuts down", day, aliases) == {}
    assert matching.match((), "Apple sues Apple Daily", date(2021, 6, 23), aliases) == {
        AAPL: "title_alias"
    }


def test_a_bottler_is_not_coca_cola_but_a_story_mentioning_one_still_is(aliases):
    day = date(2022, 6, 2)
    assert matching.match(("coca cola femsa",), None, day, aliases) == {}
    both = matching.match(("coca cola femsa", "the coca-cola company"), None, day, aliases)
    assert both == {KO: "org_exact"}


def test_a_subsidiary_counts_only_from_its_date(aliases):
    assert matching.match(("activision blizzard",), None, date(2023, 1, 18), aliases) == {}
    assert matching.match(("activision blizzard",), None, date(2023, 10, 13), aliases) == {
        MSFT: "org_subsidiary"
    }
    assert matching.match(("walmex",), None, date(2019, 1, 1), aliases) == {WMT: "org_subsidiary"}


def test_one_article_two_companies_and_the_strongest_method_wins(aliases):
    found = matching.match(
        ("microsoft",), "Walmart and Microsoft team up", date(2022, 6, 2), aliases
    )
    assert found == {MSFT: "org_exact", WMT: "title_alias"}


def test_url_normalisation_drops_scheme_www_tracking_and_fragment():
    a = "https://www.example.com/story?id=7&utm_source=x&fbclid=y#top"
    assert store.normalise_url(a) == "example.com/story?id=7"
    assert store.article_id(a) == store.article_id("http://example.com/story?id=7")


def test_only_matched_rows_are_kept_and_reingesting_adds_nothing(conn, aliases):
    entry, content = gkg_file(URL1, [
        gkg_line("https://a.com/1", ["microsoft corp"], "Microsoft cuts forecast"),
        gkg_line("https://a.com/2", ["federal reserve"], "Fed raises rates"),
    ])  # fmt: skip
    result = store.ingest_file(conn, entry, aliases, lambda _: content, lambda: NOW)
    assert (result.status, result.rows_total, result.rows_kept) == ("ok", 2, 1)
    again = store.ingest_file(conn, entry, aliases, lambda _: pytest.fail("fetched twice"))
    assert again.status == "skipped"
    assert conn.execute("SELECT COUNT(*) FROM article_sightings").fetchone()[0] == 1


def test_every_company_is_matched_whatever_window_asked(conn, aliases):
    entry, content = gkg_file(URL1, [
        gkg_line("https://a.com/1", ["microsoft"], "Microsoft news"),
        gkg_line("https://a.com/2", ["exxon mobil"], "Exxon news"),
    ])  # fmt: skip
    store.ingest_file(conn, entry, aliases, lambda _: content, lambda: NOW)
    ciks = {r[0] for r in conn.execute("SELECT cik FROM article_companies")}
    assert ciks == {MSFT, "0000034088"}


def test_a_url_seen_in_two_files_keeps_both_sightings(conn, aliases):
    for url, title in ((URL1, "First title"), (URL2, "Microsoft: later title")):
        entry, content = gkg_file(url, [gkg_line("https://a.com/1", ["microsoft"], title)])
        store.ingest_file(conn, entry, aliases, lambda _, c=content: c, lambda: NOW)
    titles = [r[0] for r in conn.execute("SELECT title FROM article_sightings ORDER BY file_url")]
    assert titles == ["First title", "Microsoft: later title"]
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_a_bad_md5_and_a_missing_file_are_recorded(conn, aliases):
    entry, content = gkg_file(URL1, [gkg_line("https://a.com/1", ["microsoft"], "t")])
    wrong = MasterEntry(entry.url, entry.size, "0" * 32)
    assert (
        store.ingest_file(conn, wrong, aliases, lambda _: content, lambda: NOW).status == "bad_md5"
    )
    slot = datetime(2022, 6, 2, 15, 30, tzinfo=UTC)
    assert store.record_missing_slot(conn, slot, aliases, NOW).status == "missing"
    rows = dict(conn.execute("SELECT file_url, status FROM news_files").fetchall())
    assert rows[URL1] == "bad_md5"
    assert rows["http://data.gdeltproject.org/gdeltv2/20220602153000.gkg.csv.zip"] == "missing"
    assert conn.execute("SELECT COUNT(*) FROM article_sightings").fetchone()[0] == 0


def test_a_changed_alias_set_reads_the_file_again_and_replaces_its_matches(conn, aliases, tmp_path):
    entry, content = gkg_file(URL1, [gkg_line("https://a.com/1", ["contoso"], "Contoso news")])
    store.ingest_file(conn, entry, aliases, lambda _: content, lambda: NOW)
    assert conn.execute("SELECT COUNT(*) FROM article_companies").fetchone()[0] == 0
    extra = tmp_path / "aliases.csv"
    extra.write_text(
        matching.ALIASES_PATH.read_text() + "MSFT,contoso,subsidiary,,a made-up unit\n"
    )
    wider = matching.load_aliases(conn, extra)
    assert wider.sha256 != aliases.sha256
    assert store.stale_files(conn, wider) == [URL1]
    store.ingest_file(conn, entry, wider, lambda _: content, lambda: NOW)
    assert [tuple(r) for r in conn.execute("SELECT cik, method FROM article_companies")] == [
        (MSFT, "org_subsidiary")
    ]
    assert store.stale_files(conn, wider) == []


def test_search_index_follows_sightings(conn, aliases):
    entry, content = gkg_file(URL1, [gkg_line("https://a.com/1", ["microsoft"], "Currency hit")])
    store.ingest_file(conn, entry, aliases, lambda _: content, lambda: NOW)
    hits = conn.execute("SELECT title FROM sightings_fts WHERE sightings_fts MATCH 'currency'")
    assert [r[0] for r in hits] == ["Currency hit"]


def test_a_file_read_before_keeps_its_rows_when_it_cant_be_fetched_again(conn, aliases, tmp_path):
    import requests

    entry, content = gkg_file(URL1, [gkg_line("https://a.com/1", ["microsoft"], "t")])
    store.ingest_file(conn, entry, aliases, lambda _: content, lambda: NOW)
    extra = tmp_path / "aliases.csv"
    extra.write_text(matching.ALIASES_PATH.read_text() + "MSFT,contoso,subsidiary,,made up\n")
    wider = matching.load_aliases(conn, extra)

    def down(_):
        raise requests.ConnectionError("offline")

    assert store.ingest_file(conn, entry, wider, down, lambda: NOW).status == "missing"
    assert conn.execute("SELECT COUNT(*) FROM article_sightings").fetchone()[0] == 1
    assert store.stale_files(conn, wider) == [URL1]  # still to be read again
