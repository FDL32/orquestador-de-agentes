"""Tests for bus integrity features: anti-duplicate emit and per-ticket archive."""

import json
from pathlib import Path

import pytest
from bus.event_bus import EventBus


class TestAntiDuplicateEmit:
    """Test anti-duplicate protection in EventBus.emit()."""

    def test_emit_allows_up_to_max_consecutive_duplicates(self, tmp_path: Path) -> None:
        """Events up to MAX_CONSECUTIVE_DUPLICATES are allowed."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events - all should succeed
        for i in range(3):
            result = bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )
            assert result is not None, f"Event {i + 1} should have been emitted"

        # Verify 3 events in bus
        events = bus.read_events()
        assert len(events) == 3

    def test_emit_blocks_fourth_consecutive_duplicate(self, tmp_path: Path) -> None:
        """Fourth consecutive duplicate is blocked."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # 4th identical event should be blocked
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "test"},
        )
        assert result is None, "4th consecutive duplicate should be blocked"

        # Verify still only 3 events
        events = bus.read_events()
        assert len(events) == 3

    def test_different_payload_resets_duplicate_counter(self, tmp_path: Path) -> None:
        """Different payload resets the duplicate counter."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Different payload should be allowed
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "different"},
        )
        assert result is not None, "Different payload should be allowed"

        # Now can emit 3 more with the new payload
        for _ in range(2):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "different"},
            )

        # 4th with new payload should be blocked
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "different"},
        )
        assert result is None

        events = bus.read_events()
        assert len(events) == 6  # 3 + 3

    def test_different_ticket_id_resets_duplicate_counter(self, tmp_path: Path) -> None:
        """Different ticket_id resets the duplicate counter."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events for ticket 1
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Same event for different ticket should be allowed
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-002",
            actor="BUILDER",
            payload={"message": "test"},
        )
        assert result is not None

    def test_different_event_type_resets_duplicate_counter(
        self, tmp_path: Path
    ) -> None:
        """Different event_type resets the duplicate counter."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Different event type should be allowed
        result = bus.emit(
            event_type="DIFFERENT_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "test"},
        )
        assert result is not None

    def test_different_actor_resets_duplicate_counter(self, tmp_path: Path) -> None:
        """Different actor resets the duplicate counter."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Different actor should be allowed
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="MANAGER",
            payload={"message": "test"},
        )
        assert result is not None

    def test_empty_bus_allows_any_event(self, tmp_path: Path) -> None:
        """Empty bus allows any event."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        result = bus.emit(
            event_type="FIRST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "first"},
        )
        assert result is not None
        assert result.sequence_number == 1

    def test_emit_blocks_interleaved_duplicates(self, tmp_path: Path) -> None:
        """Identical events are blocked even if interleaved with other events."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit A -> B -> A -> B -> A
        for _ in range(2):
            bus.emit(event_type="EVENT_A", ticket_id="WP-001", actor="B", payload={})
            bus.emit(event_type="EVENT_B", ticket_id="WP-001", actor="B", payload={})

        # At this point: A, B, A, B are in the bus.
        # Emit the 3rd A
        result = bus.emit(
            event_type="EVENT_A", ticket_id="WP-001", actor="B", payload={}
        )
        assert result is not None, "3rd A should be allowed (total in window: 3)"

        # At this point: A, B, A, B, A are in the bus.
        # Emit another B
        bus.emit(event_type="EVENT_B", ticket_id="WP-001", actor="B", payload={})

        # At this point: A, B, A, B, A, B are in the bus.
        # Now the 4th A should be blocked even though it's interleaved
        result = bus.emit(
            event_type="EVENT_A", ticket_id="WP-001", actor="B", payload={}
        )
        assert result is None, "4th interleaved A should be blocked"

        # Same for B
        result = bus.emit(
            event_type="EVENT_B", ticket_id="WP-001", actor="B", payload={}
        )
        assert result is None, "4th interleaved B should be blocked"

    def test_configurable_max_consecutive_duplicates(self, tmp_path: Path) -> None:
        """MAX_CONSECUTIVE_DUPLICATES is configurable."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=5)

        # Should allow 5 duplicates
        for i in range(5):
            result = bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )
            assert result is not None, f"Event {i + 1} should have been emitted"

        # 6th should be blocked
        result = bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "test"},
        )
        assert result is None


class TestArchiveTicketEvents:
    """Test per-ticket archive functionality."""

    def test_archive_moves_events_to_archive_file(self, tmp_path: Path) -> None:
        """Archive moves ticket events to archive file."""
        bus = EventBus(tmp_path)

        # Create some events for different tickets
        bus.emit(event_type="EVENT_A", ticket_id="WP-001", actor="BUILDER", payload={})
        bus.emit(event_type="EVENT_B", ticket_id="WP-001", actor="BUILDER", payload={})
        bus.emit(event_type="EVENT_C", ticket_id="WP-002", actor="BUILDER", payload={})
        bus.emit(event_type="EVENT_D", ticket_id="WP-001", actor="MANAGER", payload={})

        # Archive WP-001
        result = bus.archive_ticket_events("WP-001")

        assert result["archived_count"] == 3
        assert result["kept_count"] == 1
        assert result["archive_path"] is not None
        assert Path(result["archive_path"]).exists()

        # Verify archive contains WP-001 events
        archive_path = Path(result["archive_path"])
        archive_events = [
            json.loads(line)
            for line in archive_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert len(archive_events) == 3
        assert all(e["ticket_id"] == "WP-001" for e in archive_events)

        # Verify active bus only has WP-002 event
        remaining = bus.read_events()
        assert len(remaining) == 1
        assert remaining[0].ticket_id == "WP-002"

    def test_archive_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Archive creates archive directory if it doesn't exist."""
        bus = EventBus(tmp_path)

        bus.emit(event_type="EVENT", ticket_id="WP-001", actor="BUILDER", payload={})

        # Remove archive dir if it exists
        archive_dir = tmp_path / "archive"
        if archive_dir.exists():
            archive_dir.rmdir()

        result = bus.archive_ticket_events("WP-001")

        assert archive_dir.exists()
        assert result["archived_count"] == 1

    def test_archive_returns_zero_if_no_events_for_ticket(self, tmp_path: Path) -> None:
        """Archive returns zero if no events for ticket."""
        bus = EventBus(tmp_path)

        bus.emit(event_type="EVENT", ticket_id="WP-001", actor="BUILDER", payload={})

        result = bus.archive_ticket_events("WP-999")

        assert result["archived_count"] == 0
        assert result["archive_path"] is None
        assert "No events found" in result["message"]

    def test_archive_is_atomic_via_temp_file(self, tmp_path: Path) -> None:
        """Archive uses atomic replace for active bus."""
        bus = EventBus(tmp_path)

        # Create events
        bus.emit(event_type="EVENT_A", ticket_id="WP-001", actor="BUILDER", payload={})
        bus.emit(event_type="EVENT_B", ticket_id="WP-002", actor="BUILDER", payload={})

        # Archive should complete without error
        result = bus.archive_ticket_events("WP-001")

        assert result["archived_count"] == 1
        assert result["kept_count"] == 1

        # Verify bus file exists and is valid
        assert bus.events_path.exists()
        remaining = bus.read_events()
        assert len(remaining) == 1

    def test_archive_preserves_event_order(self, tmp_path: Path) -> None:
        """Archive preserves sequence order in archive file."""
        bus = EventBus(tmp_path)

        # Create events with known order
        bus.emit(
            event_type="EVENT_1",
            ticket_id="WP-001",
            actor="BUILDER",
            payload={"seq": 1},
        )
        bus.emit(event_type="EVENT_2", ticket_id="WP-002", actor="BUILDER", payload={})
        bus.emit(
            event_type="EVENT_3",
            ticket_id="WP-001",
            actor="BUILDER",
            payload={"seq": 3},
        )

        result = bus.archive_ticket_events("WP-001")

        # Read archive and verify order
        archive_path = Path(result["archive_path"])
        archive_events = [
            json.loads(line)
            for line in archive_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert len(archive_events) == 2
        assert archive_events[0]["payload"]["seq"] == 1
        assert archive_events[1]["payload"]["seq"] == 3
        assert (
            archive_events[0]["sequence_number"] < archive_events[1]["sequence_number"]
        )


class TestBlockedEmitObservability:
    """Test observability features for blocked duplicate emits."""

    def test_emit_logs_blocked_duplicates_to_file(self, tmp_path: Path) -> None:
        """Blocked duplicates are logged to event_bus_blocks.jsonl."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events (all allowed)
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # 4th duplicate should be blocked and logged
        bus.emit(
            event_type="TEST_EVENT",
            ticket_id="WP-TEST-001",
            actor="BUILDER",
            payload={"message": "test"},
        )

        # Verify log file was created
        log_path = tmp_path / "logs" / "event_bus_blocks.jsonl"
        assert log_path.exists(), "Block log file should be created"

        # Read and verify log entry
        log_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert len(log_entries) == 1, "Should have 1 blocked entry"
        entry = log_entries[0]
        assert entry["event_type"] == "TEST_EVENT"
        assert entry["ticket_id"] == "WP-TEST-001"
        assert entry["actor"] == "BUILDER"
        assert entry["duplicate_count"] == 3
        assert entry["window_size"] == 20
        assert entry["threshold"] == 3
        assert entry["session_block_number"] == 1
        assert "timestamp" in entry

    def test_emit_blocks_multiple_duplicates_all_logged(self, tmp_path: Path) -> None:
        """Multiple blocked duplicates are all logged to file."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Try to emit 5 more duplicates (all should be blocked)
        for _ in range(5):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Verify all 5 blocks are logged
        log_path = tmp_path / "logs" / "event_bus_blocks.jsonl"
        assert log_path.exists()

        log_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert len(log_entries) == 5, "Should have 5 blocked entries"

        # Verify session block numbers are sequential
        for i, entry in enumerate(log_entries, start=1):
            assert entry["session_block_number"] == i

    def test_stderr_rate_limiting(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Stderr output is rate-limited to STDERR_BLOCK_LIMIT messages."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # Emit 3 identical events
        for _ in range(3):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Emit 10 more duplicates (all blocked)
        for _ in range(10):
            bus.emit(
                event_type="TEST_EVENT",
                ticket_id="WP-TEST-001",
                actor="BUILDER",
                payload={"message": "test"},
            )

        # Capture stderr
        captured = capsys.readouterr()
        stderr_lines = captured.err.strip().split("\n")

        # Should have STDERR_BLOCK_LIMIT (5) individual warnings + 1 suppression warning
        # Total = 6 lines
        assert len(stderr_lines) == 6, (
            f"Expected 6 stderr lines, got {len(stderr_lines)}"
        )

        # First 5 should be individual block warnings
        for i in range(5):
            assert "BLOCKED duplicate event" in stderr_lines[i]

        # 6th should be suppression warning
        assert "suppressed" in stderr_lines[5].lower()
        assert "event_bus_blocks.jsonl" in stderr_lines[5]

    def test_block_log_uses_append_mode(self, tmp_path: Path) -> None:
        """Block log uses append mode to avoid overwriting."""
        bus = EventBus(tmp_path, max_consecutive_duplicates=3)

        # First batch: 3 events + 2 blocked
        for _ in range(3):
            bus.emit(event_type="EVENT_A", ticket_id="WP-001", actor="B", payload={})
        for _ in range(2):
            bus.emit(event_type="EVENT_A", ticket_id="WP-001", actor="B", payload={})

        # Second batch: 3 events + 2 blocked (different event type)
        for _ in range(3):
            bus.emit(event_type="EVENT_B", ticket_id="WP-001", actor="B", payload={})
        for _ in range(2):
            bus.emit(event_type="EVENT_B", ticket_id="WP-001", actor="B", payload={})

        # Log should have 4 entries (2 + 2)
        log_path = tmp_path / "logs" / "event_bus_blocks.jsonl"
        log_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert len(log_entries) == 4
        # Verify both event types are present
        event_types = [e["event_type"] for e in log_entries]
        assert event_types.count("EVENT_A") == 2
        assert event_types.count("EVENT_B") == 2
