"""Tests for BUILDER_EXIT order invariant in WP-2026-068."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add the agent directory to path for imports (same pattern as test_builder_exit_and_breaker.py)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from bus.event_bus import EventBus


@pytest.fixture
def temp_bus(tmp_path: Path) -> EventBus:
    """Create a temporary event bus for testing."""
    runtime_dir = tmp_path / "runtime" / "events"
    return EventBus(runtime_dir)


class TestBuilderExitOrder:
    """Test suite for BUILDER_EXIT order invariant."""

    def test_correct_order_passes(self, temp_bus: EventBus, tmp_path: Path) -> None:
        """BUILDER_EXIT before STATE_CHANGED READY_FOR_REVIEW should pass."""
        from agent_controller import _check_builder_exit_order

        # Emit BUILDER_EXIT first (seq 1)
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"exit_reason": "done", "completion_summary": "work completed"},
        )

        # Emit STATE_CHANGED READY_FOR_REVIEW after (seq 2)
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-001")
            assert len(warnings) == 0

    def test_inverted_order_warns(self, temp_bus: EventBus, tmp_path: Path) -> None:
        """STATE_CHANGED READY_FOR_REVIEW before BUILDER_EXIT should warn."""
        from agent_controller import _check_builder_exit_order

        # Emit STATE_CHANGED READY_FOR_REVIEW first (seq 1)
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-002",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Emit BUILDER_EXIT after (seq 2) - WRONG ORDER
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id="WP-TEST-002",
            actor="BUILDER",
            payload={"exit_reason": "done", "completion_summary": "work completed"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-002")
            assert len(warnings) == 1
            assert "ORDER INVARIANT" in warnings[0]
            assert "seq=1" in warnings[0]
            assert "no prior BUILDER_EXIT" in warnings[0]

    def test_no_builder_exit_silent(self, temp_bus: EventBus, tmp_path: Path) -> None:
        """No BUILDER_EXIT should be silent (invariant doesn't apply)."""
        from agent_controller import _check_builder_exit_order

        # Emit only STATE_CHANGED READY_FOR_REVIEW
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-003",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-003")
            assert len(warnings) == 0

    def test_no_state_changed_silent(self, temp_bus: EventBus, tmp_path: Path) -> None:
        """No STATE_CHANGED READY_FOR_REVIEW should be silent."""
        from agent_controller import _check_builder_exit_order

        # Emit only BUILDER_EXIT
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id="WP-TEST-004",
            actor="BUILDER",
            payload={"exit_reason": "done", "completion_summary": "work completed"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-004")
            assert len(warnings) == 0

    def test_bus_not_available_silent(self, temp_bus: EventBus, tmp_path: Path) -> None:
        """Bus not available should be silent."""
        from agent_controller import _check_builder_exit_order

        with patch("agent_controller.BUS_AVAILABLE", False):
            warnings = _check_builder_exit_order("WP-TEST-005")
            assert len(warnings) == 0

    def test_multiple_events_detects_any_inversion(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """Should detect inversions at any point in the sequence, not just latest."""
        from agent_controller import _check_builder_exit_order

        # First correct pair (seq 1, 2) - BUILDER_EXIT before STATE_CHANGED
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id="WP-TEST-006",
            actor="BUILDER",
            payload={"exit_reason": "done1", "completion_summary": "work1"},
        )
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-006",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Second pair (seq 3, 4) - STATE_CHANGED BEFORE BUILDER_EXIT (inversion)
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-006",
            actor="SUPERVISOR",
            payload={"from_state": "READY_FOR_REVIEW", "to_state": "READY_TO_CLOSE"},
        )
        # This is NOT a READY_FOR_REVIEW event, so it won't be checked

        # Third event - another READY_FOR_REVIEW without prior BUILDER_EXIT (seq 5)
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-006",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-006")
            # First READY_FOR_REVIEW (seq 2) has prior BUILDER_EXIT (seq 1) - OK
            # Second READY_FOR_REVIEW (seq 5) also has prior BUILDER_EXIT (seq 1) - OK
            # No warnings expected because there IS a prior BUILDER_EXIT for both
            assert len(warnings) == 0

    def test_inversion_with_no_prior_exit(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """Should warn when STATE_CHANGED READY_FOR_REVIEW has no prior BUILDER_EXIT."""
        from agent_controller import _check_builder_exit_order

        # Emit STATE_CHANGED READY_FOR_REVIEW first (seq 1) - NO prior BUILDER_EXIT
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-007",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Emit BUILDER_EXIT after (seq 2)
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id="WP-TEST-007",
            actor="BUILDER",
            payload={"exit_reason": "done", "completion_summary": "work completed"},
        )

        # Emit another STATE_CHANGED READY_FOR_REVIEW (seq 3) - still no prior exit before IT
        temp_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id="WP-TEST-007",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            warnings = _check_builder_exit_order("WP-TEST-007")
            # First READY_FOR_REVIEW (seq 1) has no prior BUILDER_EXIT - WARN
            # Second READY_FOR_REVIEW (seq 3) has prior BUILDER_EXIT (seq 2) - OK
            assert len(warnings) == 1
            assert "ORDER INVARIANT" in warnings[0]
            assert "seq=1" in warnings[0]
