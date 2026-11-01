"""The pipeline's nodes on Test Corp (M7 Step 2): each writes what the design says, downloads
only stale data, refuses offline what is missing, and is safe to run twice."""

from datetime import UTC, date, datetime, timedelta

import pytest

from domains.analysis.runs import run_baseline
from domains.orchestration import nodes
from domains.orchestration.state import PipelineState
from tests.analysis.conftest import AS_OF, CHOICES, companyfacts
from tests.fundamentals.conftest import FakeEdgar
from tests.orchestration.conftest import new_state, register

ORDER = ("load_fundamentals", "load_market", "build_baseline", "fetch_news", "cluster_events",
         "extract_events", "propose_shocks", "review_shocks", "simulate")  # fmt: skip


def run_through(world, state: PipelineState, upto: str = "simulate") -> PipelineState:
    deps = world.deps()
    for name in ORDER:
        state = state.model_copy(update=getattr(nodes, name)(state, deps))
        if name == upto:
            break
    return state


def counts(conn) -> dict[str, int]:
    sql = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    tables = [r[0] for r in conn.execute(sql)]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


@pytest.fixture
def state(world):
    s = new_state()
    register(world.conn, s)
    return s


def test_every_node_writes_its_part_of_the_state(world, state):
    done = run_through(world, state)
    assert done.cik and done.company == "Test Corp" and done.ingest_run_id
    assert set(done.market_fetch_ids) == {"yahoo:TST", "yahoo:^SP500TR", "fred:DGS10"}
    assert done.run_id and done.baseline_value_per_share > 0 and done.baseline_reused is False
    assert done.news_files["ok"] == 4 and done.articles_kept == 4
    assert done.events_chosen == 1
    assert done.classified == {"named": {"events": 1, "ok": 1, "failed": 0,
                                         "not_about_company": 0}}  # fmt: skip
    assert done.proposals == {"named": ["revenue_growth down medium fading from Q1"]}
    assert done.reviewed["named"]["auto_approved"] == 1
    sim = done.sim["named"]
    assert sim.sim_id.startswith(done.run_id) and sim.p10 < sim.p50 < sim.p90
    assert sim.p50 < done.baseline_value_per_share  # a revenue cut lowers the value
    row = world.conn.execute("SELECT run_id FROM pipeline_runs").fetchone()
    assert row["run_id"] == done.run_id


def test_stored_data_is_not_downloaded_again(world, state):
    run_through(world, state)
    assert world.edgar_calls == 0  # the stored ingest was fetched after the as-of date
    fetches = world.conn.execute("SELECT COUNT(*) FROM market_fetches").fetchone()[0]
    assert fetches == 3  # the fixture's three, fetched the day after the as-of date
    assert world.master_calls == 1 and world.file_calls == 4


def test_every_node_run_twice_adds_no_row(world, state):
    done = run_through(world, state)
    before = counts(world.conn)
    calls = len(world.client.requests)
    again = run_through(world, done)
    assert counts(world.conn) == before
    assert len(world.client.requests) == calls  # stored answers reused, nothing paid
    assert world.master_calls == 1  # the window is read: no master list download
    assert again.sim == done.sim and again.run_id == done.run_id and again.baseline_reused


def test_a_sunday_as_of_date_downloads_nothing_new_on_a_second_run(world):
    # analyst review: a rule on the series' last date would download on every weekend run
    sunday = date(2020, 6, 28)
    s = new_state(pipeline_id="TST_2020-06-28_p1", as_of=sunday)
    register(world.conn, s)
    run_through(world, s, upto="load_market")
    before = counts(world.conn)
    run_through(world, s, upto="load_market")
    assert counts(world.conn) == before


def test_data_fetched_before_the_as_of_date_is_downloaded_or_refused_offline(world, state):
    world.conn.execute("UPDATE market_fetches SET fetched_at = '2020-06-01T00:00:00Z'")
    world.conn.commit()
    deps = world.deps()
    with pytest.raises(nodes.PipelineError, match="offline"):
        nodes.load_market(state.model_copy(update={"offline": True}), deps)

    def prices(ticker, start):
        rows = world.conn.execute("SELECT * FROM prices WHERE ticker = ? ORDER BY date",
                                  (ticker,)).fetchall()  # fmt: skip
        return [{k: r[k] for k in ("date", "close", "adj_close", "volume", "split_ratio")}
                for r in rows]  # fmt: skip

    def yields(series):
        return [{"date": r["date"], "value": r["value"]}
                for r in world.conn.execute("SELECT * FROM yields ORDER BY date")]  # fmt: skip

    deps.prices_download, deps.yields_download = prices, yields
    out = nodes.load_market(state, deps)
    assert world.conn.execute("SELECT COUNT(*) FROM market_fetches").fetchone()[0] == 6
    assert min(out["market_fetch_ids"].values()) > 3  # the new downloads


def test_an_old_filings_download_is_ingested_again(world, state):
    world.conn.execute("UPDATE ingest_runs SET companyfacts_fetched_at = '2020-06-15T00:00:00Z'")
    world.conn.commit()
    with pytest.raises(nodes.PipelineError, match="EDGAR"):
        nodes.load_fundamentals(state.model_copy(update={"offline": True}), world.deps())
    out = nodes.load_fundamentals(state, world.deps())
    assert world.edgar_calls == 1 and out["ingest_run_id"] == 2


def test_a_baseline_from_an_older_ingest_or_other_choices_is_not_reused(world, state):
    old = run_baseline(world.conn, "TST", AS_OF)
    world.conn.execute(
        "INSERT INTO ingest_runs (cik, companyfacts_sha256, companyfacts_fetched_at, "
        "concept_map_sha256, facts_kept, facts_new) SELECT cik, companyfacts_sha256, "
        "companyfacts_fetched_at, concept_map_sha256, facts_kept, 0 FROM ingest_runs"
    )  # a newer ingest of the same filings
    world.conn.commit()
    s = run_through(world, state, upto="build_baseline")
    assert s.run_id != old and not s.baseline_reused
    # a run built with other owner choices than today's file
    other = run_baseline(world.conn, "TST", AS_OF, choices=CHOICES | {
        "erp_first_year": CHOICES["erp_first_year"].__class__("erp_first_year", "1990", "test",
                                                               "2026-10-26", "")})  # fmt: skip
    again = nodes.build_baseline(state, world.deps())
    assert other not in (old, s.run_id)
    assert again["run_id"] == s.run_id and again["baseline_reused"]  # not `other`, the newest


def test_filings_after_the_as_of_date_leave_the_baseline_unchanged(world, state):
    # a download made today holds filings from after the as-of date; every read filters them
    first = run_through(world, state, upto="build_baseline")
    facts = companyfacts()
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2020-04-01", "end": "2020-06-30", "val": 999.0, "accn": "0000000123-20-000099",
         "fy": 2020, "fp": "Q2", "form": "10-Q", "filed": "2020-07-30"})  # fmt: skip
    world.conn.execute("UPDATE ingest_runs SET companyfacts_fetched_at = '2020-06-15T00:00:00Z'")
    world.conn.commit()
    edgar = FakeEdgar()
    edgar.facts = facts
    deps = world.deps()
    deps.edgar = lambda: edgar
    later = state.model_copy(update=nodes.load_fundamentals(state, deps))
    assert later.ingest_run_id != first.ingest_run_id
    out = nodes.build_baseline(later, deps)
    assert out["run_id"] != first.run_id and not out["baseline_reused"]
    assert out["baseline_value_per_share"] == first.baseline_value_per_share


def test_a_day_not_yet_ended_in_new_york_is_refused(world, state):
    s = run_through(world, state, upto="build_baseline")
    world.now = datetime.combine(AS_OF, datetime.min.time(), tzinfo=UTC) + timedelta(hours=20)
    with pytest.raises(nodes.PipelineError, match="not ended"):
        nodes.fetch_news(s, world.deps())


def test_a_window_with_no_events_makes_no_call_and_no_proposal(world):
    s = new_state(pipeline_id="TST_2020-05-31_p1", as_of=date(2020, 5, 31))
    register(world.conn, s)
    world.files = {}
    done = run_through(world, s)
    assert world.client.requests == []
    assert done.events_chosen == 0 and done.proposal_set == {"named": None}
    assert done.sim == {"named": None}
