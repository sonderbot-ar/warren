"""The pipeline's nodes (M7): each one calls the M1–M6 library and returns the state it changed.

A node is `node(state, deps) -> dict`. `deps` holds what can't be checkpointed (the connection, the
LLM client, the downloaders, the clock); tests pass fakes. No node adds a query of its own on
financial data: every read goes through a domain function that takes the as-of date. Every node is
safe to run twice (a resume re-runs a node from the top): the domain functions are idempotent, a
baseline or simulation is reused only when it was built from the same inputs, and the review
writes nothing before its answers are in.

Data freshness has one rule: a stored download is used when it was made on or after the as-of
date (for filings, after the as-of day ended in New York), else it is downloaded again, or refused
with `offline`. `refresh` downloads again once per pipeline: what was fetched after the pipeline
started counts as fresh.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from langgraph.types import interrupt

from domains.analysis import montecarlo, shocks
from domains.analysis.math_engine import load_user_assumptions
from domains.analysis.runs import load_assumptions, run_baseline, stored_choices
from domains.fundamentals.concepts import concept_map_sha256
from domains.fundamentals.ingest import ingest_company
from domains.fundamentals.universe import get_universe_company
from domains.llm import extract, propose, review
from domains.llm.client import LLMClient
from domains.market.prices import MARKET_INDEX, MARKET_INDEX_HISTORY_START, load_prices
from domains.market.store import MarketDataError, require_coverage, selected_fetch
from domains.market.yields import RISK_FREE_SERIES, load_yields
from domains.news import cluster, gdelt, store
from domains.news.matching import load_aliases, load_headline_rule
from domains.orchestration.state import PipelineState, SimSummary
from domains.orchestration.telemetry import batch_id

NEWS_DAYS = 7  # the case window: the 7 New York days ending on the as-of date (M5)


class PipelineError(RuntimeError):
    """A step can't run: missing data offline, a date not yet closed, inputs that disagree."""


@dataclass
class Deps:
    """What the nodes need that is not state. Defaults are the real sources."""

    conn: sqlite3.Connection
    llm: Callable[[], LLMClient] | None = None  # built on first use, so a key is read only then
    edgar: Callable[[], object] | None = None  # an EdgarClient
    prices_download: Callable | None = None
    yields_download: Callable | None = None
    gdelt_master: Callable[[], dict] | None = None
    gdelt_download: Callable[[str], bytes] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _client: LLMClient | None = field(default=None, repr=False)

    def client(self) -> LLMClient:
        if self._client is None:
            if self.llm is None:
                raise PipelineError("no LLM client configured")
            self._client = self.llm()
        return self._client

    def today(self) -> date:
        return self.now().date()


def _iso(ts: datetime) -> str:
    return store.iso(ts)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def check_closed(as_of: date, now: datetime) -> None:
    """The as-of day must have ended in New York, so news and prices never cover part of it."""
    if gdelt.known_by(as_of) > now:
        raise PipelineError(
            f"{as_of} has not ended in New York yet; run it after midnight New York time"
        )


# -- data -----------------------------------------------------------------------------------------


def load_fundamentals(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    universe = get_universe_company(state.ticker)
    company = conn.execute(
        "SELECT * FROM companies WHERE ticker = ?", (state.ticker.upper(),)
    ).fetchone()
    ingest = (
        conn.execute(
            "SELECT * FROM ingest_runs WHERE cik = ? ORDER BY run_id DESC LIMIT 1",
            (company["cik"],),
        ).fetchone()
        if company
        else None
    )
    fetched = _parse(ingest["companyfacts_fetched_at"]) if ingest else None
    fresh = fetched is not None and fetched >= gdelt.known_by(state.as_of)
    if state.refresh:
        fresh = fresh and fetched >= state.started_at
    if not fresh:
        if state.offline:
            raise PipelineError(
                f"{state.ticker}: no EDGAR download from after {state.as_of} is stored, and the "
                "run is offline"
            )
        client = deps.edgar() if deps.edgar else None
        ingest_company(conn, state.ticker, client=client, cik=universe.cik, refresh=True)
        company = conn.execute(
            "SELECT * FROM companies WHERE ticker = ?", (state.ticker.upper(),)
        ).fetchone()
        ingest = conn.execute(
            "SELECT * FROM ingest_runs WHERE cik = ? ORDER BY run_id DESC LIMIT 1",
            (company["cik"],),
        ).fetchone()
    return {"cik": company["cik"], "company": company["name"], "ingest_run_id": ingest["run_id"]}


MARKET_SERIES = (("yahoo", None), ("yahoo", MARKET_INDEX), ("fred", RISK_FREE_SERIES))


def load_market(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    ids = {}
    for source, symbol in MARKET_SERIES:
        symbol = symbol or state.ticker.upper()
        try:
            fetch = require_coverage(conn, source, symbol, state.as_of)
            stale = state.refresh and _parse(fetch["fetched_at"]) < state.started_at
        except MarketDataError:
            fetch, stale = None, True
        if stale:
            if state.offline:
                raise PipelineError(
                    f"{symbol}: no {source} download made on or after {state.as_of} is stored, "
                    "and the run is offline"
                )
            if source == "fred":
                kwargs = {"download": deps.yields_download} if deps.yields_download else {}
                load_yields(conn, symbol, refresh=True, now=deps.now, **kwargs)
            else:
                kwargs = {"download": deps.prices_download} if deps.prices_download else {}
                start = {"start": MARKET_INDEX_HISTORY_START} if symbol == MARKET_INDEX else {}
                load_prices(conn, symbol, refresh=True, now=deps.now, **kwargs, **start)
            fetch = require_coverage(conn, source, symbol, state.as_of)
        ids[f"{source}:{symbol}"] = fetch["fetch_id"]
    return {"market_fetch_ids": ids}


# -- baseline -------------------------------------------------------------------------------------


def _same_inputs(conn: sqlite3.Connection, run: sqlite3.Row, ticker: str) -> bool:
    """Was the stored run built from exactly what a new run would read now?"""
    latest = conn.execute(
        "SELECT run_id FROM ingest_runs WHERE cik = ? ORDER BY run_id DESC LIMIT 1",
        (run["cik"],),
    ).fetchone()
    fetches = (
        ("price_fetch_sha256", "yahoo", ticker),
        ("index_fetch_sha256", "yahoo", MARKET_INDEX),
        ("yield_fetch_sha256", "fred", RISK_FREE_SERIES),
    )
    if latest is None or run["ingest_run_id"] != latest["run_id"]:
        return False
    if run["concept_map_sha256"] != concept_map_sha256():
        return False
    for column, source, symbol in fetches:
        fetch = selected_fetch(conn, source, symbol)
        if fetch is None or run[column] != fetch["content_sha256"]:
            return False
    try:
        stored = stored_choices(load_assumptions(conn, run["run_id"]))
    except Exception:  # a choice that can no longer be read back: build a new run
        return False
    today = load_user_assumptions()
    return {k: c.value for k, c in stored.items()} == {k: c.value for k, c in today.items()}


def build_baseline(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    ticker = state.ticker.upper()
    runs = conn.execute(
        "SELECT * FROM runs WHERE ticker = ? AND as_of = ? AND seed IS NULL "
        "ORDER BY created_at DESC, run_id DESC",
        (ticker, state.as_of.isoformat()),
    ).fetchall()
    reused = next((r for r in runs if _same_inputs(conn, r, ticker)), None)
    run_id = reused["run_id"] if reused else run_baseline(conn, ticker, state.as_of)
    value = conn.execute(
        "SELECT value FROM run_outputs WHERE run_id = ? AND name = 'value_per_share'", (run_id,)
    ).fetchone()
    with conn:
        conn.execute(
            "UPDATE pipeline_runs SET run_id = ? WHERE pipeline_id = ?",
            (run_id, state.pipeline_id),
        )
    return {
        "run_id": run_id,
        "baseline_value_per_share": value["value"] if value else None,
        "baseline_reused": reused is not None,
    }


# -- news -----------------------------------------------------------------------------------------


def _window_read(conn: sqlite3.Connection, start: datetime, end: datetime, aliases) -> bool:
    """Every 15-minute slot of the window has a file read (or known missing) under these aliases."""
    rows = conn.execute(
        "SELECT file_ts, status, aliases_sha256 FROM news_files WHERE file_ts >= ? AND file_ts < ?",
        (_iso(start), _iso(end)),
    ).fetchall()
    done = {
        r["file_ts"]
        for r in rows
        if r["status"] in ("ok", "missing") and r["aliases_sha256"] == aliases.sha256
    }
    slots, slot = 0, start
    while slot < end:
        slots += 1
        slot += timedelta(minutes=15)
    return len(done) >= slots


def _file_counts(conn: sqlite3.Connection, start: datetime, end: datetime) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n, COALESCE(SUM(rows_kept), 0) AS kept FROM news_files "
        "WHERE file_ts >= ? AND file_ts < ? GROUP BY status",
        (_iso(start), _iso(end)),
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def fetch_news(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    check_closed(state.as_of, deps.now())
    aliases = load_aliases(conn)
    start, end = gdelt.window_bounds(state.as_of, NEWS_DAYS)
    if not _window_read(conn, start, end, aliases):
        if state.offline:
            raise PipelineError(
                f"the news window {_iso(start)} to {_iso(end)} is not fully read, and the run is "
                "offline"
            )
        master_list = deps.gdelt_master or (
            lambda: gdelt.parse_master_list(gdelt.http_download(gdelt.MASTER_LIST_URL).decode())
        )
        kwargs = {"download": deps.gdelt_download} if deps.gdelt_download else {}
        store.ingest_window(conn, master_list(), start, end, aliases, now=deps.now, **kwargs)
    kept = conn.execute(
        "SELECT COUNT(DISTINCT s.article_id) FROM article_sightings s "
        "JOIN article_companies c ON c.article_id = s.article_id AND c.file_url = s.file_url "
        "WHERE c.cik = ? AND s.seen_at >= ? AND s.seen_at < ?",
        (state.cik, _iso(start), _iso(end)),
    ).fetchone()[0]
    return {"news_files": _file_counts(conn, start, end), "articles_kept": kept}


def cluster_events(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    aliases = load_aliases(conn)
    run = cluster.run_events(conn, state.cik, state.as_of, aliases,
                             rule=load_headline_rule(conn, aliases))  # fmt: skip
    events = cluster.stored_events(conn, run)
    in_window = extract.choose_events(events, extract.window_start(state.as_of))
    return {"event_run_id": run, "events_total": len(events), "events_chosen": len(in_window)}


# -- LLM steps ------------------------------------------------------------------------------------


def extract_events(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    aliases = load_aliases(conn)
    rule = load_headline_rule(conn, aliases)
    chosen = extract.choose_events(
        cluster.stored_events(conn, state.event_run_id), extract.window_start(state.as_of)
    )
    out = {}
    if not chosen:  # nothing to classify: no call, so no key is needed
        for variant in state.variants:
            conn.execute(
                "INSERT OR REPLACE INTO case_llm_status (case_id, event_run_id, variant, "
                "events_total, events_chosen) VALUES (?, ?, ?, ?, 0)",
                (state.case_id, state.event_run_id, variant, state.events_total or 0),
            )
            out[variant] = {"events": 0, "ok": 0, "failed": 0, "not_about_company": 0}
        conn.commit()
        return {"classified": out}
    ids = extract.classify_case(conn, deps.client(), state.case_id, state.ticker, state.as_of,
                                aliases, rule, tuple(state.variants),
                                batch_id(state.pipeline_id, "extract_events"),
                                state.budget)  # fmt: skip
    latest = {v: propose.latest_event_run(conn, state.case_id, v) for v in state.variants}
    if set(latest.values()) != {state.event_run_id}:
        raise PipelineError(
            f"the news changed between steps: events {state.event_run_id[:12]} were clustered, "
            f"but {sorted(v[:12] for v in latest.values() if v)} were classified"
        )
    for variant, rows in ids.items():
        marks = ",".join("?" * len(rows))
        found = conn.execute(
            f"SELECT status, event_type FROM event_classifications "
            f"WHERE classification_id IN ({marks})",
            rows,
        ).fetchall()
        out[variant] = {
            "events": len(rows),
            "ok": sum(r["status"] == "ok" for r in found),
            "failed": sum(r["status"] == "failed" for r in found),
            "not_about_company": sum(r["event_type"] == extract.NOT_ABOUT for r in found),
        }
    return {"classified": out}


def _in_words(row: sqlite3.Row) -> str:
    return (
        f"{row['driver']} {row['direction']} {row['size']} {row['duration']} "
        f"from Q{row['start_quarter']}"
    )


def propose_shocks(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    aliases = load_aliases(conn)
    co = extract.company(conn, state.ticker)
    sets, words = {}, {}
    for variant in state.variants:
        rows = propose.case_events(conn, state.case_id, variant,
                                   *propose.current_keys()[2:], state.event_run_id)  # fmt: skip
        if not rows:
            sets[variant], words[variant] = None, []
            continue
        set_id = propose.propose_case(conn, deps.client(), state.case_id, co, state.as_of,
                                      state.run_id, aliases, variant,
                                      batch_id(state.pipeline_id, "propose_shocks"),
                                      state.budget, event_run_id=state.event_run_id)  # fmt: skip
        sets[variant] = set_id
        words[variant] = [
            _in_words(r)
            for r in conn.execute(
                "SELECT * FROM shock_proposals WHERE set_id = ? ORDER BY proposal_id", (set_id,)
            )
        ]
    return {"proposal_set": sets, "proposals": words}


# -- review ---------------------------------------------------------------------------------------


def open_proposals(conn: sqlite3.Connection, state: PipelineState) -> dict[str, list[dict]]:
    """Per variant, the proposals with no review status yet, as plain data for the reviewer."""
    out = {}
    for variant in state.variants:
        set_id = state.proposal_set.get(variant)
        if set_id is None:
            continue
        rows = conn.execute(
            "SELECT p.* FROM shock_proposals p JOIN proposal_sets s USING (set_id) "
            "WHERE p.set_id = ? AND p.status = 'proposed' AND s.status = 'ok' "
            "ORDER BY p.proposal_id",
            (set_id,),
        ).fetchall()
        if rows:
            out[variant] = [
                {"proposal_id": r["proposal_id"], "driver": r["driver"], "low": r["low"],
                 "base": r["base"], "high": r["high"], "start_period": r["start_quarter"],
                 "horizon": r["horizon"], "decay": r["decay"],
                 "rationale": review.rationale(r)}
                for r in rows
            ]  # fmt: skip
    return out


def review_shocks(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    pending = open_proposals(conn, state)
    if pending and state.review != "auto":
        # one interrupt for every variant, so a resume replays the same interrupts in order;
        # nothing is written before the answers are in and checked together
        problem = None
        while True:
            given = interrupt({"proposals": pending, "problem": problem})
            try:
                answers = json.loads(given) if isinstance(given, str) else given
            except ValueError:
                answers = None
            problem = review.check_answers(
                conn, [p["proposal_id"] for ps in pending.values() for p in ps], answers
            )
            if problem is None:
                break
    counts = {}
    for variant in state.variants:
        set_id = state.proposal_set.get(variant)
        status = (
            conn.execute("SELECT status FROM proposal_sets WHERE set_id = ?", (set_id,)).fetchone()
            if set_id is not None
            else None
        )
        if status is None or status["status"] != "ok":
            counts[variant] = {}
            continue
        if state.review == "auto":
            done = review.review_set(conn, set_id, auto=True, now=deps.now)
        else:
            by_id = {str(k): v for k, v in (answers or {}).items()} if pending else {}
            done = review.review_set(conn, set_id, ask=review.answer_from(by_id),
                                     reviewer="owner", now=deps.now)  # fmt: skip
        stored = conn.execute(
            "SELECT status, COUNT(*) AS n FROM shock_proposals WHERE set_id = ? GROUP BY status",
            (set_id,),
        ).fetchall()
        counts[variant] = {r["status"]: r["n"] for r in stored} | {
            f"new_{k}": v for k, v in done.items()
        }
    return {"reviewed": counts}


# -- simulation -----------------------------------------------------------------------------------


def simulate(state: PipelineState, deps: Deps) -> dict:
    conn = deps.conn
    out: dict[str, SimSummary | None] = {}
    for variant in state.variants:
        set_id = state.proposal_set.get(variant)
        shock_list = review.approved_shocks(conn, set_id) if set_id is not None else []
        if not shock_list:
            out[variant] = None
            continue
        sized_on = conn.execute("SELECT run_id FROM proposal_sets WHERE set_id = ?", (set_id,))
        sized_on = sized_on.fetchone()["run_id"]
        if sized_on != state.run_id:
            raise PipelineError(
                f"proposal set {set_id} was sized on {sized_on}, not on this pipeline's "
                f"baseline {state.run_id}"
            )
        digest = shocks.shocks_sha256(shock_list)
        stored = conn.execute(
            "SELECT sim_id FROM simulations WHERE run_id = ? AND seed = ? AND n_samples = ? "
            "AND shocks_sha256 = ? ORDER BY sim_id LIMIT 1",
            (state.run_id, state.seed, state.n_samples, digest),
        ).fetchone()
        sim_id = (
            stored["sim_id"]
            if stored
            else montecarlo.save_simulation(
                conn, state.run_id, shock_list, state.n_samples, state.seed
            )  # fmt: skip
        )
        vps = conn.execute(
            "SELECT p10, p50, p90 FROM simulation_outputs WHERE sim_id = ? AND "
            "name = 'value_per_share'",
            (sim_id,),
        ).fetchone()
        out[variant] = SimSummary(sim_id=sim_id, p10=vps["p10"], p50=vps["p50"], p90=vps["p90"])
    return {"sim": out}
