#!/usr/bin/env python3
import json
from pathlib import Path

events_path = Path('.agent/runtime/events/events.jsonl')
if events_path.exists():
    lines = events_path.read_text(encoding='utf-8').splitlines()
    print(f"Total events: {len([l for l in lines if l.strip()])}\n")

    for line in lines[-30:]:
        if line.strip():
            try:
                event = json.loads(line)
                if event.get('event_type') in ['TURN_CHANGED', 'REQUEUE_BUILDER']:
                    print(f"seq={event.get('sequence_number')} type={event['event_type']} ticket={event['ticket_id']}")
                    print(f"  actor: {event.get('actor')}")
                    payload = event.get('payload', {})
                    print(f"  payload keys: {list(payload.keys())}")
                    for k, v in payload.items():
                        if isinstance(v, (str, int, bool)):
                            print(f"    {k}: {v}")
                    print()
            except json.JSONDecodeError as e:
                print(f"Error parsing: {e}")
