"""Storing DCF runs, reproducing them from their stored assumptions (exit criterion of M2) and
rebuilding their assumptions from the data they were built from (M2.1)."""

import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from domains.analysis import dcf
from domains.analysis.math_engine import (
    USER_CHOICES,
    EngineError,
    EngineResult,
    UserChoice,
    build_inputs,
    post_checks,
)
from domains.analysis.schemas import Assumption
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


def save_run(
    conn: sqlite3.Connection,
    result: EngineResult,
    outputs: dict[tuple[str, str], float],
    notes: list[str],
) -> str:
    """Store a run's assumptions and outputs in one transaction; returns its run id."""
    prefix = f"{result.ticker}_{result.as_of.isoformat()}_"
    count = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE run_id LIKE ?", (prefix + "%",)
    ).fetchone()[0]
    run_id = f"{prefix}{count + 1}"
    snap = result.snapshot
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
            "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256, "
            "notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                result.cik,
                result.ticker,
                result.as_of.isoformat(),
                code_version(),
                snap["ingest_run_id"],
                snap["concept_map_sha256"],
                snap["price_fetch_sha256"],
                snap["index_fetch_sha256"],
                snap["yield_fetch_sha256"],
                "\n".join(notes),
            ),
        )
        conn.executemany(
            "INSERT INTO assumptions (run_id, name, period, value, source, method) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(run_id, a.name, a.period, a.value, a.source, a.method) for a in result.assumptions],
        )
        conn.executemany(
            "INSERT INTO run_outputs (run_id, name, period, value) VALUES (?, ?, ?, ?)",
            [(run_id, name, period, value) for (name, period), value in outputs.items()],
        )
    return run_id


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

    @property
    def ok(self) -> bool:
        return not self.mismatches


def reproduce(conn: sqlite3.Connection, run_id: str) -> Reproduction:
    """Value a stored run again from its assumption rows and compare every output to the cent."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run {run_id}")
    stored = load_outputs(conn, run_id)
    now = dcf.run_outputs(load_assumptions(conn, run_id))
    mismatches = []
    for key in sorted(stored.keys() | now.keys()):
        before, after = stored.get(key), now.get(key)
        tolerance = RATIO_TOLERANCE if key[0] in RATIOS else CENT
        if before is None or after is None or abs(before - after) > tolerance:
            mismatches.append((*key, before, after))
    return Reproduction(run_id, len(stored), mismatches, run["code_version"], code_version())


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
    outputs = dcf.run_outputs(result.assumptions)
    notes = result.warnings + post_checks(result.assumptions, outputs)
    for name in ("erp_minus_1se", "erp_plus_1se"):
        if (f"value_per_share_{name}", "-") not in outputs:
            notes.append(f"No value per share at {name.replace('_', ' ')}: WACC ≤ terminal growth")
    return save_run(conn, result, outputs, notes)
