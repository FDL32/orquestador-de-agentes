#!/usr/bin/env python3
"""Eval test for bus/supervisor.py::requeue_ticket.

Verifies that requeue ticket logic works correctly without touching
the production bus or subprocesses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.state_machine import StateMachine, TicketState
from bus.supervisor import SequentialTicketSupervisor, SupervisorState


pytestmark = pytest.mark.eval


@pytest.fixture
def mock_event_bus(tmp_path: Path) -> EventBus:
    """Create a temporary EventBus."""
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return EventBus(runtime_dir=events_dir)


@pytest.fixture
def mock_supervisor(tmp_path: Path) -> SequentialTicketSupervisor:
    """Create a temporary SequentialTicketSupervisor."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    collaboration_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir = tmp_path / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


class TestSupervisorState:
    """Tests for SupervisorState dataclass."""

    def test_create_supervisor_state(self):
        """Create SupervisorState with default data."""
        state = SupervisorState()

        assert state.active_ticket is None
        assert state.completed_tickets == []
        assert state.last_action == ""
        assert state.last_processed_sequence == 0

    def test_create_supervisor_state_with_ticket(self):
        """Create SupervisorState with active ticket."""
        state = SupervisorState(
            active_ticket="WP-2026-999", loop_current_round=5, loop_max_rounds=10
        )

        assert state.active_ticket == "WP-2026-999"
        assert state.loop_current_round == 5
        assert state.loop_max_rounds == 10


class TestSequentialTicketSupervisor:
    """Tests for SequentialTicketSupervisor."""

    def test_supervisor_init_creates_dirs(
        self, mock_supervisor: SequentialTicketSupervisor
    ):
        """Supervisor creates runtime directories."""
        assert mock_supervisor.runtime_dir.exists()
        assert mock_supervisor.collaboration_dir.exists()

    def test_supervisor_state_save_load(
        self, mock_supervisor: SequentialTicketSupervisor, tmp_path: Path
    ):
        """Save and load supervisor state."""
        state = SupervisorState(
            active_ticket="WP-2026-999",
            completed_tickets=["WP-2026-998"],
            last_action="test_action",
        )

        mock_supervisor.save_state(state)
        assert mock_supervisor.state_path.exists()


class TestRequeueTicket:
    """Tests for requeue ticket logic."""

    def test_requeue_ticket_advances_and_relaunches(
        self, mock_supervisor: SequentialTicketSupervisor
    ):
        """requeue_ticket increments round and relaunches when active."""
        mock_supervisor.save_state(
            SupervisorState(active_ticket="WP-2026-999", loop_current_round=1)
        )

        calls: list[str] = []

        def fake_current_state(ticket_id: str):
            assert ticket_id == "WP-2026-999"
            return TicketState.IN_PROGRESS

        def fake_relaunch(ticket_id: str, *a, **kw) -> bool:
            calls.append(ticket_id)
            return True

        mock_supervisor._current_state = fake_current_state  # type: ignore[method-assign]
        mock_supervisor._relaunch_builder = fake_relaunch  # type: ignore[method-assign]

        result = mock_supervisor.requeue_ticket("WP-2026-999", trigger_seq=42)

        assert result is True
        assert calls == ["WP-2026-999"]
        assert mock_supervisor.load_state().loop_current_round == 2

    def test_requeue_ticket_blocks_terminal_state(
        self, mock_supervisor: SequentialTicketSupervisor
    ):
        """requeue_ticket does not relaunch terminal tickets."""
        mock_supervisor.save_state(
            SupervisorState(active_ticket="WP-2026-999", loop_current_round=1)
        )

        calls: list[str] = []

        def fake_current_state(ticket_id: str):
            assert ticket_id == "WP-2026-999"
            return TicketState.READY_TO_CLOSE

        def fake_relaunch(ticket_id: str) -> bool:
            calls.append(ticket_id)
            return True

        mock_supervisor._current_state = fake_current_state  # type: ignore[method-assign]
        mock_supervisor._relaunch_builder = fake_relaunch  # type: ignore[method-assign]

        result = mock_supervisor.requeue_ticket("WP-2026-999", trigger_seq=42)

        assert result is False
        assert calls == []
        assert mock_supervisor.load_state().loop_current_round == 1

    def test_non_terminal_states_preserve_active_ticket(self):
        """Non-terminal states preserve active_ticket."""
        from bus.supervisor import NON_TERMINAL_STATES

        assert TicketState.READY_FOR_REVIEW in NON_TERMINAL_STATES
        assert TicketState.IN_PROGRESS in NON_TERMINAL_STATES
        assert TicketState.HUMAN_GATE in NON_TERMINAL_STATES
        assert TicketState.COMPLETED not in NON_TERMINAL_STATES

    def test_relaunch_blocked_states(self):
        """States that block Builder relaunch."""
        from bus.supervisor import RELAUNCH_BLOCKED_STATES

        assert TicketState.HUMAN_GATE in RELAUNCH_BLOCKED_STATES
        assert TicketState.READY_TO_CLOSE in RELAUNCH_BLOCKED_STATES
        assert TicketState.COMPLETED in RELAUNCH_BLOCKED_STATES
        assert TicketState.IN_PROGRESS not in RELAUNCH_BLOCKED_STATES
        assert TicketState.READY_FOR_REVIEW not in RELAUNCH_BLOCKED_STATES

    def test_requeue_logic_with_state_machine(
        self, mock_event_bus: EventBus, tmp_path: Path
    ):
        """Requeue logic with state machine."""
        events = [
            {"event_type": "STATE_CHANGED", "payload": {"to_state": "IN_PROGRESS"}},
            {
                "event_type": "STATE_CHANGED",
                "payload": {"to_state": "READY_FOR_REVIEW"},
            },
        ]

        state = StateMachine.derive_state_from_events(events)
        assert state == TicketState.READY_FOR_REVIEW


class TestRequeueEdgeCases:
    """Tests for requeue edge cases."""

    def test_requeue_with_invalid_state_transition(
        self, mock_event_bus: EventBus, tmp_path: Path
    ):
        """Requeue with invalid state transition."""
        from bus.state_machine import StateMachine, TicketState

        assert hasattr(StateMachine, "derive_state_from_events")
        assert TicketState.COMPLETED is not None

    def test_concurrent_state_error_on_revision_mismatch(
        self, mock_event_bus: EventBus, tmp_path: Path
    ):
        """ConcurrentStateError when revision mismatch happens."""
        from bus.exceptions import ConcurrentStateError

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        collaboration_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir = tmp_path / ".agent" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        supervisor = SequentialTicketSupervisor(
            project_root=tmp_path,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            auto_sync=False,
        )

        state = SupervisorState(active_ticket="WP-2026-999")
        supervisor.save_state(state)
        _content, revision = supervisor._read_artifact_with_revision(
            supervisor.state_path
        )
        supervisor.state_path.write_text(
            '{"active_ticket": "WP-2026-998"}', encoding="utf-8"
        )

        with pytest.raises(ConcurrentStateError):
            supervisor.write_artifact_atomic(
                supervisor.state_path,
                '{"active_ticket": "WP-2026-997"}',
                expected_revision=revision,
                ticket_id="WP-2026-999",
            )
