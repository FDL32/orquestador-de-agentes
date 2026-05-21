#!/usr/bin/env python3
"""Run an automated manager review when a ticket reaches READY_FOR_REVIEW."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / ".agent"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from bus.review_bridge import ReviewBridge  # noqa: E402
from bus.state_machine import StateMachine, TicketState  # noqa: E402
from bus.supervisor import SequentialTicketSupervisor  # noqa: E402
from bus.time_utils import now_local  # noqa: E402


@dataclass(slots=True)
class BridgeState:
    """Persisted bridge state to avoid duplicate reviews."""

    last_processed_sequence: int = 0
    last_ticket_id: str | None = None
    last_ticket_state: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "last_processed_sequence": self.last_processed_sequence,
            "last_ticket_id": self.last_ticket_id,
            "last_ticket_state": self.last_ticket_state,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BridgeState:
        return cls(
            last_processed_sequence=int(data.get("last_processed_sequence", 0)),
            last_ticket_id=data.get("last_ticket_id") or None,
            last_ticket_state=str(data.get("last_ticket_state", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def _state_path() -> Path:
    return PROJECT_ROOT / ".agent" / "runtime" / "manager_bridge_state.json"


def _resolve_manager_executable(explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"Manager backend executable not found: {explicit}")

    # Resuelve el ejecutable del backend asignado a MANAGER en agents.json.
    # WP-2026-072 movio el Manager a OpenCode; no se asume Codex (legacy).
    try:
        from agents_config import get_backend_for_role, load_agents_config

        backend = get_backend_for_role("MANAGER", load_agents_config(PROJECT_ROOT))
    except Exception:
        backend = "opencode"  # agents.json ilegible -> default OpenCode

    detected = shutil.which(backend)
    if detected:
        return Path(detected)

    raise FileNotFoundError(
        f"No se pudo localizar el ejecutable del backend Manager '{backend}'. "
        "Pasa --backend-path con la ruta explicita."
    )


def _load_state() -> BridgeState:
    path = _state_path()
    if not path.exists():
        return BridgeState()
    return BridgeState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save_state(state: BridgeState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(tz=timezone.utc).isoformat()
    path.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _append_block(path: Path, block: str) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    content = content.rstrip()
    if content:
        content += "\n\n---\n\n"
    content += block.rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _ticket_state(
    supervisor: SequentialTicketSupervisor,
) -> tuple[str | None, TicketState, int]:
    state = supervisor.load_state()
    ticket_id = state.active_ticket
    if not ticket_id:
        return None, TicketState.IN_PROGRESS, 0
    events = supervisor.event_bus.read_events(ticket_id=ticket_id)
    latest_sequence = events[-1].sequence_number if events else 0
    current_state = (
        StateMachine.derive_state_from_events([event.to_dict() for event in events])
        if events
        else TicketState.IN_PROGRESS
    )

    if current_state == TicketState.IN_PROGRESS:
        log_status = _execution_log_state(supervisor)
        fallback_map = {
            "READY_FOR_REVIEW": TicketState.READY_FOR_REVIEW,
            "READY_TO_CLOSE": TicketState.READY_TO_CLOSE,
            "COMPLETED": TicketState.COMPLETED,
        }
        current_state = fallback_map.get(log_status, current_state)

    return ticket_id, current_state, latest_sequence


def _execution_log_state(supervisor: SequentialTicketSupervisor) -> str:
    """Read the current execution log status as a fallback signal."""
    path = getattr(
        supervisor,
        "execution_log_path",
        supervisor.collaboration_dir / "execution_log.md",
    )
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*-?\s*\*\*Estado:\*\*\s*([^\n]+)", content, flags=re.MULTILINE
    )
    if not match:
        return ""
    return match.group(1).strip().upper()


def _record_review(
    supervisor: SequentialTicketSupervisor,
    ticket_id: str,
    decision: str,
    feedback: str,
    source: str,
) -> None:
    review_queue = supervisor.collaboration_dir / "review_queue.md"
    notifications = supervisor.notifications_path
    timestamp = now_local().strftime("%Y-%m-%d %H:%M:%S")

    _append_block(
        review_queue,
        "\n".join(
            [
                f"### MANAGER REVIEW - {timestamp}",
                f"- **Plan ID:** {ticket_id}",
                f"- **Decision:** {decision}",
                f"- **Source:** {source}",
                "",
                "#### Summary",
                feedback.strip() or "(sin resumen)",
            ]
        ),
    )

    _append_block(
        notifications,
        "\n".join(
            [
                f"### MANAGER_REVIEW - {timestamp}",
                f"- **Plan ID:** {ticket_id}",
                f"- **Decision:** {decision}",
                f"- **Source:** {source}",
            ]
        ),
    )


def _bridge_heartbeat(
    *,
    prefix: str,
    active_ticket: str | None,
    current_state: TicketState,
    latest_sequence: int,
    bridge_state: BridgeState,
) -> str:
    timestamp = now_local().strftime("%Y-%m-%dT%H:%M:%S%z")
    ticket = active_ticket or "NONE"
    bridge_ticket = bridge_state.last_ticket_id or "NONE"
    bridge_state_name = bridge_state.last_ticket_state or "NONE"
    updated_at = bridge_state.updated_at or "NONE"
    return (
        f"[manager-review-bridge] {prefix} | ts={timestamp} | ticket={ticket} "
        f"| state={current_state.value} | seq={latest_sequence} "
        f"| last_processed={bridge_state.last_processed_sequence} "
        f"| bridge_ticket={bridge_ticket} | bridge_state={bridge_state_name} "
        f"| updated_at={updated_at}"
    )


def _sync_ticket_checkpoint(
    supervisor: SequentialTicketSupervisor,
    ticket_id: str,
    minimum_sequence: int,
) -> int:
    """Persist the latest processed sequence for the reviewed ticket only."""
    latest_ticket_event = supervisor.event_bus.latest_event(ticket_id=ticket_id)
    checkpoint_sequence = minimum_sequence
    if latest_ticket_event is not None:
        checkpoint_sequence = max(
            checkpoint_sequence, latest_ticket_event.sequence_number
        )

    state = supervisor.load_state()
    if checkpoint_sequence > state.last_processed_sequence:
        state.last_processed_sequence = checkpoint_sequence
        supervisor.save_state(state)
    return checkpoint_sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automated Codex manager review bridge"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep watching for READY_FOR_REVIEW tickets and trigger Codex review automatically",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single watch tick and exit",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.5,
        help="Polling interval used by --watch (seconds)",
    )
    parser.add_argument(
        "--backend-path",
        type=Path,
        default=None,
        help="Explicit path to the manager backend executable",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for the Codex review process",
    )
    return parser


def _tick(
    supervisor: SequentialTicketSupervisor,
    review: ReviewBridge,
    manager_path: Path | None,
    timeout: int,
) -> bool:
    supervisor.bootstrap()
    ticket_id, current_state, latest_sequence = _ticket_state(supervisor)
    if not ticket_id:
        return False
    if current_state != TicketState.READY_FOR_REVIEW:
        return False

    bridge_state = _load_state()
    if latest_sequence <= bridge_state.last_processed_sequence:
        return False

    try:
        manager_executable = _resolve_manager_executable(manager_path)
        result = review.run_manager_review_cycle(
            ticket_id=ticket_id,
            supervisor=supervisor,
            manager_executable=manager_executable,
            timeout_seconds=timeout,
        )
    except FileNotFoundError as exc:
        print(f"[manager-review-bridge] {exc}")
        return False
    except subprocess.TimeoutExpired:
        print(f"[manager-review-bridge] Manager review timed out for {ticket_id}")
        return False
    except ValueError as exc:
        print(f"[manager-review-bridge] Invalid transition: {exc}")
        return False
    supervisor.sync_controller("--force")
    checkpoint_sequence = _sync_ticket_checkpoint(
        supervisor=supervisor,
        ticket_id=ticket_id,
        minimum_sequence=latest_sequence,
    )
    _record_review(
        supervisor=supervisor,
        ticket_id=ticket_id,
        decision=result.decision.value.upper(),
        feedback=result.feedback,
        source="manager backend exec review",
    )

    bridge_state.last_processed_sequence = checkpoint_sequence
    bridge_state.last_ticket_id = ticket_id
    bridge_state.last_ticket_state = current_state.value
    _save_state(bridge_state)
    return True


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    supervisor = SequentialTicketSupervisor(project_root=PROJECT_ROOT, auto_sync=True)
    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=PROJECT_ROOT)

    if args.watch:
        supervisor.bootstrap()
        state = supervisor.load_state()
        print(
            f"[manager-review-bridge] watch mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | poll={args.poll_interval}s",
            flush=True,
        )
        while True:
            ticked = _tick(
                supervisor=supervisor,
                review=review,
                manager_path=args.backend_path,
                timeout=args.timeout,
            )
            if not ticked:
                active_ticket, current_state, latest_sequence = _ticket_state(
                    supervisor
                )
                bridge_state = _load_state()
                print(
                    _bridge_heartbeat(
                        prefix="waiting",
                        active_ticket=active_ticket,
                        current_state=current_state,
                        latest_sequence=latest_sequence,
                        bridge_state=bridge_state,
                    ),
                    flush=True,
                )
            time.sleep(args.poll_interval)

    if args.once:
        supervisor.bootstrap()
        state = supervisor.load_state()
        print(
            f"[manager-review-bridge] once mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)}",
            flush=True,
        )
        _tick(
            supervisor=supervisor,
            review=review,
            manager_path=args.backend_path,
            timeout=int(args.timeout),
        )
        return 0

    parser.error("Use --watch or --once")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
