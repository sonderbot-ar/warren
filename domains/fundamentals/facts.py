"""Point-in-time fact queries: what a company had reported as of a given date.

For each canonical item and period, the value comes from the newest filing public on the as-of date
(or the earliest, in first_reported mode); within that filing, the highest-priority tag wins.
Choosing the filing first means a restatement filed under a different tag still takes effect.
"""

import sqlite3
from collections import defaultdict
from datetime import date
from typing import Literal

from domains.fundamentals.schemas import Fact

Mode = Literal["latest", "first_reported"]

QUERY = """
SELECT f.*, c.canonical_name, c.priority
FROM financial_facts f JOIN concepts c USING (xbrl_concept)
WHERE f.cik = ? AND f.filed_at <= ? AND c.canonical_name IN ({placeholders})
"""


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _best_in_filing(rows: list[sqlite3.Row]) -> sqlite3.Row:
    return min(rows, key=lambda r: r["priority"])


def _to_fact(row: sqlite3.Row, restated: bool) -> Fact:
    return Fact(
        canonical_name=row["canonical_name"],
        xbrl_concept=row["xbrl_concept"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        fiscal_year=row["fiscal_year"],
        fiscal_period=row["fiscal_period"],
        value=row["value"],
        unit=row["unit"],
        accession_no=row["accession_no"],
        filed_at=row["filed_at"],
        restated=restated,
    )


def get_reported_facts(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    mode: Mode = "latest",
) -> list[Fact]:
    """Every reported period for the requested items, exactly as known on `as_of` (inclusive)."""
    if mode not in ("latest", "first_reported"):
        raise ValueError(f"Unknown mode: {mode!r}")
    known = {r[0] for r in conn.execute("SELECT DISTINCT canonical_name FROM concepts")}
    unknown = sorted(set(canonical_names) - known)
    if unknown:
        raise ValueError(f"Not in the concept map: {unknown}")
    if not canonical_names:
        return []

    sql = QUERY.format(placeholders=", ".join("?" * len(canonical_names)))
    params = [cik, _as_date(as_of).isoformat(), *canonical_names]

    # (name, start, end) -> accession -> rows (one per tag that filing used)
    periods: dict[tuple, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for row in conn.execute(sql, params):
        key = (row["canonical_name"], row["period_start"] or "", row["period_end"])
        periods[key][row["accession_no"]].append(row)

    facts = []
    for key in sorted(periods):
        filings = periods[key]
        order = sorted(filings, key=lambda accn: (filings[accn][0]["filed_at"], accn))
        first = _best_in_filing(filings[order[0]])
        if mode == "first_reported":
            facts.append(_to_fact(first, restated=False))
        else:
            latest = _best_in_filing(filings[order[-1]])
            facts.append(_to_fact(latest, restated=latest["value"] != first["value"]))
    return facts
