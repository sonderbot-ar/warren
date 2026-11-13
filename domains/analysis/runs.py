"""Storing DCF runs, reproducing them from their stored assumptions (exit criterion of M2) and
rebuilding their assumptions from the data they were built from (M2.1)."""

import dataclasses
import json
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis import sources as src
from domains.analysis.coded import RUN_NOTE_CODES, Coded
from domains.analysis.math_engine import (
    USER_CHOICES,
    EngineError,
    EngineResult,
    UserChoice,
    build_inputs,
    post_check_notes,
)
from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.analysis.schemas import Assumption
from domains.analysis.text import REASON_WORDS, WARNING_LESSONS
from domains.fundamentals.concepts import (
    ConceptMapError,
    archived_concept_map,
    concept_map_in_force,
    concept_map_sha256,
)
from domains.fundamentals.universe import COVERAGE_FIELDS, coverage_fields
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
    "reading_rules_version",  # backlog #365; NULL on runs stored before it
)


_LOCKED: set[int] = set()  # connections inside write_lock


@contextmanager
def write_lock(conn: sqlite3.Connection) -> Iterator[None]:
    """One write transaction that takes SQLite's write lock at its start (BEGIN IMMEDIATE), so a
    count or lookup made inside it can't be overtaken by another writer before the insert that
    depends on it (backlog #176). Another writer waits up to the connection's timeout. Commits on
    success and rolls back on any error. A transaction the caller left open is committed first,
    as the commit at the end would have done anyway."""
    if id(conn) in _LOCKED:
        raise RuntimeError("write_lock is already held on this connection: it doesn't nest")
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    _LOCKED.add(id(conn))
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:  # SQLite may have rolled back already; keep the first error
            conn.execute("ROLLBACK")
        raise
    finally:
        _LOCKED.discard(id(conn))


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
    notes: list[Coded | str],
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
    return save_rows(
        conn,
        run,
        result.assumptions,
        outputs,
        notes,
        gaps,
        _next_run_id(prefix),
        sources=result.sources,
    )


def save_rows(
    conn: sqlite3.Connection,
    run,
    assumptions: list[Assumption],
    outputs: dict[tuple[str, str], float],
    notes: list[Coded | str],
    gaps: dict[tuple[str, str], dcf.Gap] | None,
    run_id: str | Callable[[sqlite3.Connection], str],
    parent_run_id: str | None = None,
    sources: dict[tuple[str, str], list[dict]] | None = None,
) -> str:
    """Store a run under `run_id` in one write transaction (`write_lock`): `run` gives its
    company, date and data snapshot (a mapping with the runs columns cik, ticker, as_of and
    SNAPSHOT_COLUMNS: an engine result's, or the parent's row for a what-if). `run_id` may be a
    function of the connection, called inside the transaction to number the run. `sources` (backlog
    #175) must cover every row (`sources.check`); a run is refused, storing nothing, otherwise."""
    gaps = gaps or {}
    for gap in gaps.values():
        _check_reason(gap.reason)
    if sources is None:
        raise ValueError("a run is stored with the sources of its rows (backlog #175)")
    src.check(assumptions, sources, child=parent_run_id is not None)
    version = code_version()  # a git call: kept outside the lock
    with write_lock(conn):
        if callable(run_id):
            run_id = run_id(conn)
        insert_rows(conn, run, assumptions, outputs, notes, gaps, run_id, parent_run_id, version)
        src.insert(conn, run_id, sources)
    return run_id


def insert_rows(
    conn: sqlite3.Connection,
    run,
    assumptions: list[Assumption],
    outputs: dict[tuple[str, str], float],
    notes: list[Coded | str],
    gaps: dict[tuple[str, str], dcf.Gap],
    run_id: str,
    parent_run_id: str | None,
    version: str,
) -> None:
    """The inserts behind `save_rows`, for a caller already inside `write_lock`. `notes` go to
    `runs.notes` as their texts, one per line, and to `run_notes` with their codes (backlog
    #172); a plain string is stored as `note_text`."""
    notes = [as_coded(n) for n in notes]
    columns = ("run_id", "cik", "ticker", "as_of", "code_version", *SNAPSHOT_COLUMNS)
    columns += ("notes", "parent_run_id")
    conn.execute(
        f"INSERT INTO runs ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        (
            run_id,
            run["cik"],
            run["ticker"],
            run["as_of"],
            version,
            *(run[column] for column in SNAPSHOT_COLUMNS),
            "\n".join(n.text for n in notes),
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
    insert_notes(conn, run_id, notes)


def as_coded(note: Coded | str) -> Coded:
    if isinstance(note, str):
        return Coded("note_text", {}, note)
    if note.code not in RUN_NOTE_CODES:
        raise ValueError(f"unknown run note code {note.code!r}")
    if "\n" in note.text:
        raise ValueError(f"a run note is one line: {note.text!r}")
    return note


def insert_notes(conn: sqlite3.Connection, run_id: str, notes: list[Coded]) -> None:
    conn.executemany(
        "INSERT INTO run_notes (run_id, position, code, params, text) VALUES (?, ?, ?, ?, ?)",
        [
            (run_id, i, n.code, json.dumps(n.params, sort_keys=True), n.text)
            for i, n in enumerate(notes)
        ],
    )


@dataclass(frozen=True)
class RunNotes:
    """A run's warnings as codes (backlog #172). `recorded` is False for a run whose notes have
    no codes stored (made before 0021 and not matched by the backfill): each line of its
    `runs.notes` is then a `note_text` with the English text only."""

    run_id: str
    recorded: bool
    notes: list[Coded]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "recorded": self.recorded,
            "notes": [{**dataclasses.asdict(n), "group": note_group(n.code)} for n in self.notes],
        }


def note_group(code: str) -> str | None:
    """The `text.WARNING_GROUPS` code a run note is sorted under (backlog #197); None for a
    line Warren could not code (`note_text`)."""
    lesson = WARNING_LESSONS.get(code)
    return lesson.group if lesson else None


def run_notes(conn: sqlite3.Connection, run_id: str) -> RunNotes:
    run = conn.execute("SELECT notes FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    rows = conn.execute(
        "SELECT code, params, text FROM run_notes WHERE run_id = ? ORDER BY position", (run_id,)
    ).fetchall()
    lines = _lines(run["notes"])
    if rows or not lines:
        notes = [_with_coverage(Coded(r["code"], json.loads(r["params"]), r["text"])) for r in rows]
        return RunNotes(run_id, True, notes)
    return RunNotes(run_id, False, [Coded("note_text", {}, line) for line in lines])


def _with_coverage(note: Coded) -> Coded:
    """A `beyond_history` note stored before backlog #196 lacks `reason`, `successor_cik` and
    `successor_name`: they are added on read from today's universe row with the note's own `cik`
    and `history_ends` (a fact about the company, not the run), with `filled_on_read` true so the
    provenance shows; all None when no row matches. The stored row is unchanged."""
    if note.code != "beyond_history" or set(COVERAGE_FIELDS) <= note.params.keys():
        return note
    found = coverage_fields(note.params.get("cik"), note.params.get("history_ends"))
    found = found or dict.fromkeys(COVERAGE_FIELDS)
    missing = {k: v for k, v in found.items() if k not in note.params}
    return Coded(note.code, {**note.params, **missing, "filled_on_read": True}, note.text)


def _lines(notes: str | None) -> list[str]:
    return [line for line in (notes or "").split("\n") if line]


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
    sources: dict = dataclasses.field(default_factory=dict, compare=False)  # rebuilt (#175)
    notes: list = dataclasses.field(default_factory=list, compare=False)  # rebuilt (#172)
    archived_map: bool = False  # read through the run's own, older concept map (#357)
    rules_version: int | None = None  # the run's reading rules (#365); None: not recorded

    @property
    def older_rules(self) -> bool:
        """Made under other reading rules than today's code, or with none recorded: today's code
        rebuilds it, so a difference in its rows is expected rather than a fault (#365)."""
        return self.rules_version != READING_RULES_VERSION

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
    A different concept map can change which tag is selected, so the facts are read through the
    run's own map, from its copy in concept_maps/ (backlog #357); a map with no copy is refused.
    """
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    if run["parent_run_id"] is not None:
        raise ValueError(
            f"{run_id} is a what-if of {run['parent_run_id']}: its rows are not meant to match "
            "the data; rebuild the parent"
        )
    own_map = run["concept_map_sha256"]
    archived = own_map != concept_map_sha256()
    if archived:
        try:
            archived_concept_map(own_map)
        except ConceptMapError as e:
            raise ValueError(f"{run_id}: {e}, it can't be rebuilt") from e
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
    with pin_fetches(pins), concept_map_in_force(conn, own_map):
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
    return Rebuild(
        run_id,
        len(stored),
        mismatches,
        result.sources,
        result.notes,
        archived_map=archived,
        rules_version=run["reading_rules_version"],
    )


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
    notes = result.notes + valuation_notes(result.assumptions, outputs, gaps)
    return save_run(conn, result, outputs, notes, gaps)


def valuation_notes(
    assumptions: list[Assumption],
    outputs: dict[tuple[str, str], float],
    gaps: dict[tuple[str, str], dcf.Gap],
) -> list[Coded]:
    """A baseline's notes after its build warnings: the post-checks, then one line for each
    value per share with no value."""
    notes = post_check_notes(assumptions, outputs)
    for (name, _period), gap in sorted(gaps.items()):
        bound = name.removeprefix("value_per_share_") if name != "value_per_share" else "base"
        label = name.removeprefix("value_per_share_").replace("_", " ")
        notes.append(
            Coded(
                "no_value_per_share",
                {"bound": bound, "reason": gap.reason},
                f"No value per share at {label}: {REASON_WORDS[gap.reason]}",
            )
        )
    return notes


NOTES_BACKFILL = ("filled", "already_recorded", "no_notes", "text_differs", "failed")


def backfill_notes(
    conn: sqlite3.Connection, run_id: str, today: date | None = None
) -> tuple[str, str]:
    """Give a run stored before 0021 its notes as codes (backlog #172). A baseline's build
    warnings come from rebuilding it from its pinned data (as `rebuild` does); its post-checks and
    missing bounds, and a what-if's post-checks, from its stored rows. They are stored only when
    their texts, joined, equal `runs.notes` byte for byte. Returns (status, detail), status one of
    NOTES_BACKFILL; stores nothing otherwise."""
    from domains.market.store import MarketDataError

    run = conn.execute(
        "SELECT notes, parent_run_id FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    if conn.execute("SELECT 1 FROM run_notes WHERE run_id = ?", (run_id,)).fetchone():
        return "already_recorded", ""
    if not _lines(run["notes"]):
        return "no_notes", ""
    rows = load_assumptions(conn, run_id)
    outputs, gaps = dcf.outputs_and_gaps(rows)
    try:
        if run["parent_run_id"] is None:
            notes = rebuild(conn, run_id, today=today).notes + valuation_notes(rows, outputs, gaps)
        else:
            notes = post_check_notes(rows, outputs)
    except (ValueError, EngineError, MarketDataError) as e:
        return "failed", str(e)
    if "\n".join(n.text for n in notes) != run["notes"]:
        stored, made = _lines(run["notes"]), [n.text for n in notes]
        first = next(
            (f"line {i + 1}" for i, (a, b) in enumerate(zip(stored, made, strict=False)) if a != b),
            f"{len(stored)} lines stored, {len(made)} made",
        )
        return "text_differs", first
    with write_lock(conn):
        if conn.execute("SELECT 1 FROM run_notes WHERE run_id = ?", (run_id,)).fetchone():
            return "already_recorded", ""
        insert_notes(conn, run_id, [as_coded(n) for n in notes])
    return "filled", ""
