"""Shock proposal on Test Corp: one set per case, sized by code (M6 Step 5)."""

import json
import re
from datetime import date

import pytest

from domains.analysis.runs import run_baseline
from domains.llm import calls, propose, scales
from domains.llm.client import FakeClient
from domains.llm.extract import PROMPT as EXTRACT_PROMPT
from domains.llm.extract import company as company_of
from domains.news.matching import AliasSet
from tests.analysis.conftest import AS_OF, CHOICES, company  # noqa: F401 - the fixture

CASE = "TST_2020-06-30"
NO_ALIASES = AliasSet((), "none")  # Test Corp has no alias rows


EXTRACT_SHA = calls.latest_prompt(EXTRACT_PROMPT).sha256


def add_events(conn, *materialities, sha=EXTRACT_SHA):
    co = company_of(conn, "TST")
    conn.execute(
        "INSERT INTO event_runs (event_run_id, cik, as_of, tz, params_json, input_sha256, "
        "code_version) VALUES ('run1', ?, ?, 'America/New_York', '{}', 'x', 'test')",
        (co.cik, AS_OF.isoformat()),
    )
    for n, materiality in enumerate(materialities, start=1):
        conn.execute(
            "INSERT INTO events (event_id, event_run_id, cik, first_seen, last_seen, "
            "article_count, source_count, label, themes_json) "
            "VALUES (?, 'run1', ?, ?, ?, 3, 3, 'label', '[]')",
            (f"ev{n}", co.cik, f"2020-06-2{n + 4}T12:00:00Z", f"2020-06-2{n + 4}T18:00:00Z"),
        )
        conn.execute(
            "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, status, "
            "event_type, model_event_type, materiality, reasons, summary, evidence_json, "
            "about_json) VALUES (?, 'named', 'claude-haiku-5-5', ?, 'ok', 'guidance', "
            "'guidance', ?, '[]', 'Test Corp cuts its revenue outlook.', '[]', '{}')",
            (f"ev{n}", sha, materiality),
        )
    conn.execute(
        "INSERT INTO case_llm_status VALUES (?, 'run1', 'named', ?, ?)",
        (CASE, len(materialities), len(materialities)),
    )
    conn.commit()
    return co


def proposal(**fields):
    values = {"driver": "revenue_growth", "direction": "down", "size": "medium",
              "duration": "fading", "start_quarter": 1, "rationale": "Outlook cut.",
              "evidence": ["e1", "e2"]}  # fmt: skip
    return values | fields


def answer(*proposals, no_impact=False):
    return {"proposals": list(proposals), "no_material_impact": no_impact,
            "reason": "test"}  # fmt: skip


def run(company, client, *materialities):  # noqa: F811
    co = add_events(company, *materialities)
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    set_id = propose.propose_case(company, client, CASE, co, AS_OF, run_id, NO_ALIASES,
                                  "named", "test")  # fmt: skip
    return set_id, company.execute(
        "SELECT * FROM shock_proposals WHERE set_id = ? ORDER BY proposal_id", (set_id,)
    ).fetchall()


def test_two_events_about_one_story_give_one_shock_per_driver(company):  # noqa: F811
    client = FakeClient([answer(proposal())])
    set_id, [row] = run(company, client, "high", "medium")
    assert len(client.requests) == 1  # one call for the case
    user = client.requests[0]["user"]
    assert re.search(r"^e1 \| guidance", user, re.M) and re.search(r"^e2 \| guidance", user, re.M)
    assert json.loads(row["evidence_json"]) == ["ev1", "ev2"]
    assert row["status"] == "proposed" and row["sigma_flag"] == "floored"  # Test Corp is smooth
    assert (row["low"], row["base"], row["high"]) == pytest.approx((-0.875, -0.5, -0.125))
    assert (row["horizon"], row["decay"]) == (8, 0.7)


@pytest.mark.parametrize(
    "bad",
    [
        answer(proposal(), proposal()),  # a repeated driver
        answer(),  # empty without no_material_impact
        answer(proposal(evidence=["e9"])),
        answer(proposal(driver="risk_premium", duration="permanent", evidence=["e2"])),
        answer(proposal() | {"base": -3.0}),
    ],  # fmt: skip
)
def test_invalid_sets_are_asked_again(company, bad):  # noqa: F811
    client = FakeClient([bad, answer(no_impact=True)])
    set_id, rows = run(company, client, "high", "medium")
    assert rows == [] and len(client.requests) == 2
    stored = company.execute("SELECT * FROM proposal_sets WHERE set_id = ?", (set_id,)).fetchone()
    assert stored["status"] == "ok" and stored["no_impact"] == 1


def test_a_permanent_risk_premium_with_a_high_event_is_accepted(company):  # noqa: F811
    p = proposal(driver="risk_premium", duration="permanent", evidence=["e1"], size="small")
    _, [row] = run(company, FakeClient([answer(p)]), "high", "low")
    assert (row["low"], row["base"], row["high"]) == (-43.75, -25, -6.25)
    assert row["horizon"] == 20


def test_a_case_without_events_has_no_set(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([answer(proposal())]))
    assert set_id is None


def test_a_rerun_reuses_the_set_and_pays_nothing(company):  # noqa: F811
    set_id, _ = run(company, FakeClient([answer(proposal(evidence=["e1"]))]), "high")
    co = company_of(company, "TST")
    run_id = company.execute("SELECT run_id FROM proposal_sets").fetchone()[0]
    again = FakeClient([])
    assert propose.propose_case(company, again, CASE, co, AS_OF, run_id, NO_ALIASES,
                                "named", "test") == set_id  # fmt: skip
    assert again.requests == []


def test_history_is_point_in_time_and_long_enough(company):  # noqa: F811
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    co = company_row = company.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()
    history = propose.driver_history(company, co["cik"], AS_OF, run_id)
    assert len(history.revenue_growth) == 16  # 20 quarters of revenue
    assert history.operating_margin[-1] == pytest.approx(0.2)
    assert history.capex_intensity[-1] == pytest.approx(0.06)
    assert history.revenue_growth[-1] == pytest.approx(0.10)
    assert history.last_quarter == (2020, 1)
    before = propose.driver_history(company, company_row["cik"], date(2020, 4, 29), run_id)
    assert before.last_quarter == (2019, 4)  # the Q1 2020 10-Q was filed on 2020-04-30
    assert scales.sigma("revenue_growth", history.revenue_growth, scales.load_scales()).flag == (
        "floored"
    )


def test_a_case_reads_one_classification_per_event_from_the_current_prompt(company):  # noqa: F811
    # the real run classified each event with prompt v1, v2 and v4; a proposal must see each
    # event once, from the current prompt, and a set made from older classifications is not reused
    co = add_events(company, "high")
    company.execute(
        "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, status, "
        "event_type, model_event_type, materiality, reasons, summary, evidence_json, about_json) "
        "VALUES ('ev1', 'named', 'claude-haiku-5-5', 'older', 'ok', 'product', 'product', 'low', "
        "'[]', 'Older answer.', '[]', '{}')"
    )
    rows = propose.case_events(company, CASE, "named", "claude-haiku-5-5", EXTRACT_SHA)
    assert [(r["event_id"], r["event_type"]) for r in rows] == [("ev1", "guidance")]
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    company.execute(
        "INSERT INTO proposal_sets (case_id, event_run_id, variant, model, prompt_sha256, run_id, "
        "status, no_impact) VALUES (?, 'run1', 'named', ?, ?, ?, 'ok', 1)",
        (
            CASE,
            calls.node_model("propose_shocks").model,
            calls.latest_prompt(propose.PROMPT).sha256,
            run_id,
        ),
    )  # fmt: skip  (a set stored before 0014: its extraction prompt is not known)
    client = FakeClient([answer(no_impact=True)])
    new = propose.propose_case(company, client, CASE, co, AS_OF, run_id, NO_ALIASES, "named", "t")
    assert len(client.requests) == 1 and client.requests[0]["user"].count("e1 |") <= 1
    stored = company.execute("SELECT inputs_sha256 FROM proposal_sets WHERE set_id = ?",
                             (new,)).fetchone()[0]  # fmt: skip
    assert stored == propose.inputs_sha256(EXTRACT_SHA, rows)
    assert propose.current_set(company, CASE, "named")["set_id"] == new


def test_a_set_is_proposed_again_when_its_events_change(company):  # noqa: F811
    # the real run first chose events from outside the case window; once the choice changed, the
    # stored set no longer matched what the case reads and had to be proposed again
    co = add_events(company, "high")
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    first = FakeClient([answer(no_impact=True)])
    old = propose.propose_case(company, first, CASE, co, AS_OF, run_id, NO_ALIASES, "named", "t")
    company.execute(
        "UPDATE events SET first_seen = '2020-06-01T00:00:00Z', last_seen = '2020-06-01T06:00:00Z'"
    )  # fmt: skip  (ev1 leaves the window)
    company.execute(
        "INSERT INTO events (event_id, event_run_id, cik, first_seen, last_seen, article_count, "
        "source_count, label, themes_json) VALUES ('ev9', 'run1', ?, '2020-06-29T12:00:00Z', "
        "'2020-06-29T13:00:00Z', 3, 3, 'label', '[]')", (co.cik,),
    )  # fmt: skip
    company.execute(
        "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, status, "
        "event_type, model_event_type, materiality, reasons, summary, evidence_json, about_json) "
        "VALUES ('ev9', 'named', 'claude-haiku-5-5', ?, 'ok', 'guidance', 'guidance', 'high', "
        "'[]', 'Test Corp cuts again.', '[]', '{}')", (EXTRACT_SHA,),
    )  # fmt: skip
    rows = propose.case_events(company, CASE, "named", "claude-haiku-5-5", EXTRACT_SHA)
    assert [r["event_id"] for r in rows] == ["ev9"]
    again = FakeClient([answer(no_impact=True)])
    new = propose.propose_case(company, again, CASE, co, AS_OF, run_id, NO_ALIASES, "named", "t")
    assert new != old and len(again.requests) == 1
    assert (
        "cuts again" in again.requests[0]["user"]
        and "revenue outlook" not in again.requests[0]["user"]
    )
