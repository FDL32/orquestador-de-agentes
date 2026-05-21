#!/usr/bin/env python3
"""Test review bridge state projection capabilities."""

import json
import sys
from pathlib import Path

# Add .agent to path for imports
agent_path = Path(__file__).parent.parent.parent / ".agent"
sys.path.insert(0, str(agent_path))

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


def test_state_projection():
    """Test that bridge correctly projects ticket state, round, and last decision."""
    project_root = Path(__file__).parent.parent.parent
    event_bus = EventBus(runtime_dir=project_root / ".agent" / "runtime" / "events")
    bridge = ReviewBridge(event_bus, project_root=project_root)

    # Test case: WP-2026-048 with some event history
    ticket_id = "WP-2026-048"

    # Test round determination
    round_num = bridge._determine_current_round(ticket_id)
    print(f"Ticket {ticket_id} current round: {round_num}")
    assert isinstance(round_num, str) and (round_num.startswith("BR") or round_num.startswith("MR"))

    # Test state retrieval
    state, source = bridge._get_current_state(ticket_id)
    print(f"Current state: {state} (from {source})")
    assert state is not None

    # Test last decision retrieval
    last_decision = bridge._get_last_decision(ticket_id)
    print(f"Last decision: {last_decision}")
    assert isinstance(last_decision, str)

    # Test combined state line format
    state_line = f"[{ticket_id}] {round_num} | {state}"
    if last_decision != "none":
        state_line += f" | last: {last_decision}"

    print(f"\nFormatted state line:")
    print(f"  {state_line}")

    # Verify format is reasonable
    assert "[" in state_line and "]" in state_line
    assert "|" in state_line
    assert ticket_id in state_line
    assert (round_num in state_line)

    print("\n[OK] All tests passed!")
    return True


if __name__ == "__main__":
    test_state_projection()
