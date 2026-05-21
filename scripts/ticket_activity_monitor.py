#!/usr/bin/env python3
"""Live monitor for the active ticket's event activity."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLAB_DIR = PROJECT_ROOT / ".agent" / "collaboration"
EVENTS_PATH = PROJECT_ROOT / ".agent" / "runtime" / "events" / "events.jsonl"
STATE_PATH = PROJECT_ROOT / ".agent" / "runtime" / "supervisor_state.json"


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _active_ticket_from_work_plan() -> str | None:
    work_plan_path = COLLAB_DIR / "work_plan.md"
    if not work_plan_path.exists():
        return None
    content = work_plan_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        # Match "- **Plan activo:** WP-YYYY-XXX" and extract ticket ID robustly
        match = re.search(
            r"Plan\s+activo.*?:\s*(WP-\d{4}-[A-Za-z0-9]+)", line, re.IGNORECASE
        )
        if match:
            ticket = match.group(1).strip().lstrip("*").rstrip("*").strip()
            return ticket
    return None


def _active_ticket() -> str | None:
    state = _read_json(STATE_PATH)
    ticket = state.get("active_ticket")
    if isinstance(ticket, str) and ticket:
        return ticket
    return _active_ticket_from_work_plan()


def _derive_state(events: list[dict[str, object]]) -> str:
    if not events:
        return "IN_PROGRESS"
    latest = events[-1]
    event_type = str(latest.get("event_type", ""))
    payload = latest.get("payload", {})
    if isinstance(payload, dict):
        to_state = payload.get("to_state")
        if isinstance(to_state, str) and to_state:
            return to_state
    if event_type == "REVIEW_DECISION":
        decision = (
            str(payload.get("decision", "")).upper()
            if isinstance(payload, dict)
            else ""
        )
        if decision == "APPROVE":
            return "READY_TO_CLOSE"
    return "IN_PROGRESS"


def _load_events(ticket_id: str) -> list[dict[str, object]]:
    if not EVENTS_PATH.exists():
        return []

    events: list[dict[str, object]] = []
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(event.get("ticket_id", "")) != ticket_id:
            continue
        events.append(event)
    return events


def _format_line(event: dict[str, object]) -> str:
    timestamp = str(event.get("timestamp", ""))
    actor = str(event.get("actor", ""))
    event_type = str(event.get("event_type", ""))
    seq = event.get("sequence_number", "")
    payload = event.get("payload", {})
    state_hint = ""
    if isinstance(payload, dict):
        state_hint = str(payload.get("to_state") or payload.get("decision") or "")
    suffix = f" -> {state_hint}" if state_hint else ""
    return f"{timestamp} | seq={seq} | {actor:<9} | {event_type:<18}{suffix}"


def _print_snapshot(ticket_id: str, events: list[dict[str, object]]) -> None:
    state = _derive_state(events)
    latest_ts = str(events[-1].get("timestamp", "n/a")) if events else "n/a"
    print("=" * 72)
    print(f"Ticket activo : {ticket_id}")
    print(f"Estado        : {state}")
    print(f"Eventos       : {len(events)}")
    print(f"Ultimo evento : {latest_ts}")
    print("-" * 72)
    for event in events[-12:]:
        print(_format_line(event))
    print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live monitor for the active ticket")
    parser.add_argument("--ticket-id", type=str, help="Explicit ticket to monitor")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ticket_id = args.ticket_id or _active_ticket()
    if not ticket_id:
        print("[monitor] No active ticket found.")
        return 1

    last_signature = ""
    while True:
        events = _load_events(ticket_id)
        signature = (
            f"{len(events)}|{events[-1].get('sequence_number') if events else 0}"
        )
        if signature != last_signature:
            _print_snapshot(ticket_id, events)
            last_signature = signature
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
