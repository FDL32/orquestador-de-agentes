"""Tests for WP-2026-152: request-changes requeue handoff.

Tests the _handle_request_changes() function to ensure:
- Requeue is accepted only when REVIEW_DECISION=changes is the direct antecedent.
- Generic IN_PROGRESS without that antecedent fails closed.
- UNKNOWN state falls back to execution_log path.
- The handler derives pending_requeue from events[-1], not a second latest_event() read.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from bus.event_bus import EventRecord  # noqa: E402


def _rec(
    seq: int,
    event_type: str = "REVIEW_DECISION",
    decision: str | None = None,
    to_state: str | None = None,
) -> EventRecord:
    """Build an EventRecord for testing."""
    payload = {}
    if decision is not None:
        payload["decision"] = decision
    if to_state is not None:
        payload["to_state"] = to_state
    return EventRecord(
        event_id=f"e{seq}",
        event_type=event_type,
        ticket_id="WP-2026-152",
        actor="MANAGER",
        timestamp="2026-05-27T00:00:00+00:00",
        payload=payload,
        sequence_number=seq,
    )


class TestHandleRequestChangesRequeue:
    """Test _handle_request_changes() requeue logic."""

    @pytest.fixture
    def mock_files(self, tmp_path: Path):
        """Create minimal mock files for testing."""
        work_plan = tmp_path / ".agent" / "collaboration" / "work_plan.md"
        work_plan.parent.mkdir(parents=True, exist_ok=True)
        work_plan.write_text(
            "# Work Plan\n\n## Metadata\n- **ID:** WP-2026-152\n- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        exec_log = tmp_path / ".agent" / "collaboration" / "execution_log.md"
        exec_log.write_text(
            "# Execution Log\n\n**Estado:** READY_FOR_REVIEW\n", encoding="utf-8"
        )
        state_file = tmp_path / ".agent" / "collaboration" / "STATE.md"
        state_file.write_text(
            "# State\n\n- **Estado actual:** READY_FOR_REVIEW\n", encoding="utf-8"
        )
        turn_file = tmp_path / ".agent" / "collaboration" / "TURN.md"
        turn_file.write_text("# TURN\n", encoding="utf-8")
        agents_config = tmp_path / ".agent" / "config" / "agents.json"
        agents_config.parent.mkdir(parents=True, exist_ok=True)
        agents_config.write_text(
            json.dumps(
                {
                    "active_profile": "engine-dev",
                    "manager_review": {"max_attempts": 5},
                }
            ),
            encoding="utf-8",
        )
        return tmp_path

    @pytest.fixture
    def mock_event_bus(self):
        """Create a mock event bus."""
        bus = MagicMock()
        bus.read_events = MagicMock(return_value=[])
        bus.latest_event = MagicMock(return_value=None)
        bus.emit = MagicMock()
        return bus

    def test_allowed_requeue_with_changes_antecedent(
        self, mock_files: Path, mock_event_bus: MagicMock
    ):
        """Requeue is accepted when events[-1] is REVIEW_DECISION=changes."""
        import agent_controller

        # Setup: events with changes as the latest
        events = [
            _rec(1, "STATE_CHANGED", to_state="READY_FOR_REVIEW"),
            _rec(2, "REVIEW_DECISION", decision="changes"),
        ]
        mock_event_bus.read_events = MagicMock(return_value=events)
        mock_event_bus.latest_event = MagicMock(return_value=events[-1])

        with (
            patch.object(agent_controller, "BUS_AVAILABLE", True),
            patch.object(agent_controller, "event_bus", mock_event_bus),
            patch.object(agent_controller, "PROJECT_ROOT", mock_files),
            patch.object(agent_controller, "AGENT_DIR", mock_files / ".agent"),
            patch.object(
                agent_controller, "COLLAB_DIR", mock_files / ".agent" / "collaboration"
            ),
            patch.object(
                agent_controller, "CONTEXT_DIR", mock_files / ".agent" / "context"
            ),
            patch.object(
                agent_controller,
                "WORK_PLAN",
                mock_files / ".agent" / "collaboration" / "work_plan.md",
            ),
            patch.object(
                agent_controller,
                "EXEC_LOG",
                mock_files / ".agent" / "collaboration" / "execution_log.md",
            ),
            patch.object(
                agent_controller,
                "STATE_FILE",
                mock_files / ".agent" / "collaboration" / "STATE.md",
            ),
            patch.object(
                agent_controller,
                "TURN_FILE",
                mock_files / ".agent" / "collaboration" / "TURN.md",
            ),
            patch.object(
                agent_controller,
                "AGENTS_CONFIG_PATH",
                mock_files / ".agent" / "config" / "agents.json",
            ),
            patch.object(
                agent_controller, "_materialize_state_transition"
            ) as mock_materialize,
        ):
            result = agent_controller._handle_request_changes(
                "WP-2026-152", json_output=True, force_mode=False
            )
            # Should succeed (return 0) because changes antecedent is present
            assert result == 0
            # Should have called _materialize_state_transition for IN_PROGRESS
            mock_materialize.assert_called()
            call_args = mock_materialize.call_args
            assert call_args.kwargs["to_state"] == "IN_PROGRESS"

    def test_generic_in_progress_without_antecedent_fails_closed(
        self, mock_files: Path, mock_event_bus: MagicMock
    ):
        """Generic IN_PROGRESS without changes antecedent fails closed."""
        import agent_controller

        # Setup: events with IN_PROGRESS state but no changes antecedent
        events = [
            _rec(1, "STATE_CHANGED", to_state="IN_PROGRESS"),
        ]
        mock_event_bus.read_events = MagicMock(return_value=events)
        mock_event_bus.latest_event = MagicMock(return_value=events[-1])

        with (
            patch.object(agent_controller, "BUS_AVAILABLE", True),
            patch.object(agent_controller, "event_bus", mock_event_bus),
            patch.object(agent_controller, "PROJECT_ROOT", mock_files),
            patch.object(agent_controller, "AGENT_DIR", mock_files / ".agent"),
            patch.object(
                agent_controller, "COLLAB_DIR", mock_files / ".agent" / "collaboration"
            ),
            patch.object(
                agent_controller, "CONTEXT_DIR", mock_files / ".agent" / "context"
            ),
            patch.object(
                agent_controller,
                "WORK_PLAN",
                mock_files / ".agent" / "collaboration" / "work_plan.md",
            ),
            patch.object(
                agent_controller,
                "EXEC_LOG",
                mock_files / ".agent" / "collaboration" / "execution_log.md",
            ),
            patch.object(
                agent_controller,
                "STATE_FILE",
                mock_files / ".agent" / "collaboration" / "STATE.md",
            ),
            patch.object(
                agent_controller,
                "TURN_FILE",
                mock_files / ".agent" / "collaboration" / "TURN.md",
            ),
            patch.object(
                agent_controller,
                "AGENTS_CONFIG_PATH",
                mock_files / ".agent" / "config" / "agents.json",
            ),
        ):
            result = agent_controller._handle_request_changes(
                "WP-2026-152", json_output=True, force_mode=False
            )
            # Should fail (return 1) because IN_PROGRESS lacks changes antecedent
            assert result == 1

    def test_unknown_falls_back_to_execution_log(
        self, mock_files: Path, mock_event_bus: MagicMock
    ):
        """UNKNOWN bus state falls back to execution_log.md check."""
        import agent_controller

        # Setup: empty events = UNKNOWN state
        mock_event_bus.read_events = MagicMock(return_value=[])
        mock_event_bus.latest_event = MagicMock(return_value=None)

        # Execution log says READY_FOR_REVIEW - should proceed
        exec_log = mock_files / ".agent" / "collaboration" / "execution_log.md"
        exec_log.write_text(
            "# Execution Log\n\n**Estado:** READY_FOR_REVIEW\n", encoding="utf-8"
        )

        with (
            patch.object(agent_controller, "BUS_AVAILABLE", True),
            patch.object(agent_controller, "event_bus", mock_event_bus),
            patch.object(agent_controller, "PROJECT_ROOT", mock_files),
            patch.object(agent_controller, "AGENT_DIR", mock_files / ".agent"),
            patch.object(
                agent_controller, "COLLAB_DIR", mock_files / ".agent" / "collaboration"
            ),
            patch.object(
                agent_controller, "CONTEXT_DIR", mock_files / ".agent" / "context"
            ),
            patch.object(
                agent_controller,
                "WORK_PLAN",
                mock_files / ".agent" / "collaboration" / "work_plan.md",
            ),
            patch.object(
                agent_controller,
                "EXEC_LOG",
                mock_files / ".agent" / "collaboration" / "execution_log.md",
            ),
            patch.object(
                agent_controller,
                "STATE_FILE",
                mock_files / ".agent" / "collaboration" / "STATE.md",
            ),
            patch.object(
                agent_controller,
                "TURN_FILE",
                mock_files / ".agent" / "collaboration" / "TURN.md",
            ),
            patch.object(
                agent_controller,
                "AGENTS_CONFIG_PATH",
                mock_files / ".agent" / "config" / "agents.json",
            ),
            patch.object(
                agent_controller, "_materialize_state_transition"
            ) as mock_materialize,
        ):
            result = agent_controller._handle_request_changes(
                "WP-2026-152", json_output=True, force_mode=False
            )
            # Should succeed because execution_log fallback is READY_FOR_REVIEW
            assert result == 0
            mock_materialize.assert_called()

    def test_unknown_with_non_ready_execution_log_fails(
        self, mock_files: Path, mock_event_bus: MagicMock
    ):
        """UNKNOWN bus state with non-READY execution_log fails."""
        import agent_controller

        # Setup: empty events = UNKNOWN state
        mock_event_bus.read_events = MagicMock(return_value=[])
        mock_event_bus.latest_event = MagicMock(return_value=None)

        # Execution log says IN_PROGRESS - should fail
        exec_log = mock_files / ".agent" / "collaboration" / "execution_log.md"
        exec_log.write_text(
            "# Execution Log\n\n**Estado:** IN_PROGRESS\n", encoding="utf-8"
        )

        with (
            patch.object(agent_controller, "BUS_AVAILABLE", True),
            patch.object(agent_controller, "event_bus", mock_event_bus),
            patch.object(agent_controller, "PROJECT_ROOT", mock_files),
            patch.object(agent_controller, "AGENT_DIR", mock_files / ".agent"),
            patch.object(
                agent_controller, "COLLAB_DIR", mock_files / ".agent" / "collaboration"
            ),
            patch.object(
                agent_controller, "CONTEXT_DIR", mock_files / ".agent" / "context"
            ),
            patch.object(
                agent_controller,
                "WORK_PLAN",
                mock_files / ".agent" / "collaboration" / "work_plan.md",
            ),
            patch.object(
                agent_controller,
                "EXEC_LOG",
                mock_files / ".agent" / "collaboration" / "execution_log.md",
            ),
            patch.object(
                agent_controller,
                "STATE_FILE",
                mock_files / ".agent" / "collaboration" / "STATE.md",
            ),
            patch.object(
                agent_controller,
                "TURN_FILE",
                mock_files / ".agent" / "collaboration" / "TURN.md",
            ),
            patch.object(
                agent_controller,
                "AGENTS_CONFIG_PATH",
                mock_files / ".agent" / "config" / "agents.json",
            ),
        ):
            result = agent_controller._handle_request_changes(
                "WP-2026-152", json_output=True, force_mode=False
            )
            # Should fail because execution_log fallback is not READY_FOR_REVIEW
            assert result == 1

    def test_pending_requeue_derived_from_events_not_latest_event(
        self, mock_files: Path, mock_event_bus: MagicMock
    ):
        """pending_requeue is derived from events[-1], not a second latest_event() read."""
        import agent_controller

        # Setup: events with changes as the latest
        events = [
            _rec(1, "STATE_CHANGED", to_state="READY_FOR_REVIEW"),
            _rec(2, "REVIEW_DECISION", decision="changes"),
        ]
        mock_event_bus.read_events = MagicMock(return_value=events)
        # latest_event should NOT be called for pending_requeue derivation
        # (it may be called as fallback when events is empty, but not here)
        mock_event_bus.latest_event = MagicMock(return_value=None)

        with (
            patch.object(agent_controller, "BUS_AVAILABLE", True),
            patch.object(agent_controller, "event_bus", mock_event_bus),
            patch.object(agent_controller, "PROJECT_ROOT", mock_files),
            patch.object(agent_controller, "AGENT_DIR", mock_files / ".agent"),
            patch.object(
                agent_controller, "COLLAB_DIR", mock_files / ".agent" / "collaboration"
            ),
            patch.object(
                agent_controller, "CONTEXT_DIR", mock_files / ".agent" / "context"
            ),
            patch.object(
                agent_controller,
                "WORK_PLAN",
                mock_files / ".agent" / "collaboration" / "work_plan.md",
            ),
            patch.object(
                agent_controller,
                "EXEC_LOG",
                mock_files / ".agent" / "collaboration" / "execution_log.md",
            ),
            patch.object(
                agent_controller,
                "STATE_FILE",
                mock_files / ".agent" / "collaboration" / "STATE.md",
            ),
            patch.object(
                agent_controller,
                "TURN_FILE",
                mock_files / ".agent" / "collaboration" / "TURN.md",
            ),
            patch.object(
                agent_controller,
                "AGENTS_CONFIG_PATH",
                mock_files / ".agent" / "config" / "agents.json",
            ),
            patch.object(
                agent_controller, "_materialize_state_transition"
            ) as mock_materialize,
        ):
            result = agent_controller._handle_request_changes(
                "WP-2026-152", json_output=True, force_mode=False
            )
            # Should succeed
            assert result == 0
            # Verify pending_requeue was derived from events[-1]
            # latest_event should not be called for this (only as fallback when events empty)
            mock_materialize.assert_called()
