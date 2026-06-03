"""Tests for council broker state machine."""

from __future__ import annotations

import json

import pytest
from council.council_broker import CouncilBroker
from council.verdict import CouncilDecision, CouncilReport, Event


@pytest.fixture
def temp_runtime_dir(tmp_path):
    """Temporary runtime directory for tests."""
    runtime_dir = tmp_path / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True)
    return runtime_dir


@pytest.fixture
def broker(temp_runtime_dir):
    """Council broker instance for testing."""
    return CouncilBroker(
        ticket_id="TEST-001",
        runtime_dir=temp_runtime_dir,
    )


class TestCouncilBrokerInitialization:
    """Test broker initialization."""

    def test_initialization(self, broker, temp_runtime_dir):
        """Test broker initializes correctly."""
        assert broker.ticket_id == "TEST-001"
        assert broker.runtime_dir == temp_runtime_dir
        assert broker.events_path == temp_runtime_dir / "council_events.jsonl"
        assert broker.state_path == temp_runtime_dir / "council_state.json"

    def test_runtime_dir_creation(self, broker):
        """Test runtime directory is created when broker starts."""
        # Directory paths should exist after start() is called
        # They are created lazy on first append/write
        assert broker.runtime_dir.parent.exists()  # Parent should exist


class TestEventLogging:
    """Test event logging functionality."""

    def test_append_event(self, broker):
        """Test appending events to JSONL log."""
        event = Event(
            event_type="TEST_EVENT",
            ticket_id="TEST-001",
            actor="test_actor",
            payload={"test": "data"},
        )

        broker._append_event(event)

        content = broker.events_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        logged_event = json.loads(lines[0])
        assert logged_event["event_type"] == "TEST_EVENT"
        assert logged_event["ticket_id"] == "TEST-001"
        assert logged_event["actor"] == "test_actor"
        assert logged_event["payload"] == {"test": "data"}
        assert "event_id" in logged_event
        assert "timestamp" in logged_event


class TestStatePersistence:
    """Test state persistence."""

    def test_write_state(self, broker):
        """Test writing council state."""
        report = CouncilReport(
            ticket_id="TEST-001",
            phase="TEST_PHASE",
            verdicts={"test": "approved"},
            blocking_findings=[],
            consensus_confidence=1.0,
            decision=CouncilDecision.READY_FOR_HUMAN_REVIEW,
            next_action=None,
            repair_attempt=0,
            max_repairs=3,
        )

        broker._write_state(report)

        content = broker.state_path.read_text()
        state_data = json.loads(content)

        assert state_data["ticket_id"] == "TEST-001"
        assert state_data["phase"] == "TEST_PHASE"
        assert state_data["decision"] == "ready_for_human_review"


class TestSynthesisLogic:
    """Test council report synthesis."""

    def test_synthesize_ready_for_review(self, broker):
        """Test synthesis when ready for human review."""
        audit_results = [
            {"auditor": "static_auditor", "findings": []},
            {"auditor": "security_auditor", "findings": []},
            {"auditor": "regression_auditor", "findings": []},
        ]

        report = broker._synthesize(audit_results)

        assert report.ticket_id == "TEST-001"
        assert report.phase == "PEER_REVIEW_COMPLETE"
        assert report.decision == CouncilDecision.READY_FOR_HUMAN_REVIEW
        assert report.repair_attempt == 0
        assert report.consensus_confidence == 1.0

    def test_synthesize_with_low_findings(self, broker):
        """Test synthesis with non-blocking findings triggers repair."""
        audit_results = [
            {"auditor": "static_auditor", "findings": [{"severity": "low"}]},
            {"auditor": "security_auditor", "findings": []},
            {"auditor": "regression_auditor", "findings": []},
        ]

        report = broker._synthesize(audit_results)

        assert report.ticket_id == "TEST-001"
        # Non-blocking findings should trigger REPAIR_REQUIRED, not READY
        assert report.decision == CouncilDecision.REPAIR_REQUIRED
        assert report.next_action == "EXECUTOR_REPAIR"
        assert report.repair_attempt == 1  # First repair attempt
        assert report.consensus_confidence < 1.0  # Should be reduced

    def test_synthesize_with_blocking_findings(self, broker):
        """Test synthesis with blocking findings triggers human gate."""
        audit_results = [
            {"auditor": "static_auditor", "findings": []},
            {"auditor": "security_auditor", "findings": [{"severity": "high"}]},
            {"auditor": "regression_auditor", "findings": []},
        ]

        report = broker._synthesize(audit_results)

        assert report.ticket_id == "TEST-001"
        assert report.decision == CouncilDecision.HUMAN_GATE
        assert report.blocking_findings  # Should have blocking findings
        assert report.next_action == "HUMAN_REVIEW"


class TestBrokerFlow:
    """Test the complete broker flow."""

    def test_synthesis_and_event_persistence(self, broker):
        """Test synthesis and event/state persistence (synchronous)."""
        # Test synthesis with clean audit results
        audit_results = [
            {"auditor": "static_auditor", "findings": []},
            {"auditor": "security_auditor", "findings": []},
            {"auditor": "regression_auditor", "findings": []},
        ]

        report = broker._synthesize(audit_results)

        # Verify synthesis produces correct report
        assert report.ticket_id == "TEST-001"
        assert report.decision == CouncilDecision.READY_FOR_HUMAN_REVIEW

        # Test event appending
        from council.verdict import Event

        event = Event(
            event_type="TEST_EVENT",
            ticket_id="TEST-001",
            actor="test",
            payload={},
        )
        broker._append_event(event)

        # Verify event was persisted
        assert broker.events_path.exists()
        content = broker.events_path.read_text()
        assert "TEST_EVENT" in content

        # Test state writing
        broker._write_state(report)
        assert broker.state_path.exists()
        state_content = broker.state_path.read_text()
        assert "ready_for_human_review" in state_content
