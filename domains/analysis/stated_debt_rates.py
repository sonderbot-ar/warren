"""The rates companies state on their own debt, and which debt each rate covers (backlog #543;
Decision 11, companies as data).

`stated_debt_rates.csv` holds one row per company that states, in its 10-K's debt note, a
weighted average rate on its long-term debt without a dimension (Warren can read it), and,
when it states one, on its short-term debt. `short_rate_covers` says which year-end debt the
short-term rate is on, as the company's own note places it: `short_term_borrowings` (short-term
borrowings and commercial paper) or `due_within_one_year` (those and the current portion of
long-term debt). The cost-of-debt chart (`single_values`) reads it to check a year's book cost
of debt against the rate the company states; no number changes.
"""

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

STATED_DEBT_RATES_PATH = Path(__file__).with_name("stated_debt_rates.csv")
COLUMNS = ["ticker", "long_rate_item", "short_rate_item", "short_rate_covers", "evidence"]
# the debt Warren counts that each `short_rate_covers` puts under the short-term rate; the rest
# of the year end's debt takes the long-term rate
SHORT_RATE_COVERS = {
    "short_term_borrowings": frozenset({"short_term_borrowings", "commercial_paper"}),
    "due_within_one_year": frozenset(
        {"short_term_borrowings", "commercial_paper", "debt_current", "debt_current_total"}
    ),
}
ACCESSION = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")


class StatedDebtRatesError(ValueError):
    """stated_debt_rates.csv is malformed."""


@dataclass(frozen=True)
class StatedDebtRates:
    ticker: str
    long_rate_item: str
    short_rate_item: str | None  # None: the company states no short-term rate Warren reads
    short_rate_covers: str | None  # a SHORT_RATE_COVERS key; None with no short-term rate
    evidence: str

    @property
    def accessions(self) -> tuple[str, ...]:
        """Every SEC accession number `evidence` names, in the order written, each once."""
        return tuple(dict.fromkeys(ACCESSION.findall(self.evidence)))


def load_stated_debt_rates(path: Path | None = None) -> list[StatedDebtRates]:
    """Read and validate the file; every problem found is reported at once."""
    from domains.fundamentals.concepts import reported_only_names
    from domains.fundamentals.universe import load_universe

    source = Path(path or STATED_DEBT_RATES_PATH)
    known = {c.ticker for c in load_universe()}
    items = reported_only_names()
    errors, rows, seen = [], [], set()
    with open(source, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise StatedDebtRatesError(
                f"{source.name}: expected columns {COLUMNS}, got {reader.fieldnames}"
            )
        for n, r in enumerate(reader, start=2):
            line = f"{source.name} line {n}"
            if None in r or None in r.values():
                errors.append(f"{line}: wrong number of fields (quote any field with a comma)")
                continue
            ticker = r["ticker"].strip()
            long_item = r["long_rate_item"].strip()
            short_item = r["short_rate_item"].strip() or None
            covers = r["short_rate_covers"].strip() or None
            if ticker not in known:
                errors.append(f"{line}: {ticker!r} is not in universe.csv")
            if ticker in seen:
                errors.append(f"{line}: {ticker} is listed twice")
            seen.add(ticker)
            for item in (long_item, short_item):
                if item is not None and item not in items:
                    errors.append(f"{line}: {item!r} is not a reported-only map item")
            if (short_item is None) != (covers is None):
                errors.append(f"{line}: a short-term rate item needs short_rate_covers, and back")
            if covers is not None and covers not in SHORT_RATE_COVERS:
                errors.append(f"{line}: short_rate_covers {covers!r} is not one of "
                              f"{sorted(SHORT_RATE_COVERS)}")  # fmt: skip
            if not ACCESSION.search(r["evidence"]):
                errors.append(f"{line}: evidence names no filing a reader can check")
            rows.append(StatedDebtRates(ticker, long_item, short_item, covers,
                                        r["evidence"].strip()))  # fmt: skip
    if errors:
        raise StatedDebtRatesError("; ".join(errors))
    return rows


@cache
def _shipped() -> dict[str, StatedDebtRates]:
    return {r.ticker: r for r in load_stated_debt_rates()}


def stated_rates_for(ticker: str) -> StatedDebtRates | None:
    """The shipped row for this company, or None when it states no rate Warren reads."""
    return _shipped().get(ticker)
