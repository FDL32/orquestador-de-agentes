from __future__ import annotations

from bus.event_bus import EventBus
from bus.watcher import TurnWatcher


def test_event_bus_emit_and_read(tmp_path):
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    bus = EventBus(runtime_dir=runtime_dir)

    record = bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-023",
        actor="BUILDER",
        payload={
            "action": "IMPLEMENT",
            "plan_status": "APPROVED",
            "log_status": "IN_PROGRESS",
            "turn_path": ".agent/collaboration/TURN.md",
        },
        event_id="evt-001",
        timestamp="2026-05-11T12:23:13+00:00",
    )

    assert bus.events_path.exists()
    assert bus.schema_path.exists() is False
    assert record.sequence_number == 1

    events = bus.read_events(ticket_id="WP-2026-023")
    assert len(events) == 1
    assert events[0].to_dict() == record.to_dict()
    assert bus.latest_event(ticket_id="WP-2026-023").event_type == "TURN_CHANGED"

    second_record = bus.emit(
        "HANDOFF_REQUESTED",
        ticket_id="WP-2026-023",
        actor="SUPERVISOR",
        payload={"target_role": "MANAGER"},
        event_id="evt-002",
        timestamp="2026-05-11T12:23:14+00:00",
    )
    assert second_record.sequence_number == 2
    assert bus.latest_event(ticket_id="WP-2026-023").event_type == "HANDOFF_REQUESTED"


def test_watcher_detects_turn_changes(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    collaboration_dir.mkdir(parents=True)
    turn_path = collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Agente Activo",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-023 |",
                "| **Tipo** | IMPLEMENTATION |",
                "| **Accion** | IMPLEMENT |",
                "",
                "## Estado del Sistema",
                "",
                "| Archivo | Estado |",
                "|---------|--------|",
                "| work_plan.md | APPROVED |",
                "| execution_log.md | IN_PROGRESS |",
            ]
        ),
        encoding="utf-8",
    )

    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    watcher = TurnWatcher(collaboration_dir=collaboration_dir, event_bus=bus)

    first_event = watcher.publish_turn_event()
    assert first_event is not None
    assert first_event.ticket_id == "WP-2026-023"
    assert first_event.actor == "BUILDER"
    assert first_event.payload["action"] == "IMPLEMENT"

    second_event = watcher.publish_turn_event()
    assert second_event is None

    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Agente Activo",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **MANAGER** |",
                "| **Plan ID** | WP-2026-023 |",
                "| **Tipo** | IMPLEMENTATION |",
                "| **Accion** | REVIEW_WORK |",
                "",
                "## Estado del Sistema",
                "",
                "| Archivo | Estado |",
                "|---------|--------|",
                "| work_plan.md | APPROVED |",
                "| execution_log.md | READY_FOR_REVIEW |",
            ]
        ),
        encoding="utf-8",
    )

    third_event = watcher.publish_turn_event()
    assert third_event is not None
    assert third_event.actor == "MANAGER"
    assert third_event.payload["log_status"] == "READY_FOR_REVIEW"


def test_emit_dedupe_uses_redacted_payload(tmp_path):
    """Dedupe must compare on the redacted payload, otherwise repeated emits
    carrying the same secret would never match the stored (redacted) history
    and dedupe would silently degrade for payloads containing secrets.

    Regression guard for WP-2026-086 follow-up fix.
    """
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    bus = EventBus(runtime_dir=runtime_dir, max_duplicates=2, window_size=10)

    raw_payload = {"prompt": "use key sk-abcdefghijklmnopqrstuvwxyz12345 now"}

    # First two emits stored (dedupe threshold = 2)
    assert (
        bus.emit("X", ticket_id="WP-T", actor="A", payload=dict(raw_payload))
        is not None
    )
    assert (
        bus.emit("X", ticket_id="WP-T", actor="A", payload=dict(raw_payload))
        is not None
    )
    # Third identical emit (same raw, same redacted) must be blocked
    assert bus.emit("X", ticket_id="WP-T", actor="A", payload=dict(raw_payload)) is None

    stored = bus.read_events(ticket_id="WP-T")
    assert len(stored) == 2
    assert "sk-" not in stored[0].payload["prompt"]
    assert "***REDACTED***" in stored[0].payload["prompt"]


def _complete_ticket(bus, ticket_id="WP-RT"):
    """Helper: drive a ticket to COMPLETED (the only irreversible state)."""
    bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
    )


def test_reentry_guard_blocks_state_changed_reopen(tmp_path):
    """WP-2026-116: a direct STATE_CHANGED reopening a COMPLETED ticket is blocked."""
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    _complete_ticket(bus)

    result = bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-RT",
        actor="BUILDER",
        payload={"from_state": "COMPLETED", "to_state": "READY_FOR_REVIEW"},
    )
    assert result is None, "STATE_CHANGED reopen from COMPLETED must be blocked"


def test_reentry_guard_blocks_review_decision_changes_reopen(tmp_path):
    """WP-2026-116 follow-up: REVIEW_DECISION=changes cannot reopen a COMPLETED ticket.

    REVIEW_DECISION derives IN_PROGRESS (a work state). On a ticket already
    COMPLETED this is an illegal reentry through a route the original guard
    did not cover (it only inspected STATE_CHANGED).
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    _complete_ticket(bus)

    result = bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-RT",
        actor="MANAGER",
        payload={"decision": "changes"},
    )
    assert result is None, "REVIEW_DECISION=changes must not reopen a COMPLETED ticket"


def test_reentry_guard_allows_changes_on_ready_to_close(tmp_path):
    """WP-2026-116: READY_TO_CLOSE is NOT terminal — a changes can still revert it.

    Before the final close, an approved ticket may legitimately go back to
    work. READY_TO_CLOSE must not be guarded as irreversible.
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-RTC",
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "READY_TO_CLOSE"},
    )
    result = bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-RTC",
        actor="MANAGER",
        payload={"decision": "changes"},
    )
    assert result is not None, (
        "changes on READY_TO_CLOSE must be allowed (not terminal)"
    )


def test_reentry_guard_allows_review_decision_on_open_ticket(tmp_path):
    """WP-2026-116: REVIEW_DECISION=changes is allowed on a ticket under review."""
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-OPEN",
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )
    result = bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-OPEN",
        actor="MANAGER",
        payload={"decision": "changes"},
    )
    assert result is not None, "REVIEW_DECISION on a non-terminal ticket must pass"


def test_emit_state_changed_event(tmp_path):
    """WP-2026-118: Test real emission of STATE_CHANGED critical event.

    Before: Not all critical event types were exercised with emit().
    During: Emits STATE_CHANGED event and verifies it is stored correctly.
    After: Event is persisted with correct structure and can be retrieved.
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")

    result = bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-TEST-SC",
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    assert result is not None, "STATE_CHANGED emit should succeed"
    assert result.event_type == "STATE_CHANGED"
    assert result.ticket_id == "WP-TEST-SC"
    assert result.actor == "SUPERVISOR"
    assert result.payload["from_state"] == "IN_PROGRESS"
    assert result.payload["to_state"] == "READY_FOR_REVIEW"

    # Verify retrieval
    events = bus.read_events(ticket_id="WP-TEST-SC", event_type="STATE_CHANGED")
    assert len(events) == 1
    assert events[0].sequence_number == 1


def test_emit_review_decision_event(tmp_path):
    """WP-2026-118: Test real emission of REVIEW_DECISION critical event.

    Before: REVIEW_DECISION events were not explicitly tested with emit().
    During: Emits REVIEW_DECISION event with approve/changes decisions.
    After: Events are persisted and retrievable with correct structure.
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")

    # Test APPROVE decision
    approve_result = bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-TEST-RD",
        actor="MANAGER",
        payload={"decision": "approve"},
    )
    assert approve_result is not None
    assert approve_result.event_type == "REVIEW_DECISION"
    assert approve_result.payload["decision"] == "approve"

    # Test CHANGES decision
    changes_result = bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-TEST-RD",
        actor="MANAGER",
        payload={"decision": "changes"},
    )
    assert changes_result is not None
    assert changes_result.payload["decision"] == "changes"

    # Verify both events are retrievable
    events = bus.read_events(ticket_id="WP-TEST-RD", event_type="REVIEW_DECISION")
    assert len(events) == 2
    assert events[0].payload["decision"] == "approve"
    assert events[1].payload["decision"] == "changes"


def test_emit_loop_decision_event(tmp_path):
    """WP-2026-118: Test real emission of LOOP_DECISION critical event.

    Before: LOOP_DECISION events were not explicitly tested with emit().
    During: Emits LOOP_DECISION event with various decision types.
    After: Event is persisted with correct structure and can be retrieved.
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")

    result = bus.emit(
        "LOOP_DECISION",
        ticket_id="WP-TEST-LD",
        actor="SUPERVISOR",
        payload={
            "decision": "CONTINUE",
            "reason": "Work in progress",
            "next_action": "IMPLEMENT",
        },
    )

    assert result is not None, "LOOP_DECISION emit should succeed"
    assert result.event_type == "LOOP_DECISION"
    assert result.ticket_id == "WP-TEST-LD"
    assert result.actor == "SUPERVISOR"
    assert result.payload["decision"] == "CONTINUE"
    assert result.payload["reason"] == "Work in progress"
    assert result.payload["next_action"] == "IMPLEMENT"

    # Verify latest_event retrieval
    latest = bus.latest_event(ticket_id="WP-TEST-LD", event_type="LOOP_DECISION")
    assert latest is not None
    assert latest.payload["decision"] == "CONTINUE"


def test_critical_events_full_workflow(tmp_path):
    """WP-2026-118: Test complete workflow with all critical event types.

    Before: Critical events were tested in isolation.
    During: Exercises full ticket lifecycle with STATE_CHANGED, REVIEW_DECISION,
            and LOOP_DECISION events in sequence.
    After: All events are correctly sequenced and retrievable in order.
    """
    bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")

    # 1. STATE_CHANGED: IN_PROGRESS -> READY_FOR_REVIEW
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-FULL-WORKFLOW",
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # 2. REVIEW_DECISION: changes
    bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-FULL-WORKFLOW",
        actor="MANAGER",
        payload={"decision": "changes"},
    )

    # 3. STATE_CHANGED: back to IN_PROGRESS (after changes)
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-FULL-WORKFLOW",
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "IN_PROGRESS"},
    )

    # 4. LOOP_DECISION: continue work
    bus.emit(
        "LOOP_DECISION",
        ticket_id="WP-FULL-WORKFLOW",
        actor="SUPERVISOR",
        payload={"decision": "CONTINUE", "reason": "Builder needs more time"},
    )

    # 5. STATE_CHANGED: IN_PROGRESS -> READY_FOR_REVIEW (again)
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-FULL-WORKFLOW",
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # 6. REVIEW_DECISION: approve
    bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-FULL-WORKFLOW",
        actor="MANAGER",
        payload={"decision": "approve"},
    )

    # Verify all events are in correct sequence
    all_events = bus.read_events(ticket_id="WP-FULL-WORKFLOW")
    assert len(all_events) == 6

    # Verify sequence numbers are monotonic
    for i, event in enumerate(all_events, start=1):
        assert event.sequence_number == i

    # Verify event types in order
    expected_types = [
        "STATE_CHANGED",
        "REVIEW_DECISION",
        "STATE_CHANGED",
        "LOOP_DECISION",
        "STATE_CHANGED",
        "REVIEW_DECISION",
    ]
    actual_types = [e.event_type for e in all_events]
    assert actual_types == expected_types
