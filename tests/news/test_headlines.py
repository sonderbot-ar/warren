"""The headline rule: which matched articles feed events (M5 Step 6). Headlines are real ones
from draw 20261030 and the design review."""

import json
from datetime import UTC, date, datetime

import pytest

from domains.news import cluster, matching, report
from domains.news.matching import AliasError, about_headline
from tests.news.test_cluster import add
from tests.news.test_store import AAPL, MSFT, WMT, conn  # noqa: F401 - the conn fixture

PG, JNJ, CAT = "0000080424", "0000200406", "0000018230"
DAY = date(2022, 6, 2)
T0 = datetime(2022, 6, 2, 15, tzinfo=UTC)


@pytest.fixture
def rule(conn):  # noqa: F811
    return matching.load_headline_rule(conn, matching.load_aliases(conn))


@pytest.mark.parametrize(
    ("cik", "title"),
    [
        (AAPL, "Apple's iPhone sales slow in China"),  # possessive: `apple s`
        (AAPL, "apples new chip plan"),  # URL words: no apostrophe
        (PG, "procter gambles outlook lifts consumer stocks"),
        (PG, "PG raises prices again"),  # short form, for its own company
        (MSFT, "UK watchdog denies it blocked Microsoft deal on orders"),
        (AAPL, "Google, Apple among tech firms facing US probe of small deals"),
        (JNJ, "Judge rules against Johnson & Johnson in talc case"),
    ],
)
def test_headlines_that_name_the_company_pass(rule, cik, title):
    assert about_headline(rule, cik, title, DAY)


@pytest.mark.parametrize(
    ("cik", "title"),
    [
        (CAT, "Caterpillar Inc. (NYSE:CAT) Stock Holdings Trimmed by Renaissance Investment Group"),
        (MSFT, "Stocks Making the Biggest Moves Midday: Microsoft, Nike and more"),
        (WMT, "Best Walmart Early Black Friday Deals for 2022"),
        (MSFT, "Cloud Gaming Market Size 2025: Key Players Microsoft, Sony, Nvidia"),
        (MSFT, "Indiana Jones Game From Bethesda Reportedly Not An Xbox Exclusive"),  # no brands
        (MSFT, "Nasdaq rises as investors weigh rate path"),  # matched by org tag only
        (MSFT, ""),
        (MSFT, None),
    ],
)
def test_boilerplate_and_headlines_without_the_company_fail(rule, cik, title):
    assert not about_headline(rule, cik, title, DAY)


def test_phrases_match_whole_words_only(rule):
    assert about_headline(rule, MSFT, "Microsoft shifts the composition in its board", DAY)
    assert not about_headline(rule, MSFT, "Microsoft position in cloud slips", DAY)
    assert not about_headline(rule, MSFT, "Microsofty gadgets roundup", DAY)  # not a plural


def test_a_short_form_counts_only_for_its_own_company(rule):
    assert about_headline(rule, JNJ, "JNJ wins appeal", DAY)
    assert not about_headline(rule, PG, "JNJ wins appeal", DAY)
    assert not about_headline(rule, JNJ, "PG raises prices", DAY)


def test_a_subsidiary_counts_only_from_its_date(rule):
    title = "Activision Blizzard to cut jobs"
    assert not about_headline(rule, MSFT, title, date(2023, 10, 12))
    assert about_headline(rule, MSFT, title, date(2023, 10, 13))


def test_headline_rows_never_change_the_matching_hash(conn, tmp_path):  # noqa: F811
    aliases = matching.load_aliases(conn)
    extra = tmp_path / "headlines.csv"
    extra.write_text("ticker,name,note\nMSFT,msft,short form\n")
    base = matching.load_headline_rule(conn, aliases)
    more = matching.load_headline_rule(conn, aliases, extra)
    assert matching.load_aliases(conn).sha256 == aliases.sha256  # `rematch` reads nothing again
    assert more.sha256 != base.sha256
    assert about_headline(more, MSFT, "MSFT beats estimates", DAY)


def test_a_headline_row_for_an_unknown_company_is_refused(conn, tmp_path):  # noqa: F811
    bad = tmp_path / "headlines.csv"
    bad.write_text("ticker,name,note\nGOOG,goog,\n")
    with pytest.raises(AliasError, match="GOOG"):
        matching.load_headline_rule(conn, matching.load_aliases(conn), bad)


def test_events_read_only_passing_articles_and_matches_stay_stored(conn, rule):  # noqa: F811
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)
    add(conn, "https://b.com/2", "Nasdaq slips as yields rise", T0, "f2", aliases)
    before = conn.execute("SELECT COUNT(*) FROM article_companies").fetchone()[0]
    assert len(cluster.items_as_of(conn, MSFT, DAY)) == 2
    [kept] = cluster.items_as_of(conn, MSFT, DAY, rule=rule)
    assert kept.title == "Microsoft cuts forecast"
    run = cluster.run_events(conn, MSFT, DAY, aliases, rule=rule)
    [event] = cluster.stored_events(conn, run)
    assert event["article_count"] == 1
    assert conn.execute("SELECT COUNT(*) FROM article_companies").fetchone()[0] == before
    params = json.loads(
        conn.execute("SELECT params_json FROM event_runs WHERE event_run_id = ?", (run,))
        .fetchone()[0]
    )  # fmt: skip
    assert params["headlines_sha256"] == rule.sha256


def test_rebuild_names_a_changed_or_missing_headline_rule(conn, rule):  # noqa: F811
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)
    run = cluster.run_events(conn, MSFT, DAY, aliases, rule=rule)
    assert cluster.rebuild(conn, run, aliases, rule) == []
    other = matching.HeadlineRule(rule.names, rule.excludes, "another rule")
    assert cluster.rebuild(conn, run, aliases, other)[0].startswith("headline rule changed")
    assert cluster.rebuild(conn, run, aliases)[0].startswith("headline rule changed")
    plain = cluster.run_events(conn, MSFT, DAY, aliases)  # without a rule: another run
    assert plain != run and cluster.rebuild(conn, plain, aliases) == []


def test_draw_candidates_keep_passing_articles_mark_dropped_ones_and_skip_earlier_draws(
    conn,  # noqa: F811
    rule,
):
    aliases = matching.load_aliases(conn)
    add(conn, "https://a.com/1", "Microsoft cuts forecast", T0, "f1", aliases)
    add(conn, "https://b.com/2", "Nasdaq slips as yields rise", T0, "f2", aliases)
    add(conn, "https://c.com/3", "Microsoft unveils new laptop", T0, "f3", aliases)
    windows = [("MSFT", DAY)]
    rows = report.candidates(conn, windows, rule)
    assert sorted((r["title"], r["method"]) for r in rows) == [
        ("Microsoft cuts forecast", "org_exact"),
        ("Microsoft unveils new laptop", "org_exact"),
        ("Nasdaq slips as yields rise", report.DROPPED),
    ]
    first = next(r["article_id"] for r in rows if r["title"] == "Microsoft cuts forecast")
    again = report.candidates(conn, windows, rule, skip=frozenset({first}))
    assert first not in {r["article_id"] for r in again} and len(again) == 2
    assert report.headline_pass(conn, "MSFT", DAY, rule) == {
        "matched": 3,
        "passed": 2,
        "url_words": 0,
    }


def test_agreement_reads_about_against_the_rest_with_raw_agreement():
    def row(label, second):
        return {"draw": "1", "ticker": "MSFT", "method": "org_exact", "label": label,
                "second_label": second}  # fmt: skip

    # not/related disagreements don't count against agreement on `about`
    rows = [row("about", "about")] * 6 + [row("not", "related")] * 4 + [row("related", "-")] * 2
    [p] = report.precision(rows)
    assert (p["shared"], p["agree"], p["kappa_about"]) == (10, 1.0, 1.0)
    assert p["kappa"] < 0.6  # the three-label kappa still sinks, and is still reported
    [small] = report.precision(rows[:9])
    assert small["kappa_about"] is None and small["agree"] == 1.0  # under 10 shared rows
