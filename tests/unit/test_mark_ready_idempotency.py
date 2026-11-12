"""Tests for WP-2026-143: Bus-backed mark-ready idempotency."""

import hashlib
import json
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


@pytest.fixture(autouse=True)
def _isolate_mark_ready_projection_side_effects():
    """Prevent mark-ready unit tests from mutating canonical .agent projections."""
    with (
        patch(
            "bus.supervisor.SequentialTicketSupervisor._materialize_ticket_projection"
        ),
        patch("scripts.state_projection_sync.sync_state_projection"),
    ):
        yield


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

        with (
            patch(
                "bus.supervisor.SequentialTicketSupervisor._materialize_ticket_projection"
            ),
            patch("scripts.state_projection_sync.sync_state_projection"),
        ):
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


def test_mark_ready_blocks_ghost_ticket_before_any_write(tmp_path, monkeypatch, capsys):
    """Before: a scheduling surface exists without a row for the active ticket.

    During: invoke mark-ready with all downstream writes observable.

    After: the ghost gate blocks before the builder-round guard or event bus.
    """
    ticket_id = "WOT-2026-999"
    collaboration = tmp_path / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    (collaboration / "backlog.md").write_text(
        "| Media | OTHER | Ticket | x |", encoding="utf-8"
    )
    files = [
        collaboration / "STATE.md",
        collaboration / "TURN.md",
        collaboration / "execution_log.md",
    ]
    for path in files:
        path.write_text(f"ACTIVE_TICKET: {ticket_id}\n", encoding="utf-8")
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in files}
    mock_bus = MagicMock()
    mock_ensure = MagicMock()
    monkeypatch.setattr("agent_controller.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "agent_controller._load_mark_ready_context",
        lambda: (f"**ID:** {ticket_id}", "**Estado:** IN_PROGRESS", ticket_id),
    )
    monkeypatch.setattr("agent_controller.event_bus", mock_bus)
    monkeypatch.setattr("agent_controller.BUS_AVAILABLE", True)
    monkeypatch.setattr("agent_controller._ensure_active_builder_round", mock_ensure)

    result = _handle_mark_ready(None, False, False)

    assert result == 1
    output = capsys.readouterr().out.lower()
    assert ticket_id.lower() in output and "ghost" in output
    mock_ensure.assert_not_called()
    mock_bus.emit.assert_not_called()
    assert before == {
        path: hashlib.sha256(path.read_bytes()).digest() for path in files
    }

    (collaboration / "backlog.md").write_text(
        f"| Media | {ticket_id} | Ticket | x |", encoding="utf-8"
    )
    with (
        patch(
            "agent_controller._ensure_active_builder_round",
            return_value=(True, 1, None),
        ) as mock_ensure,
        patch(
            "agent_controller._check_circuit_breaker",
            return_value={
                "open": True,
                "reason": "test",
                "failures": 0,
                "no_progress_count": 0,
            },
        ),
    ):
        assert _handle_mark_ready(None, False, False) == 1
    mock_ensure.assert_called_once_with(ticket_id)


def test_mark_ready_dry_run_mutates_nothing_valid_ticket(tmp_path, monkeypatch, capsys):
    """Before: a valid ticket has all projection surfaces and a backlog row.

    During: run mark-ready in dry-run mode with a real event bus.

    After: preview output is returned and all four files remain byte-identical.
    """
    from bus.event_bus import EventBus

    ticket_id = "WOT-2026-998"
    before = _write_mark_ready_projection_fixture(tmp_path, ticket_id)
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    monkeypatch.setattr("agent_controller.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "agent_controller._load_mark_ready_context",
        lambda: (f"**ID:** {ticket_id}", "**Estado:** IN_PROGRESS", ticket_id),
    )
    monkeypatch.setattr("agent_controller.event_bus", event_bus)
    monkeypatch.setattr("agent_controller.BUS_AVAILABLE", True)
    with (
        patch(
            "agent_controller._ensure_active_builder_round",
            return_value=(True, 1, None),
        ),
        patch("agent_controller._check_circuit_breaker", return_value={"open": False}),
        patch("agent_controller._check_implementation_evidence", return_value=[]),
        patch("agent_controller._run_pre_handoff_guard", return_value={"valid": True}),
        patch("agent_controller._MOTOR_ROOT", Path("/motor")),
        patch("agent_controller._resolve_motor_checkpoint_files"),
    ):
        result = _handle_mark_ready(None, True, False, dry_run=True)

    assert result == 0
    assert "dry_run_preview" in capsys.readouterr().out
    assert before == {
        path: hashlib.sha256(path.read_bytes()).digest() for path in before
    }
    assert event_bus.read_events() == []

    import agent_controller
    from runtime import project_root as project_root_mod

    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    project_root_mod.clear_cache()
    captured = {}

    def _record_mark_ready(*args, **kwargs):
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(agent_controller, "_handle_mark_ready", _record_mark_ready)
    monkeypatch.setattr(
        sys, "argv", ["agent_controller.py", "--mark-ready", "--dry-run"]
    )
    try:
        agent_controller.main()
    finally:
        project_root_mod.clear_cache()
    assert captured["kwargs"].get("dry_run") is True


def test_mark_ready_dry_run_mutates_nothing_ghost_and_no_surfaces(
    tmp_path, monkeypatch, capsys
):
    """Before: exercise ghost and fail-open roots in dry-run mode.

    During: invoke mark-ready against each isolated root.

    After: both cases preview without mutating projection files.
    """
    ticket_id = "WOT-2026-997"
    ghost_root = tmp_path / "ghost"
    collab = ghost_root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Media | OTHER | Ticket | x |", encoding="utf-8"
    )
    ghost_state = collab / "STATE.md"
    ghost_state.write_text("STATUS: IN_PROGRESS\n", encoding="utf-8")
    ghost_hash = hashlib.sha256(ghost_state.read_bytes()).digest()
    monkeypatch.setattr("agent_controller.PROJECT_ROOT", ghost_root)
    monkeypatch.setattr(
        "agent_controller._load_mark_ready_context",
        lambda: (f"**ID:** {ticket_id}", "**Estado:** IN_PROGRESS", ticket_id),
    )
    monkeypatch.setattr("agent_controller.event_bus", MagicMock())
    monkeypatch.setattr("agent_controller.BUS_AVAILABLE", True)
    assert _handle_mark_ready(None, True, False, dry_run=True) == 1
    ghost_preview = json.loads(capsys.readouterr().out)
    assert ghost_preview["status"] == "dry_run_preview"
    assert ghost_preview["ghost_blocked"] is True
    assert ghost_preview["plan_id"] == ticket_id
    assert ghost_hash == hashlib.sha256(ghost_state.read_bytes()).digest()

    plain_root = tmp_path / "plain"
    plain_collab = plain_root / ".agent" / "collaboration"
    plain_collab.mkdir(parents=True)
    plain_state = plain_collab / "STATE.md"
    plain_state.write_text("STATUS: IN_PROGRESS\n", encoding="utf-8")
    plain_hash = hashlib.sha256(plain_state.read_bytes()).digest()
    monkeypatch.setattr("agent_controller.PROJECT_ROOT", plain_root)
    with (
        patch(
            "agent_controller._ensure_active_builder_round",
            return_value=(True, 1, None),
        ),
        patch("agent_controller._check_circuit_breaker", return_value={"open": False}),
        patch("agent_controller._check_implementation_evidence", return_value=[]),
        patch("agent_controller._run_pre_handoff_guard", return_value={"valid": True}),
    ):
        assert _handle_mark_ready(None, True, False, dry_run=True) == 0
    plain_output = capsys.readouterr().out.lower()
    assert "dry_run_preview" in plain_output and "gate_skipped" in plain_output
    assert plain_hash == hashlib.sha256(plain_state.read_bytes()).digest()


def _write_mark_ready_projection_fixture(
    root: Path, ticket_id: str
) -> dict[Path, bytes]:
    """Before: provide mark-ready projection files under an isolated root.

    During: create scheduling surfaces and a backlog row.

    After: return hashes for the files used by dry-run checks.
    """
    collaboration = root / ".agent" / "collaboration"
    runtime_events = root / ".agent" / "runtime" / "events"
    collaboration.mkdir(parents=True)
    runtime_events.mkdir(parents=True)
    (collaboration / "backlog.md").write_text(
        f"| Media | {ticket_id} | Ticket | scope | pending | - | test | - |\n",
        encoding="utf-8",
    )
    files = {
        collaboration
        / "STATE.md": f"ACTIVE_TICKET: {ticket_id}\nSTATUS: IN_PROGRESS\n",
        collaboration / "TURN.md": f"ticket={ticket_id}\n",
        collaboration / "execution_log.md": f"ticket={ticket_id}\n",
        runtime_events / "events.jsonl": "",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return {path: hashlib.sha256(path.read_bytes()).digest() for path in files}
