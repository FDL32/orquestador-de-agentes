from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bus.redact import redact_payload
from bus.state_machine import TicketState


@dataclass(slots=True)
class EventRecord:
    event_id: str
    event_type: str
    ticket_id: str
    actor: str
    timestamp: str
    payload: dict
    schema_version: str = "1.0"
    sequence_number: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> EventRecord:
        return cls(
            event_id=str(data.get("event_id", "")),
            event_type=str(data.get("event_type", "")),
            ticket_id=str(data.get("ticket_id", "")),
            actor=str(data.get("actor", "")),
            timestamp=str(data.get("timestamp", "")),
            payload=dict(data.get("payload") or {}),
            schema_version=str(data.get("schema_version", "1.0")),
            sequence_number=int(data.get("sequence_number", 0)),
        )


class EventBus:
    # Default maximum consecutive duplicate events allowed
    MAX_CONSECUTIVE_DUPLICATES = 3

    # De-duplication window size for counting recent duplicates
    DUPLICATE_WINDOW_SIZE = 20

    # Maximum duplicates allowed in window before blocking
    MAX_DUPLICATES_IN_WINDOW = 3

    # Maximum number of duplicate block warnings to print to stderr per session
    STDERR_BLOCK_LIMIT = 5

    def __init__(
        self,
        runtime_dir: Path,
        max_consecutive_duplicates: int | None = None,
        window_size: int | None = None,
        max_duplicates: int | None = None,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.runtime_dir / "events.jsonl"
        self.schema_path = self.runtime_dir / "events.schema.json"
        # max_duplicates and max_consecutive_duplicates are aliases for the same
        # threshold (count of identical events in the recent window). max_duplicates
        # wins if both are passed; legacy parameter kept for backward compatibility.
        if max_duplicates is not None:
            threshold = max_duplicates
        elif max_consecutive_duplicates is not None:
            threshold = max_consecutive_duplicates
        else:
            threshold = self.MAX_DUPLICATES_IN_WINDOW
        self.max_duplicates = threshold
        self.max_consecutive_duplicates = threshold  # legacy alias
        self.window_size = (
            window_size if window_size is not None else self.DUPLICATE_WINDOW_SIZE
        )
        # Session counter for rate-limiting stderr output
        self._session_block_count = 0

    def _read_raw_events(self) -> list[EventRecord]:
        if not self.events_path.exists():
            return []
        records: list[EventRecord] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(EventRecord.from_dict(json.loads(line)))
            except json.JSONDecodeError:
                continue
        return records

    def _serialize_payload(self, payload: dict | None) -> str:
        """Serialize payload for comparison."""
        return json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)

    def _count_recent_duplicates(
        self,
        records: list[EventRecord],
        event_type: str,
        ticket_id: str,
        actor: str,
        payload: dict | None,
    ) -> int:
        """
        Count identical events in the last 'window_size' records.
        This detects both consecutive and interleaved duplicates.
        """
        if not records:
            return 0
        serialized_payload = self._serialize_payload(payload)
        count = 0
        # Only check the last window_size records to keep it fast and localized
        recent_records = records[-self.window_size :]
        for record in reversed(recent_records):
            if (
                record.event_type == event_type
                and record.ticket_id == ticket_id
                and record.actor == actor
                and self._serialize_payload(record.payload) == serialized_payload
            ):
                count += 1
        return count

    def emit(
        self,
        event_type: str,
        *,
        ticket_id: str,
        actor: str,
        payload: dict | None = None,
        allow_reentry: bool = False,
        event_id: str | None = None,
        timestamp: str | None = None,
    ) -> EventRecord | None:
        """
        Emit an event to the bus with anti-duplicate protection.

        Returns None if the event would exceed the maximum consecutive duplicates
        threshold (same event_type, ticket_id, actor, and payload).

        Returns None if the event attempts to reopen a ticket from an approved/terminal
        state (READY_TO_CLOSE, COMPLETED) to a work state, unless allow_reentry=True
        is passed explicitly by a human-controlled recovery path.
        """
        records = self._read_raw_events()

        # Redact before dedupe so the comparison key matches what is persisted
        # (stored payloads are redacted; raw incoming payload with a secret would
        # otherwise never match the stored redacted history, defeating dedupe).
        redacted_payload = redact_payload(payload or {})

        # WP-2026-116: Ready-to-close reentry guard.
        # Block any event whose RESULTING state would reopen a ticket from an
        # approved/terminal state into a work state. The guard reasons about the
        # derived target state, not the event_type: both a direct STATE_CHANGED
        # and an indirect REVIEW_DECISION (decision=changes -> IN_PROGRESS, etc.)
        # can reopen a ticket, so both routes must be checked.
        reentry_target = self._reentry_target_state(event_type, payload)
        if (
            not allow_reentry
            and reentry_target
            and self._is_reentry_blocked(ticket_id, reentry_target)
        ):
            self._record_blocked_reentry(ticket_id, reentry_target.value)
            return None

        dup_count = self._count_recent_duplicates(
            records, event_type, ticket_id, actor, redacted_payload
        )
        if dup_count >= self.max_duplicates:
            self._record_blocked_emit(event_type, ticket_id, actor, dup_count)
            return None

        record = EventRecord(
            event_id=event_id or str(uuid4()),
            event_type=event_type,
            ticket_id=ticket_id,
            actor=actor,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            payload=redacted_payload,
            sequence_number=(records[-1].sequence_number if records else 0) + 1,
        )

        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    @property
    def _block_log_path(self) -> Path:
        """Path to the duplicate block log file."""
        return self.runtime_dir / "logs" / "event_bus_blocks.jsonl"

    @property
    def _reentry_log_path(self) -> Path:
        """Path to the reentry block log file."""
        return self.runtime_dir / "logs" / "event_bus_reentry_blocks.jsonl"

    def _get_current_state(self, ticket_id: str) -> TicketState | None:
        """Get the current state of a ticket from event history.

        Returns None if no state events found for the ticket.
        """
        ticket_events = [e for e in self._read_raw_events() if e.ticket_id == ticket_id]
        if not ticket_events:
            return None

        # Derive state from the last relevant event
        for event in reversed(ticket_events):
            if event.event_type == "STATE_CHANGED":
                return self._state_from_state_changed(event.payload)
            if event.event_type == "CLOSE_CONFIRMED":
                return TicketState.COMPLETED
            if event.event_type == "REVIEW_DECISION":
                return self._state_from_review_decision(event.payload)
            if event.event_type == "APPROVAL_RESOLVED":
                return self._state_from_approval_resolved(event.payload)
        return None

    @staticmethod
    def _state_from_state_changed(payload: dict | None) -> TicketState | None:
        state_str = str((payload or {}).get("to_state", "")).upper()
        return TicketState.__members__.get(state_str)

    @staticmethod
    def _state_from_review_decision(payload: dict | None) -> TicketState | None:
        decision = str((payload or {}).get("decision", "")).lower()
        return {
            "changes": TicketState.IN_PROGRESS,
            "approve": TicketState.READY_TO_CLOSE,
            "inspect": TicketState.HUMAN_GATE,
        }.get(decision)

    @staticmethod
    def _state_from_approval_resolved(payload: dict | None) -> TicketState | None:
        status = str((payload or {}).get("status", "")).lower()
        return {
            "expired": TicketState.BLOCKED,
            "approved": TicketState.READY_FOR_REVIEW,
            "rejected": TicketState.BLOCKED,
            "cancelled": TicketState.BLOCKED,
        }.get(status)

    @staticmethod
    def _reentry_target_state(
        event_type: str, payload: dict | None
    ) -> TicketState | None:
        """Derive the ticket state an event would produce, for reentry checking.

        Returns the target TicketState for events that can change a ticket's
        state, or None for events that cannot. Mirrors StateMachine's derivation
        rules so the guard covers every route into a work state:
        - STATE_CHANGED -> payload.to_state
        - REVIEW_DECISION -> changes->IN_PROGRESS, approve->READY_TO_CLOSE,
          inspect->HUMAN_GATE

        WP-2026-116 follow-up: the original guard only inspected STATE_CHANGED,
        leaving REVIEW_DECISION as an unguarded reentry route.
        """
        if not payload:
            return None
        if event_type == "STATE_CHANGED":
            return EventBus._state_from_state_changed(payload)
        if event_type == "REVIEW_DECISION":
            return EventBus._state_from_review_decision(payload)
        if event_type == "APPROVAL_RESOLVED":
            return EventBus._state_from_approval_resolved(payload)
        return None

    def _is_reentry_blocked(self, ticket_id: str, to_state: TicketState) -> bool:
        """Check if a transition should be blocked as illegal reentry.

        Blocks transitions from approved/terminal states (READY_TO_CLOSE, COMPLETED)
        to work states (IN_PROGRESS, READY_FOR_REVIEW, BLOCKED, HUMAN_GATE).

        Returns True if the transition should be blocked, False otherwise.
        """
        # Only block if current state is approved/terminal AND target is work state
        current_state = self._get_current_state(ticket_id)
        if current_state is None:
            return False

        return TicketState.is_approved_or_terminal(
            current_state
        ) and TicketState.is_work_state(to_state)

    def _record_blocked_reentry(
        self,
        ticket_id: str,
        to_state: str,
    ) -> None:
        """
        Record a blocked reentry attempt for observability.

        Writes a structured JSONL entry to _reentry_log_path and prints to stderr.
        """
        # Ensure log directory exists
        log_path = self._reentry_log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Write forensic log entry
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticket_id": ticket_id,
            "attempted_to_state": to_state,
            "reason": "Reentry from approved/terminal state blocked",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Console output (stderr)
        print(
            f"[event_bus] BLOCKED reentry attempt: ticket={ticket_id}, "
            f"to_state={to_state} (cannot reopen approved/terminal ticket)",
            file=sys.stderr,
        )

    def _record_blocked_emit(
        self,
        event_type: str,
        ticket_id: str,
        actor: str,
        dup_count: int,
    ) -> None:
        """
        Record a blocked duplicate emit for observability.

        - Increments session block counter.
        - Writes a structured JSONL entry to _block_log_path.
        - Prints to stderr if under STDERR_BLOCK_LIMIT.
        - Prints suppression warning when limit is exceeded.
        """
        # Increment session counter
        self._session_block_count += 1

        # Ensure log directory exists
        log_path = self._block_log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Write forensic log entry
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "ticket_id": ticket_id,
            "actor": actor,
            "duplicate_count": dup_count,
            "window_size": self.window_size,
            "threshold": self.max_duplicates,
            "session_block_number": self._session_block_count,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Console output (stderr) with rate limiting
        if self._session_block_count <= self.STDERR_BLOCK_LIMIT:
            print(
                f"[event_bus] BLOCKED duplicate event: type={event_type}, "
                f"ticket={ticket_id}, actor={actor}, dup_count={dup_count} "
                f"(window={self.window_size}, threshold={self.max_duplicates})",
                file=sys.stderr,
            )
        elif self._session_block_count == self.STDERR_BLOCK_LIMIT + 1:
            print(
                f"[event_bus] Further duplicate blocks suppressed for this session. "
                f"See {log_path} for full log.",
                file=sys.stderr,
            )

    def read_events(
        self,
        *,
        ticket_id: str | None = None,
        event_type: str | None = None,
    ) -> list[EventRecord]:
        records = self._read_raw_events()
        if ticket_id is not None:
            records = [record for record in records if record.ticket_id == ticket_id]
        if event_type is not None:
            records = [record for record in records if record.event_type == event_type]
        return records

    def latest_event(
        self,
        *,
        ticket_id: str | None = None,
        event_type: str | None = None,
    ) -> EventRecord | None:
        events = self.read_events(ticket_id=ticket_id, event_type=event_type)
        return events[-1] if events else None

    def archive_ticket_events(self, ticket_id: str) -> dict:
        """
        Archive all events for a closed ticket to historical storage.

        Moves events belonging to ticket_id from the active bus to
        .agent/runtime/events/archive/events.<ticket_id>.jsonl

        Uses atomic write (os.replace) to prevent corruption.

        Returns dict with:
            - archived_count: number of events moved
            - archive_path: path to archive file
            - kept_count: number of events remaining in active bus
        """
        import os
        import tempfile

        # Ensure archive directory exists
        archive_dir = self.runtime_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Read all events
        all_records = self._read_raw_events()

        # Separate events by ticket_id
        ticket_events = [r for r in all_records if r.ticket_id == ticket_id]
        remaining_events = [r for r in all_records if r.ticket_id != ticket_id]

        if not ticket_events:
            return {
                "archived_count": 0,
                "archive_path": None,
                "kept_count": len(remaining_events),
                "message": f"No events found for ticket {ticket_id}",
            }

        # Write archive file
        archive_path = archive_dir / f"events.{ticket_id}.jsonl"
        with archive_path.open("w", encoding="utf-8") as f:
            for record in ticket_events:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

        # Write remaining events atomically via temp file
        fd, temp_path = tempfile.mkstemp(
            dir=str(self.runtime_dir),
            prefix="events_",
            suffix=".jsonl.tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for record in remaining_events:
                    f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            # Atomic replace
            os.replace(temp_path, str(self.events_path))
        except Exception:
            # Clean up temp file on failure
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise

        return {
            "archived_count": len(ticket_events),
            "archive_path": str(archive_path),
            "kept_count": len(remaining_events),
            "message": f"Archived {len(ticket_events)} events for {ticket_id}",
        }
