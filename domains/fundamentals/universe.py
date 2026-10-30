"""The Phase 1 universe: large US non-financial companies with clean XBRL filings."""

import csv
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# FY2016-FY2025: the ten fiscal years the M1 exit criterion requires.
FISCAL_YEARS = range(2016, 2026)

# universe.csv is the editable company list (Decision 11: companies are data, not code)
UNIVERSE_PATH = Path(__file__).parent / "universe.csv"
COLUMNS = ["ticker", "cik", "history_ends", "note"]


class CoverageWarning(UserWarning):
    """A query asks for a date after this CIK stopped filing (its history continues elsewhere)."""


@dataclass(frozen=True)
class UniverseCompany:
    ticker: str
    cik: str | None = None  # pinned when the ticker's current CIK is not the one with the history
    note: str = ""
    history_ends: date | None = None  # from this date, newer filings are on another CIK


class UniverseError(ValueError):
    """universe.csv is malformed."""


def load_universe(path: Path = UNIVERSE_PATH) -> list[UniverseCompany]:
    """Read and validate the company list. Every problem found is reported at once."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise UniverseError(f"Expected columns {COLUMNS}, got {reader.fieldnames}")
        raw = list(reader)

    errors, companies, seen = [], [], set()
    for line, r in enumerate(raw, start=2):
        if None in r or None in r.values():
            errors.append(f"line {line}: wrong number of fields (quote any field with a comma)")
            continue
        ticker, cik, ends = r["ticker"].strip(), r["cik"].strip(), r["history_ends"].strip()
        if not ticker or ticker != ticker.upper():
            errors.append(f"line {line}: ticker must be non-empty and upper case, got {ticker!r}")
        elif ticker in seen:
            errors.append(f"line {line}: duplicate ticker {ticker}")
        seen.add(ticker)
        if cik and not (len(cik) == 10 and cik.isdigit()):
            errors.append(f"line {line}: cik must be empty or ten digits, got {cik!r}")
        history_ends = None
        if ends:
            try:
                history_ends = date.fromisoformat(ends)
            except ValueError:
                errors.append(f"line {line}: history_ends must be an ISO date, got {ends!r}")
            if not cik:
                errors.append(f"line {line}: history_ends needs a pinned cik")
        companies.append(UniverseCompany(ticker, cik or None, r["note"].strip(), history_ends))
    if errors:
        raise UniverseError(f"{path.name}: " + "; ".join(errors))
    return companies


PHASE1_UNIVERSE = load_universe()


def warn_if_beyond_history(cik: str, as_of: date) -> None:
    """Warn when a query's as-of date is past the point where this CIK's filings stop."""
    for company in PHASE1_UNIVERSE:
        if company.cik == cik and company.history_ends and as_of >= company.history_ends:
            warnings.warn(
                f"{company.ticker} (CIK {cik}) as of {as_of.isoformat()}: filings from "
                f"{company.history_ends.isoformat()} onward are on another CIK and are missing "
                f"here, so recent periods will be absent. {company.note}",
                CoverageWarning,
                stacklevel=3,
            )


def get_universe_company(ticker: str) -> UniverseCompany:
    for company in PHASE1_UNIVERSE:
        if company.ticker == ticker.upper():
            return company
    return UniverseCompany(ticker.upper())
