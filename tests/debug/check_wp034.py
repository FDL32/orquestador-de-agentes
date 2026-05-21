#!/usr/bin/env python3
"""Check WP-2026-034 events."""

import json
from pathlib import Path


events_file = Path(".agent/runtime/events/events.jsonl")
with open(events_file, encoding="utf-8") as f:
    all_events = [json.loads(line) for line in f if line.strip()]

# Get WP-2026-034 events
wp034 = [e for e in all_events if e["ticket_id"] == "WP-2026-034"]
print(f"Total WP-2026-034 events: {len(wp034)}")
print("\nLast 8 WP-2026-034 events:\n")

for evt in wp034[-8:]:
    seq = evt["sequence_number"]
    etype = evt["event_type"]
    actor = evt["actor"]
    ts = str(evt["timestamp"])[:19]
    print(f"{seq:4d} | {etype:20s} | {actor:10s} | {ts}")

    if evt.get("payload"):
        payload = evt["payload"]
        if "action" in payload:
            print(f"       -> action: {payload['action']}")
        if "from_status" in payload and "to_status" in payload:
            print(f"       -> {payload['from_status']} -> {payload['to_status']}")
        if "decision" in payload:
            print(f"       -> decision: {payload['decision']}")
        if "note" in payload and len(str(payload["note"])) > 100:
            print(f"       -> note: {str(payload['note'])[:100]}...")
    print()
