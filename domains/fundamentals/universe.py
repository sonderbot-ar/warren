"""The Phase 1 universe: large US non-financial companies with clean XBRL filings."""

import csv
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from shared_kernel.data_warnings import DataWarning

# FY2016-FY2025: the ten fiscal years the M1 exit criterion requires.
FISCAL_YEARS = range(2016, 2026)

# universe.csv is the editable company list (Decision 11: companies are data, not code)
UNIVERSE_PATH = Path(__file__).parent / "universe.csv"
COLUMNS = ["ticker", "cik", "history_ends", "reason", "successor_cik", "successor_name", "note"]

# Why a CIK's history ends (backlog #196): a closed set, so the app's text catalogue covers it.
COVERAGE_REASONS = frozenset({"holding_company_reorganisation"})
# Reasons that always have a successor registrant (a holding-company reorganisation does by
# definition: the new parent files a Form 8-K12B under Rule 12g-3). Another reason, a delisting
# say, may leave `successor_cik` and `successor_name` empty, and the note then names none.
REASONS_WITH_SUCCESSOR = frozenset({"holding_company_reorganisation"})


class CoverageWarning(DataWarning):
    """A query asks for a date after this CIK stopped filing (its history continues elsewhere).

    Carries its fields (backlog #172), so a caller can show it in another language."""

    def __init__(self, text: str, **fields) -> None:
        super().__init__(text)
        self.fields = fields


@dataclass(frozen=True)
class UniverseCompany:
    ticker: str
    cik: str | None = None  # pinned when the ticker's current CIK is not the one with the history
    note: str = ""
    history_ends: date | None = None  # from this date, newer filings are on another CIK
    reason: str | None = None  # why the history ends, one of COVERAGE_REASONS (backlog #196)
    successor_cik: str | None = None  # the CIK whose filings carry on, when known
    successor_name: str | None = None  # that registrant's name, as EDGAR gives it


class UniverseError(ValueError):
    """universe.csv is malformed."""


def load_universe(path: Path = UNIVERSE_PATH) -> list[UniverseCompany]:
    """Read and validate the company list. Every problem found is reported at once."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise UniverseError(f"Expected columns {COLUMNS}, got {reader.fieldnames}")
        raw = list(reader)

    errors, companies, seen, pinned = [], [], set(), set()
    for line, r in enumerate(raw, start=2):
        if None in r or None in r.values():
            errors.append(f"line {line}: wrong number of fields (quote any field with a comma)")
            continue
        ticker, cik, ends = r["ticker"].strip(), r["cik"].strip(), r["history_ends"].strip()
        reason, successor = r["reason"].strip(), r["successor_cik"].strip()
        successor_name = r["successor_name"].strip()
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
        if ends and not reason:
            errors.append(f"line {line}: history_ends needs a reason")
        if reason and reason not in COVERAGE_REASONS:
            errors.append(
                f"line {line}: reason must be one of {sorted(COVERAGE_REASONS)}, got {reason!r}"
            )
        if reason and not ends:
            errors.append(f"line {line}: reason needs a history_ends")
        if successor and not (len(successor) == 10 and successor.isdigit()):
            errors.append(
                f"line {line}: successor_cik must be empty or ten digits, got {successor!r}"
            )
        elif successor and successor == cik:
            errors.append(f"line {line}: successor_cik must differ from cik")
        if successor and not ends:
            errors.append(f"line {line}: successor_cik needs a history_ends")
        if reason in REASONS_WITH_SUCCESSOR and not (successor and successor_name):
            errors.append(f"line {line}: reason {reason} needs successor_cik and successor_name")
        if bool(successor) != bool(successor_name):
            errors.append(f"line {line}: successor_cik and successor_name go together")
        if cik and cik in pinned:
            errors.append(f"line {line}: cik {cik} is pinned twice")
        pinned.add(cik)
        companies.append(
            UniverseCompany(
                ticker,
                cik or None,
                r["note"].strip(),
                history_ends,
                reason or None,
                successor or None,
                successor_name or None,
            )
        )
    if errors:
        raise UniverseError(f"{path.name}: " + "; ".join(errors))
    return companies


PHASE1_UNIVERSE = load_universe()


def warn_if_beyond_history(cik: str, as_of: date) -> None:
    """Warn when a query's as-of date is past the point where this CIK's filings stop."""
    for company in PHASE1_UNIVERSE:
        if company.cik == cik and company.history_ends and as_of >= company.history_ends:
            text = (
                f"{company.ticker} (CIK {cik}) as of {as_of.isoformat()}: filings from "
                f"{company.history_ends.isoformat()} onward are on another CIK and are missing "
                f"here, so recent periods will be absent. {company.note}"
            )
            fields = {
                "ticker": company.ticker,
                "cik": cik,
                "as_of": as_of.isoformat(),
                "history_ends": company.history_ends.isoformat(),
                "reason": company.reason,
                "successor_cik": company.successor_cik,
                "successor_name": company.successor_name,
                "note": company.note,
            }
            warnings.warn(CoverageWarning(text, **fields), stacklevel=3)


COVERAGE_FIELDS = ("reason", "successor_cik", "successor_name")


def coverage_fields(cik: str | None, history_ends: str | None) -> dict | None:
    """`reason`, `successor_cik` and `successor_name` for a pinned CIK whose history ends on
    `history_ends` (ISO), from today's universe file (backlog #196): what a `beyond_history` note
    stored before #196 lacks. None when no row matches both, so a note whose cut-off was since
    corrected is never paired with another row's reason."""
    for company in PHASE1_UNIVERSE:
        if (
            cik is not None
            and company.cik == cik
            and company.history_ends is not None
            and company.history_ends.isoformat() == history_ends
        ):
            return {
                "reason": company.reason,
                "successor_cik": company.successor_cik,
                "successor_name": company.successor_name,
            }
    return None


def get_universe_company(ticker: str) -> UniverseCompany:
    for company in PHASE1_UNIVERSE:
        if company.ticker == ticker.upper():
            return company
    return UniverseCompany(ticker.upper())
