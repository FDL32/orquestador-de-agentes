from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from council.verdict import CouncilDecision, CouncilReport, Event


class CouncilBroker:
    """Council broker for managing peer review and audit state."""

    def __init__(self, ticket_id: str, runtime_dir: Path):
        """Initialize council broker."""
        self.ticket_id = ticket_id
        self.runtime_dir = runtime_dir
        self.events_path = runtime_dir / "council_events.jsonl"
        self.state_path = runtime_dir / "council_state.json"

    def _append_event(self, event: Event) -> None:
        """Append event to the JSONL log."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        event_data = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event.event_type,
            "ticket_id": event.ticket_id,
            "actor": event.actor,
            "payload": event.payload,
        }

        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_data, ensure_ascii=False) + "\n")

    def _write_state(self, report: CouncilReport) -> None:
        """Write council state to JSON file."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        state_data = {
            "ticket_id": report.ticket_id,
            "phase": report.phase,
            "verdicts": report.verdicts,
            "blocking_findings": report.blocking_findings,
            "consensus_confidence": report.consensus_confidence,
            "decision": report.decision.value,
            "next_action": report.next_action,
            "repair_attempt": report.repair_attempt,
            "max_repairs": report.max_repairs,
        }

        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)

    def _synthesize(self, audit_results: list[dict[str, Any]]) -> CouncilReport:
        """Synthesize council report from audit results."""
        verdicts = {}
        blocking_findings = []
        consensus_confidence = 1.0

        for result in audit_results:
            auditor = result.get("auditor", "unknown")
            findings = result.get("findings", [])

            # Collect verdicts
            if findings:
                verdicts[auditor] = "REJECTED"
                consensus_confidence *= 0.8  # Reduce confidence for findings
            else:
                verdicts[auditor] = "APPROVED"

            # Collect blocking findings
            for finding in findings:
                if finding.get("severity") == "high":
                    blocking_findings.append(finding)
                elif finding.get("severity") == "low":
                    consensus_confidence *= 0.9  # Reduce confidence for low severity

        # Determine decision
        if blocking_findings:
            decision = CouncilDecision.HUMAN_GATE
            next_action = "HUMAN_REVIEW"
            repair_attempt = 0  # Reset on human gate
        elif consensus_confidence < 1.0:
            decision = CouncilDecision.REPAIR_REQUIRED
            next_action = "EXECUTOR_REPAIR"
            repair_attempt = 1  # Increment repair attempt
        else:
            decision = CouncilDecision.READY_FOR_HUMAN_REVIEW
            next_action = None
            repair_attempt = 0

        return CouncilReport(
            ticket_id=self.ticket_id,
            phase="PEER_REVIEW_COMPLETE",
            verdicts=verdicts,
            blocking_findings=blocking_findings,
            consensus_confidence=consensus_confidence,
            decision=decision,
            next_action=next_action,
            repair_attempt=repair_attempt,
            max_repairs=3,
        )
