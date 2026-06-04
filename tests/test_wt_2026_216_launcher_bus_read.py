from __future__ import annotations

import json
import sys
from pathlib import Path

from bus.event_bus import EventBus
from bus.state_machine import TicketState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "launch_agent_terminals.ps1"

sys.path.insert(0, str(PROJECT_ROOT))

from scripts.get_launcher_state import derive_launcher_state  # noqa: E402


def _write_work_plan(project_root: Path, ticket_id: str) -> None:
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text(
        "\n".join(
            [
                f"# Work Ticket - {ticket_id}",
                "",
                "## Metadata",
                f"- **ID:** {ticket_id}",
                "- **Estado:** APPROVED",
            ]
        ),
        encoding="utf-8",
    )


def test_derive_launcher_state_uses_bus_for_ready_for_review(tmp_path: Path) -> None:
    ticket_id = "WT-2026-216"
    _write_work_plan(tmp_path, ticket_id)
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"
    assert state["action"] == "REVIEW_WORK"
    assert state["source"] == "event_bus"


def test_derive_launcher_state_defaults_to_builder_for_unknown_bus(
    tmp_path: Path,
) -> None:
    ticket_id = "WT-2026-216"
    _write_work_plan(tmp_path, ticket_id)

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.UNKNOWN.value
    assert state["role"] == "BUILDER"
    assert state["action"] == "IMPLEMENT"


def test_derive_launcher_state_accepts_custom_ticket_prefix(tmp_path: Path) -> None:
    ticket_id = "ABC-2026-101"
    _write_work_plan(tmp_path, ticket_id)
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"


def test_launcher_script_uses_python_helper_before_turn_fallback() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "scripts\\get_launcher_state.py" in content
    assert "--project-root $ProjectRoot" in content
    assert "ConvertFrom-Json" in content
    assert "Recurriendo a TURN.md como fallback" in content


# ---------------------------------------------------------------------------
# WT-2026-225a: Durable projection catch-up — drift detection + reprojection
# ---------------------------------------------------------------------------


def _write_supervisor_state(
    project_root: Path, *, last_processed_sequence: int
) -> None:
    """Write a supervisor_state.json with the given last_processed_sequence."""
    runtime = project_root / ".agent" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "supervisor_state.json").write_text(
        json.dumps({"last_processed_sequence": last_processed_sequence}),
        encoding="utf-8",
    )


def _write_stale_state_md(project_root: Path, ticket_id: str, status: str) -> None:
    """Write a STATE.md with an arbitrary status (possibly stale)."""
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        f"ACTIVE_TICKET: {ticket_id}\nSTATUS: {status}\n",
        encoding="utf-8",
    )


def test_derive_launcher_state_detects_drift_when_bus_ahead(tmp_path: Path) -> None:
    """WT-2026-225a TP-02: drift detected when last_processed_sequence < max bus seq.

    Reproduce FP-001: bus has READY_FOR_REVIEW but last_processed_sequence
    is behind (e.g., 0) and STATE.md shows IN_PROGRESS.
    """
    ticket_id = "WT-2026-225"
    _write_work_plan(tmp_path, ticket_id)
    _write_supervisor_state(tmp_path, last_processed_sequence=0)
    _write_stale_state_md(tmp_path, ticket_id, "IN_PROGRESS")

    # Bus has events advancing to READY_FOR_REVIEW
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # The helper should detect drift and reproject STATE.md/TURN.md
    state = derive_launcher_state(tmp_path)

    # Verify the correct state is returned (bus-derived)
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"
    assert state["action"] == "REVIEW_WORK"

    # Verify drift was detected and reconciled
    assert state.get("reconciled") == "true"

    # Verify STATE.md was reprojected
    state_md = (tmp_path / ".agent" / "collaboration" / "STATE.md").read_text(
        encoding="utf-8"
    )
    assert "STATUS: READY_FOR_REVIEW" in state_md

    # Verify TURN.md was reprojected (should show MANAGER role)
    turn_md = (tmp_path / ".agent" / "collaboration" / "TURN.md").read_text(
        encoding="utf-8"
    )
    assert "**ROL** | **MANAGER**" in turn_md
    assert "**Accion** | REVIEW_WORK" in turn_md


def test_derive_launcher_state_skips_reconciliation_when_aligned(
    tmp_path: Path,
) -> None:
    """WT-2026-225a TP-03: no reconciliation when last_processed_sequence >= max bus seq.

    When the supervisor has already processed all events, the projections
    should remain unchanged.
    """
    ticket_id = "WT-2026-225"
    _write_work_plan(tmp_path, ticket_id)
    _write_stale_state_md(tmp_path, ticket_id, "IN_PROGRESS")

    # First emit a bus event
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # Set last_processed_sequence equal to max seq (already caught up)
    # The first event has seq=1
    _write_supervisor_state(tmp_path, last_processed_sequence=1)

    state = derive_launcher_state(tmp_path)

    # Verify correct state
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"

    # Verify no reconciliation was needed
    assert "reconciled" not in state

    # Verify STATE.md is unchanged (still shows IN_PROGRESS because
    # no drift was detected, so no reprojection occurred)
    state_md = (tmp_path / ".agent" / "collaboration" / "STATE.md").read_text(
        encoding="utf-8"
    )
    assert "STATUS: IN_PROGRESS" in state_md


def test_derive_launcher_state_reconciles_state_and_turn(tmp_path: Path) -> None:
    """WT-2026-225a TP-04: catch-up leaves verifiable evidence in STATE.md and TURN.md.

    When drift is detected, both projection files must be updated to reflect
    the derived bus state.
    """
    ticket_id = "WT-2026-225"
    _write_work_plan(tmp_path, ticket_id)
    _write_supervisor_state(tmp_path, last_processed_sequence=0)

    # Write stale STATE.md with IN_PROGRESS and stale TURN.md with BUILDER role
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        "ACTIVE_TICKET: WT-2026-225\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    stale_turn = (
        "# TURNO ACTUAL\n\n"
        "**Ultima actualizacion:** 2026-01-01 00:00:00\n\n"
        "---\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | WT-2026-225 |\n"
        "| **Tipo** | IMPLEMENT |\n"
        "| **Accion** | IMPLEMENT |\n"
        "\n---\n\n"
        "## Instruccion\n\n"
        "> Continua la implementacion.\n\n"
        "---\n\n"
        "## Estado del Sistema\n\n"
        "| Archivo | Estado |\n"
        "|---------|--------|\n"
        "| work_plan.md | IN_PROGRESS |\n"
        "| execution_log.md | IN_PROGRESS |\n"
        "\n---\n\n"
        "*Preparado documentalmente para WT-2026-225*\n"
    )
    (collab / "TURN.md").write_text(stale_turn, encoding="utf-8")

    # Emit bus events that transition to READY_FOR_REVIEW
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    # Verify drift was detected and reconciled
    assert state.get("reconciled") == "true"
    assert state["state"] == TicketState.READY_FOR_REVIEW.value

    # Verify STATE.md was updated
    state_md = (collab / "STATE.md").read_text(encoding="utf-8")
    assert "STATUS: READY_FOR_REVIEW" in state_md

    # Verify TURN.md was updated to MANAGER
    turn_md = (collab / "TURN.md").read_text(encoding="utf-8")
    assert "**ROL** | **MANAGER**" in turn_md
    assert "**Accion** | REVIEW_WORK" in turn_md

    # Verify execution_log status was not touched (only STATE.md/TURN.md
    # are reprojected by the launcher helper)
    # Note: TURN.md should reference the derived state
    assert "READY_FOR_REVIEW" in turn_md or "APPROVED" in turn_md


def test_derive_launcher_state_skips_when_no_supervisor_state(tmp_path: Path) -> None:
    """WT-2026-225a edge case: no supervisor_state.json => skip drift check gracefully."""
    ticket_id = "WT-2026-225"
    _write_work_plan(tmp_path, ticket_id)
    # No supervisor_state.json written

    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    # State derived correctly even without drift check
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"
    assert "reconciled" not in state


def test_derive_launcher_state_drift_fallback_when_bus_empty(tmp_path: Path) -> None:
    """WT-2026-225a edge case: no bus events for ticket => drift check is skipped."""
    ticket_id = "WT-2026-225"
    _write_work_plan(tmp_path, ticket_id)
    _write_supervisor_state(tmp_path, last_processed_sequence=5)
    _write_stale_state_md(tmp_path, ticket_id, "IN_PROGRESS")

    # No events emitted
    state = derive_launcher_state(tmp_path)

    # Falls through to UNKNOWN state
    assert "reconciled" not in state
