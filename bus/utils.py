"""Shared pure helpers for the event bus layer.

These functions hold no state and do no I/O. They are the single source of
truth for logic that would otherwise be duplicated across the bridge and the
controller (e.g. counting review decisions).
"""

from __future__ import annotations

from typing import Any


def _event_field(event: Any, name: str) -> Any:
    """Read a field from an EventRecord or a plain dict.

    Before: event is an EventRecord-like object or a dict.
    During: tries attribute access, then dict access.
    After: returns the field value, or None if absent. Never raises.
    """
    value = getattr(event, name, None)
    if value is None and isinstance(event, dict):
        value = event.get(name)
    return value


def count_trailing_changes(events: list[Any]) -> int:
    """Count the trailing run of REVIEW_DECISION->changes decisions.

    Before: events is an ordered list (oldest first) of EventRecord objects
        or dicts. It may be pre-filtered to REVIEW_DECISION events or not.
    During: iterates from the newest event backwards, counting consecutive
        ``changes`` decisions. Any other decision (approve, inspect) ends the
        run; a REVIEW_DECISION with no ``decision`` payload is skipped without
        breaking the run; non-REVIEW_DECISION events are ignored.
    After: returns the length of the trailing ``changes`` run (0 if none).
        Pure, never raises.

    A history of changes -> approve -> changes -> changes returns 2, not 4:
    the intermediate approve resets the run.
    """
    count = 0
    for event in reversed(events):
        if _event_field(event, "event_type") != "REVIEW_DECISION":
            continue
        payload = _event_field(event, "payload") or {}
        decision = str(payload.get("decision", "")).lower()
        if decision == "changes":
            count += 1
        elif decision:
            # A non-empty, non-changes decision (approve/inspect) ends the run.
            break
        # decision == "" -> malformed payload, skip without breaking the run.
    return count
