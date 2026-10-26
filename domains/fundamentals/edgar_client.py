"""SEC EDGAR client: ticker lookup, company submissions and XBRL company facts.

Raw JSON is cached under data/raw/edgar/ so re-runs do not re-download. Every request carries the
descriptive User-Agent SEC requires and stays under SEC's limit of 10 requests per second.
All HTTP goes through EdgarClient._get(), so swapping the HTTP library touches one method.
"""

import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from shared_kernel.config import RAW_EDGAR_DIR, sec_user_agent

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

MIN_INTERVAL_SECONDS = 0.11  # just over 1/10 s, to stay under SEC's 10 requests per second
MAX_RETRIES = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}

# SIC division H (6000-6799): finance, insurance and real estate. Their valuation does not follow
# a standard free-cash-flow DCF, so they are outside the Phase 1 universe (build plan section 1).
FINANCIAL_SIC_RANGE = range(6000, 6800)


class EdgarError(RuntimeError):
    """EDGAR returned something unusable, or a lookup found nothing."""


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _write_atomic(path: Path, data: Any) -> None:
    """Write JSON to a temp file and rename, so an interrupted run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def pad_cik(cik: int | str) -> str:
    """SEC URLs and Warren's tables use the 10-digit, zero-padded CIK."""
    digits = str(cik).strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError(f"Not a valid CIK: {cik!r}")
    return digits.zfill(10)


def is_financial_sic(sic: str | None) -> bool:
    return sic is not None and sic.isdigit() and int(sic) in FINANCIAL_SIC_RANGE


def parse_company(submissions: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Map a submissions document to a companies row. Aliases = current name plus former names."""
    name = submissions["name"]
    aliases = [name] + [f["name"] for f in submissions.get("formerNames", [])]
    return {
        "cik": pad_cik(submissions["cik"]),
        "ticker": ticker.upper(),
        "name": name,
        "sic": submissions.get("sic") or None,
        "fiscal_year_end": submissions.get("fiscalYearEnd") or None,
        "aliases": list(dict.fromkeys(aliases)),  # de-duplicated, order kept
    }


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: Path = RAW_EDGAR_DIR,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.user_agent = user_agent or sec_user_agent()
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    # -- HTTP ---------------------------------------------------------------------------------

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = MIN_INTERVAL_SECONDS - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def _get(self, url: str) -> dict[str, Any]:
        """GET a JSON document, retrying rate limits, server errors and dropped connections."""
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                response = self.session.get(url, headers=headers, timeout=30)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == MAX_RETRIES:
                    raise
            else:
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                    return response.json()
                if attempt == MAX_RETRIES:
                    response.raise_for_status()
            self._sleep(2**attempt)  # 1, 2, 4, 8 s backoff
        raise AssertionError("unreachable")

    # -- cache --------------------------------------------------------------------------------

    def _cached(self, relative_path: str, url: str, refresh: bool) -> dict[str, Any]:
        path = self.cache_dir / relative_path
        if path.exists() and not refresh:
            return json.loads(path.read_text())
        data = self._get(url)
        fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_atomic(path, data)
        # a sidecar records where and when the cached copy came from (provenance)
        _write_atomic(_meta_path(path), {"url": url, "fetched_at": fetched_at})
        return data

    def fetched_at(self, relative_path: str) -> str | None:
        """When a cached file was downloaded, or None if it predates provenance sidecars."""
        meta = _meta_path(self.cache_dir / relative_path)
        return json.loads(meta.read_text())["fetched_at"] if meta.exists() else None

    def company_facts_fetched_at(self, cik: str) -> str | None:
        return self.fetched_at(f"companyfacts/CIK{pad_cik(cik)}.json")

    # -- endpoints ----------------------------------------------------------------------------

    def lookup_cik(self, ticker: str, refresh: bool = False) -> str:
        tickers = self._cached("tickers/company_tickers.json", TICKERS_URL, refresh)
        wanted = ticker.strip().upper()
        for entry in tickers.values():
            if entry["ticker"].upper() == wanted:
                return pad_cik(entry["cik_str"])
        raise EdgarError(f"Ticker not found in SEC's company tickers file: {ticker}")

    def get_submissions(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        cik = pad_cik(cik)
        url = SUBMISSIONS_URL.format(cik=cik)
        return self._cached(f"submissions/CIK{cik}.json", url, refresh)

    def get_company_facts(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        cik = pad_cik(cik)
        url = COMPANY_FACTS_URL.format(cik=cik)
        return self._cached(f"companyfacts/CIK{cik}.json", url, refresh)
