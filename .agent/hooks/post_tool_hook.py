from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from bus.redact import redact


# Import memory helpers
try:
    from memory_helpers import append_observation
except ImportError:
    # Fallback if memory_helpers not available
    def append_observation(observation: dict[str, Any]) -> bool:
        return True


# Constants
# WOT-2026-089e: the tool-call trace is TELEMETRY, not a lesson. It used to be
# appended to `memory/observations.jsonl` (the lessons buffer, L1), where it made
# up 97 % of the lines (1705 of 1758 measured 2026-10-01) and was dropped by the
# consolidation as noise anyway. It now has its own gitignored sink; the format,
# the redaction and the append-only behaviour are unchanged.
TELEMETRY_DIR = Path(".agent/runtime/telemetry")
TELEMETRY_FILE = TELEMETRY_DIR / "tool_usage.jsonl"

# Global counter for tool calls
_tool_call_counter = 0


def reset_counter() -> None:
    """Reset the tool call counter."""
    global _tool_call_counter
    _tool_call_counter = 0


def log_observation(context: dict[str, Any]) -> None:
    """Log a tool observation to memory."""
    global _tool_call_counter

    observation = {
        "timestamp": context.get("timestamp", "2026-05-13T23:00:00Z"),
        "topic": "tool_usage",
        "signal": f"Tool {context.get('tool_name', 'unknown')} called",
        "source": "post_tool_hook",
        "tool": context.get("tool_name", "unknown"),
        "context": context.get("context", ""),
        "session_id": context.get("session_id", "unknown"),
        "call_count": _tool_call_counter,
    }

    _tool_call_counter += 1

    # Redact secrets and PII before persisting
    observation["signal"] = redact(observation["signal"])
    observation["context"] = redact(observation["context"])

    # Write directly to the telemetry file (which may be patched in tests)
    with suppress(OSError, json.JSONDecodeError):
        TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TELEMETRY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(observation, ensure_ascii=False) + "\n")


def post_tool_hook(context: dict[str, Any]) -> None:
    """Main post-tool hook function."""
    # Log the tool call
    log_observation(context)

    # Additional processing could go here
    pass
