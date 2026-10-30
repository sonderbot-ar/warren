import warnings
from datetime import date

import pytest

from domains.fundamentals.facts import get_facts
from domains.fundamentals.universe import (
    PHASE1_UNIVERSE,
    CoverageWarning,
    UniverseError,
    get_universe_company,
    load_universe,
    warn_if_beyond_history,
)

XOM_CIK = "0000034088"


def test_xom_is_pinned_to_the_predecessor_cik_with_a_history_end():
    xom = get_universe_company("xom")
    assert (xom.cik, xom.history_ends) == (XOM_CIK, date(2026, 8, 3))
    assert len(PHASE1_UNIVERSE) == 8


def test_query_past_the_history_end_warns():
    with pytest.warns(CoverageWarning, match="XOM"):
        warn_if_beyond_history(XOM_CIK, date(2026, 8, 3))


def test_query_before_the_history_end_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_beyond_history(XOM_CIK, date(2026, 8, 2))
        warn_if_beyond_history("0000320193", date(2030, 1, 1))  # AAPL has no history end


def test_get_facts_carries_the_warning(ingested):
    conn, _ = ingested
    with pytest.warns(CoverageWarning):
        get_facts(conn, XOM_CIK, ["revenue"], "2027-01-01")


def test_csv_holds_the_phase1_list_in_order():
    assert [c.ticker for c in PHASE1_UNIVERSE] == [
        "AAPL", "MSFT", "WMT", "KO", "PG", "JNJ", "CAT", "XOM",
    ]  # fmt: skip
    assert all(c.cik is None and c.history_ends is None for c in PHASE1_UNIVERSE[:-1])
    assert "ExxonMobil Holdings Corp" in get_universe_company("XOM").note


def _write(tmp_path, body):
    path = tmp_path / "universe.csv"
    path.write_text("ticker,cik,history_ends,note\n" + body)
    return path


def test_a_new_company_is_one_row(tmp_path):
    path = _write(tmp_path, "AAPL,,,\nAMXB,0001129137,,a new company needs no code\n")
    new = load_universe(path)[1]
    assert (new.ticker, new.cik, new.note) == ("AMXB", "0001129137", "a new company needs no code")


@pytest.mark.parametrize(
    "body, message",
    [
        ("aapl,,,\n", "line 2: ticker must be non-empty and upper case"),
        (",,,\n", "line 2: ticker must be non-empty"),
        ("AAPL,,,\nAAPL,,,\n", "line 3: duplicate ticker AAPL"),
        ("AAPL,34088,,\n", "line 2: cik must be empty or ten digits"),
        ("XOM,0000034088,2026-13-01,\n", "line 2: history_ends must be an ISO date"),
        ("XOM,,2026-08-03,\n", "line 2: history_ends needs a pinned cik"),
        ("AAPL,,,a, b\n", "line 2: wrong number of fields"),
        ("AAPL,,\n", "line 2: wrong number of fields"),
    ],
)
def test_bad_rows_are_named_by_line(tmp_path, body, message):
    with pytest.raises(UniverseError, match=message):
        load_universe(_write(tmp_path, body))


def test_every_problem_is_reported_at_once(tmp_path):
    with pytest.raises(UniverseError, match="line 2.*line 3"):
        load_universe(_write(tmp_path, "aapl,,,\nMSFT,123,,\n"))


def test_wrong_columns_are_refused(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text("ticker,cik\nAAPL,\n")
    with pytest.raises(UniverseError, match="Expected columns"):
        load_universe(path)
