"""Tests for event bus hygiene (WP-2026-109).

Covers the leading-blank-line tolerance of the events log: a stray CRLF/blank
prefix must not break reads, and emit() must keep appending without rewriting
history.
"""

import json
from pathlib import Path

from bus.event_bus import EventBus


def _events_path(runtime_dir: Path) -> Path:
    """Resolve the events.jsonl path the EventBus uses for a given runtime dir."""
    bus = EventBus(runtime_dir)
    return bus.events_path


def _write_raw(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def _make_event_line(ticket_id: str, seq: int) -> str:
    return (
        json.dumps(
            {
                "event_id": f"evt-{seq}",
                "event_type": "STATE_CHANGED",
                "ticket_id": ticket_id,
                "actor": "SUPERVISOR",
                "timestamp": "2026-05-20T00:00:00+00:00",
                "payload": {
                    "from_state": "IN_PROGRESS",
                    "to_state": "READY_FOR_REVIEW",
                },
                "schema_version": "1.0",
                "sequence_number": seq,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def test_read_events_tolerates_leading_blank_prefix(tmp_path: Path) -> None:
    """A stray CRLF/blank prefix before the first event must not break reads."""
    events_path = _events_path(tmp_path)
    _write_raw(
        events_path,
        ["\r\n", "\n", _make_event_line("WP-2026-001", 1)],
    )

    bus = EventBus(tmp_path)
    events = bus.read_events()

    assert len(events) == 1
    assert events[0].ticket_id == "WP-2026-001"
    assert events[0].sequence_number == 1


def test_emit_appends_without_rewriting_history(tmp_path: Path) -> None:
    """emit() must append; existing event lines stay byte-identical."""
    events_path = _events_path(tmp_path)
    first_line = _make_event_line("WP-2026-001", 1)
    _write_raw(events_path, [first_line])

    bus = EventBus(tmp_path)
    result = bus.emit(
        event_type="STATE_CHANGED",
        ticket_id="WP-2026-002",
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    assert result is not None
    raw = events_path.read_text(encoding="utf-8")
    # Original line preserved verbatim as the first line on disk.
    assert raw.startswith(first_line)
    # Exactly one new line appended.
    non_empty = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(non_empty) == 2


def test_emit_on_blank_prefixed_log_keeps_prior_events_readable(
    tmp_path: Path,
) -> None:
    """After emitting onto a blank-prefixed log, all events remain readable."""
    events_path = _events_path(tmp_path)
    _write_raw(
        events_path,
        ["\r\n", _make_event_line("WP-2026-001", 1)],
    )

    bus = EventBus(tmp_path)
    bus.emit(
        event_type="STATE_CHANGED",
        ticket_id="WP-2026-001",
        actor="SUPERVISOR",
        payload={"from_state": "READY_FOR_REVIEW", "to_state": "COMPLETED"},
    )

    events = EventBus(tmp_path).read_events()
    assert [e.ticket_id for e in events] == ["WP-2026-001", "WP-2026-001"]
    assert events[-1].payload.get("to_state") == "COMPLETED"
