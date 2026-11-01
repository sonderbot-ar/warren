"""Event extraction: choosing events and headlines, masking, validation and storage (M6 Step 3)."""

import json
import re
from datetime import UTC, date, datetime, timedelta

import pytest

from domains.llm import extract
from domains.llm.client import FakeClient
from domains.news import cluster, matching, store
from domains.news.gdelt import ArticleRecord
from tests.news.test_store import MSFT, NOW, conn  # noqa: F401 - the conn fixture

DAY = date(2022, 6, 2)
T0 = datetime(2022, 6, 2, 15, tzinfo=UTC)
MSFT_CO = extract.Company(MSFT, "MSFT", "MICROSOFT CORP")


def add(conn, n, title, seen_at=T0, source=None):  # noqa: F811
    aliases = matching.load_aliases(conn)
    file_url = f"f{n}"
    conn.execute(
        "INSERT OR IGNORE INTO news_files (file_url, file_ts, status, aliases_sha256, fetched_at) "
        "VALUES (?, ?, 'ok', ?, ?)",
        (file_url, store.iso(seen_at), aliases.sha256, store.iso(NOW)),
    )
    domain = source or f"outlet{n}.com"
    record = ArticleRecord(f"https://outlet{n}.com/{n}", domain, seen_at, title, False, -1.0,
                           ("ECON_CURRENCY",), ("microsoft",), file_url)  # fmt: skip
    store.store_records(conn, [record], aliases)
    conn.commit()


def story(conn, first=0, count=3, hours=0):  # noqa: F811
    titles = ["Microsoft cuts quarterly revenue forecast on strong dollar",
              "Microsoft lowers quarterly revenue forecast citing strong dollar",
              "Strong dollar: Microsoft cuts revenue forecast for quarter"]  # fmt: skip
    for n in range(first, first + count):
        add(conn, n, titles[n % 3], T0 + timedelta(hours=hours + n / 4))


def ids_in(user: str) -> list[str]:
    return re.findall(r"^(h\d+) \|", user, re.MULTILINE)


def answer(event_type="guidance", about=True):
    def respond(system, user):
        ids = ids_in(user)
        return {"event_type": event_type, "materiality": "medium",
                "reasons": ["The company cut its own revenue forecast."],
                "summary": "The company lowered its quarterly revenue forecast.",
                "evidence": ids[:1] if about else [],
                "headlines": [{"id": i, "about": about} for i in ids]}  # fmt: skip

    return respond


def classify(conn, client, variants=("named",)):  # noqa: F811
    aliases = matching.load_aliases(conn)
    rule = matching.load_headline_rule(conn, aliases)
    return extract.classify_case(conn, client, "MSFT_2022-06-02", "MSFT", DAY, aliases, rule,
                                 variants, "test")  # fmt: skip


def rows(conn):  # noqa: F811
    return conn.execute("SELECT * FROM event_classifications ORDER BY classification_id").fetchall()


def test_a_valid_answer_is_stored_with_article_ids_not_prompt_ids(conn):  # noqa: F811
    story(conn)
    out = classify(conn, FakeClient(answer()))
    [row] = rows(conn)
    assert out == {"named": [row["classification_id"]]}
    assert row["status"] == "ok" and row["event_type"] == "guidance"
    about = json.loads(row["about_json"])
    assert len(about) == 3 and all(about.values())
    assert all(len(a) == 64 for a in json.loads(row["evidence_json"]))  # article ids
    status = conn.execute("SELECT * FROM case_llm_status").fetchone()
    assert (status["events_total"], status["events_chosen"]) == (1, 1)


def test_a_rerun_reuses_the_stored_answer_and_pays_nothing(conn):  # noqa: F811
    story(conn)
    classify(conn, FakeClient(answer()))
    client = FakeClient(answer())
    classify(conn, client)
    assert client.requests == [] and len(rows(conn)) == 1


def test_a_failed_event_is_stored_failed_then_tried_again(conn):  # noqa: F811
    story(conn)
    classify(conn, FakeClient([{"event_type": "weather"}] * 3))
    assert [r["status"] for r in rows(conn)] == ["failed"]
    classify(conn, FakeClient(answer()))
    assert [r["status"] for r in rows(conn)] == ["ok"]


def test_out_of_taxonomy_unknown_or_missing_headlines_are_refused():
    headlines = [extract.Headline(f"h{n}", f"a{n}", T0, "x.com", "t") for n in (1, 2)]
    check = extract.checker(headlines, {"guidance": "", "not_about_company": ""})
    good = extract.EventClassification(event_type="guidance", materiality="low", reasons=["r"],
                                       summary="s", evidence=["h1"],
                                       headlines=[{"id": "h1", "about": True},
                                                  {"id": "h2", "about": False}])  # fmt: skip
    check(good)
    bad = [
        {"event_type": "weather"},
        {"evidence": ["h9"]},
        {"evidence": ["h2"]},  # cites a headline marked not about
        {"headlines": [{"id": "h1", "about": True}]},  # misses h2
        {"headlines": [{"id": "h1", "about": True}] * 2},  # repeats h1, misses h2
        {"event_type": "not_about_company"},  # while h1 is about
        {"evidence": []},
    ]
    for change in bad:
        with pytest.raises(ValueError):
            check(extract.EventClassification(**(good.model_dump() | change)))


def test_a_number_added_by_the_model_is_an_invalid_answer(conn):  # noqa: F811
    story(conn)

    def with_number(system, user):
        return answer()(system, user) | {"revenue_impact": -2.5}

    classify(conn, FakeClient(with_number))
    assert [r["status"] for r in rows(conn)] == ["failed"]


def test_no_headline_about_the_company_makes_the_event_not_about_company(conn):  # noqa: F811
    story(conn)
    classify(conn, FakeClient(answer("not_about_company", about=False)))
    [row] = rows(conn)
    assert row["event_type"] == "not_about_company" and not any(
        json.loads(row["about_json"]).values()
    )


def test_masking_removes_every_alias_the_name_and_the_ticker(conn):  # noqa: F811
    pattern = extract.mask_pattern(matching.load_aliases(conn), MSFT_CO)
    title = "MSFT: Microsoft Corp's forecast cut; MICROSOFT shares fall (msft.com not touched)"
    masked = extract.mask(title, pattern)
    assert "microsoft" not in masked.lower().replace("msft.com", "")
    assert masked.startswith("the Company: the Company's forecast cut; the Company shares")


def test_the_masked_prompt_has_no_name_domain_or_date(conn):  # noqa: F811
    story(conn)
    client = FakeClient(answer())
    classify(conn, client, ("named", "masked"))
    named, masked = (r["user"] for r in client.requests)
    assert "Microsoft" in named and "2022-06-02" in named and "outlet0.com" in named
    for word in ("Microsoft", "MSFT", "2022", "outlet"):
        assert word not in masked
    assert "day +0 11:00" in masked  # 15:00 UTC is 11:00 in New York, on the as-of day
    variants = [r["variant"] for r in rows(conn)]
    assert variants == ["named", "masked"]


def test_an_article_seen_after_the_as_of_date_is_never_an_input(conn):  # noqa: F811
    story(conn)
    add(conn, 9, "Microsoft forecast cut: what comes next", T0 + timedelta(days=2))
    client = FakeClient(answer())
    classify(conn, client)
    assert "what comes next" not in client.requests[0]["user"]


def test_single_source_events_are_skipped_and_counted(conn):  # noqa: F811
    for n in range(3):
        add(conn, n, "Microsoft cuts quarterly revenue forecast", T0, source="same.com")
    client = FakeClient(answer())
    assert classify(conn, client) == {"named": []}
    status = conn.execute("SELECT * FROM case_llm_status").fetchone()
    assert (status["events_total"], status["events_chosen"]) == (1, 0)
    assert client.requests == []


def test_events_chosen_largest_first_and_at_most_fifteen():
    events = [{"event_id": f"e{n:02d}", "source_count": n % 5, "first_seen": f"2022-06-{n:02d}",
               "last_seen": f"2022-06-{n:02d}"} for n in range(1, 30)]  # fmt: skip
    chosen = extract.choose_events(events, "2022-06-01T00:00:00Z")
    assert len(chosen) == 15 and all(e["source_count"] >= 2 for e in chosen)
    assert [e["source_count"] for e in chosen] == sorted(
        (e["source_count"] for e in chosen), reverse=True
    )


def test_headlines_one_per_source_first_then_earliest():
    def item(n, source):
        return cluster.Item(f"a{n:02d}", "f", source, T0 + timedelta(minutes=n), f"t{n}", None,
                            frozenset())  # fmt: skip

    items = [item(n, "big.com") for n in range(30)] + [item(40, "late.com")]
    chosen = extract.choose_headlines(items)
    assert len(chosen) == extract.MAX_HEADLINES
    assert "a40" in {i.article_id for i in chosen}
    assert [i.seen_at for i in chosen] == sorted(i.seen_at for i in chosen)


def test_only_events_running_in_the_case_window_are_chosen():
    # the real run: WMT_2022-07-25 read 2019 news, larger than its own profit warning (37 sources)
    start = extract.window_start(date(2022, 7, 25))
    assert start == "2022-07-19T04:00:00Z"  # 7 New York days ending on the case date
    old = {
        "event_id": "old",
        "source_count": 90,
        "first_seen": "2019-08-04T00:00:00Z",
        "last_seen": "2019-08-06T00:00:00Z",
    }
    late = {
        "event_id": "late",
        "source_count": 5,
        "first_seen": "2022-07-18T20:00:00Z",
        "last_seen": "2022-07-19T05:00:00Z",
    }  # began before the window, still running in it
    own = {
        "event_id": "own",
        "source_count": 37,
        "first_seen": "2022-07-25T21:30:00Z",
        "last_seen": "2022-07-25T23:00:00Z",
    }
    ended = {
        "event_id": "ended",
        "source_count": 50,
        "first_seen": "2022-07-17T00:00:00Z",
        "last_seen": "2022-07-19T03:59:59Z",
    }
    chosen = extract.choose_events([old, late, own, ended], start)
    assert [e["event_id"] for e in chosen] == ["own", "late"]


def test_a_case_classifies_none_of_another_windows_news(conn):  # noqa: F811
    story(conn, hours=-24 * 30)  # the same story a month before the case window
    client = FakeClient(answer())
    assert classify(conn, client) == {"named": []}
    assert client.requests == []
