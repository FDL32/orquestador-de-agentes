"""Tests for scripts/loop_hard_stop.py -- Loop Kill-Switch Guard.

All tests use EventBus REAL (no mock) to avoid mock-drift.
tmp_path from pytest provides an isolated project_root per test.

WOT-2026-014v: deliverable_type mixed. Mutation-verify required for all 3 topes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# Ensure engine root is importable
_ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from bus.event_bus import EventBus  # noqa: E402
from bus.state_machine import StateMachine, TicketState  # noqa: E402
from scripts.loop_hard_stop import check_and_stop  # noqa: E402


TICKET = "WOT-2026-014v"

BUDGET_NORMAL = {
    "max_iterations": 10,
    "token_budget_estimated": 100_000,
    "timeout_seconds": 3600.0,
}


def _make_bus(project_root: Path) -> EventBus:
    """Create a real EventBus pointing to project_root/.agent/runtime/events."""
    events_dir = project_root / ".agent" / "runtime" / "events"
    return EventBus(runtime_dir=events_dir)


def _derive_state(project_root: Path, ticket_id: str) -> TicketState:
    """Read all events for ticket_id and derive the current state."""
    bus = _make_bus(project_root)
    events = [e.to_dict() for e in bus.read_events(ticket_id=ticket_id)]
    return StateMachine.derive_state_from_events(events)


# ---------------------------------------------------------------------------
# Test 1: iterations tope exceeded -> STOP + BLOCKED_FINAL
# ---------------------------------------------------------------------------


def test_stop_on_iterations_exceeded(tmp_path: Path) -> None:
    """iterations_current >= max_iterations triggers STOP with BLOCKED_FINAL.

    This test is the mutation-verify target for the iterations tope.
    When the iterations comparison is commented out in check_and_stop, this
    test must FAIL (guard returns CONTINUE instead of STOP).
    """
    budget = {**BUDGET_NORMAL, "max_iterations": 5}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=5,  # exactly at limit
        tokens_estimated=1_000,
        elapsed_seconds=10.0,
        budget=budget,
        project_root=tmp_path,
    )

    assert result["stopped"] is True, (
        "Guard must return stopped=True when iterations exceeded"
    )
    assert result["reason"] == "iterations", (
        f"Expected reason=iterations, got {result['reason']}"
    )

    # Bus state must be BLOCKED_FINAL
    state = _derive_state(tmp_path, TICKET)
    assert state == TicketState.BLOCKED_FINAL, f"Expected BLOCKED_FINAL, got {state}"

    # State artifact must exist with correct tope_cruzado
    artifact = tmp_path / ".agent" / "runtime" / "loop_hard_stop_state.json"
    assert artifact.exists(), "loop_hard_stop_state.json must be written"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["tope_cruzado"] == "iterations"
    assert data["ticket_id"] == TICKET
    assert "timestamp_utc" in data


# ---------------------------------------------------------------------------
# Test 2: tokens tope exceeded -> STOP + BLOCKED_FINAL
# ---------------------------------------------------------------------------


def test_stop_on_tokens_exceeded(tmp_path: Path) -> None:
    """tokens_estimated >= token_budget_estimated triggers STOP with BLOCKED_FINAL.

    Mutation-verify target for the tokens tope: comment out the tokens
    comparison -> this test must FAIL.
    """
    budget = {**BUDGET_NORMAL, "token_budget_estimated": 50_000}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=2,  # well below max_iterations
        tokens_estimated=50_000,  # exactly at limit
        elapsed_seconds=10.0,
        budget=budget,
        project_root=tmp_path,
    )

    assert result["stopped"] is True, (
        "Guard must return stopped=True when tokens exceeded"
    )
    assert result["reason"] == "tokens", (
        f"Expected reason=tokens, got {result['reason']}"
    )

    state = _derive_state(tmp_path, TICKET)
    assert state == TicketState.BLOCKED_FINAL

    artifact = tmp_path / ".agent" / "runtime" / "loop_hard_stop_state.json"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["tope_cruzado"] == "tokens"


# ---------------------------------------------------------------------------
# Test 3: timeout tope exceeded -> STOP + BLOCKED_FINAL
# ---------------------------------------------------------------------------


def test_stop_on_timeout_exceeded(tmp_path: Path) -> None:
    """elapsed_seconds >= timeout_seconds triggers STOP with BLOCKED_FINAL.

    Mutation-verify target for the timeout tope: comment out the timeout
    comparison -> this test must FAIL.
    """
    budget = {**BUDGET_NORMAL, "timeout_seconds": 300.0}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=2,  # below max_iterations
        tokens_estimated=1_000,  # below token budget
        elapsed_seconds=300.0,  # exactly at limit
        budget=budget,
        project_root=tmp_path,
    )

    assert result["stopped"] is True, (
        "Guard must return stopped=True when timeout exceeded"
    )
    assert result["reason"] == "timeout", (
        f"Expected reason=timeout, got {result['reason']}"
    )

    state = _derive_state(tmp_path, TICKET)
    assert state == TicketState.BLOCKED_FINAL

    artifact = tmp_path / ".agent" / "runtime" / "loop_hard_stop_state.json"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["tope_cruzado"] == "timeout"


# ---------------------------------------------------------------------------
# Test 4: no tope crossed -> CONTINUE, no terminal event
# ---------------------------------------------------------------------------


def test_continue_when_no_tope_crossed(tmp_path: Path) -> None:
    """All counters below limits -> stopped=False, no BLOCKED_FINAL in bus."""
    budget = {**BUDGET_NORMAL}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=4,  # below max_iterations=10
        tokens_estimated=50_000,  # below token_budget_estimated=100_000
        elapsed_seconds=100.0,  # below timeout_seconds=3600
        budget=budget,
        project_root=tmp_path,
    )

    assert result["stopped"] is False, (
        "Guard must return stopped=False when no tope crossed"
    )
    assert result["reason"] is None

    # Bus must have no events for this ticket (no stop occurred)
    bus = _make_bus(tmp_path)
    events = bus.read_events(ticket_id=TICKET)
    state_changed_events = [e for e in events if e.event_type == "STATE_CHANGED"]
    blocked_final_events = [
        e for e in state_changed_events if e.payload.get("to_state") == "BLOCKED_FINAL"
    ]
    assert len(blocked_final_events) == 0, (
        "No BLOCKED_FINAL must be emitted on CONTINUE"
    )

    # State artifact must NOT be written
    artifact = tmp_path / ".agent" / "runtime" / "loop_hard_stop_state.json"
    assert not artifact.exists(), (
        "loop_hard_stop_state.json must NOT be written on CONTINUE"
    )


# ---------------------------------------------------------------------------
# Test 5: bus coherence invariant -- BUILDER_EXIT seq < STATE_CHANGED seq
# ---------------------------------------------------------------------------


def test_builder_exit_before_state_changed(tmp_path: Path) -> None:
    """After STOP, BUILDER_EXIT sequence_number must be strictly less than
    the STATE_CHANGED -> BLOCKED_FINAL sequence_number (FP-001 invariant).

    Uses EventBus real with tmp_path. No mocks.
    """
    budget = {**BUDGET_NORMAL, "max_iterations": 3}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=3,
        tokens_estimated=1_000,
        elapsed_seconds=10.0,
        budget=budget,
        project_root=tmp_path,
    )

    assert result["stopped"] is True

    # Read all events from the real bus
    bus = _make_bus(tmp_path)
    all_events = bus.read_events(ticket_id=TICKET)

    # Find BUILDER_EXIT event
    builder_exit_events = [e for e in all_events if e.event_type == "BUILDER_EXIT"]
    assert len(builder_exit_events) >= 1, "BUILDER_EXIT must be emitted on STOP"
    builder_exit_seq = builder_exit_events[-1].sequence_number

    # Find STATE_CHANGED -> BLOCKED_FINAL event
    blocked_final_events = [
        e
        for e in all_events
        if e.event_type == "STATE_CHANGED"
        and e.payload.get("to_state") == "BLOCKED_FINAL"
    ]
    assert len(blocked_final_events) >= 1, (
        "STATE_CHANGED BLOCKED_FINAL must be emitted on STOP"
    )
    blocked_final_seq = blocked_final_events[-1].sequence_number

    assert builder_exit_seq < blocked_final_seq, (
        f"FP-001 violated: BUILDER_EXIT seq={builder_exit_seq} must be < "
        f"STATE_CHANGED seq={blocked_final_seq}"
    )

    # Verify BUILDER_EXIT payload
    bx_payload = builder_exit_events[-1].payload
    assert bx_payload.get("exit_reason") == "hard_stop"
    assert "tope_cruzado" in bx_payload

    # Verify no drift: derived state is BLOCKED_FINAL (no IN_PROGRESS dangling)
    events_as_dicts = [e.to_dict() for e in all_events]
    derived = StateMachine.derive_state_from_events(events_as_dicts)
    assert derived == TicketState.BLOCKED_FINAL, f"No drift expected; got {derived}"


# ---------------------------------------------------------------------------
# Test 6 (bonus): resume_predicate idempotence
# ---------------------------------------------------------------------------


def test_resume_predicate_idempotent(tmp_path: Path) -> None:
    """Calling resume_predicate twice from same partial state returns same result.

    After a hard stop the resume_predicate returns False (no M0 tag in tmp_path,
    and git clean check runs against tmp_path which is not a git repo). Calling
    it a second time produces the same result without duplicating bus events.
    """
    from scripts.loop_hard_stop import resume_predicate

    # First, trigger a stop so bus has BLOCKED_FINAL
    budget = {**BUDGET_NORMAL, "max_iterations": 1}
    result = check_and_stop(
        ticket_id=TICKET,
        iterations_current=1,
        tokens_estimated=1_000,
        elapsed_seconds=10.0,
        budget=budget,
        project_root=tmp_path,
    )
    assert result["stopped"] is True

    # resume_predicate requires a git repo (tmp_path is not one) -> False
    r1 = resume_predicate(tmp_path, TICKET)
    r2 = resume_predicate(tmp_path, TICKET)

    assert r1 == r2, "resume_predicate must be deterministic (idempotent)"

    # Bus events count must not grow between calls (no duplicate emissions)
    bus = _make_bus(tmp_path)
    events_after_r1 = len(bus.read_events(ticket_id=TICKET))
    _ = resume_predicate(tmp_path, TICKET)
    events_after_r2 = len(bus.read_events(ticket_id=TICKET))
    assert events_after_r1 == events_after_r2, (
        "resume_predicate must not add events to the bus"
    )
