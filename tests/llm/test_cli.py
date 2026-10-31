"""The LLM command line end to end with recorded answers, the dry run and the report (Step 7)."""

import pytest

from domains.llm import __main__ as cli
from domains.llm.client import FakeClient
from shared_kernel.database import get_db_connection
from tests.llm.test_extract import answer, story
from tests.news.test_store import conn  # noqa: F401 - the conn fixture


@pytest.fixture
def wired(conn, db_path, tmp_path, monkeypatch):  # noqa: F811
    """The CLI on the test database, with a fake model and a report folder in tmp."""
    monkeypatch.setattr(
        cli, "get_db_connection", lambda path=None: get_db_connection(path or db_path)
    )
    monkeypatch.setattr(cli, "DB_PATH", db_path)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = FakeClient(answer())
    monkeypatch.setattr(cli, "AnthropicClient", lambda key: fake)
    return fake


def test_classify_then_report_end_to_end(conn, wired, tmp_path, capsys):  # noqa: F811
    story(conn)
    assert cli.main(["classify", "--case", "MSFT_2022-06-02"]) == 0
    assert "MSFT_2022-06-02  named 1  masked 1" in capsys.readouterr().out
    assert len(wired.requests) == 2
    assert cli.main(["report"]) == 0
    text = (tmp_path / "reports" / "llm" / "llm_report.md").read_text()
    assert "| MSFT_2022-06-02 | masked | 1 (1) | 1 / 0 |" in text
    assert "same type: 1" in text and "does not remove it" in text
    assert "| extract_events | claude-haiku-5-5 | 2 | 2 / 0 / 0 |" in text


def test_dry_run_calls_nothing_counts_calls_and_leaves_the_database(conn, wired,  # noqa: F811
                                                                    capsys):  # fmt: skip
    story(conn)
    assert cli.main(["classify", "--case", "MSFT_2022-06-02", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "claude-haiku-5-5: 2 calls" in out
    assert wired.requests == []
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM event_classifications").fetchone()[0] == 0


def test_a_missing_key_stops_before_any_call(conn, wired, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("WARREN_ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["classify", "--case", "MSFT_2022-06-02"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err and wired.requests == []


def test_a_spent_budget_stops_cleanly(conn, wired, capsys):  # noqa: F811
    story(conn)
    story(conn, first=10, count=3, hours=100)  # a second event, days later
    code = cli.main(["classify", "--case", "MSFT_2022-06-02", "--max-tokens-total", "100"])
    assert code == 3 and "Run the same command again" in capsys.readouterr().out
    assert len(wired.requests) == 1
