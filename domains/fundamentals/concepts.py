"""Concept map: Warren's canonical names and the XBRL tags behind them, in priority order.

concept_map.csv is the editable source; sync_concepts() copies it into the `concepts` table, which
is the enforced vocabulary (financial_facts can only reference tags that exist there).

The map is two files with the same columns (backlog #157). concept_map.csv holds every item a
valuation can read, and its SHA-256 is the fingerprint each run stores: a different file can give
a different answer for an old date, so a run built from another map can't be rebuilt.
concept_map_reported.csv holds items only the reported-figures query reads (net income to the
parent, discontinued operations), so adding one there leaves every stored run rebuildable.
Ingest and the `concepts` table see both files as one map.
"""

import csv
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

CONCEPT_MAP_PATH = Path(__file__).parent / "concept_map.csv"
CONCEPT_MAP_REPORTED_PATH = Path(__file__).parent / "concept_map_reported.csv"
COLUMNS = [
    "canonical_name",
    "xbrl_concept",
    "priority",
    "unit",
    "period_type",
    "gate",
    "definition",
    "note",
]
UNITS = {"USD", "shares", "USD/shares"}
PERIOD_TYPES = {"duration", "instant"}
# required: every gap must be explained (the quality gate). optional: fallbacks and items a company
# may not hold (e.g. marketable securities); gaps are listed but never fail the gate.
GATES = {"required", "optional"}
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
    gate: str = "required"

    @property
    def taxonomy(self) -> str:
        return self.xbrl_concept.split(":", 1)[0]

    @property
    def tag(self) -> str:
        return self.xbrl_concept.split(":", 1)[1]


def load_concept_map(
    path: Path | None = None, reported_path: Path | None = None
) -> list[ConceptRow]:
    """Read and validate the concept map: both shipped files by default, or the files given
    (`path` alone reads one file). Every problem found is reported at once."""
    if path is None:
        paths = [CONCEPT_MAP_PATH, reported_path or CONCEPT_MAP_REPORTED_PATH]
    else:
        paths = [path] + ([reported_path] if reported_path else [])
    raw, files = [], {}
    for source in paths:
        with open(source, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != COLUMNS:
                raise ConceptMapError(
                    f"{Path(source).name}: expected columns {COLUMNS}, got {reader.fieldnames}"
                )
            raw += [(f"{Path(source).name} line {n}", r) for n, r in enumerate(reader, start=2)]

    errors, rows = [], []
    for line, r in raw:
        if None in r or None in r.values():
            errors.append(f"{line}: wrong number of fields (quote any field with a comma)")
            continue
        if not r["priority"].isdigit():
            errors.append(f"{line}: priority must be a positive integer")
            continue
        row = ConceptRow(
            canonical_name=r["canonical_name"].strip(),
            xbrl_concept=r["xbrl_concept"].strip(),
            priority=int(r["priority"]),
            unit=r["unit"].strip(),
            period_type=r["period_type"].strip(),
            definition=r["definition"].strip(),
            gate=r["gate"].strip(),
        )
        if not row.xbrl_concept.startswith(TAXONOMIES):
            errors.append(f"{line}: {row.xbrl_concept} must start with one of {TAXONOMIES}")
        if row.unit not in UNITS:
            errors.append(f"{line}: unknown unit {row.unit!r}")
        if row.period_type not in PERIOD_TYPES:
            errors.append(f"{line}: unknown period_type {row.period_type!r}")
        if row.gate not in GATES:
            errors.append(f"{line}: gate must be one of {sorted(GATES)}")
        if not row.definition:
            errors.append(f"{line}: definition is required")
        files.setdefault(row.canonical_name, set()).add(line.split(" line ")[0])
        rows.append(row)

    tags = [r.xbrl_concept for r in rows]
    for tag in sorted({t for t in tags if tags.count(t) > 1}):
        errors.append(f"{tag} is mapped more than once (one tag maps to one canonical name)")

    for name in sorted(n for n, names in files.items() if len(names) > 1):
        errors.append(f"{name}: an item's tags must all be in one file, not {sorted(files[name])}")

    for name in sorted({r.canonical_name for r in rows}):
        group = [r for r in rows if r.canonical_name == name]
        if sorted(r.priority for r in group) != list(range(1, len(group) + 1)):
            errors.append(f"{name}: priorities must be 1..{len(group)} with no gaps or repeats")
        for field in ("unit", "period_type", "definition", "gate"):
            if len({getattr(r, field) for r in group}) > 1:
                errors.append(f"{name}: every tag must share the same {field}")

    if errors:
        raise ConceptMapError("Invalid concept map:\n  " + "\n  ".join(errors))
    return rows


def concept_map_sha256(path: Path = CONCEPT_MAP_PATH) -> str:
    """Fingerprint of the valuation's concept map (concept_map.csv only): a different map can give
    different answers for old dates. The reported-only file is left out by design (backlog #157):
    no valuation reads its items, so editing it must not stop old runs from rebuilding."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reported_only_names(path: Path = CONCEPT_MAP_REPORTED_PATH) -> set[str]:
    """The items only the reported-figures query reads (concept_map_reported.csv)."""
    return {r.canonical_name for r in load_concept_map(path)}


def sync_concepts(conn: sqlite3.Connection, rows: list[ConceptRow]) -> dict[str, int]:
    """Make the concepts table match the CSV, in one transaction.

    Pass the whole map (`load_concept_map()`, both files): rows read from one file alone would
    delete the other file's tags (backlog #157).

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
