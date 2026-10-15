"""The Phase 1 universe: large US non-financial companies with clean XBRL filings."""

from dataclasses import dataclass

# FY2016-FY2025: the ten fiscal years the M1 exit criterion requires.
FISCAL_YEARS = range(2016, 2026)


@dataclass(frozen=True)
class UniverseCompany:
    ticker: str
    cik: str | None = None  # pinned when the ticker's current CIK is not the one with the history
    note: str = ""


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
    ),
]


def get_universe_company(ticker: str) -> UniverseCompany:
    for company in PHASE1_UNIVERSE:
        if company.ticker == ticker.upper():
            return company
    return UniverseCompany(ticker.upper())
