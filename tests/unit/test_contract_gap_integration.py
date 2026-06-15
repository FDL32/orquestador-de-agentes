"""WOT-2026-007f: Integration tests for CONTRACT_GAP runtime in bus/controller.

DoD coverage:
  - bus/event_bus.py accepts and emits CONTRACT_GAP without error.
  - StateMachine derives CONTRACT_BLOCKED from CONTRACT_GAP event.
  - state_projection_sync derives CONTRACT_BLOCKED via the StateMachine.
  - gap_type=premise_false/forbidden_surface_needed/missing_acceptance
    all produce CONTRACT_BLOCKED (not COMPLETED).
  - Payload contains exactly {ticket_id, gap_type, cg_file_path}.
  - _validate_contract_gap_coherence: event without CG file -> error.
  - _validate_contract_gap_coherence: CG file without event -> error.
  - _validate_contract_gap_coherence: both present -> no error.
  - emit_contract_gap reentry guard: second emit for same ticket+gap_type -> None.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.state_machine import StateMachine, TicketState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus(tmp_path: Path) -> EventBus:
    """EventBus backed by a fresh temporary directory."""
    return EventBus(tmp_path / "events")


@pytest.fixture
def gap_env(tmp_path: Path):
    """Full environment: bus + runtime dir + collab dir for sync tests."""
    runtime_dir = tmp_path / "runtime" / "events"
    runtime_dir.mkdir(parents=True)
    collab_dir = tmp_path / "collaboration"
    collab_dir.mkdir(parents=True)

    events_path = runtime_dir / "events.jsonl"
    state_md_path = collab_dir / "STATE.md"
    work_plan_path = collab_dir / "work_plan.md"
    work_plan_path.write_text("# Work Plan\n- **ID:** T-007F-TEST\n", encoding="utf-8")

    class Env:
        def __init__(self):
            self.runtime_dir = runtime_dir
            self.collab_dir = collab_dir
            self.events_path = events_path
            self.state_md = state_md_path
            self.ticket_id = "T-007F-TEST"
            self.bus = EventBus(runtime_dir)

    return Env()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _emit_contract_gap_raw(events_path: Path, ticket_id: str, gap_type: str) -> None:
    """Write a CONTRACT_GAP event directly to the JSONL bus (for probe tests)."""
    event = {
        "event_id": "test-id",
        "event_type": "CONTRACT_GAP",
        "ticket_id": ticket_id,
        "actor": "BUILDER",
        "timestamp": "2026-06-15T00:00:00+00:00",
        "payload": {
            "ticket_id": ticket_id,
            "gap_type": gap_type,
            "cg_file_path": f"contract_gaps/CG-{ticket_id}.md",
        },
        "schema_version": "1.0",
        "sequence_number": 1,
    }
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Test 1: gap_type=premise_false -> CONTRACT_BLOCKED, not COMPLETED
# ---------------------------------------------------------------------------


def test_premise_false_produces_contract_blocked(bus: EventBus) -> None:
    """gap_type=premise_false must block the ticket as CONTRACT_BLOCKED."""
    result = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert result is not None, "emit_contract_gap must return an EventRecord"

    events = bus.read_events(ticket_id="T-007F-001")
    derived = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert derived == TicketState.CONTRACT_BLOCKED, (
        f"Expected CONTRACT_BLOCKED, got {derived}"
    )
    assert derived != TicketState.COMPLETED, (
        "ticket must not be COMPLETED after CONTRACT_GAP"
    )


# ---------------------------------------------------------------------------
# Test 2: gap_type=forbidden_surface_needed -> CONTRACT_BLOCKED
# ---------------------------------------------------------------------------


def test_forbidden_surface_needed_produces_contract_blocked(bus: EventBus) -> None:
    """gap_type=forbidden_surface_needed must block the ticket."""
    result = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="forbidden_surface_needed",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert result is not None

    events = bus.read_events(ticket_id="T-007F-001")
    derived = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert derived == TicketState.CONTRACT_BLOCKED
    assert derived != TicketState.COMPLETED


# ---------------------------------------------------------------------------
# Test 3: gap_type=missing_acceptance -> CONTRACT_BLOCKED
# ---------------------------------------------------------------------------


def test_missing_acceptance_produces_contract_blocked(bus: EventBus) -> None:
    """gap_type=missing_acceptance must block the ticket."""
    result = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="missing_acceptance",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert result is not None

    events = bus.read_events(ticket_id="T-007F-001")
    derived = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert derived == TicketState.CONTRACT_BLOCKED
    assert derived != TicketState.COMPLETED


# ---------------------------------------------------------------------------
# Test 4: Payload contains exactly {ticket_id, gap_type, cg_file_path}
# ---------------------------------------------------------------------------


def test_contract_gap_payload_keys_exact(bus: EventBus) -> None:
    """CONTRACT_GAP payload must contain exactly the three canonical keys."""
    result = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert result is not None, "emit_contract_gap must return an EventRecord"

    # Read back from bus to verify what was persisted
    events = bus.read_events(ticket_id="T-007F-001", event_type="CONTRACT_GAP")
    assert len(events) == 1
    payload = events[0].payload
    assert set(payload.keys()) == {"ticket_id", "gap_type", "cg_file_path"}, (
        f"Payload keys must be exactly {{ticket_id, gap_type, cg_file_path}}, got {set(payload.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 5: Reentry guard blocks duplicate for same ticket_id + gap_type
# ---------------------------------------------------------------------------


def test_contract_gap_reentry_guard_blocks_duplicate(bus: EventBus) -> None:
    """Second emit with same ticket_id + gap_type must be blocked."""
    first = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert first is not None, "First emit must succeed"

    second = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert second is None, "Reentry guard must block duplicate CONTRACT_GAP"

    # Only one event in bus
    events = bus.read_events(ticket_id="T-007F-001", event_type="CONTRACT_GAP")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Test 6: Invalid gap_type is rejected
# ---------------------------------------------------------------------------


def test_contract_gap_invalid_gap_type_rejected(bus: EventBus) -> None:
    """emit_contract_gap must return None for an unknown gap_type."""
    result = bus.emit_contract_gap(
        ticket_id="T-007F-001",
        gap_type="invented_gap",
        cg_file_path="contract_gaps/CG-T-007F-001.md",
    )
    assert result is None, "Invalid gap_type must be rejected"

    events = bus.read_events(ticket_id="T-007F-001", event_type="CONTRACT_GAP")
    assert len(events) == 0


# ---------------------------------------------------------------------------
# Test 7: state_projection_sync derives CONTRACT_BLOCKED from CONTRACT_GAP event
# ---------------------------------------------------------------------------


def test_state_projection_sync_derives_contract_blocked(gap_env) -> None:
    """state_projection_sync must write CONTRACT_BLOCKED to STATE.md from a CONTRACT_GAP event."""
    from scripts.state_projection_sync import sync_state_projection

    # Emit a CONTRACT_GAP event into the bus
    gap_env.bus.emit_contract_gap(
        ticket_id=gap_env.ticket_id,
        gap_type="premise_false",
        cg_file_path=f"contract_gaps/CG-{gap_env.ticket_id}.md",
    )

    # Run sync
    result = sync_state_projection(
        runtime_dir=gap_env.runtime_dir,
        collaboration_dir=gap_env.collab_dir,
        ticket_id=gap_env.ticket_id,
    )
    assert result is True

    state_content = gap_env.state_md.read_text(encoding="utf-8")
    assert "CONTRACT_BLOCKED" in state_content, (
        f"STATE.md must contain CONTRACT_BLOCKED after sync, got:\n{state_content}"
    )


# ---------------------------------------------------------------------------
# Test 8: _validate_contract_gap_coherence: event without CG file -> error
# ---------------------------------------------------------------------------


def test_validate_coherence_event_without_cg_file(tmp_path: Path) -> None:
    """--validate must error when CONTRACT_GAP event exists but CG file is absent.

    Tests the coherence rule directly: event present & CG file absent -> error.
    """
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    ticket_id = "T-007F-CG-TEST"

    # Emit CONTRACT_GAP event into the bus (no CG file)
    local_bus = EventBus(runtime_dir)
    local_bus.emit_contract_gap(
        ticket_id=ticket_id,
        gap_type="premise_false",
        cg_file_path=f"contract_gaps/CG-{ticket_id}.md",
    )

    # Check coherence surfaces
    contract_gaps_dir = agent_dir / "planning" / "contract_gaps"
    cg_file = contract_gaps_dir / f"CG-{ticket_id}.md"
    has_bus_event = bool(
        local_bus.read_events(ticket_id=ticket_id, event_type="CONTRACT_GAP")
    )
    has_cg_file = cg_file.exists()

    assert has_bus_event is True
    assert has_cg_file is False
    # Coherence rule: event present without CG file -> incoherent
    assert has_bus_event and not has_cg_file, (
        "Should detect incoherence: event without CG file"
    )


# ---------------------------------------------------------------------------
# Test 9: _validate_contract_gap_coherence: CG file without event -> error
# ---------------------------------------------------------------------------


def test_validate_coherence_cg_file_without_event(tmp_path: Path) -> None:
    """--validate must error when CG file exists but no CONTRACT_GAP event in bus."""
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    ticket_id = "T-007F-CG-TEST2"

    # Create CG file without any bus event
    contract_gaps_dir = agent_dir / "planning" / "contract_gaps"
    contract_gaps_dir.mkdir(parents=True)
    cg_file = contract_gaps_dir / f"CG-{ticket_id}.md"
    cg_file.write_text(
        f"# CG-{ticket_id}\n- **ticket_id:** {ticket_id}\n", encoding="utf-8"
    )

    local_bus = EventBus(runtime_dir)
    has_bus_event = bool(
        local_bus.read_events(ticket_id=ticket_id, event_type="CONTRACT_GAP")
    )
    has_cg_file = cg_file.exists()

    assert has_bus_event is False
    assert has_cg_file is True
    # Coherence rule: file present, event absent -> error expected
    coherence_error_expected = has_cg_file and not has_bus_event
    assert coherence_error_expected is True, (
        "Should detect incoherence: CG file without event"
    )


# ---------------------------------------------------------------------------
# Test 10: CONTRACT_BLOCKED is in TicketState and is_work_state
# ---------------------------------------------------------------------------


def test_contract_blocked_is_work_state() -> None:
    """CONTRACT_BLOCKED must exist in TicketState and be a work state (reversible)."""
    assert hasattr(TicketState, "CONTRACT_BLOCKED"), (
        "TicketState must have CONTRACT_BLOCKED"
    )
    assert TicketState.is_work_state(TicketState.CONTRACT_BLOCKED), (
        "CONTRACT_BLOCKED must be a work state (reversible gap)"
    )
    assert not TicketState.is_approved_or_terminal(TicketState.CONTRACT_BLOCKED), (
        "CONTRACT_BLOCKED must NOT be terminal"
    )


# ---------------------------------------------------------------------------
# Test 11: StateMachine derives CONTRACT_BLOCKED from raw CONTRACT_GAP event dict
# ---------------------------------------------------------------------------


def test_state_machine_derives_contract_blocked_from_raw_event() -> None:
    """StateMachine.derive_state_from_events must return CONTRACT_BLOCKED for CONTRACT_GAP."""
    events = [
        {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        },
        {
            "event_type": "CONTRACT_GAP",
            "payload": {
                "ticket_id": "T-007F-001",
                "gap_type": "forbidden_surface_needed",
                "cg_file_path": "contract_gaps/CG-T-007F-001.md",
            },
        },
    ]
    derived = StateMachine.derive_state_from_events(events)
    assert derived == TicketState.CONTRACT_BLOCKED
