"""Storing DCF runs, reproducing them from their stored assumptions (exit criterion of M2) and
rebuilding their assumptions from the data they were built from (M2.1)."""

import dataclasses
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis.math_engine import (
    USER_CHOICES,
    EngineError,
    EngineResult,
    UserChoice,
    build_inputs,
    post_checks,
)
from domains.analysis.schemas import Assumption
from domains.analysis.text import REASON_WORDS
from domains.fundamentals.concepts import concept_map_sha256
from domains.market.prices import MARKET_INDEX
from domains.market.store import fetch_with_hash, pin_fetches
from domains.market.yields import RISK_FREE_SERIES

REPO_ROOT = Path(__file__).resolve().parents[2]
CENT = 0.005  # money outputs must agree to the cent
RATIO_TOLERANCE = 1e-9  # rates and shares of value, which a cent would not test
RATIOS = {"cost_of_equity", "wacc", "terminal_share", "discount_factor"}


def code_version() -> str:
    """The git commit the code runs from, with '+dirty' when there are uncommitted changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("+dirty" if status else "")


SNAPSHOT_COLUMNS = (
    "ingest_run_id",
    "concept_map_sha256",
    "price_fetch_sha256",
    "index_fetch_sha256",
    "yield_fetch_sha256",
)


@contextmanager
def write_lock(conn: sqlite3.Connection) -> Iterator[None]:
    """One write transaction that takes SQLite's write lock at its start (BEGIN IMMEDIATE), so a
    count or lookup made inside it can't be overtaken by another writer before the insert that
    depends on it (backlog #176). Another writer waits up to the connection's timeout. Commits on
    success and rolls back on any error. A transaction the caller left open is committed first,
    as the commit at the end would have done anyway."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _next_run_id(prefix: str) -> Callable[[sqlite3.Connection], str]:
    def allocate(conn: sqlite3.Connection) -> str:
        # what-ifs (backlog #141) have their own ids and don't count
        count = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id LIKE ? AND parent_run_id IS NULL",
            (prefix + "%",),
        ).fetchone()[0]
        return f"{prefix}{count + 1}"

    return allocate


def save_run(
    conn: sqlite3.Connection,
    result: EngineResult,
    outputs: dict[tuple[str, str], float],
    notes: list[str],
    gaps: dict[tuple[str, str], dcf.Gap] | None = None,
) -> str:
    """Store a run's assumptions, outputs and the reasons for outputs it has no value for, in one
    transaction; returns its run id. The id is numbered inside that transaction, so two runs
    saved at once never get the same one."""
    run = {
        "cik": result.cik,
        "ticker": result.ticker,
        "as_of": result.as_of.isoformat(),
        **{column: result.snapshot[column] for column in SNAPSHOT_COLUMNS},
    }
    prefix = f"{result.ticker}_{result.as_of.isoformat()}_"
    return save_rows(conn, run, result.assumptions, outputs, notes, gaps, _next_run_id(prefix))


def save_rows(
    conn: sqlite3.Connection,
    run,
    assumptions: list[Assumption],
    outputs: dict[tuple[str, str], float],
    notes: list[str],
    gaps: dict[tuple[str, str], dcf.Gap] | None,
    run_id: str | Callable[[sqlite3.Connection], str],
    parent_run_id: str | None = None,
) -> str:
    """Store a run under `run_id` in one write transaction (`write_lock`): `run` gives its
    company, date and data snapshot (a mapping with the runs columns cik, ticker, as_of and
    SNAPSHOT_COLUMNS: an engine result's, or the parent's row for a what-if). `run_id` may be a
    function of the connection, called inside the transaction to number the run."""
    gaps = gaps or {}
    for gap in gaps.values():
        _check_reason(gap.reason)
    version = code_version()  # a git call: kept outside the lock
    with write_lock(conn):
        if callable(run_id):
            run_id = run_id(conn)
        insert_rows(conn, run, assumptions, outputs, notes, gaps, run_id, parent_run_id, version)
    return run_id


def insert_rows(
    conn: sqlite3.Connection,
    run,
    assumptions: list[Assumption],
    outputs: dict[tuple[str, str], float],
    notes: list[str],
    gaps: dict[tuple[str, str], dcf.Gap],
    run_id: str,
    parent_run_id: str | None,
    version: str,
) -> None:
    """The inserts behind `save_rows`, for a caller already inside `write_lock`."""
    for gap in gaps.values():
        _check_reason(gap.reason)
    conn.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256, "
        "notes, parent_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            run["cik"],
            run["ticker"],
            run["as_of"],
            version,
            *(run[column] for column in SNAPSHOT_COLUMNS),
            "\n".join(notes),
            parent_run_id,
        ),
    )
    conn.executemany(
        "INSERT INTO assumptions (run_id, name, period, value, source, method) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(run_id, a.name, a.period, a.value, a.source, a.method) for a in assumptions],
    )
    conn.executemany(
        "INSERT INTO run_outputs (run_id, name, period, value) VALUES (?, ?, ?, ?)",
        [(run_id, name, period, value) for (name, period), value in outputs.items()],
    )
    conn.executemany(
        "INSERT INTO run_output_gaps (run_id, name, period, reason, detail) VALUES (?, ?, ?, ?, ?)",
        [(run_id, n, p, g.reason, g.detail) for (n, p), g in gaps.items()],
    )


def _check_reason(reason: str) -> str:
    if reason not in fm.REASONS:
        raise ValueError(f"unknown reason {reason!r} for a missing output")
    return reason


def load_gaps(conn: sqlite3.Connection, run_id: str) -> dict[tuple[str, str], dcf.Gap]:
    """Why each output a run has no value for is missing. Empty for a run stored before 0013."""
    return {
        (r["name"], r["period"]): dcf.Gap(_check_reason(r["reason"]), r["detail"])
        for r in conn.execute(
            "SELECT name, period, reason, detail FROM run_output_gaps WHERE run_id = ?", (run_id,)
        )
    }


def load_assumptions(conn: sqlite3.Connection, run_id: str) -> list[Assumption]:
    rows = conn.execute(
        "SELECT name, period, value, source, method FROM assumptions WHERE run_id = ? "
        "ORDER BY name, period",
        (run_id,),
    ).fetchall()
    if not rows:
        raise ValueError(f"No run {run_id}")
    return [Assumption(**dict(r)) for r in rows]


def load_outputs(conn: sqlite3.Connection, run_id: str) -> dict[tuple[str, str], float]:
    return {
        (r["name"], r["period"]): r["value"]
        for r in conn.execute(
            "SELECT name, period, value FROM run_outputs WHERE run_id = ?", (run_id,)
        )
    }


@dataclass(frozen=True)
class Reproduction:
    run_id: str
    outputs_checked: int
    mismatches: list[tuple[str, str, float | None, float | None]]  # name, period, stored, now
    stored_code_version: str
    current_code_version: str
    # name, period, stored reason, reason now: a stored gap whose cause changed (backlog #9)
    gap_mismatches: list[tuple[str, str, str, str | None]] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.gap_mismatches


def reproduce(conn: sqlite3.Connection, run_id: str) -> Reproduction:
    """Value a stored run again from its assumption rows and compare every output to the cent."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    stored = load_outputs(conn, run_id)
    now, gaps_now = dcf.outputs_and_gaps(load_assumptions(conn, run_id))
    mismatches = []
    for key in sorted(stored.keys() | now.keys()):
        before, after = stored.get(key), now.get(key)
        tolerance = RATIO_TOLERANCE if key[0] in RATIOS else CENT
        if before is None or after is None or abs(before - after) > tolerance:
            mismatches.append((*key, before, after))
    # a run stored before 0013 has no gap rows: its missing outputs are checked above, not why
    gap_mismatches = [
        (*key, gap.reason, gaps_now[key].reason if key in gaps_now else None)
        for key, gap in sorted(load_gaps(conn, run_id).items())
        if key not in gaps_now or gaps_now[key].reason != gap.reason
    ]
    return Reproduction(
        run_id, len(stored), mismatches, run["code_version"], code_version(), gap_mismatches
    )


# Choices a run made before they existed may lack; the engine's rule for their absence applies
# (no terminal_method: Gordon on FCFF, as before M4).
CHOICES_ADDED_LATER = {"terminal_method"}


def stored_choices(rows: list[Assumption]) -> dict[str, UserChoice]:
    """The owner's choices a run used, read back from its own rows (not today's file)."""
    choices = {
        a.name: UserChoice.from_assumption(a)
        for a in rows
        if a.source == "user" and a.name in USER_CHOICES
    }
    missing = sorted(set(USER_CHOICES) - CHOICES_ADDED_LATER - set(choices))
    if missing:
        raise EngineError(f"the run stored no choice for {missing}")
    for choice in choices.values():
        # the engine doesn't read every method name, so one it no longer supports is refused here
        allowed = USER_CHOICES[choice.name]
        if (
            allowed is None
            and not choice.value.isdigit()
            or allowed
            and choice.value not in allowed
        ):
            raise EngineError(f"the run's {choice.name} {choice.value!r} is no longer supported")
    return choices


@dataclass(frozen=True)
class Rebuild:
    run_id: str
    rows_checked: int
    mismatches: list[tuple[str, str, str]]  # name, period, what differs

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def values_ok(self) -> bool:
        """Only method text differs: expected when the code that writes it changed since."""
        return all(what == "method" for _name, _period, what in self.mismatches)


def rebuild(
    conn: sqlite3.Connection,
    run_id: str,
    choices: dict[str, UserChoice] | None = None,
    today: date | None = None,
) -> Rebuild:
    """Build a stored run's assumption rows again from data and compare them row by row.

    The owner's choices are the ones the run stored, so a later edit of user_assumptions.csv
    changes nothing; passing `choices` rebuilds the run as if they had been different. Market
    queries are pinned to the downloads the run used (by content hash). Facts need no pin: the
    point-in-time query only sees filings public on the as-of date, and ingests only add facts.
    A different concept map can change which tag is selected, so it is refused.
    """
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    if run["parent_run_id"] is not None:
        raise ValueError(
            f"{run_id} is a what-if of {run['parent_run_id']}: its rows are not meant to match "
            "the data; rebuild the parent"
        )
    if run["concept_map_sha256"] != concept_map_sha256():
        raise ValueError(f"{run_id}: concept_map.csv changed since the run, it can't be rebuilt")
    pins = {
        (source, symbol): fetch_with_hash(conn, source, symbol, run[column])["fetch_id"]
        for source, symbol, column in (
            ("yahoo", run["ticker"], "price_fetch_sha256"),
            ("yahoo", MARKET_INDEX, "index_fetch_sha256"),
            ("fred", RISK_FREE_SERIES, "yield_fetch_sha256"),
        )
    }
    stored_rows = load_assumptions(conn, run_id)
    if choices is None:
        choices = stored_choices(stored_rows)
    elif not any(a.name == "terminal_method" for a in stored_rows):
        # made before the owner set terminal_method (M4): rebuild it under the rule it used
        choices = {k: v for k, v in choices.items() if k != "terminal_method"}
    with pin_fetches(pins):
        result = build_inputs(
            conn, run["ticker"], date.fromisoformat(run["as_of"]), choices=choices, today=today
        )
    stored = {(a.name, a.period): a for a in stored_rows}
    built = {(a.name, a.period): a for a in result.assumptions}
    mismatches = []
    for key in sorted(stored.keys() | built.keys()):
        before, after = stored.get(key), built.get(key)
        if before is None or after is None:
            mismatches.append((*key, "only in the stored run" if after is None else "only rebuilt"))
            continue
        for field in ("value", "source", "method"):
            if getattr(before, field) != getattr(after, field):
                mismatches.append((*key, field))
    return Rebuild(run_id, len(stored), mismatches)


def run_baseline(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date,
    choices: dict[str, UserChoice] | None = None,
    today: date | None = None,
) -> str:
    """Build, value and store a baseline DCF; returns the run id."""
    result = build_inputs(conn, ticker, as_of, choices=choices, today=today)
    outputs, gaps = dcf.outputs_and_gaps(result.assumptions)
    notes = result.warnings + post_checks(result.assumptions, outputs)
    for (name, _period), gap in sorted(gaps.items()):
        label = name.removeprefix("value_per_share_").replace("_", " ")
        notes.append(f"No value per share at {label}: {REASON_WORDS[gap.reason]}")
    return save_run(conn, result, outputs, notes, gaps)
