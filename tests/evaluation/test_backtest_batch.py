"""The backtest batch, its reproduce check and its report, on Test Corp (M8 Step 3)."""

import json

from domains.evaluation import backtest_report
from domains.evaluation.__main__ import main
from domains.evaluation.backtest_batch import reproduce_batch, run_backtest
from tests.evaluation.test_harness import TODAY, case
from tests.evaluation.test_llm_variants import answer, proposal, stored_set

N = 400


def two_sets(conn):
    run_id, _ = stored_set(conn, answer(proposal()))
    stored_set(conn, answer(proposal(driver="operating_margin", direction="up")), "masked",
               run_id=run_id)  # fmt: skip
    return run_id


def backtest(conn):
    return run_backtest(conn, [case()], "sha", actuals_as_of=TODAY, today=TODAY, n_samples=N)


def test_a_batch_scores_five_variants_on_the_sets_run_and_records_its_inputs(company):
    run_id = two_sets(company)
    batch = backtest(company)
    variants = {r[0] for r in company.execute(
        "SELECT DISTINCT variant FROM eval_results WHERE batch_id = ?", (batch,))}  # fmt: skip
    assert variants == {"baseline", "naive_srw", "llm_named", "llm_masked"}  # no guidance here
    assert {r[0] for r in company.execute("SELECT DISTINCT run_id FROM eval_results")} == {run_id}
    notes = json.loads(company.execute("SELECT notes FROM eval_batches").fetchone()[0])
    assert notes["kind"] == "backtest" and notes["actuals_as_of"] == TODAY.isoformat()
    assert set(notes["sets"][case().case_id]) == {"named", "masked"}
    assert company.execute("SELECT COUNT(*) FROM eval_failures").fetchone()[0] == 0


def test_a_case_without_both_current_sets_fails_with_its_reason(company):
    stored_set(company, answer(proposal()))  # named only
    batch = backtest(company)
    reason = company.execute("SELECT reason FROM eval_failures WHERE batch_id = ?", (batch,))
    assert "no current masked proposal set" in reason.fetchone()[0]


def test_a_stored_batch_reproduces_to_the_cent(company):
    two_sets(company)
    batch = backtest(company)
    sims = company.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
    check = reproduce_batch(company, batch, [case()])
    assert check.ok, check.mismatches
    assert check.rows_checked == 4 * 2 * 4  # 4 quarters, 2 items, 4 variants
    assert check.simulations_checked == 2
    assert company.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == sims  # no writes


def test_an_edited_shock_fails_the_reproduce_check(company):
    two_sets(company)
    batch = backtest(company)
    company.execute(
        "UPDATE shocks SET low = low - 1, base = base - 0.5 WHERE driver = 'revenue_growth'"
    )
    company.commit()
    check = reproduce_batch(company, batch, [case()])
    assert not check.ok
    assert any("no stored simulation" in m or "hash" in m for m in check.mismatches)


def test_an_edited_percentile_fails_the_reproduce_check(company):
    two_sets(company)
    batch = backtest(company)
    company.execute("UPDATE simulation_outputs SET p50 = p50 + 1 WHERE name = 'revenue'")
    company.commit()
    check = reproduce_batch(company, batch, [case()])
    assert not check.ok
    assert any(" forecast: stored" in m for m in check.mismatches)
    assert any("p50: stored" in m for m in check.mismatches)


def test_a_changed_guidance_file_fails_the_reproduce_check(company):
    two_sets(company)
    batch = backtest(company)
    check = reproduce_batch(company, batch, [case()], guidance_sha256="other")
    assert not check.ok and "guidance file hash" in check.mismatches[0]


def test_the_report_holds_the_headline_the_band_caveat_and_every_case(company):
    two_sets(company)
    batch = backtest(company)
    text = backtest_report.render(company, batch)
    assert "## Headline: all cases" in text
    assert "| AI, masked | Revenue |" in text and "| AI, named | EBIT |" in text
    assert "covers only the uncertainty in the size of the shocks" in text
    assert f"| {case().case_id} | guidance | margin up | revenue down |" in text
    assert "Cases dated after the models' training cutoff (2026-06-01): 0 of 1" in text
    assert "without deals" in text and "Items moved in opposite directions" in text


def test_the_cli_runs_the_backtest_and_reproduces_it(company, monkeypatch, tmp_path, capsys):
    two_sets(company)
    import domains.evaluation.__main__ as cli

    class Same:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return company

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cli, "get_db_connection", Same)
    monkeypatch.setattr(cli, "run_backtest", lambda conn, cases, sha, guides, gsha: backtest(conn))
    monkeypatch.setattr(cli, "write_report", lambda conn, b: tmp_path / f"{b}.md")
    write = backtest_report.write_report
    monkeypatch.setattr(backtest_report, "write_report", lambda conn, b: write(conn, b, tmp_path))
    cases_file = tmp_path / "cases.csv"
    cases_file.write_text("x")  # hashed only; the cases come from load_cases below
    monkeypatch.setattr(cli, "load_cases", lambda path: [case()])
    assert main(["backtest", "--cases-file", str(cases_file)]) == 0
    out = capsys.readouterr().out
    batch = out.split()[0]
    assert (tmp_path / f"{batch}_backtest.md").exists()
    assert main(["reproduce", "--batch", batch, "--cases-file", str(cases_file)]) == 0
    assert "OK" in capsys.readouterr().out
