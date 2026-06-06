"""Tests for --manager-approve flag in WP-2026-068."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from bus.event_bus import EventBus


@pytest.fixture
def temp_bus(tmp_path: Path) -> EventBus:
    """Create a temporary event bus for testing."""
    runtime_dir = tmp_path / "runtime" / "events"
    return EventBus(runtime_dir)


@pytest.fixture
def mock_files(tmp_path: Path) -> dict:
    """Create mock collaboration files."""
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)

    work_plan = collab_dir / "work_plan.md"
    work_plan.write_text(
        "# Plan de Trabajo: WP-TEST-001\n\n"
        "## Metadata\n"
        "- **ID:** WP-TEST-001\n"
        "- **Estado:** APPROVED\n"
    )

    exec_log = collab_dir / "execution_log.md"
    exec_log.write_text(
        "# Execution Log\n\n## WP-TEST-001\n**Estado:** READY_FOR_REVIEW\n"
    )

    turn_file = collab_dir / "TURN.md"
    turn_file.write_text("# TURNO ACTUAL\n\n## Agente Activo\n")

    state_file = collab_dir / "STATE.md"
    state_file.write_text("# STATE\n\n- **Estado actual:** READY_FOR_REVIEW\n")

    return {
        "work_plan": work_plan,
        "exec_log": exec_log,
        "turn": turn_file,
        "state": state_file,
        "collab_dir": collab_dir,
    }


class TestManagerApprove:
    """Test suite for --manager-approve flag."""

    def test_complete_cascade_emitted(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should emit complete closeout cascade."""
        from agent_controller import _handle_manager_approve

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result == 0

        # Verify cascade events were emitted
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        event_types = [e.event_type for e in events]

        assert "REVIEW_DECISION" in event_types
        assert "STATE_CHANGED" in event_types
        assert "CLOSE_CONFIRMED" in event_types
        assert "SUPERVISOR_CLOSED" in event_types

        # Verify REVIEW_DECISION payload
        review_events = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(review_events) == 1
        assert review_events[0].payload["decision"] == "approve"
        assert review_events[0].payload["note"] == "Canonical closeout approved"

        # Verify STATE_CHANGED events
        state_events = [e for e in events if e.event_type == "STATE_CHANGED"]
        assert len(state_events) >= 2  # At least READY_TO_CLOSE and COMPLETED

        to_states = [e.payload.get("to_state") for e in state_events]
        assert "READY_TO_CLOSE" in to_states
        assert "COMPLETED" in to_states

    def test_idempotency_already_completed(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve on COMPLETED ticket should be idempotent."""
        from agent_controller import _handle_manager_approve

        # Set state to COMPLETED
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** COMPLETED\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )

        assert result == 0

        # No events should be emitted
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        assert len(events) == 0

    def test_blocks_if_not_ready_for_review(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should block if ticket not in READY_FOR_REVIEW."""
        from agent_controller import _handle_manager_approve

        # Set state to IN_PROGRESS
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** IN_PROGRESS\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result != 0

        # No events should be emitted
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        assert len(events) == 0

    def test_requires_ticket_id(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should fail without ticket_id."""
        from agent_controller import _handle_manager_approve

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            result = _handle_manager_approve(None, json_output=False, force_mode=False)

        assert result != 0

    def test_json_output_on_completed(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should return JSON on already completed ticket."""
        from agent_controller import _handle_manager_approve

        # Set state to COMPLETED
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** COMPLETED\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            # Capture stdout
            captured = io.StringIO()
            sys.stdout = captured
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )
            sys.stdout = sys.__stdout__

        assert result == 0
        output = json.loads(captured.getvalue())
        assert output["status"] == "already_completed"
        assert output["ticket_id"] == "WP-TEST-001"

    def test_circuit_breaker_reset(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should reset circuit breaker on success."""
        from agent_controller import _handle_manager_approve, _read_circuit_breaker

        # Pre-set circuit breaker to OPEN
        breaker_path = tmp_path / ".agent" / "runtime" / "circuit_breaker.json"
        breaker_path.parent.mkdir(parents=True, exist_ok=True)
        breaker_path.write_text(
            '{"state": "OPEN", "failures": 3, "reason": "test failure"}'
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result == 0

        # Verify circuit breaker was reset
        breaker = _read_circuit_breaker()
        assert breaker["state"] == "CLOSED"

    def test_idempotency_via_bus_supervisor_closed(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should be idempotent if SUPERVISOR_CLOSED exists in bus."""
        from agent_controller import _handle_manager_approve

        # Pre-populate bus with SUPERVISOR_CLOSED event for this ticket
        temp_bus.emit(
            event_type="SUPERVISOR_CLOSED",
            ticket_id="WP-TEST-001",
            actor="SUPERVISOR",
            payload={"source": "manager-approve", "reason": "Already closed"},
        )

        # Set markdown state to READY_FOR_REVIEW (simulating drift)
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** READY_FOR_REVIEW\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )

        assert result == 0

        # Should return already_completed without emitting new events
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        # Only the pre-existing SUPERVISOR_CLOSED event should exist
        assert len(events) == 1
        assert events[0].event_type == "SUPERVISOR_CLOSED"

        # Verify JSON output
        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        # Re-run to capture output
        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )
        sys.stdout = sys.__stdout__

        output = json.loads(captured.getvalue())
        assert output["status"] == "already_completed"
        assert output["ticket_id"] == "WP-TEST-001"
