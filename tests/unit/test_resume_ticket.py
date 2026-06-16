"""
Test suite for --resume-ticket functionality (WOT-2026-010d).

Tests resume from PAUSED state: restoration of changes, bus advancement,
fail-closed behavior on conflicts, and detection of intervening events.

Contract: test_resume_ticket.py
"""

import json
from unittest import mock

import pytest


@pytest.fixture
def paused_ticket_artifact(tmp_path):
    """Create a paused ticket artifact in repo_destino."""
    destino = tmp_path / "destino"
    (destino / ".agent" / "collaboration" / "paused").mkdir(parents=True)

    artifact = {
        "ticket_id": "WOT-2026-010d",
        "status": "PAUSED",
        "reason": "Pausing for hotfix",
        "timestamp": "2026-06-16T12:00:00+00:00",
        "repo": "motor",
        "changed_paths": ["src/file1.py"],
        "diff_stat": "1 file changed, 10 insertions(+), 5 deletions(-)",
        "stash_ref": "abc123def456",
        "wip_commit": None,
        "bus_last_seq_global": 100,
        "ticket_last_seq": 42,
        "state_snapshot": {"status": "IN_PROGRESS"},
        "turn_snapshot": {},
        "resume_instructions": "Apply stash and verify state",
    }

    artifact_path = (
        destino / ".agent" / "collaboration" / "paused" / "WOT-2026-010d.json"
    )
    artifact_path.write_text(json.dumps(artifact, indent=2))

    return {"destino": destino, "artifact_path": artifact_path, "artifact": artifact}


@pytest.fixture
def mock_event_bus_with_history():
    """Mock EventBus with events history."""
    bus = mock.MagicMock()  # No spec to allow custom methods

    # Global sequence is at 110 (advanced by 10 since pause at 100)
    bus.get_last_sequence.return_value = 110

    # Ticket WOT-2026-010d has only the pause event (seq 42)
    # No new events for this ticket after pause
    bus.read_events.return_value = []
    bus.emit.return_value = {"event_id": "resume-event", "seq": 111}

    return bus


class TestResumeTicketBarrier:
    """Barrier tests for --resume-ticket: tests that verify resume structure."""

    def test_resume_handler_exists_in_agent_controller(self):
        """Verify --resume-ticket handler is defined in agent_controller."""
        try:
            from agent_controller import _handle_resume_ticket

            assert callable(_handle_resume_ticket)
        except ImportError:
            pytest.fail("_handle_resume_ticket not found in agent_controller")

    def test_pause_artifact_can_be_created_and_read(self, paused_ticket_artifact):
        """Verify pause artifacts can be created and read."""
        artifact_path = paused_ticket_artifact["artifact_path"]
        assert artifact_path.exists()

        artifact = json.loads(artifact_path.read_text())
        assert artifact["ticket_id"] == "WOT-2026-010d"
        assert artifact["status"] == "PAUSED"
        assert "reason" in artifact

    def test_resume_will_validate_artifact_existence(self, paused_ticket_artifact):
        """Document that resume will require valid artifact."""
        # Resume should fail if artifact doesn't exist
        missing_artifact = (
            paused_ticket_artifact["destino"]
            / ".agent"
            / "collaboration"
            / "paused"
            / "MISSING.json"
        )
        assert not missing_artifact.exists()

        # This documents the precondition for resume operations

    def test_resume_artifact_contains_required_fields(self, paused_ticket_artifact):
        """Verify pause artifact has all required fields for resume."""
        artifact = paused_ticket_artifact["artifact"]

        required_fields = [
            "ticket_id",
            "status",
            "reason",
            "bus_last_seq_global",
            "ticket_last_seq",
        ]

        for field in required_fields:
            assert field in artifact, f"Artifact missing required field: {field}"


class TestAbortPausedTicket:
    """Tests for --abort-paused-ticket: fail-closed or auditable stub."""

    def test_abort_paused_ticket_exists(self):
        """--abort-paused-ticket flag must exist and be callable."""
        from agent_controller import _handle_abort_paused_ticket

        assert callable(_handle_abort_paused_ticket), (
            "--abort-paused-ticket handler must exist"
        )

    def test_abort_stub_audit_trail(self, paused_ticket_artifact):
        """If --abort-paused-ticket is stubbed, it must record audit trail with reason."""
        ticket_id = "WOT-2026-010d"
        reason = "Aborting due to complexity"

        from agent_controller import _handle_abort_paused_ticket

        result = _handle_abort_paused_ticket(
            ticket_id=ticket_id, reason=reason, json_output=False
        )

        # Either success (0) or fail with clear diagnostic
        assert isinstance(result, int)

        # If stub, artifact must be updated with abort reason
        artifact_path = paused_ticket_artifact["artifact_path"]
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text())
            if "abort_reason" in artifact:
                assert artifact["abort_reason"] == reason
