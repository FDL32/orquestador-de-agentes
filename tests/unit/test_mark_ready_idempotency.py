"""Tests for WP-2026-143: Bus-backed mark-ready idempotency."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import (  # noqa: E402
    _ensure_active_builder_round,
    _handle_mark_ready,
)


class TestMarkReadyIdempotency:
    """Test bus-backed idempotency for --mark-ready."""

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_op_when_bus_state_is_ready_for_review(self, mock_bus, mock_load):
        """Bus state READY_FOR_REVIEW should return clean no-op."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        mock_bus.read_events.return_value = [mock_event]

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 0
        mock_bus.emit.assert_not_called()

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_op_when_bus_state_is_ready_to_close(self, mock_bus, mock_load):
        """Bus state READY_TO_CLOSE should return clean no-op."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_TO_CLOSE"},
        }
        mock_bus.read_events.return_value = [mock_event]

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 0
        mock_bus.emit.assert_not_called()

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_op_when_bus_state_is_completed(self, mock_bus, mock_load):
        """Bus state COMPLETED should return clean no-op."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "COMPLETED"},
        }
        mock_bus.read_events.return_value = [mock_event]

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 0
        mock_bus.emit.assert_not_called()

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_blocked_when_bus_state_is_human_gate(self, mock_bus, mock_load):
        """Bus state HUMAN_GATE should block mark-ready."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "REVIEW_DECISION",
            "payload": {"decision": "inspect"},
        }
        mock_bus.read_events.return_value = [mock_event]

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 1

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", False)
    def test_fallback_to_markdown_when_bus_unavailable(self, mock_load):
        """When bus is unavailable, fallback to markdown-based logic."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** READY_FOR_REVIEW",
            "WP-2026-143",
        )

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 0

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_emits_events_when_bus_state_is_in_progress(self, mock_bus, mock_load):
        """Bus state IN_PROGRESS should allow mark-ready to proceed."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.latest_event.return_value = None

        with (
            patch("agent_controller._scope_gate_allows_close", return_value=True),
            patch("agent_controller._check_implementation_evidence", return_value=[]),
            patch(
                "agent_controller._run_pre_handoff_guard",
                return_value={"valid": True},
            ),
            patch("agent_controller._emit_builder_exit"),
            patch("agent_controller._sync_mark_ready_targets"),
            patch("agent_controller._reset_circuit_breaker"),
            patch("agent_controller._release_builder_lock"),
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 0

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_json_output_when_bus_state_is_ready_for_review(self, mock_bus, mock_load):
        """JSON output should include bus_state when already ready."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        mock_bus.read_events.return_value = [mock_event]

        with patch("builtins.print") as mock_print:
            result = _handle_mark_ready(
                scope_override=None, json_output=True, force_mode=False
            )

            assert result == 0
            json_call = mock_print.call_args_list[0]
            import json

            output = json.loads(json_call[0][0])
            assert output["status"] == "already_ready"
            assert output["bus_state"] == "READY_FOR_REVIEW"

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_events_when_bus_state_unknown_but_no_events(self, mock_bus, mock_load):
        """When bus has no events, should proceed with normal flow."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WP-2026-143",
            "**Estado:** IN_PROGRESS",
            "WP-2026-143",
        )

        mock_bus.read_events.return_value = []
        mock_bus.latest_event.return_value = None

        with (
            patch("agent_controller._scope_gate_allows_close", return_value=True),
            patch("agent_controller._check_implementation_evidence", return_value=[]),
            patch(
                "agent_controller._run_pre_handoff_guard",
                return_value={"valid": True},
            ),
            patch("agent_controller._emit_builder_exit"),
            patch("agent_controller._sync_mark_ready_targets"),
            patch("agent_controller._reset_circuit_breaker"),
            patch("agent_controller._release_builder_lock"),
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 0

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    @patch("agent_controller._ensure_active_builder_round")
    def test_blocks_stale_builder_round_before_mark_ready(
        self, mock_round, mock_bus, mock_load
    ):
        """A stale Builder shell must not emit READY_FOR_REVIEW or release the lock."""

        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-221b",
            "**Estado:** IN_PROGRESS",
            "WT-2026-221b",
        )
        mock_round.return_value = (False, 3, "stale Builder round 3; active round is 4")

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 1
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert handoff_events, "stale mark-ready must emit HANDOFF_BLOCKED"

    def test_builder_round_check_accepts_powershell_utf8_bom_lock(
        self, tmp_path, monkeypatch
    ):
        """PowerShell 5.1 UTF8 locks include a BOM; active Builders must still pass."""

        lock_path = tmp_path / "builder_lock.txt"
        lock_path.write_text(
            '{"ticket_id":"WT-2026-221b","round":4}', encoding="utf-8-sig"
        )
        monkeypatch.setattr("agent_controller.BUILDER_LOCK_PATH", lock_path)
        monkeypatch.setenv("AGENT_BUILDER_TICKET", "WT-2026-221b")
        monkeypatch.setenv("AGENT_BUILDER_ROUND", "4")

        assert _ensure_active_builder_round("WT-2026-221b") == (True, 4, None)

        monkeypatch.setenv("AGENT_BUILDER_ROUND", "3")

        assert _ensure_active_builder_round("WT-2026-221b") == (
            False,
            3,
            "stale Builder round 3; active round is 4",
        )
