"""The evaluation command line end to end on Test Corp: a case file in, a report out."""

from contextlib import contextmanager
from datetime import date

from domains.evaluation import __main__ as cli
from domains.evaluation import cases, harness, report
from tests.evaluation.conftest import CHOICES
from tests.evaluation.test_cases import GOOD, write

TODAY = date(2020, 6, 30)


def tst_case(event_date: str) -> dict:
    return {**GOOD, "case_id": f"TST_{event_date}", "ticker": "TST", "event_date": event_date}


def wire(monkeypatch, company, tmp_path):
    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    monkeypatch.setattr(cli, "load_cases", lambda path: cases.load_cases(path, {"TST"}))
    monkeypatch.setattr(
        cli,
        "run_batch",
        lambda conn, cs, sha: harness.run_batch(conn, cs, sha, CHOICES, TODAY, TODAY),
    )
    monkeypatch.setattr(cli, "write_report", lambda conn, b: report.write_report(conn, b, tmp_path))


def test_run_scores_every_case_and_writes_the_report(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    # the second case is after "today", so the engine refuses it and it is listed
    path = write(tmp_path, tst_case("2019-06-30"), tst_case("2020-09-30"))
    assert cli.main(["run", "--cases-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "TST_2020-09-30" in out and "FAILED" in out
    assert "1/2 cases scored" in out
    assert "revenue  median error baseline 0.0000" in out

    batch_id = f"eval_{TODAY.isoformat()}_1"
    text = (tmp_path / f"{batch_id}.md").read_text()
    assert f"# Evaluation batch {batch_id}" in text
    assert "## Headline: median error, baseline vs naive" in text
    assert "| Revenue (absolute % error) | all | 4 | 0.0% | 9.1% |" in text
    for period in ("FY2019Q2", "FY2019Q3", "FY2019Q4", "FY2020Q1"):
        assert f"| TST_2019-06-30 | guidance | {period} |" in text
    assert "derived Q4" in text
    assert "## Failed cases" in text and "- **TST_2020-09-30**:" in text
    assert "## Glossary" in text and "## Limitations" in text
    assert cases.cases_sha256(path)[:12] in text


def test_run_only_the_cases_named(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    path = write(tmp_path, tst_case("2019-06-30"), tst_case("2020-09-30"))
    assert cli.main(["run", "--cases-file", str(path), "--case", "TST_2019-06-30"]) == 0
    assert "1/1 cases scored" in capsys.readouterr().out
    assert cli.main(["run", "--cases-file", str(path), "--case", "NOPE"]) == 2
    assert "Unknown case ids: ['NOPE']" in capsys.readouterr().out


def test_run_exits_1_when_no_case_could_be_scored(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    path = write(tmp_path, tst_case("2020-09-30"))
    assert cli.main(["run", "--cases-file", str(path)]) == 1
    assert "0/1 cases scored" in capsys.readouterr().out


def test_report_rewrites_a_stored_batch(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    path = write(tmp_path, tst_case("2019-06-30"))
    cli.main(["run", "--cases-file", str(path)])
    capsys.readouterr()
    (tmp_path / f"eval_{TODAY.isoformat()}_1.md").unlink()
    assert cli.main(["report", "--batch", f"eval_{TODAY.isoformat()}_1"]) == 0
    assert (tmp_path / f"eval_{TODAY.isoformat()}_1.md").exists()
