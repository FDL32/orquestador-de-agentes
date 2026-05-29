#!/usr/bin/env python3
"""Run an automated manager review when a ticket reaches READY_FOR_REVIEW.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

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


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
# Precedence: AGENT_PROJECT_ROOT env > derived from module location


# Add .agent to sys.path using the bootstrap root (engine-rooted, not operational).
# resolve_project_root() is NOT called here so that --project-root can win precedence
# in main() before the lru_cache is populated.
_AGENT_DIR_BOOTSTRAP = _PROJECT_ROOT_BOOTSTRAP / ".agent"
if str(_AGENT_DIR_BOOTSTRAP) not in sys.path:
    sys.path.append(str(_AGENT_DIR_BOOTSTRAP))


from runtime.project_root import resolve_project_root  # noqa: E402


def _project_root() -> Path:
    """Return the resolved project root (lazy — reads AGENT_PROJECT_ROOT each call)."""
    return resolve_project_root()


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
    heartbeat_at: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "last_processed_sequence": self.last_processed_sequence,
            "last_ticket_id": self.last_ticket_id,
            "last_ticket_state": self.last_ticket_state,
            "updated_at": self.updated_at,
            "heartbeat_at": self.heartbeat_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BridgeState:
        return cls(
            last_processed_sequence=int(data.get("last_processed_sequence", 0)),
            last_ticket_id=data.get("last_ticket_id") or None,
            last_ticket_state=str(data.get("last_ticket_state", "")),
            updated_at=str(data.get("updated_at", "")),
            heartbeat_at=str(data.get("heartbeat_at", "")),
        )


def _state_path() -> Path:
    return _project_root() / ".agent" / "runtime" / "manager_bridge_state.json"


def _checkpoint_path() -> Path:
    return _project_root() / ".agent" / "runtime" / "bridge_checkpoint.json"


def _resolve_manager_executable(explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"Manager backend executable not found: {explicit}")

    # Resuelve el ejecutable del backend asignado a MANAGER en agents.json.
    # WP-2026-072 movio el Manager a OpenCode; no se asume Codex (legacy).
    try:
        from agents_config import get_backend_for_role, load_agents_config

        backend = get_backend_for_role("MANAGER", load_agents_config(_project_root()))
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
        state = BridgeState()
    else:
        try:
            state = BridgeState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, TypeError):
            state = BridgeState()
    # Durable checkpoint (bridge_checkpoint.json) takes precedence if it holds
    # a higher sequence than the heartbeat state file. This prevents reprocessing
    # events after supervisor restarts.
    checkpoint_seq = _load_checkpoint()
    if checkpoint_seq > state.last_processed_sequence:
        state.last_processed_sequence = checkpoint_seq
    return state


def _save_state(state: BridgeState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(tz=timezone.utc).isoformat()
    path.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_checkpoint() -> int:
    """Load last_processed_sequence from the durable checkpoint file.

    Returns the sequence number, or 0 if the file is missing or corrupt.
    """
    path = _checkpoint_path()
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("last_processed_sequence", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def _save_checkpoint(state: BridgeState) -> None:
    """Persist last_processed_sequence to the durable checkpoint file.

    Must be called AFTER _save_state() to keep heartbeat and cursor in sync.
    """
    path = _checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"last_processed_sequence": state.last_processed_sequence},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _refresh_heartbeat(state: BridgeState) -> None:
    """Stamp heartbeat_at with current UTC time so supervisor can detect a live bridge."""
    state.heartbeat_at = datetime.now(tz=timezone.utc).isoformat()


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
    raw_stdout: str = "",
    parse_method: str = "",
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

    # WP-2026-155: Persist canonical normalized feedback
    feedback_file = supervisor.collaboration_dir / f"manager_feedback_{ticket_id}.md"
    is_parse_warning = "[PARSE_WARNING]" if not feedback.strip() else ""
    feedback_content = [
        f"# Manager Feedback - {ticket_id} {is_parse_warning}".strip(),
        f"- Decision: {decision}",
        f"- Parse method: {parse_method or 'unknown'}",
        f"- Source: {source}",
        f"- Timestamp: {datetime.now(timezone.utc).isoformat()}",
        "",
        feedback.strip()
        or "[Feedback no pudo ser parseado en secciones estructuradas]",
        "",
        "## Raw Review",
        "```text",
        raw_stdout or "[empty stdout]",
        "```",
        "",
    ]
    feedback_file.write_text("\n".join(feedback_content), encoding="utf-8")


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
    parser = argparse.ArgumentParser(description="Automated manager review bridge")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep watching for READY_FOR_REVIEW tickets and trigger manager review automatically",
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
        "--project-root",
        type=Path,
        default=None,
        help="Destination workspace root to review",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for the manager review process",
    )
    return parser


def _tick(
    supervisor: SequentialTicketSupervisor,
    review: ReviewBridge,
    manager_path: Path | None,
    timeout: int,
) -> bool:
    # Bridge must NOT call reconcile_state() here — that is the supervisor's
    # job during its own cycle. Writing supervisor_state.json from the bridge
    # process causes ConcurrentStateError under concurrent writes.
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
        raw_stdout=result.stdout,
        parse_method=result.parse_method,
    )

    bridge_state.last_processed_sequence = checkpoint_sequence
    bridge_state.last_ticket_id = ticket_id
    bridge_state.last_ticket_state = current_state.value
    _save_state(bridge_state)
    _save_checkpoint(bridge_state)
    return True


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.project_root is not None:
        import os

        from runtime.project_root import clear_cache

        os.environ["AGENT_PROJECT_ROOT"] = str(args.project_root.resolve())
        clear_cache()
    project_root = _project_root()
    supervisor = SequentialTicketSupervisor(project_root=project_root, auto_sync=True)
    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=project_root)

    if args.watch:
        supervisor.reconcile_state()
        state = supervisor.load_state()
        print(
            f"[manager-review-bridge] watch mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | poll={args.poll_interval}s",
            flush=True,
        )
        while True:
            # Refresh heartbeat before _tick() so long reviews (up to timeout seconds)
            # do not appear stale to the supervisor watchdog during the review cycle.
            bridge_state = _load_state()
            _refresh_heartbeat(bridge_state)
            _save_state(bridge_state)
            ticked = _tick(
                supervisor=supervisor,
                review=review,
                manager_path=args.backend_path,
                timeout=args.timeout,
            )
            # Refresh heartbeat again after _tick() so the supervisor sees a live
            # bridge immediately after the review completes.
            bridge_state = _load_state()
            _refresh_heartbeat(bridge_state)
            _save_state(bridge_state)
            if not ticked:
                active_ticket, current_state, latest_sequence = _ticket_state(
                    supervisor
                )
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
        supervisor.reconcile_state()
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
