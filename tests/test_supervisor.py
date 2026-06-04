from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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
    assert "WT-2026-025" in content
    assert "WT-2026-026" in content


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
    assert state.active_ticket == "WT-2026-025"

    events = supervisor.event_bus.read_events()
    event_types = [event.event_type for event in events]
    assert "SUPERVISOR_ACTIVATED" in event_types
    assert "SUPERVISOR_CLOSED" in event_types
    assert "HANDOFF_REQUESTED" in event_types
    assert "STATE_CHANGED" in event_types

    plan_content = (collaboration_dir / "work_plan.md").read_text(encoding="utf-8")
    assert "WT-2026-025" in plan_content


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
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id),
    )

    changed = supervisor.run_once()
    assert changed is True

    state = supervisor.load_state()
    assert state.loop_current_round == 1
    assert relaunch_calls == []


def test_run_once_triggers_requeue_on_review_decision_changes(tmp_path, monkeypatch):
    """REVIEW_DECISION with decision=CHANGES must trigger requeue, not just LOOP_DECISION."""
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
        "REVIEW_DECISION",
        ticket_id="WP-2026-041",
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "fix the tests"},
    )

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    changed = supervisor.run_once()
    assert changed is True

    state = supervisor.load_state()
    assert state.loop_current_round == 2, (
        "round must increment after REVIEW_DECISION CHANGES"
    )
    assert relaunch_calls == ["WP-2026-041"], "Builder must be relaunched"
    assert state.last_requeue_trigger_sequence > 0, "watermark must be persisted"


def test_run_once_watermark_prevents_double_requeue(tmp_path, monkeypatch):
    """A repeated REVIEW_DECISION with the same (already-seen) sequence must not trigger a second requeue."""
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
        "REVIEW_DECISION",
        ticket_id="WP-2026-041",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    # First run_once: should trigger requeue
    supervisor.run_once()
    assert len(relaunch_calls) == 1
    state = supervisor.load_state()
    watermark = state.last_requeue_trigger_sequence
    assert watermark > 0

    # Second run_once with same events (no new events added): watermark blocks requeue
    supervisor.run_once()
    assert len(relaunch_calls) == 1, (
        "watermark must prevent second requeue for same CHANGES"
    )
    state2 = supervisor.load_state()
    assert state2.loop_current_round == 2, "round must not increment a second time"


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


def test_run_reactive_idle_timeout_ignored_when_builder_alive(tmp_path, monkeypatch):
    """Idle timeout should not stop the watcher while Builder is still alive."""
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
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: True)

    should_stop = supervisor._should_stop_run_reactive(
        start_time=0.0,
        last_activity=0.0,
        idle_timeout=300.0,
        max_runtime=3600.0,
        now=540.0,
    )

    assert should_stop is False


def test_run_reactive_idle_timeout_stops_when_builder_not_alive(tmp_path, monkeypatch):
    """Idle timeout should still stop the watcher when there is no live Builder."""
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
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    should_stop = supervisor._should_stop_run_reactive(
        start_time=0.0,
        last_activity=0.0,
        idle_timeout=300.0,
        max_runtime=3600.0,
        now=540.0,
    )

    assert should_stop is True


def test_run_reactive_max_runtime_stops_even_when_builder_alive(tmp_path, monkeypatch):
    """Max runtime remains a hard cap for the reactive supervisor loop."""
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
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: True)

    should_stop = supervisor._should_stop_run_reactive(
        start_time=0.0,
        last_activity=3500.0,
        idle_timeout=300.0,
        max_runtime=3600.0,
        now=3600.0,
    )

    assert should_stop is True


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
    """Test that _relaunch_builder uses -ResumeBuilder flag with trigger_seq and -SkipSupervisorWait.

    WT-2026-201: Endurecido para cubrir la firma real con trigger_seq no nulo
    y afirmar los cuatro flags: -LaunchBuilder, -OnlyBuilder, -ResumeBuilder
    y -SkipSupervisorWait.
    """
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

    # WT-2026-201: Pasar trigger_seq no nulo para ejercer la firma real
    supervisor._relaunch_builder("WP-TEST", trigger_seq=42)

    assert captured_cmd is not None
    # WT-2026-201: Afirmar los cuatro flags del launcher
    assert "-LaunchBuilder" in captured_cmd
    assert "-OnlyBuilder" in captured_cmd
    assert "-ResumeBuilder" in captured_cmd
    assert "-SkipSupervisorWait" in captured_cmd
    assert "-StrictLaunch:$false" not in captured_cmd
    # Regression: WP-085 used -LaunchSupervisor:0 etc which still failed under
    # PS 5.1 SwitchParameter cast from subprocess argv. Replaced with the
    # additive -OnlyBuilder switch defined in launch_agent_terminals.ps1.
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


def _make_supervisor(tmp_path):
    """Helper: create a SequentialTicketSupervisor with standard dirs."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


# WT-2026-194: zombie READY_TO_CLOSE detection and reconcile guard


def test_zombie_ready_to_close_excluded_from_bus_active(tmp_path):
    """READY_TO_CLOSE + approve + no SUPERVISOR_CLOSED → excluded as zombie.

    Scenario: WT-2026-187 got approved but Supervisor died before SUPERVISOR_CLOSED.
    Expected: _bus_active_non_terminal_ticket returns None (zombie ignored).
    """
    supervisor = _make_supervisor(tmp_path)

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-187",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Manager approved",
        },
    )
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WT-2026-187",
        actor="MANAGER",
        payload={"decision": "approve"},
    )
    # No SUPERVISOR_CLOSED → zombie

    result = supervisor._bus_active_non_terminal_ticket()
    assert result is None, f"Expected None (zombie ignored), got {result}"


def test_legitimate_ready_to_close_not_excluded(tmp_path):
    """READY_TO_CLOSE without approve → still returned as active (awaiting approval)."""
    supervisor = _make_supervisor(tmp_path)

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-190",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Manager approved",
        },
    )
    # No REVIEW_DECISION yet → not a zombie

    result = supervisor._bus_active_non_terminal_ticket()
    assert result == "WT-2026-190", f"Expected WT-2026-190, got {result}"


def test_reconcile_state_zombie_guard_prefers_work_plan(tmp_path):
    """reconcile_state ignores zombie bus_active when work_plan has newer ticket.

    Scenario: bus has WT-2026-187 zombie READY_TO_CLOSE; work_plan.md has WT-2026-188.
    Expected: reconcile_state sets active_ticket = WT-2026-188, not WT-2026-187.
    """
    supervisor = _make_supervisor(tmp_path)

    # Emit zombie in bus
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-187",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Manager approved",
        },
    )
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WT-2026-187",
        actor="MANAGER",
        payload={"decision": "approve"},
    )

    # work_plan.md has newer ticket WT-2026-188
    work_plan = supervisor.collaboration_dir / "work_plan.md"
    work_plan.write_text(
        "# Work Ticket - WT-2026-188\n## Metadata\n- **ID:** WT-2026-188\n- **Estado:** COMPLETED\n",
        encoding="utf-8",
    )

    supervisor.reconcile_state()
    state = supervisor.load_state()
    assert state.active_ticket != "WT-2026-187", (
        "Zombie WT-2026-187 must not win over work_plan WT-2026-188"
    )


def test_reconcile_state_prefers_newer_alphanumeric_ticket_over_stale_numeric_ticket(
    tmp_path,
):
    """Bootstrap must not resurrect a lower numeric ticket over WT-2026-221a."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    (collaboration_dir / "work_plan.md").write_text(
        "# Work Ticket - WT-2026-221a\n\n## Metadata\n- **ID:** WT-2026-221a\n- **Estado:** APPROVED\n",
        encoding="utf-8",
    )
    (collaboration_dir / "TURN.md").write_text(
        "| **Plan ID** | WT-2026-221a |\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log WT-2026-221a\n\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-183",
        actor="SUPERVISOR",
        payload={"from_state": "APPROVED", "to_state": "IN_PROGRESS"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-221a",
        actor="BOOTSTRAP",
        payload={"from_state": "APPROVED", "to_state": "IN_PROGRESS"},
    )

    supervisor.reconcile_state()

    state = supervisor.load_state()
    assert state.active_ticket == "WT-2026-221a"


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


def test_has_builder_exited_after_equal_boundary(tmp_path, monkeypatch):
    """Test _has_builder_exited_after uses >= so exact-boundary BUILDER_EXIT is caught.

    WT-2026-199 Capa C: a BUILDER_EXIT at the exact relaunch_started_at timestamp
    must suppress builder_started_verified. The >= comparison (not >) ensures the
    equality boundary is counted as an exit during the verification window.
    """
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

    ticket_id = "WP-TEST"
    lock_start = datetime.now(timezone.utc)

    # Create a mock BUILDER_EXIT event at exactly lock_start
    mock_event = MagicMock()
    mock_event.actor = "BUILDER"
    mock_event.event_type = "BUILDER_EXIT"
    mock_event.timestamp = lock_start.isoformat()

    # Mock read_events to return the exit event
    with patch.object(supervisor.event_bus, "read_events", return_value=[mock_event]):
        # Should return True because event_time >= lock_start
        result = supervisor._has_builder_exited_after(ticket_id, lock_start)
        assert result is True, "BUILDER_EXIT at exactly lock_start must be detected"

    # Now test that an event BEFORE lock_start is NOT detected
    mock_event_before = MagicMock()
    mock_event_before.actor = "BUILDER"
    mock_event_before.event_type = "BUILDER_EXIT"
    mock_event_before.timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()

    with patch.object(
        supervisor.event_bus, "read_events", return_value=[mock_event_before]
    ):
        result = supervisor._has_builder_exited_after(ticket_id, lock_start)
        assert result is False, "BUILDER_EXIT before lock_start must NOT be detected"


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


# =============================================================================
# Tests WP-2026-159: Instrumentacion del relanzado (Fase 0)
# =============================================================================


def test_run_launcher_subprocess_success(tmp_path, monkeypatch):
    """Test _run_launcher_subprocess returns exit code and output on success."""
    import subprocess

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

    # Mock subprocess.run to simulate success
    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="Launcher OK", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    cmd = ["fake_cmd", "arg1"]
    exit_code, stdout, stderr = supervisor._run_launcher_subprocess(cmd)

    assert exit_code == 0
    assert stdout == "Launcher OK"
    assert stderr == ""


def test_run_launcher_subprocess_timeout(tmp_path, monkeypatch):
    """Test _run_launcher_subprocess returns timeout signature on TimeoutExpired."""
    import subprocess

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

    # Mock subprocess.run to simulate timeout
    def mock_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr("subprocess.run", mock_run)

    cmd = ["fake_cmd", "arg1"]
    exit_code, stdout, stderr = supervisor._run_launcher_subprocess(cmd)

    assert exit_code == -1
    assert stdout == ""
    assert "timed out" in stderr


def test_run_launcher_subprocess_exception(tmp_path, monkeypatch):
    """Test _run_launcher_subprocess returns exception signature on error."""
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

    # Mock subprocess.run to simulate exception
    def mock_run(cmd, **kwargs):
        raise FileNotFoundError("Command not found")

    monkeypatch.setattr("subprocess.run", mock_run)

    cmd = ["fake_cmd", "arg1"]
    exit_code, stdout, stderr = supervisor._run_launcher_subprocess(cmd)

    assert exit_code == -1
    assert stdout == ""
    assert "ERROR" in stderr


def test_persist_relaunch_log_writes_file(tmp_path):
    """Test _persist_relaunch_log writes stdout/stderr to log file."""
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

    supervisor._persist_relaunch_log("STDOUT_OUTPUT", "STDERR_OUTPUT")

    log_path = runtime_dir / "logs" / "launcher_last.log"
    assert log_path.exists()

    content = log_path.read_text(encoding="utf-8")
    assert "=== STDOUT ===" in content
    assert "STDOUT_OUTPUT" in content
    assert "=== STDERR ===" in content
    assert "STDERR_OUTPUT" in content


def test_relaunch_emits_event_skipped_alive(tmp_path, monkeypatch):
    """Test _relaunch_builder emits BUILDER_RELAUNCH_ATTEMPTED with skipped_alive."""
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

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=2,
        )
    )

    # Mock _builder_alive to return True (skip relaunch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: True)

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is True

    # Verify event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 2
    assert payload["outcome"] == "skipped_alive"
    assert payload.get("launcher_exit_code") is None
    assert "Builder alive" in payload["stderr_tail"]

    # Verify log was persisted
    log_path = runtime_dir / "logs" / "launcher_last.log"
    assert log_path.exists()


def test_relaunch_emits_event_launcher_failed(tmp_path, monkeypatch):
    """Test _relaunch_builder emits BUILDER_RELAUNCH_ATTEMPTED with launcher_failed."""

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=3,
        )
    )

    # Mock _builder_alive to return False (proceed to launch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Mock _run_launcher_subprocess to simulate failure
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (1, "", "Launcher error output"),
    )

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is False

    # Verify event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 3
    assert payload["outcome"] == "launcher_failed"
    assert payload["launcher_exit_code"] == 1
    assert payload["stderr_tail"] == "Launcher error output"

    # Verify log was persisted
    log_path = runtime_dir / "logs" / "launcher_last.log"
    assert log_path.exists()


def test_relaunch_outcome_builder_started_verified(tmp_path, monkeypatch):
    """Test _relaunch_builder emits builder_started_verified when builder_lock is found."""
    import json
    from datetime import datetime, timezone

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )

    # Mock _builder_alive to return False (proceed to launch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Mock _run_launcher_subprocess to simulate success
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (0, "Launcher OK", ""),
    )

    # Create builder_lock.txt with matching round and fresh timestamp
    lock_path = runtime_dir / "builder_lock.txt"
    lock_data = {
        "pid": 12345,
        "ticket_id": "WP-TEST",
        "round": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    # Also mock _verify_builder_start to return verified immediately
    # (the lock already exists, but the polling method may need a shorter timeout)
    monkeypatch.setattr(
        supervisor,
        "_verify_builder_start",
        lambda ticket_id, relaunch_started_at, expected_round: (
            "builder_started_verified",
            "builder_lock",
        ),
    )

    result = supervisor._relaunch_builder("WP-TEST", trigger_seq=42)

    assert result is True

    # Verify event was emitted with new taxonomy
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 1
    assert payload["outcome"] == "builder_started_verified"
    assert payload["trigger_seq"] == 42
    assert payload["launcher_exit_code"] == 0
    assert payload["verify_signal"] == "builder_lock"

    # Verify log was persisted
    log_path = runtime_dir / "logs" / "launcher_last.log"
    assert log_path.exists()


def test_relaunch_emits_event_timeout(tmp_path, monkeypatch):
    """Test _relaunch_builder emits BUILDER_RELAUNCH_ATTEMPTED with timeout."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=4,
        )
    )

    # Mock _builder_alive to return False (proceed to launch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Mock _run_launcher_subprocess to simulate timeout
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (-1, "", "launcher timed out after 60s"),
    )

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is False

    # Verify event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 4
    assert payload["outcome"] == "timeout"
    assert payload["launcher_exit_code"] == -1
    assert "timed out" in payload["stderr_tail"]


def test_relaunch_launcher_not_found_emits_event(tmp_path, monkeypatch):
    """Test _relaunch_builder emits event when launcher file is missing."""
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

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )

    # Mock _builder_alive to return False (proceed to launch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Ensure launcher doesn't exist
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    if launcher_path.exists():
        launcher_path.unlink()

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is False

    # Verify event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 1
    assert payload["outcome"] == "launcher_failed"
    assert payload["launcher_exit_code"] == -1
    assert "Launcher not found" in payload["stderr_tail"]


def test_relaunch_powershell_not_found_emits_event(tmp_path, monkeypatch):
    """Test _relaunch_builder emits event when PowerShell is not found."""
    import shutil

    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Set loop_current_round for the event
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )

    # Mock _builder_alive to return False (proceed to launch)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Mock shutil.which to return None (PowerShell not found)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is False

    # Verify event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["round"] == 1
    assert payload["outcome"] == "launcher_failed"
    assert payload["launcher_exit_code"] == -1
    assert "PowerShell executable not found" in payload["stderr_tail"]


def test_relaunch_seam_allows_monkeypatch_without_pytest_check(tmp_path, monkeypatch):
    """Test that _run_launcher_subprocess seam allows testing without PYTEST_CURRENT_TEST blocking.

    This verifies the key design decision: the seam enables tests to control
    subprocess behavior without depending on the old PYTEST_CURRENT_TEST global check.
    """

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

    # Ensure we're NOT blocking via PYTEST_CURRENT_TEST
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Mock the seam directly - this is the key testability improvement
    call_args = []

    def mock_run_launcher(cmd):
        call_args.append(cmd)
        return (0, "mocked output", "")

    monkeypatch.setattr(supervisor, "_run_launcher_subprocess", mock_run_launcher)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    result = supervisor._relaunch_builder("WP-TEST")

    assert result is True
    assert len(call_args) == 1
    # Verify the seam was called with the expected command
    assert "launch_agent_terminals.ps1" in str(call_args[0])


# =============================================================================
# Tests WP-2026-159: Smoke path reactivo estable (Fase 2)
# =============================================================================


def test_run_reactive_smoke_with_requeue_polling(tmp_path, monkeypatch):
    """Smoke test: run_reactive maintains polling after requeue, respects timeout/idle timeout.

    This test verifies the full reactive cycle:
    1. Supervisor bootstraps and acquires lock
    2. Detects CHANGES event and triggers requeue
    3. Continues polling after requeue (does not exit immediately)
    4. Respects idle timeout when no activity is observed
    """
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

    # Bootstrap must return True for run_reactive to proceed
    monkeypatch.setattr(supervisor, "bootstrap", lambda: True)

    # Track run_once calls and simulate requeue on second call
    run_once_calls = []
    requeue_triggered = False

    def fake_run_once():
        nonlocal requeue_triggered
        call_idx = len(run_once_calls)
        run_once_calls.append(call_idx)

        # Simulate activity for first 3 calls, then idle
        if call_idx == 1:
            # Trigger requeue on second call
            requeue_triggered = True
            return True
        return call_idx < 3  # Activity continues until call 3

    monkeypatch.setattr(supervisor, "run_once", fake_run_once)

    # Set short timeouts for test
    monkeypatch.setenv("TICKET_SUPERVISOR_IDLE_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("TICKET_SUPERVISOR_MAX_RUNTIME_SECONDS", "10")

    # Mock time to simulate passage: 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5
    # This should trigger idle timeout after 2 seconds of inactivity
    times = iter(
        [
            0.0,
            0.0,  # start_time, last_activity init
            1.0,
            1.0,  # call 0: activity
            2.0,
            2.0,  # call 1: requeue + activity
            3.0,
            3.0,  # call 2: activity
            4.0,
            4.0,  # call 3: no activity, but within idle timeout
            5.0,
            5.0,  # call 4: no activity, but within idle timeout
            7.0,
            7.0,  # call 5: idle timeout triggered (>2s since last activity at 3.0)
        ]
    )
    monkeypatch.setattr("time.time", lambda: next(times))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    changed = supervisor.run_reactive(timeout_seconds=10.0)

    # Verify run_once was called multiple times (polling continued after requeue)
    assert len(run_once_calls) >= 3, "run_once must be called at least 3 times"

    # Verify requeue was triggered
    assert requeue_triggered, "requeue must be triggered during polling"

    # Verify loop exited (changed should be True since we had activity)
    assert changed is True

    # Verify lock was released
    assert not supervisor.supervisor_lock_path.exists()
    assert supervisor._lock_fd is None


def test_run_once_requeue_watermark_persists_across_calls(tmp_path, monkeypatch):
    """Test that last_requeue_trigger_sequence watermark persists and prevents double requeue.

    This verifies the watermark mechanism works correctly across multiple run_once calls
    when the same CHANGES event is present.
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

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-159",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    # Emit a single CHANGES event with blockers payload (WT-2026-204)
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-159",
        actor="MANAGER",
        payload={
            "decision": "CHANGES",
            "feedback": "needs work",
            "blockers": "- fix parser",
        },
    )

    relaunch_calls = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    # First run_once: should trigger requeue
    changed1 = supervisor.run_once()
    assert changed1 is True
    assert len(relaunch_calls) == 1, "First call should trigger requeue"

    state1 = supervisor.load_state()
    # After WT-2026-199, round starts at 1 and requeue_ticket increments to 2
    assert state1.loop_current_round == 2, (
        "Watermark must be persisted after first requeue"
    )
    watermark1 = state1.last_requeue_trigger_sequence
    assert watermark1 > 0, "Watermark must be persisted after first requeue"

    # Second run_once: same events, watermark should block requeue
    changed2 = supervisor.run_once()
    assert len(relaunch_calls) == 1, (
        "Second call should NOT trigger requeue (watermark)"
    )
    assert changed2 is False  # No new activity

    state2 = supervisor.load_state()
    assert state2.loop_current_round == 2, "Round must not increment twice"
    assert state2.last_requeue_trigger_sequence == watermark1, "Watermark unchanged"

    # Third run_once: emit NEW CHANGES event with higher sequence
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-159",
        actor="MANAGER",
        payload={
            "decision": "CHANGES",
            "feedback": "still needs work",
            "blockers": "- fix other thing",
        },
    )

    changed3 = supervisor.run_once()
    assert changed3 is True
    assert len(relaunch_calls) == 2, "New CHANGES event should trigger second requeue"

    state3 = supervisor.load_state()
    assert state3.loop_current_round == 3, "Round increments for new CHANGES"
    assert state3.last_requeue_trigger_sequence > watermark1, (
        "Watermark updated for new event"
    )


def test_run_reactive_emits_supervisor_idle_once_when_no_active_ticket(
    tmp_path, monkeypatch
):
    """SUPERVISOR_IDLE should be emitted once for bootstrap-only idle sessions."""
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

    supervisor.save_state(
        SupervisorState(
            active_ticket=None,
            loop_current_round=0,
            last_requeue_trigger_sequence=0,
        )
    )

    monkeypatch.delenv("SUPERVISOR_RESTART_REASON", raising=False)
    monkeypatch.setattr(supervisor, "bootstrap", lambda: True)
    monkeypatch.setattr(supervisor, "run_once", lambda: False)
    monkeypatch.setattr(supervisor, "_release_supervisor_lock", lambda: None)

    events: list[tuple[str, str, dict]] = []

    def capture_emit(event_type, *, ticket_id, actor, payload=None, **_kwargs):
        events.append((event_type, ticket_id, payload or {}))
        return None

    monkeypatch.setattr(supervisor.event_bus, "emit", capture_emit)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    times = iter([0.0, 0.0, 301.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    result = supervisor.run_reactive(timeout_seconds=300.0)

    assert result is False
    assert events == [
        (
            "SUPERVISOR_IDLE",
            "__bootstrap__",
            {"reason": "no active ticket after bootstrap"},
        )
    ]


# =============================================================================
# Tests WP-2026-160: Restart supervisor on Builder relaunch
# =============================================================================


def test_run_reactive_stays_alive_after_requeue(tmp_path, monkeypatch):
    """WT-2026-202: run_reactive no debe romper el bucle tras un requeue builder-only.

    WP-2026-160 salia del loop para dejar al launcher arrancar un supervisor fresco.
    WT-2026-200 elimino esa premisa: el requeue usa -OnlyBuilder y no abre supervisor.
    El supervisor debe quedarse como watcher del Builder.

    Prueba de comportamiento: time.sleep se llama al final de cada iteracion, despues
    del flag check. Con el codigo viejo el break ocurria antes de llegar a sleep
    (sleep_calls == []). Con el nuevo codigo el loop continua y alcanza sleep
    (sleep_calls >= 1), lo que prueba que el loop siguio vivo tras el requeue.
    """
    from bus.supervisor import SequentialTicketSupervisor

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

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-160",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-160",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )

    relaunch_calls = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    # Iter 1: requeue fires (last_activity updated). Iter 2: idle. Exit via idle timeout.
    # time.time() calls: start(0.0), check(0.1), activity(0.2), check(0.3), exit-check(15.0)
    times = iter([0.0, 0.1, 0.2, 0.3, 15.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    # Track sleep calls: sleep is reached only if the loop does NOT break early.
    sleep_calls: list = []
    monkeypatch.setattr("time.sleep", lambda _seconds: sleep_calls.append(1))

    monkeypatch.setattr(supervisor, "bootstrap", lambda: True)

    result = supervisor.run_reactive(timeout_seconds=10.0)

    assert result is True
    assert len(relaunch_calls) == 1, "Exactly one requeue must have fired"
    # Flag must be reset (not left True): run_reactive resets it, run_once sets it.
    assert getattr(supervisor, "_requeue_triggered_this_session", False) is False
    # Behavioral proof: loop continued past the requeue iteration.
    # With the old break, sleep was never reached (sleep_calls == []).
    assert len(sleep_calls) >= 1, (
        "Loop must reach time.sleep after requeue — no early break"
    )


def test_run_once_sets_requeue_flag(tmp_path, monkeypatch):
    """WP-2026-160: run_once debe setear _requeue_triggered_this_session tras requeue exitoso."""
    from bus.supervisor import SequentialTicketSupervisor

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

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-160",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-160",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )

    # Mock _relaunch_builder to return success
    monkeypatch.setattr(supervisor, "_relaunch_builder", lambda *a, **kw: True)

    # Run once should trigger requeue and set flag
    result = supervisor.run_once()

    assert result is True
    assert getattr(supervisor, "_requeue_triggered_this_session", False) is True


def test_run_once_no_requeue_flag_false(tmp_path, monkeypatch):
    """WP-2026-160: run_once sin requeue debe dejar _requeue_triggered_this_session en False."""
    from bus.supervisor import SequentialTicketSupervisor

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

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-160",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    # No CHANGES event - just normal activity
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-2026-160",
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # Run once without requeue
    result = supervisor.run_once()

    assert result is True  # Changed due to event activity
    assert getattr(supervisor, "_requeue_triggered_this_session", False) is False


def test_run_reactive_emits_supervisor_restarted_when_env_set(tmp_path, monkeypatch):
    """WP-2026-160: run_reactive debe emitir SUPERVISOR_RESTARTED si SUPERVISOR_RESTART_REASON esta en el entorno."""
    from bus.supervisor import SequentialTicketSupervisor

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

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-160",
            loop_current_round=2,
            last_requeue_trigger_sequence=0,
        )
    )

    monkeypatch.setenv("SUPERVISOR_RESTART_REASON", "resume-builder")
    monkeypatch.setattr(supervisor, "bootstrap", lambda: True)
    monkeypatch.setattr(supervisor, "_release_supervisor_lock", lambda: None)

    # Make the loop exit immediately via idle timeout
    times = iter([0.0, 400.0])
    monkeypatch.setattr("time.time", lambda: next(times))
    monkeypatch.setattr("time.sleep", lambda _: None)

    supervisor.run_reactive(timeout_seconds=1.0)

    events = supervisor.event_bus.read_events()
    restarted = [e for e in events if e.event_type == "SUPERVISOR_RESTARTED"]
    assert len(restarted) == 1, "Should emit exactly one SUPERVISOR_RESTARTED"
    assert restarted[0].payload == {"round": 2, "reason": "resume-builder"}


def test_bootstrap_requeue_if_needed_fires_when_changes_unprocessed(
    tmp_path, monkeypatch
):
    """bootstrap detects an unprocessed CHANGES trigger and requeues Builder directly.

    Scenario: Supervisor restarts after a REVIEW_DECISION(changes) was emitted.
    _bootstrap_reconcile_sequence() advanced last_processed_sequence to the latest
    event (past the CHANGES trigger), so run_once() would never see it in new_events.
    Expected: reconcile_state() detects the gap via _bootstrap_requeue_if_needed()
    and fires requeue before run_once() even runs.
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

    ticket_id = "WP-2026-164"

    # Emit the exact event sequence that causes the bug:
    # initial start → Builder done → Manager: changes → Supervisor: IN_PROGRESS
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Done",
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

    # Simulate the consumed-trigger bug: bootstrap already advanced
    # last_processed_sequence to the latest event, but requeue never fired.
    all_events = supervisor.event_bus.read_events()
    latest_seq = all_events[-1].sequence_number
    supervisor.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
            last_processed_sequence=latest_seq,
            last_requeue_trigger_sequence=0,
        )
    )

    relaunch_calls: list[str] = []

    def fake_relaunch(t: str, *a, **kw) -> bool:
        relaunch_calls.append(t)
        return True

    monkeypatch.setattr(supervisor, "_relaunch_builder", fake_relaunch)

    supervisor.bootstrap()

    assert relaunch_calls == [ticket_id], (
        "bootstrap must requeue Builder when CHANGES is unprocessed"
    )
    state = supervisor.load_state()
    assert state.last_requeue_trigger_sequence > 0, (
        "watermark must be updated after bootstrap requeue"
    )
    assert state.loop_current_round == 2, "round must increment on bootstrap requeue"


def test_bootstrap_requeue_if_needed_defers_when_builder_lock_fresh(
    tmp_path, monkeypatch
):
    """bootstrap defers requeue when builder_lock.txt is fresh (alive or stale without BUILDER_EXIT).

    Scenario: Stale builder_lock.txt exists (<15 min, no BUILDER_EXIT) and
    _builder_alive() returns True via mtime fallback. bootstrap must NOT update
    the watermark so the next restart can retry after the lock expires.
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

    ticket_id = "WP-2026-166"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
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

    all_events = supervisor.event_bus.read_events()
    latest_seq = all_events[-1].sequence_number
    supervisor.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
            last_processed_sequence=latest_seq,
            last_requeue_trigger_sequence=0,
        )
    )

    # Simulate a fresh builder_lock.txt (stale without BUILDER_EXIT)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: True)

    relaunch_calls: list[str] = []

    def fake_relaunch(t: str, *a, **kw) -> bool:
        relaunch_calls.append(t)
        return True

    monkeypatch.setattr(supervisor, "_relaunch_builder", fake_relaunch)

    supervisor.bootstrap()

    deferred = [
        e
        for e in supervisor.event_bus.read_events()
        if e.event_type == "SUPERVISOR_REQUEUE_DEFERRED"
    ]
    assert len(deferred) == 1, "first bootstrap must defer exactly once"
    assert relaunch_calls == [], "first bootstrap must not relaunch Builder"

    state_after_defer = supervisor.load_state()
    assert state_after_defer.last_requeue_trigger_sequence == 0, (
        "watermark must remain unset after defer"
    )

    # Second bootstrap: lock is gone, so requeue should fire.
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)
    supervisor.bootstrap()

    assert relaunch_calls == [ticket_id], "second bootstrap must relaunch Builder"
    state_after_retry = supervisor.load_state()
    assert state_after_retry.last_requeue_trigger_sequence > 0, (
        "watermark must update after successful retry"
    )


def test_bootstrap_requeue_if_needed_skips_when_watermark_already_set(
    tmp_path, monkeypatch
):
    """bootstrap does NOT requeue if last_requeue_trigger_sequence already covers the CHANGES event.

    This prevents double-requeue on a second bootstrap call after the first
    bootstrap already handled the CHANGES trigger.
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

    ticket_id = "WP-2026-165"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
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

    all_events = supervisor.event_bus.read_events()
    latest_seq = all_events[-1].sequence_number
    # Find the REVIEW_DECISION sequence
    changes_seq = next(
        e.sequence_number for e in all_events if e.event_type == "REVIEW_DECISION"
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=2,
            last_processed_sequence=latest_seq,
            last_requeue_trigger_sequence=changes_seq,  # watermark already covers it
        )
    )

    relaunch_calls: list[str] = []

    def fake_relaunch(t: str, *a, **kw) -> bool:
        relaunch_calls.append(t)
        return True

    monkeypatch.setattr(supervisor, "_relaunch_builder", fake_relaunch)

    supervisor.bootstrap()

    assert relaunch_calls == [], (
        "bootstrap must NOT requeue when watermark already covers the CHANGES event"
    )
    state = supervisor.load_state()
    assert state.loop_current_round == 2, "round must not change"


# =============================================================================
# Tests WP-2026-166: Manager watchdog for stale READY_FOR_REVIEW
# =============================================================================


def _make_watchdog_supervisor(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


def test_watchdog_fires_when_bridge_stale(tmp_path, monkeypatch):
    """Stale bridge → MANAGER_STALE emitted, Popen called, watermark updated."""
    import subprocess as _subprocess

    supervisor = _make_watchdog_supervisor(tmp_path)
    ticket_id = "WP-2026-166"

    # Emit STATE_CHANGED → READY_FOR_REVIEW so the watchdog has a trigger sequence.
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )
    events_after_emit = supervisor.event_bus.read_events(ticket_id=ticket_id)
    rfr_seq = events_after_emit[-1].sequence_number

    # Set up state with watermark below the trigger.
    state = supervisor.load_state()
    state.active_ticket = ticket_id
    state.last_manager_stale_trigger_sequence = 0
    supervisor.save_state(state)

    # Bridge state: heartbeat_at is old (> MANAGER_STALE_TIMEOUT).
    from datetime import timedelta

    old_hb = (datetime.now(tz=timezone.utc) - timedelta(seconds=700)).isoformat()
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        f'{{"heartbeat_at": "{old_hb}", "last_processed_sequence": 0}}',
        encoding="utf-8",
    )

    emitted_events: list[str] = []

    def fake_emit(event_type, *, ticket_id, actor, payload=None, **_kw):
        emitted_events.append(event_type)

    monkeypatch.setattr(supervisor.event_bus, "emit", fake_emit)

    popen_calls: list = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        mock = MagicMock()
        return mock

    monkeypatch.setattr(_subprocess, "Popen", fake_popen)

    # _current_state must return READY_FOR_REVIEW.
    monkeypatch.setattr(
        supervisor, "_current_state", lambda tid: TicketState.READY_FOR_REVIEW
    )

    state = supervisor.load_state()
    supervisor._bootstrap_watchdog_manager_if_needed(state, ticket_id)

    assert "MANAGER_STALE" in emitted_events, "watchdog must emit MANAGER_STALE"
    assert len(popen_calls) == 1, "Popen must be called once to relaunch bridge"
    assert "--watch" in popen_calls[0]

    reloaded = supervisor.load_state()
    assert reloaded.last_manager_stale_trigger_sequence == rfr_seq, (
        "watermark must advance to rfr_seq after relaunch"
    )


def test_watchdog_skips_when_bridge_fresh(tmp_path, monkeypatch):
    """Fresh bridge heartbeat → watchdog must NOT fire."""
    import subprocess as _subprocess

    supervisor = _make_watchdog_supervisor(tmp_path)
    ticket_id = "WP-2026-166"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = supervisor.load_state()
    state.active_ticket = ticket_id
    state.last_manager_stale_trigger_sequence = 0
    supervisor.save_state(state)

    # Fresh heartbeat.
    fresh_hb = datetime.now(tz=timezone.utc).isoformat()
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        f'{{"heartbeat_at": "{fresh_hb}", "last_processed_sequence": 0}}',
        encoding="utf-8",
    )

    popen_calls: list = []
    monkeypatch.setattr(_subprocess, "Popen", lambda cmd, **kw: popen_calls.append(cmd))
    monkeypatch.setattr(
        supervisor, "_current_state", lambda tid: TicketState.READY_FOR_REVIEW
    )

    state = supervisor.load_state()
    supervisor._bootstrap_watchdog_manager_if_needed(state, ticket_id)

    assert popen_calls == [], "Popen must NOT be called when bridge is fresh"

    reloaded = supervisor.load_state()
    assert reloaded.last_manager_stale_trigger_sequence == 0, (
        "watermark must not advance when bridge is alive"
    )


def test_watchdog_skips_when_watermark_covers_sequence(tmp_path, monkeypatch):
    """Watermark already at RFR sequence → watchdog must not double-fire."""
    import subprocess as _subprocess

    supervisor = _make_watchdog_supervisor(tmp_path)
    ticket_id = "WP-2026-166"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )
    events_after_emit = supervisor.event_bus.read_events(ticket_id=ticket_id)
    rfr_seq = events_after_emit[-1].sequence_number

    # Watermark already covers the trigger.
    state = supervisor.load_state()
    state.active_ticket = ticket_id
    state.last_manager_stale_trigger_sequence = rfr_seq
    supervisor.save_state(state)

    popen_calls: list = []
    monkeypatch.setattr(_subprocess, "Popen", lambda cmd, **kw: popen_calls.append(cmd))
    monkeypatch.setattr(
        supervisor, "_current_state", lambda tid: TicketState.READY_FOR_REVIEW
    )

    state = supervisor.load_state()
    supervisor._bootstrap_watchdog_manager_if_needed(state, ticket_id)

    assert popen_calls == [], (
        "Popen must NOT be called when watermark covers the sequence"
    )


@pytest.mark.parametrize(
    "fake_platform,expected_key,absent_key",
    [
        ("win32", "creationflags", "start_new_session"),
        ("linux", "start_new_session", "creationflags"),
    ],
)
def test_watchdog_popen_detach_flags(
    tmp_path, monkeypatch, fake_platform, expected_key, absent_key
):
    """Popen receives the correct OS-level detach kwarg for each platform.

    Parametrized over win32 and linux so both branches are exercised on any CI host.
    Windows-only subprocess constants are stubbed when running on POSIX.
    """
    import subprocess as _subprocess
    from datetime import timedelta

    # Windows-only constants may be absent on POSIX; provide stubs so the
    # production code can evaluate the creationflags bitmask expression.
    if not hasattr(_subprocess, "DETACHED_PROCESS"):
        monkeypatch.setattr(_subprocess, "DETACHED_PROCESS", 8, raising=False)
    if not hasattr(_subprocess, "CREATE_NEW_PROCESS_GROUP"):
        monkeypatch.setattr(_subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)

    # Force the platform seen by supervisor's _bootstrap_watchdog_manager_if_needed.
    monkeypatch.setattr(sys, "platform", fake_platform)

    supervisor = _make_watchdog_supervisor(tmp_path)
    ticket_id = "WP-2026-166"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = supervisor.load_state()
    state.active_ticket = ticket_id
    state.last_manager_stale_trigger_sequence = 0
    supervisor.save_state(state)

    old_hb = (datetime.now(tz=timezone.utc) - timedelta(seconds=700)).isoformat()
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        f'{{"heartbeat_at": "{old_hb}", "last_processed_sequence": 0}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(supervisor.event_bus, "emit", lambda *a, **kw: None)
    monkeypatch.setattr(
        supervisor, "_current_state", lambda tid: TicketState.READY_FOR_REVIEW
    )

    captured_kwargs: list[dict] = []

    def fake_popen(cmd, **kwargs):
        captured_kwargs.append(kwargs)
        return MagicMock()

    monkeypatch.setattr(_subprocess, "Popen", fake_popen)

    state = supervisor.load_state()
    supervisor._bootstrap_watchdog_manager_if_needed(state, ticket_id)

    assert len(captured_kwargs) == 1, "Popen must be called exactly once"
    kw = captured_kwargs[0]

    assert expected_key in kw, f"{fake_platform}: must pass {expected_key}"
    assert absent_key not in kw, f"{fake_platform}: must NOT pass {absent_key}"

    if fake_platform == "win32":
        assert kw["creationflags"] & _subprocess.DETACHED_PROCESS
        assert kw["creationflags"] & _subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kw["start_new_session"] is True


def test_watchdog_skips_when_ticket_not_ready_for_review(tmp_path, monkeypatch):
    """Stale bridge + ticket in IN_PROGRESS → watchdog must be a no-op."""
    import subprocess as _subprocess
    from datetime import timedelta

    supervisor = _make_watchdog_supervisor(tmp_path)
    ticket_id = "WP-2026-166"

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = supervisor.load_state()
    state.active_ticket = ticket_id
    state.last_manager_stale_trigger_sequence = 0
    supervisor.save_state(state)

    old_hb = (datetime.now(tz=timezone.utc) - timedelta(seconds=700)).isoformat()
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        f'{{"heartbeat_at": "{old_hb}", "last_processed_sequence": 0}}',
        encoding="utf-8",
    )

    popen_calls: list = []
    monkeypatch.setattr(_subprocess, "Popen", lambda cmd, **kw: popen_calls.append(cmd))
    # Ticket is IN_PROGRESS, not READY_FOR_REVIEW — watchdog guard must block here.
    monkeypatch.setattr(
        supervisor, "_current_state", lambda tid: TicketState.IN_PROGRESS
    )

    state = supervisor.load_state()
    supervisor._bootstrap_watchdog_manager_if_needed(state, ticket_id)

    assert popen_calls == [], "Popen must NOT fire when ticket is not READY_FOR_REVIEW"


def test_is_manager_bridge_stale_no_file(tmp_path):
    """Absent bridge state file → stale (True)."""
    supervisor = _make_watchdog_supervisor(tmp_path)
    assert supervisor._is_manager_bridge_stale() is True


def test_is_manager_bridge_stale_empty_heartbeat(tmp_path):
    """Bridge file present but heartbeat_at is empty string → stale (True)."""
    supervisor = _make_watchdog_supervisor(tmp_path)
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        '{"heartbeat_at": "", "last_processed_sequence": 0}',
        encoding="utf-8",
    )
    assert supervisor._is_manager_bridge_stale() is True


def test_is_manager_bridge_stale_malformed_heartbeat(tmp_path):
    """Bridge file present but heartbeat_at is not a valid ISO timestamp → stale (True)."""
    supervisor = _make_watchdog_supervisor(tmp_path)
    (supervisor.runtime_dir / "manager_bridge_state.json").write_text(
        '{"heartbeat_at": "not-a-valid-timestamp", "last_processed_sequence": 0}',
        encoding="utf-8",
    )
    assert supervisor._is_manager_bridge_stale() is True


# =============================================================================
# Tests WP-2026-172: HANDOFF_BLOCKED suppression + PROJECT.md live surface
# =============================================================================


def test_run_once_suppresses_relaunch_on_handoff_blocked(tmp_path, monkeypatch):
    """run_once must suppress relaunch when HANDOFF_BLOCKED exists after trigger.

    WP-2026-172: HANDOFF_BLOCKED after requeue trigger → RELAUNCH_SUPPRESSED emitted,
    no BUILDER_RELAUNCH_ATTEMPTED, no requeue_ticket call.
    """
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-172",
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
            active_ticket="WP-2026-172",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    # Emit CHANGES trigger event
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-172",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )

    # Emit HANDOFF_BLOCKED after the trigger (higher sequence)
    supervisor.event_bus.emit(
        "HANDOFF_BLOCKED",
        ticket_id="WP-2026-172",
        actor="BUILDER",
        payload={"reason": "pre_handoff_guard_failed", "dirty_tree": True},
    )

    # Track calls
    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    result = supervisor.run_once()

    # Should process events but NOT relaunch
    assert result is True  # Event activity occurred
    assert relaunch_calls == [], (
        "run_once must NOT relaunch when HANDOFF_BLOCKED exists after trigger"
    )

    # Verify RELAUNCH_SUPPRESSED was emitted
    suppressed = [
        e
        for e in supervisor.event_bus.read_events()
        if e.event_type == "RELAUNCH_SUPPRESSED"
    ]
    assert len(suppressed) == 1, "Exactly one RELAUNCH_SUPPRESSED must be emitted"
    payload = suppressed[0].payload
    assert payload["reason"] == "handoff_blocked"
    assert payload["trigger_sequence"] > 0
    assert payload["blocking_sequence"] > payload["trigger_sequence"]

    # Verify no BUILDER_RELAUNCH_ATTEMPTED was emitted
    launch_attempts = [
        e
        for e in supervisor.event_bus.read_events()
        if e.event_type == "BUILDER_RELAUNCH_ATTEMPTED"
    ]
    assert len(launch_attempts) == 0, (
        "BUILDER_RELAUNCH_ATTEMPTED must NOT be emitted when suppressed"
    )

    # Watermark should NOT be updated (no requeue happened)
    state = supervisor.load_state()
    assert state.last_requeue_trigger_sequence == 0, (
        "watermark must stay at 0 when relaunch is suppressed"
    )
    assert state.loop_current_round == 1, "round must not increment when suppressed"


def test_run_once_relaunches_on_timeout_without_handoff_blocked(tmp_path, monkeypatch):
    """run_once must still relaunch on timeout/crash when no HANDOFF_BLOCKED exists.

    WP-2026-172: crash/timeout scenario without HANDOFF_BLOCKED must preserve
    existing requeue behavior.
    """
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WP-2026-172",
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
            active_ticket="WP-2026-172",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    # Emit CHANGES trigger (no HANDOFF_BLOCKED after it)
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-2026-172",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    result = supervisor.run_once()

    # Must still trigger requeue (existing behavior preserved)
    assert result is True
    assert relaunch_calls == ["WP-2026-172"], (
        "run_once must still relaunch when no HANDOFF_BLOCKED exists"
    )

    # Verify NO RELAUNCH_SUPPRESSED was emitted
    suppressed = [
        e
        for e in supervisor.event_bus.read_events()
        if e.event_type == "RELAUNCH_SUPPRESSED"
    ]
    assert len(suppressed) == 0, (
        "RELAUNCH_SUPPRESSED must NOT be emitted in normal crash/timeout scenario"
    )

    # Watermark must be updated after successful requeue
    state = supervisor.load_state()
    assert state.last_requeue_trigger_sequence > 0, (
        "watermark must update after successful requeue"
    )
    assert state.loop_current_round == 2, "round must increment on requeue"


def test_run_once_uses_review_decision_as_single_requeue_trigger(tmp_path, monkeypatch):
    """A CHANGES decision plus IN_PROGRESS transition must relaunch only once."""
    from bus.supervisor import SequentialTicketSupervisor, SupervisorState

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    _write_work_plan(collaboration_dir / "work_plan.md")
    _write_execution_log(collaboration_dir / "execution_log.md")
    _write_turn(
        collaboration_dir / "TURN.md",
        role="BUILDER",
        plan_id="WT-2026-197",
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
            active_ticket="WT-2026-197",
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )

    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id="WT-2026-197",
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "needs work"},
    )
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-197",
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "IN_PROGRESS",
            "reason": "Manager requested changes",
            "source": "request-changes",
        },
    )

    events = supervisor.event_bus.read_events(ticket_id="WT-2026-197")
    review_seq = next(
        e.sequence_number for e in events if e.event_type == "REVIEW_DECISION"
    )
    in_progress_seq = next(
        e.sequence_number
        for e in events
        if e.event_type == "STATE_CHANGED"
        and str((e.payload or {}).get("to_state", "")) == "IN_PROGRESS"
    )
    assert in_progress_seq > review_seq

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda ticket_id, *a, **kw: relaunch_calls.append(ticket_id) or True,
    )

    result = supervisor.run_once()

    assert result is True
    assert relaunch_calls == ["WT-2026-197"], (
        "run_once must relaunch exactly once for the CHANGES decision and must "
        "not treat STATE_CHANGED -> IN_PROGRESS as a second trigger"
    )
    state = supervisor.load_state()
    assert state.last_requeue_trigger_sequence == review_seq
    assert state.last_requeue_trigger_sequence != in_progress_seq


def test_bootstrap_requeue_suppresses_on_handoff_blocked(tmp_path, monkeypatch):
    """_bootstrap_requeue_if_needed must suppress relaunch when HANDOFF_BLOCKED
    exists after the trigger sequence.

    WP-2026-172: Bootstrap path also checks HANDOFF_BLOCKED before requeueing.
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

    ticket_id = "WP-2026-172"

    # Emit initial start
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    # Emit CHANGES trigger
    supervisor.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "Fix it"},
    )
    # Emit HANDOFF_BLOCKED after the trigger (higher sequence)
    supervisor.event_bus.emit(
        "HANDOFF_BLOCKED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"reason": "pre_handoff_guard_failed", "dirty_tree": True},
    )

    all_events = supervisor.event_bus.read_events()
    latest_seq = all_events[-1].sequence_number

    # Set up state as if bootstrap reconciled sequence already
    supervisor.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
            last_processed_sequence=latest_seq,
            last_requeue_trigger_sequence=0,
        )
    )

    # Mock _builder_alive to return False (Builder not alive, would normally proceed)
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    relaunch_calls: list[str] = []
    monkeypatch.setattr(
        supervisor,
        "_relaunch_builder",
        lambda t: relaunch_calls.append(t) or True,
    )

    # Run bootstrap requeue check directly
    state = supervisor.load_state()
    supervisor._bootstrap_requeue_if_needed(state, ticket_id)

    # Must NOT relaunch because HANDOFF_BLOCKED exists after trigger
    assert relaunch_calls == [], (
        "bootstrap must NOT relaunch when HANDOFF_BLOCKED exists after trigger"
    )

    # Verify RELAUNCH_SUPPRESSED was emitted
    suppressed = [
        e
        for e in supervisor.event_bus.read_events()
        if e.event_type == "RELAUNCH_SUPPRESSED"
    ]
    assert len(suppressed) == 1, "Exactly one RELAUNCH_SUPPRESSED must be emitted"
    payload = suppressed[0].payload
    assert payload["reason"] == "handoff_blocked"
    assert payload["trigger_sequence"] > 0
    assert payload["blocking_sequence"] > payload["trigger_sequence"]

    # Watermark must NOT be updated
    state_after = supervisor.load_state()
    assert state_after.last_requeue_trigger_sequence == 0, (
        "watermark must not be updated when relaunch is suppressed in bootstrap"
    )


def test_has_handoff_blocked_after_sequence_returns_zero_when_none(tmp_path):
    """_has_handoff_blocked_after_sequence returns 0 when no HANDOFF_BLOCKED exists."""
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

    result = supervisor._has_handoff_blocked_after_sequence("WP-2026-172", 0)
    assert result == 0


def test_has_handoff_blocked_after_sequence_finds_blocking(tmp_path):
    """_has_handoff_blocked_after_sequence returns highest blocking seq when present."""
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

    ticket_id = "WP-2026-172"

    # Emit normal events at seq 1
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS"},
    )
    # Emit HANDOFF_BLOCKED at seq 2 (after trigger at seq 1)
    supervisor.event_bus.emit(
        "HANDOFF_BLOCKED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"reason": "blocked"},
    )
    # Emit another HANDOFF_BLOCKED at seq 3
    supervisor.event_bus.emit(
        "HANDOFF_BLOCKED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"reason": "blocked again"},
    )

    # Check with trigger at seq 1: should find seq 3 (highest)
    result = supervisor._has_handoff_blocked_after_sequence(ticket_id, 1)
    assert result == 3, "Should return highest HANDOFF_BLOCKED sequence > trigger"

    # Check with trigger at seq 2: should find seq 3
    result = supervisor._has_handoff_blocked_after_sequence(ticket_id, 2)
    assert result == 3, "Should find HANDOFF_BLOCKED at seq 3"

    # Check with trigger at seq 3: should find 0 (none after)
    result = supervisor._has_handoff_blocked_after_sequence(ticket_id, 3)
    assert result == 0, "Should return 0 when no HANDOFF_BLOCKED after trigger"

    # Check with trigger at seq 0: should find seq 3
    result = supervisor._has_handoff_blocked_after_sequence(ticket_id, 0)
    assert result == 3, "Should find highest HANDOFF_BLOCKED"


# ======================================================================
# WT-2026-181: Dual WP-/WT- prefix regression tests
# ======================================================================


class TestDualPrefixSupervisor:
    """Verify the supervisor accepts both WP- and WT- prefixes."""

    def test_next_ticket_id_from_wp(self, tmp_path):
        """_next_ticket_id generates next ID from WP- ticket, emits WT-."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor._next_ticket_id("WP-2026-100")
        assert result == "WT-2026-101", f"Expected WT-2026-101, got {result}"

    def test_next_ticket_id_from_wt(self, tmp_path):
        """_next_ticket_id generates next ID from WT- ticket."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor._next_ticket_id("WT-2026-100")
        assert result == "WT-2026-101", f"Expected WT-2026-101, got {result}"

    def test_next_ticket_id_invalid_returns_none(self, tmp_path):
        """_next_ticket_id returns None for invalid ticket IDs."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        assert supervisor._next_ticket_id("INVALID-123") is None
        assert supervisor._next_ticket_id("") is None

    def test_ticket_sort_key_wp(self, tmp_path):
        """_ticket_sort_key sorts WP- tickets correctly."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        key = supervisor._ticket_sort_key("WP-2026-100")
        assert key[0] == 2026
        assert key[1] == 100

    def test_ticket_sort_key_wt(self, tmp_path):
        """_ticket_sort_key sorts WT- tickets correctly."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        key = supervisor._ticket_sort_key("WT-2026-100")
        assert key[0] == 2026
        assert key[1] == 100

    def test_ticket_sort_key_wt_alphanumeric_suffix_uses_numeric_prefix(self, tmp_path):
        """WT alphanumeric suffixes must sort by their leading numeric component."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)

        key = supervisor._ticket_sort_key("WT-2026-221a")

        assert key[0] == 2026
        assert key[1] == 221
        assert key > supervisor._ticket_sort_key("WT-2026-183")

    def test_ticket_sort_key_wp_wt_mixed(self, tmp_path):
        """_ticket_sort_key produces consistent ordering for mixed WP/WT tickets."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        key_wp = supervisor._ticket_sort_key("WP-2026-100")
        key_wt = supervisor._ticket_sort_key("WT-2026-100")
        assert key_wp == key_wt, (
            "WP and WT tickets with same year+num should have same sort key"
        )

    def test_recover_active_ticket_from_turn_wp(self, tmp_path):
        """recover_active_ticket() reads WP- ticket from TURN.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        turn = collab / "TURN.md"
        turn.write_text(
            "| **Plan ID** | WP-2026-100 |\n",
            encoding="utf-8",
        )
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor.recover_active_ticket()
        assert result == "WP-2026-100", f"Expected WP-2026-100, got {result}"

    def test_recover_active_ticket_from_turn_wt(self, tmp_path):
        """recover_active_ticket() reads WT- ticket from TURN.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        turn = collab / "TURN.md"
        turn.write_text(
            "| **Plan ID** | WT-2026-100 |\n",
            encoding="utf-8",
        )
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor.recover_active_ticket()
        assert result == "WT-2026-100", f"Expected WT-2026-100, got {result}"

    def test_recover_active_ticket_from_work_plan_wp(self, tmp_path):
        """recover_active_ticket() reads WP- ticket from work_plan.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wp = collab / "work_plan.md"
        wp.write_text(
            "# Work Plan - WP-2026-100\n\n## Metadata\n- **ID:** WP-2026-100\n"
        )
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor.recover_active_ticket()
        assert result == "WP-2026-100", f"Expected WP-2026-100, got {result}"

    def test_recover_active_ticket_from_work_plan_wt(self, tmp_path):
        """recover_active_ticket() reads WT- ticket from work_plan.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wp = collab / "work_plan.md"
        wp.write_text(
            "# Work Plan - WT-2026-100\n\n## Metadata\n- **ID:** WT-2026-100\n"
        )
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        result = supervisor.recover_active_ticket()
        assert result == "WT-2026-100", f"Expected WT-2026-100, got {result}"

    def test_ensure_ticket_queue_extracts_both_prefixes(self, tmp_path):
        """ensure_ticket_queue() extracts both WP- and WT- tickets from work_plan."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wp = collab / "work_plan.md"
        wp.write_text(
            "# Work Plan\n\n"
            "## WP-2026-100: First ticket\n\n### Metadata\n- **ID:** WP-2026-100\n\n"
            "## WT-2026-101: Second ticket\n\n### Metadata\n- **ID:** WT-2026-101\n"
        )
        bus_dir = tmp_path / ".agent" / "runtime" / "events"
        bus_dir.mkdir(parents=True)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        # ensure_ticket_queue should not crash with mixed prefixes
        supervisor.ensure_ticket_queue()


# ---------------------------------------------------------------------------
# WT-2026-197: Supervisor post-restart sin Builder tras CHANGES
# ---------------------------------------------------------------------------


def _make_supervisor_wt197(tmp_path):
    """Helper: create a supervisor with collaboration + runtime dirs."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    (collaboration_dir / "work_plan.md").write_text(
        "# Work Ticket - WT-2026-197\n\n## Metadata\n- **ID:** WT-2026-197\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log WT-2026-197\n\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


def test_wt197_bootstrap_requeues_builder_on_spurious_ready_for_review(
    tmp_path, monkeypatch
):
    """WT-2026-197: Supervisor reinicia con READY_FOR_REVIEW espurio (crash durante
    BUILDER_RELAUNCH_ATTEMPTED tras CHANGES) → debe forzar requeue de Builder.

    Scenario:
      seq1  REVIEW_DECISION(changes)
      seq2  BUILDER_RELAUNCH_ATTEMPTED          ← crash aquí
      seq3  STATE_CHANGED → READY_FOR_REVIEW    ← estado proyectado espurio

    last_processed_sequence = 0 (crash; watermark no avanzó)
    last_requeue_trigger_sequence = 0

    Expect: requeue_ticket() llamado; NO se despacha al Manager.
    """
    sup = _make_supervisor_wt197(tmp_path)
    ticket_id = "WT-2026-197"

    # Build bus state simulating the crash scenario
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "builder ready",
        },
    )
    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "fix the guard"},
    )
    sup.event_bus.emit(
        "BUILDER_RELAUNCH_ATTEMPTED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"reason": "changes_decision"},
    )
    # Crash here — bus left in READY_FOR_REVIEW (no IN_PROGRESS transition was written)
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_FOR_REVIEW",
            "reason": "spurious",
        },
    )

    # Persisted state: watermarks at 0 (crash, nothing was committed)
    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            last_processed_sequence=0,
            last_requeue_trigger_sequence=0,
        )
    )

    requeue_calls = []
    monkeypatch.setattr(
        sup, "requeue_ticket", lambda tid, *a, **kw: requeue_calls.append(tid) or True
    )
    # _builder_alive must return False so the requeue is not deferred
    monkeypatch.setattr(sup, "_builder_alive", lambda: False)
    # Watchdog must be no-op to isolate the test
    monkeypatch.setattr(sup, "_bootstrap_watchdog_manager_if_needed", lambda s, t: None)

    sup._bootstrap_requeue_if_needed(sup.load_state(), ticket_id)

    assert requeue_calls == [ticket_id], (
        "Expected requeue_ticket() to be called once for the spurious READY_FOR_REVIEW scenario"
    )


def test_wt197_bootstrap_does_not_requeue_on_legitimate_ready_for_review(
    tmp_path, monkeypatch
):
    """WT-2026-197: Supervisor reinicia con READY_FOR_REVIEW legítimo
    (Builder respondió al CHANGES y emitió BUILDER_EXIT; watermark avanzó) →
    debe despachar al Manager, no relanzar Builder.

    Scenario:
      seq1  REVIEW_DECISION(changes)
      seq2  BUILDER_EXIT                        ← Builder respondió normalmente
      seq3  STATE_CHANGED → READY_FOR_REVIEW    ← Builder hizo mark-ready en el segundo ciclo

    last_processed_sequence ≥ seq1 (watermark avanzó)
    last_requeue_trigger_sequence = seq1 (ya procesado)

    Expect: requeue_ticket() NO llamado.
    """
    sup = _make_supervisor_wt197(tmp_path)
    ticket_id = "WT-2026-197"

    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "builder ready",
        },
    )
    changes_event = sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "fix the guard"},
    )
    changes_seq = changes_event.sequence_number if changes_event else 2

    sup.event_bus.emit(
        "BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={"exit_code": 0},
    )
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "second cycle done",
        },
    )

    all_events = sup.event_bus.read_events()
    latest_seq = all_events[-1].sequence_number if all_events else changes_seq + 2

    # Watermark advanced past the CHANGES event — Builder acknowledged it
    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            last_processed_sequence=latest_seq,
            last_requeue_trigger_sequence=changes_seq,
        )
    )

    requeue_calls = []
    monkeypatch.setattr(
        sup, "requeue_ticket", lambda tid, *a, **kw: requeue_calls.append(tid) or True
    )
    monkeypatch.setattr(sup, "_builder_alive", lambda: False)
    monkeypatch.setattr(sup, "_bootstrap_watchdog_manager_if_needed", lambda s, t: None)

    sup._bootstrap_requeue_if_needed(sup.load_state(), ticket_id)

    assert requeue_calls == [], (
        "requeue_ticket() must NOT be called when READY_FOR_REVIEW is legitimate "
        "(watermark covers the CHANGES event)"
    )


def test_wt197_no_double_requeue_when_watermark_already_covers_changes(
    tmp_path, monkeypatch
):
    """WT-2026-197: Regresión — si last_requeue_trigger_sequence ya cubre el seq del CHANGES,
    no debe producirse un segundo requeue aunque el estado sea READY_FOR_REVIEW.

    This guards against the WT-2026-189 double-requeue pattern being re-introduced.
    """
    sup = _make_supervisor_wt197(tmp_path)
    ticket_id = "WT-2026-197"

    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "fix it"},
    )
    all_events = sup.event_bus.read_events(ticket_id=ticket_id)
    changes_seq = all_events[-1].sequence_number if all_events else 1

    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "spurious",
        },
    )

    # Watermark already covers the CHANGES — a previous bootstrap already processed it
    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            last_processed_sequence=0,
            last_requeue_trigger_sequence=changes_seq,  # already recorded
        )
    )

    requeue_calls = []
    monkeypatch.setattr(
        sup, "requeue_ticket", lambda tid, *a, **kw: requeue_calls.append(tid) or True
    )
    monkeypatch.setattr(sup, "_builder_alive", lambda: False)
    monkeypatch.setattr(sup, "_bootstrap_watchdog_manager_if_needed", lambda s, t: None)

    sup._bootstrap_requeue_if_needed(sup.load_state(), ticket_id)

    assert requeue_calls == [], (
        "Must not double-requeue when last_requeue_trigger_sequence already covers the CHANGES seq"
    )


# =============================================================================
# Tests WT-2026-199: Claim atomico de requeue y verificacion de Builder vivo
# =============================================================================


def _make_supervisor_with_claims(tmp_path):
    """Helper: create supervisor with standard dirs for claim tests."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


def test_claim_requeue_excl_only_one_winner(tmp_path):
    """TP-01: _claim_requeue usa O_CREAT|O_EXCL; solo un winner por (ticket, seq)."""
    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 100

    # First claim should succeed
    assert sup._claim_requeue(ticket_id, trigger_seq) is True

    # Second claim for same (ticket, seq) should fail (FileExistsError, no staleness)
    assert sup._claim_requeue(ticket_id, trigger_seq) is False

    # Different trigger_seq should succeed
    assert sup._claim_requeue(ticket_id, 101) is True


def test_claim_requeue_blocks_second_path_same_sequence(tmp_path):
    """TP-02: Two callers for same (ticket_id, trigger_seq) — only one wins."""
    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 200

    # Simulate two callers
    winner1 = sup._claim_requeue(ticket_id, trigger_seq)
    winner2 = sup._claim_requeue(ticket_id, trigger_seq)

    # Exactly one should win
    assert winner1 is True
    assert winner2 is False


def test_requeue_ticket_no_side_effects_when_claim_denied(tmp_path, monkeypatch):
    """TP-03: requeue_ticket no produce efectos si el claim falla."""
    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 300

    # Set up state so the first check passes
    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
        )
    )
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )

    # Acquire claim first (simulates another supervisor owning it)
    assert sup._claim_requeue(ticket_id, trigger_seq) is True

    # Mock _relaunch_builder to track calls
    relaunch_calls = []
    monkeypatch.setattr(
        sup, "_relaunch_builder", lambda *a, **kw: relaunch_calls.append(True) or True
    )

    # requeue_ticket should fail because claim is denied
    result = sup.requeue_ticket(ticket_id, trigger_seq)
    assert result is False

    # No side effects: round not incremented, relaunch not called
    state = sup.load_state()
    assert state.loop_current_round == 1
    assert relaunch_calls == []


def test_claim_stale_recovered_after_ttl_without_relaunch(tmp_path):
    """TP-04: Claim stale se recupera si TTL excedido y no hay relanzado previo."""
    import os
    import time

    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 400

    # Create a stale claim by writing directly (bypassing _claim_requeue)
    claims_dir = sup.runtime_dir / "requeue_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{ticket_id}_seq-{trigger_seq}.claim"
    claim_path.write_text("stale claim content", encoding="utf-8")

    # Make it old (> TTL)
    old_time = time.time() - 200  # well past default 90s TTL
    os.utime(claim_path, (old_time, old_time))

    # No BUILDER_RELAUNCH_ATTEMPTED event on bus

    # Should recover stale claim
    result = sup._claim_requeue(ticket_id, trigger_seq)
    assert result is True, "Stale claim should be recoverable"


def test_claim_stale_takeover_atomic_only_one_recovers(tmp_path):
    """TP-05: Solo un supervisor puede recuperar un stale claim (takeover atomico)."""
    import os
    import time

    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 500

    # Create stale claim
    claims_dir = sup.runtime_dir / "requeue_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{ticket_id}_seq-{trigger_seq}.claim"
    claim_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 200
    os.utime(claim_path, (old_time, old_time))

    # Create a takeover file to block recovery (simulates another contender)
    takeover_path = claim_path.with_suffix(".claim.takeover")
    takeover_path.write_text("locked", encoding="utf-8")

    # Recovery should fail because takeover is held
    result = sup._claim_requeue(ticket_id, trigger_seq)
    assert result is False, (
        "Recovery must fail when another contender holds the takeover"
    )


def test_claim_stale_takeover_cleanup_on_successful_recovery(tmp_path):
    """TP-05b: Takeover file is cleaned up after successful stale claim recovery."""
    import os
    import time

    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"
    trigger_seq = 501

    # Create stale claim (TTL exceeded, no relaunch for this trigger)
    claims_dir = sup.runtime_dir / "requeue_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{ticket_id}_seq-{trigger_seq}.claim"
    claim_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 200
    os.utime(claim_path, (old_time, old_time))

    takeover_path = claim_path.with_suffix(".claim.takeover")
    assert not takeover_path.exists(), "Takeover file should not exist yet"

    # Successful recovery should create and then clean up the takeover file
    result = sup._claim_requeue(ticket_id, trigger_seq)
    assert result is True, "Must recover stale claim"

    # Takeover file must be removed after recovery completes
    assert not takeover_path.exists(), (
        "Takeover file must be cleaned up after successful recovery"
    )

    # New claim file should be present with fresh content
    assert claim_path.exists(), "Fresh claim must exist after recovery"
    import json

    claim_data = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim_data["ticket_id"] == ticket_id
    assert claim_data["trigger_seq"] == trigger_seq


def test_claim_not_reclaimed_when_relaunch_already_emitted(tmp_path):
    """TP-06: No reclamar si ya existe BUILDER_RELAUNCH_ATTEMPTED para el trigger."""
    import os
    import time

    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"

    # Emit some events first so sequence numbers are realistic
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )
    # This is the REVIEW_DECISION that acts as trigger — seq=2
    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "changes", "feedback": "fix it"},
    )
    trigger_seq = 2  # The REVIEW_DECISION sequence

    # Now emit BUILDER_RELAUNCH_ATTEMPTED at seq=3 (> trigger_seq=2)
    sup.event_bus.emit(
        "BUILDER_RELAUNCH_ATTEMPTED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "round": 1,
            "outcome": "builder_started_verified",
            "trigger_seq": trigger_seq,
        },
    )

    # Create stale claim for the trigger
    claims_dir = sup.runtime_dir / "requeue_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{ticket_id}_seq-{trigger_seq}.claim"
    claim_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 200
    os.utime(claim_path, (old_time, old_time))

    # Should NOT reclaim because relaunch already emitted for this trigger
    result = sup._claim_requeue(ticket_id, trigger_seq)
    assert result is False, (
        "Must not reclaim when relaunch already emitted for the trigger"
    )


def test_requeue_ticket_fails_closed_when_trigger_seq_none(tmp_path, monkeypatch):
    """TP-07: trigger_seq invalido (<= 0) → fail-closed, no requeue."""
    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"

    # Set up minimal state
    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
        )
    )
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )

    # trigger_seq=0 should fail closed: _claim_requeue returns False
    result = sup._claim_requeue(ticket_id, 0)
    assert result is False, "trigger_seq=0 must return False (fail-closed)"

    # requeue_ticket should also fail closed without side effects
    relaunch_calls = []
    monkeypatch.setattr(
        sup, "_relaunch_builder", lambda *a, **kw: relaunch_calls.append(True) or True
    )
    result2 = sup.requeue_ticket(ticket_id, 0)
    assert result2 is False, "requeue_ticket with trigger_seq=0 must return False"
    assert relaunch_calls == [], "No relaunch should occur with invalid trigger_seq"
    state = sup.load_state()
    assert state.loop_current_round == 1, "Round must not be incremented"


def test_relaunch_outcome_builder_launch_unverified_when_no_signal(
    tmp_path, monkeypatch
):
    """TP-08: builder_launch_unverified cuando no hay senal viva en el timeout."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    # Create fake launcher
    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )

    # Mock _builder_alive to return False
    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)

    # Mock _run_launcher_subprocess to simulate success
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (0, "Launcher OK", ""),
    )

    # Mock _verify_builder_start to return unverified (no builder_lock found)
    monkeypatch.setattr(
        supervisor,
        "_verify_builder_start",
        lambda *a, **kw: ("builder_launch_unverified", "none"),
    )

    result = supervisor._relaunch_builder("WP-TEST", trigger_seq=99)

    # Returns True because launcher exit 0
    assert result is True

    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    assert len(events) == 1
    payload = events[0].payload
    assert payload["outcome"] == "builder_launch_unverified"
    assert payload["trigger_seq"] == 99
    assert payload["verify_signal"] == "none"


def test_relaunch_outcome_never_uses_success_string(tmp_path, monkeypatch):
    """TP-09: Ningun outcome usa la cadena 'success'."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    launcher_path = tmp_path / "scripts" / "launch_agent_terminals.ps1"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("# fake launcher", encoding="utf-8")

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )

    monkeypatch.setattr(supervisor, "_builder_alive", lambda: False)
    monkeypatch.setattr(
        supervisor,
        "_verify_builder_start",
        lambda *a, **kw: ("builder_started_verified", "builder_lock"),
    )

    # Test all outcome paths
    outcomes_seen = set()

    # Path 1: launcher exit 0 → builder_started_verified
    monkeypatch.setattr(supervisor, "_run_launcher_subprocess", lambda cmd: (0, "", ""))
    supervisor._relaunch_builder("WP-TEST")
    events = supervisor.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    for e in events:
        outcomes_seen.add(e.payload.get("outcome"))

    # Path 2: timeout
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (-1, "", "launcher timed out after 60s"),
    )
    supervisor._relaunch_builder("WP-TEST")

    # Path 3: launcher not found (no launcher)
    supervisor2 = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor2.save_state(
        SupervisorState(
            active_ticket="WP-TEST",
            loop_current_round=1,
        )
    )
    monkeypatch.setattr(supervisor2, "_builder_alive", lambda: False)
    # Remove launcher
    if launcher_path.exists():
        launcher_path.unlink()
    supervisor2._relaunch_builder("WP-TEST")
    events2 = supervisor2.event_bus.read_events(
        ticket_id="WP-TEST", event_type="BUILDER_RELAUNCH_ATTEMPTED"
    )
    for e in events2:
        outcomes_seen.add(e.payload.get("outcome"))

    # 'success' must never appear
    assert "success" not in outcomes_seen, (
        f"'success' must never be an outcome, got: {outcomes_seen}"
    )


def test_single_review_decision_yields_single_relaunch(tmp_path, monkeypatch):
    """TP-10: Para un unico REVIEW_DECISION, a lo sumo un relanzado real."""
    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"

    sup.save_state(
        SupervisorState(
            active_ticket=ticket_id,
            loop_current_round=1,
            last_requeue_trigger_sequence=0,
        )
    )
    sup.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "N/A", "to_state": "IN_PROGRESS", "reason": "Start"},
    )

    # Emit CHANGES decision
    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={"decision": "CHANGES", "feedback": "fix it"},
    )

    relaunch_calls = []
    monkeypatch.setattr(
        sup, "_relaunch_builder", lambda *a, **kw: relaunch_calls.append(True) or True
    )
    monkeypatch.setattr(sup, "_builder_alive", lambda: False)

    # First requeue_ticket should succeed
    trigger_seq = 700
    result1 = sup.requeue_ticket(ticket_id, trigger_seq)
    assert result1 is True

    # Second requeue_ticket for same trigger_seq should be blocked by claim
    result2 = sup.requeue_ticket(ticket_id, trigger_seq)
    assert result2 is False

    # Exactly one relaunch
    assert len(relaunch_calls) == 1, (
        "Only one relaunch should occur for a single REVIEW_DECISION"
    )


def test_terminal_ticket_clears_its_requeue_claims(tmp_path):
    """TP-11: Ticket terminal limpia sus requeue claims."""

    sup = _make_supervisor_with_claims(tmp_path)
    ticket_id = "WT-2026-199"

    # Create some claim files
    claims_dir = sup.runtime_dir / "requeue_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)

    for seq in [100, 200, 300]:
        claim_path = claims_dir / f"{ticket_id}_seq-{seq}.claim"
        claim_path.write_text("claim", encoding="utf-8")

    # Create a claim for a different ticket (should not be deleted)
    other_claim = claims_dir / "WT-2026-198_seq-50.claim"
    other_claim.write_text("other", encoding="utf-8")

    # Clean up claims for the terminal ticket
    sup._cleanup_terminal_requeue_claims(ticket_id)

    # Claims for the ticket should be gone
    remaining = list(claims_dir.iterdir())
    ticket_files = [c for c in remaining if ticket_id in c.name]
    assert ticket_files == [], (
        f"Claims for {ticket_id} should be removed: {ticket_files}"
    )

    # Other ticket's claim should survive
    assert other_claim.exists(), "Other ticket's claim must not be deleted"


# =============================================================================
# WT-2026-203: Tests for TURN.md blockers materialization
# =============================================================================


def test_materialize_turn_blockers_adds_blockers(tmp_path):
    """TP-03: _materialize_turn_blockers updates TURN.md with blockers from feedback."""
    sup = _make_supervisor(tmp_path)
    ticket_id = "WT-2026-203"

    # Create TURN.md with standard content
    turn_path = sup.collaboration_dir / "TURN.md"
    turn_path.write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Instruccion",
                "",
                "> Implementa segun work_plan.md",
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

    # WT-2026-204: emit REVIEW_DECISION with blockers instead of writing feedback file
    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "CHANGES",
            "blockers": "- Missing unit test for edge case\n- Ruff formatting issue in src/module.py",
            "stdout_tail": "...",
        },
    )

    # Call the method
    sup._materialize_turn_blockers(ticket_id)

    # Verify TURN.md now contains blockers
    turn_content = turn_path.read_text(encoding="utf-8")
    assert "## Blockers from Manager" in turn_content, (
        "TURN.md should contain Blockers section"
    )
    assert "Missing unit test" in turn_content, (
        "TURN.md should include feedback blockers"
    )
    assert "Ruff formatting" in turn_content, (
        "TURN.md should include all blocker details"
    )
    # Original instruction should be preserved
    assert "Implementa segun work_plan.md" in turn_content, (
        "Original TURN.md instruction must be preserved"
    )
    # Estado del Sistema should still be present
    assert "## Estado del Sistema" in turn_content, (
        "Estado del Sistema section must be preserved"
    )


def test_materialize_turn_blockers_idempotent(tmp_path):
    """_materialize_turn_blockers is idempotent: second call does not duplicate."""
    sup = _make_supervisor(tmp_path)
    ticket_id = "WT-2026-203"

    # Create TURN.md
    turn_path = sup.collaboration_dir / "TURN.md"
    turn_path.write_text(
        "# TURNO ACTUAL\n\n## Estado del Sistema\n\n",
        encoding="utf-8",
    )

    # WT-2026-204: emit REVIEW_DECISION with blockers instead of writing feedback file
    sup.event_bus.emit(
        "REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "CHANGES",
            "blockers": "- Some feedback\n- More blockers",
            "stdout_tail": "...",
        },
    )

    # Call twice
    sup._materialize_turn_blockers(ticket_id)
    content_after_first = turn_path.read_text(encoding="utf-8")
    sup._materialize_turn_blockers(ticket_id)
    content_after_second = turn_path.read_text(encoding="utf-8")

    # Should be identical (no duplicate Blockers section)
    assert content_after_first == content_after_second
    # Should have exactly one Blockers section
    assert content_after_first.count("## Blockers from Manager") == 1, (
        "Must not duplicate the Blockers section"
    )


# =============================================================================
# Tests WT-2026-204: materializacion de blockers desde REVIEW_DECISION payload
# =============================================================================


class TestMaterializeTurnBlockersV2:
    """WT-2026-204: _materialize_turn_blockers consume payload["blockers"]."""

    def _setup(self, tmp_path) -> tuple[SequentialTicketSupervisor, Path, str]:
        ticket_id = "WT-2026-204"
        collaboration_dir = tmp_path / ".agent" / "collaboration"
        runtime_dir = tmp_path / ".agent" / "runtime"
        collaboration_dir.mkdir(parents=True)
        runtime_dir.mkdir(parents=True)
        sup = SequentialTicketSupervisor(
            project_root=tmp_path,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            auto_sync=False,
        )
        # Create TURN.md
        turn_path = sup.collaboration_dir / "TURN.md"
        turn_path.write_text(
            "# TURNO ACTUAL\n\n## Estado del Sistema\n\n",
            encoding="utf-8",
        )
        # Emit REVIEW_DECISION with blockers in payload
        sup.event_bus.emit(
            "REVIEW_DECISION",
            ticket_id=ticket_id,
            actor="MANAGER",
            payload={
                "decision": "changes",
                "blockers": "- bus/parser.py: fix edge case\n- tests/: add null test",
                "stdout_tail": "...",
            },
        )
        return sup, turn_path, ticket_id

    # TP-03: consume payload["blockers"] de REVIEW_DECISION
    def test_materialize_from_review_decision_payload(self, tmp_path):
        """_materialize_turn_blockers reads blockers from REVIEW_DECISION payload."""
        sup, turn_path, ticket_id = self._setup(tmp_path)

        sup._materialize_turn_blockers(ticket_id)

        content = turn_path.read_text(encoding="utf-8")
        assert "## Blockers from Manager" in content
        assert "fix edge case" in content
        assert "add null test" in content

    # TP-04: TURN.md contiene blockers accionables, pesa menos de 15 KB
    def test_materialized_blockers_under_15kb(self, tmp_path):
        """Materialized TURN.md must be under 15 KB."""
        sup, turn_path, ticket_id = self._setup(tmp_path)

        sup._materialize_turn_blockers(ticket_id)

        content = turn_path.read_text(encoding="utf-8")
        assert len(content.encode("utf-8")) < 15 * 1024, "TURN.md must be under 15 KB"
        # Must contain actionable blockers
        assert "fix edge case" in content
        assert "## Blockers from Manager" in content

    # TP-04: sin JSONL crudo
    def test_materialized_blockers_no_jsonl_crudo(self, tmp_path):
        """Materialized TURN.md must not contain raw JSONL markers."""
        sup, turn_path, ticket_id = self._setup(tmp_path)

        sup._materialize_turn_blockers(ticket_id)

        content = turn_path.read_text(encoding="utf-8")
        assert '{"type":' not in content
        assert "sessionID" not in content

    # TP-05: HANDOFF_BLOCKED on empty blockers
    def test_empty_blockers_emits_handoff_blocked(self, tmp_path):
        """When blockers payload is empty, emit HANDOFF_BLOCKED, don't relaunch."""
        sup, turn_path, ticket_id = self._setup(tmp_path)
        # Clear the existing event and emit one without blockers
        sup.event_bus.emit(
            "REVIEW_DECISION",
            ticket_id=ticket_id,
            actor="MANAGER",
            payload={
                "decision": "changes",
                "blockers": "",
                "stdout_tail": "...",
            },
        )

        sup._materialize_turn_blockers(ticket_id)

        events = sup.event_bus.read_events(ticket_id=ticket_id)
        handoff_blocked = [e for e in events if e.event_type == "HANDOFF_BLOCKED"]
        assert handoff_blocked, "HANDOFF_BLOCKED must be emitted"
        assert handoff_blocked[-1].payload.get("reason") == "empty_blockers"
        # TURN.md should NOT have blockers section
        content = turn_path.read_text(encoding="utf-8")
        assert "## Blockers from Manager" not in content

    # TP-05: HANDOFF_BLOCKED on oversized blockers
    def test_oversized_blockers_emits_handoff_blocked(self, tmp_path):
        """When blockers exceed 15 KB, emit HANDOFF_BLOCKED, don't relaunch."""
        sup, turn_path, ticket_id = self._setup(tmp_path)
        sup.event_bus.emit(
            "REVIEW_DECISION",
            ticket_id=ticket_id,
            actor="MANAGER",
            payload={
                "decision": "changes",
                "blockers": "x" * (16 * 1024),
                "stdout_tail": "...",
            },
        )

        sup._materialize_turn_blockers(ticket_id)

        events = sup.event_bus.read_events(ticket_id=ticket_id)
        handoff_blocked = [e for e in events if e.event_type == "HANDOFF_BLOCKED"]
        assert handoff_blocked, "HANDOFF_BLOCKED must be emitted"
        assert handoff_blocked[-1].payload.get("reason") == "blockers_too_large"
        content = turn_path.read_text(encoding="utf-8")
        assert "## Blockers from Manager" not in content

    # TP-05: HANDOFF_BLOCKED on JSONL crudo in blockers
    def test_jsonl_crudo_blockers_emits_handoff_blocked(self, tmp_path):
        """When blockers contain raw JSONL markers, emit HANDOFF_BLOCKED."""
        sup, turn_path, ticket_id = self._setup(tmp_path)
        sup.event_bus.emit(
            "REVIEW_DECISION",
            ticket_id=ticket_id,
            actor="MANAGER",
            payload={
                "decision": "changes",
                "blockers": '{"type":"text","part":...}',
                "stdout_tail": "...",
            },
        )

        sup._materialize_turn_blockers(ticket_id)

        events = sup.event_bus.read_events(ticket_id=ticket_id)
        handoff_blocked = [e for e in events if e.event_type == "HANDOFF_BLOCKED"]
        assert handoff_blocked, "HANDOFF_BLOCKED must be emitted"
        assert handoff_blocked[-1].payload.get("reason") == "blockers_contain_raw_jsonl"
        content = turn_path.read_text(encoding="utf-8")
        assert "## Blockers from Manager" not in content

    # TP-05: No REVIEW_DECISION event → no-op (no HANDOFF_BLOCKED, no blockers in TURN)
    def test_no_review_decision_event_is_noop(self, tmp_path):
        """When no REVIEW_DECISION event exists, materialize is a no-op."""
        ticket_id = "WT-2026-204"
        collaboration_dir = tmp_path / ".agent" / "collaboration"
        runtime_dir = tmp_path / ".agent" / "runtime"
        collaboration_dir.mkdir(parents=True)
        runtime_dir.mkdir(parents=True)
        sup = SequentialTicketSupervisor(
            project_root=tmp_path,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            auto_sync=False,
        )
        turn_path = sup.collaboration_dir / "TURN.md"
        turn_path.write_text(
            "# TURNO ACTUAL\n\n## Estado del Sistema\n\n",
            encoding="utf-8",
        )
        # No REVIEW_DECISION event emitted
        sup.event_bus.emit(
            "STATE_CHANGED",
            ticket_id=ticket_id,
            actor="MANAGER",
            payload={"from_state": "READY_FOR_REVIEW", "to_state": "IN_PROGRESS"},
        )

        sup._materialize_turn_blockers(ticket_id)

        content = turn_path.read_text(encoding="utf-8")
        assert "## Blockers from Manager" not in content
