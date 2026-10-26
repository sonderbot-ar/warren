"""The Phase 1 universe: large US non-financial companies with clean XBRL filings."""

import warnings
from dataclasses import dataclass
from datetime import date

# FY2016-FY2025: the ten fiscal years the M1 exit criterion requires.
FISCAL_YEARS = range(2016, 2026)


class CoverageWarning(UserWarning):
    """A query asks for a date after this CIK stopped filing (its history continues elsewhere)."""


@dataclass(frozen=True)
class UniverseCompany:
    ticker: str
    cik: str | None = None  # pinned when the ticker's current CIK is not the one with the history
    note: str = ""
    history_ends: date | None = None  # from this date, newer filings are on another CIK


PHASE1_UNIVERSE = [
    UniverseCompany("AAPL"),
    UniverseCompany("MSFT"),
    UniverseCompany("WMT"),
    UniverseCompany("KO"),
    UniverseCompany("PG"),
    UniverseCompany("JNJ"),
    UniverseCompany("CAT"),
    UniverseCompany(
        "XOM",
        cik="0000034088",
        note=(
            "Exxon Mobil Corp, the registrant before the 2026-07-01 holding-company "
            "reorganisation. The XOM ticker now maps to ExxonMobil Holdings Corp (CIK 0002115436), "
            "whose filings start in 2026. Linking predecessor and successor is a later task."
        ),
        # the Q3 2026 10-Q (due early November) is the first periodic report on the new CIK
        history_ends=date(2026, 11, 1),
    ),
]


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
