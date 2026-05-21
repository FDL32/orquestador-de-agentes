from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CouncilDecision(Enum):
    """Possible decisions from council evaluation."""

    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    REPAIR_REQUIRED = "repair_required"
    HUMAN_GATE = "human_gate"


@dataclass
class CouncilReport:
    """Report from council evaluation."""

    ticket_id: str
    phase: str
    verdicts: dict[str, str]
    blocking_findings: list[dict[str, Any]]
    consensus_confidence: float
    decision: CouncilDecision
    next_action: str | None
    repair_attempt: int
    max_repairs: int


@dataclass
class Event:
    """Council event for logging."""

    event_type: str
    ticket_id: str
    actor: str
    payload: dict[str, Any]
