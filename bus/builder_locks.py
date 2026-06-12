"""Builder lock, round, and session helpers extracted from ``builder_lifecycle``.

This module owns Builder liveness checks, requeue claims, round tracking
signals, and session cleanup primitives split out of the original monolith.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .event_bus import EventBus
from .state_machine import TicketState


REQUEUE_CLAIMS_DIRNAME = "requeue_claims"
_REQUEUE_CLAIM_TTL_ENV = "TICKET_SUPERVISOR_REQUEUE_CLAIM_TTL_SECONDS"

RELAUNCH_BLOCKED_STATES = frozenset(
    {
        TicketState.HUMAN_GATE,
        TicketState.READY_TO_CLOSE,
        TicketState.COMPLETED,
    }
)

MANAGER_STALE_TIMEOUT = 600


def bus_cleanup_builder_session(runtime_dir: Path) -> None:
    """Remove builder_session.json from the runtime directory."""
    session_path = runtime_dir / "builder_session.json"
    if session_path.exists():
        with contextlib.suppress(OSError):
            session_path.unlink()
            print(
                f"[supervisor] Purged stale builder_session.json in {runtime_dir}",
                flush=True,
            )


def _parse_iso_datetime(iso_str: str) -> datetime:
    normalized = iso_str.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_pid_alive(pid: int) -> bool:
    if os.name != "nt":
        return False
    tasklist = shutil.which("tasklist")
    if not tasklist:
        return False
    try:
        check_result = subprocess.run(  # noqa: S603
            [tasklist, "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return check_result.returncode == 0 and str(pid) in check_result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _has_builder_exited_after(
    event_bus: EventBus, ticket_id: str, lock_start: datetime
) -> bool:
    events = event_bus.read_events(ticket_id=ticket_id)
    for event in reversed(events):
        if event.actor == "BUILDER" and event.event_type == "BUILDER_EXIT":
            try:
                event_time = _parse_iso_datetime(event.timestamp)
                if event_time >= lock_start:
                    return True
            except (ValueError, TypeError, AttributeError) as exc:
                print(
                    f"[supervisor] Failed to parse timestamp for BUILDER_EXIT event: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
    return False


def builder_alive(runtime_dir: Path, event_bus: EventBus) -> bool:
    lock = runtime_dir / "builder_lock.txt"
    if not lock.exists():
        return False
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    ticket_id = data.get("ticket_id")
    started_at_str = data.get("started_at")

    if ticket_id and started_at_str:
        try:
            lock_start = _parse_iso_datetime(started_at_str)
            if _has_builder_exited_after(event_bus, ticket_id, lock_start):
                return False
        except (ValueError, TypeError, AttributeError) as exc:
            print(
                f"[supervisor] Failed to parse lock timestamp: {exc}",
                file=sys.stderr,
                flush=True,
            )

    try:
        age = time.time() - lock.stat().st_mtime
        return age < 900
    except OSError:
        return False


def _has_handoff_blocked_after_sequence(
    event_bus: EventBus, ticket_id: str, trigger_sequence: int
) -> int:
    max_seq = 0
    for event in event_bus.read_events(ticket_id=ticket_id):
        if (
            event.event_type == "HANDOFF_BLOCKED"
            and event.sequence_number > trigger_sequence
            and event.sequence_number > max_seq
        ):
            max_seq = event.sequence_number
    return max_seq


def _get_claim_ttl() -> float:
    raw = os.environ.get(_REQUEUE_CLAIM_TTL_ENV, "")
    if raw and raw.strip():
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return 90.0


def _has_relaunched_for_trigger(
    event_bus: EventBus, ticket_id: str, trigger_seq: int
) -> bool:
    for event in reversed(event_bus.read_events(ticket_id=ticket_id)):
        if event.event_type != "BUILDER_RELAUNCH_ATTEMPTED":
            continue
        if event.sequence_number <= trigger_seq:
            continue
        payload_trigger_seq = (event.payload or {}).get("trigger_seq")
        if payload_trigger_seq == trigger_seq:
            return True
    return False


def _claim_requeue(  # noqa: C901
    runtime_dir: Path, event_bus: EventBus, ticket_id: str, trigger_seq: int
) -> bool:
    if not isinstance(trigger_seq, int) or trigger_seq <= 0:
        return False

    claims_dir = runtime_dir / REQUEUE_CLAIMS_DIRNAME
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / f"{ticket_id}_seq-{trigger_seq}.claim"
    takeover_path = claim_path.with_suffix(".claim.takeover")

    try:
        fd = os.open(
            str(claim_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError:
        pass
    except OSError as exc:
        print(
            f"[supervisor] _claim_requeue: OSError creating claim for "
            f"{ticket_id} seq={trigger_seq}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False
    else:
        try:
            claim_content = json.dumps(
                {
                    "ticket_id": ticket_id,
                    "trigger_seq": trigger_seq,
                    "pid": os.getpid(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "supervisor_id": f"{os.getpid()}@{socket.gethostname()}",
                },
                indent=2,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                file_obj.write(claim_content)
            print(
                f"[supervisor] _claim_requeue: acquired claim for "
                f"{ticket_id} seq={trigger_seq}",
                flush=True,
            )
            return True
        except Exception:
            with contextlib.suppress(OSError):
                os.close(fd)
                os.unlink(str(claim_path))
            raise

    try:
        stat_info = os.stat(str(claim_path))
        age = time.time() - stat_info.st_mtime
    except OSError:
        return False

    ttl = _get_claim_ttl()

    if age <= ttl:
        return False

    if _has_relaunched_for_trigger(event_bus, ticket_id, trigger_seq):
        print(
            f"[supervisor] _claim_requeue: claim stale but relaunch already "
            f"emitted for {ticket_id} seq={trigger_seq}. Not reclaiming.",
            flush=True,
        )
        return False

    try:
        takeover_fd = os.open(
            str(takeover_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        os.close(takeover_fd)
    except FileExistsError:
        return False
    except OSError:
        return False

    try:
        os.unlink(str(claim_path))
        new_fd = os.open(
            str(claim_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        try:
            claim_content = json.dumps(
                {
                    "ticket_id": ticket_id,
                    "trigger_seq": trigger_seq,
                    "pid": os.getpid(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "supervisor_id": f"{os.getpid()}@{socket.gethostname()}",
                },
                indent=2,
            )
            with os.fdopen(new_fd, "w", encoding="utf-8") as file_obj:
                file_obj.write(claim_content)
            print(
                f"[supervisor] _claim_requeue: recovered stale claim for "
                f"{ticket_id} seq={trigger_seq}",
                flush=True,
            )
            return True
        except Exception:
            with contextlib.suppress(OSError):
                os.close(new_fd)
                os.unlink(str(claim_path))
            raise
    finally:
        with contextlib.suppress(OSError):
            os.unlink(str(takeover_path))


def _cleanup_terminal_requeue_claims(runtime_dir: Path, ticket_id: str) -> None:
    claims_dir = runtime_dir / REQUEUE_CLAIMS_DIRNAME
    if not claims_dir.exists():
        return
    prefix = f"{ticket_id}_seq-"
    for child in claims_dir.iterdir():
        if child.is_file() and child.name.startswith(prefix):
            with contextlib.suppress(OSError):
                child.unlink()


def _latest_changes_trigger_sequence(events: list, ticket_id: str | None = None) -> int:
    result = 0
    for event in events:
        if ticket_id is not None and getattr(event, "ticket_id", None) != ticket_id:
            continue
        if (
            event.event_type in ("LOOP_DECISION", "REVIEW_DECISION")
            and str((getattr(event, "payload", None) or {}).get("decision", "")).upper()
            == "CHANGES"
            and event.sequence_number > result
        ):
            result = event.sequence_number
    return result


def _load_manager_bridge_state(runtime_dir: Path) -> dict | None:
    path = runtime_dir / "manager_bridge_state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_manager_bridge_stale(runtime_dir: Path) -> bool:
    bridge = _load_manager_bridge_state(runtime_dir)
    if not bridge:
        return True
    heartbeat_at = bridge.get("heartbeat_at", "")
    if not heartbeat_at:
        return True
    try:
        heartbeat = datetime.fromisoformat(str(heartbeat_at))
        age = (datetime.now(tz=timezone.utc) - heartbeat).total_seconds()
        return age > MANAGER_STALE_TIMEOUT
    except Exception:
        return True


def _timeout_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _emit_supervisor_restarted_if_requested(
    runtime_dir: Path, event_bus: EventBus, load_state_fn=None
) -> None:
    _ = runtime_dir
    restart_reason = os.environ.get("SUPERVISOR_RESTART_REASON", "").strip()
    if not restart_reason:
        return

    state = load_state_fn() if load_state_fn else None
    event_bus.emit(
        "SUPERVISOR_RESTARTED",
        ticket_id=state.active_ticket or "" if state else "",
        actor="SUPERVISOR",
        payload={
            "round": state.loop_current_round if state else 0,
            "reason": restart_reason,
        },
    )


def _should_stop_run_reactive(
    *,
    start_time: float,
    last_activity: float,
    idle_timeout: float,
    max_runtime: float,
    now: float,
    runtime_dir: Path,
    event_bus: EventBus,
    builder_alive_fn=None,
) -> bool:
    if max_runtime > 0 and now - start_time >= max_runtime:
        return True

    if idle_timeout > 0 and now - last_activity >= idle_timeout:
        alive = (
            builder_alive_fn()
            if builder_alive_fn
            else builder_alive(runtime_dir, event_bus)
        )
        return not alive

    return False
