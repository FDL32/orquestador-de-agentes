#!/usr/bin/env python3
"""Return canonical launcher state derived from the bus.

WT-2026-216: the launcher must not derive operational role from TURN.md.
This helper reads the active ticket from work_plan.md, derives TicketState
via StateMachine.derive_state_from_events(), and returns a compact JSON
payload that PowerShell can consume safely.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[1]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from bus.event_bus import EventBus  # noqa: E402
from bus.state_machine import StateMachine, TicketState  # noqa: E402


WORK_PLAN_REL = Path(".agent") / "collaboration" / "work_plan.md"
RUNTIME_EVENTS_REL = Path(".agent") / "runtime" / "events"
_TICKET_PATTERN = re.compile(r"\*\*ID:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9-]+)")


def _read_active_ticket(project_root: Path) -> str:
    work_plan_path = project_root / WORK_PLAN_REL
    if not work_plan_path.exists():
        raise RuntimeError(f"work_plan.md not found: {work_plan_path}")
    content = work_plan_path.read_text(encoding="utf-8")
    match = _TICKET_PATTERN.search(content)
    if not match:
        raise RuntimeError("Unable to derive active ticket from work_plan.md")
    return match.group(1)


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
    event_bus = EventBus(runtime_dir=project_root / RUNTIME_EVENTS_REL)
    events = [record.to_dict() for record in event_bus.read_events(ticket_id=ticket_id)]
    state = StateMachine.derive_state_from_events(events)
    role, action = _role_action_for_state(state)
    return {
        "ticket_id": ticket_id,
        "state": state.value,
        "role": role,
        "action": action,
        "source": "event_bus",
    }


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
