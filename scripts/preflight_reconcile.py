#!/usr/bin/env python3
"""Preflight reconcile decision for the launcher.

Called from launch_agent_terminals.ps1 to determine whether the previous
ticket (from stale runtime state) needs canonical reconciliation or just
local cleanup.

Exit codes:
  0 = decision made (JSON on stdout)
  1 = error (message on stderr)
  2 = ABORT decision (JSON on stdout with reason)

Decisions:
  ALIGNED       - No drift; proceed normally.
  CLEANUP_LOCAL - Previous ticket is terminal; just clean local state.
  RECONCILE     - Previous ticket is non-terminal; reconcile first.
  ABORT         - Bus illegible or contradictory; stop.

Before (Pre-condiciones):
- project_root must be a valid workspace with .agent/runtime/ structure.
- work_plan_id is the current active ticket ID extracted from work_plan.md.
- supervisor_state.json and/or manager_bridge_state.json may or may not exist.

During (Proceso y Recursos):
- Reads supervisor_state.json and manager_bridge_state.json from the runtime.
- Resolves the previous ticket ID from stale runtime state.
- Reads bus events (events.jsonl) for the previous ticket.
- Derives the previous ticket state via StateMachine.derive_state_from_events().
- Returns a JSON decision object on stdout.

After (Post-condiciones y Errores):
- Does NOT modify any files on disk (pure read).
- Returns exit code 0 for ALIGNED/CLEANUP_LOCAL/RECONCILE.
- Returns exit code 2 for ABORT.
- Returns exit code 1 on internal errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MOTOR_ROOT = Path(__file__).resolve().parents[1]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from bus.state_machine import StateMachine  # noqa: E402


RUNTIME_REL = Path(".agent") / "runtime"
EVENTS_REL = RUNTIME_REL / "events" / "events.jsonl"
SUPERVISOR_STATE_REL = RUNTIME_REL / "supervisor_state.json"
MANAGER_BRIDGE_STATE_REL = RUNTIME_REL / "manager_bridge_state.json"

INVALID_TICKET_VALUES = {"", "none", "null", "unknown", "n/a"}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _normalize_ticket_id(value: Any) -> str | None:
    if value is None:
        return None
    ticket = str(value).strip()
    if ticket.lower() in INVALID_TICKET_VALUES:
        return None
    return ticket if ticket else None


def _read_events_for_ticket(events_path: Path, ticket_id: str) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []

    ticket_records = [
        e for e in records if _normalize_ticket_id(e.get("ticket_id")) == ticket_id
    ]
    ticket_records.sort(key=lambda item: int(item.get("sequence_number", 0)))
    return ticket_records


def _derive_ticket_state(events: list[dict[str, Any]]) -> str | None:
    if not events:
        return None
    try:
        state = StateMachine.derive_state_from_events(events)
        return state.value if state else None
    except Exception:
        return None


def _resolve_prev_ticket_id(
    supervisor_state: dict[str, Any] | None,
    bridge_state: dict[str, Any] | None,
) -> str | None:
    """Get the previous ticket ID from stale runtime state.

    Checks supervisor_state.active_ticket first, then falls back to
    manager_bridge_state.last_ticket_id.
    """
    if supervisor_state:
        tid = _normalize_ticket_id(supervisor_state.get("active_ticket"))
        if tid:
            return tid
    if bridge_state:
        tid = _normalize_ticket_id(bridge_state.get("last_ticket_id"))
        if tid:
            return tid
    return None


def _terminal_state(state: str) -> bool:
    """Check if a state is terminal (irreversible).

    Mirrors reconcile_ticket.py TERMINAL_STATES logic: COMPLETED is the
    canonical irreversible state from the state machine. CLOSED is also
    recognised for tickets that received SUPERVISOR_CLOSED without a
    preceding STATE_CHANGED->COMPLETED.
    """
    return state.upper() in {"COMPLETED", "CLOSED"}


def derive_preflight_decision(
    project_root: Path,
    work_plan_id: str,
    supervisor_state: dict[str, Any] | None = None,
    bridge_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the preflight decision from current runtime state.

    Cases resolved (in priority order):
    1. No prev_ticket_id or matches current → ALIGNED
    2. Prev ticket state is terminal → CLEANUP_LOCAL
    3. Prev ticket state non-terminal → RECONCILE
    4. Bus illegible/unreadable for prev ticket → ABORT
    """
    prev_ticket_id = _resolve_prev_ticket_id(supervisor_state, bridge_state)

    # Case 1: No drift
    if not prev_ticket_id or prev_ticket_id == work_plan_id:
        return {
            "decision": "ALIGNED",
            "prev_ticket_id": prev_ticket_id,
            "prev_ticket_state": None,
            "reason": "No drift detected between work plan and runtime state.",
            "bus_ok": True,
        }

    # Read bus events for previous ticket to determine terminality
    events_path = project_root / EVENTS_REL
    prev_events = _read_events_for_ticket(events_path, prev_ticket_id)

    if not prev_events:
        # No bus events for prev ticket → can't determine terminality
        return {
            "decision": "ABORT",
            "prev_ticket_id": prev_ticket_id,
            "prev_ticket_state": None,
            "reason": (
                f"No bus events found for previous ticket {prev_ticket_id}. "
                "Cannot determine whether it is terminal. Manual investigation required."
            ),
            "bus_ok": False,
        }

    prev_state = _derive_ticket_state(prev_events)
    if prev_state is None:
        # State derivation failed (corrupt events, state machine error, etc.)
        return {
            "decision": "ABORT",
            "prev_ticket_id": prev_ticket_id,
            "prev_ticket_state": None,
            "reason": (
                f"Failed to derive state for {prev_ticket_id} from bus events. "
                "The event bus may be corrupt or contain unrecognised transitions."
            ),
            "bus_ok": False,
        }

    # Case 2: Terminal → cleanup only
    if _terminal_state(prev_state):
        return {
            "decision": "CLEANUP_LOCAL",
            "prev_ticket_id": prev_ticket_id,
            "prev_ticket_state": prev_state,
            "reason": (
                f"Previous ticket {prev_ticket_id} is already terminal "
                f"({prev_state}). No reconciliation needed."
            ),
            "bus_ok": True,
        }

    # Case 3: Non-terminal → reconcile
    return {
        "decision": "RECONCILE",
        "prev_ticket_id": prev_ticket_id,
        "prev_ticket_state": prev_state,
        "reason": (
            f"Previous ticket {prev_ticket_id} is non-terminal ({prev_state}). "
            "Canonical reconciliation required before cleanup."
        ),
        "bus_ok": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight reconcile decision for the launcher."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Workspace project root.",
    )
    parser.add_argument(
        "--work-plan-id",
        type=str,
        required=True,
        help="Current ticket ID from work_plan.md.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    supervisor_state = _load_json(project_root / SUPERVISOR_STATE_REL)
    bridge_state = _load_json(project_root / MANAGER_BRIDGE_STATE_REL)

    decision = derive_preflight_decision(
        project_root=project_root,
        work_plan_id=args.work_plan_id,
        supervisor_state=supervisor_state,
        bridge_state=bridge_state,
    )

    print(json.dumps(decision, ensure_ascii=False), flush=True)

    if decision["decision"] == "ABORT":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
