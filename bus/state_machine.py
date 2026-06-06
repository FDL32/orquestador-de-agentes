from __future__ import annotations

from enum import Enum


class TicketState(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    HUMAN_GATE = "HUMAN_GATE"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
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

        Work states: IN_PROGRESS, READY_FOR_REVIEW, BLOCKED, HUMAN_GATE.
        These states represent active work or pending human action.
        """
        return state in {
            cls.IN_PROGRESS,
            cls.READY_FOR_REVIEW,
            cls.BLOCKED,
            cls.HUMAN_GATE,
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
        return TicketState.UNKNOWN
