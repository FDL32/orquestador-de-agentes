from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RepairBudget:
    """Configuration for repair attempts and thresholds."""

    max_attempts: int = 3
    weak_consensus_threshold: float = 0.7


DEFAULT_REPAIR_BUDGET = RepairBudget()


def should_human_gate(report: Any, budget: RepairBudget) -> bool:
    """Determine if human gate is required based on report and budget."""
    # Gate if there are blocking findings
    if report.blocking_findings:
        return True

    # Gate if confidence is below threshold
    if report.consensus_confidence < budget.weak_consensus_threshold:
        return True

    # Gate if max repair attempts reached
    if report.repair_attempt >= budget.max_attempts:
        return True

    # Gate if decision is HUMAN_GATE
    return bool(hasattr(report, "decision") and str(report.decision) == "HUMAN_GATE")


def should_retry(report: Any, budget: RepairBudget) -> bool:
    """Determine if retry is appropriate based on report and budget."""
    # Only retry if decision is REPAIR_REQUIRED
    if not hasattr(report, "decision") or str(report.decision) != "REPAIR_REQUIRED":
        return False

    # Don't retry if max attempts reached
    if report.repair_attempt >= budget.max_attempts:
        return False

    # Don't retry if confidence is too low
    return not report.consensus_confidence < budget.weak_consensus_threshold
