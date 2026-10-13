"""Closure invariants: bus/markdown consistency checks for ticket lifecycle.

Extracted from agent_controller.py (monolith decomposition). This module
owns the pre/post-closure invariant checks that --validate runs against
the event bus:

- Bus vs markdown state drift.
- BUILDER_EXIT presence, required fields and ordering relative to
  STATE_CHANGED READY_FOR_REVIEW.
- Circuit breaker and builder lock consistency at closure states.

All functions are pure given their inputs: the caller (agent_controller)
passes the event bus instance and pre-read breaker/lock dicts, so its
module globals (monkeypatched by tests) remain the single seam.
"""

from __future__ import annotations

from enum import Enum


class BusTicketEventState(Enum):
    """Tri-state verdict of ``bus_has_ticket_events`` (WOT-2026-067f).

    - ``WITH_EVENTS``: the read succeeded and the bus holds at least one
      event for the ticket.
    - ``WITHOUT_EVENTS``: the read succeeded and holds NO event for the
      ticket. Legitimate absence -- e.g. CI / fresh clone / other machine,
      where the gitignored ``events.jsonl`` never travels (WOT-2026-003a,
      WOT-2026-067e).
    - ``READ_FAILED``: the read itself raised (OSError, denied permission,
      corrupt store). Ticket visibility is UNKNOWN here, NOT proven absent.

    Truthiness is the consumer contract: only ``WITHOUT_EVENTS`` is falsy,
    so the legitimately-absent bus keeps degrading to a WARNING (the 003a/
    067e control negative), while ``READ_FAILED`` stays truthy so a broken
    read can never downgrade an observable violation to that WARNING
    (OBJ-002: an ERROR cannot degrade to a WARNING because of a broken read).
    """

    WITH_EVENTS = "with_events"
    WITHOUT_EVENTS = "without_events"
    READ_FAILED = "read_failed"

    def __bool__(self) -> bool:
        return self is not BusTicketEventState.WITHOUT_EVENTS


def bus_has_ticket_events(event_bus, plan_id: str) -> BusTicketEventState:
    """Tri-state verdict on whether the runtime bus holds this ticket's events.

    WOT-2026-003a: Distinguishes two levels the validator must not conflate:
    versioned destination state (work_plan/STATE/execution_log) vs runtime
    evidence (the gitignored event bus). When the bus has NO event for the
    ticket, the runtime bus is absent from this context -- e.g. a fresh
    checkout / CI run where ``.agent/runtime/events/events.jsonl`` is not
    present. In that case bus-dependent invariants are *unverifiable* and must
    be reported as warnings, not asserted as violations. When the bus DOES
    hold events for the ticket but the required one is missing, that is a real
    violation (error).

    WOT-2026-067f: the old ``try: bool(read_events) except: False`` collapsed
    a FAILED read into the same verdict as a legitimately absent bus, so a
    broken read silently downgraded the ERROR branch to the 067e WARNING.
    The three states are now never collapsed.

    Before: ``event_bus`` is a live bus; ``plan_id`` is non-empty.
    During: reads the ticket's events exactly once; never mutates; any
        exception raised by the read is contained here.
    After: returns ``WITH_EVENTS`` (>=1 event), ``WITHOUT_EVENTS`` (read ok,
        zero events for the ticket) or ``READ_FAILED`` (read raised). See
        ``BusTicketEventState`` for the truthiness contract consumed by
        ``check_post_closure_*`` and ``agent_controller``.
    """
    try:
        events = event_bus.read_events(ticket_id=plan_id)
    except Exception:
        return BusTicketEventState.READ_FAILED
    if events:
        return BusTicketEventState.WITH_EVENTS
    return BusTicketEventState.WITHOUT_EVENTS


def check_bus_drift(event_bus, plan_id: str, log_status: str) -> list[str]:
    """Check for drift between Markdown state and bus events.

    ``event_bus`` may be None (bus unavailable); the caller decides how to
    report that. ``plan_id`` must be already resolved and non-empty.
    """
    warnings: list[str] = []
    latest_state_event = event_bus.latest_event(
        ticket_id=plan_id, event_type="STATE_CHANGED"
    )
    if latest_state_event:
        bus_state = latest_state_event.payload.get(
            "to_state"
        ) or latest_state_event.payload.get("state")
        if bus_state != log_status:
            warnings.append(
                f"Drift detected: Markdown state='{log_status}' vs Bus state='{bus_state}' for ticket {plan_id}"
            )
    else:
        warnings.append(f"No STATE_CHANGED event found in bus for ticket {plan_id}")

    return warnings


def check_pre_closure_invariants(event_bus, plan_id: str) -> list[str]:
    """Check pre-closure invariants (IN_PROGRESS, APPROVED, PENDING).

    WOT-2026-089b: the bus is append-only, so a BUILDER_EXIT from a round
    already closed by a ``--request-changes`` requeue (a STATE_CHANGED moving
    the ticket back to IN_PROGRESS/HUMAN_GATE) stays on the bus forever. The
    previous existence-only check re-read it as fresh and produced a permanent
    warning after every requeue, until the next ``--mark-ready``.

    The exit now only warns when it has no later STATE_CHANGED closing its
    round, i.e. when ``builder_exit.sequence_number`` is greater than the
    latest STATE_CHANGED for the ticket. This mirrors the sequence_number
    comparison already used by ``check_builder_exit_order``; no to_state filter
    is applied (any later state change closes the round). Synthetic
    BUILDER_EXIT events from ``reconcile_ticket`` are excluded the same way
    ``_latest_real_builder_exit`` and ``check_builder_exit_order`` do it.
    """
    result: list[str] = []
    builder_exit = next(
        (
            event
            for event in reversed(
                event_bus.read_events(ticket_id=plan_id, event_type="BUILDER_EXIT")
            )
            if not _is_reconciled_event(event)
        ),
        None,
    )
    if builder_exit is None:
        return result
    state_event = event_bus.latest_event(ticket_id=plan_id, event_type="STATE_CHANGED")
    if state_event is None or (
        builder_exit.sequence_number > state_event.sequence_number
    ):
        result.append(
            "BUILDER_EXIT exists but ticket not in READY_FOR_REVIEW/COMPLETED"
        )
    return result


def _is_reconciled_event(event) -> bool:
    """True if the event was emitted by reconcile_ticket (synthetic, not a real closure)."""
    return event.payload.get("source") == "reconcile_ticket"


def _latest_real_builder_exit(event_bus, plan_id: str):
    """Return the latest BUILDER_EXIT that is NOT from reconcile_ticket, or None."""
    for event in reversed(
        event_bus.read_events(ticket_id=plan_id, event_type="BUILDER_EXIT")
    ):
        if not _is_reconciled_event(event):
            return event
    return None


def check_post_closure_built_exit(
    event_bus, plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check BUILDER_EXIT invariant. Returns (errors, warnings).

    WOT-2026-067f: the absent-vs-failed split is explicit. A legitimately
    absent bus (``WITHOUT_EVENTS``) keeps degrading to a warning (WOT-2026-
    003a/067e control negative); a FAILED read (``READ_FAILED``) is reported
    as an error, never as the "bus absent in this context" warning.
    """
    errors: list[str] = []
    warnings: list[str] = []
    builder_exit = _latest_real_builder_exit(event_bus, plan_id)
    if not builder_exit:
        state = bus_has_ticket_events(event_bus, plan_id)
        if state is BusTicketEventState.READ_FAILED:
            errors.append(
                f"INVARIANT: bus read FAILED while checking BUILDER_EXIT for "
                f"ticket {plan_id} in state {log_status}: events store "
                "unreadable, absence cannot be verified"
            )
        elif state is BusTicketEventState.WITH_EVENTS:
            errors.append(
                f"INVARIANT: Missing BUILDER_EXIT event for ticket {plan_id} in state {log_status}"
            )
        else:
            warnings.append(
                f"Cannot verify BUILDER_EXIT for ticket {plan_id} in state {log_status}: "
                "runtime bus has no events for this ticket (bus absent in this context)"
            )
    else:
        # ticket_id is at event level, exit_reason and completion_summary are in payload
        payload = builder_exit.payload
        if not builder_exit.ticket_id:
            errors.append(f"INVARIANT: BUILDER_EXIT missing ticket_id for {plan_id}")
        if not payload.get("exit_reason"):
            errors.append(
                f"INVARIANT: BUILDER_EXIT missing required field exit_reason for {plan_id}"
            )
        if not payload.get("completion_summary"):
            warnings.append(f"BUILDER_EXIT missing completion_summary for {plan_id}")
    return errors, warnings


def check_post_closure_breaker(breaker: dict, log_status: str) -> list[str]:
    """Check circuit breaker invariant against a pre-read breaker dict."""
    errors: list[str] = []
    if breaker.get("state") == "OPEN" and log_status == "READY_FOR_REVIEW":
        errors.append("INVARIANT: Circuit breaker OPEN but ticket in READY_FOR_REVIEW")
    return errors


def check_post_closure_lock(
    lock: dict | None, plan_id: str, log_status: str
) -> list[str]:
    """Check builder lock invariant against a pre-read lock dict."""
    warnings: list[str] = []
    if lock and lock.get("ticket_id") == plan_id and log_status == "COMPLETED":
        warnings.append(f"Builder lock still held for completed ticket {plan_id}")
    return warnings


def check_post_closure_state_changed(
    event_bus, plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check STATE_CHANGED invariant. Returns (errors, warnings).

    WOT-2026-067f: mirrors ``check_post_closure_built_exit`` -- absent bus
    degrades to a warning, failed read errors, and the two are never
    conflated.
    """
    errors: list[str] = []
    warnings: list[str] = []
    state_event = event_bus.latest_event(ticket_id=plan_id, event_type="STATE_CHANGED")
    if not state_event:
        state = bus_has_ticket_events(event_bus, plan_id)
        if state is BusTicketEventState.READ_FAILED:
            errors.append(
                f"INVARIANT: bus read FAILED while checking STATE_CHANGED for "
                f"ticket {plan_id}: events store unreadable, absence cannot "
                "be verified"
            )
        elif state is BusTicketEventState.WITH_EVENTS:
            errors.append(
                f"INVARIANT: Missing STATE_CHANGED event for ticket {plan_id}"
            )
        else:
            warnings.append(
                f"Cannot verify STATE_CHANGED for ticket {plan_id}: "
                "runtime bus has no events for this ticket (bus absent in this context)"
            )
    else:
        bus_state = state_event.payload.get("to_state")
        if bus_state and bus_state != log_status:
            warnings.append(
                f"STATE_CHANGED to_state='{bus_state}' differs from log_status='{log_status}'"
            )
    return errors, warnings


def check_builder_exit_order(event_bus, plan_id: str) -> list[str]:
    """Check that BUILDER_EXIT precedes each STATE_CHANGED READY_FOR_REVIEW.

    Returns warnings (not errors, to avoid invalidating historical tickets).
    Checks the COMPLETE sequence of events, not just the latest: for each
    STATE_CHANGED -> READY_FOR_REVIEW there must be a BUILDER_EXIT with a
    lower sequence number.
    """
    warnings: list[str] = []
    builder_exits = [
        e
        for e in event_bus.read_events(ticket_id=plan_id, event_type="BUILDER_EXIT")
        if not _is_reconciled_event(e)
    ]
    if not builder_exits:
        # No real BUILDER_EXIT yet (only reconciled or none) - invariant doesn't apply
        return warnings

    state_events = event_bus.read_events(ticket_id=plan_id, event_type="STATE_CHANGED")
    ready_for_review_events = [
        e for e in state_events if e.payload.get("to_state") == "READY_FOR_REVIEW"
    ]
    if not ready_for_review_events:
        # No STATE_CHANGED READY_FOR_REVIEW yet - invariant doesn't apply
        return warnings

    # Detect inversions at any point in the sequence, not just the latest.
    for ready_event in ready_for_review_events:
        has_prior_exit = any(
            exit_event.sequence_number < ready_event.sequence_number
            for exit_event in builder_exits
        )
        if not has_prior_exit:
            warnings.append(
                f"ORDER INVARIANT: STATE_CHANGED READY_FOR_REVIEW (seq={ready_event.sequence_number}) "
                f"has no prior BUILDER_EXIT for ticket {plan_id}. "
                f"BUILDER_EXIT should be emitted before STATE_CHANGED READY_FOR_REVIEW."
            )

    return warnings
