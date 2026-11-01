"""The pipeline as a LangGraph graph, with a SQLite checkpointer and the review pause (M7).

    load_fundamentals → load_market → build_baseline → fetch_news → cluster_events
        → extract_events (LLM) → propose_shocks (LLM) → review_shocks (pause for a person)
        → simulate → write_report

The checkpointer (`langgraph-checkpoint-sqlite`) writes the full state after every node into the
same `warren.db` (Decision 2: one system of record), on its own connection; WAL mode lets it write
while the nodes' connection reads. Durability is `sync`: a checkpoint is on disk before the next
node starts. A failed pipeline resumes from its last checkpoint, re-running only the failed node;
a pipeline paused for review resumes with the answers. The checkpoints are a resumable,
step-by-step record, not a tamper-evident one: anyone with the file can edit a row.
"""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from domains.analysis.runs import code_version
from domains.evaluation.cases import CASES_PATH, load_cases
from domains.llm import calls
from domains.orchestration import nodes, report
from domains.orchestration.state import PipelineState
from domains.orchestration.telemetry import Emitter, check_tracing_off, traced

NODE_ORDER = (
    "load_fundamentals",
    "load_market",
    "build_baseline",
    "fetch_news",
    "cluster_events",
    "extract_events",
    "propose_shocks",
    "review_shocks",
    "simulate",
    "write_report",
)
LIVE_DAYS = 7  # a date this recent is live use: a person may review its shocks (no hindsight)
DEFAULT_SAMPLES = 10_000


@dataclass(frozen=True)
class Folders:
    reports: Path
    telemetry: Path


@dataclass
class Outcome:
    pipeline_id: str
    status: str  # done | waiting_review | failed
    state: PipelineState | None
    waiting: dict | None = None  # what the review pause asks, when waiting_review
    error: BaseException | None = None


def _db_file(conn: sqlite3.Connection) -> str:
    return conn.execute("PRAGMA database_list").fetchone()["file"]


@contextmanager
def checkpointer(conn: sqlite3.Connection):
    """LangGraph's SQLite saver on its own connection to the same database file."""
    with closing(sqlite3.connect(_db_file(conn), check_same_thread=False, timeout=10.0)) as c:
        c.execute("PRAGMA journal_mode=WAL;")
        saver = SqliteSaver(c)
        saver.setup()
        yield saver


def write_report(state: PipelineState, deps: nodes.Deps, folders: Folders) -> dict:
    path = report.write_report(deps.conn, state, folders.reports,
                               folders.telemetry / f"{state.pipeline_id}.jsonl")  # fmt: skip
    with deps.conn:
        deps.conn.execute(
            "UPDATE pipeline_runs SET report_path = ? WHERE pipeline_id = ?",
            (str(path), state.pipeline_id),
        )
    return {"report_path": str(path)}


def build(deps: nodes.Deps, folders: Folders, saver: SqliteSaver, pipeline_id: str):
    """The compiled graph; every node wrapped by the telemetry emitter."""
    emitter = Emitter(folders.telemetry / f"{pipeline_id}.jsonl")
    graph = StateGraph(PipelineState)
    for name in NODE_ORDER:
        if name == "write_report":

            def fn(s, name=name):
                return write_report(s, deps, folders)
        else:

            def fn(s, name=name):
                return getattr(nodes, name)(s, deps)

        graph.add_node(name, traced(name, fn, emitter, deps.conn))
    graph.add_edge(START, NODE_ORDER[0])
    for a, b in zip(NODE_ORDER, NODE_ORDER[1:], strict=False):
        graph.add_edge(a, b)
    graph.add_edge(NODE_ORDER[-1], END)
    return graph.compile(checkpointer=saver)


def is_case(ticker: str, as_of: date) -> bool:
    return any(c.ticker == ticker.upper() and c.event_date == as_of for c in load_cases(CASES_PATH))


def default_review(as_of: date, today: date) -> str:
    """Auto for a date more than a week old (a person today knows what came next), else manual."""
    return "manual" if (today - as_of).days <= LIVE_DAYS else "auto"


def new_pipeline_id(conn: sqlite3.Connection, ticker: str, as_of: date) -> str:
    prefix = f"{ticker.upper()}_{as_of.isoformat()}_p"
    n = conn.execute(
        "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_id LIKE ?", (prefix + "%",)
    ).fetchone()[0]
    return f"{prefix}{n + 1}"


def _config(pipeline_id: str) -> dict:
    return {"configurable": {"thread_id": pipeline_id}}


def _set_status(conn: sqlite3.Connection, pipeline_id: str, status: str) -> None:
    finished = status in ("done", "failed")
    with conn:
        conn.execute(
            "UPDATE pipeline_runs SET status = ?, finished_at = CASE WHEN ? THEN "
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now') ELSE NULL END WHERE pipeline_id = ?",
            (status, finished, pipeline_id),
        )


def _drive(app, payload, pipeline_id: str, conn: sqlite3.Connection) -> Outcome:
    try:
        app.invoke(payload, _config(pipeline_id), durability="sync")
    except Exception as e:  # the failed node's telemetry line has the error; resume retries it
        _set_status(conn, pipeline_id, "failed")
        snapshot = app.get_state(_config(pipeline_id))
        values = PipelineState(**snapshot.values) if snapshot.values else None
        return Outcome(pipeline_id, "failed", values, error=e)
    snapshot = app.get_state(_config(pipeline_id))
    state = PipelineState(**snapshot.values)
    if snapshot.interrupts:
        _set_status(conn, pipeline_id, "waiting_review")
        return Outcome(pipeline_id, "waiting_review", state, waiting=snapshot.interrupts[0].value)
    _set_status(conn, pipeline_id, "done")
    return Outcome(pipeline_id, "done", state)


def start(
    deps: nodes.Deps,
    folders: Folders,
    ticker: str,
    as_of: date,
    variants: list[str] | None = None,
    review: str | None = None,
    seed: int | None = None,
    n_samples: int = DEFAULT_SAMPLES,
    budget: int = calls.DEFAULT_BUDGET,
    offline: bool = False,
    refresh: bool = False,
) -> Outcome:
    """Start a pipeline and run it until it ends or pauses for review."""
    check_tracing_off()
    conn, ticker = deps.conn, ticker.upper()
    variants = variants or (["named", "masked"] if is_case(ticker, as_of) else ["named"])
    review = review or default_review(as_of, deps.today())
    seed = int(np.random.SeedSequence().entropy % 2**63) if seed is None else seed
    pipeline_id = new_pipeline_id(conn, ticker, as_of)
    telemetry_path = folders.telemetry / f"{pipeline_id}.jsonl"
    state = PipelineState(pipeline_id=pipeline_id, ticker=ticker, as_of=as_of, variants=variants,
                          review=review, seed=seed, n_samples=n_samples, budget=budget,
                          offline=offline, refresh=refresh, started_at=deps.now())  # fmt: skip
    with conn:
        conn.execute(
            "INSERT INTO pipeline_runs (pipeline_id, ticker, as_of, variants, review, seed, "
            "n_samples, status, telemetry_path, code_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
            (pipeline_id, ticker, as_of.isoformat(), ",".join(variants), review, seed,
             n_samples, str(telemetry_path), code_version()),
        )  # fmt: skip
    with checkpointer(conn) as saver:
        return _drive(build(deps, folders, saver, pipeline_id), state, pipeline_id, conn)


def resume(
    deps: nodes.Deps,
    folders: Folders,
    pipeline_id: str,
    answers: dict | None = None,
    budget: int | None = None,
) -> Outcome:
    """Continue a failed pipeline, or a paused one with the review answers."""
    check_tracing_off()
    conn = deps.conn
    row = conn.execute("SELECT * FROM pipeline_runs WHERE pipeline_id = ?", (pipeline_id,))
    row = row.fetchone()
    if row is None:
        raise nodes.PipelineError(f"no pipeline {pipeline_id}")
    with checkpointer(conn) as saver:
        app = build(deps, folders, saver, pipeline_id)
        snapshot = app.get_state(_config(pipeline_id))
        if row["status"] == "done" or not snapshot.next:
            return Outcome(pipeline_id, "done", PipelineState(**snapshot.values))
        if snapshot.interrupts:
            if answers is None:
                return Outcome(pipeline_id, "waiting_review", PipelineState(**snapshot.values),
                               waiting=snapshot.interrupts[0].value)  # fmt: skip
            # sent as JSON text: LangGraph reads a dict given to `resume` as a map from interrupt
            # ids to answers, and checkpoints keep the text as it was given
            payload = Command(resume=json.dumps(answers, sort_keys=True, default=str))
        else:
            if budget is not None:
                app.update_state(_config(pipeline_id), {"budget": budget})
            payload = None
        _set_status(conn, pipeline_id, "running")
        return _drive(app, payload, pipeline_id, conn)


def history(conn: sqlite3.Connection, folders: Folders, pipeline_id: str) -> list[tuple]:
    """Every checkpoint after a node, oldest first: (step, node, the state fields it changed)."""
    with checkpointer(conn) as saver:
        app = build(nodes.Deps(conn=conn), folders, saver, pipeline_id)
        snaps = list(app.get_state_history(_config(pipeline_id)))[::-1]
    out = []
    for before, after in zip(snaps, snaps[1:], strict=False):
        if not before.next or before.next[0] not in NODE_ORDER:
            continue
        changed = sorted(k for k, v in after.values.items() if before.values.get(k) != v)
        out.append((after.metadata.get("step"), before.next[0], changed))
    return out


def final_state(conn: sqlite3.Connection, folders: Folders, pipeline_id: str):
    """A done pipeline's last state, from its checkpoint; None when it is not done."""
    with checkpointer(conn) as saver:
        app = build(nodes.Deps(conn=conn), folders, saver, pipeline_id)
        snapshot = app.get_state(_config(pipeline_id))
    if not snapshot.values or snapshot.next:
        return None
    return PipelineState(**snapshot.values)
