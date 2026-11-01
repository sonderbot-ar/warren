"""Telemetry (Decision 5): one JSON line when a node starts and one when it ends, in a local file.

A decoupled observer: nodes don't know it exists. `traced` wraps a node, times it, and appends
`TelemetryEvent` lines to `data/telemetry/<pipeline_id>.jsonl`. LLM nodes run with the batch id
`<pipeline_id>:<node>`, so their models and tokens are summed from `llm_calls` (every attempt,
M6), never estimated. A line holds no inputs, prompts or environment, so it can't hold a key.
"""

import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from langgraph.errors import GraphInterrupt

from shared_kernel.schemas import LLMUsage, TelemetryEvent

LLM_NODES = ("extract_events", "propose_shocks")
TRACING_VARIABLES = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")


class TelemetryError(RuntimeError):
    pass


def check_tracing_off(environ=os.environ) -> None:
    """LangGraph can send traces to an outside service (LangSmith); Decision 5 keeps telemetry
    local, so a pipeline refuses to start when that is switched on."""
    on = [v for v in TRACING_VARIABLES if environ.get(v, "").strip().lower() in ("1", "true")]
    if on:
        raise TelemetryError(
            f"{', '.join(on)} is on, which would send traces outside Warren; unset it "
            "(Decision 5: telemetry is a local file)"
        )


def batch_id(pipeline_id: str, node: str) -> str:
    return f"{pipeline_id}:{node}"


def llm_usage(conn: sqlite3.Connection, batch: str) -> list[LLMUsage]:
    """Calls and tokens per model for one batch, from `llm_calls`."""
    rows = conn.execute(
        "SELECT model, COUNT(*) AS calls, SUM(status != 'ok') AS invalid, "
        "COALESCE(SUM(input_tokens), 0) AS i, COALESCE(SUM(output_tokens), 0) AS o "
        "FROM llm_calls WHERE batch_id = ? GROUP BY model ORDER BY model",
        (batch,),
    ).fetchall()
    return [
        LLMUsage(
            model=r["model"],
            calls=r["calls"],
            invalid=r["invalid"] or 0,
            input_tokens=r["i"],
            output_tokens=r["o"],
        )  # fmt: skip
        for r in rows
    ]


class Emitter:
    """Appends telemetry lines to one pipeline's file."""

    def __init__(self, path: Path):
        self.path = path

    def emit(self, event: TelemetryEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read(self) -> list[TelemetryEvent]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [TelemetryEvent.model_validate_json(line) for line in lines if line]


def error_text(e: BaseException) -> str:
    """The error's type and first line of its message; never a traceback."""
    message = str(e).strip().splitlines()
    return f"{type(e).__name__}: {message[0] if message else ''}".strip()


def traced(
    node: str,
    fn: Callable,
    emitter: Emitter,
    conn: sqlite3.Connection,
    clock: Callable[[], float] = time.monotonic,
) -> Callable:
    """`fn(state)` with a start line before it and an ok, error or interrupted line after."""

    def run(state):
        pid = state.pipeline_id
        emitter.emit(TelemetryEvent(pipeline_id=pid, node=node, status="started"))
        start = clock()

        def end(status, error=None):
            usage = llm_usage(conn, batch_id(pid, node)) if node in LLM_NODES else []
            emitter.emit(TelemetryEvent(pipeline_id=pid, node=node, status=status,
                                        duration_ms=max(0, round(1000 * (clock() - start))),
                                        error=error, llm=usage))  # fmt: skip

        try:
            out = fn(state)
        except GraphInterrupt:
            end("interrupted")
            raise
        except Exception as e:
            end("error", error_text(e))
            raise
        end("ok")
        return out

    return run
