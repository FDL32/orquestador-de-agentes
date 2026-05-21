"""Tests for STATE_CHANGED emission on --mark-ready."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add the agent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from agent_controller import _sync_mark_ready_targets


class TestBusEmissionOnMarkReady:
    """Test idempotent emission of STATE_CHANGED events."""

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    def test_emits_state_changed_with_correct_schema(self, mock_write, mock_read, mock_update_turn, mock_bus):
        """Test emission with correct schema: actor=SUPERVISOR, payload with from_state/to_state/reason/source."""
        # Mock bus available
        mock_bus.latest_event.return_value = None
        mock_bus.emit.return_value = MagicMock()

        # Mock file contents
        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else ""

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        # Assert emit was called with correct schema
        mock_bus.emit.assert_called_once()
        call_kwargs = mock_bus.emit.call_args.kwargs
        assert call_kwargs["event_type"] == "STATE_CHANGED"
        assert call_kwargs["ticket_id"] == "WP-2026-063"
        assert call_kwargs["actor"] == "SUPERVISOR"
        assert "payload" in call_kwargs
        payload = call_kwargs["payload"]
        assert "from_state" in payload
        assert payload["to_state"] == "READY_FOR_REVIEW"
        assert "reason" in payload
        assert payload["source"] == "mark-ready"

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    def test_no_emission_when_already_emitted_same_state(self, mock_write, mock_read, mock_update_turn, mock_bus):
        """Test no emission when STATE_CHANGED already exists for same to_state."""
        # Mock existing event with same to_state
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "READY_FOR_REVIEW", "from_state": "IN_PROGRESS", "reason": "test", "source": "mark-ready"}
        mock_bus.latest_event.return_value = mock_event

        # Mock file contents
        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else ""

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        # Assert emit was not called
        mock_bus.emit.assert_not_called()

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    def test_emits_when_previous_event_different_state(self, mock_write, mock_read, mock_update_turn, mock_bus):
        """Test emission when previous event has different to_state."""
        # Mock existing event with different to_state
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS", "from_state": "DRAFT", "reason": "test", "source": "manual"}
        mock_bus.latest_event.return_value = mock_event
        mock_bus.emit.return_value = MagicMock()

        # Mock file contents
        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else ""

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        # Assert emit was called with correct schema
        mock_bus.emit.assert_called_once()
        call_kwargs = mock_bus.emit.call_args.kwargs
        assert call_kwargs["actor"] == "SUPERVISOR"
        assert call_kwargs["payload"]["to_state"] == "READY_FOR_REVIEW"
        assert call_kwargs["payload"]["source"] == "mark-ready"

    @patch('agent_controller.event_bus', None)  # Bus not available
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    def test_no_emission_when_bus_unavailable(self, mock_write, mock_read, mock_update_turn):
        """Test no emission when bus is not available."""
        # Mock file contents
        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else ""

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        # No assertion needed, just ensure no error when bus is None

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    def test_from_state_derived_from_bus_not_markdown(
        self, mock_write, mock_read, mock_update_turn, mock_bus
    ):
        """WP-2026-109: from_state must come from the last bus STATE_CHANGED.

        Even if the markdown is ahead, the emitted from_state must reflect the
        bus (here IN_PROGRESS), preventing a spurious READY_FOR_REVIEW no-op.
        """
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS", "from_state": "READY_FOR_REVIEW"}
        mock_bus.latest_event.return_value = mock_event
        mock_bus.emit.return_value = MagicMock()

        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else ""

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        mock_bus.emit.assert_called_once()
        payload = mock_bus.emit.call_args.kwargs["payload"]
        # from_state derives from the bus event's to_state, not the markdown.
        assert payload["from_state"] == "IN_PROGRESS"
        assert payload["to_state"] == "READY_FOR_REVIEW"
        # The emitted transition is real, not a no-op.
        assert payload["from_state"] != payload["to_state"]
