"""The command line end to end on Test Corp with a fake model (M7 Step 5)."""

import pytest

from domains.orchestration import __main__ as cli
from domains.orchestration import graph
from shared_kernel.database import get_db_connection


@pytest.fixture
def wired(world, db_path, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_db_connection",
                        lambda path=None: get_db_connection(path or db_path))  # fmt: skip
    monkeypatch.setattr(cli, "FOLDERS", graph.Folders(tmp_path / "reports", tmp_path / "tel"))
    monkeypatch.setattr(cli, "make_deps", lambda conn: _deps(world, conn))
    monkeypatch.setenv("WARREN_ANTHROPIC_API_KEY", "sk-test")
    return world


def _deps(world, conn):
    deps = world.deps()
    deps.conn = conn
    return deps


ARGS = ["run", "--ticker", "TST", "--as-of", "2020-06-30", "--seed", "7", "--n", "200"]


def test_run_end_to_end_writes_a_report_and_telemetry(wired, tmp_path, capsys):
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "TST_2020-06-30_p1  value per share baseline" in out and "named p10" in out
    assert (tmp_path / "reports" / "TST_2020-06-30_p1.md").exists()
    assert (tmp_path / "tel" / "TST_2020-06-30_p1.jsonl").exists()
    assert cli.main(["show", "--pipeline-id", "TST_2020-06-30_p1"]) == 0
    assert "write_report" in capsys.readouterr().out


def test_reproduce_passes_and_fails_after_a_stored_output_changes(wired, capsys):
    assert cli.main(ARGS) == 0
    assert cli.main(["reproduce", "--pipeline-id", "TST_2020-06-30_p1"]) == 0
    out = capsys.readouterr().out
    assert out.count("OK") == 3 and "MISMATCH" not in out
    wired.conn.execute("UPDATE simulation_outputs SET p50 = p50 + 1 WHERE name = 'revenue'")
    wired.conn.commit()
    assert cli.main(["reproduce", "--pipeline-id", "TST_2020-06-30_p1"]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_later_exits_4_and_resume_asks_then_finishes(wired, monkeypatch, capsys):
    assert cli.main([*ARGS, "--review", "later"]) == 4
    assert "resume --pipeline-id TST_2020-06-30_p1" in capsys.readouterr().out
    answers = iter(["r", "too small to matter"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["resume", "--pipeline-id", "TST_2020-06-30_p1"]) == 0
    assert "named no shock" in capsys.readouterr().out


def test_a_missing_key_exits_2_before_anything_runs(wired, monkeypatch, capsys):
    monkeypatch.delenv("WARREN_ANTHROPIC_API_KEY")
    assert cli.main(ARGS) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert wired.conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 0
    assert wired.client.requests == []


def test_a_bad_date_exits_2(wired):
    assert cli.main(["run", "--ticker", "TST", "--as-of", "jun.30.2020"]) == 2


def test_run_without_a_date_takes_the_last_day_ended_in_new_york(wired, capsys):
    # the world's clock is 2026-11-01 20:00 UTC; offline, the old download stops the run early
    assert cli.main(["run", "--ticker", "TST", "--offline", "--seed", "7"]) == 1
    out = capsys.readouterr().out
    assert "as of 2026-10-31 (the latest day that has ended in New York)" in out
    row = wired.conn.execute("SELECT pipeline_id, as_of FROM pipeline_runs").fetchone()
    assert tuple(row) == ("TST_2026-10-31_p1", "2026-10-31")
    assert "no EDGAR download from after 2026-10-31" in out
