"""Validated, logged and budgeted LLM calls; the 0012 migration (M6 Step 2)."""

import json
import shutil
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from domains.llm import calls
from domains.llm.client import FakeClient, LLMError
from shared_kernel.database import MIGRATIONS_DIR, apply_migrations, get_db_connection

PROMPTS = Path(__file__).parent / "prompts"


class Colour(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: Literal["red", "green", "blue"]


def ask(conn, client, budget=calls.DEFAULT_BUDGET, check=None):
    prompt = calls.load_prompt("demo", 1, PROMPTS)
    return calls.structured_call(conn, client, "extract_events", prompt, {"thing": "the sky"},
                                 Colour, "sky", "batch1", budget, check)  # fmt: skip


def rows(conn):
    return conn.execute("SELECT * FROM llm_calls ORDER BY call_id").fetchall()


def test_a_valid_answer_is_stored_once_with_prompt_and_tokens(conn):
    result = ask(conn, FakeClient([{"colour": "blue"}]))
    assert result.value.colour == "blue"
    [row] = rows(conn)
    assert row["call_id"] == result.call_id and row["status"] == "ok" and row["attempt"] == 1
    assert row["prompt_name"] == "demo" and row["prompt_version"] == 1
    assert row["prompt_sha256"] == calls.load_prompt("demo", 1, PROMPTS).sha256
    assert row["model"] == "claude-haiku-5-5" and row["node"] == "extract_events"
    assert (row["input_tokens"], row["output_tokens"]) == (100, 20)
    assert json.loads(row["input_json"]) == {"thing": "the sky"}


def test_an_invalid_answer_is_asked_again_with_the_error(conn):
    client = FakeClient([{"colour": "purple"}, {"colour": "blue"}])
    assert ask(conn, client).value.colour == "blue"
    assert [r["status"] for r in rows(conn)] == ["invalid", "ok"]
    assert "previous answer was invalid" in client.requests[1]["user"]
    assert "previous answer" not in client.requests[0]["user"]


def test_an_extra_field_is_invalid(conn):
    client = FakeClient([{"colour": "blue", "value": 1.5}, {"colour": "blue"}])
    ask(conn, client)
    assert rows(conn)[0]["status"] == "invalid"


def test_three_invalid_answers_are_rejected_never_guessed(conn):
    with pytest.raises(calls.LLMRejected):
        ask(conn, FakeClient(["not json", {"colour": "pink"}, {}]))
    assert [r["status"] for r in rows(conn)] == ["invalid"] * 3


def test_a_check_failure_is_an_invalid_answer(conn):
    def no_red(value):
        if value.colour == "red":
            raise ValueError("red is not allowed")

    ask(conn, FakeClient([{"colour": "red"}, {"colour": "green"}]), check=no_red)
    assert rows(conn)[0]["error"] == "red is not allowed"


def test_an_api_error_is_logged_and_counts_as_an_attempt(conn):
    ask(conn, FakeClient([LLMError("overloaded"), {"colour": "red"}]))
    assert [r["status"] for r in rows(conn)] == ["error", "ok"]
    with pytest.raises(calls.LLMRejected):
        ask(conn, FakeClient([LLMError("down")] * 3))


def test_the_budget_refuses_the_next_call(conn):
    client = FakeClient([{"colour": "red"}] * 3, tokens=(60, 0))
    ask(conn, client, budget=100)
    ask(conn, client, budget=100)  # 60 used, under 100
    with pytest.raises(calls.BudgetSpent):
        ask(conn, client, budget=100)
    assert len(client.requests) == 2


def test_latest_prompt_takes_the_highest_version_and_versions_differ():
    v2 = calls.latest_prompt("demo", PROMPTS)
    assert v2.version == 2 and v2.sha256 != calls.load_prompt("demo", 1, PROMPTS).sha256


def test_a_prompt_without_the_user_line_is_refused(tmp_path):
    (tmp_path / "bad.v1.md").write_text("all one part {x}")
    with pytest.raises(ValueError, match="---- user ----"):
        calls.load_prompt("bad", 1, tmp_path)


def test_0012_applies_to_a_v11_database(db_path, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name[:4]) <= 11:
            shutil.copy(path, old / path.name)
    with get_db_connection(db_path) as conn:
        assert max(apply_migrations(conn, old)) == 11
        assert apply_migrations(conn) == [12, 13, 14, 15, 16]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"llm_calls", "event_classifications", "headline_checks", "shock_proposals",
                "case_llm_status", "proposal_sets", "proposal_shocks"} <= tables  # fmt: skip
