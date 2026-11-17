"""The merged current portion (backlog #421) comes back in the order an unmerged read of the same
names does (backlog #427, item 2): only the figure chosen differs."""

import pytest

from domains.fundamentals.facts import _get_facts, get_facts
from tests.analysis.conftest import AS_OF
from tests.analysis.test_current_lease_debt import WITH, lease_inclusive

CIK = "0000000123"
NAMES = ["debt_noncurrent", "debt_current", "cash"]  # not in name order


def sequence(facts):
    return [(f.canonical_name, f.period_start, f.period_end) for f in facts]


@pytest.mark.parametrize("frequency", ["reported", "annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_the_merged_read_keeps_the_unmerged_order(make_company, mode, frequency):
    conn = make_company(lease_inclusive())
    merged = get_facts(conn, CIK, NAMES, AS_OF, mode, frequency)
    unmerged = _get_facts(conn, CIK, NAMES, AS_OF, mode, frequency)
    assert len(merged) > len(NAMES)  # several dates of each item
    assert sequence(merged) == sequence(unmerged)
    # the merge did run: the current portion is the lease-inclusive figure
    current = [f for f in merged if f.canonical_name == "debt_current"]
    assert current and all(f.xbrl_concept == f"us-gaap:{WITH}" for f in current)


def test_durations_keep_the_unmerged_order(make_company):
    # reported durations sort by start, then end, as `_facts` sorts its keys
    conn = make_company(lease_inclusive())
    names = ["revenue", "debt_current"]
    merged = get_facts(conn, CIK, names, AS_OF, frequency="reported")
    assert sequence(merged) == sequence(_get_facts(conn, CIK, names, AS_OF))
    assert any(f.period_start is not None for f in merged)
