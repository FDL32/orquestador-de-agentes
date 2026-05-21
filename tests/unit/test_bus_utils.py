"""Tests for bus.utils.count_trailing_changes (WP-2026-106).

The single source of truth for counting consecutive review rejections.
"""

from bus.event_bus import EventRecord
from bus.utils import count_trailing_changes


def _rec(seq: int, decision: str, event_type: str = "REVIEW_DECISION") -> EventRecord:
    """Build an EventRecord with a given decision."""
    return EventRecord(
        event_id=f"e{seq}",
        event_type=event_type,
        ticket_id="WP-1",
        actor="MANAGER",
        timestamp="2026-05-20T00:00:00+00:00",
        payload={"decision": decision} if decision else {},
        sequence_number=seq,
    )


def test_empty_list_returns_zero():
    assert count_trailing_changes([]) == 0


def test_all_changes_counts_all():
    events = [_rec(1, "changes"), _rec(2, "changes"), _rec(3, "changes")]
    assert count_trailing_changes(events) == 3


def test_approve_resets_the_run():
    """changes -> approve -> changes -> changes counts the trailing 2, not 4."""
    events = [
        _rec(1, "changes"),
        _rec(2, "approve"),
        _rec(3, "changes"),
        _rec(4, "changes"),
    ]
    assert count_trailing_changes(events) == 2


def test_trailing_approve_yields_zero():
    events = [_rec(1, "changes"), _rec(2, "changes"), _rec(3, "approve")]
    assert count_trailing_changes(events) == 0


def test_inspect_also_resets():
    events = [_rec(1, "changes"), _rec(2, "inspect"), _rec(3, "changes")]
    assert count_trailing_changes(events) == 1


def test_malformed_payload_does_not_break_run():
    """A REVIEW_DECISION with no decision is skipped, not a run-breaker."""
    events = [_rec(1, "changes"), _rec(2, ""), _rec(3, "changes")]
    assert count_trailing_changes(events) == 2


def test_non_review_events_are_ignored():
    events = [
        _rec(1, "changes"),
        _rec(2, "", event_type="MANAGER_REVIEWING"),
        _rec(3, "changes"),
    ]
    assert count_trailing_changes(events) == 2


def test_accepts_plain_dicts():
    """The helper tolerates dict events, not only EventRecord."""
    events = [
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "changes"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "approve"}},
        {"event_type": "REVIEW_DECISION", "payload": {"decision": "changes"}},
    ]
    assert count_trailing_changes(events) == 1
