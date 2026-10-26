"""Storing DCF runs and reproducing them from their stored assumptions (exit criterion of M2)."""

import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from domains.analysis import dcf
from domains.analysis.math_engine import EngineResult, UserChoice, build_inputs, post_checks
from domains.analysis.schemas import Assumption

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
    notes = result.warnings + post_checks(outputs[("terminal_share", "-")])
    for name in ("erp_minus_1se", "erp_plus_1se"):
        if (f"value_per_share_{name}", "-") not in outputs:
            notes.append(f"No value per share at {name.replace('_', ' ')}: WACC ≤ terminal growth")
    return save_run(conn, result, outputs, notes)
