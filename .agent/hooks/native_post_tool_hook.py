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


def _extract_read_payload(input_data: dict) -> tuple[str, str]:  # noqa: C901
    """Extract file_path and content from a Claude Code PostToolUse payload.

    Real Claude Code sends: {tool_name, tool_input, tool_response, ...}
    - file_path is in tool_input (as "file_path" or "path")
    - content is in tool_response (as string, content-block array, or structured dict)

    The old "result" key was a guess that never arrived in production.
    Returns (file_path, content) — file_path defaults to "unknown".
    """
    file_path = "unknown"
    content = ""

    # 1) Pull file_path from tool_input (the original tool call)
    tool_input = input_data.get("tool_input") or {}
    for _k in ("file_path", "path"):
        _v = tool_input.get(_k)
        if isinstance(_v, str) and _v:
            file_path = _v
            break

    # 2) Pull content from tool_response (the actual tool output)
    tool_response = input_data.get("tool_response")
    if isinstance(tool_response, str):
        content = tool_response
    elif isinstance(tool_response, list):
        # Content-block array: [{type: "text", text: "…"}, ...]
        parts: list[str] = []
        for block in tool_response:
            if isinstance(block, dict):
                txt = block.get("text") or block.get("content", "")
                if isinstance(txt, str):
                    parts.append(txt)
        content = "\n".join(parts) if parts else ""
    elif isinstance(tool_response, dict):
        resp_content = tool_response.get("content")
        if isinstance(resp_content, str):
            content = resp_content
        else:
            # WOT-2026-pendiente (medido 2026-10-15): la forma REAL que este
            # Claude Code envia para Read es {"type": "text", "file":
            # {"filePath": ..., "content": ...}} -- ninguna de las 3 formas
            # anteriores la cubria, por lo que el conteo de lineas salia
            # SIEMPRE "0 lines" (confirmado: 100% de las entradas historicas
            # de tool_usage.jsonl con file_path correcto tenian "0 lines").
            file_block = tool_response.get("file")
            if isinstance(file_block, dict):
                file_content = file_block.get("content")
                if isinstance(file_content, str):
                    content = file_content
                file_path_from_block = file_block.get("filePath")
                if (
                    file_path == "unknown"
                    and isinstance(file_path_from_block, str)
                    and file_path_from_block
                ):
                    file_path = file_path_from_block
            if not content:
                stdout_val = tool_response.get("stdout")
                if isinstance(stdout_val, str):
                    content = stdout_val
                stderr_val = tool_response.get("stderr")
                if isinstance(stderr_val, str):
                    content = content + stderr_val

    return file_path, content


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
        file_path, content = _extract_read_payload(input_data)
        line_count = len(content.splitlines()) if content else 0
        context = f"Read file {file_path}, {line_count} lines"

        # WOT-2026-105a: capture the real offset/limit of the Read call so the
        # gate can union intervals instead of only keeping max(line_count).
        # Empirical verification (2026-10-19): the Kilo Read tool passes
        # `offset` (0-based line index where to start reading) and `limit`
        # (number of lines to return) in `tool_input`.  A call like
        # Read("file.md", offset=100, limit=50) returns lines 100..149,
        # i.e. offset is 0-based inclusive start and limit is a count.
        tool_input = input_data.get("tool_input") or {}
        read_offset: int | None = None
        read_limit: int | None = None
        for key in ("offset", "limit"):
            val = tool_input.get(key)
            if isinstance(val, int) and val >= 0:
                if key == "offset":
                    read_offset = val
                else:
                    read_limit = val

        # Only emit structured fields when offset/limit are valid
        if read_offset is not None and read_limit is not None and read_limit > 0:
            context_data_extra: dict[str, int] = {
                "read_offset": read_offset,
                "read_limit": read_limit,
            }
        else:
            context_data_extra = {}
    else:
        translated_name = tool_name.lower()
        context = f"Executed {tool_name}"
        context_data_extra = {}

    # Create context for post-tool hook
    from datetime import datetime, timezone

    context_data = {
        "tool_name": translated_name,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": input_data.get("session_id", "unknown"),
        "original_input": input_data,
        **context_data_extra,
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
