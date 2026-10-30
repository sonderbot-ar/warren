"""The case library (M3): historical events and rule-dated controls the harness scores.

The file is checked in and committed before any batch runs; each batch records its SHA-256, so
the library can't be tuned to the results without that showing. Selection rules are in
docs/designs/m3-evaluation-harness.md (Case library).
"""

import csv
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from domains.analysis.math_engine import SUPPORTED_FROM
from domains.fundamentals.universe import PHASE1_UNIVERSE

CASES_PATH = Path(__file__).parent / "cases.csv"
CONTROL_CLEARANCE_DAYS = 120  # a control sits at least this far from any event of its company
EVENT_TYPES = {
    "guidance",
    "m_and_a",
    "litigation",
    "regulation",
    "supply_chain",
    "macro",
    "restructuring",
    "control",
}
COLUMNS = (
    "case_id",
    "ticker",
    "event_date",
    "event_type",
    "description",
    "horizon_quarters",
    "selected_because",
    "source_url",
    "scope_change",
)


class CaseError(ValueError):
    """A row of the case file breaks a selection rule or is malformed."""


@dataclass(frozen=True)
class Case:
    case_id: str
    ticker: str
    event_date: date
    event_type: str
    description: str
    horizon_quarters: int
    selected_because: str
    source_url: str
    scope_change: str

    @property
    def is_control(self) -> bool:
        return self.event_type == "control"


def cases_sha256(path: Path = CASES_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse(row: dict[str, str], line: int, tickers: set[str]) -> Case:
    where = f"cases line {line}"
    try:
        event_date = date.fromisoformat(row["event_date"])
        horizon = int(row["horizon_quarters"])
    except (TypeError, ValueError) as e:
        raise CaseError(f"{where}: bad date or horizon ({e})") from e
    case = Case(
        case_id=row["case_id"].strip(),
        ticker=row["ticker"].strip().upper(),
        event_date=event_date,
        event_type=row["event_type"].strip(),
        description=row["description"].strip(),
        horizon_quarters=horizon,
        selected_because=row["selected_because"].strip(),
        source_url=(row.get("source_url") or "").strip(),
        scope_change=(row.get("scope_change") or "").strip(),
    )
    problems = []
    if case.case_id != f"{case.ticker}_{case.event_date.isoformat()}":
        problems.append("case_id must be <TICKER>_<event_date>")
    if case.ticker not in tickers:
        problems.append(f"{case.ticker} is not in the universe")
    if case.event_date < SUPPORTED_FROM:
        problems.append(f"event date before {SUPPORTED_FROM} (the engine's first as-of date)")
    if case.event_type not in EVENT_TYPES:
        problems.append(f"unknown event type {case.event_type!r}")
    if not 1 <= case.horizon_quarters <= 4:
        problems.append("horizon must be 1-4 quarters")
    if not case.description or not case.selected_because:
        problems.append("description and selected_because are required")
    if case.is_control and not case.selected_because.startswith("control rule"):
        problems.append("a control must be admitted by the control rule")
    if not case.is_control and not case.source_url.startswith("https://"):
        problems.append("an event needs a source URL")
    if problems:
        raise CaseError(f"{where} ({case.case_id}): " + "; ".join(problems))
    return case


def load_cases(path: Path = CASES_PATH, tickers: set[str] | None = None) -> list[Case]:
    """Every case in the file, validated; fails on the first bad row or a duplicate."""
    tickers = tickers if tickers is not None else {c.ticker for c in PHASE1_UNIVERSE}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise CaseError(f"case file columns must be {COLUMNS}, got {reader.fieldnames}")
        cases = [_parse(row, i, tickers) for i, row in enumerate(reader, start=2)]
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise CaseError(f"duplicate case {case.case_id}")
        seen.add(case.case_id)
    for control in (c for c in cases if c.is_control):
        for event in (c for c in cases if c.ticker == control.ticker and not c.is_control):
            if abs((control.event_date - event.event_date).days) < CONTROL_CLEARANCE_DAYS:
                raise CaseError(
                    f"control {control.case_id} is within {CONTROL_CLEARANCE_DAYS} days of "
                    f"{event.case_id}: move it forward one fiscal quarter"
                )
    return cases


def store_cases(conn: sqlite3.Connection, cases: list[Case]) -> None:
    """Write the cases to eval_cases (replacing earlier versions of the same case ids)."""
    rows = []
    for case in cases:
        company = conn.execute(
            "SELECT cik FROM companies WHERE ticker = ?", (case.ticker,)
        ).fetchone()
        if company is None:
            raise CaseError(f"{case.case_id}: {case.ticker} has not been ingested")
        rows.append(
            (
                case.case_id,
                case.ticker,
                company["cik"],
                case.event_date.isoformat(),
                case.event_type,
                case.description,
                case.horizon_quarters,
                case.selected_because,
                case.source_url,
                case.scope_change,
            )
        )
    with conn:
        conn.executemany(
            "INSERT INTO eval_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (case_id) DO UPDATE SET ticker = excluded.ticker, cik = excluded.cik, "
            "event_date = excluded.event_date, event_type = excluded.event_type, "
            "description = excluded.description, horizon_quarters = excluded.horizon_quarters, "
            "selected_because = excluded.selected_because, source_url = excluded.source_url, "
            "scope_change = excluded.scope_change",
            rows,
        )
