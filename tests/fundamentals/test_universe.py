import warnings
from datetime import date

import pytest

from domains.fundamentals.facts import get_facts
from domains.fundamentals.universe import (
    PHASE1_UNIVERSE,
    CoverageWarning,
    get_universe_company,
    warn_if_beyond_history,
)

XOM_CIK = "0000034088"


def test_xom_is_pinned_to_the_predecessor_cik_with_a_history_end():
    xom = get_universe_company("xom")
    assert (xom.cik, xom.history_ends) == (XOM_CIK, date(2026, 11, 1))
    assert len(PHASE1_UNIVERSE) == 8


def test_query_past_the_history_end_warns():
    with pytest.warns(CoverageWarning, match="XOM"):
        warn_if_beyond_history(XOM_CIK, date(2026, 11, 1))


def test_query_before_the_history_end_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_beyond_history(XOM_CIK, date(2026, 10, 31))
        warn_if_beyond_history("0000320193", date(2030, 1, 1))  # AAPL has no history end


def test_get_facts_carries_the_warning(ingested):
    conn, _ = ingested
    with pytest.warns(CoverageWarning):
        get_facts(conn, XOM_CIK, ["revenue"], "2027-01-01")
