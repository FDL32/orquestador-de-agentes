"""Tests for the deterministic state projection probe."""

import sys
from pathlib import Path


# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from scripts.state_projection_probe import (  # noqa: E402
    ProbeOutput,
    ProbeResult,
    _extract_ticket_id_from_work_plan,
    _filter_events_for_ticket,
    _parse_markdown_state,
    _read_events_jsonl,
    run_probe,
)


class TestReadEventsJsonl:
    """Test reading events from JSONL bus file."""

    def test_read_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        events_path = tmp_path / "events.jsonl"
        events_path.write_text("", encoding="utf-8")
        result = _read_events_jsonl(events_path)
        assert result == []

    def test_read_valid_events(self, tmp_path: Path) -> None:
        """Valid JSONL returns parsed events."""
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-001"}\n'
            '{"event_type": "REVIEW_DECISION", "ticket_id": "WP-2026-001"}\n',
            encoding="utf-8",
        )
        result = _read_events_jsonl(events_path)
        assert len(result) == 2
        assert result[0]["event_type"] == "STATE_CHANGED"
        assert result[1]["event_type"] == "REVIEW_DECISION"

    def test_skip_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed JSON lines are skipped silently."""
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            '{"event_type": "VALID"}\nnot valid json\n{"event_type": "ALSO_VALID"}\n',
            encoding="utf-8",
        )
        result = _read_events_jsonl(events_path)
        assert len(result) == 2
        assert result[0]["event_type"] == "VALID"
        assert result[1]["event_type"] == "ALSO_VALID"

    def test_file_not_exists(self, tmp_path: Path) -> None:
        """Non-existent file returns empty list."""
        events_path = tmp_path / "nonexistent.jsonl"
        result = _read_events_jsonl(events_path)
        assert result == []


class TestExtractTicketIdFromWorkPlan:
    """Test extracting ticket ID from work_plan.md."""

    def test_extract_valid_id(self, tmp_path: Path) -> None:
        """Valid work_plan.md returns ticket ID."""
        work_plan_path = tmp_path / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan - WP-2026-145\n\n"
            "## Metadata\n"
            "- **ID:** WP-2026-145\n"
            "- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        result = _extract_ticket_id_from_work_plan(work_plan_path)
        assert result == "WP-2026-145"

    def test_no_id_field(self, tmp_path: Path) -> None:
        """Missing ID field returns None."""
        work_plan_path = tmp_path / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\nNo ID here\n",
            encoding="utf-8",
        )
        result = _extract_ticket_id_from_work_plan(work_plan_path)
        assert result is None

    def test_file_not_exists(self, tmp_path: Path) -> None:
        """Non-existent file returns None."""
        work_plan_path = tmp_path / "nonexistent.md"
        result = _extract_ticket_id_from_work_plan(work_plan_path)
        assert result is None


class TestParseMarkdownState:
    """Test parsing state from STATE.md."""

    def test_parse_valid_state(self, tmp_path: Path) -> None:
        """Valid STATE.md returns state."""
        state_md_path = tmp_path / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\n"
            "Plan Activo: WP-2026-145\n"
            "Estado actual: IN_PROGRESS\n"
            "Rol activo: BUILDER\n",
            encoding="utf-8",
        )
        result = _parse_markdown_state(state_md_path, "WP-2026-145")
        assert result == "IN_PROGRESS"

    def test_no_estado_actual_line(self, tmp_path: Path) -> None:
        """Missing 'Estado actual:' line returns None."""
        state_md_path = tmp_path / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nPlan Activo: WP-2026-145\nSome other content\n",
            encoding="utf-8",
        )
        result = _parse_markdown_state(state_md_path, "WP-2026-145")
        assert result is None

    def test_file_not_exists(self, tmp_path: Path) -> None:
        """Non-existent file returns None."""
        state_md_path = tmp_path / "nonexistent.md"
        result = _parse_markdown_state(state_md_path, "WP-2026-145")
        assert result is None

    def test_header_mismatch_returns_none(self, tmp_path: Path) -> None:
        """Parser returns None when header ticket_id does not match requested ticket_id.

        This is the Phase 6 fix: _parse_markdown_state must validate the ticket header
        before trusting the state line, preventing cross-ticket state pollution.
        """
        state_md_path = tmp_path / "STATE.md"
        # STATE.md has header for WP-2026-100 but we request WP-2026-145
        state_md_path.write_text(
            "# State - WP-2026-100\n\n"
            "Plan Activo: WP-2026-100\n"
            "Estado actual: COMPLETED\n",
            encoding="utf-8",
        )
        # Requesting different ticket should return None (header mismatch)
        result = _parse_markdown_state(state_md_path, "WP-2026-145")
        assert result is None

    def test_header_mismatch_does_not_trust_state_line(self, tmp_path: Path) -> None:
        """Parser must not trust 'Estado actual:' when header belongs to different ticket.

        Regression test: even if 'Estado actual: IN_PROGRESS' exists, if the header
        is for a different ticket, the parser must reject it.
        """
        state_md_path = tmp_path / "STATE.md"
        # Old ticket header with a state line that could be misleading
        state_md_path.write_text(
            "# State - WP-2026-099\n\n"
            "Plan Activo: WP-2026-099\n"
            "Estado actual: READY_FOR_REVIEW\n",
            encoding="utf-8",
        )
        # Must NOT return 'READY_FOR_REVIEW' for a different ticket
        result = _parse_markdown_state(state_md_path, "WP-2026-149")
        assert result is None


class TestFilterEventsForTicket:
    """Test filtering events by ticket ID."""

    def test_filter_matching_events(self) -> None:
        """Returns only events for specified ticket."""
        events = [
            {"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-001"},
            {"event_type": "REVIEW_DECISION", "ticket_id": "WP-2026-002"},
            {"event_type": "APPROVAL_RESOLVED", "ticket_id": "WP-2026-001"},
        ]
        result = _filter_events_for_ticket(events, "WP-2026-001")
        assert len(result) == 2
        assert all(e["ticket_id"] == "WP-2026-001" for e in result)

    def test_no_matching_events(self) -> None:
        """Returns empty list when no matches."""
        events = [
            {"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-001"},
        ]
        result = _filter_events_for_ticket(events, "WP-2026-999")
        assert result == []

    def test_empty_events_list(self) -> None:
        """Returns empty list for empty input."""
        result = _filter_events_for_ticket([], "WP-2026-001")
        assert result == []


class TestProbeOutput:
    """Test ProbeOutput dataclass."""

    def test_to_dict(self) -> None:
        """to_dict returns correct dictionary."""
        output = ProbeOutput(
            result=ProbeResult.MATCHED,
            ticket_id="WP-2026-145",
            bus_derived_state="IN_PROGRESS",
            markdown_state="IN_PROGRESS",
            drift_detected=False,
            events_count=5,
            message="State matched: IN_PROGRESS",
        )
        result = output.to_dict()
        assert result["result"] == "matched"
        assert result["ticket_id"] == "WP-2026-145"
        assert result["bus_derived_state"] == "IN_PROGRESS"
        assert result["markdown_state"] == "IN_PROGRESS"
        assert result["drift_detected"] is False
        assert result["events_count"] == 5
        assert result["message"] == "State matched: IN_PROGRESS"


class TestRunProbeMatched:
    """Test run_probe when states match."""

    def test_states_match(self, tmp_path: Path) -> None:
        """Bus-derived state matches markdown state."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with matching state
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "IN_PROGRESS"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md with same state
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: IN_PROGRESS\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.MATCHED
        assert output.bus_derived_state == "IN_PROGRESS"
        assert output.markdown_state == "IN_PROGRESS"
        assert output.drift_detected is False
        assert output.events_count == 1


class TestRunProbeDrift:
    """Test run_probe when drift is detected."""

    def test_states_differ(self, tmp_path: Path) -> None:
        """Bus-derived state differs from markdown state."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with IN_PROGRESS
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "IN_PROGRESS"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md with different state (READY_FOR_REVIEW)
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: READY_FOR_REVIEW\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.DRIFTED
        assert output.bus_derived_state == "IN_PROGRESS"
        assert output.markdown_state == "READY_FOR_REVIEW"
        assert output.drift_detected is True
        assert "Drift detected" in output.message


class TestRunProbeBusEmpty:
    """Test run_probe when bus is empty or missing."""

    def test_events_file_missing(self, tmp_path: Path) -> None:
        """Missing events.jsonl returns BUS_EMPTY."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create STATE.md
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: IN_PROGRESS\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        # No events.jsonl created

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.BUS_EMPTY
        assert output.events_count == 0
        assert "Bus file not found" in output.message

    def test_no_events_for_ticket(self, tmp_path: Path) -> None:
        """No events for specific ticket returns BUS_EMPTY."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with different ticket
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-999", '
            '"payload": {"to_state": "IN_PROGRESS"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: IN_PROGRESS\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.BUS_EMPTY
        assert output.events_count == 1  # Total events, but none for our ticket
        assert "No events found for ticket" in output.message


class TestRunProbeError:
    """Test run_probe error cases."""

    def test_cannot_determine_ticket_id(self, tmp_path: Path) -> None:
        """Missing ticket ID in work_plan.md returns ERROR."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create work_plan.md without ID
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\nNo ID field here\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.ERROR
        assert "Could not determine ticket ID" in output.message

    def test_state_md_missing(self, tmp_path: Path) -> None:
        """Missing STATE.md returns DRIFTED."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "IN_PROGRESS"}}\n',
            encoding="utf-8",
        )

        # Create work_plan.md (no STATE.md)
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.DRIFTED
        assert output.bus_derived_state == "IN_PROGRESS"
        assert output.markdown_state is None
        assert "STATE.md not found" in output.message


class TestRunProbeWithExplicitTicketId:
    """Test run_probe with explicit ticket_id parameter."""

    def test_explicit_ticket_id(self, tmp_path: Path) -> None:
        """Explicit ticket_id overrides work_plan.md."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-999", '
            '"payload": {"to_state": "READY_FOR_REVIEW"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-999\n\nEstado actual: READY_FOR_REVIEW\n",
            encoding="utf-8",
        )

        # Create work_plan.md with different ID (ignored)
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
            ticket_id="WP-2026-999",
        )

        assert output.result == ProbeResult.MATCHED
        assert output.ticket_id == "WP-2026-999"
        assert output.bus_derived_state == "READY_FOR_REVIEW"


class TestRunProbeComplexStateTransitions:
    """Test run_probe with complex state transition sequences."""

    def test_multiple_state_changes(self, tmp_path: Path) -> None:
        """Last STATE_CHANGED determines the state."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with multiple state changes
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "IN_PROGRESS"}}\n'
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "READY_FOR_REVIEW"}}\n'
            '{"event_type": "STATE_CHANGED", "ticket_id": "WP-2026-145", '
            '"payload": {"to_state": "BLOCKED"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md matching last state
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: BLOCKED\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.MATCHED
        assert output.bus_derived_state == "BLOCKED"
        assert output.events_count == 3

    def test_review_decision_event(self, tmp_path: Path) -> None:
        """REVIEW_DECISION event determines state."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with REVIEW_DECISION
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "REVIEW_DECISION", "ticket_id": "WP-2026-145", '
            '"payload": {"decision": "approve"}}\n',
            encoding="utf-8",
        )

        # Create STATE.md
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: READY_TO_CLOSE\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.MATCHED
        assert output.bus_derived_state == "READY_TO_CLOSE"

    def test_close_confirmed_event(self, tmp_path: Path) -> None:
        """CLOSE_CONFIRMED event results in COMPLETED state."""
        runtime_dir = tmp_path / "events"
        runtime_dir.mkdir()
        collaboration_dir = tmp_path / "collaboration"
        collaboration_dir.mkdir()

        # Create events.jsonl with CLOSE_CONFIRMED
        events_path = runtime_dir / "events.jsonl"
        events_path.write_text(
            '{"event_type": "CLOSE_CONFIRMED", "ticket_id": "WP-2026-145", '
            '"payload": {}}\n',
            encoding="utf-8",
        )

        # Create STATE.md
        state_md_path = collaboration_dir / "STATE.md"
        state_md_path.write_text(
            "# State - WP-2026-145\n\nEstado actual: COMPLETED\n",
            encoding="utf-8",
        )

        # Create work_plan.md
        work_plan_path = collaboration_dir / "work_plan.md"
        work_plan_path.write_text(
            "# Work Plan\n\n- **ID:** WP-2026-145\n",
            encoding="utf-8",
        )

        output = run_probe(
            runtime_dir=runtime_dir,
            collaboration_dir=collaboration_dir,
        )

        assert output.result == ProbeResult.MATCHED
        assert output.bus_derived_state == "COMPLETED"
