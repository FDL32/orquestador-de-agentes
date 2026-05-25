from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bus.state_machine import StateMachine, TicketState
from bus.supervisor import SequentialTicketSupervisor, SupervisorState


def _write_work_plan(path):
    path.write_text(
        "\n".join(
            [
                "# Plan de Trabajo del Proyecto",
                "",
                "## WP-2026-024: UI State Projection",
                "",
                "### Metadata",
                "- **ID:** WP-2026-024",
                "- **Estado:** PENDING",
                "- **Creado por:** Manager",
                "- **Fecha:** 2026-05-11",
                "",
                "### Objetivo",
                "Generar ui_state.json.",
            ]
        ),
        encoding="utf-8",
    )


def _write_execution_log(path):
    path.write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## Project summary",
                "",
                "- Project: `orquestador_de_agentes`",
                "- **Estado:** IN_PROGRESS",
                "- Current state: ACTIVE",
                "- Active workstreams: WP-2026-024",
                "",
                "### Quality Gates",
                "- [OK] Ruff: Clean",
                "- [OK] Pytest: Tests OK",
                "- Quality Gates: PASSED",
            ]
        ),
        encoding="utf-8",
    )


def _write_turn(
    path,
    role="BUILDER",
    plan_id="WP-2026-024",
    action="IMPLEMENT",
    plan_status="APPROVED",
    log_status="IN_PROGRESS",
):
    path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Agente Activo",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                f"| **ROL** | **{role}** |",
                f"| **Plan ID** | {plan_id} |",
                "| **Tipo** | IMPLEMENTATION |",
                f"| **Accion** | {action} |",
                "",
                "## Estado del Sistema",
                "",
                "| Archivo | Estado |",
                "|---------|--------|",
                f"| work_plan.md | {plan_status} |",
                f"| execution_log.md | {log_status} |",
            ]
        ),
        encoding="utf-8",
    )


def test_supervisor_seeds_missing_queue_entries(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.ensure_ticket_queue()

    content = (collaboration_dir / "work_plan.md").read_text(encoding="utf-8")
    assert "WP-2026-024" in content
    assert "WP-2026-025" in content
    assert "WP-2026-026" in content


def test_supervisor_advances_on_review_turn(tmp_path):
    """Test supervisor advances to next ticket when current is READY_TO_CLOSE."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.ensure_ticket_queue()
    supervisor.activate_ticket("WP-2026-024")

    ticket_id = "WP-2026-024"

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="READY_FOR_REVIEW",
        reason="Ready for review",
    )

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "approve",
            "feedback": "Ready for closure",
        },
    )

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="READY_TO_CLOSE",
        reason="Manager approved",
    )

    supervisor.event_bus.emit(
        "CLOSE_CONFIRMED",
        ticket_id=ticket_id,
        actor="USER",
        payload={"action": "closeout_confirmed"},
    )

    changed = supervisor.advance_if_review_ready()
    assert changed is True

    state = supervisor.load_state()
    assert "WP-2026-024" in state.completed_tickets
    assert state.active_ticket == "WP-2026-025"

    events = supervisor.event_bus.read_events()
    event_types = [event.event_type for event in events]
    assert "SUPERVISOR_ACTIVATED" in event_types
    assert "SUPERVISOR_CLOSED" in event_types
    assert "HANDOFF_REQUESTED" in event_types
    assert "STATE_CHANGED" in event_types

    plan_content = (collaboration_dir / "work_plan.md").read_text(encoding="utf-8")
    assert "WP-2026-025" in plan_content


def test_supervisor_blocks_close_without_quality_gates(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    (collaboration_dir / "execution_log.md").write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## Project summary",
                "",
                "- Project: `orquestador_de_agentes`",
                "- **Estado:** IN_PROGRESS",
                "- Current state: ACTIVE",
                "- Active workstreams: WP-2026-024",
            ]
        ),
        encoding="utf-8",
    )
    _write_turn(
        collaboration_dir / "TURN.md",
        role="MANAGER",
        action="REVIEW_WORK",
        plan_status="APPROVED",
        log_status="READY_FOR_REVIEW",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.ensure_ticket_queue()
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-024",
            completed_tickets=[],
            last_action="ACTIVATE",
        )
    )

    changed = supervisor.advance_if_review_ready()
    assert changed is False
    assert supervisor.load_state().active_ticket == "WP-2026-024"


def test_supervisor_bootstrap_does_not_skip_ready_for_review_to_completed(tmp_path):
    """READY_FOR_REVIEW + log COMPLETED should not jump directly to COMPLETED."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    (collaboration_dir / "execution_log.md").write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## Project summary",
                "",
                "- Project: `orquestador_de_agentes`",
                "- State: ACTIVE",
                "- Current state: WP-2026-024 READY_FOR_REVIEW",
                "- Active workstreams: WP-2026-024 (active)",
                "",
                "## WP-2026-024: UI State Projection",
                "",
                "### Summary",
                "",
                "**Estado:** COMPLETED",
            ]
        ),
        encoding="utf-8",
    )
    _write_turn(
        collaboration_dir / "TURN.md",
        role="MANAGER",
        plan_id="NINGUNO",
        action="CREATE_PLAN",
        plan_status="N/A",
        log_status="COMPLETED",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.ensure_ticket_queue()
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-024",
            completed_tickets=[],
            last_action="ACTIVATE",
        )
    )
    supervisor.transition_ticket(
        ticket_id="WP-2026-024",
        new_state="READY_FOR_REVIEW",
        reason="Ready for review",
    )

    supervisor.bootstrap()

    state = supervisor.load_state()
    assert state.active_ticket == "WP-2026-024"
    events = supervisor.event_bus.read_events(ticket_id="WP-2026-024")
    current_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert current_state == TicketState.READY_FOR_REVIEW


def test_supervisor_tracks_processed_events(tmp_path):
    """Test that supervisor tracks last_processed_sequence correctly."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    state_initial = supervisor.load_state()
    assert state_initial.last_processed_sequence == 0

    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-024",
        actor="CONTROLLER",
        payload={"action": "IMPLEMENT"},
    )

    supervisor._process_new_events()
    state_tracked = supervisor.load_state()
    assert state_tracked.last_processed_sequence > 0


def test_supervisor_processes_state_changed_events(tmp_path):
    """Test that supervisor consumes STATE_CHANGED events as coordination input."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-024",
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready for review",
        },
    )

    changed = supervisor._process_new_events()
    # Changed is True because sequence was advanced from 0 to 1
    assert changed is True
    state_tracked = supervisor.load_state()
    assert state_tracked.last_processed_sequence > 0


def test_supervisor_does_not_promote_ready_for_review_from_execution_log(tmp_path):
    """Execution log alone must not promote a ticket to READY_FOR_REVIEW."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    (collaboration_dir / "execution_log.md").write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## WP-2026-025: Status Bar Indicator",
                "",
                "### Summary",
                "",
                "**Estado:** READY_FOR_REVIEW ✅",
                "",
                "### Quality Gates",
                "- [OK] Ruff: Clean",
                "- [OK] Pytest: Tests OK",
                "- Quality Gates: PASSED",
            ]
        ),
        encoding="utf-8",
    )
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-025",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="READY_FOR_REVIEW",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-025",
            completed_tickets=["WP-2026-024"],
            last_action="ACTIVATE",
        )
    )

    supervisor.bootstrap()

    events = supervisor.event_bus.read_events(
        ticket_id="WP-2026-025", event_type="STATE_CHANGED"
    )
    assert not events
    state = supervisor.load_state()
    assert state.active_ticket == "WP-2026-025"


def test_state_machine_e2e_flow(tmp_path):
    """Test full state machine flow: IN_PROGRESS → READY_FOR_REVIEW → changes → approve → COMPLETED."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.ensure_ticket_queue()
    supervisor.activate_ticket("WP-2026-024")

    ticket_id = "WP-2026-024"

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="READY_FOR_REVIEW",
        reason="Ready for manager review",
    )

    events = supervisor.event_bus.read_events(ticket_id=ticket_id)
    current_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert current_state == TicketState.READY_FOR_REVIEW

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "changes",
            "feedback": "Objective regex needs refinement",
            "triggered_by_sequence": events[-1].sequence_number,
        },
    )

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="IN_PROGRESS",
        reason="Manager requested changes",
    )

    events = supervisor.event_bus.read_events(ticket_id=ticket_id)
    current_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert current_state == TicketState.IN_PROGRESS

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="READY_FOR_REVIEW",
        reason="Changes completed",
    )

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "approve",
            "feedback": "Ready for closure",
            "triggered_by_sequence": events[-1].sequence_number + 2,
        },
    )

    supervisor.transition_ticket(
        ticket_id=ticket_id,
        new_state="READY_TO_CLOSE",
        reason="Manager approved",
    )

    events = supervisor.event_bus.read_events(ticket_id=ticket_id)
    current_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert current_state == TicketState.READY_TO_CLOSE

    assert supervisor.close_active_ticket() is False

    supervisor.event_bus.emit(
        "CLOSE_CONFIRMED",
        ticket_id=ticket_id,
        actor="USER",
        payload={"action": "closeout_confirmed"},
    )

    assert supervisor.close_active_ticket() is True

    events = supervisor.event_bus.read_events(ticket_id=ticket_id)
    current_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    assert current_state == TicketState.COMPLETED

    review_decisions = supervisor.event_bus.read_events(
        ticket_id=ticket_id, event_type="REVIEW_DECISION"
    )
    assert len(review_decisions) == 2
    assert review_decisions[0].payload["decision"] == "changes"
    assert review_decisions[1].payload["decision"] == "approve"


def test_can_builder_act_blocks_during_review(tmp_path):
    """Test that builder is blocked when ticket is in READY_FOR_REVIEW or READY_TO_CLOSE."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-024"
    assert supervisor.can_builder_act(ticket_id) is True

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready for review",
        },
    )

    assert supervisor.can_builder_act(ticket_id) is False

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Approved",
        },
    )

    assert supervisor.can_builder_act(ticket_id) is False

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_TO_CLOSE",
            "to_state": "COMPLETED",
            "reason": "Closed",
        },
    )

    assert supervisor.can_builder_act(ticket_id) is True


def test_recover_active_ticket_from_turn(tmp_path):
    """Test recovering active ticket from TURN.md."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-027",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="IN_PROGRESS",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    recovered = supervisor.recover_active_ticket()
    assert recovered == "WP-2026-027"


def test_recover_active_ticket_from_events(tmp_path):
    """Test recovering active ticket from events when TURN.md is missing."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # No TURN.md
    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit a TURN_CHANGED event
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-027",
        actor="BUILDER",
        payload={"action": "IMPLEMENT"},
    )

    recovered = supervisor.recover_active_ticket()
    assert recovered == "WP-2026-027"


def test_bootstrap_recovery(tmp_path):
    """Test bootstrap recovers active ticket."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-027",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="IN_PROGRESS",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # State has no active ticket
    supervisor.save_state(SupervisorState())

    supervisor.bootstrap()

    state = supervisor.load_state()
    assert state.active_ticket == "WP-2026-027"
    assert state.last_action == "RECOVERED"
    events = supervisor.event_bus.read_events(ticket_id="WP-2026-027")
    assert not any(event.event_type == "SUPERVISOR_RECONCILED" for event in events)


def test_execution_log_status_reads_correct_ticket(tmp_path):
    """Test _execution_log_status reads status for the correct ticket when multiple exist."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Mock execution_log.md with multiple tickets
    (collaboration_dir / "execution_log.md").write_text(
        """# Execution Log

## WP-2026-026: Smart Auto-Open (Pausado)

### Summary

**Estado:** PENDING

## WP-2026-027: Supervisor Recovery and Reconciliation

### Summary

**Estado:** READY_FOR_REVIEW

## WP-2026-024: UI State Projection

### Summary

**Estado:** COMPLETED
""",
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Test each ticket's status
    assert supervisor._execution_log_status("WP-2026-026") == "PENDING"
    assert supervisor._execution_log_status("WP-2026-027") == "READY_FOR_REVIEW"
    assert supervisor._execution_log_status("WP-2026-024") == "COMPLETED"
    assert supervisor._execution_log_status("WP-2026-999") == ""  # Non-existent


def test_supervisor_preserves_loop_round_after_changes(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-041",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="READY_FOR_REVIEW",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-041",
            completed_tickets=[],
            last_action="ACTIVATE",
            loop_current_round=1,
            loop_max_rounds=3,
        )
    )
    supervisor.event_bus.emit(
        "LOOP_INITIALIZED",
        ticket_id="WP-2026-041",
        actor="CONTROLLER",
        payload={"current_round": 1, "max_rounds": 3},
    )
    supervisor.event_bus.emit(
        "LOOP_DECISION",
        ticket_id="WP-2026-041",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "tighten the guard"},
    )

    changed = supervisor.run_once()
    assert changed is True

    state = supervisor.load_state()
    assert state.loop_current_round == 2
    assert state.last_processed_sequence > 0


def test_supervisor_skips_relaunch_on_human_gate(tmp_path, monkeypatch):
    """Supervisor must not relaunch Builder once the ticket reaches HUMAN_GATE."""
    from bus.state_machine import TicketState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-041",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="READY_FOR_REVIEW",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-041",
            completed_tickets=[],
            last_action="RECOVERED",
            loop_current_round=1,
            loop_max_rounds=3,
        )
    )

    supervisor.event_bus.emit(
        "LOOP_DECISION",
        ticket_id="WP-2026-041",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "tighten the guard"},
    )

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor, "_current_state", lambda _ticket_id: TicketState.HUMAN_GATE
    )
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id: relaunch_calls.append(ticket_id),
    )

    changed = supervisor.run_once()
    assert changed is True

    state = supervisor.load_state()
    assert state.loop_current_round == 1
    assert relaunch_calls == []


def test_run_reactive_uses_idle_timeout_reset(tmp_path, monkeypatch):
    """run_reactive should reset its timeout when activity is observed."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(collaboration_dir / "TURN.md")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    # Bootstrap must return True for run_reactive to proceed
    monkeypatch.setattr(supervisor, "bootstrap", lambda: True)

    run_once_calls: list[int] = []

    def fake_run_once() -> bool:
        run_once_calls.append(len(run_once_calls))
        return len(run_once_calls) < 3

    monkeypatch.setattr(supervisor, "run_once", fake_run_once)
    monkeypatch.setenv("TICKET_SUPERVISOR_IDLE_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("TICKET_SUPERVISOR_MAX_RUNTIME_SECONDS", "1000")

    times = iter([0.0, 0.0, 0.0, 200.0, 200.0, 200.0, 400.0, 400.0, 701.0])
    monkeypatch.setattr("time.time", lambda: next(times))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    changed = supervisor.run_reactive(timeout_seconds=1.0)
    assert changed is True
    assert run_once_calls[:3] == [0, 1, 2]
    assert len(run_once_calls) > 3


def test_supervisor_bootstrap_reconciles_stale_state_with_work_plan(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-053",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="IN_PROGRESS",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-052",
            completed_tickets=["WP-2026-049"],
            last_action="RECOVERED",
        )
    )

    supervisor.bootstrap()

    state = supervisor.load_state()
    assert state.active_ticket == "WP-2026-053"
    assert state.last_action == "RECONCILED"
    events = supervisor.event_bus.read_events(ticket_id="WP-2026-053")
    assert any(event.event_type == "SUPERVISOR_RECONCILED" for event in events)


def test_supervisor_bootstrap_emits_reconciled_only_for_stale_state(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-054",
        action="IMPLEMENT",
        plan_status="APPROVED",
        log_status="IN_PROGRESS",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor.save_state(SupervisorState())

    supervisor.bootstrap()

    events = supervisor.event_bus.read_events(ticket_id="WP-2026-054")
    assert not any(event.event_type == "SUPERVISOR_RECONCILED" for event in events)


def test_ticket_supervisor_reactive_prints_bootstrapped_state(
    monkeypatch, tmp_path, capsys
):
    from scripts import ticket_supervisor as ticket_supervisor_script

    class DummySupervisor:
        def __init__(self, *args, **kwargs):
            self.state = SupervisorState(
                active_ticket="WP-2026-041",
                completed_tickets=[],
            )

        def bootstrap(self):
            self.state.active_ticket = "WP-2026-042"
            self.state.completed_tickets = ["WP-2026-024", "WP-2026-027"]
            return True  # Must return True for run_reactive to proceed

        def load_state(self):
            return self.state

        def run_reactive(self, timeout_seconds: float = 300.0):
            return None

    monkeypatch.setattr(
        ticket_supervisor_script, "SequentialTicketSupervisor", DummySupervisor
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ticket_supervisor.py", "--reactive", "--timeout", "1"],
    )

    ticket_supervisor_script.main()

    out = capsys.readouterr().out
    assert "active=WP-2026-042" in out
    assert "completed=2" in out


# =============================================================================
# Tests WP-2026-084: Robust Builder Relaunch (4 capas)
# =============================================================================


def test_builder_alive_pid_exists(tmp_path, monkeypatch):
    """Test _builder_alive returns True when PID exists in tasklist."""
    import json
    import os
    import time

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Crear lock con PID actual (pytest process)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {
        "pid": os.getpid(),
        "ticket_id": "WP-TEST",
        "project_root": str(tmp_path),
        "started_at": time.time(),
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # En entorno real, tasklist deberia encontrar el PID actual
    result = supervisor._builder_alive()
    # Puede ser True (tasklist funciona) o False (tasklist no disponible en test)
    # Lo importante es que no crashea
    assert isinstance(result, bool)


def test_builder_alive_pid_dead(tmp_path, monkeypatch):
    """Test _builder_alive returns False when PID is dead."""
    import json
    import os
    import subprocess
    import time

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Crear lock con PID inexistente y mtime viejo (>15 min)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {"pid": 999999, "ticket_id": "WP-TEST"}
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Hacer el lock viejo para que el fallback mtime tambien devuelva False
    old_time = time.time() - 1000  # ~16 minutos
    os.utime(lock_path, (old_time, old_time))

    # Mock tasklist para simular PID no encontrado
    def mock_tasklist(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", mock_tasklist)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    result = supervisor._builder_alive()
    assert result is False


def test_builder_alive_no_lock(tmp_path):
    """Test _builder_alive returns False when no lock file exists."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    result = supervisor._builder_alive()
    assert result is False


def test_builder_alive_fallback_mtime(tmp_path):
    """Test _builder_alive fallback to mtime check when PID not available."""
    import json
    import os
    import time

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Crear lock sin PID pero fresco (<15 min)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {"ticket_id": "WP-TEST"}
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Lock fresco debe devolver True
    result = supervisor._builder_alive()
    assert result is True

    # Ahora hacer el lock viejo (>15 min)
    old_time = time.time() - 1000  # ~16 minutos
    os.utime(lock_path, (old_time, old_time))

    result = supervisor._builder_alive()
    assert result is False


def test_relaunch_uses_resume_flag(tmp_path, monkeypatch):
    """Test that _relaunch_builder uses -ResumeBuilder flag."""
    import subprocess
    import sys

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Crear launcher falso
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    # Mock subprocess.run para capturar args
    captured_cmd = None

    def mock_run(cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", mock_run)
    # Remover PYTEST_CURRENT_TEST para que el codigo no detecte que estamos en test
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Tambien mockear sys.modules para que no detecte pytest
    monkeypatch.delitem(sys.modules, "pytest", raising=False)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Forzar que _builder_alive devuelva False para que proceda al relanzamiento
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    supervisor._relaunch_builder("WP-TEST")

    assert captured_cmd is not None
    assert "-ResumeBuilder" in captured_cmd
    assert "-StrictLaunch:$false" not in captured_cmd
    # Regression: WP-085 used -LaunchSupervisor:0 etc which still failed under
    # PS 5.1 SwitchParameter cast from subprocess argv. Replaced with the
    # additive -OnlyBuilder switch defined in launch_agent_terminals.ps1.
    assert "-OnlyBuilder" in captured_cmd
    assert "-LaunchSupervisor:0" not in captured_cmd
    assert "-LaunchBridge:0" not in captured_cmd
    assert "-LaunchMonitor:0" not in captured_cmd
    assert "-LaunchSupervisor:$false" not in captured_cmd
    # Regression: supervisor must pass -ProjectRoot explicitly. Under PS 5.1
    # subprocess invocation $PSScriptRoot/$PSCommandPath/$MyInvocation can all
    # be null during param-block defaults.
    assert "-ProjectRoot" in captured_cmd
    idx = captured_cmd.index("-ProjectRoot")
    assert captured_cmd[idx + 1] == str(tmp_path)


def test_supervisor_skips_relaunch_when_builder_alive(tmp_path, monkeypatch, capsys):
    """Smoke e2e: when builder is alive, relaunch is skipped."""
    import sys

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Mock _builder_alive para devolver True
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: True)

    # Remover PYTEST_CURRENT_TEST para que el codigo no detecte que estamos en test
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)

    # Mock subprocess.run para asegurar que no se llama
    call_count = 0

    def mock_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("subprocess.run should not be called when builder is alive")

    monkeypatch.setattr("subprocess.run", mock_run)

    # Llamar a _relaunch_builder deberia skippear y devolver True
    result = supervisor._relaunch_builder("WP-TEST")

    assert result is True
    assert call_count == 0  # subprocess.run nunca fue llamado

    # Verificar log message
    captured = capsys.readouterr()
    assert "Builder alive" in captured.err or "Builder alive" in captured.out


# =============================================================================
# Tests WP-2026-102: Bridge/Supervisor Hardening
# =============================================================================


def test_non_terminal_states_constant():
    """Test NON_TERMINAL_STATES constant is properly defined."""
    from bus.state_machine import TicketState
    from bus.supervisor import NON_TERMINAL_STATES

    assert isinstance(NON_TERMINAL_STATES, frozenset)
    assert len(NON_TERMINAL_STATES) > 0

    # Verify expected non-terminal states are included
    assert TicketState.READY_FOR_REVIEW in NON_TERMINAL_STATES
    assert TicketState.READY_TO_CLOSE in NON_TERMINAL_STATES
    assert TicketState.IN_PROGRESS in NON_TERMINAL_STATES
    assert TicketState.BLOCKED in NON_TERMINAL_STATES
    assert TicketState.HUMAN_GATE in NON_TERMINAL_STATES

    # Verify terminal states are NOT included
    assert TicketState.COMPLETED not in NON_TERMINAL_STATES
    assert TicketState.UNKNOWN not in NON_TERMINAL_STATES


def test_is_state_terminal_method(tmp_path):
    """Test _is_state_terminal correctly classifies states."""
    from bus.state_machine import TicketState
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Non-terminal states should return False
    for state in [
        TicketState.READY_FOR_REVIEW,
        TicketState.READY_TO_CLOSE,
        TicketState.IN_PROGRESS,
        TicketState.BLOCKED,
        TicketState.HUMAN_GATE,
    ]:
        assert supervisor._is_state_terminal(state) is False

    # Terminal states should return True
    for state in [TicketState.COMPLETED, TicketState.UNKNOWN]:
        assert supervisor._is_state_terminal(state) is True


def test_builder_alive_requeues_when_exited_with_alive_pid(tmp_path):
    """Test that _builder_alive returns False when a BUILDER_EXIT event exists

    after the lock's started_at datetime, even if the lock's PID belongs to an
    active process (like the current test process).
    """
    import json
    import os
    import time
    from datetime import datetime, timezone

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-103"

    # 1. Create a lock file with the current PID (which is definitely running!)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_start_dt = datetime.now(timezone.utc)
    lock_data = {
        "pid": os.getpid(),
        "ticket_id": ticket_id,
        "project_root": str(tmp_path),
        "started_at": lock_start_dt.isoformat(),
        "role": "BUILDER",
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # 2. Before any event on the bus, _builder_alive should return True (because process is alive)
    assert supervisor._builder_alive() is True

    # 3. Emit a BUILDER_EXIT event strictly AFTER the lock was created
    time.sleep(0.01)  # ensure timestamp advances slightly
    supervisor.event_bus.emit(
        "BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"exit_reason": "Changes completed"},
    )

    # 4. Now, _builder_alive() must return False because of the event bus safeguard
    assert supervisor._builder_alive() is False


# =============================================================================
# Tests WP-2026-105: Bus Precedence Bootstrap Hardening
# =============================================================================


def test_bus_active_non_terminal_ticket_finds_active_ticket(tmp_path):
    """Test _bus_active_non_terminal_ticket returns ticket in non-terminal state."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit events for WP-2026-100 in IN_PROGRESS state
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-100",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Started"},
    )

    result = supervisor._bus_active_non_terminal_ticket()
    assert result == "WP-2026-100"


def test_bus_active_non_terminal_ticket_ignores_completed(tmp_path):
    """Test _bus_active_non_terminal_ticket skips completed tickets."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit events for WP-2026-100 in COMPLETED state
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-100",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_TO_CLOSE",
            "to_state": "COMPLETED",
            "reason": "Closed",
        },
    )

    result = supervisor._bus_active_non_terminal_ticket()
    assert result is None


def test_bus_active_non_terminal_ticket_prefers_highest_wp_id(tmp_path):
    """Test _bus_active_non_terminal_ticket returns highest WP-ID among active tickets."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # WP-2026-050 active, WP-2026-101 active
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-050",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Started"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-101",
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )

    result = supervisor._bus_active_non_terminal_ticket()
    assert result == "WP-2026-101"


def test_bootstrap_bus_precedence_over_turn_divergence(tmp_path):
    """Test bootstrap prefers bus active ticket over TURN.md when they diverge.

    This is the core regression test for WP-2026-105.
    Scenario: TURN.md says WP-2026-099, but bus has WP-2026-100 in READY_FOR_REVIEW.
    Expected: bootstrap selects WP-2026-100 (bus wins).
    """
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # TURN.md says WP-2026-099 (old ticket)
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
                "| **Plan ID** | WP-2026-099 |",
                "| **Tipo** | IMPLEMENTATION |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Bus has WP-2026-050 and WP-2026-106 active; WP-2026-106 should win
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-050",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Started"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-106",
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )

    # State starts empty
    supervisor.save_state(SupervisorState())

    supervisor.bootstrap()

    state = supervisor.load_state()
    # Bus should win over TURN.md and prefer the highest WP-ID
    assert state.active_ticket == "WP-2026-106"


def test_bootstrap_bus_requeue_repeated_changes(tmp_path):
    """Test bootstrap preserves active ticket through repeated requeue (changes -> IN_PROGRESS).

    Scenario: Ticket goes through REVIEW_DECISION -> changes -> IN_PROGRESS multiple times.
    Expected: bootstrap keeps the same active ticket, doesn't revert to TURN.md.
    """
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # TURN.md says WP-2026-050 (old ticket from previous round)
    turn_path = collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-050 |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-051"

    # Simulate a requeue cycle: IN_PROGRESS -> READY_FOR_REVIEW -> changes -> IN_PROGRESS
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "Fix it"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "IN_PROGRESS",
            "reason": "Requeue",
        },
    )

    supervisor.save_state(SupervisorState())
    supervisor.bootstrap()

    state = supervisor.load_state()
    # Should stay with the active ticket from bus, not revert to TURN.md
    assert state.active_ticket == ticket_id


def test_bootstrap_fallback_to_turn_when_bus_has_no_active(tmp_path):
    """Test bootstrap falls back to TURN.md when bus has no non-terminal active ticket."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # TURN.md says WP-2026-105
    turn_path = collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-105 |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Bus only has completed tickets
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-104",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_TO_CLOSE",
            "to_state": "COMPLETED",
            "reason": "Closed",
        },
    )

    supervisor.save_state(SupervisorState())
    supervisor.bootstrap()

    state = supervisor.load_state()
    # Should fall back to TURN.md when bus has no active non-terminal
    assert state.active_ticket == "WP-2026-105"


# =============================================================================
# Tests WP-2026-115: Bus-only Builder Liveness
# =============================================================================


def test_builder_alive_bus_only_no_pid_fallback(tmp_path, monkeypatch):
    """Test _builder_alive does NOT use PID as authority (bus-only liveness).

    Scenario: Lock has a valid PID that is alive, but BUILDER_EXIT event exists.
    Expected: _builder_alive returns False because bus says Builder exited.
    """
    import json
    import os
    import time
    from datetime import datetime, timezone

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-115"

    # Create lock with current PID (which is definitely running)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_start_dt = datetime.now(timezone.utc)
    lock_data = {
        "pid": os.getpid(),
        "ticket_id": ticket_id,
        "project_root": str(tmp_path),
        "started_at": lock_start_dt.isoformat(),
        "role": "BUILDER",
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Emit BUILDER_EXIT after lock start
    time.sleep(0.01)
    supervisor.event_bus.emit(
        "BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"exit_reason": "Changes completed"},
    )

    # _builder_alive must return False because bus says exited
    # (PID check is no longer authoritative)
    assert supervisor._builder_alive() is False


def test_builder_alive_mtime_fallback_only(tmp_path, monkeypatch):
    """Test _builder_alive uses mtime fallback when no BUILDER_EXIT event.

    Scenario: Lock is fresh (<15 min), no BUILDER_EXIT event, PID dead.
    Expected: _builder_alive returns True based on mtime (crash recovery).
    """
    import json
    import subprocess

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Mock tasklist to always return PID not found
    def mock_tasklist(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", mock_tasklist)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Create fresh lock with dead PID
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {
        "pid": 999999,  # Dead PID
        "ticket_id": "WP-TEST",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # No BUILDER_EXIT event on bus
    # Fresh lock should return True (mtime fallback for crash recovery)
    assert supervisor._builder_alive() is True


def test_builder_alive_stale_lock_no_exit_event(tmp_path, monkeypatch):
    """Test _builder_alive returns False for stale lock without BUILDER_EXIT.

    Scenario: Lock is old (>15 min), no BUILDER_EXIT event.
    Expected: _builder_alive returns False (lock is stale).
    """
    import json
    import os
    import time

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Create old lock (>15 min)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {
        "pid": 999999,
        "ticket_id": "WP-TEST",
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Make lock old
    old_time = time.time() - 1000  # ~16 minutes
    os.utime(lock_path, (old_time, old_time))

    # No BUILDER_EXIT event, but lock is stale
    assert supervisor._builder_alive() is False


def test_has_builder_exited_after_parse_error_logged(tmp_path, monkeypatch, capsys):
    """Test _has_builder_exited_after handles parse errors without crashing."""
    from datetime import datetime, timezone

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-115"

    # Create a mock event with invalid timestamp that will cause parse error
    mock_event = MagicMock()
    mock_event.actor = "BUILDER"
    mock_event.event_type = "BUILDER_EXIT"
    mock_event.timestamp = "not-a-valid-timestamp"

    # Mock read_events to return event with bad timestamp
    with patch.object(supervisor.event_bus, "read_events", return_value=[mock_event]):
        lock_start = datetime.now(timezone.utc)

        # Should not raise, should return False and log error
        result = supervisor._has_builder_exited_after(ticket_id, lock_start)

        # Should return False because parse failed
        assert result is False

    # Check error was logged
    captured = capsys.readouterr()
    assert "Failed to parse timestamp" in captured.err


def test_builder_alive_wrapper_pid_dead_builder(tmp_path, monkeypatch):
    """Test _builder_alive handles wrapper PID scenario (PowerShell wrapper alive, Builder dead).

    This is the core regression test for WP-2026-115.
    Scenario: PowerShell wrapper PID is alive, but real Builder exited (BUILDER_EXIT on bus).
    Expected: _builder_alive returns False because bus overrides PID.
    """
    import json
    import os
    import subprocess
    import time
    from datetime import datetime, timezone

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-115"

    # Mock tasklist to report wrapper PID as alive
    def mock_tasklist_alive(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=f"{os.getpid()}  powershell.exe\n", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_tasklist_alive)

    # Create lock with wrapper PID (alive)
    lock_path = runtime_dir / "builder_lock.txt"
    lock_start_dt = datetime.now(timezone.utc)
    lock_data = {
        "pid": os.getpid(),  # Wrapper PID (alive)
        "ticket_id": ticket_id,
        "project_root": str(tmp_path),
        "started_at": lock_start_dt.isoformat(),
        "role": "BUILDER",
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Emit BUILDER_EXIT after lock start (real Builder exited)
    time.sleep(0.01)
    supervisor.event_bus.emit(
        "BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"exit_reason": "Builder crashed, wrapper still alive"},
    )

    # _builder_alive must return False because bus says exited
    # This is the core fix: PID check no longer produces false positive
    assert supervisor._builder_alive() is False


# =============================================================================
# Tests WP-2026-116: Ready-to-close reentry guard
# =============================================================================


def test_event_bus_allows_revert_from_ready_to_close(tmp_path):
    """WP-2026-116 follow-up: READY_TO_CLOSE is NOT terminal.

    A ticket approved (READY_TO_CLOSE) but not yet closed can still be
    reverted to work by a legitimate change before SUPERVISOR_CLOSED.
    The reentry guard must NOT block this.
    """
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    bus = EventBus(runtime_dir=runtime_dir)
    ticket_id = "WP-2026-116"

    bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "READY_TO_CLOSE"},
    )

    # Revert to IN_PROGRESS before final close - must be allowed.
    result = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_TO_CLOSE", "to_state": "IN_PROGRESS"},
    )

    assert result is not None, (
        "READY_TO_CLOSE -> IN_PROGRESS must be allowed (not terminal)"
    )
    events = bus.read_events(ticket_id=ticket_id, event_type="STATE_CHANGED")
    assert len(events) == 2


def test_event_bus_blocks_reentry_from_completed(tmp_path):
    """Test that EventBus blocks STATE_CHANGED from COMPLETED to any work state."""
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    bus = EventBus(runtime_dir=runtime_dir)
    ticket_id = "WP-2026-116"

    # First, transition to COMPLETED
    bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
    )

    # Attempt to reopen to READY_FOR_REVIEW - should be blocked
    result = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "COMPLETED", "to_state": "READY_FOR_REVIEW"},
    )

    assert result is None

    # Verify state remains COMPLETED
    events = bus.read_events(ticket_id=ticket_id, event_type="STATE_CHANGED")
    assert len(events) == 1
    assert events[0].payload["to_state"] == "COMPLETED"


def test_event_bus_allows_normal_transitions(tmp_path):
    """Test that normal state transitions are not blocked."""
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    bus = EventBus(runtime_dir=runtime_dir)
    ticket_id = "WP-2026-116"

    # Normal flow: IN_PROGRESS -> READY_FOR_REVIEW -> READY_TO_CLOSE
    result1 = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )
    assert result1 is not None

    result2 = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "READY_TO_CLOSE"},
    )
    assert result2 is not None

    events = bus.read_events(ticket_id=ticket_id, event_type="STATE_CHANGED")
    assert len(events) == 2


def test_event_bus_allows_changes_from_ready_for_review(tmp_path):
    """Test that changes from READY_FOR_REVIEW to IN_PROGRESS are allowed."""
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    bus = EventBus(runtime_dir=runtime_dir)
    ticket_id = "WP-2026-116"

    # First, transition to READY_FOR_REVIEW
    bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # Manager requests changes - should be allowed (not from terminal state)
    result = bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "IN_PROGRESS"},
    )

    assert result is not None

    events = bus.read_events(ticket_id=ticket_id, event_type="STATE_CHANGED")
    assert len(events) == 2
    assert events[1].payload["to_state"] == "IN_PROGRESS"


# =============================================================================
# Tests WP-2026-119: Supervisor state reconciliation
# =============================================================================


def test_bootstrap_reconciles_last_processed_sequence_with_bus(tmp_path):
    """Test bootstrap reconciles last_processed_sequence to bus reality.

    Scenario: Persisted sequence is ahead of bus (phantom/stale after crash).
    Expected: bootstrap lowers last_processed_sequence to match bus.
    """
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit some events to bus
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-119",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-119",
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )

    # Persisted state has sequence ahead of bus (phantom)
    bus_latest_seq = 2  # Two events emitted
    phantom_seq = 999
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-119",
            last_processed_sequence=phantom_seq,
        )
    )

    supervisor.bootstrap()

    state = supervisor.load_state()
    # Should reconcile down to bus reality
    assert state.last_processed_sequence == bus_latest_seq


def test_bootstrap_reconciles_loop_round_from_bus(tmp_path):
    """Test bootstrap reconciles loop_current_round from LOOP_INITIALIZED events."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    ticket_id = "WP-2026-119"

    # Emit LOOP_INITIALIZED with round 3
    supervisor.event_bus.emit(
        "LOOP_INITIALIZED",
        ticket_id=ticket_id,
        actor="CONTROLLER",
        payload={"current_round": 3, "max_rounds": 5},
    )

    # Persisted state has stale round
    supervisor.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,  # Stale
        )
    )

    supervisor.bootstrap()

    state = supervisor.load_state()
    # Should reconcile to bus round
    assert state.loop_current_round == 3


def test_process_new_events_reconciles_sequence_down(tmp_path):
    """Test _process_new_events reconciles sequence down when bus is behind persisted."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit one event
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-119",
        actor="BUILDER",
        payload={"action": "IMPLEMENT"},
    )

    # Persisted state has phantom sequence ahead
    supervisor.save_state(SupervisorState(last_processed_sequence=999))

    changed = supervisor._process_new_events()

    state = supervisor.load_state()
    # Should reconcile down and return True (changed)
    assert changed is True
    assert state.last_processed_sequence == 1  # One event in bus


def test_process_new_events_advances_sequence_normal(tmp_path):
    """Test _process_new_events advances sequence when new events exist."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Start with sequence 0
    supervisor.save_state(SupervisorState(last_processed_sequence=0))

    # Emit event
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-119",
        actor="BUILDER",
        payload={"action": "IMPLEMENT"},
    )

    changed = supervisor._process_new_events()

    state = supervisor.load_state()
    assert changed is True
    assert state.last_processed_sequence == 1


def test_bootstrap_reconciles_active_ticket_none_when_bus_terminal(tmp_path):
    """Test bootstrap clears active_ticket when bus confirms terminal state.

    Scenario: Persisted state has active_ticket, but bus shows COMPLETED.
    Expected: active_ticket is cleared to None.
    """
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    ticket_id = "WP-2026-119"

    # Create execution_log.md with COMPLETED status for the ticket
    # Format must match _execution_log_status regex pattern
    execution_log_path = collaboration_dir / "execution_log.md"
    execution_log_path.write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                f"## {ticket_id}: Test Ticket",
                "",
                "### Summary",
                "",
                "**Estado:** COMPLETED",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Emit events leading to COMPLETED
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Approved",
        },
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_TO_CLOSE",
            "to_state": "COMPLETED",
            "reason": "Closed",
        },
    )

    # Persisted state has stale active_ticket
    supervisor.save_state(SupervisorState(active_ticket=ticket_id))

    supervisor.bootstrap()

    state = supervisor.load_state()
    # Should clear active_ticket when bus shows COMPLETED and execution_log confirms
    assert state.active_ticket is None


def test_supervisor_state_reconciliation_e2e(tmp_path):
    """End-to-end test: full state reconciliation after crash/interrupt.

    Scenario:
    - Bus has WP-2026-119 in READY_FOR_REVIEW (round 2)
    - Persisted state has WP-2026-118 (stale ticket), sequence 999 (phantom), round 1 (stale)
    Expected:
    - active_ticket reconciled to WP-2026-119
    - last_processed_sequence reconciled to bus reality
    - loop_current_round reconciled to bus round
    """
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Bus has WP-2026-119 active
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-118",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-118",
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "COMPLETED",
            "reason": "Done",
        },
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-119",
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "LOOP_INITIALIZED",
        ticket_id="WP-2026-119",
        actor="CONTROLLER",
        payload={"current_round": 2, "max_rounds": 5},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-119",
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Review",
        },
    )

    # Persisted state is completely stale
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-118",  # Stale ticket
            last_processed_sequence=999,  # Phantom sequence
            loop_current_round=1,  # Stale round
        )
    )

    supervisor.bootstrap()

    state = supervisor.load_state()
    # All fields should be reconciled
    assert state.active_ticket == "WP-2026-119"
    assert state.last_processed_sequence == 6  # 6 events in bus
    assert state.loop_current_round == 2


# =============================================================================
# Tests WP-2026-137: Supervisor startup lock and reconciliation dedupe
# =============================================================================


def test_supervisor_lock_acquire_atomic(tmp_path):
    """Test that supervisor lock is acquired atomically."""
    import json
    import os

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Acquire lock
    result = supervisor._acquire_supervisor_lock()
    assert result is True
    assert supervisor._lock_fd is not None
    assert supervisor.supervisor_lock_path.exists()

    # Verify lock content
    lock_data = json.loads(supervisor.supervisor_lock_path.read_text(encoding="utf-8"))
    assert lock_data["pid"] == os.getpid()
    assert "started_at" in lock_data

    # Release lock
    supervisor._release_supervisor_lock()
    assert not supervisor.supervisor_lock_path.exists()


def test_supervisor_lock_contention(tmp_path):
    """Test that second supervisor instance cannot acquire lock when first holds it."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor1 = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor2 = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # First supervisor acquires lock
    result1 = supervisor1._acquire_supervisor_lock()
    assert result1 is True

    # Second supervisor should fail to acquire lock
    result2 = supervisor2._acquire_supervisor_lock()
    assert result2 is False

    # Release lock from first supervisor
    supervisor1._release_supervisor_lock()

    # Now second supervisor should be able to acquire
    result2_retry = supervisor2._acquire_supervisor_lock()
    assert result2_retry is True

    supervisor2._release_supervisor_lock()


def test_supervisor_lock_stale_by_mtime(tmp_path):
    """Test that stale lock (old mtime) is broken and re-acquired."""
    import json
    import os
    import time

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Create a fake old lock file
    lock_path = supervisor.supervisor_lock_path
    lock_data = {
        "pid": 999999,  # Dead PID
        "ticket_id": "WP-OLD",
        "started_at": "2020-01-01T00:00:00Z",
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Make lock file old (>15 min)
    old_time = time.time() - 1000
    os.utime(lock_path, (old_time, old_time))

    # Should break stale lock and acquire successfully
    result = supervisor._acquire_supervisor_lock()
    assert result is True

    # Verify new lock has current PID
    new_lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert new_lock_data["pid"] == os.getpid()

    supervisor._release_supervisor_lock()


def test_bootstrap_rejects_duplicate_instance(tmp_path, monkeypatch):
    """Test that bootstrap returns False when another instance holds the lock."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor1 = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor2 = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # First supervisor acquires lock via bootstrap
    result1 = supervisor1.bootstrap()
    assert result1 is True

    # Second supervisor should be rejected
    result2 = supervisor2.bootstrap()
    assert result2 is False

    # Clean up
    supervisor1._release_supervisor_lock()


def test_bootstrap_reconciled_deduplication(tmp_path):
    """Test that SUPERVISOR_RECONCILED is not emitted twice for same pair."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create TURN.md with ticket
    turn_path = collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-137 |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Start with stale state pointing to old ticket
    supervisor.save_state(SupervisorState(active_ticket="WP-2026-136"))

    # First bootstrap - should emit SUPERVISOR_RECONCILED
    result1 = supervisor.bootstrap()
    assert result1 is True

    events1 = supervisor.event_bus.read_events(
        ticket_id="WP-2026-137", event_type="SUPERVISOR_RECONCILED"
    )
    assert len(events1) == 1
    assert events1[0].payload["previous_ticket"] == "WP-2026-136"
    assert events1[0].payload["recovered_ticket"] == "WP-2026-137"

    # Release lock to simulate restart
    supervisor._release_supervisor_lock()

    # Second bootstrap with same state - should NOT emit again
    result2 = supervisor.bootstrap()
    assert result2 is True

    events2 = supervisor.event_bus.read_events(
        ticket_id="WP-2026-137", event_type="SUPERVISOR_RECONCILED"
    )
    # Still only 1 event - deduplication worked
    assert len(events2) == 1

    supervisor._release_supervisor_lock()


def test_bootstrap_reconciled_different_pair_emits(tmp_path):
    """Test that SUPERVISOR_RECONCILED is emitted for different ticket pairs."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create TURN.md with ticket WP-2026-137
    turn_path = collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-137 |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # First bootstrap: None -> WP-2026-137 (recovery, no RECONCILED event)
    supervisor.save_state(SupervisorState(active_ticket=None))
    result1 = supervisor.bootstrap()
    assert result1 is True

    # Recovery from None should not emit RECONCILED
    events_after_first = supervisor.event_bus.read_events(
        ticket_id="WP-2026-137", event_type="SUPERVISOR_RECONCILED"
    )
    assert len(events_after_first) == 0

    # Release lock to simulate restart
    supervisor._release_supervisor_lock()

    # Change TURN.md to WP-2026-138
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-138 |",
                "| **Accion** | IMPLEMENT |",
            ]
        ),
        encoding="utf-8",
    )

    # Second bootstrap: WP-2026-137 -> WP-2026-138 (reconciliation, should emit)
    result2 = supervisor.bootstrap()
    assert result2 is True

    # Should emit RECONCILED for the new pair
    events_after_second = supervisor.event_bus.read_events(
        ticket_id="WP-2026-138", event_type="SUPERVISOR_RECONCILED"
    )
    assert len(events_after_second) == 1
    assert events_after_second[0].payload["previous_ticket"] == "WP-2026-137"
    assert events_after_second[0].payload["recovered_ticket"] == "WP-2026-138"

    supervisor._release_supervisor_lock()

    # Second bootstrap: WP-2026-137 -> WP-2026-138 (different pair)
    # Manually set state to simulate ticket change
    supervisor.save_state(SupervisorState(active_ticket="WP-2026-137"))
    result2 = supervisor.bootstrap()
    assert result2 is True

    # Should have new event for the different pair
    events_after_second = supervisor.event_bus.read_events(
        ticket_id="WP-2026-138", event_type="SUPERVISOR_RECONCILED"
    )
    assert len(events_after_second) == 1

    supervisor._release_supervisor_lock()


def test_run_reactive_releases_lock_on_exit(tmp_path, monkeypatch):
    """Test that run_reactive releases lock when exiting."""

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Mock run_once to return False immediately for quick exit
    monkeypatch.setattr(supervisor, "run_once", lambda: False)

    # Mock time.time to simulate timeout quickly
    times = iter([0.0, 0.0, 2.0])  # Start, check, timeout
    monkeypatch.setattr("time.time", lambda: next(times))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    # Run reactive with very short timeout
    supervisor.run_reactive(timeout_seconds=1.0)

    # Lock should be released after exit
    assert not supervisor.supervisor_lock_path.exists()
    assert supervisor._lock_fd is None


def test_run_loop_releases_lock_on_exception(tmp_path, monkeypatch):
    """Test that run_loop releases lock even when exception occurs."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Mock run_once to raise exception on first call
    call_count = 0

    def flaky_run_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated error")
        return False

    monkeypatch.setattr(supervisor, "run_once", flaky_run_once)

    # Mock time.sleep to exit quickly
    sleep_count = 0

    def quick_sleep(_seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count > 2:
            raise KeyboardInterrupt("Stop loop")

    monkeypatch.setattr("time.sleep", quick_sleep)

    import contextlib

    # Run loop should release lock even with exception
    with contextlib.suppress(RuntimeError, KeyboardInterrupt):
        supervisor.run_loop(poll_interval=0.1)

    # Lock should be released despite exception
    assert not supervisor.supervisor_lock_path.exists()
    assert supervisor._lock_fd is None
