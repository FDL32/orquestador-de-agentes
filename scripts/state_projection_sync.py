#!/usr/bin/env python3
"""
Idempotent STATE projection sync.

Updates STATE.md from the bus-derived state if drift is detected.
Relies on state_projection_probe.py for detection.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import after path setup (E402 intentional for runtime path resolution)
from scripts.state_projection_probe import ProbeResult, run_probe  # noqa: E402


def sync_state_projection(
    runtime_dir: Path | None = None,
    collaboration_dir: Path | None = None,
    ticket_id: str | None = None,
) -> bool:
    """
    Synchronize STATE.md from the bus-derived state if drifted.
    Returns True if state was synced or already matched, False if error.
    """
    if collaboration_dir is None:
        collaboration_dir = _PROJECT_ROOT / ".agent" / "collaboration"

    probe_output = run_probe(
        runtime_dir=runtime_dir,
        collaboration_dir=collaboration_dir,
        ticket_id=ticket_id,
    )

    if probe_output.result == ProbeResult.ERROR:
        return False

    if probe_output.result == ProbeResult.BUS_EMPTY:
        # Fallback gracefully
        return True

    if probe_output.result == ProbeResult.MATCHED:
        return True

    if probe_output.result == ProbeResult.DRIFTED and probe_output.bus_derived_state:
        state_md_path = collaboration_dir / "STATE.md"
        actual_ticket_id = probe_output.ticket_id

        # Write canonical plain line format
        content = f"# State - {actual_ticket_id}\n\nEstado actual: {probe_output.bus_derived_state}\n"
        state_md_path.write_text(content, encoding="utf-8")
        return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize STATE.md from events.jsonl"
    )
    parser.add_argument("--ticket-id", type=str, default=None)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    args = parser.parse_args()

    success = sync_state_projection(
        runtime_dir=args.runtime_dir, ticket_id=args.ticket_id
    )
    if success:
        print("Sync completed successfully.")
    else:
        print("Sync encountered an error.")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
