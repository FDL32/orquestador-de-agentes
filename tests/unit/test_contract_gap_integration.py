"""WOT-2026-007f: Integration tests for CONTRACT_GAP runtime in bus/controller.

DoD coverage:
  - bus/event_bus.py accepts and emits CONTRACT_GAP without error.
  - StateMachine derives CONTRACT_BLOCKED from CONTRACT_GAP event.
  - state_projection_sync derives CONTRACT_BLOCKED via the StateMachine.
  - gap_type=premise_false/forbidden_surface_needed/missing_acceptance
    all produce CONTRACT_BLOCKED (not COMPLETED).
  - Payload contains exactly {ticket_id, gap_type, cg_file_path}.
  - _validate_contract_gap_coherence: event without CG file -> error.
  - _validate_contract_gap_coherence: CG file without event -> warning when
    the bus holds no events for the ticket (WOT-2026-067e: bus absent in
    this context), error when the bus holds other events for the ticket.
  - _validate_contract_gap_coherence: both present -> no error.
  - emit_contract_gap reentry guard: second emit for same ticket+gap_type -> None.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.state_machine import StateMachine, TicketState


# agent_controller lives under .agent/ and exposes _validate_contract_gap_coherence,
# the validator under test. Mirror the sys.path setup used by test_scope_gate.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AGENT_DIR = _PROJECT_ROOT / ".agent"
for _p in (str(_PROJECT_ROOT), str(_AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_controller  # noqa: E402


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
    work_plan_path.write_text(
        "# Work Plan\n- **ID:** WOT-2026-007t\n", encoding="utf-8"
    )

    class Env:
        def __init__(self):
            self.runtime_dir = runtime_dir
            self.collab_dir = collab_dir
            self.events_path = events_path
            self.state_md = state_md_path
            self.ticket_id = "WOT-2026-007t"
            self.bus = EventBus(runtime_dir)

    return Env()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _emit_contract_gap_raw(
    events_path: Path,
    ticket_id: str,
    gap_type: str,
    cg_file_path: str | None = None,
) -> None:
    """Write a CONTRACT_GAP event directly to the JSONL bus (for probe tests).

    Bypasses emit_contract_gap validation so tests can simulate legacy or
    tampered events (e.g. a non-canonical stored cg_file_path).
    """
    event = {
        "event_id": "test-id",
        "event_type": "CONTRACT_GAP",
        "ticket_id": ticket_id,
        "actor": "BUILDER",
        "timestamp": "2026-06-15T00:00:00+00:00",
        "payload": {
            "ticket_id": ticket_id,
            "gap_type": gap_type,
            "cg_file_path": cg_file_path or f"contract_gaps/CG-{ticket_id}.md",
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
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert result is not None, "emit_contract_gap must return an EventRecord"

    events = bus.read_events(ticket_id="WOT-2026-007a")
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
        ticket_id="WOT-2026-007a",
        gap_type="forbidden_surface_needed",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert result is not None

    events = bus.read_events(ticket_id="WOT-2026-007a")
    derived = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert derived == TicketState.CONTRACT_BLOCKED
    assert derived != TicketState.COMPLETED


# ---------------------------------------------------------------------------
# Test 3: gap_type=missing_acceptance -> CONTRACT_BLOCKED
# ---------------------------------------------------------------------------


def test_missing_acceptance_produces_contract_blocked(bus: EventBus) -> None:
    """gap_type=missing_acceptance must block the ticket."""
    result = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="missing_acceptance",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert result is not None

    events = bus.read_events(ticket_id="WOT-2026-007a")
    derived = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert derived == TicketState.CONTRACT_BLOCKED
    assert derived != TicketState.COMPLETED


# ---------------------------------------------------------------------------
# Test 4: Payload contains exactly {ticket_id, gap_type, cg_file_path}
# ---------------------------------------------------------------------------


def test_contract_gap_payload_keys_exact(bus: EventBus) -> None:
    """CONTRACT_GAP payload must contain exactly the three canonical keys."""
    result = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert result is not None, "emit_contract_gap must return an EventRecord"

    # Read back from bus to verify what was persisted
    events = bus.read_events(ticket_id="WOT-2026-007a", event_type="CONTRACT_GAP")
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
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert first is not None, "First emit must succeed"

    second = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert second is None, "Reentry guard must block duplicate CONTRACT_GAP"

    # Only one event in bus
    events = bus.read_events(ticket_id="WOT-2026-007a", event_type="CONTRACT_GAP")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Test 6: Invalid gap_type is rejected
# ---------------------------------------------------------------------------


def test_contract_gap_invalid_gap_type_rejected(bus: EventBus) -> None:
    """emit_contract_gap must return None for an unknown gap_type."""
    result = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="invented_gap",
        cg_file_path="contract_gaps/CG-WOT-2026-007a.md",
    )
    assert result is None, "Invalid gap_type must be rejected"

    events = bus.read_events(ticket_id="WOT-2026-007a", event_type="CONTRACT_GAP")
    assert len(events) == 0


# ---------------------------------------------------------------------------
# Test 6b: non-canonical cg_file_path is rejected (payload-path security)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "C:/abs/CG-WOT-2026-007a.md",  # absolute (windows)
        "/abs/CG-WOT-2026-007a.md",  # absolute (posix)
        "../CG-WOT-2026-007a.md",  # parent traversal
        "contract_gaps/../CG-WOT-2026-007a.md",  # embedded traversal
        "other/CG-WOT-2026-007a.md",  # wrong directory
        "contract_gaps/CG-WRONG.md",  # wrong filename for ticket
        "contract_gaps/CG-WOT-2026-007a.txt",  # wrong extension
    ],
    # Explicit, filesystem-safe ids: the raw paths contain ':' and '/' which
    # break the tmp_path factory's per-node directory name on Windows.
    ids=[
        "abs-windows",
        "abs-posix",
        "parent-traversal",
        "embedded-traversal",
        "wrong-dir",
        "wrong-filename",
        "wrong-ext",
    ],
)
def test_contract_gap_rejects_non_canonical_cg_path(
    bus: EventBus, bad_path: str
) -> None:
    """emit_contract_gap must reject any cg_file_path != contract_gaps/CG-<ticket>.md."""
    result = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path=bad_path,
    )
    assert result is None, f"Non-canonical cg_file_path must be rejected: {bad_path}"
    assert bus.read_events(ticket_id="WOT-2026-007a", event_type="CONTRACT_GAP") == []


def test_contract_gap_stores_normalized_canonical_path(bus: EventBus) -> None:
    """A backslash-variant canonical path is accepted and stored normalized."""
    result = bus.emit_contract_gap(
        ticket_id="WOT-2026-007a",
        gap_type="premise_false",
        cg_file_path="contract_gaps\\CG-WOT-2026-007a.md",
    )
    assert result is not None
    events = bus.read_events(ticket_id="WOT-2026-007a", event_type="CONTRACT_GAP")
    assert len(events) == 1
    assert events[0].payload["cg_file_path"] == "contract_gaps/CG-WOT-2026-007a.md"


# ---------------------------------------------------------------------------
# Test 6c: invalid ticket_id is rejected (closes path-guard bypass)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ticket",
    [
        "../outside",  # traversal smuggled via ticket_id
        "not a ticket",  # free text
        "WOT-2026-007a/../evil",  # path injection
        "",  # empty
        "lowercase-2026-001",  # bad prefix
    ],
    ids=["traversal", "free-text", "path-injection", "empty", "bad-prefix"],
)
def test_contract_gap_rejects_invalid_ticket_id(bus: EventBus, bad_ticket: str) -> None:
    """emit_contract_gap must reject any ticket_id that is not a canonical id.

    A crafted ticket_id like "../outside" would otherwise make the canonical
    path contract_gaps/CG-../outside.md and smuggle traversal past the path
    guard. is_valid_ticket_id forecloses that.
    """
    result = bus.emit_contract_gap(
        ticket_id=bad_ticket,
        gap_type="premise_false",
        cg_file_path=f"contract_gaps/CG-{bad_ticket}.md",
    )
    assert result is None, f"Invalid ticket_id must be rejected: {bad_ticket!r}"
    assert bus.read_events(event_type="CONTRACT_GAP") == []


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


def _patch_coherence_seams(monkeypatch, agent_dir: Path, bus: EventBus) -> None:
    """Point _validate_contract_gap_coherence at a tmp agent dir + given bus.

    The validator reads BUS_AVAILABLE, calls _get_event_bus(), and scans
    get_agent_dir()/planning/contract_gaps/. Patching these three seams makes
    the test exercise the real validator deterministically.
    """
    monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
    monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: bus)
    monkeypatch.setattr(agent_controller, "get_agent_dir", lambda: agent_dir)


def test_validate_coherence_event_without_cg_file(tmp_path: Path, monkeypatch) -> None:
    """_validate_contract_gap_coherence: bus event present, CG file absent -> error.

    Exercises the REAL validator (not pre-baked booleans): emits a CONTRACT_GAP
    event into a bus, leaves contract_gaps/ empty, and asserts the validator
    returns the incoherence error.
    """
    ticket_id = "WOT-2026-007b"
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)
    # contract_gaps/ exists but holds no CG file for this ticket.
    (agent_dir / "planning" / "contract_gaps").mkdir(parents=True)

    local_bus = EventBus(runtime_dir)
    local_bus.emit_contract_gap(
        ticket_id=ticket_id,
        gap_type="premise_false",
        cg_file_path=f"contract_gaps/CG-{ticket_id}.md",
    )

    _patch_coherence_seams(monkeypatch, agent_dir, local_bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert len(errors) == 1, f"Expected exactly one coherence error, got: {errors}"
    assert "not found in contract_gaps" in errors[0]
    assert warnings == [], f"Inverse branch must not emit warnings, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 9: _validate_contract_gap_coherence: CG file without event for the
# ticket -> degraded to warning (WOT-2026-067e, re-anchored: was error)
# ---------------------------------------------------------------------------


def test_validate_coherence_cg_file_without_event(tmp_path: Path, monkeypatch) -> None:
    """CG file present, bus WITHOUT events for this ticket -> warning, not error.

    WOT-2026-067e: originally this test pinned the pre-fix behavior (hard
    error on an empty bus). The fix degrades the branch to a warning when the
    runtime bus holds no events for the ticket (bus absent in this context).
    Re-anchored to the ticket-scoping boundary: the bus is NON-empty but only
    holds events for a DIFFERENT ticket, so bus_has_ticket_events(<ticket>)
    is still False and the branch must degrade, not hard-fail.
    """
    ticket_id = "WOT-2026-007c"
    other_ticket = "WOT-2026-000z"
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)
    cg_dir = agent_dir / "planning" / "contract_gaps"
    cg_dir.mkdir(parents=True)
    (cg_dir / f"CG-{ticket_id}.md").write_text(
        f"# CG-{ticket_id}\n- **ticket_id:** {ticket_id}\n", encoding="utf-8"
    )

    local_bus = EventBus(runtime_dir)  # events for another ticket only
    emitted = local_bus.emit(
        "STATE_CHANGED",
        ticket_id=other_ticket,
        actor="BUILDER",
        payload={"to_state": "IN_PROGRESS"},
    )
    assert emitted is not None, "bus setup: STATE_CHANGED for other ticket must emit"

    _patch_coherence_seams(monkeypatch, agent_dir, local_bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert errors == [], (
        f"Bus absent for THIS ticket must degrade to warning, got errors: {errors}"
    )
    assert len(warnings) == 1, f"Expected exactly one warning, got: {warnings}"
    assert "no CONTRACT_GAP event found in bus" in warnings[0]
    assert "bus absent in this context" in warnings[0]


# ---------------------------------------------------------------------------
# Test 9b: _validate_contract_gap_coherence: both present -> no error (boundary)
# ---------------------------------------------------------------------------


def test_validate_coherence_both_present_no_error(tmp_path: Path, monkeypatch) -> None:
    """Both the bus event and the CG file present -> coherent -> no errors."""
    ticket_id = "WOT-2026-007d"
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)
    cg_dir = agent_dir / "planning" / "contract_gaps"
    cg_dir.mkdir(parents=True)
    (cg_dir / f"CG-{ticket_id}.md").write_text(f"# CG-{ticket_id}\n", encoding="utf-8")

    local_bus = EventBus(runtime_dir)
    local_bus.emit_contract_gap(
        ticket_id=ticket_id,
        gap_type="missing_acceptance",
        cg_file_path=f"contract_gaps/CG-{ticket_id}.md",
    )

    _patch_coherence_seams(monkeypatch, agent_dir, local_bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert errors == [], f"Coherent state must produce no errors, got: {errors}"
    assert warnings == [], f"Coherent state must produce no warnings, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 9c: validator flags a stored non-canonical cg_file_path (legacy/tampered)
# ---------------------------------------------------------------------------


def test_validate_coherence_flags_non_canonical_stored_path(
    tmp_path: Path, monkeypatch
) -> None:
    """A legacy/tampered event whose stored cg_file_path is non-canonical -> error.

    emit_contract_gap now rejects bad paths, so this event is written raw to
    simulate an event that predates the guard. The validator must still catch
    the non-canonical stored path even though the CG file itself exists.
    """
    ticket_id = "WOT-2026-007e"
    agent_dir = tmp_path / ".agent"
    runtime_dir = agent_dir / "runtime" / "events"
    runtime_dir.mkdir(parents=True)
    cg_dir = agent_dir / "planning" / "contract_gaps"
    cg_dir.mkdir(parents=True)
    # Canonical CG file present (so the present/absent check passes).
    (cg_dir / f"CG-{ticket_id}.md").write_text("x", encoding="utf-8")
    # Raw event with a NON-canonical stored path (absolute, smuggled).
    _emit_contract_gap_raw(
        runtime_dir / "events.jsonl",
        ticket_id,
        "premise_false",
        cg_file_path="/abs/evil.md",
    )

    local_bus = EventBus(runtime_dir)
    _patch_coherence_seams(monkeypatch, agent_dir, local_bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, _warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert any("path incoherence" in e for e in errors), (
        f"Validator must flag the stored non-canonical path, got: {errors}"
    )


# ---------------------------------------------------------------------------
# WOT-2026-067e: the "CG file without event" branch degrades to a warning
# when the runtime bus holds no events for the ticket (bus absent in this
# context), and stays an error when the bus DOES hold events for the ticket.
# The inverse branch (event without CG file) is untouched. These use the
# same `bus: EventBus` fixture as the rest of the file; the validator seams
# are patched with the same _patch_coherence_seams helper.
# ---------------------------------------------------------------------------


def test_cg_sin_evento_y_bus_vacio_degrada_a_warning(
    bus: EventBus, tmp_path: Path, monkeypatch
) -> None:
    """DoD 1: CG on disk + bus with NO events for the ticket -> warning.

    The CI / fresh-clone case: the gitignored bus never travels, so the
    "CG exists but no CONTRACT_GAP event" branch fired on every CI run. The
    fix degrades it to a warning when bus_has_ticket_events is False.
    """
    ticket_id = "WOT-2026-067e"
    agent_dir = tmp_path / ".agent"
    cg_dir = agent_dir / "planning" / "contract_gaps"
    cg_dir.mkdir(parents=True)
    (cg_dir / f"CG-{ticket_id}.md").write_text(
        f"# CG-{ticket_id}\n- **ticket_id:** {ticket_id}\n", encoding="utf-8"
    )

    # `bus` fixture: fresh EventBus over tmp_path/events -- no events at all.
    assert bus.read_events(ticket_id=ticket_id) == []
    _patch_coherence_seams(monkeypatch, agent_dir, bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert errors == [], (
        f"Bus absent in this context must NOT hard-fail, got errors: {errors}"
    )
    assert len(warnings) == 1, f"Expected exactly one warning, got: {warnings}"
    assert "no CONTRACT_GAP event found in bus" in warnings[0]
    assert "bus absent in this context" in warnings[0]


def test_cg_sin_evento_pero_bus_con_eventos_sigue_siendo_error_bus_sin_contract_gap(
    bus: EventBus, tmp_path: Path, monkeypatch
) -> None:
    """DoD 3 (negative control): CG on disk + bus with OTHER events for the
    ticket but NO CONTRACT_GAP -> stays an error.

    Builds the "bus with events but no CONTRACT_GAP" state by emitting a
    STATE_CHANGED for the plan_id and no CONTRACT_GAP, per the work plan.

    Name note: the work plan's -k filter for this DoD is
    ``bus_sin_contract_gap``; the suffix keeps that filter selecting THIS
    test (the plan's mandated name alone did not match its own -k command).
    """
    ticket_id = "WOT-2026-067b"
    agent_dir = tmp_path / ".agent"
    cg_dir = agent_dir / "planning" / "contract_gaps"
    cg_dir.mkdir(parents=True)
    (cg_dir / f"CG-{ticket_id}.md").write_text(
        f"# CG-{ticket_id}\n- **ticket_id:** {ticket_id}\n", encoding="utf-8"
    )

    emitted = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"to_state": "IN_PROGRESS"},
    )
    assert emitted is not None, "bus setup: STATE_CHANGED for the ticket must emit"
    assert bus.read_events(ticket_id=ticket_id, event_type="CONTRACT_GAP") == []

    _patch_coherence_seams(monkeypatch, agent_dir, bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert len(errors) == 1, f"Observable incoherence must stay an ERROR, got: {errors}"
    assert "no CONTRACT_GAP event found in bus" in errors[0]
    assert warnings == [], f"No warning may accompany the error, got: {warnings}"


def test_evento_sin_cg_sigue_siendo_error_bus_sin_contract_gap(
    bus: EventBus, tmp_path: Path, monkeypatch
) -> None:
    """DoD 4: bus with a CONTRACT_GAP event and NO CG file -> stays an error.

    The inverse branch must NOT be relaxed by WOT-2026-067e: when the bus is
    visible and declares a CONTRACT_GAP without a file, that is a real
    incoherence regardless of bus visibility.
    """
    ticket_id = "WOT-2026-067c"
    agent_dir = tmp_path / ".agent"
    # contract_gaps/ exists but holds no CG file for this ticket.
    (agent_dir / "planning" / "contract_gaps").mkdir(parents=True)

    result = bus.emit_contract_gap(
        ticket_id=ticket_id,
        gap_type="premise_false",
        cg_file_path=f"contract_gaps/CG-{ticket_id}.md",
    )
    assert result is not None, "bus setup: CONTRACT_GAP emit must succeed"
    assert not (
        agent_dir / "planning" / "contract_gaps" / f"CG-{ticket_id}.md"
    ).exists()

    _patch_coherence_seams(monkeypatch, agent_dir, bus)
    plan_content = f"# Work Plan\n- **ID:** {ticket_id}\n"
    errors, warnings = agent_controller._validate_contract_gap_coherence(plan_content)

    assert len(errors) == 1, f"Inverse branch must stay an ERROR, got: {errors}"
    assert "not found in contract_gaps" in errors[0]
    assert warnings == [], f"No warning may accompany the error, got: {warnings}"


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
                "ticket_id": "WOT-2026-007a",
                "gap_type": "forbidden_surface_needed",
                "cg_file_path": "contract_gaps/CG-WOT-2026-007a.md",
            },
        },
    ]
    derived = StateMachine.derive_state_from_events(events)
    assert derived == TicketState.CONTRACT_BLOCKED
