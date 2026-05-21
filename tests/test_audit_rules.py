"""Tests for council audit rules and stop conditions."""

from __future__ import annotations

import pytest
from council.audit_rules import (
    DEFAULT_REPAIR_BUDGET,
    RepairBudget,
    should_human_gate,
    should_retry,
)
from council.verdict import CouncilDecision, CouncilReport


@pytest.fixture
def sample_report():
    """Sample council report for testing."""
    return CouncilReport(
        ticket_id="TEST-001",
        phase="PEER_REVIEW_COMPLETE",
        verdicts={
            "executor": "APPROVED",
            "static_auditor": "APPROVED",
            "security_auditor": "APPROVED",
            "regression_auditor": "APPROVED",
        },
        blocking_findings=[],
        consensus_confidence=1.0,
        decision=CouncilDecision.READY_FOR_HUMAN_REVIEW,
        next_action=None,
        repair_attempt=0,
        max_repairs=3,
    )


class TestRepairBudget:
    """Test RepairBudget configuration."""

    def test_default_budget(self):
        """Test default repair budget values."""
        assert DEFAULT_REPAIR_BUDGET.max_attempts == 3
        assert DEFAULT_REPAIR_BUDGET.weak_consensus_threshold == 0.7

    def test_custom_budget(self):
        """Test custom repair budget."""
        budget = RepairBudget(max_attempts=5, weak_consensus_threshold=0.8)
        assert budget.max_attempts == 5
        assert budget.weak_consensus_threshold == 0.8


class TestShouldHumanGate:
    """Test human gate conditions."""

    def test_no_blocking_findings_high_confidence(self, sample_report):
        """Should not gate when no blocking findings and high confidence."""
        assert not should_human_gate(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_blocking_findings(self, sample_report):
        """Should gate when there are blocking findings."""
        sample_report.blocking_findings = [{"id": "test", "severity": "high"}]
        assert should_human_gate(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_low_confidence(self, sample_report):
        """Should gate when consensus confidence is below threshold."""
        sample_report.consensus_confidence = 0.5
        assert should_human_gate(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_max_repair_attempts_reached(self, sample_report):
        """Should gate when max repair attempts reached."""
        sample_report.repair_attempt = 3
        assert should_human_gate(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_human_gate_decision(self, sample_report):
        """Should gate when decision is HUMAN_GATE."""
        sample_report.decision = CouncilDecision.HUMAN_GATE
        assert should_human_gate(sample_report, DEFAULT_REPAIR_BUDGET)


class TestShouldRetry:
    """Test retry conditions."""

    def test_repair_required_within_budget(self, sample_report):
        """Should retry when repair required and within budget."""
        sample_report.decision = CouncilDecision.REPAIR_REQUIRED
        sample_report.repair_attempt = 1
        sample_report.consensus_confidence = 0.8
        assert should_retry(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_repair_required_but_max_attempts_reached(self, sample_report):
        """Should not retry when max attempts reached."""
        sample_report.decision = CouncilDecision.REPAIR_REQUIRED
        sample_report.repair_attempt = 3
        assert not should_retry(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_repair_required_but_low_confidence(self, sample_report):
        """Should not retry when confidence too low."""
        sample_report.decision = CouncilDecision.REPAIR_REQUIRED
        sample_report.repair_attempt = 1
        sample_report.consensus_confidence = 0.6
        assert not should_retry(sample_report, DEFAULT_REPAIR_BUDGET)

    def test_not_repair_required(self, sample_report):
        """Should not retry when decision is not REPAIR_REQUIRED."""
        assert not should_retry(sample_report, DEFAULT_REPAIR_BUDGET)
