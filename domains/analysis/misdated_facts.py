"""Filed facts a filing put under the wrong fiscal year, with the filing's own words that say so
(backlog #610; Decision 11, companies as data).

`misdated_facts.csv` holds one row per fact: the company, the Warren item, the fiscal year the
filing's dates give it, the filing, and the fiscal year the filing's own text gives the figure
(`stated_fiscal_year`, which the cost-of-debt chart's `misdated_fact_left_out` note names; backlog
#613). Each error is visible in the same filing's text on the day
it was filed, so leaving the fact out uses nothing that was not public. The cost of debt (D8,
`math_engine._incurred`) leaves a listed fact out of the year's interest; no older version stands
in for it, since in those years nothing of the kind happened. Only the items in CHECKED_ITEMS are
read against the list. The file's bytes are part of the reading rules' fingerprint
(`reading_rules.RULES_DATA`), so a new row needs a new reading-rules version.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from domains.fundamentals.misdating import MisdatingCandidate, misdating_candidates

MISDATED_FACTS_PATH = Path(__file__).parent / "misdated_facts.csv"
COLUMNS = [
    "ticker",
    "canonical_name",
    "fiscal_year",
    "accession_no",
    "stated_fiscal_year",
    "evidence",
]
# The items the engine checks against the list; a row for any other would never be read
CHECKED_ITEMS = ("debt_extinguishment_in_interest",)
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class MisdatedFactsError(ValueError):
    """misdated_facts.csv is malformed."""


@dataclass(frozen=True)
class MisdatedFact:
    ticker: str
    canonical_name: str
    fiscal_year: int
    accession_no: str
    stated_fiscal_year: int  # the year the filing's own text gives the figure (#613)
    evidence: str


def load_misdated_facts(path: Path | None = None) -> list[MisdatedFact]:
    """Read and validate the file; every problem found is reported at once."""
    from domains.fundamentals.universe import load_universe

    source = Path(path or MISDATED_FACTS_PATH)
    # An accession's first ten digits name whoever submitted it, which can be a filing agent
    # (Coca-Cola's FY2025 10-K is 0001628280-26-010047), so they are not checked against the CIK
    tickers = {c.ticker for c in load_universe()}
    errors, rows, seen = [], [], set()
    with open(source, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise MisdatedFactsError(
                f"{source.name}: expected columns {COLUMNS}, got {reader.fieldnames}"
            )
        for n, r in enumerate(reader, start=2):
            line = f"{source.name} line {n}"
            if None in r or None in r.values():
                errors.append(f"{line}: wrong number of fields (quote any field with a comma)")
                continue
            ticker, item = r["ticker"].strip(), r["canonical_name"].strip()
            year, accession = r["fiscal_year"].strip(), r["accession_no"].strip()
            stated, evidence = r["stated_fiscal_year"].strip(), r["evidence"].strip()
            if ticker not in tickers:
                errors.append(f"{line}: {ticker!r} is not in universe.csv")
            if item not in CHECKED_ITEMS:
                errors.append(f"{line}: item {item!r} is not one of {list(CHECKED_ITEMS)}")
            if not year.isdigit():
                errors.append(f"{line}: fiscal_year must be a whole number")
            if not stated.isdigit():
                errors.append(f"{line}: stated_fiscal_year must be a whole number")
            elif stated == year:
                errors.append(f"{line}: stated_fiscal_year must differ from fiscal_year")
            elif stated not in evidence:
                errors.append(f"{line}: the evidence must quote the year it states ({stated})")
            if not ACCESSION.match(accession):
                errors.append(f"{line}: {accession!r} is not an SEC accession number")
            if accession not in evidence:
                errors.append(f"{line}: the evidence must quote the filing it names ({accession})")
            if (ticker, item, year, accession) in seen:
                errors.append(f"{line}: repeats an earlier row")
            seen.add((ticker, item, year, accession))
            if not errors:
                rows.append(MisdatedFact(ticker, item, int(year), accession, int(stated), evidence))
    if errors:
        raise MisdatedFactsError("\n".join(errors))
    return rows


@cache
def _by_key() -> dict[tuple[str, int, str], MisdatedFact]:
    """Every listed row by (item, fiscal year, accession), read once. An accession number is one
    filing of one company, so the company is implied."""
    return {(m.canonical_name, m.fiscal_year, m.accession_no): m for m in load_misdated_facts()}


def misdated_keys() -> frozenset[tuple[str, int, str]]:
    """(item, fiscal year, accession) of every listed fact."""
    return frozenset(_by_key())


def is_misdated(item: str, fiscal_year: int | None, accession_no: str | None) -> bool:
    return (item, fiscal_year, accession_no) in _by_key()


def misdated_fact(
    item: str, fiscal_year: int | None, accession_no: str | None
) -> MisdatedFact | None:
    """The listed row for a fact, or None: listed exactly when `is_misdated` says so, since both
    read the same table (backlog #613, the cost-of-debt chart's `misdated_fact_left_out`)."""
    return _by_key().get((item, fiscal_year, accession_no))


# The scan against the list (backlog #613 item 1)


@dataclass(frozen=True)
class ScanResult:
    """One company's scan as known on `as_of`: each candidate with the listed row it matches (or
    None), and each listed row whose filing is public on `as_of` that no candidate matches (a row
    that lost the shape, as a later filing repeated its figure). Listed rows whose filing is not
    yet public are neither."""

    ticker: str
    as_of: date
    candidates: list[tuple[MisdatingCandidate, MisdatedFact | None]]
    not_found: list[MisdatedFact]

    @property
    def needs_a_person(self) -> bool:
        return any(row is None for _, row in self.candidates) or bool(self.not_found)


def scan(conn, as_of: date, tickers: list[str] | None = None) -> list[ScanResult]:
    """Each company's `misdating_candidates` against the list, read only; never writes the
    file. A candidate matches a row with the same item, fiscal year and filing."""
    from domains.fundamentals.universe import load_universe

    companies = [c for c in load_universe() if tickers is None or c.ticker in tickers]
    unknown = sorted(set(tickers or ()) - {c.ticker for c in companies})
    if unknown:
        raise ValueError(f"not in universe.csv: {unknown}")
    rows = load_misdated_facts()
    results = []
    for company in companies:
        found = conn.execute(
            "SELECT cik FROM companies WHERE ticker = ?", (company.ticker,)
        ).fetchone()
        candidates = misdating_candidates(conn, found[0], as_of) if found else []
        listed = {
            (r.canonical_name, r.fiscal_year, r.accession_no): r
            for r in rows
            if r.ticker == company.ticker
        }
        matched = [
            (c, listed.get((c.canonical_name, c.fiscal_year, c.accession_no))) for c in candidates
        ]
        hit = {id(r) for _, r in matched if r is not None}
        public = _filed_on_or_before(conn, [r.accession_no for r in listed.values()], as_of)
        not_found = [r for r in listed.values() if id(r) not in hit and r.accession_no in public]
        results.append(ScanResult(company.ticker, as_of, matched, not_found))
    return results


def _filed_on_or_before(conn, accessions: list[str], as_of: date) -> set[str]:
    if not accessions:
        return set()
    marks = ", ".join("?" * len(accessions))
    return {
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT accession_no FROM financial_facts WHERE accession_no IN ({marks}) "
            "AND filed_at <= ?",
            (*accessions, as_of.isoformat()),
        )
    }


def proposed_row(c: MisdatingCandidate) -> str:
    """A template row for a candidate not listed. Its evidence is a placeholder that names
    neither the filing nor a year, so the loader refuses it until a person replaces it with the
    filing's own words."""
    return (
        f"{c.ticker},{c.canonical_name},{c.fiscal_year},{c.accession_no},"
        f'{c.stated_fiscal_year},"<quote the filing\'s own words that give the year>"'
    )


def scan_lines(result: ScanResult) -> list[str]:
    lines = []
    for c, row in result.candidates:
        where = (
            f"{result.ticker} {c.canonical_name} FY{c.fiscal_year} {c.value / 1e6:,.0f}M in "
            f"{c.accession_no} (filed {c.filed_at}), same as FY{c.stated_fiscal_year} in "
            f"{c.prior_accession_no}"
        )
        if row is not None:
            lines.append(f"listed      {where}")
        elif c.canonical_name in CHECKED_ITEMS:
            lines.append(f"NOT LISTED  {where}")
            lines.append(f"    if its text names {c.stated_fiscal_year}, add: {proposed_row(c)}")
        else:
            lines.append(f"NOT LISTED  {where}")
            lines.append(
                "    this item is not read against the list: if its text names "
                f"{c.stated_fiscal_year}, file a backlog issue to check it"
            )
    for r in result.not_found:
        lines.append(
            f"NOT FOUND   {result.ticker} {r.canonical_name} FY{r.fiscal_year} in "
            f"{r.accession_no}: listed, but the scan no longer finds the shape"
        )
    return lines
