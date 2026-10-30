"""Clustering articles into events as of a date, event runs and as-of search (M5 Step 3)."""

import random
from datetime import UTC, date, datetime, timedelta

from domains.news import cluster, matching, store
from domains.news.cluster import Item
from domains.news.gdelt import ArticleRecord
from tests.news.test_store import MSFT, NOW, conn  # noqa: F401 - the conn fixture

T0 = datetime(2022, 6, 2, 14, tzinfo=UTC)
WORDS = frozenset({"microsoft"})
THEMES = frozenset({"ECON_CURRENCY", "ECON_EARNINGSREPORT", "ECON_FOREIGNINVEST", "FX_RATE"})


def item(n: int, title: str, hours: float = 0, source: str | None = None, themes=THEMES) -> Item:
    return Item(f"a{n:03d}", "f", source or f"outlet{n}.com", T0 + timedelta(hours=hours), title,
                -1.0, frozenset(themes))  # fmt: skip


def test_the_same_story_from_ten_outlets_is_one_event():
    titles = [
        "Microsoft cuts quarterly revenue forecast on strong dollar",
        "Microsoft lowers quarterly revenue forecast citing strong dollar",
        "Strong dollar: Microsoft cuts revenue forecast for quarter",
    ]
    items = [item(n, titles[n % 3], hours=n / 2) for n in range(10)]
    [event] = cluster.cluster(items, WORDS)
    e = cluster.describe(event, MSFT, date(2022, 6, 2))
    assert e["article_count"] == 10 and e["source_count"] == 10


def test_two_unrelated_stories_sharing_themes_are_two_events():
    items = [
        item(1, "Microsoft cuts revenue forecast on strong dollar"),
        item(2, "Microsoft opens new data centre in Poland", hours=1),
    ]
    assert len(cluster.cluster(items, WORDS)) == 2


def test_themes_join_only_with_some_title_overlap():
    a = item(1, "Microsoft forecast cut dollar currency hit")
    b = item(2, "Dollar strength hits forecast for software earnings", hours=1)  # Jaccard 2/9
    events = cluster.cluster([a, b], WORDS)
    assert len(events) == 1 and events[0].joined_by_themes == 1
    c = item(3, "Software earnings season begins", hours=1, themes=set())
    assert len(cluster.cluster([a, c], WORDS)) == 2


def test_a_gap_over_48_hours_starts_a_new_event():
    items = [item(1, "Microsoft cuts forecast"), item(2, "Microsoft cuts forecast", hours=49)]
    assert len(cluster.cluster(items, WORDS)) == 2


def test_input_order_doesnt_change_events():
    items = [item(n, f"Microsoft story {n // 3} update", hours=n) for n in range(12)]
    shuffled = items[:]
    random.Random(7).shuffle(shuffled)
    ids = lambda evs: [cluster.describe(e, MSFT, date(2022, 6, 2))["event_id"] for e in evs]  # noqa: E731
    assert ids(cluster.cluster(items, WORDS)) == ids(cluster.cluster(shuffled, WORDS))


def add(conn, url, title, seen_at, file_url, aliases):  # noqa: F811
    conn.execute(
        "INSERT OR IGNORE INTO news_files (file_url, file_ts, status, aliases_sha256, fetched_at) "
        "VALUES (?, ?, 'ok', ?, ?)",
        (file_url, store.iso(seen_at), aliases.sha256, store.iso(NOW)),
    )
    record = ArticleRecord(url, "reuters.com", seen_at, title, -1.0, ("ECON_CURRENCY",),
                           ("microsoft",), file_url)  # fmt: skip
    store.store_records(conn, [record], aliases)
    conn.commit()


def test_a_story_continuing_after_the_as_of_date_stops_there(conn):  # noqa: F811
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)
    # 03:00 UTC on jun.03 is 23:00 on jun.02 in New York: known by jun.02
    add(
        conn,
        "https://b.com/2",
        "Microsoft cuts forecast again",
        datetime(2022, 6, 3, 3, tzinfo=UTC),
        "f2",
        aliases,
    )  # noqa: E501
    add(
        conn,
        "https://c.com/3",
        "Microsoft forecast cut reaction",
        datetime(2022, 6, 3, 5, tzinfo=UTC),
        "f3",
        aliases,
    )  # noqa: E501
    run = cluster.run_events(conn, MSFT, date(2022, 6, 2), aliases)
    [event] = cluster.stored_events(conn, run)
    assert event["article_count"] == 2
    assert [r["title"] for r in cluster.search(conn, "forecast", date(2022, 6, 2), MSFT)] == [
        "Microsoft cuts forecast",
        "Microsoft cuts forecast again",
    ]


def test_the_earliest_sighting_keeps_its_own_title_whatever_the_ingest_order(conn):  # noqa: F811
    aliases = matching.load_aliases(conn)
    late = datetime(2022, 6, 5, tzinfo=UTC)
    add(conn, "https://a.com/1", "Microsoft: updated headline", late, "f9", aliases)  # seen later
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)  # ingested second
    [it] = cluster.items_as_of(conn, MSFT, date(2022, 6, 2))
    assert it.title == "Microsoft cuts forecast" and it.seen_at == T0
    [later] = cluster.items_as_of(conn, MSFT, date(2022, 6, 10))
    assert later.title == "Microsoft cuts forecast"  # the earliest sighting, still


def test_an_event_run_rebuilds_and_detects_a_changed_input(conn):  # noqa: F811
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)
    run = cluster.run_events(conn, MSFT, date(2022, 6, 2), aliases)
    assert cluster.run_events(conn, MSFT, date(2022, 6, 2), aliases) == run  # same input, same run
    assert cluster.rebuild(conn, run, aliases) == []
    other = matching.AliasSet(aliases.aliases, "another alias set")
    assert cluster.rebuild(conn, run, other)[0].startswith("aliases changed")
    assert cluster.run_events(conn, MSFT, date(2022, 6, 2), other) != run
    add(conn, "https://d.com/4", "Microsoft forecast", T0 - timedelta(hours=1), "f0", aliases)
    assert cluster.rebuild(conn, run, aliases)[0].startswith("input changed")


def test_search_returns_each_article_once_with_its_earliest_sighting(conn):  # noqa: F811
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft forecast cut", T0, "f1", aliases)
    add(
        conn,
        "https://a.com/1",
        "Microsoft forecast cut, updated",
        T0 + timedelta(hours=2),
        "f2",
        aliases,
    )  # noqa: E501
    [hit] = cluster.search(conn, "forecast", date(2022, 6, 2), MSFT)
    assert hit["title"] == "Microsoft forecast cut"
