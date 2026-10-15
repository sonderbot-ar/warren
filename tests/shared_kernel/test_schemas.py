from datetime import UTC, datetime, timedelta

from shared_kernel.schemas import SimulationState, TelemetryEvent


def test_telemetry_event_defaults_to_timezone_aware_now():
    before = datetime.now(UTC)
    event = TelemetryEvent(agent_name="node", task_id="t1", status="running")
    after = datetime.now(UTC)

    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timedelta(0)
    assert before <= event.timestamp <= after


def test_simulation_state_has_no_current_node():
    assert "current_node" not in SimulationState.model_fields
    SimulationState(session_id="s1", current_ticker="AAPL")
