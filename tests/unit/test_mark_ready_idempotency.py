"""Tests for WP-2026-143: Bus-backed mark-ready idempotency."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import (  # noqa: E402
    _ensure_active_builder_round,
    _handle_mark_ready,
    _is_bus_state_post_success,
    _sync_mark_ready_targets,
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
        # _sync_mark_ready_targets may emit STATE_CHANGED for READY_FOR_REVIEW;
        # verify no blocking events are emitted.
        blocked_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type")
            in ("HANDOFF_BLOCKED", "STALE_BUILDER_ORPHAN")
        ]
        assert not blocked_events, (
            "no-op must not emit HANDOFF_BLOCKED or STALE_BUILDER_ORPHAN"
        )

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
        blocked_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type")
            in ("HANDOFF_BLOCKED", "STALE_BUILDER_ORPHAN")
        ]
        assert not blocked_events, (
            "no-op must not emit HANDOFF_BLOCKED or STALE_BUILDER_ORPHAN"
        )

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
        blocked_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type")
            in ("HANDOFF_BLOCKED", "STALE_BUILDER_ORPHAN")
        ]
        assert not blocked_events, (
            "no-op must not emit HANDOFF_BLOCKED or STALE_BUILDER_ORPHAN"
        )

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

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_evidence_failure_emits_terminal_events_and_releases_lock(
        self, mock_bus, mock_load
    ):
        """Failed closeout must emit HANDOFF_BLOCKED + BUILDER_EXIT and release lock."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-236a\n- **deliverable_type:** code",
            "**Estado:** IN_PROGRESS",
            "WT-2026-236a",
        )
        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.latest_event.return_value = None

        with (
            patch(
                "agent_controller._ensure_active_builder_round",
                return_value=(True, 1, None),
            ),
            patch(
                "agent_controller._check_circuit_breaker", return_value={"open": False}
            ),
            patch(
                "agent_controller._check_implementation_evidence",
                return_value=["No implementation evidence"],
            ),
            patch("agent_controller._emit_builder_exit") as mock_exit,
            patch("agent_controller._release_builder_lock") as mock_release,
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 1
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert handoff_events
        mock_exit.assert_called_once()
        mock_release.assert_called_once_with("WT-2026-236a", expected_round=1)

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_pre_handoff_failure_releases_lock_once(self, mock_bus, mock_load):
        """Pre-handoff guard failure should emit one HANDOFF_BLOCKED and release lock."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-236a\n- **deliverable_type:** code",
            "**Estado:** IN_PROGRESS",
            "WT-2026-236a",
        )
        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.latest_event.return_value = None

        with (
            patch(
                "agent_controller._ensure_active_builder_round",
                return_value=(True, 1, None),
            ),
            patch(
                "agent_controller._check_circuit_breaker", return_value={"open": False}
            ),
            patch("agent_controller._check_implementation_evidence", return_value=[]),
            patch(
                "agent_controller._run_pre_handoff_guard",
                return_value={
                    "valid": False,
                    "dirty_tree": True,
                    "dirty_files": ["x.py"],
                },
            ),
            patch("agent_controller._emit_builder_exit") as mock_exit,
            patch("agent_controller._release_builder_lock") as mock_release,
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 1
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert len(handoff_events) == 1
        mock_exit.assert_called_once()
        mock_release.assert_called_once_with("WT-2026-236a", expected_round=1)

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

    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_sync_mark_ready_reemits_after_changes_decision(self, mock_bus):
        """A CHANGES decision resets derived state even if latest STATE_CHANGED is ready."""
        ready_event = MagicMock()
        ready_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        changes_event = MagicMock()
        changes_event.to_dict.return_value = {
            "event_type": "REVIEW_DECISION",
            "payload": {"decision": "CHANGES"},
        }
        latest_state = MagicMock()
        latest_state.payload = {"to_state": "READY_FOR_REVIEW"}

        mock_bus.read_events.return_value = [ready_event, changes_event]
        mock_bus.latest_event.return_value = latest_state

        _sync_mark_ready_targets("WT-2026-236a", "", current_round=2)

        state_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "STATE_CHANGED"
        ]
        assert len(state_events) == 2
        assert all(
            call.kwargs["payload"]["to_state"] == "READY_FOR_REVIEW"
            for call in state_events
        )

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_doc_ticket_skips_motor_checkpoint(self, mock_bus, mock_load):
        """Documentation ticket must reach --mark-ready without a motor checkpoint tag."""
        plan_content = (
            "**Estado:** APPROVED\n"
            "**ID:** WT-2026-236a\n"
            "- **deliverable_type:** documentation\n"
        )
        mock_load.return_value = (
            plan_content,
            "**Estado:** IN_PROGRESS",
            "WT-2026-236a",
        )
        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.latest_event.return_value = None

        with (
            patch(
                "agent_controller._ensure_active_builder_round",
                return_value=(True, 1, None),
            ),
            patch(
                "agent_controller._check_circuit_breaker", return_value={"open": False}
            ),
            patch("agent_controller._check_implementation_evidence", return_value=[]),
            patch(
                "agent_controller._run_pre_handoff_guard",
                return_value={"valid": True},
            ),
            patch("agent_controller._MOTOR_ROOT", Path("/motor")),
            patch("agent_controller.PROJECT_ROOT", Path("/workspace")),
            patch("agent_controller._emit_builder_exit"),
            patch("agent_controller._sync_mark_ready_targets"),
            patch("agent_controller._reset_circuit_breaker"),
            patch("agent_controller._release_builder_lock"),
            patch("agent_controller._resolve_motor_checkpoint_files") as mock_cp,
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 0
        # Motor checkpoint should never be consulted for doc tickets
        mock_cp.assert_not_called()

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_motor_checkpoint_failure_emits_handoff_blocked(self, mock_bus, mock_load):
        """Missing motor checkpoint must emit HANDOFF_BLOCKED and release lock."""
        plan_content = (
            "**Estado:** APPROVED\n**ID:** WT-2026-236a\n- **deliverable_type:** code\n"
        )
        mock_load.return_value = (
            plan_content,
            "**Estado:** IN_PROGRESS",
            "WT-2026-236a",
        )
        mock_event = MagicMock()
        mock_event.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_event]
        mock_bus.latest_event.return_value = None

        with (
            patch(
                "agent_controller._ensure_active_builder_round",
                return_value=(True, 1, None),
            ),
            patch(
                "agent_controller._check_circuit_breaker", return_value={"open": False}
            ),
            patch("agent_controller._check_implementation_evidence", return_value=[]),
            patch(
                "agent_controller._run_pre_handoff_guard",
                return_value={"valid": True},
            ),
            patch("agent_controller._MOTOR_ROOT", Path("/motor")),
            patch("agent_controller.PROJECT_ROOT", Path("/workspace")),
            patch(
                "agent_controller._resolve_motor_checkpoint_files",
                return_value=(
                    False,
                    [],
                    "Tag checkpoint/review-WT-2026-236a not found",
                ),
            ),
            patch("agent_controller._emit_builder_exit") as mock_exit,
            patch("agent_controller._release_builder_lock") as mock_release,
        ):
            result = _handle_mark_ready(
                scope_override=None, json_output=False, force_mode=False
            )

        assert result == 1
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert handoff_events, "missing motor checkpoint must emit HANDOFF_BLOCKED"
        mock_exit.assert_called_once()
        mock_release.assert_called_once_with("WT-2026-236a", expected_round=1)

    @pytest.mark.parametrize(
        ("event_dict", "active_round"),
        [
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "READY_FOR_REVIEW"},
                },
                4,
            ),
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "READY_TO_CLOSE"},
                },
                5,
            ),
            (
                {
                    "event_type": "REVIEW_DECISION",
                    "payload": {"decision": "inspect"},
                },
                3,
            ),
            (
                {
                    "event_type": "STATE_CHANGED",
                    "payload": {"to_state": "COMPLETED"},
                },
                2,
            ),
        ],
    )
    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    @patch("agent_controller._ensure_active_builder_round")
    def test_stale_builder_orphan_for_post_success_states(
        self, mock_round, mock_bus, mock_load, event_dict, active_round
    ):
        """Stale shell on post-success states must emit STALE_BUILDER_ORPHAN and exit 0."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-242b",
            "**Estado:** IN_PROGRESS",
            "WT-2026-242b",
        )
        mock_round.return_value = (
            False,
            active_round - 1,
            f"stale Builder round {active_round - 1}; active round is {active_round}",
        )

        mock_event = MagicMock()
        mock_event.to_dict.return_value = event_dict
        mock_bus.read_events.return_value = [mock_event]

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 0
        orphan_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert orphan_events, "post-success stale must emit STALE_BUILDER_ORPHAN"
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert not handoff_events, "must NOT emit HANDOFF_BLOCKED for orphan"

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    @patch("agent_controller._ensure_active_builder_round")
    def test_stale_builder_round_stays_blocking_when_bus_state_unknown(
        self, mock_round, mock_bus, mock_load
    ):
        """Unknown bus state must keep the original blocking path."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-242b",
            "**Estado:** IN_PROGRESS",
            "WT-2026-242b",
        )
        mock_round.return_value = (False, 1, "stale Builder round 1; active round is 2")
        mock_bus.read_events.return_value = []

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 1
        handoff_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "HANDOFF_BLOCKED"
        ]
        assert handoff_events, "unknown bus state must keep HANDOFF_BLOCKED"
        orphan_events = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert not orphan_events

    def test_is_bus_state_post_success_rejects_none_and_unknown(self):
        """Only explicit post-success states should bypass stale shell blocking."""
        assert _is_bus_state_post_success(None) is False
        assert _is_bus_state_post_success("UNKNOWN") is False

    @patch("agent_controller._load_mark_ready_context")
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    @patch("agent_controller._ensure_active_builder_round")
    def test_stale_builder_orphan_emits_with_correct_payload(
        self, mock_round, mock_bus, mock_load
    ):
        """STALE_BUILDER_ORPHAN must carry ticket_id, round, and bus_state in payload."""
        mock_load.return_value = (
            "**Estado:** APPROVED\n**ID:** WT-2026-242b",
            "**Estado:** IN_PROGRESS",
            "WT-2026-242b",
        )
        mock_round.return_value = (False, 1, "stale Builder round 1; active round is 3")

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
        orphan_calls = [
            call
            for call in mock_bus.emit.call_args_list
            if call.kwargs.get("event_type") == "STALE_BUILDER_ORPHAN"
        ]
        assert len(orphan_calls) == 1
        payload = orphan_calls[0].kwargs.get("payload", {})
        assert payload.get("reason") == "stale_builder_round"
        assert payload.get("process_round") == 1
        assert payload.get("bus_state") == "READY_FOR_REVIEW"
