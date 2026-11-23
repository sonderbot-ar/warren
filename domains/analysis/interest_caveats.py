"""Companies whose filed interest line is known not to be the interest on their debt, and from
which year (backlog #542; Decision 11, companies as data).

`interest_caveats.csv` holds one row per company and caveat. The cost-of-debt chart and cell
(`single_values`) read it to put a coded note beside the years it covers; no number changes.
"""

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

INTEREST_CAVEATS_PATH = Path(__file__).parent / "interest_caveats.csv"
COLUMNS = ["ticker", "code", "from_fiscal_year", "to_fiscal_year", "rate_item", "evidence", "note"]
# A closed set, so the app's text catalogue covers every code.
CAVEAT_CODES = ("interest_net_of_hedge_gains",)


class InterestCaveatError(ValueError):
    """interest_caveats.csv is malformed."""


@dataclass(frozen=True)
class InterestCaveat:
    ticker: str
    code: str
    from_fiscal_year: int
    to_fiscal_year: int | None  # None: still true in the newest filing
    rate_item: str | None  # the reported-only item holding the company's own stated rate
    evidence: str
    note: str

    def covers(self, fiscal_year: int) -> bool:
        return self.from_fiscal_year <= fiscal_year and (
            self.to_fiscal_year is None or fiscal_year <= self.to_fiscal_year
        )


def load_interest_caveats(path: Path | None = None) -> list[InterestCaveat]:
    """Read and validate the file; every problem found is reported at once."""
    from domains.fundamentals.concepts import reported_only_names
    from domains.fundamentals.universe import load_universe

    source = Path(path or INTEREST_CAVEATS_PATH)
    known = {c.ticker for c in load_universe()}
    rate_items = reported_only_names()
    errors, rows = [], []
    with open(source, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise InterestCaveatError(
                f"{source.name}: expected columns {COLUMNS}, got {reader.fieldnames}"
            )
        for n, r in enumerate(reader, start=2):
            line = f"{source.name} line {n}"
            if None in r or None in r.values():
                errors.append(f"{line}: wrong number of fields (quote any field with a comma)")
                continue
            ticker, code = r["ticker"].strip(), r["code"].strip()
            first, last = r["from_fiscal_year"].strip(), r["to_fiscal_year"].strip()
            rate_item = r["rate_item"].strip() or None
            if ticker not in known:
                errors.append(f"{line}: {ticker!r} is not in universe.csv")
            if code not in CAVEAT_CODES:
                errors.append(f"{line}: code {code!r} is not one of {list(CAVEAT_CODES)}")
            if not first.isdigit() or (last and not last.isdigit()):
                errors.append(f"{line}: fiscal years must be whole numbers (to may be empty)")
                continue
            if last and int(last) < int(first):
                errors.append(f"{line}: to_fiscal_year {last} is before from_fiscal_year {first}")
            if rate_item is not None and rate_item not in rate_items:
                errors.append(f"{line}: rate_item {rate_item!r} is not a reported-only map item")
            if not r["evidence"].strip():
                errors.append(f"{line}: evidence is empty (name the filings a reader can check)")
            row = InterestCaveat(
                ticker, code, int(first), int(last) if last else None, rate_item,
                r["evidence"].strip(), r["note"].strip(),
            )  # fmt: skip
            for other_line, other in rows:
                if (other.ticker, other.code) == (row.ticker, row.code) and _overlap(other, row):
                    errors.append(f"{line}: overlaps {other_line} ({ticker}, {code})")
            rows.append((line, row))
    if errors:
        raise InterestCaveatError("; ".join(errors))
    return [row for _line, row in rows]


def _overlap(a: InterestCaveat, b: InterestCaveat) -> bool:
    big = 10**6
    return a.from_fiscal_year <= (b.to_fiscal_year or big) and b.from_fiscal_year <= (
        a.to_fiscal_year or big
    )


@cache
def _shipped() -> tuple[InterestCaveat, ...]:
    return tuple(load_interest_caveats())


def caveat_for(ticker: str, fiscal_year: int) -> InterestCaveat | None:
    """The shipped row covering this company's fiscal year, or None."""
    return next((c for c in _shipped() if c.ticker == ticker and c.covers(fiscal_year)), None)
