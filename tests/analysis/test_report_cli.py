from contextlib import contextmanager

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
