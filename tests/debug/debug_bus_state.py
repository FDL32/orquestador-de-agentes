#!/usr/bin/env python3
"""Debug script to analyze the event bus state."""

import json
from collections import defaultdict
from contextlib import suppress
from pathlib import Path


events_file = Path(".agent/runtime/events/events.jsonl")
events = []

with open(events_file, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            with suppress(json.JSONDecodeError):
                events.append(json.loads(line))

# Group by ticket_id
by_ticket = defaultdict(list)
for event in events:
    by_ticket[event["ticket_id"]].append(event)

print(f"Total events: {len(events)}")
print(f"Total unique tickets: {len(by_ticket)}")
print("\nTickets by event count (top 10):")

for tid, events_list in sorted(
    by_ticket.items(), key=lambda x: len(x[1]), reverse=True
)[:10]:
    last_event = events_list[-1]
    print(
        f"{tid:12} | {len(events_list):4} events | last: {last_event['event_type']:20} | seq: {last_event['sequence_number']:4}"
    )

print("\nLast 5 events overall:")
for evt in events[-5:]:
    print(
        f"{evt['ticket_id']:12} | {evt['event_type']:20} | seq: {evt['sequence_number']:4}"
    )
