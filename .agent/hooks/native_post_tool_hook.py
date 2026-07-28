#!/usr/bin/env python3
"""Native post-tool hook for translating tool calls.

WOT-2026-042d: the payload used to be UNREACHABLE BY CONSTRUCTION. The hook is
launched as ``subprocess.run([sys.executable, str(hook)], input=data)``, so
``sys.path[0]`` is the SCRIPT's dir (``.agent/hooks/``), not ``.agent/``. From
there the ``hooks`` package is invisible, ``ImportError`` fired on EVERY run,
and the ``except`` printed a consolation JSON and returned 0 -- the error branch
was indistinguishable from the success branch. Evidence: of the 73 (motor) / 64
(destino) records in ``observations.jsonl``, ZERO came from this hook; all were
manual promotions (``source: session-close...``).

Fix: put BOTH roots the payload needs on ``sys.path`` -- ``.agent/`` for the
``hooks`` package and the motor root for ``bus`` -- and let a genuine failure
surface instead of being disguised. Measured 2026-07-28: adding only ``.agent/``
moves the failure one layer deeper (``ModuleNotFoundError: No module named
'bus'``, since ``bus/`` lives at the MOTOR ROOT, not under ``.agent/``), which
is why the end-to-end probe -- not just the import probe -- is the real check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# `hooks` lives under `.agent/`; `bus` lives at the motor root (`.agent/`'s
# parent). This script lives in `.agent/hooks/`, so sys.path[0] is neither.
_AGENT_DIR = Path(__file__).resolve().parent.parent
_MOTOR_ROOT = _AGENT_DIR.parent
for _root in (_AGENT_DIR, _MOTOR_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))


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

    # The payload MUST reach post_tool_hook. An ImportError here is a real
    # breakage of the hook chain, not a benign "not installed" case: the module
    # ships in the same tree as this script. Failing loud is the whole point of
    # WOT-2026-042d -- the old `except ImportError: print(...); return` made the
    # error branch indistinguishable from success.
    from hooks.post_tool_hook import post_tool_hook

    post_tool_hook(context_data)

    # Output success
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
