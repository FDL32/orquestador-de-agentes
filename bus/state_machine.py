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
    # WOT-2026-013n: honest non-success terminal states.
    # SUPERSEDED - work rejected/redirected to child tickets, not pursued
    #   under this id (e.g. WT-2026-239a). NOT incomplete work to rescue.
    # BLOCKED_FINAL - documented CONTRACT_GAP whose cure belongs to a
    #   separate (product) ticket; cannot be completed as-is (e.g. 013c).
    # Both are irreversible terminals like COMPLETED but do NOT mean success
    #   and must never be reconciled to COMPLETED to silence views.
    SUPERSEDED = "SUPERSEDED"
    BLOCKED_FINAL = "BLOCKED_FINAL"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def is_approved_or_terminal(cls, state: TicketState) -> bool:
        """Check if a state is terminal (cannot be reopened).

        WOT-2026-013n: terminality is an explicit authority set with three
        irreversible members - COMPLETED (success), SUPERSEDED and BLOCKED_FINAL
        (honest non-success). Consumers MUST consult this authority rather than
        hardcode ``state == COMPLETED``.

        READY_TO_CLOSE is deliberately NOT terminal — it means "approved,
        pending close". Before the final SUPERVISOR_CLOSED, a legitimate
        REVIEW_DECISION=changes can still revert it to work (see WP-2026-106
        escalation flow). Treating READY_TO_CLOSE as terminal would break that.
        """
        return state in IRREVERSIBLE_TERMINAL_STATES

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


# WOT-2026-013n: shared terminality authority.
#
# IRREVERSIBLE_TERMINAL_STATES is the single source of truth for "this ticket is
# closed and cannot return to a work state". It holds the success terminal
# (COMPLETED) and the two honest non-success terminals (SUPERSEDED,
# BLOCKED_FINAL). Consumers (supervisor, builder_locks, closeout, reconcile,
# launcher, publication) MUST consult this set / the helpers below instead of
# hardcoding ``== COMPLETED`` or maintaining divergent local lists.
IRREVERSIBLE_TERMINAL_STATES: frozenset[TicketState] = frozenset(
    {
        TicketState.COMPLETED,
        TicketState.SUPERSEDED,
        TicketState.BLOCKED_FINAL,
    }
)

# Honest non-success terminals: closed, but NOT a success close. Tooling that
# wants to distinguish "done well" from "closed without completing" uses this.
NON_SUCCESS_TERMINAL_STATES: frozenset[TicketState] = frozenset(
    {
        TicketState.SUPERSEDED,
        TicketState.BLOCKED_FINAL,
    }
)

# Legacy literal absorbed (WOT-2026-013n): some historical events / scripts used
# the bare string "CLOSED" (never an enum member) as an alias for a terminal
# ticket. We recognise it as terminal for back-compat WITHOUT promoting it to a
# TicketState. New code must emit COMPLETED / SUPERSEDED / BLOCKED_FINAL.
_LEGACY_TERMINAL_LITERALS: frozenset[str] = frozenset({"CLOSED"})

# All known non-terminal states. Derived as the complement of the terminal
# authority over the set of states that represent an open/pending ticket, so it
# can never silently diverge from IRREVERSIBLE_TERMINAL_STATES.
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


def is_terminal_state(state: TicketState | str | None) -> bool:
    """Return True if ``state`` is an irreversible terminal (success or not).

    Accepts a TicketState, a state string (case-insensitive), or None. The bare
    legacy literal "CLOSED" is recognised as terminal for back-compat but is NOT
    a TicketState member. Unknown / non-terminal / None -> False.
    """
    if state is None:
        return False
    if isinstance(state, TicketState):
        return state in IRREVERSIBLE_TERMINAL_STATES
    text = str(state).strip().upper()
    if text in _LEGACY_TERMINAL_LITERALS:
        return True
    member = TicketState.__members__.get(text)
    return member in IRREVERSIBLE_TERMINAL_STATES if member is not None else False


def terminal_state_strings(*, include_legacy: bool = True) -> frozenset[str]:
    """Return terminal state values as strings, for string-based consumers.

    include_legacy adds the absorbed bare literal(s) (e.g. "CLOSED") so scripts
    that compare raw ``to_state`` strings stay back-compatible.
    """
    base = {s.value for s in IRREVERSIBLE_TERMINAL_STATES}
    if include_legacy:
        base |= set(_LEGACY_TERMINAL_LITERALS)
    return frozenset(base)
