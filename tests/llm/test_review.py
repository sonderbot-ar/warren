"""Review of proposed shocks: approve, edit, reject, auto; stored shocks simulate (M6 Step 6)."""

import pytest

from domains.analysis import montecarlo
from domains.llm import review
from domains.llm.client import FakeClient
from tests.analysis.conftest import company  # noqa: F401 - the fixture
from tests.llm.test_propose import answer, proposal, run

THREE = answer(proposal(evidence=["e1"]),
               proposal(driver="operating_margin", size="small", evidence=["e1"]),
               proposal(driver="risk_premium", duration="lasting", evidence=["e1"]))  # fmt: skip


def statuses(conn):
    return [r[0] for r in conn.execute("SELECT status FROM shock_proposals ORDER BY proposal_id")]


def test_auto_approves_everything_with_reviewer_none(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([THREE]), "high")
    assert review.review_set(company, set_id, auto=True) == {"auto_approved": 3}
    assert statuses(company) == ["auto_approved"] * 3
    reviewers = {r[0] for r in company.execute("SELECT reviewer FROM shock_proposals")}
    assert reviewers == {"none"}
    shocks = review.approved_shocks(company, set_id)
    assert [s.basis for s in shocks] == ["level", "growth", "growth"]
    assert {s.source for s in shocks} == {"llm_proposed"}
    assert "fading, halving in about 2 quarters" in shocks[0].rationale


def test_reviewing_twice_writes_no_second_shock(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([THREE]), "high")
    review.review_set(company, set_id, auto=True)
    assert review.review_set(company, set_id, auto=True) == {}
    assert company.execute("SELECT COUNT(*) FROM proposal_shocks").fetchone()[0] == 3


def test_manual_edit_stores_user_source_and_keeps_the_original(company):  # noqa: F811
    set_id, [first, *_] = run(company, FakeClient([THREE]), "high")
    decisions = iter([("edit", {"base": -2.0, "low": -3.0, "high": -1.0}),
                      ("reject", "not material"), ("approve", None)])  # fmt: skip
    counts = review.review_set(company, set_id, ask=lambda row, shock: next(decisions),
                               reviewer="andrew")  # fmt: skip
    assert counts == {"edited": 1, "rejected": 1, "approved": 1}
    assert statuses(company) == ["edited", "rejected", "approved"]
    kept = company.execute("SELECT * FROM shock_proposals WHERE proposal_id = ?",
                           (first["proposal_id"],)).fetchone()  # fmt: skip
    assert kept["base"] == first["base"] and kept["review_note"] == (
        '{"base": -2.0, "high": -1.0, "low": -3.0}'
    )
    edited, approved = review.approved_shocks(company, set_id)  # the rejection wrote none
    assert (edited.source, edited.base) == ("user", -2.0)
    assert approved.driver == "risk_premium" and approved.source == "llm_proposed"


def test_an_edit_that_changes_nothing_is_refused(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([THREE]), "high")
    with pytest.raises(ValueError, match="an edit changes"):
        review.review_set(company, set_id, ask=lambda row, shock: ("edit", {"driver": "x"}))


def test_approved_shocks_simulate_and_reproduce_to_the_cent(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([THREE]), "high")
    review.review_set(company, set_id, auto=True)
    run_id = company.execute("SELECT run_id FROM proposal_sets WHERE set_id = ?",
                             (set_id,)).fetchone()[0]  # fmt: skip
    sim_id = montecarlo.save_simulation(company, run_id, review.approved_shocks(company, set_id),
                                        n=300, seed=7)  # fmt: skip
    assert montecarlo.reproduce_simulation(company, sim_id).ok
