from __future__ import annotations

from enum import Enum


class TicketState(str, Enum):
    """Estados validos de un ticket en el sistema multi-agente."""

    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    # WOT-2026-007f: CONTRACT_BLOCKED is set when a Builder emits a CONTRACT_GAP
    # event. The ticket is frozen until Contract Formation resolves the gap.
    # This state is reversible: once the contract is updated and re-frozen,
    # the ticket can be reopened (transitions back to IN_PROGRESS).
    CONTRACT_BLOCKED = "CONTRACT_BLOCKED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def is_approved_or_terminal(cls, state: TicketState) -> bool:
        """Check if a state is terminal (cannot be reopened).

        Only COMPLETED is irreversible: once a ticket is closed, no event may
        return it to a work state.

        READY_TO_CLOSE is deliberately NOT terminal — it means "approved,
        pending close". Before the final SUPERVISOR_CLOSED, a legitimate
        REVIEW_DECISION=changes can still revert it to work (see WP-2026-106
        escalation flow). Treating READY_TO_CLOSE as terminal would break that.
        """
        return state == cls.COMPLETED

    @classmethod
    def is_work_state(cls, state: TicketState) -> bool:
        """Check if a state is a work state (can transition to review).

        Work states: IN_PROGRESS, READY_FOR_REVIEW, BLOCKED, HUMAN_GATE,
        CONTRACT_BLOCKED, PAUSED.
        These states represent active work or pending human action.
        CONTRACT_BLOCKED and PAUSED are included because they are reversible:
        once the contract gap is resolved or the pause is resumed, the ticket
        transitions back to a work state.
        """
        return state in {
            cls.IN_PROGRESS,
            cls.READY_FOR_REVIEW,
            cls.BLOCKED,
            cls.HUMAN_GATE,
            cls.CONTRACT_BLOCKED,
            cls.PAUSED,
        }


class StateMachine:
    @staticmethod
    def _state_from_state_changed(payload: dict | None) -> TicketState:
        state = str((payload or {}).get("to_state", "")).upper()
        return TicketState.__members__.get(state, TicketState.UNKNOWN)

    @staticmethod
    def _state_from_review_decision(payload: dict | None) -> TicketState:
        decision = str((payload or {}).get("decision", "")).lower()
        return {
            "changes": TicketState.IN_PROGRESS,
            "approve": TicketState.READY_TO_CLOSE,
            "inspect": TicketState.HUMAN_GATE,
        }.get(decision, TicketState.UNKNOWN)

    @staticmethod
    def _state_from_approval_resolved(payload: dict | None) -> TicketState:
        status = str((payload or {}).get("status", "")).lower()
        return {
            "expired": TicketState.BLOCKED,
            "approved": TicketState.READY_FOR_REVIEW,
            "rejected": TicketState.BLOCKED,
            "cancelled": TicketState.BLOCKED,
        }.get(status, TicketState.UNKNOWN)

    @staticmethod
    def derive_state_from_events(events: list[dict]) -> TicketState:
        for event in reversed(events):
            event_type = event.get("event_type")
            payload = event.get("payload") or {}
            if event_type == "STATE_CHANGED":
                return StateMachine._state_from_state_changed(payload)
            if event_type in {"CLOSE_CONFIRMED", "SUPERVISOR_CLOSED"}:
                return TicketState.COMPLETED
            if event_type == "REVIEW_DECISION":
                return StateMachine._state_from_review_decision(payload)
            if event_type == "APPROVAL_RESOLVED":
                return StateMachine._state_from_approval_resolved(payload)
            # WOT-2026-007f: CONTRACT_GAP event transitions the ticket to
            # CONTRACT_BLOCKED, freezing it until Contract Formation resolves
            # the gap.  This is checked AFTER terminal/approved events so a
            # later resolution can override it.
            if event_type == "CONTRACT_GAP":
                return TicketState.CONTRACT_BLOCKED
        return TicketState.UNKNOWN


# Non-terminal states (used by supervisor, builder_locks, projector)
NON_TERMINAL_STATES: frozenset[TicketState] = frozenset(
    {
        TicketState.IN_PROGRESS,
        TicketState.READY_FOR_REVIEW,
        TicketState.BLOCKED,
        TicketState.HUMAN_GATE,
        TicketState.READY_TO_CLOSE,
        TicketState.CONTRACT_BLOCKED,
        TicketState.PAUSED,
    }
)
