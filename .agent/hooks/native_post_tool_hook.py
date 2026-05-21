#!/usr/bin/env python3
"""Native post-tool hook for translating tool calls."""

from __future__ import annotations

import json
import sys


def main() -> None:
    """Main entry point for the native post-tool hook."""
    try:
        # Read input from stdin
        input_data = json.loads(sys.stdin.read())
    except Exception:
        input_data = {}

    # Translate tool names
    tool_name = input_data.get("tool_name", "")
    if tool_name == "Read":
        translated_name = "view_file"
        file_path = input_data.get("result", {}).get("filePath", "unknown")
        content = input_data.get("result", {}).get("content", "")
        line_count = len(content.splitlines()) if content else 0
        context = f"Read file {file_path}, {line_count} lines"
    else:
        translated_name = tool_name.lower()
        context = f"Executed {tool_name}"

    # Create context for post-tool hook
    from datetime import datetime, timezone

    context_data = {
        "tool_name": translated_name,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": input_data.get("session_id", "unknown"),
        "original_input": input_data,
    }

    # Try to call the post_tool_hook if it exists
    try:
        # Import here to avoid circular imports
        from hooks.post_tool_hook import post_tool_hook

        post_tool_hook(context_data)
    except ImportError:
        # If post_tool_hook doesn't exist, just output the context
        print(json.dumps({"translated": context_data}))
        return

    # Output success
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
