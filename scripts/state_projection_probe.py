#!/usr/bin/env python3
"""
Deterministic STATE projection probe.

Read-only probe that reconstructs the active ticket state from events.jsonl,
compares it against STATE.md, and reports any drift.

This probe validates whether the bus can serve as single source of truth
for state projection, without mutating canonical files.

Usage:
    python scripts/state_projection_probe.py [--ticket-id WP-YYYY-NNN] [--json]

Exit codes:
    0 - State matched or drift detected (informational)
    1 - Error (file not found, parse error, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from bus.state_machine import StateMachine  # noqa: E402


class ProbeResult(str, Enum):
    """Result status of the state projection probe."""

    MATCHED = "matched"
    DRIFTED = "drifted"
    BUS_EMPTY = "bus_empty"
    ERROR = "error"


@dataclass(slots=True)
class ProbeOutput:
    """Structured output from the state projection probe."""

    result: ProbeResult
    ticket_id: str
    bus_derived_state: str | None
    markdown_state: str | None
    drift_detected: bool
    events_count: int
    message: str

    def to_dict(self) -> dict:
        return {
            "result": self.result.value,
            "ticket_id": self.ticket_id,
            "bus_derived_state": self.bus_derived_state,
            "markdown_state": self.markdown_state,
            "drift_detected": self.drift_detected,
            "events_count": self.events_count,
            "message": self.message,
        }


def _read_events_jsonl(events_path: Path) -> list[dict]:
    """
    Read events from the JSONL bus file.

    Before: File must exist at events_path.
    During: Parses each line as JSON, skipping empty lines and malformed entries.
    After: Returns list of event dicts; empty list if file missing.
    """
    if not events_path.exists():
        return []

    events: list[dict] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip malformed lines silently (read-only probe)
            continue
    return events


def _extract_ticket_id_from_work_plan(work_plan_path: Path) -> str | None:
    """
    Extract active ticket ID from work_plan.md.

    Before: File must exist at work_plan_path.
    During: Parses markdown metadata section for **ID:** field.
    After: Returns ticket ID string or None if not found.
    """
    if not work_plan_path.exists():
        return None

    content = work_plan_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        # Match both "**ID:** WP-2026-145" and "- **ID:** WP-2026-145"
        if "**ID:**" in line:
            # Extract everything after the colon, strip markdown and whitespace
            parts = line.split(":", 1)
            if len(parts) == 2:
                ticket_id = parts[1].strip()
                # Remove markdown bold markers
                ticket_id = ticket_id.replace("**", "").strip()
                return ticket_id
    return None


def _parse_markdown_state(state_md_path: Path, ticket_id: str) -> str | None:
    """
    Parse current state from STATE.md.

    Before: File must exist at state_md_path.
    During: Searches for 'Estado actual:' line or plan header matching ticket_id.
    After: Returns state string or None if not found.
    """
    if not state_md_path.exists():
        return None

    content = state_md_path.read_text(encoding="utf-8")

    expected_header = f"# State - {ticket_id}"
    if expected_header not in content:
        return None

    for line in content.splitlines():
        line_stripped = line.strip()
        # Look for "Estado actual: STATE" or "- **Estado actual:** STATE"
        if line_stripped.startswith("Estado actual:"):
            return line_stripped.split(":", 1)[1].strip()
        if line_stripped.startswith("- **Estado actual:**"):
            return line_stripped.split(":", 1)[1].strip().replace("*", "")
    return None


def _filter_events_for_ticket(all_events: list[dict], ticket_id: str) -> list[dict]:
    """
    Filter events belonging to a specific ticket.

    Before: all_events is a list of event dicts.
    During: Filters by ticket_id field.
    After: Returns filtered list (may be empty).
    """
    return [e for e in all_events if e.get("ticket_id") == ticket_id]


def run_probe(
    runtime_dir: Path | None = None,
    collaboration_dir: Path | None = None,
    ticket_id: str | None = None,
) -> ProbeOutput:
    """
    Run the deterministic state projection probe.

    Before:
        - runtime_dir must point to .agent/runtime/events/ or similar.
        - collaboration_dir must point to .agent/collaboration/.
        - If ticket_id not provided, reads from work_plan.md.
        - events.jsonl may or may not exist.
        - STATE.md may or may not exist.

    During:
        - Reads events from events.jsonl (read-only).
        - Derives state using StateMachine.derive_state_from_events().
        - Parses STATE.md for comparison.
        - Compares bus-derived state vs markdown state.

    After:
        - Returns ProbeOutput with result status.
        - Does NOT mutate any canonical files.
        - May log warnings for invalid transitions (non-blocking).

    Raises:
        No exceptions are raised; errors are captured in ProbeOutput.
    """
    # Resolve paths
    if runtime_dir is None:
        runtime_dir = _PROJECT_ROOT / ".agent" / "runtime" / "events"

    if collaboration_dir is None:
        collaboration_dir = _PROJECT_ROOT / ".agent" / "collaboration"

    events_path = runtime_dir / "events.jsonl"
    state_md_path = collaboration_dir / "STATE.md"
    work_plan_path = collaboration_dir / "work_plan.md"

    # Determine ticket ID
    if ticket_id is None:
        ticket_id = _extract_ticket_id_from_work_plan(work_plan_path)
        if not ticket_id:
            return ProbeOutput(
                result=ProbeResult.ERROR,
                ticket_id="unknown",
                bus_derived_state=None,
                markdown_state=None,
                drift_detected=False,
                events_count=0,
                message="Could not determine ticket ID from work_plan.md",
            )

    # Read events from bus
    if not events_path.exists():
        return ProbeOutput(
            result=ProbeResult.BUS_EMPTY,
            ticket_id=ticket_id,
            bus_derived_state=None,
            markdown_state=None,
            drift_detected=False,
            events_count=0,
            message=f"Bus file not found: {events_path}",
        )

    all_events = _read_events_jsonl(events_path)
    ticket_events = _filter_events_for_ticket(all_events, ticket_id)

    if not ticket_events:
        return ProbeOutput(
            result=ProbeResult.BUS_EMPTY,
            ticket_id=ticket_id,
            bus_derived_state=None,
            markdown_state=None,
            drift_detected=False,
            events_count=len(all_events),
            message=f"No events found for ticket {ticket_id}",
        )

    # Derive state from bus events using the canonical StateMachine
    try:
        derived_state = StateMachine.derive_state_from_events(ticket_events)
        bus_derived_state = derived_state.value
    except Exception as e:
        return ProbeOutput(
            result=ProbeResult.ERROR,
            ticket_id=ticket_id,
            bus_derived_state=None,
            markdown_state=None,
            drift_detected=False,
            events_count=len(ticket_events),
            message=f"Error deriving state from events: {e}",
        )

    # Parse markdown state
    markdown_state = _parse_markdown_state(state_md_path, ticket_id)

    # Compare states
    if markdown_state is None:
        return ProbeOutput(
            result=ProbeResult.DRIFTED,
            ticket_id=ticket_id,
            bus_derived_state=bus_derived_state,
            markdown_state=None,
            drift_detected=True,
            events_count=len(ticket_events),
            message="STATE.md not found or state not parseable",
        )

    drift_detected = bus_derived_state != markdown_state

    if drift_detected:
        return ProbeOutput(
            result=ProbeResult.DRIFTED,
            ticket_id=ticket_id,
            bus_derived_state=bus_derived_state,
            markdown_state=markdown_state,
            drift_detected=True,
            events_count=len(ticket_events),
            message=f"Drift detected: bus={bus_derived_state}, markdown={markdown_state}",
        )
    else:
        return ProbeOutput(
            result=ProbeResult.MATCHED,
            ticket_id=ticket_id,
            bus_derived_state=bus_derived_state,
            markdown_state=markdown_state,
            drift_detected=False,
            events_count=len(ticket_events),
            message=f"State matched: {bus_derived_state}",
        )


def main() -> int:
    """
    Main entry point for the state projection probe.

    Before: Command-line arguments parsed.
    During: Runs probe and formats output.
    After: Prints result and returns exit code.
    """
    parser = argparse.ArgumentParser(
        description="Deterministic STATE projection probe (read-only)"
    )
    parser.add_argument(
        "--ticket-id",
        type=str,
        default=None,
        help="Ticket ID to probe (default: read from work_plan.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Runtime directory containing events.jsonl",
    )

    args = parser.parse_args()

    output = run_probe(runtime_dir=args.runtime_dir, ticket_id=args.ticket_id)

    if args.json:
        print(json.dumps(output.to_dict(), indent=2))
    else:
        print(f"[STATE PROBE] Ticket: {output.ticket_id}")
        print(f"[STATE PROBE] Result: {output.result.value}")
        print(f"[STATE PROBE] Bus-derived state: {output.bus_derived_state or 'N/A'}")
        print(f"[STATE PROBE] Markdown state: {output.markdown_state or 'N/A'}")
        print(f"[STATE PROBE] Events count: {output.events_count}")
        print(f"[STATE PROBE] Drift detected: {output.drift_detected}")
        print(f"[STATE PROBE] Message: {output.message}")

    # Exit code: 0 for informational results, 1 for errors
    if output.result == ProbeResult.ERROR:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
