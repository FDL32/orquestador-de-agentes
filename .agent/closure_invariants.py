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


def bus_has_ticket_events(event_bus, plan_id: str) -> bool:
    """True if the runtime bus holds any event for this ticket.

    WOT-2026-003a: Distinguishes two levels the validator must not conflate:
    versioned destination state (work_plan/STATE/execution_log) vs runtime
    evidence (the gitignored event bus). When the bus has NO event for the
    ticket, the runtime bus is absent from this context -- e.g. a fresh
    checkout / CI run where ``.agent/runtime/events/events.jsonl`` is not
    present. In that case bus-dependent invariants are *unverifiable* and must
    be reported as warnings, not asserted as violations. When the bus DOES
    hold events for the ticket but the required one is missing, that is a real
    violation (error).

    Before: ``event_bus`` is a live bus; ``plan_id`` is non-empty.
    During: Reads the ticket's events; never mutates.
    After: Returns True if at least one event exists for the ticket, else
    False (including when the bus read fails for any reason).
    """
    try:
        return bool(event_bus.read_events(ticket_id=plan_id))
    except Exception:
        return False


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
    """Check pre-closure invariants (IN_PROGRESS, APPROVED, PENDING)."""
    result: list[str] = []
    builder_exit = event_bus.latest_event(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if builder_exit:
        result.append(
            "BUILDER_EXIT exists but ticket not in READY_FOR_REVIEW/COMPLETED"
        )
    return result


def check_post_closure_built_exit(
    event_bus, plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check BUILDER_EXIT invariant. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    builder_exit = event_bus.latest_event(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if not builder_exit:
        if bus_has_ticket_events(event_bus, plan_id):
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
    """Check STATE_CHANGED invariant. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    state_event = event_bus.latest_event(ticket_id=plan_id, event_type="STATE_CHANGED")
    if not state_event:
        if bus_has_ticket_events(event_bus, plan_id):
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
    builder_exits = event_bus.read_events(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if not builder_exits:
        # No BUILDER_EXIT yet - invariant doesn't apply
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
