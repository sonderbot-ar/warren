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
from functools import cache
from pathlib import Path

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
