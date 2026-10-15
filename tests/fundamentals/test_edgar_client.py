import pytest
import requests

from domains.fundamentals.edgar_client import (
    MAX_RETRIES,
    MIN_INTERVAL_SECONDS,
    EdgarClient,
    EdgarError,
    is_financial_sic,
    pad_cik,
    parse_company,
)

UA = "Jane Doe jane@example.com"
TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(tmp_path, *responses):
    session, clock = FakeSession(*responses), FakeClock()
    client = EdgarClient(
        user_agent=UA, cache_dir=tmp_path, session=session, sleep=clock.sleep, clock=clock
    )
    return client, session, clock


def test_pad_cik():
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("0000320193") == "0000320193"
    with pytest.raises(ValueError):
        pad_cik("abc")


def test_user_agent_header_is_sent(tmp_path):
    client, session, _ = make_client(tmp_path, FakeResponse(payload=TICKERS))
    client.lookup_cik("aapl")
    assert session.calls[0][1]["User-Agent"] == UA


def test_lookup_cik_is_case_insensitive_and_padded(tmp_path):
    client, _, _ = make_client(tmp_path, FakeResponse(payload=TICKERS))
    assert client.lookup_cik("aapl") == "0000320193"


def test_unknown_ticker_raises(tmp_path):
    client, _, _ = make_client(tmp_path, FakeResponse(payload=TICKERS))
    with pytest.raises(EdgarError):
        client.lookup_cik("NOPE")


def test_cache_hit_skips_fetching(tmp_path):
    client, session, _ = make_client(tmp_path, FakeResponse(payload={"facts": {}}))
    first = client.get_company_facts("320193")
    second = client.get_company_facts("320193")
    assert first == second
    assert len(session.calls) == 1
    assert (tmp_path / "companyfacts" / "CIK0000320193.json").exists()


def test_refresh_fetches_again(tmp_path):
    client, session, _ = make_client(
        tmp_path, FakeResponse(payload={"v": 1}), FakeResponse(payload={"v": 2})
    )
    client.get_submissions("320193")
    assert client.get_submissions("320193", refresh=True) == {"v": 2}
    assert len(session.calls) == 2


def test_rate_limit_and_dropped_connection_are_retried(tmp_path):
    client, session, clock = make_client(
        tmp_path,
        FakeResponse(status_code=429),
        requests.ConnectionError("reset"),
        FakeResponse(payload={"ok": True}),
    )
    assert client.get_submissions("1") == {"ok": True}
    assert len(session.calls) == 3
    assert 1 in clock.sleeps and 2 in clock.sleeps  # exponential backoff


def test_gives_up_after_max_retries(tmp_path):
    responses = [FakeResponse(status_code=503)] * (MAX_RETRIES + 1)
    client, session, _ = make_client(tmp_path, *responses)
    with pytest.raises(requests.HTTPError):
        client.get_submissions("1")
    assert len(session.calls) == MAX_RETRIES + 1


def test_client_errors_are_not_retried(tmp_path):
    client, session, _ = make_client(tmp_path, FakeResponse(status_code=404))
    with pytest.raises(requests.HTTPError):
        client.get_submissions("1")
    assert len(session.calls) == 1


def test_requests_are_throttled(tmp_path):
    client, _, clock = make_client(tmp_path, FakeResponse(payload={}), FakeResponse(payload={}))
    client.get_submissions("1")
    client.get_submissions("2")
    assert clock.sleeps == [pytest.approx(MIN_INTERVAL_SECONDS)]


@pytest.mark.parametrize(
    ("sic", "financial"),
    [("3571", False), ("6021", True), ("6311", True), ("6798", True), (None, False)],
)
def test_is_financial_sic(sic, financial):
    assert is_financial_sic(sic) is financial


def test_parse_company_collects_aliases():
    submissions = {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "sic": "3571",
        "fiscalYearEnd": "0926",
        "formerNames": [{"name": "APPLE INC"}, {"name": "APPLE COMPUTER INC"}],
    }
    company = parse_company(submissions, "aapl")
    assert company["ticker"] == "AAPL"
    assert company["aliases"] == ["Apple Inc.", "APPLE INC", "APPLE COMPUTER INC"]
