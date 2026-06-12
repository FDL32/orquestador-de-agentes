"""Builder lifecycle extracted from :mod:`bus.supervisor`.

This module owns Builder liveness, requeue claims, relaunch verification,
session cleanup, and the supervisor run loops. Callers provide stateful seams
as callbacks so the module has no dependency on ``SequentialTicketSupervisor``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .approval import ApprovalReason
from .event_bus import EventBus
from .state_machine import TicketState


REQUEUE_CLAIMS_DIRNAME = "requeue_claims"
_REQUEUE_CLAIM_TTL_ENV = "TICKET_SUPERVISOR_REQUEUE_CLAIM_TTL_SECONDS"
_BUILDER_START_VERIFY_TIMEOUT_ENV = "BUILDER_START_VERIFY_TIMEOUT_SECONDS"
_BUILDER_START_VERIFY_TIMEOUT_DEFAULT = 20.0

RELAUNCH_BLOCKED_STATES = frozenset(
    {
        TicketState.HUMAN_GATE,
        TicketState.READY_TO_CLOSE,
        TicketState.COMPLETED,
    }
)

MANAGER_STALE_TIMEOUT = 600


def bus_cleanup_builder_session(runtime_dir: Path) -> None:
    """Remove builder_session.json from the runtime directory.

    Before: builder_session.json may or may not exist.
    During: Unconditionally removes the file, suppressing any OSError.
    After: builder_session.json no longer exists in the runtime directory.

    This is called by the supervisor before a clean requeue to ensure
    the next Builder launch starts without attempting to reuse a stale
    or corrupt session ID.
    """
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
    import time

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


def _run_launcher_subprocess(
    project_root: Path, cmd: list[str]
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        return -1, "", f"launcher timed out after 60s: {exc}"
    except Exception as exc:
        return -1, "", f"ERROR executing launcher: {exc}"


def _persist_relaunch_log(runtime_dir: Path, stdout: str, stderr: str) -> None:
    logs_dir = runtime_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "launcher_last.log"
    content = f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n"
    log_path.write_text(content, encoding="utf-8")


def _resolve_launcher_path(project_root: Path) -> Path:
    try:
        from runtime.motor_link import resolve_motor_root as _resolve_motor_root

        motor_root = _resolve_motor_root(project_root) or project_root
    except ImportError:
        motor_root = project_root
    return motor_root / "scripts" / "launch_agent_terminals.ps1"


def _check_artifact(name: str, path: Path) -> tuple[bool, str]:
    try:
        if not path.exists():
            return False, f"Required artifact {name} missing: {path}"
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return False, f"Required artifact {name} is empty: {path}"
    except OSError as exc:
        return False, f"Cannot read {name}: {exc}"
    return True, ""


def _verify_relaunch_topology(  # noqa: C901
    project_root: Path,
    collaboration_dir: Path,
    runtime_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    ticket_id: str,
) -> tuple[bool, str]:
    try:
        if not project_root.exists():
            return False, f"project_root does not exist: {project_root}"
        if not project_root.is_dir():
            return False, f"project_root is not a directory: {project_root}"
    except OSError as exc:
        return False, f"project_root access error: {exc}"

    try:
        if not collaboration_dir.exists():
            return False, f"Collaboration dir missing: {collaboration_dir}"
        if not collaboration_dir.is_dir():
            return (
                False,
                f"Collaboration path is not a directory: {collaboration_dir}",
            )
    except OSError as exc:
        return False, f"Collaboration dir access error: {exc}"

    for art_name, art_path in [
        ("work_plan.md", work_plan_path),
        ("TURN.md", turn_path),
        ("STATE.md", state_path_file),
    ]:
        if not art_path.exists():
            continue
        ok, msg = _check_artifact(art_name, art_path)
        if not ok:
            return False, msg

    try:
        events_dir = runtime_dir / "events"
        if not events_dir.exists():
            return False, f"Bus events directory missing: {events_dir}"
        events_file = events_dir / "events.jsonl"
        if events_file.exists():
            try:
                events_file.read_text(encoding="utf-8")
            except OSError as exc:
                return False, f"Bus events file not readable: {exc}"
    except OSError as exc:
        return False, f"Bus events directory access error: {exc}"

    motor_link_path = project_root / ".agent" / "config" / "motor_destination_link.json"
    if motor_link_path.exists():
        try:
            from runtime.motor_link import resolve_motor_root as _rmr

            motor_root = _rmr(project_root)
            if motor_root is None:
                return (
                    False,
                    "Motor root not resolvable from motor_destination_link.json",
                )
            if not motor_root.exists():
                return False, f"Motor root path does not exist: {motor_root}"
        except ImportError as exc:
            return False, f"Cannot import runtime.motor_link: {exc}"

    if state_path_file.exists():
        try:
            state_content = state_path_file.read_text(encoding="utf-8")
            m = re.search(r"ACTIVE_TICKET:\s*(\S+)", state_content)
            if m:
                artifact_ticket = m.group(1)
                if artifact_ticket != ticket_id:
                    return (
                        False,
                        f"Ticket mismatch: STATE.md says {artifact_ticket} "
                        f"but relaunching for {ticket_id}",
                    )
        except OSError:
            pass

    return True, ""


def _capsule_hechos_from_work_plan(work_plan_path: Path) -> list[str]:
    result = []
    try:
        wp = work_plan_path.read_text(encoding="utf-8")
        for line in wp.split("\n"):
            ls = line.strip()
            for prefix in (
                "**ID:**",
                "**Title:**",
                "**Estado:**",
                "**deliverable_type:**",
            ):
                marker = f"- {prefix}"
                if ls.startswith(marker):
                    val = ls[len(marker) :].strip()
                    key = prefix.strip("*:")
                    result.append(f"{key}: {val}")
    except OSError:
        result.append("(work_plan.md no disponible)")
    return result


def _capsule_hechos_from_state(state_path: Path) -> list[str]:
    try:
        state = state_path.read_text(encoding="utf-8").strip()
        return [f"STATE.md: {state}"] if state else []
    except OSError:
        return ["(STATE.md no disponible)"]


def _capsule_hechos_from_log_tail(log_path: Path) -> list[str]:
    try:
        content = log_path.read_text(encoding="utf-8")
        log_lines = [ln for ln in content.split("\n") if ln.strip()]
        tail_count = min(10, len(log_lines))
        tail = log_lines[-tail_count:] if tail_count > 0 else log_lines
        if not tail:
            return []
        result = ["Execution log tail:"]
        result.extend(f"  {tline}" for tline in tail)
        return result
    except OSError:
        return ["(execution_log.md no disponible)"]


def _capsule_hechos_from_bus(event_bus: EventBus, ticket_id: str) -> list[str]:
    try:
        events = event_bus.read_events(
            ticket_id=ticket_id,
            event_type="BUILDER_RELAUNCH_ATTEMPTED",
        )
        if events:
            latest = events[-1]
            pl = latest.payload or {}
            return [
                f"Event {latest.sequence_number}: "
                f"outcome={pl.get('outcome', '?')} "
                f"verify_signal={pl.get('verify_signal', '?')}",
            ]
    except Exception as exc:
        print(
            f"[supervisor] capsule bus read error: {exc}",
            file=sys.stderr,
            flush=True,
        )
    return ["(event bus no disponible)"]


def _capsule_blockers_from_turn(turn_path: Path) -> list[str]:
    result = []
    try:
        turn = turn_path.read_text(encoding="utf-8")
        in_blockers = False
        for line in turn.split("\n"):
            if "## Blockers from Manager" in line:
                in_blockers = True
                continue
            if in_blockers:
                if line.startswith("## "):
                    break
                stripped = line.strip()
                if stripped:
                    result.append(stripped)
    except OSError:
        result.append("(TURN.md no disponible)")
    if not result:
        result.append("(No blockers documentados en TURN.md)")
    return result


def _capsule_hipotesis_from_log(log_path: Path) -> list[str]:
    _markers = ("hipotesis:", "[hipotesis]")
    try:
        content = log_path.read_text(encoding="utf-8")
        return [
            ln.strip()
            for ln in content.split("\n")
            if any(m in ln.lower() for m in _markers)
        ][:5]
    except OSError:
        return []


def _build_relaunch_capsule(
    project_root: Path,
    collaboration_dir: Path,
    runtime_dir: Path,
    work_plan_path: Path,
    state_path_file: Path,
    execution_log_path: Path,
    turn_path: Path,
    event_bus: EventBus,
    ticket_id: str,
) -> str:
    hechos = []
    hechos.extend(_capsule_hechos_from_work_plan(work_plan_path))
    hechos.extend(_capsule_hechos_from_state(state_path_file))
    hechos.extend(_capsule_hechos_from_log_tail(execution_log_path))
    hechos.extend(_capsule_hechos_from_bus(event_bus, ticket_id))

    blockers = _capsule_blockers_from_turn(turn_path)
    hipotesis = _capsule_hipotesis_from_log(execution_log_path)

    siguiente_accion = [
        f"Implementar {ticket_id} segun work_plan.md y ejecutar "
        "ruff + pytest-safe sobre archivos tocados.",
    ]

    now = datetime.now(timezone.utc).isoformat()
    capsule = (
        f"# Capsula de Relaunch - {ticket_id}\n"
        f"Generada: {now}\n\n"
        f"Fuentes: work_plan.md, TURN.md, STATE.md, "
        f"execution_log.md, bus events\n\n"
    )

    capsule += "## 1. Hechos Verificados\n"
    for h in hechos:
        capsule += f"- {h}\n"

    capsule += "\n## 2. Blockers del Manager\n"
    for b in blockers:
        capsule += f"- {b}\n"

    capsule += "\n## 3. Hipotesis / Puntos No Verificados\n"
    for h in hipotesis:
        capsule += f"- {h}\n"

    capsule += "\n## 4. Siguiente Accion Esperada\n"
    for a in siguiente_accion:
        capsule += f"- {a}\n"

    capsule += (
        f"\n---\n"
        f"*Capsula generada por supervisor para relaunch de {ticket_id}. "
        "Fuentes primarias: work_plan.md, TURN.md, STATE.md, "
        "execution_log.md, bus events.*\n"
    )

    capsule_path = runtime_dir / "relaunch_capsule.md"
    capsule_path.parent.mkdir(parents=True, exist_ok=True)
    capsule_path.write_text(capsule, encoding="utf-8")
    print(
        f"[ticket-supervisor] Capsula evidence-linked generada: {capsule_path}",
        flush=True,
    )

    return capsule


def _get_verify_timeout() -> float:
    raw = os.environ.get(_BUILDER_START_VERIFY_TIMEOUT_ENV, "")
    if raw and raw.strip():
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return _BUILDER_START_VERIFY_TIMEOUT_DEFAULT


def _verify_builder_start(  # noqa: C901
    runtime_dir: Path,
    event_bus: EventBus,
    ticket_id: str,
    relaunch_started_at: datetime,
    expected_round: int,
) -> tuple[str, str]:
    verify_timeout = _get_verify_timeout()
    deadline = time.time() + verify_timeout
    poll_interval = 0.5

    while time.time() < deadline:
        lock = runtime_dir / "builder_lock.txt"
        if not lock.exists():
            time.sleep(poll_interval)
            continue

        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            time.sleep(poll_interval)
            continue

        started_at_str = data.get("started_at")
        if not started_at_str:
            time.sleep(poll_interval)
            continue

        try:
            lock_started_at = _parse_iso_datetime(started_at_str)
        except (ValueError, TypeError, AttributeError):
            time.sleep(poll_interval)
            continue

        slack_threshold = relaunch_started_at - timedelta(seconds=5)
        if lock_started_at < slack_threshold:
            time.sleep(poll_interval)
            continue

        try:
            lock_age = time.time() - lock.stat().st_mtime
        except OSError:
            time.sleep(poll_interval)
            continue

        if lock_age > verify_timeout:
            time.sleep(poll_interval)
            continue

        lock_round = data.get("round")
        if lock_round != expected_round:
            time.sleep(poll_interval)
            continue

        if _has_builder_exited_after(event_bus, ticket_id, relaunch_started_at):
            return ("builder_launch_unverified", "none")

        return ("builder_started_verified", "builder_lock")

    return ("builder_launch_unverified", "none")


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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(claim_content)
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
            with os.fdopen(new_fd, "w", encoding="utf-8") as f:
                f.write(claim_content)
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
        hb = datetime.fromisoformat(str(heartbeat_at))
        age = (datetime.now(tz=timezone.utc) - hb).total_seconds()
        return age > MANAGER_STALE_TIMEOUT
    except Exception:
        return True


def _materialize_turn_blockers(
    collaboration_dir: Path,
    event_bus: EventBus,
    ticket_id: str,
) -> None:
    try:
        review_events = event_bus.read_events(
            ticket_id=ticket_id, event_type="REVIEW_DECISION"
        )
        if not review_events:
            return

        latest_review = review_events[-1]
        payload = latest_review.payload or {}

        if "blockers" not in payload:
            return

        blockers = payload.get("blockers", "")

        if not blockers or not blockers.strip():
            print(
                f"[supervisor] Empty blockers from REVIEW_DECISION for "
                f"{ticket_id}. Emitting HANDOFF_BLOCKED.",
                flush=True,
            )
            event_bus.emit(
                "HANDOFF_BLOCKED",
                ticket_id=ticket_id,
                actor="SUPERVISOR",
                payload={
                    "reason": "empty_blockers",
                    "details": "REVIEW_DECISION payload blockers field is empty.",
                },
            )
            return

        blockers_bytes = blockers.encode("utf-8")
        if len(blockers_bytes) >= 15 * 1024:
            print(
                f"[supervisor] Blockers too large ({len(blockers_bytes)} bytes) "
                f"for {ticket_id}. Emitting HANDOFF_BLOCKED.",
                flush=True,
            )
            event_bus.emit(
                "HANDOFF_BLOCKED",
                ticket_id=ticket_id,
                actor="SUPERVISOR",
                payload={
                    "reason": "blockers_too_large",
                    "size_bytes": len(blockers_bytes),
                },
            )
            return

        if '{"type":' in blockers or "sessionID" in blockers:
            print(
                f"[supervisor] Blockers contain raw JSONL for {ticket_id}. "
                "Emitting HANDOFF_BLOCKED.",
                flush=True,
            )
            event_bus.emit(
                "HANDOFF_BLOCKED",
                ticket_id=ticket_id,
                actor="SUPERVISOR",
                payload={
                    "reason": "blockers_contain_raw_jsonl",
                    "details": "blockers contain {'type': or sessionID markers.",
                },
            )
            return

        turn_path = collaboration_dir / "TURN.md"
        if not turn_path.exists():
            return

        current_turn = turn_path.read_text(encoding="utf-8")

        if "## Blockers from Manager" in current_turn:
            return

        blocker_section = (
            f"\n\n## Blockers from Manager\n\n"
            f"The last review returned CHANGES. "
            f"Address these blockers before marking ready:\n\n"
            f"{blockers}\n"
        )

        if "## Estado del Sistema" in current_turn:
            turn_path.write_text(
                current_turn.replace(
                    "## Estado del Sistema",
                    f"{blocker_section}\n## Estado del Sistema",
                ),
                encoding="utf-8",
            )
        else:
            turn_path.write_text(
                current_turn.rstrip() + blocker_section, encoding="utf-8"
            )

        print(
            f"[supervisor] Materialized blockers into TURN.md for {ticket_id}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[supervisor] Error materializing TURN blockers: {exc}",
            flush=True,
        )


def _relaunch_builder(  # noqa: C901
    project_root: Path,
    runtime_dir: Path,
    collaboration_dir: Path,
    event_bus: EventBus,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    ticket_id: str,
    trigger_seq: int = 0,
    load_state_fn=None,
    save_state_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    cleanup_session_fn=None,
    verify_topology_fn=None,
    build_capsule_fn=None,
    resolve_launcher_fn=None,
    persist_log_fn=None,
    verify_builder_start_fn=None,
) -> bool:
    current_round = 0
    if load_state_fn:
        state = load_state_fn()
        current_round = state.loop_current_round

    alive_check = (
        builder_alive_fn
        if builder_alive_fn
        else (lambda: builder_alive(runtime_dir, event_bus))
    )
    if alive_check():
        print(
            f"[ticket-supervisor] Builder alive (lock fresh), skipping relaunch for {ticket_id}",
            file=sys.stderr,
            flush=True,
        )
        persist_log = persist_log_fn or (
            lambda stdout, stderr: _persist_relaunch_log(runtime_dir, stdout, stderr)
        )
        persist_log("", f"Builder alive, skipped relaunch for {ticket_id}")
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "skipped_alive",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": None,
                "verify_signal": "none",
                "stderr_tail": "Builder alive, skipped",
            },
        )
        return True

    cleanup_session = cleanup_session_fn or (
        lambda: bus_cleanup_builder_session(runtime_dir)
    )
    cleanup_session()

    topology_valid, topology_msg = (
        verify_topology_fn(ticket_id)
        if verify_topology_fn
        else _verify_relaunch_topology(
            project_root=project_root,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            state_path_file=state_path_file,
            turn_path=turn_path,
            work_plan_path=work_plan_path,
            ticket_id=ticket_id,
        )
    )
    if not topology_valid:
        print(
            f"[ticket-supervisor] Topology invalid, blocking relaunch: {topology_msg}",
            file=sys.stderr,
            flush=True,
        )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "topology_invalid",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": -1,
                "verify_signal": "none",
                "stderr_tail": f"Topology invalid: {topology_msg}",
            },
        )
        return False

    if build_capsule_fn:
        build_capsule_fn(ticket_id)
    else:
        _build_relaunch_capsule(
            project_root=project_root,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            work_plan_path=work_plan_path,
            state_path_file=state_path_file,
            execution_log_path=execution_log_path,
            turn_path=turn_path,
            event_bus=event_bus,
            ticket_id=ticket_id,
        )

    launcher_path = (
        resolve_launcher_fn()
        if resolve_launcher_fn
        else _resolve_launcher_path(project_root)
    )
    if not launcher_path.exists():
        print(
            f"[ticket-supervisor] ERROR: Launcher not found at {launcher_path}",
            file=sys.stderr,
            flush=True,
        )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "launcher_failed",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": -1,
                "verify_signal": "none",
                "stderr_tail": f"Launcher not found: {launcher_path}",
            },
        )
        return False

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        print(
            "[ticket-supervisor] ERROR: PowerShell executable not found",
            file=sys.stderr,
            flush=True,
        )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "launcher_failed",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": -1,
                "verify_signal": "none",
                "stderr_tail": "PowerShell executable not found",
            },
        )
        return False

    cmd = [
        pwsh,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher_path),
        "-ProjectRoot",
        str(project_root),
        "-LaunchBuilder",
        "-OnlyBuilder",
        "-ResumeBuilder",
        "-SkipSupervisorWait",
    ]
    print(f"[ticket-supervisor] Executing: {' '.join(cmd)}", flush=True)

    relaunch_started_at = datetime.now(timezone.utc)

    launch = (
        run_launcher_fn
        if run_launcher_fn
        else (lambda cmd: _run_launcher_subprocess(project_root, cmd))
    )
    exit_code, stdout, stderr = launch(cmd)

    persist_log = persist_log_fn or (
        lambda out, err: _persist_relaunch_log(runtime_dir, out, err)
    )
    persist_log(stdout, stderr)

    if exit_code == 0:
        outcome, verify_signal = (
            verify_builder_start_fn(
                ticket_id=ticket_id,
                relaunch_started_at=relaunch_started_at,
                expected_round=current_round,
            )
            if verify_builder_start_fn
            else _verify_builder_start(
                runtime_dir=runtime_dir,
                event_bus=event_bus,
                ticket_id=ticket_id,
                relaunch_started_at=relaunch_started_at,
                expected_round=current_round,
            )
        )
        print(
            f"[ticket-supervisor] Builder relaunch outcome={outcome} "
            f"verify_signal={verify_signal} for {ticket_id}",
            flush=True,
        )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": outcome,
                "trigger_seq": trigger_seq,
                "launcher_exit_code": exit_code,
                "verify_signal": verify_signal,
                "stderr_tail": stderr[-200:] if stderr else None,
            },
        )
        return True
    elif exit_code == -1 and "timed out" in stderr:
        print(
            "[ticket-supervisor] launcher timed out after 60s",
            file=sys.stderr,
            flush=True,
        )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "timeout",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": exit_code,
                "verify_signal": "none",
                "stderr_tail": stderr[-200:] if stderr else None,
            },
        )
        return False
    else:
        print(
            f"[ticket-supervisor] launcher failed exit={exit_code}",
            file=sys.stderr,
            flush=True,
        )
        if stdout:
            print(
                f"  stdout (last 500): {stdout[-500:]}",
                file=sys.stderr,
                flush=True,
            )
        if stderr:
            print(
                f"  stderr (last 500): {stderr[-500:]}",
                file=sys.stderr,
                flush=True,
            )
        event_bus.emit(
            "BUILDER_RELAUNCH_ATTEMPTED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "round": current_round,
                "outcome": "launcher_failed",
                "trigger_seq": trigger_seq,
                "launcher_exit_code": exit_code,
                "verify_signal": "none",
                "stderr_tail": stderr[-200:] if stderr else None,
            },
        )
        return False


def requeue_ticket(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    ticket_id: str,
    trigger_seq: int = 0,
    load_state_fn=None,
    save_state_fn=None,
    current_state_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    claim_requeue_fn=None,
) -> bool:
    if not isinstance(trigger_seq, int) or trigger_seq <= 0:
        print(
            f"[ticket-supervisor] requeue_ticket: invalid trigger_seq={trigger_seq} "
            f"for {ticket_id}. Failing closed.",
            flush=True,
        )
        return False

    claim_requeue = claim_requeue_fn or (
        lambda tid, seq: _claim_requeue(runtime_dir, event_bus, tid, seq)
    )
    if not claim_requeue(ticket_id, trigger_seq):
        print(
            f"[ticket-supervisor] requeue_ticket: claim denied for "
            f"{ticket_id} seq={trigger_seq}. Skipping relaunch.",
            flush=True,
        )
        return False

    if load_state_fn:
        state = load_state_fn()
    else:
        return False
    if state.active_ticket != ticket_id:
        return False

    if current_state_fn:
        current_state = current_state_fn(ticket_id)
    else:
        return False
    if current_state in RELAUNCH_BLOCKED_STATES:
        print(
            f"[ticket-supervisor] Skipping Builder relaunch for {ticket_id}: "
            f"ticket is {current_state.value}",
            flush=True,
        )
        return False

    state.last_requeue_trigger_sequence = trigger_seq
    state.loop_current_round += 1
    if save_state_fn:
        save_state_fn(state)
    print(
        f"[ticket-supervisor] Detected requeue for {ticket_id} "
        f"(round {state.loop_current_round}). Relaunching Builder...",
        flush=True,
    )
    if relaunch_builder_fn:
        return relaunch_builder_fn(ticket_id, trigger_seq)
    return _relaunch_builder(
        project_root=project_root,
        runtime_dir=runtime_dir,
        collaboration_dir=collaboration_dir,
        event_bus=event_bus,
        state_path_file=state_path_file,
        turn_path=turn_path,
        work_plan_path=work_plan_path,
        execution_log_path=execution_log_path,
        ticket_id=ticket_id,
        trigger_seq=trigger_seq,
        load_state_fn=load_state_fn,
        save_state_fn=save_state_fn,
        builder_alive_fn=builder_alive_fn,
        run_launcher_fn=run_launcher_fn,
    )


def _bootstrap_requeue_if_needed(  # noqa: C901
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    ticket_id: str,
    load_state_fn=None,
    save_state_fn=None,
    current_state_fn=None,
    requeue_ticket_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    cleanup_session_fn=None,
    materialize_turn_blockers_fn=None,
) -> bool:
    if load_state_fn is None:
        return False
    state = load_state_fn()

    requeue_trigger_seq = _latest_changes_trigger_sequence(
        event_bus.read_events(ticket_id=ticket_id), ticket_id=ticket_id
    )

    if not (
        requeue_trigger_seq > 0
        and requeue_trigger_seq > state.last_requeue_trigger_sequence
    ):
        return False

    current_ticket_state = current_state_fn(ticket_id) if current_state_fn else None
    if current_ticket_state is None:
        return False
    state_ok = current_ticket_state == TicketState.IN_PROGRESS or (
        current_ticket_state == TicketState.READY_FOR_REVIEW
        and requeue_trigger_seq > 0
        and requeue_trigger_seq > state.last_processed_sequence
    )
    if not state_ok:
        return False
    if current_ticket_state == TicketState.READY_FOR_REVIEW:
        print(
            f"[supervisor] bootstrap: spurious READY_FOR_REVIEW detected for {ticket_id} "
            f"after CHANGES at seq={requeue_trigger_seq} — crash during relaunch suspected. "
            "Forcing Builder requeue.",
            flush=True,
        )

    alive_check = (
        builder_alive_fn
        if builder_alive_fn
        else (lambda: builder_alive(runtime_dir, event_bus))
    )
    if alive_check():
        print(
            f"[supervisor] bootstrap: Builder lock is fresh for {ticket_id}, "
            "deferring requeue until lock expires.",
            flush=True,
        )
        event_bus.emit(
            "SUPERVISOR_REQUEUE_DEFERRED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "trigger_sequence": requeue_trigger_seq,
                "reason": "builder_lock_fresh",
                "watermark": state.last_requeue_trigger_sequence,
            },
        )
        return False

    blocking_seq = _has_handoff_blocked_after_sequence(
        event_bus, ticket_id, requeue_trigger_seq
    )
    if blocking_seq > 0:
        print(
            f"[supervisor] bootstrap: HANDOFF_BLOCKED at seq={blocking_seq} after "
            f"trigger seq={requeue_trigger_seq} for {ticket_id}. "
            "Suppressing relaunch.",
            flush=True,
        )
        event_bus.emit(
            "RELAUNCH_SUPPRESSED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "reason": "handoff_blocked",
                "trigger_sequence": requeue_trigger_seq,
                "blocking_sequence": blocking_seq,
            },
        )
        return False

    print(
        f"[supervisor] bootstrap: unprocessed CHANGES trigger at seq={requeue_trigger_seq} "
        f"for {ticket_id}. Firing requeue.",
        flush=True,
    )
    if cleanup_session_fn:
        cleanup_session_fn()
    else:
        bus_cleanup_builder_session(runtime_dir)

    if materialize_turn_blockers_fn:
        materialize_turn_blockers_fn(ticket_id)
    else:
        _materialize_turn_blockers(collaboration_dir, event_bus, ticket_id)

    impl = requeue_ticket_fn if requeue_ticket_fn else requeue_ticket
    if requeue_ticket_fn:
        return requeue_ticket_fn(ticket_id, requeue_trigger_seq)
    return impl(
        runtime_dir=runtime_dir,
        event_bus=event_bus,
        project_root=project_root,
        collaboration_dir=collaboration_dir,
        state_path_file=state_path_file,
        turn_path=turn_path,
        work_plan_path=work_plan_path,
        execution_log_path=execution_log_path,
        ticket_id=ticket_id,
        trigger_seq=requeue_trigger_seq,
        load_state_fn=load_state_fn,
        save_state_fn=save_state_fn,
        current_state_fn=current_state_fn,
        relaunch_builder_fn=relaunch_builder_fn,
        builder_alive_fn=builder_alive_fn,
        run_launcher_fn=run_launcher_fn,
    )


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


def run_once(  # noqa: C901
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    process_new_events_fn=None,
    requeue_ticket_fn=None,
) -> tuple[bool, bool]:
    if load_state_fn is None:
        return False, False
    state = load_state_fn()

    if get_approval_store_fn:
        try:
            store = get_approval_store_fn()
            expired = store.check_and_expire_all()
            for req in expired:
                target_state = "BLOCKED"
                if req.reason == ApprovalReason.TIMEOUT_EXPIRED:
                    target_state = "BLOCKED"
                    if transition_ticket_fn:
                        transition_ticket_fn(
                            ticket_id=req.ticket_id,
                            new_state=target_state,
                            reason=f"Approval {req.approval_id} expired after {req.timeout_seconds}s",
                        )
                event_bus.emit(
                    "APPROVAL_RESOLVED",
                    ticket_id=req.ticket_id,
                    actor="SUPERVISOR",
                    payload={
                        "approval_id": req.approval_id,
                        "status": req.status.value,
                        "reason": req.reason.value if req.reason else "TIMEOUT_EXPIRED",
                        "to_state": target_state,
                        "message": "Approval expired automatically by supervisor timeout policy",
                    },
                )
                print(
                    f"[ticket-supervisor] Auto-expired approval {req.approval_id}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[ticket-supervisor] Error checking approval timeouts: {exc}",
                file=sys.stderr,
                flush=True,
            )

    previous_sequence = state.last_processed_sequence
    events = event_bus.read_events()
    new_events = [
        e for e in events if e.sequence_number > state.last_processed_sequence
    ]

    changed = process_new_events_fn() if process_new_events_fn else False
    state = load_state_fn()
    event_activity = state.last_processed_sequence > previous_sequence

    if (
        state.active_ticket
        and materialize_ticket_projection_fn
        and materialize_ticket_projection_fn(
            state.active_ticket,
            current_state_fn(state.active_ticket)
            if current_state_fn
            else TicketState.UNKNOWN,
        )
    ):
        changed = True

    requeue_trigger_sequence = _latest_changes_trigger_sequence(
        new_events, ticket_id=state.active_ticket
    )

    requeue_triggered = (
        requeue_trigger_sequence > 0
        and requeue_trigger_sequence > state.last_requeue_trigger_sequence
    )

    requeue_success = False
    if requeue_triggered and state.active_ticket:
        blocking_seq = _has_handoff_blocked_after_sequence(
            event_bus, state.active_ticket, requeue_trigger_sequence
        )
        if blocking_seq > 0:
            print(
                f"[supervisor] run_once: HANDOFF_BLOCKED at seq={blocking_seq} after "
                f"trigger seq={requeue_trigger_sequence} for {state.active_ticket}. "
                "Suppressing relaunch.",
                flush=True,
            )
            event_bus.emit(
                "RELAUNCH_SUPPRESSED",
                ticket_id=state.active_ticket,
                actor="SUPERVISOR",
                payload={
                    "reason": "handoff_blocked",
                    "trigger_sequence": requeue_trigger_sequence,
                    "blocking_sequence": blocking_seq,
                },
            )
        else:
            _materialize_turn_blockers(
                collaboration_dir, event_bus, state.active_ticket
            )
            requeue_succeeded = (
                requeue_ticket_fn(state.active_ticket, requeue_trigger_sequence)
                if requeue_ticket_fn
                else requeue_ticket(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    ticket_id=state.active_ticket,
                    trigger_seq=requeue_trigger_sequence,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    current_state_fn=current_state_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                    builder_alive_fn=builder_alive_fn,
                    run_launcher_fn=run_launcher_fn,
                )
            )
            if requeue_succeeded:
                changed = True
                requeue_success = True

    if advance_if_review_ready_fn and advance_if_review_ready_fn():
        changed = True
    return changed or event_activity, requeue_success


def run_reactive(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    bootstrap_fn=None,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    release_supervisor_lock_fn=None,
    relaunch_builder_fn=None,
    run_once_fn=None,
    builder_alive_fn=None,
    get_requeue_triggered_fn=None,
    clear_requeue_triggered_fn=None,
    timeout_seconds: float = 300.0,
):
    if bootstrap_fn is None or bootstrap_fn() is False:
        return False

    _emit_supervisor_restarted_if_requested(runtime_dir, event_bus, load_state_fn)

    state_after_bootstrap = load_state_fn() if load_state_fn else None
    if not state_after_bootstrap or not state_after_bootstrap.active_ticket:
        print(
            "[supervisor] idle: no active ticket. Waiting for Manager to create a new plan.",
            flush=True,
        )
        event_bus.emit(
            "SUPERVISOR_IDLE",
            ticket_id="__bootstrap__",
            actor="SUPERVISOR",
            payload={"reason": "no active ticket after bootstrap"},
        )

    idle_timeout = _timeout_from_env(
        "TICKET_SUPERVISOR_IDLE_TIMEOUT_SECONDS", timeout_seconds
    )
    max_runtime = _timeout_from_env("TICKET_SUPERVISOR_MAX_RUNTIME_SECONDS", 3600.0)
    start_time = time.time()
    last_activity = start_time
    changed = False
    try:
        while True:
            if _should_stop_run_reactive(
                start_time=start_time,
                last_activity=last_activity,
                idle_timeout=idle_timeout,
                max_runtime=max_runtime,
                now=time.time(),
                runtime_dir=runtime_dir,
                event_bus=event_bus,
                builder_alive_fn=builder_alive_fn,
            ):
                break
            run_changed = (
                run_once_fn()
                if run_once_fn
                else run_once(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    transition_ticket_fn=transition_ticket_fn,
                    get_approval_store_fn=get_approval_store_fn,
                    advance_if_review_ready_fn=advance_if_review_ready_fn,
                    current_state_fn=current_state_fn,
                    materialize_ticket_projection_fn=materialize_ticket_projection_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                )[0]
            )
            if run_changed:
                changed = True
                last_activity = time.time()
            if get_requeue_triggered_fn and get_requeue_triggered_fn():
                if clear_requeue_triggered_fn:
                    clear_requeue_triggered_fn()
                print(
                    "[supervisor] Builder-only requeue: staying alive as watcher",
                    flush=True,
                )
            time.sleep(1.0)
    finally:
        if release_supervisor_lock_fn:
            release_supervisor_lock_fn()
    return changed


def run_loop(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    bootstrap_fn=None,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    release_supervisor_lock_fn=None,
    relaunch_builder_fn=None,
    run_once_fn=None,
    poll_interval: float = 1.0,
):
    if bootstrap_fn is None or bootstrap_fn() is False:
        return
    try:
        while True:
            if run_once_fn:
                run_once_fn()
            else:
                run_once(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    transition_ticket_fn=transition_ticket_fn,
                    get_approval_store_fn=get_approval_store_fn,
                    advance_if_review_ready_fn=advance_if_review_ready_fn,
                    current_state_fn=current_state_fn,
                    materialize_ticket_projection_fn=materialize_ticket_projection_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                )
            time.sleep(poll_interval)
    finally:
        if release_supervisor_lock_fn:
            release_supervisor_lock_fn()
