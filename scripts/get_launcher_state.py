#!/usr/bin/env python3
"""Return canonical launcher state derived from the bus.

WT-2026-216: the launcher must not derive operational role from TURN.md.
This helper reads the active ticket from work_plan.md, derives TicketState
via StateMachine.derive_state_from_events(), and returns a compact JSON
payload that PowerShell can consume safely.

WT-2026-225a: before deriving state, detects projection drift between
supervisor_state.json:last_processed_sequence and the bus max sequence.
If drift is confirmed (bus ahead of projection), reprojects STATE.md and
TURN.md from the derived bus state before returning the launcher decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[1]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from bus.event_bus import EventBus  # noqa: E402
from bus.state_machine import StateMachine, TicketState  # noqa: E402


WORK_PLAN_REL = Path(".agent") / "collaboration" / "work_plan.md"
RUNTIME_EVENTS_REL = Path(".agent") / "runtime" / "events"
SUPERVISOR_STATE_REL = Path(".agent") / "runtime" / "supervisor_state.json"
_TICKET_PATTERN = re.compile(r"\*\*ID:\*\*\s*([A-Z][A-Z0-9]*-\d{4}-[A-Za-z0-9-]+)")


def _read_active_ticket(project_root: Path) -> str:
    work_plan_path = project_root / WORK_PLAN_REL
    if not work_plan_path.exists():
        raise RuntimeError(f"work_plan.md not found: {work_plan_path}")
    content = work_plan_path.read_text(encoding="utf-8")
    match = _TICKET_PATTERN.search(content)
    if not match:
        raise RuntimeError("Unable to derive active ticket from work_plan.md")
    return match.group(1)


def _load_json_safe(path: Path) -> dict | None:
    """Load a JSON file safely, returning None on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _render_turn_for_state(ticket_id: str, state: TicketState) -> str:
    """Render TURN.md content for the given ticket and state.

    Mirrors the canonical format from bus/supervisor.py:_render_turn_for_state
    to avoid importing the full supervisor module.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    turn_map: dict[TicketState, tuple[str, str, str, str]] = {
        TicketState.READY_FOR_REVIEW: (
            "MANAGER",
            "REVIEW_WORK",
            f"Builder completo {ticket_id}. Revisa el trabajo.",
            "APPROVED",
        ),
        TicketState.READY_TO_CLOSE: (
            "SUPERVISOR",
            "CLOSEOUT",
            f"Ticket {ticket_id} aprobado. Procede al cierre.",
            "APPROVED",
        ),
        TicketState.IN_PROGRESS: (
            "BUILDER",
            "IMPLEMENT",
            f"Ticket {ticket_id} reactivado. Continua la implementacion.",
            "IN_PROGRESS",
        ),
        TicketState.HUMAN_GATE: (
            "SUPERVISOR",
            "HUMAN_GATE",
            f"Escalada humana requerida para {ticket_id}.",
            "BLOCKED",
        ),
        TicketState.COMPLETED: (
            "MANAGER",
            "CREATE_PLAN",
            f"Ticket {ticket_id} cerrado. Crea el siguiente work_plan.md.",
            "COMPLETED",
        ),
        TicketState.BLOCKED: (
            "SUPERVISOR",
            "BLOCKED",
            f"Ticket {ticket_id} bloqueado. Revisa los bloqueadores.",
            "BLOCKED",
        ),
    }
    role, action_type, instruction, work_plan_status = turn_map.get(
        state,
        (
            "UNKNOWN",
            "STATE_TRANSITION",
            f"Estado materializado desde el bus: {state.value}.",
            state.value,
        ),
    )
    return (
        "# TURNO ACTUAL\n\n"
        f"**Ultima actualizacion:** {timestamp}\n\n"
        "---\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        f"| **ROL** | **{role}** |\n"
        f"| **Plan ID** | {ticket_id} |\n"
        "| **Tipo** | IMPLEMENT |\n"
        f"| **Accion** | {action_type} |\n"
        "\n---\n\n"
        "## Instruccion\n\n"
        f"> {instruction}\n\n"
        "---\n\n"
        "## Estado del Sistema\n\n"
        "| Archivo | Estado |\n"
        "|---------|--------|\n"
        f"| work_plan.md | {work_plan_status} |\n"
        f"| execution_log.md | {state.value} |\n"
        "\n---\n\n"
        f"*Preparado documentalmente para {ticket_id}*\n"
    )


def _check_and_reconcile_drift(project_root: Path, ticket_id: str) -> dict:
    """Detect if the bus is ahead of the last_processed_sequence and reproject.

    Reads supervisor_state.json:last_processed_sequence and compares it with
    the max sequence_number in the bus. If the bus is ahead, derives the
    canonical state from bus events and reprojects STATE.md and TURN.md.

    Before: supervisor_state.json must exist. Bus events may or may not exist.
    During: Compares sequence numbers; if drift confirmed, writes STATE.md
            and TURN.md directly from the derived bus state.
    After: Returns dict with drift_detected, last_processed_sequence,
           max_bus_sequence, and reconciled status. No files are modified
           unless drift is confirmed.

    Returns:
        dict with keys:
            drift_detected (bool): True if drift was found and corrected.
            reconciled (bool): True if reprojection succeeded (only set when
                              drift_detected is True).
            last_processed_sequence (int): Value from supervisor_state.json.
            max_bus_sequence (int): Max sequence number from bus events.
            reason (str): Human-readable reason for the outcome.
    """
    result: dict = {"drift_detected": False}

    sup_state = _load_json_safe(project_root / SUPERVISOR_STATE_REL)
    if sup_state is None:
        result["reason"] = "no_supervisor_state"
        return result

    last_processed = int(sup_state.get("last_processed_sequence", 0))

    event_bus = EventBus(runtime_dir=project_root / RUNTIME_EVENTS_REL)
    all_events = event_bus.read_events(ticket_id=ticket_id)

    if not all_events:
        result["reason"] = "no_bus_events_for_ticket"
        result["last_processed_sequence"] = last_processed
        return result

    max_seq = all_events[-1].sequence_number
    result["last_processed_sequence"] = last_processed
    result["max_bus_sequence"] = max_seq

    if last_processed >= max_seq:
        result["reason"] = "projection_up_to_date"
        return result

    # Drift confirmed: bus is ahead of projection
    result["drift_detected"] = True

    try:
        events_dicts = [e.to_dict() for e in all_events]
        state = StateMachine.derive_state_from_events(events_dicts)

        collab_dir = project_root / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)

        # Reproject STATE.md
        state_path = collab_dir / "STATE.md"
        state_path.write_text(
            f"ACTIVE_TICKET: {ticket_id}\nSTATUS: {state.value}\n",
            encoding="utf-8",
        )

        # Reproject TURN.md
        turn_path = collab_dir / "TURN.md"
        turn_content = _render_turn_for_state(ticket_id, state)
        turn_path.write_text(turn_content, encoding="utf-8")

        result["reconciled"] = True
        result["derived_state"] = state.value
        result["reason"] = "drift_detected_and_reconciled"
    except Exception as exc:
        result["reconciled"] = False
        result["reason"] = f"reconciliation_failed: {exc}"

    return result


def _role_action_for_state(state: TicketState) -> tuple[str, str]:
    mapping: dict[TicketState, tuple[str, str]] = {
        TicketState.READY_FOR_REVIEW: ("MANAGER", "REVIEW_WORK"),
        TicketState.READY_TO_CLOSE: ("SUPERVISOR", "CLOSEOUT"),
        TicketState.IN_PROGRESS: ("BUILDER", "IMPLEMENT"),
        TicketState.HUMAN_GATE: ("SUPERVISOR", "HUMAN_GATE"),
        TicketState.COMPLETED: ("MANAGER", "CREATE_PLAN"),
        TicketState.BLOCKED: ("SUPERVISOR", "BLOCKED"),
    }
    return mapping.get(state, ("BUILDER", "IMPLEMENT"))


def derive_launcher_state(project_root: Path) -> dict[str, str]:
    ticket_id = _read_active_ticket(project_root)

    # WT-2026-225a: Detect and correct projection drift before deriving state.
    # If last_processed_sequence < max bus seq, reproject STATE.md and TURN.md
    # from the derived bus state before the launcher makes its role decision.
    drift_result = _check_and_reconcile_drift(project_root, ticket_id)

    event_bus = EventBus(runtime_dir=project_root / RUNTIME_EVENTS_REL)
    events = [record.to_dict() for record in event_bus.read_events(ticket_id=ticket_id)]
    state = StateMachine.derive_state_from_events(events)
    role, action = _role_action_for_state(state)
    payload: dict[str, str] = {
        "ticket_id": ticket_id,
        "state": state.value,
        "role": role,
        "action": action,
        "source": "event_bus",
    }

    if drift_result.get("drift_detected"):
        payload["reconciled"] = "true" if drift_result.get("reconciled") else "failed"
        payload["reconcile_reason"] = str(drift_result.get("reason", ""))

    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Get canonical launcher state")
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Workspace project root whose bus should be read",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = derive_launcher_state(args.project_root.resolve())
    except Exception as exc:  # pragma: no cover - exercised via CLI contract
        print(f"[get-launcher-state] {exc}", file=sys.stderr, flush=True)
        return 1
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
