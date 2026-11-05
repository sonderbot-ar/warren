import argparse
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

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


def _wire(company, monkeypatch, at):
    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    monkeypatch.setattr(cli, "get_universe_company", lambda t: type("C", (), {"ticker": t}))
    monkeypatch.setattr(cli, "now", lambda: at)


def test_dcf_without_a_date_takes_the_last_day_ended_in_new_york(company, monkeypatch, capsys):
    # 2020-07-01 03:59 UTC is 23:59 on jun.30 in New York: jun.29 is the last day ended
    _wire(company, monkeypatch, datetime(2020, 7, 1, 3, 59, tzinfo=UTC))
    days = []
    monkeypatch.setattr(cli, "run_baseline", lambda conn, t, d: days.append(d) or run(conn))
    monkeypatch.setattr(cli, "write_report", lambda conn, r: Path("r.md"))
    assert cli.main(["dcf", "--ticker", "TST"]) == 0
    out = capsys.readouterr().out
    assert days == [date(2020, 6, 29)]
    assert "as of 2020-06-29 (the latest day that has ended in New York)" in out
    assert "TST: filings as downloaded from EDGAR on 2026-10-26" in out and "WARNING" not in out


def test_dcf_without_a_date_warns_of_an_old_download_and_old_prices(company, monkeypatch, capsys):
    company.execute("UPDATE ingest_runs SET companyfacts_fetched_at = '2020-06-01T12:00:00Z'")
    # jul.01 has ended; prices were downloaded at 12:00 UTC that day, before it ended
    _wire(company, monkeypatch, datetime(2020, 7, 2, 5, 0, tzinfo=UTC))
    assert cli.main(["dcf", "--ticker", "TST"]) == 1
    out = capsys.readouterr().out
    assert "as of 2020-07-01" in out
    assert "WARNING: TST: filings after 2020-06-01 may be missing" in out
    assert "domains.fundamentals ingest --ticker TST" in out
    assert "FAILED" in out and "before the as-of date 2020-07-01 ended in New York" in out


def test_reported_without_a_date_keeps_the_json_clean(company, monkeypatch, capsys):
    _wire(company, monkeypatch, datetime(2020, 7, 1, 5, 0, tzinfo=UTC))
    assert cli.main(["reported", "--ticker", "TST", "--period", "latest-quarter", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data[0]["as_of"] == "2020-06-30" and data[0]["period"] == "FY2020Q1"
    assert "as of 2020-06-30 (the latest day that has ended in New York)" in captured.err


def test_whatif_command_prints_the_ripple_and_json(company, monkeypatch, capsys):
    _wire(company, monkeypatch, datetime(2020, 7, 2, tzinfo=UTC))
    run_id = run(company)
    assert cli.main(["whatif", "--run-id", run_id, "--add", "operating_margin=-0.01"]) == 0
    out = capsys.readouterr().out
    assert f"What-if {run_id}_whatif_1 on {run_id}" in out
    assert "value_per_share" in out and "operating_margin" in out and "NOPAT" in out
    assert cli.main(["whatif", "--run-id", run_id, "--set", "beta=1.2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["parent_run_id"] == run_id and data["changes"][0]["name"] == "beta"
    # what-ifs reproduce with the rest and are not rebuilt
    assert cli.main(["reproduce", "--all", "--rebuild"]) == 0
    out = capsys.readouterr().out
    assert "3 of 3 runs reproduced to the cent" in out
    assert "1 of 1 runs rebuilt to identical rows" in out and "2 what-ifs not rebuilt" in out


def test_whatif_command_sets_wacc_and_the_report_says_the_range_is_not_computed(
    company, monkeypatch, capsys
):
    from domains.analysis.report import render

    _wire(company, monkeypatch, datetime(2020, 7, 2, tzinfo=UTC))
    run_id = run(company)
    assert cli.main(["whatif", "--run-id", run_id, "--set", "wacc=0.12"]) == 0
    out = capsys.readouterr().out
    assert "wacc" in out and "WACC is set directly" in out
    assert "not computed: WACC set directly" in render(company, f"{run_id}_whatif_1")


def test_whatif_command_refuses_with_its_code(company, monkeypatch, capsys):
    _wire(company, monkeypatch, datetime(2020, 7, 2, tzinfo=UTC))
    run_id = run(company)
    assert cli.main(["whatif", "--run-id", run_id, "--set", "debt=0"]) == 1
    assert "REFUSED (not_changeable)" in capsys.readouterr().out


def test_parse_change_reads_name_period_and_number():
    change = cli.parse_change("operating_margin@FY2021Q1=-0.01", "delta")
    assert (change.name, change.period, change.delta, change.value) == (
        "operating_margin",
        "FY2021Q1",
        -0.01,
        None,
    )
    assert cli.parse_change("beta=1.1", "value").period is None
    for bad in ("beta", "beta=high"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_change(bad, "value")


def test_sensitivity_command_prints_both_tables_and_json(company, monkeypatch, capsys):
    _wire(company, monkeypatch, datetime(2020, 7, 2, tzinfo=UTC))
    run_id = run(company)
    assert cli.main(["sensitivity", "--run-id", run_id]) == 0
    out = capsys.readouterr().out
    assert f"Sensitivity of {run_id}" in out and "Contrast (gordon_fcff)" in out
    assert "*" in out and "per point" in out
    args = ["sensitivity", "--run-id", run_id, "--wacc-steps=-0.01,0.01", "--growth-steps"]
    assert cli.main(args + ["0.005", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["wacc_steps"] == [-0.01, 0.0, 0.01] and data["growth_steps"] == [0.0, 0.005]
    assert data["run_point"] == {"row": 1, "column": 0}


def test_sensitivity_command_refuses_with_its_code(company, monkeypatch, capsys):
    _wire(company, monkeypatch, datetime(2020, 7, 2, tzinfo=UTC))
    run_id = run(company)
    assert cli.main(["sensitivity", "--run-id", run_id, "--wacc-steps=0"]) == 1
    assert "REFUSED (too_few_steps)" in capsys.readouterr().out


def test_sensitivity_steps_must_be_numbers():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_steps("0.01,abc")
    assert cli.parse_steps("-0.01, 0,0.01") == [-0.01, 0.0, 0.01]
