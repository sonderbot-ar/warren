"""Pipeline state, telemetry lines and migration 0015 (M7 Step 1)."""

import json
import shutil

import pytest
from langgraph.errors import GraphInterrupt
from pydantic import ValidationError

from domains.llm import scales
from domains.orchestration import telemetry
from domains.orchestration.state import PipelineState
from shared_kernel.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    current_schema_version,
    get_db_connection,
)
from shared_kernel.schemas import TelemetryEvent
from tests.orchestration.conftest import new_state


def state(**changes) -> PipelineState:
    return new_state(**changes)


def test_state_refuses_an_unknown_field_and_builds_the_case_id():
    with pytest.raises(ValidationError):
        state(conn="a connection")  # state is checkpointed: plain data only
    assert state().case_id == "TST_2020-06-30"


def test_state_is_small_and_round_trips_as_json():
    s = state(classified={"named": {"total": 15}}, proposals={"named": ["revenue down medium"]})
    text = s.model_dump_json()
    assert len(text) < 4000
    assert PipelineState.model_validate_json(text) == s


@pytest.fixture
def conn(db_path):
    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        yield conn


def ticks():
    t = iter(range(0, 100, 2))
    return lambda: next(t) / 1000


def test_a_node_writes_a_started_and_an_ok_line_that_validate(conn, tmp_path):
    emitter = telemetry.Emitter(tmp_path / "t.jsonl")
    node = telemetry.traced("build_baseline", lambda s: {"run_id": "r"}, emitter, conn, ticks())
    assert node(state()) == {"run_id": "r"}
    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    assert [json.loads(line)["status"] for line in lines] == ["started", "ok"]
    events = [TelemetryEvent.model_validate_json(line) for line in lines]
    assert events[1].duration_ms == 2 and events[1].llm == []
    assert {e.pipeline_id for e in events} == {"TST_2020-06-30_p1"}


def test_an_error_line_has_type_and_message_and_no_traceback(conn, tmp_path):
    emitter = telemetry.Emitter(tmp_path / "t.jsonl")

    def fails(s):
        raise ValueError("no prices on or before 2020-06-30\nsecond line")

    with pytest.raises(ValueError):
        telemetry.traced("load_market", fails, emitter, conn)(state())
    end = emitter.read()[-1]
    assert end.status == "error"
    assert end.error == "ValueError: no prices on or before 2020-06-30"
    assert "Traceback" not in (tmp_path / "t.jsonl").read_text()


def test_an_interrupt_is_its_own_status(conn, tmp_path):
    emitter = telemetry.Emitter(tmp_path / "t.jsonl")

    def waits(s):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        telemetry.traced("review_shocks", waits, emitter, conn)(state())
    assert emitter.read()[-1].status == "interrupted"


def test_llm_lines_sum_every_attempt_of_the_nodes_batch(conn, tmp_path):
    rows = [("TST_2020-06-30_p1:extract_events", "claude-haiku-5-5", "ok", 100, 10),
            ("TST_2020-06-30_p1:extract_events", "claude-haiku-5-5", "invalid", 120, 12),
            ("other:extract_events", "claude-haiku-5-5", "ok", 999, 99)]  # fmt: skip
    for batch, model, status, i, o in rows:
        conn.execute(
            "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
            "prompt_sha256, ref, attempt, input_json, status, input_tokens, output_tokens) "
            "VALUES (?, 'extract_events', ?, 'p', 1, 's', 'r', 1, '{}', ?, ?, ?)",
            (batch, model, status, i, o),
        )
    emitter = telemetry.Emitter(tmp_path / "t.jsonl")
    telemetry.traced("extract_events", lambda s: {}, emitter, conn)(state())
    [usage] = emitter.read()[-1].llm
    assert (usage.model, usage.calls, usage.invalid) == ("claude-haiku-5-5", 2, 1)
    assert (usage.input_tokens, usage.output_tokens) == (220, 22)


@pytest.mark.parametrize("name", telemetry.TRACING_VARIABLES)
def test_tracing_to_an_outside_service_is_refused(name):
    with pytest.raises(telemetry.TelemetryError, match=name):
        telemetry.check_tracing_off({name: "true"})
    telemetry.check_tracing_off({name: "false"})


def test_migration_0015_applies_to_a_v14_database(db_path, tmp_path):
    before = tmp_path / "migrations_0014"
    before.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 14:
            shutil.copy(path, before / path.name)
    with get_db_connection(db_path) as conn:
        apply_migrations(conn, before)
        assert current_schema_version(conn) == 14
        conn.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000123', 'TST', 'T')")
        conn.execute(
            "INSERT INTO ingest_runs (run_id, cik, companyfacts_sha256, concept_map_sha256, "
            "facts_kept, facts_new) VALUES (1, '0000000123', 'a', 'b', 0, 0)"
        )
        conn.execute(
            "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
            "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
            "VALUES ('TST_2019-06-30_1', '0000000123', 'TST', '2019-06-30', 'c', 1, 'b', 'p', "
            "'i', 'y')"
        )
        conn.execute(
            "INSERT INTO event_runs (event_run_id, cik, as_of, tz, params_json, input_sha256, "
            "code_version) VALUES ('r1', '0000000123', '2019-06-30', 'America/New_York', '{}', "
            "'x', 'c')"
        )
        conn.execute(
            "INSERT INTO proposal_sets (set_id, case_id, event_run_id, variant, model, "
            "prompt_sha256, inputs_sha256, run_id, status) VALUES (7, 'C', 'r1', 'named', 'm', "
            "'p', 'x', 'TST_2019-06-30_1', 'ok')"
        )
        conn.execute(
            "INSERT INTO shock_proposals (set_id, driver, direction, size, duration, "
            "start_quarter, rationale, evidence_json, sigma, low, base, high, horizon, decay, "
            "clipped, status) VALUES (7, 'operating_margin', 'down', 'small', 'fading', 1, 'r', "
            "'[]', 0.01, -0.02, -0.01, 0, 8, 0.7, 0, 'auto_approved')"
        )
        conn.commit()
        assert apply_migrations(conn) == [15, 16]
        kept = conn.execute("SELECT * FROM proposal_sets WHERE set_id = 7").fetchone()
        assert kept["run_id"] == "TST_2019-06-30_1" and kept["inputs_sha256"] == "x"
        assert kept["scales_sha256"] == scales.scales_sha256()  # the file is unchanged since M6
        assert conn.execute("SELECT set_id FROM shock_proposals").fetchone()[0] == 7
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(shock_proposals)")}
        assert "reviewed_at" in cols
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
        # LangGraph's checkpointer creates these two in the same file; no Warren table may
        assert "pipeline_runs" in tables and not {"checkpoints", "writes"} & tables
