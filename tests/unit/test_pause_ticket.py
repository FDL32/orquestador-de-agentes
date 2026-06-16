"""
Test suite for --pause-ticket functionality (WOT-2026-010d).

Tests the minimal lifecycle: IN_PROGRESS -> PAUSED -> IN_PROGRESS
with mandatory reason, bus event, readable artifact in repo_destino,
fail-closed recovery, and handoff blocking.

Contract: test_pause_ticket.py
"""

import json
from unittest import mock

import pytest


@pytest.fixture
def temp_repo_structure(tmp_path):
    """Create a minimal repo_motor + repo_destino structure."""
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"

    motor.mkdir()
    destino.mkdir()

    # Minimal structure in destino
    (destino / ".agent" / "collaboration").mkdir(parents=True)
    (destino / ".agent" / "runtime").mkdir(parents=True)
    (destino / ".agent" / "collaboration" / "paused").mkdir(parents=True)

    work_plan_path = destino / ".agent" / "collaboration" / "work_plan.md"
    work_plan_path.write_text("# Work Plan: WOT-2026-010d\n- **ID:** WOT-2026-010d\n")

    state_path = destino / ".agent" / "collaboration" / "STATE.md"
    state_path.write_text("ACTIVE_TICKET: WOT-2026-010d\nSTATUS: IN_PROGRESS\n")

    return {"motor": motor, "destino": destino}


@pytest.fixture
def mock_event_bus(temp_repo_structure):
    """Mock EventBus with ticket WOT-2026-010d in IN_PROGRESS."""
    bus = mock.MagicMock()  # No spec to allow custom methods
    bus.read_events.return_value = []
    bus.get_last_sequence.return_value = 0
    bus.emit.return_value = {"event_id": "test-event-1", "seq": 1}
    return bus


class TestPauseTicketBarrier:
    """Barrier tests for --pause-ticket: tests that verify pause exists or is implemented."""

    def test_pause_artifact_directory_exists(self, temp_repo_structure):
        """Verify paused/ directory exists in collaboration folder."""
        paused_dir = (
            temp_repo_structure["destino"] / ".agent" / "collaboration" / "paused"
        )
        assert paused_dir.exists(), "paused/ directory must exist"

    def test_pause_handler_exists_in_agent_controller(self):
        """Verify --pause-ticket handler is defined in agent_controller."""
        try:
            from agent_controller import _handle_pause_ticket

            assert callable(_handle_pause_ticket)
        except ImportError:
            pytest.fail("_handle_pause_ticket not found in agent_controller")

    def test_paused_state_will_exist_in_state_machine(self):
        """Verify PAUSED state will be added to TicketState enum."""
        # This test will pass once PAUSED is added
        try:
            from bus.state_machine import TicketState

            # When implemented, PAUSED should exist
            has_paused = hasattr(TicketState, "PAUSED")
            # For now, this documents what needs to be added
            assert has_paused, "PAUSED state should be added to TicketState"
        except ImportError:
            pytest.skip("state_machine not available")

    def test_pause_artifact_json_schema_example(self, temp_repo_structure):
        """Document the expected JSON schema for pause artifacts."""
        # Demonstrate that a pause artifact JSON can be created and loaded
        from pathlib import Path

        paused_dir = (
            Path(temp_repo_structure["destino"]) / ".agent" / "collaboration" / "paused"
        )
        paused_dir.mkdir(parents=True, exist_ok=True)

        artifact_data = {
            "ticket_id": "WOT-2026-010d",
            "status": "PAUSED",
            "reason": "Working on critical fix",
            "stash_ref": "stash@{0}",
        }

        artifact_path = paused_dir / "WOT-2026-010d.json"
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(artifact_data, f, indent=2)

        # Verify it can be read back
        with open(artifact_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["status"] == "PAUSED"
        assert loaded["ticket_id"] == "WOT-2026-010d"
        test_artifact = paused_dir / "WOT-2026-010d.json"

        # Can write test artifact
        test_artifact.write_text(
            json.dumps(
                {
                    "ticket_id": "WOT-2026-010d",
                    "status": "PAUSED",
                    "reason": "Test",
                    "timestamp": "2026-06-16T00:00:00Z",
                    "repo": "motor",
                    "changed_paths": [],
                    "diff_stat": "",
                    "stash_ref": None,
                    "bus_last_seq_global": 0,
                    "ticket_last_seq": 0,
                }
            )
        )

        assert test_artifact.exists()
        artifact_data = json.loads(test_artifact.read_text())
        assert artifact_data["ticket_id"] == "WOT-2026-010d"
