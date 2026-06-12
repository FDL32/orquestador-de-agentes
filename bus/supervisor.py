from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .approval import ApprovalPolicy, ApprovalStatus, ApprovalStore
from .builder_lifecycle import (
    MANAGER_STALE_TIMEOUT as MANAGER_STALE_TIMEOUT,
    RELAUNCH_BLOCKED_STATES as RELAUNCH_BLOCKED_STATES,
    REQUEUE_CLAIMS_DIRNAME as REQUEUE_CLAIMS_DIRNAME,
    _BUILDER_START_VERIFY_TIMEOUT_DEFAULT as _BUILDER_START_VERIFY_TIMEOUT_DEFAULT,
    _BUILDER_START_VERIFY_TIMEOUT_ENV as _BUILDER_START_VERIFY_TIMEOUT_ENV,
    _REQUEUE_CLAIM_TTL_ENV as _REQUEUE_CLAIM_TTL_ENV,
    _bootstrap_requeue_if_needed as _bootstrap_requeue_if_needed,
    _build_relaunch_capsule as _build_relaunch_capsule,
    _capsule_blockers_from_turn as _capsule_blockers_from_turn,
    _capsule_hechos_from_bus as _capsule_hechos_from_bus,
    _capsule_hechos_from_log_tail as _capsule_hechos_from_log_tail,
    _capsule_hechos_from_state as _capsule_hechos_from_state,
    _capsule_hechos_from_work_plan as _capsule_hechos_from_work_plan,
    _capsule_hipotesis_from_log as _capsule_hipotesis_from_log,
    _check_artifact as _check_artifact,
    _claim_requeue as _claim_requeue,
    _cleanup_terminal_requeue_claims as _cleanup_terminal_requeue_claims,
    _emit_supervisor_restarted_if_requested as _emit_supervisor_restarted_if_requested,
    _get_claim_ttl as _get_claim_ttl,
    _get_verify_timeout as _get_verify_timeout,
    _has_builder_exited_after as _has_builder_exited_after,
    _has_handoff_blocked_after_sequence as _has_handoff_blocked_after_sequence,
    _has_relaunched_for_trigger as _has_relaunched_for_trigger,
    _is_manager_bridge_stale as _is_manager_bridge_stale_bare,
    _is_pid_alive as _is_pid_alive_bare,
    _latest_changes_trigger_sequence as _latest_changes_trigger_sequence_bare,
    _materialize_turn_blockers as _materialize_turn_blockers_bare,
    _parse_iso_datetime as _parse_iso_datetime,
    _persist_relaunch_log as _persist_relaunch_log_bare,
    _relaunch_builder as _relaunch_builder_bare,
    _resolve_launcher_path as _resolve_launcher_path_bare,
    _run_launcher_subprocess as _run_launcher_subprocess_bare,
    _should_stop_run_reactive as _should_stop_run_reactive_bare,
    _timeout_from_env as _timeout_from_env_bare,
    _verify_builder_start as _verify_builder_start_bare,
    _verify_relaunch_topology as _verify_relaunch_topology_bare,
    builder_alive as _builder_alive_bare,
    bus_cleanup_builder_session as _bus_cleanup_builder_session,
    requeue_ticket as _requeue_ticket_bare,
    run_loop as _run_loop_bare,
    run_once as _run_once_bare,
    run_reactive as _run_reactive_bare,
)
from .event_bus import EventBus
from .exceptions import ConcurrentStateError
from .state_machine import StateMachine, TicketState
from .ticket_id import (
    LOOSE_PATTERN,
    NEXT_TICKET_PATTERN,
    NUMERIC_SUFFIX_PATTERN,
    TICKET_ID_PATTERN,
    TICKET_SORT_KEY_PATTERN,
    TURN_TABLE_PATTERN,
    WORKPLAN_FIELD_PATTERN,
    WORKPLAN_HEADING_PATTERN,
)


# Non-terminal states: supervisor must preserve active_ticket while bus is in these states.
# Execution log may lag behind the bus, so we never clear active_ticket based solely on
# execution_log status when the bus confirms a non-terminal state.
NON_TERMINAL_STATES = frozenset(
    {
        TicketState.READY_FOR_REVIEW,
        TicketState.READY_TO_CLOSE,
        TicketState.IN_PROGRESS,
        TicketState.BLOCKED,
        TicketState.HUMAN_GATE,
    }
)


@dataclass(slots=True)
class SupervisorState:
    active_ticket: str | None = None
    completed_tickets: list[str] = field(default_factory=list)
    last_action: str = ""
    last_processed_sequence: int = 0
    loop_current_round: int = 0
    loop_max_rounds: int = 0
    last_requeue_trigger_sequence: int = 0
    last_manager_stale_trigger_sequence: int = 0
    _revision: int | None = field(default=None, repr=False, compare=False)


class SequentialTicketSupervisor:
    def __init__(
        self,
        project_root: Path,
        collaboration_dir: Path | None = None,
        runtime_dir: Path | None = None,
        auto_sync: bool = True,
    ):
        self.project_root = Path(project_root)
        self.collaboration_dir = Path(
            collaboration_dir or self.project_root / ".agent" / "collaboration"
        )
        self.runtime_dir = Path(runtime_dir or self.project_root / ".agent" / "runtime")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.turn_path = self.collaboration_dir / "TURN.md"
        self.work_plan_path = self.collaboration_dir / "work_plan.md"
        self.execution_log_path = self.collaboration_dir / "execution_log.md"
        self.state_path_file = self.collaboration_dir / "STATE.md"
        self.review_queue_path = self.collaboration_dir / "review_queue.md"
        self.notifications_path = self.collaboration_dir / "notifications.md"
        self.event_bus = EventBus(runtime_dir=self.runtime_dir / "events")
        self.auto_sync = auto_sync
        self.state_path = self.runtime_dir / "supervisor_state.json"
        self.supervisor_lock_path = self.runtime_dir / "supervisor_lock.txt"
        self._lock_fd: int | None = None
        self._supervisor_lock_held: bool = False

    def save_state(self, state: SupervisorState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(state)
        data.pop("_revision", None)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        new_rev = self.write_artifact_atomic(
            self.state_path,
            content,
            expected_revision=getattr(state, "_revision", None),
        )
        state._revision = new_rev

    def _compute_revision(self, content: str) -> int:
        """Compute a revision number from content hash.

        Before: State writes had no revision tracking.
        During: Revision is computed as a hash-based integer from content.
        After: Returns monotonically increasing revision number for OCC.
        """
        import hashlib

        return int(hashlib.sha256(content.encode("utf-8")).hexdigest()[:8], 16)

    def _read_artifact_with_revision(
        self, artifact_path: Path
    ) -> tuple[str, int | None]:
        """Read artifact content and compute its current revision.

        Args:
            artifact_path: Path to the artifact file.

        Returns:
            Tuple of (content, revision) where revision is None if file doesn't exist.
        """
        if not artifact_path.exists():
            return "", None
        content = artifact_path.read_text(encoding="utf-8")
        revision = self._compute_revision(content)
        return content, revision

    def write_artifact_atomic(
        self,
        artifact_path: Path,
        new_content: str,
        expected_revision: int | None = None,
        ticket_id: str | None = None,
        max_retries: int = 3,
        retry_delay_ms: int = 50,
    ) -> int:
        """Write an artifact atomically with optimistic concurrency control.

        Before: State writes could overwrite concurrent modifications silently.
        During: Writer provides expectedRevision; bus compares with current revision
                and retries on conflict up to max_retries.
        After: Write succeeds with new revision, or raises ConcurrentStateError.

        Args:
            artifact_path: Path to the artifact file.
            new_content: New content to write.
            expected_revision: Expected current revision (None for blind write).
            ticket_id: Optional ticket ID for error context.
            max_retries: Maximum number of OCC retry attempts.
            retry_delay_ms: Delay between retries in milliseconds.

        Returns:
            The new revision number after successful write.

        Raises:
            ConcurrentStateError: If revision mismatch persists after all retries.
        """
        import time

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = artifact_path.with_name(artifact_path.name + ".lock")

        for attempt in range(max_retries):
            lock_fd = None
            try:
                lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                # Stale lock recovery: if lock is older than 30 seconds, break it
                try:
                    if time.time() - os.path.getmtime(lock_path) > 30.0:
                        os.unlink(lock_path)
                        continue  # retry immediately after breaking stale lock
                except OSError:
                    pass  # File might have been deleted concurrently

                if attempt < max_retries - 1:
                    time.sleep(retry_delay_ms / 1000.0 * (attempt + 1))
                    continue
                raise ConcurrentStateError(
                    artifact_path=str(artifact_path),
                    expected_revision=expected_revision,
                    actual_revision=None,
                    ticket_id=ticket_id,
                ) from None

            try:
                # Read current content and revision under the lock
                _, current_revision = self._read_artifact_with_revision(artifact_path)

                # Check expected revision if provided
                if (
                    expected_revision is not None
                    and current_revision != expected_revision
                ):
                    raise ConcurrentStateError(
                        artifact_path=str(artifact_path),
                        expected_revision=expected_revision,
                        actual_revision=current_revision,
                        ticket_id=ticket_id,
                    ) from None

                # Write atomically via temp file + replace
                fd, temp_path = tempfile.mkstemp(
                    dir=str(artifact_path.parent),
                    prefix=".tmp_",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    os.replace(temp_path, str(artifact_path))
                except Exception:
                    import contextlib

                    with contextlib.suppress(OSError):
                        os.unlink(temp_path)
                    raise

                # Compute and return new revision
                return self._compute_revision(new_content)
            finally:
                if lock_fd is not None:
                    try:
                        os.close(lock_fd)
                        os.unlink(str(lock_path))
                    except OSError:
                        pass

        # Should not reach here, but defensive fallback
        raise ConcurrentStateError(
            artifact_path=str(artifact_path),
            expected_revision=expected_revision,
            actual_revision=None,
            ticket_id=ticket_id,
        )

    def get_approval_store(self) -> ApprovalStore:
        """Get or create the approval store for this supervisor.

        Before: No persistent approval store existed.
        During: ApprovalStore is lazily created under runtime_dir.
        After: Returns configured ApprovalStore for managing approval requests.
        """
        store_path = self.runtime_dir / "approvals" / "store.json"
        # This policy timeout only applies to requests created directly by the
        # supervisor. HUMAN_GATE requests are created by agent_controller with
        # their own timeout (manager_review.human_gate_timeout_seconds, default
        # 86400s); is_expired() reads the request's own timeout_seconds, so
        # this 300s default does not affect those requests.
        policy = ApprovalPolicy(
            policy_name="default",
            timeout_seconds=300,
            auto_resolve=True,
            auto_resolve_status=ApprovalStatus.EXPIRED,
        )
        return ApprovalStore(store_path=store_path, policy=policy)

    def _acquire_supervisor_lock(self) -> bool:
        """Acquire supervisor instance lock atomically.

        Before: No instance lock existed; multiple supervisors could start on same ticket.
        During: Attempts atomic lock acquisition with O_CREAT | O_EXCL to prevent TOCTOU.
                If lock exists, checks liveness via PID (Windows) + mtime fallback (15 min).
                Stale locks are broken and re-acquired.
        After: Returns True if lock acquired, False if another live instance holds it.

        Lock file format (JSON):
        {
            "ticket_id": "WT-2026-XXX",
            "pid": <process_id>,
            "started_at": "<ISO8601 timestamp>"
        }
        """
        import contextlib
        import json
        import os
        from datetime import datetime

        # Reentrancy: same instance already holds the lock (e.g. standalone
        # bootstrap() call followed by run_reactive() calling bootstrap() again).
        if self._supervisor_lock_held:
            return True

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        lock_path = str(self.supervisor_lock_path)

        try:
            # Try atomic acquire first
            self._lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            # Write lock metadata
            lock_data = {
                "ticket_id": self.load_state().active_ticket,
                "pid": os.getpid(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            with os.fdopen(self._lock_fd, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2)
            self._supervisor_lock_held = True
            return True
        except FileExistsError:
            # Lock exists - check if it's stale
            if self._is_supervisor_lock_stale():
                # Break stale lock and re-acquire
                with contextlib.suppress(OSError):
                    os.unlink(lock_path)
                # Retry acquisition
                return self._acquire_supervisor_lock()
            else:
                # Lock is held by a live instance
                return False

    def _is_supervisor_lock_stale(self) -> bool:
        """Check if supervisor lock is stale (orphaned).

        Before: No stale lock detection.
        During: Checks PID liveness via tasklist (Windows) + mtime fallback (15 min).
        After: Returns True if lock is stale and can be broken safely.
        """
        import json
        import time

        if not self.supervisor_lock_path.exists():
            return True  # No lock = can acquire

        try:
            lock_data = json.loads(
                self.supervisor_lock_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return True  # Corrupt lock = stale

        # Check PID liveness (Windows only)
        pid = lock_data.get("pid")
        if pid and self._is_pid_alive(pid):
            return False  # PID alive = lock is live

        # Fallback: mtime check (15 min TTL)
        try:
            age = time.time() - self.supervisor_lock_path.stat().st_mtime
            return age > 900  # 15 minutes
        except OSError:
            return True  # Can't stat = assume stale

    def _release_supervisor_lock(self) -> None:
        """Release supervisor instance lock.

        Before: No lock release mechanism.
        During: Closes lock file descriptor and removes lock file.
        After: Lock file is removed; other instances can acquire.
        """
        import contextlib
        import os

        self._supervisor_lock_held = False

        if self._lock_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._lock_fd)
            self._lock_fd = None

        with contextlib.suppress(OSError):
            if self.supervisor_lock_path.exists():
                self.supervisor_lock_path.unlink()

    def _get_supervisor_lock_holder(self) -> dict | None:
        """Read lock file and return lock holder info.

        Before: No way to inspect lock holder.
        During: Parses lock file JSON if it exists and is valid.
        After: Returns dict with ticket_id, pid, started_at or None if no lock.
        """
        import json

        if not self.supervisor_lock_path.exists():
            return None

        try:
            return json.loads(self.supervisor_lock_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _normalize_ticket_id(ticket_id: str | None) -> str | None:
        if ticket_id is None:
            return None
        normalized = str(ticket_id).strip()
        if not normalized or normalized.upper() in {"UNKNOWN", "NONE", "N/A"}:
            return None
        return normalized

    def load_state(self) -> SupervisorState:
        if not self.state_path.exists():
            return SupervisorState()
        content, revision = self._read_artifact_with_revision(self.state_path)
        data = json.loads(content)
        return SupervisorState(
            active_ticket=self._normalize_ticket_id(data.get("active_ticket")),
            completed_tickets=list(data.get("completed_tickets") or []),
            last_action=str(data.get("last_action", "")),
            last_processed_sequence=int(data.get("last_processed_sequence", 0)),
            loop_current_round=int(data.get("loop_current_round", 0)),
            loop_max_rounds=int(data.get("loop_max_rounds", 0)),
            last_requeue_trigger_sequence=int(
                data.get("last_requeue_trigger_sequence", 0)
            ),
            last_manager_stale_trigger_sequence=int(
                data.get("last_manager_stale_trigger_sequence", 0)
            ),
            _revision=revision,
        )

    def ensure_ticket_queue(self) -> None:
        work_plan = self.collaboration_dir / "work_plan.md"
        work_plan.parent.mkdir(parents=True, exist_ok=True)
        if not work_plan.exists():
            work_plan.write_text("# Plan de Trabajo del Proyecto\n", encoding="utf-8")
            return

        content = work_plan.read_text(encoding="utf-8")
        tickets = re.findall(TICKET_ID_PATTERN, content)
        if not tickets:
            return
        match = re.search(TICKET_SORT_KEY_PATTERN, tickets[0])
        if not match:
            return
        prefix = match.group(1)
        last_num = (
            int(re.findall(NUMERIC_SUFFIX_PATTERN, tickets[-1])[0])
            if re.search(NUMERIC_SUFFIX_PATTERN, tickets[-1])
            else 0
        )
        if last_num == 0:
            return
        additions = []
        for offset in (1, 2):
            candidate = f"WT-{prefix}-{last_num + offset:03d}"
            if candidate not in content:
                additions.append(
                    "\n".join(
                        [
                            "",
                            f"## {candidate}: Ticket adicional",
                            "",
                            "### Metadata",
                            f"- **ID:** {candidate}",
                            "- **Estado:** PENDING",
                            "- **Creado por:** Supervisor",
                            "- **Fecha:** 2026-05-13",
                            "",
                            "### Objetivo",
                            "Tarea de consolidacion operativa.",
                        ]
                    )
                )
        if additions:
            work_plan.write_text(
                content.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8"
            )

    def activate_ticket(self, ticket_id: str) -> None:
        state = self.load_state()
        state.active_ticket = ticket_id
        state.last_action = "ACTIVATE"
        self.save_state(state)
        self.event_bus.emit(
            "SUPERVISOR_ACTIVATED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={"action": "ACTIVATE"},
        )

    def _current_state(self, ticket_id: str) -> TicketState:
        events = [
            event.to_dict() for event in self.event_bus.read_events(ticket_id=ticket_id)
        ]
        return StateMachine.derive_state_from_events(events)

    def _last_state_changed(self, ticket_id: str) -> str:
        events = self.event_bus.read_events(
            ticket_id=ticket_id, event_type="STATE_CHANGED"
        )
        if not events:
            return ""
        return str((events[-1].payload or {}).get("to_state", "")).upper()

    def transition_ticket(
        self,
        ticket_id: str,
        new_state: str,
        reason: str,
        source_event_id: str | None = None,
    ) -> None:
        current = self._current_state(ticket_id)
        self.event_bus.emit(
            "STATE_CHANGED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "from_state": current.value,
                "to_state": new_state,
                "reason": reason,
                "source": "supervisor",
                "source_event_id": source_event_id,
            },
        )

    def can_builder_act(self, ticket_id: str) -> bool:
        state = self._current_state(ticket_id)
        return state in {
            TicketState.IN_PROGRESS,
            TicketState.COMPLETED,
            TicketState.UNKNOWN,
        }

    def close_active_ticket(self) -> bool:
        state = self.load_state()
        if not state.active_ticket:
            return False
        ticket_id = state.active_ticket
        if self._last_state_changed(ticket_id) != "READY_TO_CLOSE":
            return False
        if not self.event_bus.latest_event(
            ticket_id=ticket_id, event_type="CLOSE_CONFIRMED"
        ):
            return False
        self.event_bus.emit(
            "STATE_CHANGED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "from_state": "READY_TO_CLOSE",
                "to_state": "COMPLETED",
                "reason": "Closeout confirmed",
                "source": "supervisor",
            },
        )
        self.event_bus.emit(
            "SUPERVISOR_CLOSED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={"action": "close_active_ticket"},
        )
        state.completed_tickets.append(ticket_id)
        state.active_ticket = None
        state.last_action = "CLOSE"
        self.save_state(state)
        return True

    def advance_if_review_ready(self) -> bool:
        state = self.load_state()
        if not state.active_ticket:
            return False
        ticket_id = state.active_ticket
        if self._last_state_changed(ticket_id) != "READY_TO_CLOSE":
            return False
        if not self.close_active_ticket():
            return False
        next_ticket = self._next_ticket_id(ticket_id)
        if next_ticket:
            state = self.load_state()
            state.active_ticket = next_ticket
            state.last_action = "ADVANCE"
            self.save_state(state)
            self.event_bus.emit(
                "HANDOFF_REQUESTED",
                ticket_id=next_ticket,
                actor="SUPERVISOR",
                payload={"target_role": "BUILDER"},
            )
            self.event_bus.emit(
                "STATE_CHANGED",
                ticket_id=next_ticket,
                actor="SUPERVISOR",
                payload={
                    "from_state": "N/A",
                    "to_state": "IN_PROGRESS",
                    "reason": "Next ticket activated",
                    "source": "supervisor",
                },
            )
        return True

    def _next_ticket_id(self, ticket_id: str) -> str | None:
        match = NEXT_TICKET_PATTERN.fullmatch(ticket_id)
        if not match:
            return None
        prefix, number = match.groups()
        return f"WT-{prefix}-{int(number) + 1:03d}"

    def _execution_log_status(self, ticket_id: str) -> str:
        path = self.collaboration_dir / "execution_log.md"
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        pattern = rf"##\s+{re.escape(ticket_id)}.*?\*\*Estado:\*\*\s*([A-Z_]+)"
        match = re.search(pattern, content, re.S)
        return match.group(1) if match else ""

    def recover_active_ticket(self) -> str | None:
        turn_path = self.collaboration_dir / "TURN.md"
        if turn_path.exists():
            content = turn_path.read_text(encoding="utf-8")
            patterns = (TURN_TABLE_PATTERN,) * 4
            for pattern in patterns:
                match = pattern.search(content)
                if match:
                    return match.group(1)
            loose_match = LOOSE_PATTERN.search(content)
            if loose_match:
                return loose_match.group(1)
        work_plan_path = self.collaboration_dir / "work_plan.md"
        if work_plan_path.exists():
            content = work_plan_path.read_text(encoding="utf-8")
            patterns = (
                WORKPLAN_FIELD_PATTERN,
                WORKPLAN_FIELD_PATTERN,
                WORKPLAN_HEADING_PATTERN,
            )
            for pattern in patterns:
                match = pattern.search(content)
                if match:
                    return match.group(1)
            loose_match = LOOSE_PATTERN.search(content)
            if loose_match:
                return loose_match.group(1)
        latest = self.event_bus.latest_event(event_type="TURN_CHANGED")
        if latest:
            return latest.ticket_id
        return None

    def _work_plan_active_ticket(self) -> str | None:
        work_plan_path = self.collaboration_dir / "work_plan.md"
        if not work_plan_path.exists():
            return None
        content = work_plan_path.read_text(encoding="utf-8")
        patterns = (
            WORKPLAN_FIELD_PATTERN,
            WORKPLAN_FIELD_PATTERN,
            WORKPLAN_HEADING_PATTERN,
        )
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                return match.group(1)
            loose_match = LOOSE_PATTERN.search(content)
            if loose_match:
                return loose_match.group(1)
        return None

    def _is_state_terminal(self, state: TicketState) -> bool:
        """Check if a TicketState is terminal (i.e., active_ticket can be cleared).

        Before: Inline set comparison in bootstrap().
        During: Delegates to NON_TERMINAL_STATES constant for single source of truth.
        After: Returns True only for COMPLETED, UNKNOWN, and any future terminal states.
        """
        return state not in NON_TERMINAL_STATES

    @staticmethod
    def _ticket_sort_key(ticket_id: str) -> tuple[int, int, str]:
        """Return a sortable authority key for a WP ticket id.

        Higher keys win. We order by WP year, then by numeric suffix, then by
        raw suffix as a stable tie-breaker for any non-numeric variant.
        """
        match = re.match(TICKET_SORT_KEY_PATTERN, ticket_id or "")
        if not match:
            return (-1, -1, ticket_id or "")
        year = int(match.group(1))
        suffix = match.group(2)
        numeric_match = re.match(r"(\d+)", suffix)
        numeric_suffix = int(numeric_match.group(1)) if numeric_match else -1
        return (year, numeric_suffix, suffix)

    def _is_approved_zombie_ready_to_close(self, ticket_id: str) -> bool:
        """Return True if ticket is a zombie: READY_TO_CLOSE but approved and never closed.

        Before: ticket_id is in READY_TO_CLOSE state per bus.
        During: Checks for REVIEW_DECISION(approve) and absence of SUPERVISOR_CLOSED.
                A ticket that has been approved but whose Supervisor died before emitting
                SUPERVISOR_CLOSED is stuck in READY_TO_CLOSE indefinitely.
        After: Returns True only for the zombie pattern; False for legitimate
               READY_TO_CLOSE tickets still awaiting approval.

        WT-2026-194: prevents zombie from blocking reconcile_state() on restart.
        """
        events = self.event_bus.read_events(ticket_id=ticket_id)
        has_approve = any(
            e.event_type == "REVIEW_DECISION"
            and str((e.payload or {}).get("decision", "")).lower() == "approve"
            for e in events
        )
        has_closed = any(e.event_type == "SUPERVISOR_CLOSED" for e in events)
        return has_approve and not has_closed

    def _bus_active_non_terminal_ticket(self) -> str | None:
        """Find the active non-terminal ticket from the event bus.

        Before: bootstrap() relied on TURN.md and work_plan.md as primary sources.
        During: Scans all tickets in the bus, derives their current state, and
                returns the highest-authority ticket in a non-terminal state
                (READY_FOR_REVIEW, READY_TO_CLOSE, IN_PROGRESS, BLOCKED, HUMAN_GATE).
                Excludes READY_TO_CLOSE tickets that are approved zombies (WT-2026-194).
        After: Returns the bus-authoritative active ticket or None if no active ticket.
        """
        all_events = self.event_bus.read_events()
        seen_tickets: dict[str, TicketState] = {}
        for event in all_events:
            tid = event.ticket_id
            if tid and tid not in seen_tickets:
                ticket_events = [
                    e.to_dict() for e in self.event_bus.read_events(ticket_id=tid)
                ]
                seen_tickets[tid] = StateMachine.derive_state_from_events(ticket_events)

        active_tickets = [
            tid
            for tid, tstate in seen_tickets.items()
            if tstate in NON_TERMINAL_STATES
            and not (
                tstate == TicketState.READY_TO_CLOSE
                and self._is_approved_zombie_ready_to_close(tid)
            )
        ]
        if not active_tickets:
            return None
        return max(active_tickets, key=self._ticket_sort_key)

    def _bootstrap_reconcile_loop_round(
        self, state: SupervisorState, ticket_id: str
    ) -> None:
        """Reconcile loop_current_round from LOOP_INITIALIZED bus events."""
        loop_events = self.event_bus.read_events(
            ticket_id=ticket_id, event_type="LOOP_INITIALIZED"
        )
        if loop_events:
            latest_loop = loop_events[-1]
            bus_round = (latest_loop.payload or {}).get("current_round", 0)
            if bus_round != state.loop_current_round:
                state.loop_current_round = bus_round
                state.last_action = "RECONCILED"
                self.save_state(state)

    def _bootstrap_reconcile_sequence(self, state: SupervisorState) -> None:
        """Reconcile last_processed_sequence with bus reality."""
        events = self.event_bus.read_events()
        if events:
            latest_seq = events[-1].sequence_number
            if latest_seq != state.last_processed_sequence:
                state.last_processed_sequence = latest_seq
                state.last_action = "RECONCILED"
                self.save_state(state)

    def _write_text_if_changed(self, path: Path, content: str) -> bool:
        """Write a text artifact only when its content changes."""
        current = ""
        if path.exists():
            current = path.read_text(encoding="utf-8")
        if current == content:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    def _turn_without_update_timestamp(self, content: str) -> str:
        """Normalize the volatile TURN.md timestamp."""
        return re.sub(
            r"^\*\*Ultima actualizacion:\*\* .*$(?:\r?\n)?",
            "**Ultima actualizacion:** <timestamp>\n",
            content,
            count=1,
            flags=re.MULTILINE,
        )

    def _preserve_turn_blockers(self, content: str) -> str:
        """Carry Manager blockers across projection refreshes."""
        if not self.turn_path.exists():
            return content
        current = self.turn_path.read_text(encoding="utf-8")
        marker = "## Blockers from Manager"
        if marker not in current or marker in content:
            return content

        match = re.search(
            r"\n\n## Blockers from Manager\n\n.*?(?=\n## Estado del Sistema|\Z)",
            current,
            flags=re.DOTALL,
        )
        if not match:
            return content
        blockers_section = match.group(0).rstrip() + "\n\n"
        if "## Estado del Sistema" in content:
            return content.replace(
                "## Estado del Sistema",
                f"{blockers_section}## Estado del Sistema",
                1,
            )
        return content.rstrip() + blockers_section

    def _write_turn_if_semantic_changed(self, content: str) -> bool:
        """Write TURN.md only when role or state semantics change."""
        content = self._preserve_turn_blockers(content)
        current = ""
        if self.turn_path.exists():
            current = self.turn_path.read_text(encoding="utf-8")
        if self._turn_without_update_timestamp(
            current
        ) == self._turn_without_update_timestamp(content):
            return False
        return self._write_text_if_changed(self.turn_path, content)

    @staticmethod
    def _render_turn_for_state(ticket_id: str, state: TicketState) -> str:
        """Render TURN.md for a derived ticket state."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        turn_map: dict[TicketState, tuple[str, str, str, str]] = {
            TicketState.READY_FOR_REVIEW: (
                "MANAGER",
                "REVIEW_WORK",
                f"Builder completo {ticket_id}. Revisa el trabajo.",
                "APPROVED",
            ),
            TicketState.READY_TO_CLOSE: (
                "SUPERVISOR",
                "CLOSEOUT",
                f"Ticket {ticket_id} aprobado. Procede al cierre.",
                "APPROVED",
            ),
            TicketState.IN_PROGRESS: (
                "BUILDER",
                "IMPLEMENT",
                f"Ticket {ticket_id} reactivado. Continua la implementacion.",
                "IN_PROGRESS",
            ),
            TicketState.HUMAN_GATE: (
                "SUPERVISOR",
                "HUMAN_GATE",
                f"Escalada humana requerida para {ticket_id}.",
                "BLOCKED",
            ),
            TicketState.COMPLETED: (
                "MANAGER",
                "CREATE_PLAN",
                f"Ticket {ticket_id} cerrado. Crea el siguiente work_plan.md.",
                "COMPLETED",
            ),
            TicketState.BLOCKED: (
                "SUPERVISOR",
                "BLOCKED",
                f"Ticket {ticket_id} bloqueado. Revisa los bloqueadores.",
                "BLOCKED",
            ),
        }
        role, action_type, instruction, work_plan_status = turn_map.get(
            state,
            (
                "UNKNOWN",
                "STATE_TRANSITION",
                f"Estado materializado desde el bus: {state.value}.",
                state.value,
            ),
        )

        return (
            "# TURNO ACTUAL\n\n"
            f"**Ultima actualizacion:** {timestamp}\n\n"
            "---\n\n"
            "## Agente Activo\n\n"
            "| Campo | Valor |\n"
            "|-------|-------|\n"
            f"| **ROL** | **{role}** |\n"
            f"| **Plan ID** | {ticket_id} |\n"
            "| **Tipo** | IMPLEMENT |\n"
            f"| **Accion** | {action_type} |\n"
            "\n---\n\n"
            "## Instruccion\n\n"
            f"> {instruction}\n\n"
            "---\n\n"
            "## Estado del Sistema\n\n"
            "| Archivo | Estado |\n"
            "|---------|--------|\n"
            f"| work_plan.md | {work_plan_status} |\n"
            f"| execution_log.md | {state.value} |\n"
            "\n---\n\n"
            f"*Preparado documentalmente para {ticket_id}*\n"
        )

    def _materialize_ticket_projection(
        self, ticket_id: str, state: TicketState
    ) -> bool:
        """Materialize active-ticket projections synchronously."""
        if state == TicketState.UNKNOWN:
            return False
        changed = False

        changed |= self._write_turn_if_semantic_changed(
            self._render_turn_for_state(ticket_id, state)
        )
        changed |= self._write_text_if_changed(
            self.state_path_file, f"ACTIVE_TICKET: {ticket_id}\nSTATUS: {state.value}\n"
        )

        if self.execution_log_path.exists():
            log_content = self.execution_log_path.read_text(encoding="utf-8")
            updated_log = log_content
            for old_marker in (
                "**Estado:**",
                "Estado documental:",
                "Estado actual:",
            ):
                if old_marker in updated_log:
                    updated_log = re.sub(
                        rf"{re.escape(old_marker)}\s*.*",
                        f"{old_marker} {state.value}",
                        updated_log,
                        count=1,
                    )
                    break
            else:
                updated_log = (
                    updated_log.rstrip() + f"\n- Estado documental: {state.value}\n"
                )
            if updated_log != log_content:
                changed |= self._write_text_if_changed(
                    self.execution_log_path, updated_log
                )

        return changed

    def _is_manager_bridge_stale(self) -> bool:
        return _is_manager_bridge_stale_bare(self.runtime_dir)

    def _materialize_turn_blockers(self, ticket_id: str) -> None:
        _materialize_turn_blockers_bare(
            self.collaboration_dir, self.event_bus, ticket_id
        )

    @staticmethod
    def _latest_changes_trigger_sequence(
        events: list, ticket_id: str | None = None
    ) -> int:
        return _latest_changes_trigger_sequence_bare(events, ticket_id)

    @staticmethod
    def _check_artifact(name: str, path: Path) -> tuple[bool, str]:
        return _check_artifact(name, path)

    @staticmethod
    def _capsule_hechos_from_work_plan(work_plan_path: Path) -> list[str]:
        return _capsule_hechos_from_work_plan(work_plan_path)

    @staticmethod
    def _capsule_hechos_from_state(state_path: Path) -> list[str]:
        return _capsule_hechos_from_state(state_path)

    @staticmethod
    def _capsule_hechos_from_log_tail(log_path: Path) -> list[str]:
        return _capsule_hechos_from_log_tail(log_path)

    def _capsule_hechos_from_bus(self, ticket_id: str) -> list[str]:
        return _capsule_hechos_from_bus(self.event_bus, ticket_id)

    @staticmethod
    def _capsule_blockers_from_turn(turn_path: Path) -> list[str]:
        return _capsule_blockers_from_turn(turn_path)

    @staticmethod
    def _capsule_hipotesis_from_log(log_path: Path) -> list[str]:
        return _capsule_hipotesis_from_log(log_path)

    def _build_relaunch_capsule(self, ticket_id: str) -> str:
        return _build_relaunch_capsule(
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            runtime_dir=self.runtime_dir,
            work_plan_path=self.work_plan_path,
            state_path_file=self.state_path_file,
            execution_log_path=self.execution_log_path,
            turn_path=self.turn_path,
            event_bus=self.event_bus,
            ticket_id=ticket_id,
        )

    @staticmethod
    def _get_claim_ttl() -> float:
        return _get_claim_ttl()

    @staticmethod
    def _get_verify_timeout() -> float:
        return _get_verify_timeout()

    @staticmethod
    def _timeout_from_env(name: str, default: float) -> float:
        return _timeout_from_env_bare(name, default)

    def _is_pid_alive(self, pid: int) -> bool:
        return _is_pid_alive_bare(pid)

    def _parse_iso_datetime(self, iso_str: str) -> datetime:
        return _parse_iso_datetime(iso_str)

    def _has_builder_exited_after(self, ticket_id: str, lock_start: datetime) -> bool:
        return _has_builder_exited_after(self.event_bus, ticket_id, lock_start)

    def _has_handoff_blocked_after_sequence(
        self, ticket_id: str, trigger_sequence: int
    ) -> int:
        return _has_handoff_blocked_after_sequence(
            self.event_bus, ticket_id, trigger_sequence
        )

    def _builder_alive(self) -> bool:
        return _builder_alive_bare(self.runtime_dir, self.event_bus)

    def _run_launcher_subprocess(self, cmd: list[str]) -> tuple[int, str, str]:
        return _run_launcher_subprocess_bare(self.project_root, cmd)

    def _persist_relaunch_log(self, stdout: str, stderr: str) -> None:
        _persist_relaunch_log_bare(self.runtime_dir, stdout, stderr)

    def _resolve_launcher_path(self) -> Path:
        return _resolve_launcher_path_bare(self.project_root)

    def _verify_relaunch_topology(self, ticket_id: str) -> tuple[bool, str]:
        return _verify_relaunch_topology_bare(
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            runtime_dir=self.runtime_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            ticket_id=ticket_id,
        )

    def _relaunch_builder(self, ticket_id: str, trigger_seq: int = 0) -> bool:
        return _relaunch_builder_bare(
            project_root=self.project_root,
            runtime_dir=self.runtime_dir,
            collaboration_dir=self.collaboration_dir,
            event_bus=self.event_bus,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            ticket_id=ticket_id,
            trigger_seq=trigger_seq,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            builder_alive_fn=self._builder_alive,
            run_launcher_fn=self._run_launcher_subprocess,
            cleanup_session_fn=lambda: _bus_cleanup_builder_session(self.runtime_dir),
            verify_topology_fn=self._verify_relaunch_topology,
            build_capsule_fn=self._build_relaunch_capsule,
            resolve_launcher_fn=self._resolve_launcher_path,
            persist_log_fn=self._persist_relaunch_log,
            verify_builder_start_fn=self._verify_builder_start,
        )

    def _verify_builder_start(
        self,
        ticket_id: str,
        relaunch_started_at: datetime,
        expected_round: int,
    ) -> tuple[str, str]:
        return _verify_builder_start_bare(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            ticket_id=ticket_id,
            relaunch_started_at=relaunch_started_at,
            expected_round=expected_round,
        )

    def _claim_requeue(self, ticket_id: str, trigger_seq: int) -> bool:
        return _claim_requeue(self.runtime_dir, self.event_bus, ticket_id, trigger_seq)

    def _has_relaunched_for_trigger(self, ticket_id: str, trigger_seq: int) -> bool:
        return _has_relaunched_for_trigger(self.event_bus, ticket_id, trigger_seq)

    def _cleanup_terminal_requeue_claims(self, ticket_id: str) -> None:
        _cleanup_terminal_requeue_claims(self.runtime_dir, ticket_id)

    def requeue_ticket(self, ticket_id: str, trigger_seq: int = 0) -> bool:
        return _requeue_ticket_bare(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            ticket_id=ticket_id,
            trigger_seq=trigger_seq,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            current_state_fn=self._current_state,
            relaunch_builder_fn=self._relaunch_builder,
            builder_alive_fn=self._builder_alive,
            run_launcher_fn=self._run_launcher_subprocess,
            claim_requeue_fn=self._claim_requeue,
        )

    def _bootstrap_requeue_if_needed(
        self, state: SupervisorState, ticket_id: str
    ) -> None:
        _bootstrap_requeue_if_needed(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            ticket_id=ticket_id,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            current_state_fn=self._current_state,
            requeue_ticket_fn=self.requeue_ticket,
            relaunch_builder_fn=self._relaunch_builder,
            builder_alive_fn=self._builder_alive,
            run_launcher_fn=self._run_launcher_subprocess,
            cleanup_session_fn=lambda: _bus_cleanup_builder_session(self.runtime_dir),
            materialize_turn_blockers_fn=self._materialize_turn_blockers,
        )

    def _emit_supervisor_restarted_if_requested(self) -> None:
        _emit_supervisor_restarted_if_requested(
            self.runtime_dir, self.event_bus, self.load_state
        )

    def _should_stop_run_reactive(
        self,
        *,
        start_time: float,
        last_activity: float,
        idle_timeout: float,
        max_runtime: float,
        now: float,
    ) -> bool:
        return _should_stop_run_reactive_bare(
            start_time=start_time,
            last_activity=last_activity,
            idle_timeout=idle_timeout,
            max_runtime=max_runtime,
            now=now,
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            builder_alive_fn=self._builder_alive,
        )

    def run_once(self) -> bool:
        changed, requeued = _run_once_bare(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            transition_ticket_fn=self.transition_ticket,
            get_approval_store_fn=self.get_approval_store,
            advance_if_review_ready_fn=self.advance_if_review_ready,
            current_state_fn=self._current_state,
            materialize_ticket_projection_fn=self._materialize_ticket_projection,
            relaunch_builder_fn=self._relaunch_builder,
            builder_alive_fn=self._builder_alive,
            run_launcher_fn=self._run_launcher_subprocess,
            process_new_events_fn=self._process_new_events,
            requeue_ticket_fn=self.requeue_ticket,
        )
        self._requeue_triggered_this_session = requeued
        return changed

    def run_reactive(self, timeout_seconds: float = 300.0):
        return _run_reactive_bare(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            bootstrap_fn=self.bootstrap,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            transition_ticket_fn=self.transition_ticket,
            get_approval_store_fn=self.get_approval_store,
            advance_if_review_ready_fn=self.advance_if_review_ready,
            current_state_fn=self._current_state,
            materialize_ticket_projection_fn=self._materialize_ticket_projection,
            release_supervisor_lock_fn=self._release_supervisor_lock,
            timeout_seconds=timeout_seconds,
            relaunch_builder_fn=self._relaunch_builder,
            run_once_fn=self.run_once,
            builder_alive_fn=self._builder_alive,
            get_requeue_triggered_fn=lambda: getattr(
                self, "_requeue_triggered_this_session", False
            ),
            clear_requeue_triggered_fn=lambda: setattr(
                self, "_requeue_triggered_this_session", False
            ),
        )

    def run_loop(self, poll_interval: float = 1.0):
        _run_loop_bare(
            runtime_dir=self.runtime_dir,
            event_bus=self.event_bus,
            project_root=self.project_root,
            collaboration_dir=self.collaboration_dir,
            state_path_file=self.state_path_file,
            turn_path=self.turn_path,
            work_plan_path=self.work_plan_path,
            execution_log_path=self.execution_log_path,
            bootstrap_fn=self.bootstrap,
            load_state_fn=self.load_state,
            save_state_fn=self.save_state,
            transition_ticket_fn=self.transition_ticket,
            get_approval_store_fn=self.get_approval_store,
            advance_if_review_ready_fn=self.advance_if_review_ready,
            current_state_fn=self._current_state,
            materialize_ticket_projection_fn=self._materialize_ticket_projection,
            release_supervisor_lock_fn=self._release_supervisor_lock,
            poll_interval=poll_interval,
            relaunch_builder_fn=self._relaunch_builder,
            run_once_fn=self.run_once,
        )

    def sync_controller(self, *_args, **_kwargs) -> bool:
        """Compatibility shim for the review bridge.

        Canonical state is already persisted by bridge and supervisor events.
        This keeps the bridge flow stable without the old controller entrypoint.
        """
        return True

    def _bootstrap_watchdog_manager_if_needed(
        self, state: SupervisorState, ticket_id: str
    ) -> None:
        """Relaunch the manager review bridge if ticket is READY_FOR_REVIEW and bridge is stale.

        Before: ticket_id is READY_FOR_REVIEW in the bus; bridge heartbeat may be absent/old.
        During: Finds the latest STATE_CHANGED → READY_FOR_REVIEW sequence, compares against
                last_manager_stale_trigger_sequence watermark, verifies bridge staleness, emits
                MANAGER_STALE, and spawns manager_review_bridge.py --watch as a detached process.
        After: If relaunched, last_manager_stale_trigger_sequence is updated so subsequent
               reconcile() calls do not double-fire the watchdog for the same RFR event.
        """
        import subprocess

        latest_rfr_seq = 0
        for event in self.event_bus.read_events(ticket_id=ticket_id):
            if (
                event.event_type == "STATE_CHANGED"
                and str((event.payload or {}).get("to_state", "")) == "READY_FOR_REVIEW"
                and event.sequence_number > latest_rfr_seq
            ):
                latest_rfr_seq = event.sequence_number

        if not (
            latest_rfr_seq > 0
            and latest_rfr_seq > state.last_manager_stale_trigger_sequence
        ):
            return

        if self._current_state(ticket_id) != TicketState.READY_FOR_REVIEW:
            return

        if not self._is_manager_bridge_stale():
            return

        self.event_bus.emit(
            "MANAGER_STALE",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "trigger_sequence": latest_rfr_seq,
                "reason": "bridge_heartbeat_stale",
            },
        )
        print(
            f"[supervisor] watchdog: bridge stale for {ticket_id} "
            f"(rfr_seq={latest_rfr_seq}). Relaunching manager_review_bridge.",
            flush=True,
        )
        cmd = [
            sys.executable,
            str(self.project_root / "scripts" / "manager_review_bridge.py"),
            "--watch",
            "--project-root",
            str(self.project_root),
        ]
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(cmd, **kwargs)  # noqa: S603
            state = self.load_state()
            state.last_manager_stale_trigger_sequence = latest_rfr_seq
            self.save_state(state)
        except Exception as exc:
            print(
                f"[supervisor] watchdog: failed to relaunch bridge: {exc}",
                file=sys.stderr,
            )

    def _bootstrap_clear_terminal_ticket(
        self, state: SupervisorState, ticket_id: str
    ) -> None:
        """Clear active_ticket if execution_log and bus confirm terminal state.

        When clearing a terminal ticket, also removes any requeue claim
        files for that ticket (WT-2026-199, Fase 3).
        """
        if self._execution_log_status(ticket_id) != "COMPLETED":
            return
        current_state = self._current_state(ticket_id)
        if self._is_state_terminal(current_state):
            # WT-2026-199: Clean up any stale requeue claims for this ticket
            self._cleanup_terminal_requeue_claims(ticket_id)
            state.active_ticket = None
            state.last_action = "BOOTSTRAP_COMPLETED"
            self.save_state(state)

    def _has_reconciled_event(
        self, previous_ticket: str, recovered_ticket: str
    ) -> bool:
        """Check if SUPERVISOR_RECONCILED was already emitted for this exact pair.

        Before: bootstrap() emitted SUPERVISOR_RECONCILED on every call when state was stale.
        During: Reads existing SUPERVISOR_RECONCILED events for recovered_ticket from bus.
        After: Returns True if a matching event exists; caller must skip re-emission.
        """
        existing = self.event_bus.read_events(
            ticket_id=recovered_ticket, event_type="SUPERVISOR_RECONCILED"
        )
        return any(
            (e.payload or {}).get("previous_ticket") == previous_ticket
            and (e.payload or {}).get("recovered_ticket") == recovered_ticket
            for e in existing
        )

    def reconcile_state(self) -> None:
        """Reconcile supervisor state from canonical sources without acquiring the lock.

        Before: State may be stale, empty, or diverge from bus/TURN.md/work_plan.md.
        During: Bus-first precedence. Recovers active ticket from bus → TURN.md →
                work_plan.md → persisted state. Reconciles loop_current_round and
                last_processed_sequence. Clears terminal tickets confirmed by bus.
                Does NOT acquire the instance lock — safe to call from non-supervisor
                processes (e.g. manager_review_bridge) that must not own the lock.
        After: Supervisor state file synchronized with bus-authoritative source.
        """
        state = self.load_state()

        # BUS-FIRST: Check if there's an active non-terminal ticket in the bus
        # (zombie READY_TO_CLOSE tickets are already excluded by _bus_active_non_terminal_ticket)
        bus_active = self._bus_active_non_terminal_ticket()

        # Defense-in-depth (WT-2026-194): if bus_active is still a READY_TO_CLOSE zombie
        # that slipped through, and work_plan.md has a newer ticket, prefer work_plan.
        if bus_active:
            wp_ticket = self._work_plan_active_ticket()
            if (
                wp_ticket
                and wp_ticket != bus_active
                and self._ticket_sort_key(wp_ticket) > self._ticket_sort_key(bus_active)
            ):
                print(
                    f"[supervisor] zombie guard: {bus_active} superseded by {wp_ticket} in work_plan; ignoring bus zombie",
                    file=sys.stderr,
                    flush=True,
                )
                bus_active = None

        # Fallback chain: bus (non-terminal) -> TURN.md -> work_plan.md -> state
        if bus_active:
            target_ticket = bus_active
        else:
            recovered = self.recover_active_ticket()
            active_from_plan = self._work_plan_active_ticket()
            target_ticket = recovered or active_from_plan or state.active_ticket

        # Reconcile active_ticket
        if target_ticket and state.active_ticket != target_ticket:
            previous_ticket = state.active_ticket
            state.active_ticket = target_ticket
            state.last_action = "RECOVERED" if previous_ticket is None else "RECONCILED"
            self.save_state(state)
            if previous_ticket is not None and not self._has_reconciled_event(
                previous_ticket, target_ticket
            ):
                self.event_bus.emit(
                    "SUPERVISOR_RECONCILED",
                    ticket_id=target_ticket,
                    actor="SUPERVISOR",
                    payload={
                        "previous_ticket": previous_ticket,
                        "recovered_ticket": target_ticket,
                        "source": "bootstrap",
                    },
                )

        # Reconcile loop_current_round from bus events
        if target_ticket:
            self._bootstrap_reconcile_loop_round(state, target_ticket)

        # Reconcile last_processed_sequence with bus reality
        self._bootstrap_reconcile_sequence(state)

        # Requeue Builder if a CHANGES trigger was consumed by sequence reconciliation
        ticket_id = state.active_ticket or target_ticket
        if ticket_id:
            self._bootstrap_requeue_if_needed(state, ticket_id)

        # Watchdog: relaunch manager review bridge if ticket is stale in READY_FOR_REVIEW
        ticket_id = state.active_ticket or target_ticket
        if ticket_id:
            self._bootstrap_watchdog_manager_if_needed(state, ticket_id)

        # Clear active_ticket if execution_log and bus confirm terminal state
        ticket_id = state.active_ticket or target_ticket
        if ticket_id:
            self._bootstrap_clear_terminal_ticket(state, ticket_id)

    def bootstrap(self) -> bool:
        """Acquire instance lock then reconcile supervisor state.

        Before: Relies on TURN.md (primary) and work_plan.md (fallback) for ticket recovery.
        During: Acquires instance lock atomically to prevent duplicate supervisors, then
                delegates full state reconciliation to reconcile_state().
        After: Supervisor state synchronized with bus-first precedence.
               Returns True if bootstrap succeeded, False if lock rejected (duplicate instance).
        """
        if not self._acquire_supervisor_lock():
            print(
                "[supervisor] bootstrap rejected: another supervisor instance is active",
                file=sys.stderr,
                flush=True,
            )
            return False
        self.reconcile_state()
        return True

    def _process_new_events(self) -> bool:
        """Process new events and reconcile last_processed_sequence with bus.

        Before: Only advanced last_processed_sequence, never decreased.
        During: Compares persisted sequence with bus reality; reconciles down
                if bus shows the persisted value is stale/phantom.
        After: last_processed_sequence matches bus reality after recovery.
        """
        state = self.load_state()
        events = self.event_bus.read_events()
        if not events:
            return False
        latest = events[-1]
        # Reconcile: if bus latest is behind persisted sequence, bus wins
        # (persisted sequence was phantom/ahead after crash/interrupt)
        if latest.sequence_number < state.last_processed_sequence:
            state.last_processed_sequence = latest.sequence_number
            self.save_state(state)
            return True
        # Normal case: advance if new events exist
        if latest.sequence_number > state.last_processed_sequence:
            state.last_processed_sequence = latest.sequence_number
            self.save_state(state)
            return True
        return False
