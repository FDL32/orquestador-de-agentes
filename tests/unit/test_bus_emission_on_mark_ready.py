"""Tests for STATE_CHANGED emission on --mark-ready."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import _sync_mark_ready_targets


class TestBusEmissionOnMarkReady:
    """Test idempotent emission of STATE_CHANGED events."""

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    @patch('agent_controller.BUS_AVAILABLE', True)
    def test_emits_state_changed_with_correct_schema(self, mock_write, mock_read, mock_update_turn, mock_bus):
        mock_bus.latest_event.return_value = None
        mock_bus.read_events.return_value = []
        mock_bus.emit.return_value = MagicMock()

        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else "**Estado:** IN_PROGRESS"

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        emit_calls = mock_bus.emit.call_args_list
        assert len(emit_calls) >= 1
        first_call = emit_calls[0]
        kwargs = first_call.kwargs
        assert kwargs["event_type"] == "STATE_CHANGED"
        assert kwargs["ticket_id"] == "WP-2026-063"
        assert kwargs["actor"] == "BUILDER"
        assert kwargs["payload"]["to_state"] == "READY_FOR_REVIEW"
        assert kwargs["payload"]["source"] == "mark-ready"

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    @patch('agent_controller.BUS_AVAILABLE', True)
    def test_no_emission_when_already_emitted_same_state(self, mock_write, mock_read, mock_update_turn, mock_bus):
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "READY_FOR_REVIEW", "from_state": "IN_PROGRESS", "reason": "test", "source": "mark-ready"}
        mock_bus.latest_event.return_value = mock_event

        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else "**Estado:** READY_FOR_REVIEW"

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        mock_bus.emit.assert_not_called()

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    @patch('agent_controller.BUS_AVAILABLE', True)
    def test_emits_when_previous_event_different_state(self, mock_write, mock_read, mock_update_turn, mock_bus):
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS", "from_state": "DRAFT", "reason": "test", "source": "manual"}
        mock_bus.latest_event.return_value = mock_event
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.emit.return_value = MagicMock()

        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else "**Estado:** IN_PROGRESS"

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        emit_calls = mock_bus.emit.call_args_list
        assert len(emit_calls) >= 1
        first_call = emit_calls[0]
        kwargs = first_call.kwargs
        assert kwargs["actor"] == "BUILDER"
        assert kwargs["payload"]["to_state"] == "READY_FOR_REVIEW"
        assert kwargs["payload"]["source"] == "mark-ready"

    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    @patch('agent_controller.BUS_AVAILABLE', False)
    def test_no_emission_when_bus_unavailable(self, mock_write, mock_read, mock_update_turn):
        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else "**Estado:** IN_PROGRESS"

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

    @patch('agent_controller.event_bus')
    @patch('agent_controller.update_turn_file')
    @patch('agent_controller.read_file')
    @patch('agent_controller.write_file')
    @patch('agent_controller.BUS_AVAILABLE', True)
    def test_from_state_derived_from_bus_not_markdown(
        self, mock_write, mock_read, mock_update_turn, mock_bus
    ):
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS", "from_state": "READY_FOR_REVIEW"}
        mock_event.event_type = "STATE_CHANGED"
        mock_event.ticket_id = "WP-2026-063"
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS", "from_state": "READY_FOR_REVIEW"},
        }
        mock_bus.latest_event.return_value = mock_event
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.emit.return_value = MagicMock()

        mock_read.side_effect = lambda path: "content" if "STATE.md" in str(path) else "**Estado:** IN_PROGRESS"

        plan_content = "**Estado:** APPROVED\n**ID:** WP-2026-063"
        _sync_mark_ready_targets("WP-2026-063", plan_content)

        emit_calls = mock_bus.emit.call_args_list
        assert len(emit_calls) >= 1
        first_payload = emit_calls[0].kwargs["payload"]
        assert first_payload["from_state"] == "IN_PROGRESS"
        assert first_payload["to_state"] == "READY_FOR_REVIEW"
