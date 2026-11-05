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
        lambda conn, cs, sha, **kw: harness.run_batch(conn, cs, sha, CHOICES, TODAY, TODAY, **kw),
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


# -- ranges run (backlog #144) -----------------------------------------------------------------


def _tst_run(company) -> str:
    from domains.evaluation import ranges

    ranges.build_origin(company, "TST", date(2019, 5, 1), TODAY, CHOICES, TODAY)
    return company.execute("SELECT run_id FROM forecast_origins").fetchone()[0]


def test_ranges_run_prints_the_bands_and_the_track_record(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    run_id = _tst_run(company)
    assert cli.main(["ranges", "run", "--run-id", run_id]) == 0
    out = capsys.readouterr().out
    assert f"TST run {run_id} as of 2019-05-01" in out and "baseline forecast" in out
    assert "pooled pool" in out and "own pool" in out and "Track record" in out
    assert "no_history" in out and "beyond_horizon" in out  # one origin: no past misses yet
    assert "no_coverage_history" in out  # a run before 2021 has no track record
    assert "does not include news" in out


def test_ranges_run_json_is_plain_json(company, tmp_path, monkeypatch, capsys):
    import json

    wire(monkeypatch, company, tmp_path)
    run_id = _tst_run(company)
    assert cli.main(["ranges", "run", "--run-id", run_id, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == run_id and data["basis"] == "baseline" and data["currency"] == "USD"
    assert len(data["quarters"]) == 8 and len(data["coverage"]) == 8
    assert {b["pool"] for b in data["quarters"][0]["bands"]} == {"pooled", "own"}
    assert {"target", "acceptable", "verdict", "n_quarters", "interval"} <= set(data["coverage"][0])


def test_ranges_run_on_an_unknown_run_exits_1(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    assert cli.main(["ranges", "run", "--run-id", "NOPE_1"]) == 1
    assert "not stored" in capsys.readouterr().out


# -- track-record (backlog #145) ----------------------------------------------------------------


def _track_record_origins(company, monkeypatch):
    from domains.evaluation import run_ranges
    from tests.evaluation.test_track_record import origin, q

    monkeypatch.setattr(run_ranges, "basis_flags", lambda conn, ticker, on: set())
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=80.0)], {"FY2021Q1": (90.0, 9.0)})


def test_track_record_prints_the_summaries_and_quarters(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    _track_record_origins(company, monkeypatch)
    assert cli.main(["track-record", "--ticker", "TST", "--as-of", "2021-07-01"]) == 0
    out = capsys.readouterr().out
    assert "TST track record as of 2021-07-01" in out
    assert "| FY2021Q1 | 1 | 2021-02-01 |" in out and "revenue: forecast" in out


def test_track_record_without_as_of_says_it_is_the_last_ended_day(
    company, tmp_path, monkeypatch, capsys
):
    wire(monkeypatch, company, tmp_path)
    _track_record_origins(company, monkeypatch)
    assert cli.main(["track-record", "--ticker", "tst"]) == 0
    out = capsys.readouterr().out
    assert "TST track record as of " in out and "(the last day ended in New York)" in out


def test_track_record_json_is_plain_json(company, tmp_path, monkeypatch, capsys):
    import json

    wire(monkeypatch, company, tmp_path)
    _track_record_origins(company, monkeypatch)
    args = ["track-record", "--ticker", "TST", "--as-of", "2021-07-01", "--json"]
    assert cli.main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"ticker", "rows", "summaries", "notes"} <= set(data)
    assert data["ticker"] == "TST" and data["as_of"] == "2021-07-01"
    assert [r["period"] for r in data["rows"]] == ["FY2021Q1"]
    assert data["rows"][0]["items"]["revenue"]["signed_miss"] == 0.25
    assert len(data["summaries"]) == 10


def test_track_record_on_an_unknown_ticker_exits_1(company, tmp_path, monkeypatch, capsys):
    wire(monkeypatch, company, tmp_path)
    assert cli.main(["track-record", "--ticker", "ZZZ", "--as-of", "2021-07-01"]) == 1
    assert "has not been ingested" in capsys.readouterr().out
