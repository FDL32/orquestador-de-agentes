"""Tests for bus/state_machine.py - WP-2026-112 HUMAN_GATE enforcement."""
from __future__ import annotations

from bus.state_machine import StateMachine, TicketState


def test_derive_state_from_empty_events():
    """Empty events list returns UNKNOWN."""
    state = StateMachine.derive_state_from_events([])
    assert state == TicketState.UNKNOWN


def test_derive_state_from_last_state_changed():
    """Derive state from the last STATE_CHANGED event."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "IN_PROGRESS"}},
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.READY_FOR_REVIEW


def test_derive_state_from_close_confirmed():
    """CLOSE_CONFIRMED takes precedence and returns COMPLETED."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "CLOSE_CONFIRMED", "payload": {}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.COMPLETED


def test_derive_state_from_review_decision_approve():
    """REVIEW_DECISION with approve returns READY_TO_CLOSE."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "approve"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.READY_TO_CLOSE


def test_derive_state_from_review_decision_changes():
    """REVIEW_DECISION with changes returns IN_PROGRESS."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "changes"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.IN_PROGRESS


def test_derive_state_from_review_decision_inspect():
    """REVIEW_DECISION with inspect returns HUMAN_GATE."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "inspect"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.HUMAN_GATE


def test_derive_state_unknown_state_value():
    """Unknown state values return UNKNOWN."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "NONEXISTENT_STATE"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.UNKNOWN


def test_derive_state_case_insensitive():
    """State derivation is case-insensitive."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "in_progress"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.IN_PROGRESS


def test_derive_state_from_close_confirmed_after_review_decision():
    """CLOSE_CONFIRMED after REVIEW_DECISION still returns COMPLETED."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "approve"}},
        {"event_type": "CLOSE_CONFIRMED", "payload": {}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.COMPLETED


# WP-2026-112: HUMAN_GATE transition validation tests
# These tests document the expected behavior that the EventBus enforces

def test_human_gate_is_valid_ticket_state():
    """HUMAN_GATE is a valid TicketState that can be derived from events."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "inspect"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.HUMAN_GATE
    assert state.value == "HUMAN_GATE"


def test_ready_to_close_is_valid_ticket_state():
    """READY_TO_CLOSE is a valid TicketState that can be derived from events."""
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": "READY_FOR_REVIEW"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "approve"}},
    ]
    state = StateMachine.derive_state_from_events(events)
    assert state == TicketState.READY_TO_CLOSE
    assert state.value == "READY_TO_CLOSE"


# =============================================================================
# Tests WP-2026-116: Ready-to-close reentry guard
# =============================================================================


def test_is_approved_or_terminal_ready_to_close_is_not_terminal():
    """WP-2026-116 follow-up: READY_TO_CLOSE is NOT terminal.

    It means 'approved, pending close'; a changes can still revert it before
    the final SUPERVISOR_CLOSED. Only COMPLETED is irreversible.
    """
    assert TicketState.is_approved_or_terminal(TicketState.READY_TO_CLOSE) is False


def test_is_approved_or_terminal_completed():
    """TicketState.is_approved_or_terminal returns True for COMPLETED (irreversible)."""
    assert TicketState.is_approved_or_terminal(TicketState.COMPLETED) is True


def test_is_approved_or_terminal_non_terminal_states():
    """TicketState.is_approved_or_terminal returns False for every non-COMPLETED state."""
    for state in [
        TicketState.IN_PROGRESS,
        TicketState.READY_FOR_REVIEW,
        TicketState.BLOCKED,
        TicketState.HUMAN_GATE,
        TicketState.READY_TO_CLOSE,
    ]:
        assert TicketState.is_approved_or_terminal(state) is False


def test_is_work_state():
    """TicketState.is_work_state returns True for work states."""
    for state in [
        TicketState.IN_PROGRESS,
        TicketState.READY_FOR_REVIEW,
        TicketState.BLOCKED,
        TicketState.HUMAN_GATE,
    ]:
        assert TicketState.is_work_state(state) is True


def test_is_work_state_terminal_states():
    """TicketState.is_work_state returns False for terminal states."""
    for state in [TicketState.READY_TO_CLOSE, TicketState.COMPLETED]:
        assert TicketState.is_work_state(state) is False
