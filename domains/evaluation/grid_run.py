"""Run the grid cases through the one-command pipeline (M10 Step 2).

Date by date, so each GDELT week is read once and then serves every company on that date
(`nodes.fetch_news` downloads a window only when it isn't fully read). Post-cutoff dates run
first, newest first, then the pre-cutoff grid from the newest date back, so a stop leaves a dated,
usable subset. A case already done is skipped; a failed one is resumed. One spending cap covers
the whole command: before each case the cost of every AI call made since the command started (or
since `--since`, so a restarted run still counts what the first one spent) is
added up from `llm_calls`, and the command stops cleanly when the next case could pass the cap.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from domains.evaluation import grid
from domains.evaluation.cases import Case
from domains.evaluation.harness import case_seed
from domains.llm import calls

# US dollars per million input / output tokens, as published by Anthropic and read in M6 Step 8
# (docs/designs/m6-llm-steps.md, Step 8 notes). Used only to keep a run under the owner's cap;
# prices change, so a stored cost is always recomputable from the stored tokens.
PRICES_USD_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
RESERVE_USD = 0.50  # the most one case (two variants) may cost; M7's measured date cost ~$0.04
ESTIMATE_USD = 0.08  # per case before any grid case has run (M7 Step 6, two variants)


class GridRunError(RuntimeError):
    """The grid run can't go on (a model with no price, or a bad setup)."""


@dataclass
class GridSummary:
    done_before: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    not_run: list[str] = field(default_factory=list)
    spent_usd: float = 0.0
    stopped: str | None = None  # why the run stopped early, if it did


def ordered(cases: list[Case]) -> list[Case]:
    """Post-cutoff dates first, newest first; then pre-cutoff, newest first; universe order kept
    within a date."""
    position = {c.case_id: i for i, c in enumerate(cases)}
    return sorted(
        cases,
        key=lambda c: (not grid.is_post_cutoff(c.event_date), -c.event_date.toordinal(),
                       position[c.case_id]),
    )  # fmt: skip


def spent_usd(conn: sqlite3.Connection, since: str) -> float:
    """What the AI calls made at or after `since` (ISO UTC) cost, at PRICES_USD_PER_MTOK."""
    total = 0.0
    rows = conn.execute(
        "SELECT model, COALESCE(SUM(input_tokens), 0) AS i, COALESCE(SUM(output_tokens), 0) AS o "
        "FROM llm_calls WHERE created_at >= ? GROUP BY model",
        (since,),
    ).fetchall()
    for model, i, o in rows:
        if model not in PRICES_USD_PER_MTOK:
            raise GridRunError(f"no price for model {model!r}: add it to PRICES_USD_PER_MTOK")
        p_in, p_out = PRICES_USD_PER_MTOK[model]
        total += (i * p_in + o * p_out) / 1_000_000
    return total


def latest_pipeline(conn: sqlite3.Connection, case: Case) -> sqlite3.Row | None:
    """The newest pipeline for the case's company and date that ran both variants."""
    return conn.execute(
        "SELECT pipeline_id, status FROM pipeline_runs WHERE ticker = ? AND as_of = ? "
        "AND variants = 'named,masked' ORDER BY started_at DESC, pipeline_id DESC LIMIT 1",
        (case.ticker, case.event_date.isoformat()),
    ).fetchone()


def pending(conn: sqlite3.Connection, cases: list[Case]) -> tuple[list[Case], list[str]]:
    """The cases still to run, in run order, and the ids already done."""
    todo, done = [], []
    for case in ordered(cases):
        row = latest_pipeline(conn, case)
        (done.append(case.case_id) if row and row["status"] == "done" else todo.append(case))
    return todo, done


def estimate_usd(conn: sqlite3.Connection, n_cases: int) -> float:
    """A cost estimate for n cases: ESTIMATE_USD each (the measured M7 date, both variants)."""
    return n_cases * ESTIMATE_USD


def run_grid(
    conn: sqlite3.Connection,
    cases: list[Case],
    max_usd: float,
    start: Callable,
    resume: Callable,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    budget: int = calls.DEFAULT_BUDGET,
    log: Callable[[str], None] = print,
    since: str | None = None,
) -> GridSummary:
    """Run every pending case until done or the cap would be passed.

    `start(ticker, as_of, seed, budget)` and `resume(pipeline_id, budget)` return a
    `graph.Outcome`; the command line binds them to the real graph."""
    since = since or now().strftime("%Y-%m-%dT%H:%M:%SZ")
    todo, summary_done = pending(conn, cases)
    summary = GridSummary(done_before=summary_done)
    for i, case in enumerate(todo):
        summary.spent_usd = spent_usd(conn, since)
        if summary.spent_usd + RESERVE_USD > max_usd:
            summary.stopped = (
                f"cap: ${summary.spent_usd:.2f} spent of ${max_usd:.2f}, and a case may cost up "
                f"to ${RESERVE_USD:.2f}"
            )
            summary.not_run = [c.case_id for c in todo[i:]]
            break
        row = latest_pipeline(conn, case)
        if row is not None and row["status"] in ("failed", "waiting_review"):
            out = resume(row["pipeline_id"], budget)
        else:
            out = start(case.ticker, case.event_date, case_seed(case.case_id), budget)
        if out.status == "done":
            summary.done.append(case.case_id)
            log(f"done    {case.case_id}  {out.pipeline_id}")
            continue
        reason = str(out.error) if out.error else out.status
        summary.failed[case.case_id] = reason
        log(f"FAILED  {case.case_id}  {out.pipeline_id}: {reason}")
        if isinstance(out.error, calls.BudgetSpent):
            summary.stopped = f"token budget spent on {case.case_id}"
            summary.not_run = [c.case_id for c in todo[i + 1 :]]
            break
    summary.spent_usd = spent_usd(conn, since)
    return summary
