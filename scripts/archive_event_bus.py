"""Archive terminal ticket events from the canonical event bus.

Before:
    - The event bus already exposes EventBus.archive_ticket_events(ticket_id)
      but only tests call it.
    - The active bus keeps growing without an operational rotation entrypoint.

During:
    - Read events from .agent/runtime/events/events.jsonl.
    - Determine closed tickets from the latest STATE_CHANGED event
      (COMPLETED or HUMAN_GATE).
    - Archive those tickets through EventBus.archive_ticket_events().
    - Support explicit ticket selection and dry-run reporting.

After:
    - Closed tickets are moved to .agent/runtime/events/archive/events.<id>.jsonl.
    - The active bus keeps only non-terminal tickets.
    - The script exits non-zero only on operational failure.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime or bus modules.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

from bus.event_bus import EventBus  # noqa: E402

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


_PROJECT_ROOT = resolve_project_root()
EVENTS_DIR = _PROJECT_ROOT / ".agent" / "runtime" / "events"

TERMINAL_STATES = {"COMPLETED", "HUMAN_GATE"}


def _iter_terminal_tickets(event_bus: EventBus) -> list[str]:
    tickets: dict[str, str] = {}
    for record in event_bus.read_events(event_type="STATE_CHANGED"):
        to_state = record.payload.get("to_state") or record.payload.get("state")
        if record.ticket_id and to_state:
            tickets[record.ticket_id] = str(to_state)
    return sorted(
        ticket_id for ticket_id, state in tickets.items() if state in TERMINAL_STATES
    )


def _archive_ticket(event_bus: EventBus, ticket_id: str, dry_run: bool) -> dict:
    if dry_run:
        total = len(event_bus.read_events(ticket_id=ticket_id))
        return {
            "ticket_id": ticket_id,
            "dry_run": True,
            "archived_count": total,
            "archive_path": str(
                event_bus.runtime_dir / "archive" / f"events.{ticket_id}.jsonl"
            ),
        }
    return event_bus.archive_ticket_events(ticket_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive terminal tickets from the canonical event bus."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticket", help="Archive a single ticket by ID.")
    group.add_argument(
        "--all-terminal",
        action="store_true",
        help="Archive every ticket whose latest STATE_CHANGED is terminal.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be archived without writing files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    event_bus = EventBus(EVENTS_DIR)
    ticket_ids = [args.ticket] if args.ticket else _iter_terminal_tickets(event_bus)

    if not ticket_ids:
        print(
            json.dumps({"status": "no-op", "reason": "no_terminal_tickets"}, indent=2)
        )
        return 0

    results = [
        _archive_ticket(event_bus, ticket_id, args.dry_run) for ticket_id in ticket_ids
    ]
    print(json.dumps({"status": "ok", "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
