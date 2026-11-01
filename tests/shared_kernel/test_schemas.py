from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from domains.orchestration.state import PipelineState
from shared_kernel.schemas import TelemetryEvent


def test_telemetry_event_defaults_to_timezone_aware_now():
    before = datetime.now(UTC)
    event = TelemetryEvent(pipeline_id="p1", node="node", status="started")
    after = datetime.now(UTC)

    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timedelta(0)
    assert before <= event.timestamp <= after


def test_telemetry_event_refuses_an_unknown_field_or_status():
    with pytest.raises(ValidationError):
        TelemetryEvent(pipeline_id="p1", node="n", status="started", prompt="x")
    with pytest.raises(ValidationError):
        TelemetryEvent(pipeline_id="p1", node="n", status="running")


def test_pipeline_state_has_no_current_node():
    # Decision 2: LangGraph tracks the node; the M7 state replaces the SimulationState placeholder
    assert "current_node" not in PipelineState.model_fields
