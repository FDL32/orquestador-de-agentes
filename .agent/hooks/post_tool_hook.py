from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any


# Import memory helpers
try:
    from memory_helpers import append_observation
except ImportError:
    # Fallback if memory_helpers not available
    def append_observation(observation: dict[str, Any]) -> bool:
        return True


# Constants
MEMORY_DIR = Path(".agent/runtime/memory")
OBSERVATIONS_FILE = MEMORY_DIR / "observations.jsonl"

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

    # Write directly to the observations file (which may be patched in tests)
    with suppress(OSError, json.JSONDecodeError):
        OBSERVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OBSERVATIONS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(observation, ensure_ascii=False) + "\n")


def post_tool_hook(context: dict[str, Any]) -> None:
    """Main post-tool hook function."""
    # Log the tool call
    log_observation(context)

    # Additional processing could go here
    pass
