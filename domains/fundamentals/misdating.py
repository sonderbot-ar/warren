"""Figures a 10-K may have filed under the wrong fiscal year (backlog #613 item 1).

Both misdated figures found so far (`domains/analysis/misdated_facts.csv`, backlog #610) have one
shape, an error SEC staff name ("using an incorrect year when tagging comparative prior period
information", data quality reminder of 2022-01-14): a filing's annual figure for year Y is exactly
the figure filed earlier for year Y-1 under the same tag, the filing itself gives Y-1 no equal
figure, and no filing on another year gives Y that figure. A 10-K shows three years of income
statement (Regulation S-X 3-02), so a true figure is usually given again by the next 10-Ks; one
only its own filing gives is the suspect. A filing's year is the newest fiscal year it gives any
annual figure for: an amendment of the same year's report (a 10-K/A that re-files the 10-K, as
P&G's 0000080424-20-000059 and Exxon's 0001193125-11-050134 do) is a copy, not a second source,
so it does not corroborate.

This module finds that shape in the facts as known on a date and proposes each hit as a
candidate. It never leaves a figure out: only the filing's own text can say the year is wrong, so
a person reads it and, if it names Y-1, adds a row to the list. A candidate can appear on one
date and go away on a later one, when a later filing gives the year the same figure.

On the snapshot of nov.27.2026 the shape alone gives 27 hits over the eight companies; 25 are
true repeats of rounded figures (J&J's amortization of 1,200M two years running) or a filing
repeating itself. With the conditions it finds the two listed rows and nothing else on the first
of every month from 2009 to 2026, but the conditions were fitted on those two errors, so that is
in sample by construction: a tripwire, not a measured detector. It misses a misdated figure a
later filing repeats (staff also name "context dates carried over from a prior period's filing"),
a figure moved two years or moved and revised, and quarters and balances.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

QUERY = """
SELECT f.xbrl_concept, f.fiscal_year, f.value, f.accession_no, f.form, f.filed_at,
       c.canonical_name
FROM financial_facts f JOIN concepts c USING (xbrl_concept)
WHERE f.cik = ? AND f.filed_at <= ? AND f.fiscal_period = 'FY' AND f.unit = 'USD'
  AND f.fiscal_year IS NOT NULL AND c.period_type = 'duration'
"""


@dataclass(frozen=True)
class MisdatingCandidate:
    ticker: str
    canonical_name: str
    xbrl_concept: str
    fiscal_year: int  # Y, the year the filing's dates give the figure
    value: float
    accession_no: str  # the filing that gives Y the figure
    form: str
    filed_at: str
    prior_accession_no: str  # the earliest earlier filing that gave Y-1 the same figure
    prior_filed_at: str

    @property
    def stated_fiscal_year(self) -> int:
        """The year to look for in the filing's text: the one the same figure was filed for."""
        return self.fiscal_year - 1


def misdating_candidates(
    conn: sqlite3.Connection, cik: str, as_of: date | str
) -> list[MisdatingCandidate]:
    """Annual US-dollar flow figures filed on or before `as_of` that have the misdated shape
    (module docstring): one per (item, tag, fiscal year, filing), sorted by item, year and
    filing. Reads every tag of every mapped item, not only the one the selection rule picks."""
    as_of = as_of.isoformat() if isinstance(as_of, date) else as_of
    company = conn.execute("SELECT ticker FROM companies WHERE cik = ?", (cik,)).fetchone()
    ticker = company[0] if company else cik
    rows: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    report_year: dict[str, int] = {}  # a filing's newest fiscal year: the year it reports on
    for row in conn.execute(QUERY, (cik, as_of)):
        rows[(row["canonical_name"], row["xbrl_concept"], row["fiscal_year"])].append(row)
        accession = row["accession_no"]
        report_year[accession] = max(
            report_year.get(accession, row["fiscal_year"]), row["fiscal_year"]
        )
    found: dict[tuple, MisdatingCandidate] = {}
    for (name, tag, year), same_year in rows.items():
        year_before = rows.get((name, tag, year - 1), [])
        for row in same_year:
            value, accession = row["value"], row["accession_no"]
            if value == 0:
                continue
            earlier = sorted(
                (p for p in year_before if p["value"] == value and p["filed_at"] < row["filed_at"]),
                key=lambda p: (p["filed_at"], p["accession_no"]),
            )
            if not earlier:
                continue
            if any(p["accession_no"] == accession and p["value"] == value for p in year_before):
                continue  # the filing states both years: a true repeat
            own_report = report_year[accession]
            if any(
                o["accession_no"] != accession
                and o["value"] == value
                and report_year[o["accession_no"]] != own_report
                for o in same_year
            ):
                continue  # a filing on another year gives this year the same figure: corroborated
            key = (name, tag, year, accession)
            found.setdefault(
                key,
                MisdatingCandidate(
                    ticker=ticker,
                    canonical_name=name,
                    xbrl_concept=tag,
                    fiscal_year=year,
                    value=value,
                    accession_no=accession,
                    form=row["form"],
                    filed_at=row["filed_at"],
                    prior_accession_no=earlier[0]["accession_no"],
                    prior_filed_at=earlier[0]["filed_at"],
                ),
            )
    return [found[k] for k in sorted(found)]
