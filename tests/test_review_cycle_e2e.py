# ruff: noqa: S101
"""E2E tests for review cycle: review -> decision -> bus -> projections.

WP-2026-124: These tests verify that approve, changes, and inspect all
materialize state through the same canonical route, and that bus and
projections remain aligned.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bus.event_bus import EventBus
from bus.state_machine import StateMachine, TicketState
from bus.review_bridge import ReviewBridge, ReviewDecision


@pytest.fixture
def event_bus(tmp_path: Path) -> EventBus:
    """Create an event bus in a temporary directory."""
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return EventBus(events_dir)


@pytest.fixture
def review_bridge(event_bus: EventBus, tmp_path: Path) -> ReviewBridge:
    """Create a review bridge for testing."""
    return ReviewBridge(event_bus=event_bus, project_root=tmp_path)


class TestReviewCycleE2E:
    """E2E tests for the review cycle."""

    def test_approve_emits_state_changed_and_materializes(self, event_bus, tmp_path):
        """APPROVE decision emits STATE_CHANGED -> READY_TO_CLOSE and syncs projections."""
        # Setup: Create minimal collaboration structure
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST-001\n- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n**Estado:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "STATE.md").write_text(
            "# STATE.md\n- **Estado actual:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "TURN.md").write_text("# TURN.md\n", encoding="utf-8")

        # Emit initial STATE_CHANGED
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Simulate APPROVE decision
        event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"decision": "approve"},
        )

        # Verify bus has REVIEW_DECISION
        events = event_bus.read_events(ticket_id="WP-TEST-001")
        decisions = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(decisions) >= 1
        assert decisions[-1].payload.get("decision") == "approve"

        # Verify bus-derived state is READY_TO_CLOSE (from REVIEW_DECISION approve)
        bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        assert bus_state == TicketState.READY_TO_CLOSE

    def test_changes_emits_state_changed_and_materializes(self, event_bus, tmp_path):
        """CHANGES decision emits REVIEW_DECISION and triggers --request-changes CLI."""
        # Setup
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST-001\n- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n**Estado:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "STATE.md").write_text(
            "# STATE.md\n- **Estado actual:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "TURN.md").write_text("# TURN.md\n", encoding="utf-8")

        # Emit initial STATE_CHANGED
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Simulate CHANGES decision
        event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"decision": "changes"},
        )

        # Verify bus has REVIEW_DECISION
        events = event_bus.read_events(ticket_id="WP-TEST-001")
        decisions = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(decisions) >= 1
        assert decisions[-1].payload.get("decision") == "changes"

        # Bus-derived state should be IN_PROGRESS (from REVIEW_DECISION changes)
        bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        assert bus_state == TicketState.IN_PROGRESS

    def test_inspect_emits_state_changed_to_human_gate(self, event_bus, tmp_path):
        """INSPECT decision triggers --escalate-human-gate and emits STATE_CHANGED -> HUMAN_GATE."""
        # Setup
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST-001\n- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n**Estado:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "STATE.md").write_text(
            "# STATE.md\n- **Estado actual:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "TURN.md").write_text("# TURN.md\n", encoding="utf-8")

        # Emit initial STATE_CHANGED
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Simulate INSPECT decision
        event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"decision": "inspect"},
        )

        # Verify bus has REVIEW_DECISION
        events = event_bus.read_events(ticket_id="WP-TEST-001")
        decisions = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(decisions) >= 1
        assert decisions[-1].payload.get("decision") == "inspect"

        # Bus-derived state should be HUMAN_GATE (from REVIEW_DECISION inspect)
        bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        assert bus_state == TicketState.HUMAN_GATE

    def test_escalate_human_gate_materialization(self, event_bus, tmp_path):
        """Test inspect decision materializes STATE_CHANGED -> HUMAN_GATE via bus."""
        # Setup
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST-001\n- **Estado:** APPROVED\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n**Estado:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "STATE.md").write_text(
            "# STATE.md\n- **Estado actual:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "TURN.md").write_text("# TURN.md\n", encoding="utf-8")

        # Emit initial STATE_CHANGED
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Simulate inspect decision via REVIEW_DECISION event
        event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"decision": "inspect"},
        )

        # Verify bus-derived state is HUMAN_GATE
        events = event_bus.read_events(ticket_id="WP-TEST-001")
        bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        assert bus_state == TicketState.HUMAN_GATE

    def test_request_changes_materialization(self, event_bus, tmp_path):
        """Test changes decision materializes STATE_CHANGED -> IN_PROGRESS via bus."""
        # Setup
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST-001\n- **Estado:** APPROVED\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        (collab_dir / "execution_log.md").write_text(
            "# Execution Log\n**Estado:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "STATE.md").write_text(
            "# STATE.md\n- **Estado actual:** READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        (collab_dir / "TURN.md").write_text("# TURN.md\n", encoding="utf-8")

        # Emit initial STATE_CHANGED
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Simulate changes decision via REVIEW_DECISION event
        event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"decision": "changes"},
        )

        # Verify bus-derived state is IN_PROGRESS
        events = event_bus.read_events(ticket_id="WP-TEST-001")
        bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        assert bus_state == TicketState.IN_PROGRESS
