from contextlib import contextmanager

import pytest

from domains.analysis import __main__ as cli
from domains.analysis import report
from domains.analysis.runs import load_outputs, run_baseline
from tests.analysis.conftest import AS_OF, CHOICES


def run(conn):
    return run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def test_report_shows_the_valuation_and_its_sources(company, tmp_path):
    run_id = run(company)
    text = report.render(company, run_id)
    for heading in (
        "## Summary",
        "## Cost of capital",
        "## Drivers",
        "## Free cash flow",
        "## From enterprise value to value per share",
        "## Inputs and fallbacks",
        "## Warnings",
        "## Data snapshot",
    ):
        assert heading in text
    value = load_outputs(company, run_id)[("value_per_share", "-")]
    assert f"**Value per share: {value:,.2f}**" in text
    assert "0000000123-20-000016" in text
    path = report.write_report(company, run_id, tmp_path)
    assert path.name == "TST_2020-06-30.md"
    assert "No useful precision" not in text


MINUS = "value_per_share_erp_minus_1se"


def _drop_minus(conn, run_id):
    conn.execute("DELETE FROM run_outputs WHERE run_id = ? AND name = ?", (run_id, MINUS))


@pytest.mark.parametrize(
    "reason, words, sentence",
    [
        ("growth_not_below_rate", "WACC ≤ terminal growth", "falls to terminal growth or below"),
        ("rate_not_positive", "WACC ≤ 0", "falls to zero or below"),
    ],
)
def test_report_says_the_stored_reason_for_a_missing_value(company, reason, words, sentence):
    run_id = run(company)
    _drop_minus(company, run_id)
    company.execute(
        "INSERT INTO run_output_gaps VALUES (?, ?, '-', ?, 'detail')", (run_id, MINUS, reason)
    )
    text = report.render(company, run_id)
    assert f"−1 SE no value ({words})" in text
    assert "**No useful precision.**" in text and sentence in text
    # a lower ERP raises the value, so the missing bound is the upper one
    assert "without an upper bound" in text and "lower bound" not in text
    assert "recomputed" not in text


def test_report_recomputes_the_reason_for_a_run_stored_before_reasons_were(company):
    # no gap row (a run from before 0013) and rows whose ERP − 1 SE truly has no value: an
    # ERP standard error larger than the ERP takes the cost of equity, and WACC, below zero
    run_id = run(company)
    _drop_minus(company, run_id)
    erp = company.execute(
        "SELECT value FROM assumptions WHERE run_id = ? AND name = 'erp'", (run_id,)
    ).fetchone()[0]
    company.execute(
        "UPDATE assumptions SET value = ? WHERE run_id = ? AND name = 'erp_std_error'",
        (erp + 0.5, run_id),
    )
    text = report.render(company, run_id)
    assert "−1 SE no value (WACC ≤ 0) (recomputed" in text
    assert "falls to zero or below" in text


def test_report_does_not_guess_a_reason_it_cannot_find(company):
    # an output missing although the rows give it a value: say so, never name a cause
    run_id = run(company)
    _drop_minus(company, run_id)
    text = report.render(company, run_id)
    assert "−1 SE no value (reason not found)" in text
    assert "No useful precision" not in text


def test_cli_runs_reproduces_and_reports(company, tmp_path, monkeypatch, capsys):
    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    monkeypatch.setattr(cli, "get_universe_company", lambda t: type("C", (), {"ticker": t}))
    monkeypatch.setattr(cli, "run_baseline", lambda conn, t, d: run(conn))
    monkeypatch.setattr(cli, "write_report", lambda conn, r: report.write_report(conn, r, tmp_path))
    assert cli.main(["dcf", "--ticker", "TST", "--as-of", AS_OF.isoformat()]) == 0
    assert cli.main(["reproduce", "--all"]) == 0
    out = capsys.readouterr().out
    assert "value per share" in out and "1 of 1 runs reproduced to the cent" in out
    # the real rebuild, with the choices the run stored (not today's user_assumptions.csv)
    assert cli.main(["reproduce", "--all", "--rebuild"]) == 0
    assert "1 of 1 runs rebuilt to identical rows" in capsys.readouterr().out
