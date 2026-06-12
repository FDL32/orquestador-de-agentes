"""Builder relaunch topology and launcher helpers extracted from ``builder_lifecycle``.

This module owns artifact validation, launcher resolution, subprocess
execution, log persistence, blocker materialization, and relaunch verification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .builder_capsule import _build_relaunch_capsule
from .builder_locks import (
    _has_builder_exited_after,
    _parse_iso_datetime,
    builder_alive,
    bus_cleanup_builder_session,
)
from .event_bus import EventBus


_BUILDER_START_VERIFY_TIMEOUT_ENV = "BUILDER_START_VERIFY_TIMEOUT_SECONDS"
_BUILDER_START_VERIFY_TIMEOUT_DEFAULT = 20.0


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

    for artifact_name, artifact_path in [
        ("work_plan.md", work_plan_path),
        ("TURN.md", turn_path),
        ("STATE.md", state_path_file),
    ]:
        if not artifact_path.exists():
            continue
        ok, message = _check_artifact(artifact_name, artifact_path)
        if not ok:
            return False, message

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
            from runtime.motor_link import resolve_motor_root as _resolve_motor_root

            motor_root = _resolve_motor_root(project_root)
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
            match = re.search(r"ACTIVE_TICKET:\s*(\S+)", state_content)
            if match:
                artifact_ticket = match.group(1)
                if artifact_ticket != ticket_id:
                    return (
                        False,
                        f"Ticket mismatch: STATE.md says {artifact_ticket} "
                        f"but relaunching for {ticket_id}",
                    )
        except OSError:
            pass

    return True, ""


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
    if exit_code == -1 and "timed out" in stderr:
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
