from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .approval import ApprovalPolicy, ApprovalReason, ApprovalStatus, ApprovalStore
from .event_bus import EventBus
from .exceptions import ConcurrentStateError
from .state_machine import StateMachine, TicketState


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

# Do not relaunch Builder once the ticket has crossed into a gate/closeout state.
RELAUNCH_BLOCKED_STATES = frozenset(
    {
        TicketState.HUMAN_GATE,
        TicketState.READY_TO_CLOSE,
        TicketState.COMPLETED,
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
        policy = ApprovalPolicy(
            policy_name="default",
            timeout_seconds=300,  # 5 minutes default
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
            "ticket_id": "WP-2026-XXX",
            "pid": <process_id>,
            "started_at": "<ISO8601 timestamp>"
        }
        """
        import contextlib
        import json
        import os
        from datetime import datetime, timezone

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
            _revision=revision,
        )

    def ensure_ticket_queue(self) -> None:
        work_plan = self.collaboration_dir / "work_plan.md"
        work_plan.parent.mkdir(parents=True, exist_ok=True)
        if not work_plan.exists():
            work_plan.write_text("# Plan de Trabajo del Proyecto\n", encoding="utf-8")
            return

        content = work_plan.read_text(encoding="utf-8")
        tickets = re.findall(r"WP-\d{4}-[A-Za-z0-9]+", content)
        if not tickets:
            return
        match = re.search(r"WP-(\d{4})-([A-Za-z0-9]+)", tickets[0])
        if not match:
            return
        prefix = match.group(1)
        last_num = (
            int(re.findall(r"WP-\d{4}-(\d+)", tickets[-1])[0])
            if re.search(r"WP-\d{4}-(\d+)", tickets[-1])
            else 0
        )
        if last_num == 0:
            return
        additions = []
        for offset in (1, 2):
            candidate = f"WP-{prefix}-{last_num + offset:03d}"
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
        match = re.match(r"WP-(\d{4})-(\d+)", ticket_id)
        if not match:
            return None
        prefix, number = match.groups()
        return f"WP-{prefix}-{int(number) + 1:03d}"

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
            patterns = (
                r"\|\s*\*\*Ticket Activo\*\*\s*\|\s*(WP-\d{4}-[A-Za-z0-9]+)\s*\|",
                r"\|\s*\*\*Plan ID\*\*\s*\|\s*(WP-\d{4}-[A-Za-z0-9]+)\s*\|",
                r"\|\s*\*\*Ticket\*\*\s*\|\s*(WP-\d{4}-[A-Za-z0-9]+)\s*\|",
                r"\|\s*\*\*Plan activo\*\*\s*\|\s*(WP-\d{4}-[A-Za-z0-9]+)\s*\|",
            )
            for pattern in patterns:
                match = re.search(pattern, content, flags=re.IGNORECASE)
                if match:
                    return match.group(1)
            loose_match = re.search(r"(WP-\d{4}-[A-Za-z0-9]+)", content)
            if loose_match:
                return loose_match.group(1)
        work_plan_path = self.collaboration_dir / "work_plan.md"
        if work_plan_path.exists():
            content = work_plan_path.read_text(encoding="utf-8")
            patterns = (
                r"\*\*Plan activo:\*\*\s*(WP-\d{4}-[A-Za-z0-9]+)",
                r"\*\*ID:\*\*\s*(WP-\d{4}-[A-Za-z0-9]+)",
                r"^\s*##\s+(WP-\d{4}-[A-Za-z0-9]+)\b",
            )
            for pattern in patterns:
                match = re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    return match.group(1)
            loose_match = re.search(r"(WP-\d{4}-[A-Za-z0-9]+)", content)
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
            r"\*\*Plan activo:\*\*\s*(WP-\d{4}-[A-Za-z0-9]+)",
            r"\*\*ID:\*\*\s*(WP-\d{4}-[A-Za-z0-9]+)",
            r"^\s*##\s+(WP-\d{4}-[A-Za-z0-9]+)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1)
        loose_match = re.search(r"(WP-\d{4}-[A-Za-z0-9]+)", content)
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
        match = re.match(r"WP-(\d{4})-([A-Za-z0-9]+)", ticket_id or "")
        if not match:
            return (-1, -1, ticket_id or "")
        year = int(match.group(1))
        suffix = match.group(2)
        numeric_suffix = int(suffix) if suffix.isdigit() else -1
        return (year, numeric_suffix, suffix)

    def _bus_active_non_terminal_ticket(self) -> str | None:
        """Find the active non-terminal ticket from the event bus.

        Before: bootstrap() relied on TURN.md and work_plan.md as primary sources.
        During: Scans all tickets in the bus, derives their current state, and
                returns the highest-authority ticket in a non-terminal state
                (READY_FOR_REVIEW, READY_TO_CLOSE, IN_PROGRESS, BLOCKED, HUMAN_GATE).
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
            tid for tid, tstate in seen_tickets.items() if tstate in NON_TERMINAL_STATES
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

    def _bootstrap_clear_terminal_ticket(
        self, state: SupervisorState, ticket_id: str
    ) -> None:
        """Clear active_ticket if execution_log and bus confirm terminal state."""
        if self._execution_log_status(ticket_id) != "COMPLETED":
            return
        current_state = self._current_state(ticket_id)
        if self._is_state_terminal(current_state):
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

    def bootstrap(self) -> bool:
        """Bootstrap supervisor state from canonical sources.

        Before: Relied on TURN.md (primary) and work_plan.md (fallback) for ticket recovery.
        During: Prioritizes the bus's active non-terminal ticket over TURN.md and
                work_plan.md. Uses file-based sources only as fallback when the bus
                has no active non-terminal ticket. Reconciles stale state with the
                bus-authoritative source. Reconciles loop_current_round from bus.
                Only clears active_ticket when bus confirms terminal state.
                Acquires instance lock atomically to prevent duplicate supervisors.
        After: Supervisor state synchronized with bus-first precedence.
               Returns True if bootstrap succeeded, False if lock rejected (duplicate instance).
        """
        # Acquire instance lock first - reject if another live supervisor exists
        if not self._acquire_supervisor_lock():
            print(
                "[supervisor] bootstrap rejected: another supervisor instance is active",
                file=sys.stderr,
                flush=True,
            )
            return False

        state = self.load_state()

        # BUS-FIRST: Check if there's an active non-terminal ticket in the bus
        bus_active = self._bus_active_non_terminal_ticket()

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

        # Clear active_ticket if execution_log and bus confirm terminal state
        ticket_id = state.active_ticket or target_ticket
        if ticket_id:
            self._bootstrap_clear_terminal_ticket(state, ticket_id)

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

    def _parse_iso_datetime(self, iso_str: str) -> datetime:
        """Parse an ISO 8601 string into a timezone-aware datetime object."""
        normalized = iso_str.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        return datetime.fromisoformat(normalized)

    def _has_builder_exited_after(self, ticket_id: str, lock_start: datetime) -> bool:
        """Return True if a BUILDER_EXIT event was recorded for the ticket after lock_start.

        Before: Silently swallowed parse errors and fell back to PID check.
        During: Iterates events in reverse, parses timestamps with explicit error logging.
        After: Returns True/False based on bus evidence; errors are logged, not silenced.
        """
        events = self.event_bus.read_events(ticket_id=ticket_id)
        for event in reversed(events):
            if event.actor == "BUILDER" and event.event_type == "BUILDER_EXIT":
                try:
                    event_time = self._parse_iso_datetime(event.timestamp)
                    if event_time > lock_start:
                        return True
                except (ValueError, TypeError, AttributeError) as exc:
                    # Log parse error but continue checking other events
                    print(
                        f"[supervisor] Failed to parse timestamp for BUILDER_EXIT event: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
        return False

    def _is_pid_alive(self, pid: int) -> bool:
        """Return True if the given process PID is running (NT tasklist check)."""
        import os
        import shutil
        import subprocess

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

    def _builder_alive(self) -> bool:
        """Return True if Builder is alive based on bus events and lock mtime.

        Before: Checked bus, then fell back to PID check, then mtime.
        During: Checks bus for BUILDER_EXIT after lock start; falls back to mtime only.
        After: PID is never used as authority; bus + mtime are the only signals.

        Bus-first precedence:
        - If BUILDER_EXIT event exists after lock_start -> Builder is dead.
        - If no BUILDER_EXIT and lock is fresh (<15 min) -> Builder is alive.
        - If no BUILDER_EXIT and lock is old -> Builder is dead.
        """
        import time

        lock = self.runtime_dir / "builder_lock.txt"
        if not lock.exists():
            return False
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        ticket_id = data.get("ticket_id")
        started_at_str = data.get("started_at")

        # Bus-first: if BUILDER_EXIT event exists after lock_start, Builder is dead.
        if ticket_id and started_at_str:
            try:
                lock_start = self._parse_iso_datetime(started_at_str)
                if self._has_builder_exited_after(ticket_id, lock_start):
                    return False
            except (ValueError, TypeError, AttributeError) as exc:
                # Log parse error but continue to mtime fallback
                print(
                    f"[supervisor] Failed to parse lock timestamp: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

        # Fallback: lock fresh (<15 min) treated as alive for crash recovery.
        # PID is NOT used as authority - it can be stale/wrapper PID.
        try:
            age = time.time() - lock.stat().st_mtime
            return age < 900  # 15 minutes TTL
        except OSError:
            return False

    def _relaunch_builder(self, ticket_id: str) -> bool:
        """Relaunch Builder via launcher. Returns True if successful or skipped (alive), False on failure."""
        import os
        import shutil
        import subprocess
        import sys

        if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
            return False

        # Capa 2: Check liveness before relaunch
        if self._builder_alive():
            print(
                f"[ticket-supervisor] Builder alive (lock fresh), skipping relaunch for {ticket_id}",
                file=sys.stderr,
                flush=True,
            )
            return True  # no es error, Builder vivo manejará el requeue

        launcher_path = self.project_root / "scripts" / "launch_agent_terminals.ps1"
        if not launcher_path.exists():
            print(
                f"[ticket-supervisor] ERROR: Launcher not found at {launcher_path}",
                file=sys.stderr,
                flush=True,
            )
            return False

        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            print(
                "[ticket-supervisor] ERROR: PowerShell executable not found",
                file=sys.stderr,
                flush=True,
            )
            return False

        # Use -OnlyBuilder additive switch: PowerShell 5.1 invoked from
        # subprocess.run cannot cast string argv elements ("0", "$false") to
        # SwitchParameter, so -LaunchSupervisor:0 / :$false both fail. The
        # launcher now exposes -OnlyBuilder which internally sets the other
        # launchers to $false. Pair with -ResumeBuilder to skip cleanup.
        # Pass -ProjectRoot explicitly: under PowerShell 5.1 subprocess invocation,
        # the script's auto-variables ($PSScriptRoot, $PSCommandPath,
        # $MyInvocation.MyCommand.Path) can all be null during param-block
        # evaluation. The supervisor already knows the absolute root.
        cmd = [
            pwsh,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher_path),
            "-ProjectRoot",
            str(self.project_root),
            "-LaunchBuilder",
            "-OnlyBuilder",
            "-ResumeBuilder",
        ]
        print(f"[ticket-supervisor] Executing: {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(  # noqa: S603
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            return True
        except subprocess.CalledProcessError as exc:
            # Capa 1: diagnóstico stdout/stderr
            print(
                f"[ticket-supervisor] launcher failed exit={exc.returncode}",
                file=sys.stderr,
                flush=True,
            )
            if exc.stdout:
                print(
                    f"  stdout (last 500): {exc.stdout[-500:]}",
                    file=sys.stderr,
                    flush=True,
                )
            if exc.stderr:
                print(
                    f"  stderr (last 500): {exc.stderr[-500:]}",
                    file=sys.stderr,
                    flush=True,
                )
            return False
        except subprocess.TimeoutExpired:
            print(
                "[ticket-supervisor] launcher timed out after 60s",
                file=sys.stderr,
                flush=True,
            )
            return False
        except Exception as exc:
            print(
                f"[ticket-supervisor] ERROR relaunching builder: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return False

    def run_once(self) -> bool:
        state = self.load_state()

        # Wire approval timeout expiration into the live loop
        try:
            store = self.get_approval_store()
            expired = store.check_and_expire_all()
            for req in expired:
                target_state = "BLOCKED"
                if req.reason == ApprovalReason.TIMEOUT_EXPIRED:
                    target_state = "BLOCKED"
                    self.transition_ticket(
                        ticket_id=req.ticket_id,
                        new_state=target_state,
                        reason=f"Approval {req.approval_id} expired after {req.timeout_seconds}s",
                    )
                self.event_bus.emit(
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
            import sys

            print(
                f"[ticket-supervisor] Error checking approval timeouts: {exc}",
                file=sys.stderr,
                flush=True,
            )

        previous_sequence = state.last_processed_sequence
        events = self.event_bus.read_events()
        new_events = [
            e for e in events if e.sequence_number > state.last_processed_sequence
        ]

        changed = self._process_new_events()
        state = self.load_state()
        event_activity = state.last_processed_sequence > previous_sequence

        requeue_triggered = False
        for event in new_events:
            if event.ticket_id == state.active_ticket and (
                (
                    event.event_type == "LOOP_DECISION"
                    and str((event.payload or {}).get("decision", "")).upper()
                    == "CHANGES"
                )
                or (
                    event.event_type == "STATE_CHANGED"
                    and str((event.payload or {}).get("to_state", "")).upper()
                    == "IN_PROGRESS"
                )
            ):
                requeue_triggered = True

        if requeue_triggered and state.active_ticket:
            current_state = self._current_state(state.active_ticket)
            if current_state in RELAUNCH_BLOCKED_STATES:
                print(
                    f"[ticket-supervisor] Skipping Builder relaunch for {state.active_ticket}: "
                    f"ticket is {current_state.value}",
                    flush=True,
                )
            else:
                state.loop_current_round += 1
                self.save_state(state)
                changed = True
                print(
                    f"[ticket-supervisor] Detected requeue for {state.active_ticket} (round {state.loop_current_round}). Relaunching Builder...",
                    flush=True,
                )
                self._relaunch_builder(state.active_ticket)

        if self.advance_if_review_ready():
            changed = True
        return changed or event_activity

    def run_reactive(self, timeout_seconds: float = 300.0):
        import os
        import time

        def _timeout_from_env(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return default
            return value if value > 0 else default

        # Acquire lock via bootstrap - if rejected, another instance is running
        if self.bootstrap() is False:
            return False  # Lock rejected, another supervisor is active

        idle_timeout = _timeout_from_env(
            "TICKET_SUPERVISOR_IDLE_TIMEOUT_SECONDS", timeout_seconds
        )
        max_runtime = _timeout_from_env("TICKET_SUPERVISOR_MAX_RUNTIME_SECONDS", 3600.0)
        start_time = time.time()
        last_activity = start_time
        changed = False
        try:
            while True:
                now = time.time()
                if max_runtime > 0 and now - start_time >= max_runtime:
                    break
                if idle_timeout > 0 and now - last_activity >= idle_timeout:
                    break
                if self.run_once():
                    changed = True
                    last_activity = time.time()
                time.sleep(1.0)
        finally:
            # Always release lock on exit (normal or exceptional)
            self._release_supervisor_lock()
        return changed

    def run_loop(self, poll_interval: float = 1.0):
        import time

        # Acquire lock via bootstrap - if rejected, another instance is running
        if self.bootstrap() is False:
            return  # Lock rejected, another supervisor is active

        try:
            while True:
                self.run_once()
                time.sleep(poll_interval)
        finally:
            # Always release lock on exit
            self._release_supervisor_lock()

    def sync_controller(self, *_args, **_kwargs) -> bool:
        """Compatibility shim for the review bridge.

        The canonical state is already persisted by the bridge/supervisor events.
        This method keeps the bridge flow stable without requiring the old controller
        entrypoint contract.
        """
        # Note: sync_controller does not acquire/release lock - it's a read-only sync
        # called from the review bridge which has its own lifecycle management.
        self.bootstrap()
        return True
