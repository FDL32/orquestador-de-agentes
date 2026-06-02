#!/usr/bin/env python3
"""Reconcile a ticket runtime and close it canonically.

This utility is the maintenance bridge for ticket forced-close / freeze
operations. It is intentionally conservative:

- It only touches the runtime surfaces for the target ticket.
- It appends canonical bus events only when they are missing.
- It cleans stale runtime artifacts tied to the target ticket.
- It does not auto-hook into the launcher yet.

The intended use is to close a ticket that was left in a non-terminal state
while the documentation moved on to a new ticket, so the next ticket can start
without inheriting stale runtime state.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MOTOR_ROOT = Path(__file__).resolve().parents[1]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from bus.event_bus import EventBus  # noqa: E402
from bus.state_machine import StateMachine  # noqa: E402


RUNTIME_REL = Path(".agent") / "runtime"
EVENTS_REL = RUNTIME_REL / "events" / "events.jsonl"
SUPERVISOR_STATE_REL = RUNTIME_REL / "supervisor_state.json"
MANAGER_BRIDGE_STATE_REL = RUNTIME_REL / "manager_bridge_state.json"
BRIDGE_CHECKPOINT_REL = RUNTIME_REL / "bridge_checkpoint.json"
BUILDER_LOCK_REL = RUNTIME_REL / "builder_lock.txt"
SUPERVISOR_LOCK_REL = RUNTIME_REL / "supervisor_lock.txt"
BUILDER_SESSION_REL = RUNTIME_REL / "builder_session.json"
REQUEUE_CLAIMS_REL = RUNTIME_REL / "requeue_claims"

TERMINAL_STATES = {"COMPLETED", "CLOSED"}


@dataclass(slots=True)
class ReconcileResult:
    ticket_id: str
    mode: str
    reason: str
    before_state: str
    after_state: str
    events_emitted: list[str] = field(default_factory=list)
    cleaned_artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_events_from_path(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    records.sort(key=lambda item: int(item.get("sequence_number", 0)))
    return records


def _read_events_for_ticket(project_root: Path, ticket_id: str) -> list[dict[str, Any]]:
    events_path = project_root / EVENTS_REL
    records = [
        record
        for record in _read_events_from_path(events_path)
        if _normalize_ticket_id(record.get("ticket_id")) == ticket_id
    ]
    records.sort(key=lambda item: int(item.get("sequence_number", 0)))
    return records


def _derive_ticket_state(events: list[dict[str, Any]]) -> str:
    state = StateMachine.derive_state_from_events(events)
    return state.value


def _latest_event(
    events: list[dict[str, Any]], event_type: str
) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") == event_type:
            return event
    return None


def _normalize_ticket_id(value: Any) -> str | None:
    if value is None:
        return None
    ticket = str(value).strip()
    if not ticket or ticket.upper() in {"NONE", "UNKNOWN", "N/A"}:
        return None
    return ticket


def _resolve_target_ticket(project_root: Path, explicit_ticket: str | None) -> str:
    if explicit_ticket:
        return explicit_ticket

    supervisor_state = _load_json(project_root / SUPERVISOR_STATE_REL)
    active_ticket = _normalize_ticket_id(supervisor_state.get("active_ticket"))
    if active_ticket:
        return active_ticket

    events = _read_events_from_path(project_root / EVENTS_REL)
    for event in reversed(events):
        ticket = _normalize_ticket_id(event.get("ticket_id"))
        if ticket:
            return ticket

    raise SystemExit("Unable to infer a ticket to reconcile; pass --ticket.")


def _append_terminal_events(
    project_root: Path,
    ticket_id: str,
    *,
    reason: str,
    dry_run: bool,
) -> tuple[list[str], str]:
    events = _read_events_for_ticket(project_root, ticket_id)
    before_state = _derive_ticket_state(events) if events else "BOOTSTRAP"
    emitted: list[str] = []
    bus = None
    if not dry_run:
        bus = EventBus(runtime_dir=project_root / RUNTIME_REL / "events")

    state_changed = _latest_event(events, "STATE_CHANGED")
    terminal_change_present = (
        bool(state_changed)
        and str((state_changed.get("payload") or {}).get("to_state", "")).upper()
        == "COMPLETED"
    )
    closed_present = _latest_event(events, "SUPERVISOR_CLOSED") is not None

    if (
        before_state not in TERMINAL_STATES
        and not terminal_change_present
        and bus is not None
    ):
        record = bus.emit(
            "STATE_CHANGED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "from_state": before_state,
                "to_state": "COMPLETED",
                "reason": reason,
                "source": "reconcile_ticket",
            },
        )
        if record is not None:
            events.append(record.to_dict())
            emitted.append("STATE_CHANGED->COMPLETED")

    if not closed_present and bus is not None:
        record = bus.emit(
            "SUPERVISOR_CLOSED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "source": "reconcile_ticket",
                "reason": reason,
            },
        )
        if record is not None:
            events.append(record.to_dict())
            emitted.append("SUPERVISOR_CLOSED")

    after_state = _derive_ticket_state(events) if events else before_state
    return emitted, after_state


def _try_unlink(path: Path, label: str, *, dry_run: bool, log: list[str]) -> None:
    if not path.exists():
        return
    if dry_run:
        log.append(f"{label} (dry-run)")
        return
    try:
        path.unlink()
        log.append(label)
    except OSError as exc:
        log.append(f"{label} (failed: {exc})")


def _remove_lock_if_owned(
    path: Path, label: str, ticket_id: str, *, dry_run: bool, log: list[str]
) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _normalize_ticket_id(data.get("ticket_id")) != ticket_id:
            return
    except (OSError, json.JSONDecodeError):
        pass  # unreadable lock -> remove unconditionally
    _try_unlink(path, label, dry_run=dry_run, log=log)


def _cleanup_runtime_artifacts(
    project_root: Path,
    ticket_id: str,
    *,
    dry_run: bool,
) -> list[str]:
    cleaned: list[str] = []
    runtime_dir = project_root / RUNTIME_REL

    for rel, label in (
        (BUILDER_LOCK_REL, "builder_lock.txt"),
        (BUILDER_SESSION_REL, "builder_session.json"),
        (SUPERVISOR_LOCK_REL, "supervisor_lock.txt"),
    ):
        _remove_lock_if_owned(
            project_root / rel, label, ticket_id, dry_run=dry_run, log=cleaned
        )

    claims_dir = runtime_dir / REQUEUE_CLAIMS_REL.name
    if claims_dir.exists() and claims_dir.is_dir():
        prefix = f"{ticket_id}_seq-"
        for child in claims_dir.iterdir():
            if child.is_file() and child.name.startswith(prefix):
                _try_unlink(
                    child, f"requeue_claims/{child.name}", dry_run=dry_run, log=cleaned
                )

    return cleaned


def _update_runtime_state(
    project_root: Path,
    ticket_id: str,
    *,
    after_state: str,
    dry_run: bool,
) -> list[str]:
    notes: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    latest_sequence = 0
    events = _read_events_for_ticket(project_root, ticket_id)
    if events:
        latest_sequence = int(events[-1].get("sequence_number", 0))

    supervisor_state_path = project_root / SUPERVISOR_STATE_REL
    supervisor_state = _load_json(supervisor_state_path)
    completed = list(supervisor_state.get("completed_tickets") or [])
    if ticket_id not in completed:
        completed.append(ticket_id)

    supervisor_state.update(
        {
            "active_ticket": None,
            "completed_tickets": completed,
            "last_action": "RECONCILED",
            "last_processed_sequence": latest_sequence,
            "loop_current_round": 0,
            "loop_max_rounds": int(supervisor_state.get("loop_max_rounds", 0) or 0),
            "last_requeue_trigger_sequence": 0,
            "last_manager_stale_trigger_sequence": 0,
        }
    )
    if not dry_run:
        _write_json(supervisor_state_path, supervisor_state)
    notes.append(f"supervisor_state.json -> active_ticket=None, completed={ticket_id}")

    bridge_state_path = project_root / MANAGER_BRIDGE_STATE_REL
    if bridge_state_path.exists():
        bridge_state = _load_json(bridge_state_path)
        bridge_state.update(
            {
                "last_ticket_id": ticket_id,
                "last_ticket_state": after_state,
                "last_processed_sequence": latest_sequence,
                "updated_at": now,
                "heartbeat_at": now,
            }
        )
        if not dry_run:
            _write_json(bridge_state_path, bridge_state)
        notes.append(f"manager_bridge_state.json -> last_ticket_state={after_state}")

    bridge_checkpoint_path = project_root / BRIDGE_CHECKPOINT_REL
    if bridge_checkpoint_path.exists():
        bridge_checkpoint = _load_json(bridge_checkpoint_path)
        bridge_checkpoint.update({"last_processed_sequence": latest_sequence})
        if not dry_run:
            _write_json(bridge_checkpoint_path, bridge_checkpoint)
        notes.append("bridge_checkpoint.json updated")

    return notes


def reconcile_ticket(
    project_root: Path,
    ticket_id: str,
    *,
    reason: str,
    dry_run: bool = False,
) -> ReconcileResult:
    events = _read_events_for_ticket(project_root, ticket_id)
    before_state = _derive_ticket_state(events) if events else "BOOTSTRAP"

    events_emitted, after_state = _append_terminal_events(
        project_root,
        ticket_id,
        reason=reason,
        dry_run=dry_run,
    )
    cleaned_artifacts = _cleanup_runtime_artifacts(
        project_root,
        ticket_id,
        dry_run=dry_run,
    )
    notes = _update_runtime_state(
        project_root,
        ticket_id,
        after_state=after_state,
        dry_run=dry_run,
    )

    if dry_run:
        notes.append("dry-run: no files written")

    return ReconcileResult(
        ticket_id=ticket_id,
        mode="close",
        reason=reason,
        before_state=before_state,
        after_state=after_state,
        events_emitted=events_emitted,
        cleaned_artifacts=cleaned_artifacts,
        notes=notes,
        dry_run=dry_run,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Canonical ticket reconciler for workspace runtime cleanup."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root (default: current directory).",
    )
    parser.add_argument(
        "--ticket",
        type=str,
        default="",
        help="Ticket ID to reconcile. Defaults to supervisor active_ticket.",
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="manual reconciliation",
        help="Reason to store in terminal events.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the reconciliation without writing any files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    ticket_id = _resolve_target_ticket(project_root, args.ticket.strip() or None)

    result = reconcile_ticket(
        project_root,
        ticket_id,
        reason=args.reason,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[reconcile-ticket] ticket={result.ticket_id}")
        print(
            f"[reconcile-ticket] before={result.before_state} after={result.after_state}"
        )
        if result.events_emitted:
            print("[reconcile-ticket] events=" + ", ".join(result.events_emitted))
        if result.cleaned_artifacts:
            print("[reconcile-ticket] cleaned=" + ", ".join(result.cleaned_artifacts))
        for note in result.notes:
            print(f"[reconcile-ticket] note={note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
