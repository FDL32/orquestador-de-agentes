"""WOT-2026-013n: honest non-success terminal states (SUPERSEDED, BLOCKED_FINAL).

These tests are the regression barrier for terminality. Each FAIL-without/PASS-with
pair would have failed before the fix: the old authority only treated COMPLETED as
terminal, so SUPERSEDED / BLOCKED_FINAL would have been classified as non-terminal
(and reconcilers/closeout/launcher would have demanded a fake COMPLETED).
"""

from __future__ import annotations

import pytest
from bus.state_machine import (
    IRREVERSIBLE_TERMINAL_STATES,
    NON_SUCCESS_TERMINAL_STATES,
    NON_TERMINAL_STATES,
    StateMachine,
    TicketState,
    is_terminal_state,
    terminal_state_strings,
)


# --- Authority: the new states exist and are irreversible terminals ----------


def test_new_states_are_enum_members():
    assert TicketState.SUPERSEDED.value == "SUPERSEDED"
    assert TicketState.BLOCKED_FINAL.value == "BLOCKED_FINAL"


@pytest.mark.parametrize("state", [TicketState.SUPERSEDED, TicketState.BLOCKED_FINAL])
def test_new_states_are_terminal(state: TicketState):
    # FAIL-without: old authority returned terminal only for COMPLETED.
    assert state in IRREVERSIBLE_TERMINAL_STATES
    assert TicketState.is_approved_or_terminal(state) is True
    assert is_terminal_state(state) is True
    assert state not in NON_TERMINAL_STATES


@pytest.mark.parametrize("state", [TicketState.SUPERSEDED, TicketState.BLOCKED_FINAL])
def test_new_states_are_non_success(state: TicketState):
    # Honest non-success: terminal but NOT COMPLETED.
    assert state in NON_SUCCESS_TERMINAL_STATES
    assert state != TicketState.COMPLETED


def test_completed_still_terminal_success():
    assert TicketState.COMPLETED in IRREVERSIBLE_TERMINAL_STATES
    assert TicketState.COMPLETED not in NON_SUCCESS_TERMINAL_STATES
    assert TicketState.is_approved_or_terminal(TicketState.COMPLETED) is True


def test_ready_to_close_is_not_terminal():
    # Regression guard: approved-pending-close must stay reversible.
    assert TicketState.READY_TO_CLOSE in NON_TERMINAL_STATES
    assert TicketState.is_approved_or_terminal(TicketState.READY_TO_CLOSE) is False
    assert is_terminal_state(TicketState.READY_TO_CLOSE) is False


# --- Legacy CLOSED absorbed as literal, NOT promoted to enum ------------------


def test_closed_recognised_as_terminal_literal():
    assert is_terminal_state("CLOSED") is True
    assert "CLOSED" in terminal_state_strings(include_legacy=True)
    assert "CLOSED" not in terminal_state_strings(include_legacy=False)


def test_closed_is_not_an_enum_member():
    assert "CLOSED" not in TicketState.__members__


# --- is_terminal_state helper contract ---------------------------------------


def test_is_terminal_state_accepts_string_and_none():
    assert is_terminal_state("SUPERSEDED") is True
    assert is_terminal_state("blocked_final") is True  # case-insensitive
    assert is_terminal_state("IN_PROGRESS") is False
    assert is_terminal_state(None) is False
    assert is_terminal_state("NONSENSE") is False


# --- derive_state_from_events maps the new states (close consumer) ------------


@pytest.mark.parametrize("name", ["SUPERSEDED", "BLOCKED_FINAL"])
def test_derive_state_from_events_maps_new_terminals(name: str):
    events = [
        {"event_type": "STATE_CHANGED", "payload": {"to_state": name}},
    ]
    derived = StateMachine.derive_state_from_events(events)
    assert derived is TicketState[name]
    assert is_terminal_state(derived) is True


# --- Close consumer barrier: reconcile_ticket TERMINAL_STATES -----------------


@pytest.mark.parametrize("name", ["SUPERSEDED", "BLOCKED_FINAL", "COMPLETED", "CLOSED"])
def test_reconcile_terminal_states_include_authority(name: str):
    # FAIL-without: reconcile previously had {"COMPLETED","CLOSED"} only, so a
    # ticket already SUPERSEDED would be re-driven to COMPLETED (fake success).
    from scripts.reconcile_ticket import TERMINAL_STATES

    assert name in TERMINAL_STATES
