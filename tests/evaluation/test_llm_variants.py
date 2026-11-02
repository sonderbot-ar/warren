"""The harness scores the AI's shocks on the run they were sized on (M8 Step 1).

Test Corp's case is 2019-06-30; its events, proposal set and auto-review are built the way M6
stores them, with a scripted model answer."""

import shutil
from datetime import date

import pytest

from domains.analysis.runs import run_baseline
from domains.evaluation.cases import store_cases
from domains.evaluation.harness import (
    COLUMNS,
    EvaluationError,
    case_seed,
    evaluate_case,
    guard_event_dates,
)
from domains.llm import calls, propose, review
from domains.llm.client import FakeClient
from domains.llm.extract import PROMPT as EXTRACT_PROMPT
from domains.llm.extract import company as company_of
from domains.news.matching import AliasSet
from shared_kernel.database import MIGRATIONS_DIR, apply_migrations, get_db_connection
from tests.evaluation.conftest import CHOICES
from tests.evaluation.test_harness import TODAY, by, case

CASE_DATE = date(2019, 6, 30)
EXTRACT_SHA = calls.latest_prompt(EXTRACT_PROMPT).sha256


def add_events(conn, case_id, last_seen=("2019-06-28T18:00:00Z",), variant="named"):
    co = company_of(conn, "TST")
    run = f"run_{variant}"
    conn.execute(
        "INSERT INTO event_runs (event_run_id, cik, as_of, tz, params_json, input_sha256, "
        "code_version) VALUES (?, ?, ?, 'America/New_York', '{}', 'x', 'test')",
        (run, co.cik, CASE_DATE.isoformat()),
    )
    for n, seen in enumerate(last_seen, start=1):
        conn.execute(
            "INSERT INTO events (event_id, event_run_id, cik, first_seen, last_seen, "
            "article_count, source_count, label, themes_json) "
            "VALUES (?, ?, ?, '2019-06-27T12:00:00Z', ?, 3, 3, 'label', '[]')",
            (f"{variant}{n}", run, co.cik, seen),
        )
        conn.execute(
            "INSERT INTO event_classifications (event_id, variant, model, prompt_sha256, status, "
            "event_type, model_event_type, materiality, reasons, summary, evidence_json, "
            "about_json) VALUES (?, ?, 'claude-haiku-5-5', ?, 'ok', 'guidance', 'guidance', "
            "'high', '[]', 'Test Corp cuts its revenue outlook.', '[]', '{}')",
            (f"{variant}{n}", variant, EXTRACT_SHA),
        )
    conn.execute(
        "INSERT INTO case_llm_status VALUES (?, ?, ?, ?, ?)",
        (case_id, run, variant, len(last_seen), len(last_seen)),
    )
    conn.commit()
    return co


def proposal(n_events=1, **fields):
    values = {"driver": "revenue_growth", "direction": "down", "size": "large",
              "duration": "lasting", "start_quarter": 1, "rationale": "Outlook cut.",
              "evidence": [f"e{i}" for i in range(1, n_events + 1)]}  # fmt: skip
    return values | fields


def answer(*proposals):
    return {"proposals": list(proposals), "no_material_impact": not proposals,
            "reason": "test"}  # fmt: skip


def stored_set(conn, model_answer, variant="named", last_seen=("2019-06-28T18:00:00Z",),
               run_id=None):  # fmt: skip
    """Events, a proposal set from a scripted answer, auto-reviewed; (run_id, shocks)."""
    c = case()
    co = add_events(conn, c.case_id, last_seen, variant)
    run_id = run_id or run_baseline(conn, "TST", CASE_DATE, choices=CHOICES, today=TODAY)
    set_id = propose.propose_case(conn, FakeClient([model_answer]), c.case_id, co, CASE_DATE,
                                  run_id, AliasSet((), "none"), variant, "test")  # fmt: skip
    review.review_set(conn, set_id, auto=True)
    return run_id, review.approved_shocks(conn, set_id)


def score(conn, run_id, shock_sets, c=None):
    return evaluate_case(conn, c or case(), CHOICES, actuals_as_of=TODAY, today=TODAY,
                         n_samples=500, run_id=run_id, shock_sets=shock_sets)  # fmt: skip


def test_a_revenue_cut_scores_below_the_baseline_on_the_same_run(company):
    run_id, shocks = stored_set(company, answer(proposal()))
    used, rows = score(company, run_id, {"llm_named": shocks})
    assert used == run_id  # the stored run, not a new one
    assert company.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    base = {r["period"]: r for r in by(rows, "baseline", "revenue")}
    llm = by(rows, "llm_named", "revenue")
    assert len(llm) == 4
    for r in llm:
        assert r["p10"] <= r["p50"] <= r["p90"]
        assert r["forecast"] == r["p50"] < base[r["period"]]["forecast"]
        assert r["seed"] == case_seed(case().case_id)
        assert r["status"] == "ok" and r["error"] > base[r["period"]]["error"]  # Test Corp is exact


def test_a_no_impact_set_writes_no_rows(company):
    run_id, shocks = stored_set(company, answer())
    assert shocks == []
    _, rows = score(company, run_id, {"llm_named": shocks})
    assert {r["variant"] for r in rows} == {"baseline", "naive_srw"}


def test_named_and_masked_use_one_run_and_one_seed(company):
    run_id, named = stored_set(company, answer(proposal()))
    _, masked = stored_set(company, answer(proposal(driver="operating_margin")), "masked",
                           run_id=run_id)  # fmt: skip
    _, rows = score(company, run_id, {"llm_named": named, "llm_masked": masked})
    seeds = {r["seed"] for r in rows if r["variant"].startswith("llm_")}
    assert seeds == {case_seed(case().case_id)}
    sims = company.execute("SELECT DISTINCT run_id FROM simulations").fetchall()
    assert [s[0] for s in sims] == [run_id]


def test_a_stored_simulation_is_reused(company):
    run_id, shocks = stored_set(company, answer(proposal()))
    score(company, run_id, {"llm_named": shocks})
    score(company, run_id, {"llm_named": shocks})
    assert company.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == 1


def test_a_stored_run_of_another_date_is_refused(company):
    other = run_baseline(company, "TST", date(2019, 9, 30), choices=CHOICES, today=TODAY)
    with pytest.raises(EvaluationError, match="not TST as of 2019-06-30"):
        score(company, other, {})


def test_an_unknown_run_is_refused(company):
    with pytest.raises(EvaluationError, match="is not stored"):
        score(company, "TST_1999-01-01_1", {})


def test_a_cited_event_after_the_case_date_fails_the_case_even_if_it_is_not_the_first(company):
    # two cited events: the first is fine, the second runs into the next New York day
    seen = ("2019-06-28T18:00:00Z", "2019-07-01T04:30:00Z")
    run_id, shocks = stored_set(company, answer(proposal(n_events=2)), last_seen=seen)
    assert shocks[0].event_id == "named1"  # the shock itself names only the first
    with pytest.raises(EvaluationError, match="named2.*after the case date in New York"):
        score(company, run_id, {"llm_named": shocks})


def test_event_times_are_compared_in_new_york_not_utc(company):
    # 2019-07-01T03:45Z is 23:45 on 2019-06-30 in New York: inside the case date
    run_id, shocks = stored_set(company, answer(proposal()), last_seen=("2019-07-01T03:45:00Z",))
    assert guard_event_dates(company, [s.shock_id for s in shocks], case()) == 1
    # 04:15Z is 00:15 on 2019-07-01 in New York: one day late
    company.execute("UPDATE events SET last_seen = '2019-07-01T04:15:00Z'")
    with pytest.raises(EvaluationError, match="after the case date"):
        guard_event_dates(company, [s.shock_id for s in shocks], case())


def test_shocks_without_a_stored_proposal_are_refused(company):
    from domains.analysis.shocks import Shock

    run_id = run_baseline(company, "TST", CASE_DATE, choices=CHOICES, today=TODAY)
    typed = Shock(shock_id="hand", event_id=None, driver="revenue_growth", low=-2, base=-1,
                  high=0, start_period=1, horizon=1, decay=1, source="user",
                  rationale="typed in")  # fmt: skip
    with pytest.raises(EvaluationError, match="no stored proposal"):
        score(company, run_id, {"llm_named": [typed]})


def test_only_the_two_llm_variants_take_shock_sets(company):
    run_id = run_baseline(company, "TST", CASE_DATE, choices=CHOICES, today=TODAY)
    with pytest.raises(EvaluationError, match="unknown shocked variant"):
        score(company, run_id, {"with_shocks": []})


def test_llm_rows_are_stored_by_a_batch(company):
    run_id, shocks = stored_set(company, answer(proposal()))
    # the backtest batch (Step 3) stores these rows; here the table must accept the new name
    company.execute(
        "INSERT INTO eval_batches (batch_id, code_version, cases_sha256) VALUES ('b', 'c', 's')"
    )
    _, rows = score(company, run_id, {"llm_named": shocks})
    store_cases(company, [case()])
    company.executemany(
        f"INSERT INTO eval_results (batch_id, {', '.join(COLUMNS)}) "
        f"VALUES ('b', {', '.join('?' * len(COLUMNS))})",
        [tuple(r.get(c) for c in COLUMNS) for r in rows],
    )
    variants = {r[0] for r in company.execute("SELECT DISTINCT variant FROM eval_results")}
    assert variants == {"baseline", "naive_srw", "llm_named"}


def test_0016_keeps_stored_results_on_a_v15_database(db_path, tmp_path):
    before = tmp_path / "migrations_0015"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 15:
            shutil.copy(path, before / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, before)
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000123', 'TST', 'T')")
        conn.execute(
            "INSERT INTO ingest_runs (run_id, cik, companyfacts_sha256, concept_map_sha256, "
            "facts_kept, facts_new) VALUES (1, '0000000123', 'a', 'b', 0, 0)"
        )
        conn.execute(
            "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
            "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
            "VALUES ('R', '0000000123', 'TST', '2019-06-30', 'c', 1, 'b', 'p', 'i', 'y')"
        )
        conn.execute(
            "INSERT INTO eval_cases VALUES ('C', 'TST', '0000000123', '2019-06-30', 'guidance', "
            "'d', 4, 's', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO eval_batches (batch_id, code_version, cases_sha256) VALUES ('B', 'c', 's')"
        )
        conn.execute(
            "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
            "horizon, forecast, status, p10, p50, p90, seed) VALUES ('B', 'C', 'R', "
            "'with_shocks', 'revenue', 'FY2019Q3', 1, 101.5, 'missing', 99.0, 101.5, 103.0, 7)"
        )
        conn.commit()
        before_rows = conn.execute("SELECT * FROM eval_results").fetchall()
        assert apply_migrations(conn) == [16]
        assert [tuple(r) for r in conn.execute("SELECT * FROM eval_results")] == [
            tuple(r) for r in before_rows
        ]
        conn.execute(
            "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
            "horizon, forecast, status) VALUES ('B', 'C', 'R', 'llm_masked', 'revenue', "
            "'FY2019Q3', 1, 100.0, 'missing')"
        )
        with pytest.raises(Exception, match="CHECK"):
            conn.execute(
                "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
                "horizon, forecast, status) VALUES ('B', 'C', 'R', 'llm_other', 'revenue', "
                "'FY2019Q3', 1, 100.0, 'missing')"
            )
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is None


def test_a_shock_whose_proposal_cites_no_event_is_refused(company):
    run_id, shocks = stored_set(company, answer(proposal()))
    company.execute("UPDATE shock_proposals SET evidence_json = '[]'")
    with pytest.raises(EvaluationError, match="cites no event"):
        guard_event_dates(company, [s.shock_id for s in shocks], case())
