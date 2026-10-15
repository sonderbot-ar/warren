"""Concept map: Warren's canonical names and the XBRL tags behind them, in priority order.

concept_map.csv is the editable source; sync_concepts() copies it into the `concepts` table, which
is the enforced vocabulary (financial_facts can only reference tags that exist there).
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

CONCEPT_MAP_PATH = Path(__file__).parent / "concept_map.csv"
COLUMNS = [
    "canonical_name",
    "xbrl_concept",
    "priority",
    "unit",
    "period_type",
    "definition",
    "note",
]
UNITS = {"USD", "shares", "USD/shares"}
PERIOD_TYPES = {"duration", "instant"}
TAXONOMIES = ("us-gaap:", "dei:")


class ConceptMapError(ValueError):
    """The concept map CSV is invalid, or the database can't be synced to it."""


@dataclass(frozen=True)
class ConceptRow:
    canonical_name: str
    xbrl_concept: str
    priority: int
    unit: str
    period_type: str
    definition: str

    @property
    def taxonomy(self) -> str:
        return self.xbrl_concept.split(":", 1)[0]

    @property
    def tag(self) -> str:
        return self.xbrl_concept.split(":", 1)[1]


def load_concept_map(path: Path = CONCEPT_MAP_PATH) -> list[ConceptRow]:
    """Read and validate the concept map. Every problem found is reported at once."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ConceptMapError(f"Expected columns {COLUMNS}, got {reader.fieldnames}")
        raw = list(reader)

    errors, rows = [], []
    for line, r in enumerate(raw, start=2):
        if not r["priority"].isdigit():
            errors.append(f"line {line}: priority must be a positive integer")
            continue
        row = ConceptRow(
            canonical_name=r["canonical_name"].strip(),
            xbrl_concept=r["xbrl_concept"].strip(),
            priority=int(r["priority"]),
            unit=r["unit"].strip(),
            period_type=r["period_type"].strip(),
            definition=r["definition"].strip(),
        )
        if not row.xbrl_concept.startswith(TAXONOMIES):
            errors.append(f"line {line}: {row.xbrl_concept} must start with one of {TAXONOMIES}")
        if row.unit not in UNITS:
            errors.append(f"line {line}: unknown unit {row.unit!r}")
        if row.period_type not in PERIOD_TYPES:
            errors.append(f"line {line}: unknown period_type {row.period_type!r}")
        if not row.definition:
            errors.append(f"line {line}: definition is required")
        rows.append(row)

    tags = [r.xbrl_concept for r in rows]
    for tag in sorted({t for t in tags if tags.count(t) > 1}):
        errors.append(f"{tag} is mapped more than once (one tag maps to one canonical name)")

    for name in sorted({r.canonical_name for r in rows}):
        group = [r for r in rows if r.canonical_name == name]
        if sorted(r.priority for r in group) != list(range(1, len(group) + 1)):
            errors.append(f"{name}: priorities must be 1..{len(group)} with no gaps or repeats")
        for field in ("unit", "period_type", "definition"):
            if len({getattr(r, field) for r in group}) > 1:
                errors.append(f"{name}: every tag must share the same {field}")

    if errors:
        raise ConceptMapError("Invalid concept map:\n  " + "\n  ".join(errors))
    return rows


def sync_concepts(conn: sqlite3.Connection, rows: list[ConceptRow]) -> dict[str, int]:
    """Make the concepts table match the CSV, in one transaction.

    A tag removed from the CSV is deleted from the table; if stored facts still reference it the
    sync fails loudly, because silently keeping it would leave those facts in every query.
    """
    wanted = {r.xbrl_concept: r for r in rows}
    current = {r["xbrl_concept"]: r for r in conn.execute("SELECT * FROM concepts").fetchall()}
    stale = sorted(set(current) - set(wanted))
    referenced = [
        tag
        for tag in stale
        if conn.execute(
            "SELECT 1 FROM financial_facts WHERE xbrl_concept = ? LIMIT 1", (tag,)
        ).fetchone()
    ]
    if referenced:
        raise ConceptMapError(
            f"Tags removed from the concept map still have stored facts: {referenced}. "
            "Delete those facts first if the removal is intended."
        )

    counts = {"inserted": 0, "updated": 0, "deleted": len(stale)}
    with conn:
        # shift existing priorities out of the way so reordering can't trip UNIQUE(name, priority)
        conn.execute("UPDATE concepts SET priority = priority + 1000")
        conn.executemany("DELETE FROM concepts WHERE xbrl_concept = ?", [(t,) for t in stale])
        for row in rows:
            old = current.get(row.xbrl_concept)
            values = (row.canonical_name, row.priority, row.unit, row.period_type, row.definition)
            if old is None:
                conn.execute(
                    "INSERT INTO concepts (canonical_name, priority, unit, period_type, "
                    "definition, xbrl_concept) VALUES (?, ?, ?, ?, ?, ?)",
                    (*values, row.xbrl_concept),
                )
                counts["inserted"] += 1
            else:
                conn.execute(
                    "UPDATE concepts SET canonical_name = ?, priority = ?, unit = ?, "
                    "period_type = ?, definition = ? WHERE xbrl_concept = ?",
                    (*values, row.xbrl_concept),
                )
                old_values = (
                    old["canonical_name"],
                    old["priority"],
                    old["unit"],
                    old["period_type"],
                    old["definition"],
                )
                if values != old_values:
                    counts["updated"] += 1
    return counts
