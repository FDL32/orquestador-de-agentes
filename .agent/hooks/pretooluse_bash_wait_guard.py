"""Block unsafe foreground Bash waits.

Before: receive a Claude PreToolUse JSON object on standard input with a
``tool_input.command`` string and optional timeout/background fields.
During: parse the payload fail-closed, inspect unquoted shell text, and apply
the foreground timeout and conservative loop-sleep limits using only stdlib.
After: return zero for an allowed call; exit two with a diagnostic for a
malformed payload or a blocked foreground wait.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


TIMEOUT_MS_MAX = 300000
TOTAL_SLEEP_MAX_S = 300
_SLEEP_RE = re.compile(r"\bsleep\s+([0-9]+(?:\.[0-9]+)?)([smhdSMHD]?)")
_LOOP_RE = re.compile(r"\b(?:while|until)\b")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def _fail(message: str) -> int:
    """Report a fail-closed condition and terminate with status two.

    Before: ``message`` identifies a malformed payload or blocked operation.
    During: write one diagnostic to standard error and raise ``SystemExit``.
    After: direct callers observe exit code two and subprocesses receive it.
    """
    print(f"pretooluse_bash_wait_guard: {message}", file=sys.stderr)
    raise SystemExit(2)


def _outside_quotes(command: str) -> str:
    """Remove single- and double-quoted shell interiors from ``command``.

    Before: ``command`` is a string supplied in the tool payload.
    During: scan characters while tracking shell quote state and preserve only
    unquoted text; escaped double quotes do not close a double-quoted region.
    After: return text suitable for conservative token detection; no I/O occurs.
    """
    result: list[str] = []
    quote: str | None = None
    escaped = False
    for char in command:
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
            continue
        if quote == "'":
            if char == "'":
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        else:
            result.append(char)
    return "".join(result)


def _sleep_total(command: str) -> float:
    """Calculate the conservative total of unquoted sleep durations.

    Before: ``command`` is a shell command string.
    During: scan outside quotes, parse supported sleep units, and sum seconds.
    After: return a non-negative float; the sum is a conservative per-iteration
    bound for a loop, not an attempt to model shell control flow.
    """
    total = 0.0
    for match in _SLEEP_RE.finditer(_outside_quotes(command)):
        total += float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    return total


def _read_payload() -> dict[str, Any]:
    """Read and validate the required payload shape from standard input.

    Before: standard input contains JSON bytes or text from a PreToolUse call.
    During: read the documented stream form, decode JSON, and validate the
    object, tool_input mapping, and non-empty command string.
    After: return the validated top-level dictionary or exit two diagnostically.
    """
    try:
        raw = (
            sys.stdin.buffer.read()
            if hasattr(sys.stdin, "buffer")
            else sys.stdin.read()
        )
        if isinstance(raw, bytes):
            data = json.loads(raw.decode("utf-8"))
        else:
            data = json.loads(raw)
    except Exception as exc:
        return _fail(f"payload JSON ilegible: {exc}")
    if not isinstance(data, dict):
        return _fail("payload JSON no es un objeto dict")
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return _fail("tool_input ausente o no es un dict")
    command = tool_input.get("command")
    if not isinstance(command, str):
        return _fail("tool_input.command ausente o no es str")
    if not command.strip():
        return _fail("tool_input.command vacio tras strip")
    return data


def main(argv: list[str] | None = None) -> int:
    """Decide whether a Bash tool call may wait in the foreground.

    Before: stdin supplies a valid PreToolUse payload with a command string.
    During: allow non-Bash and background calls, reject excessive timeout, and
    reject a foreground while/until whose conservative sleep sum exceeds 300s.
    After: return zero when allowed; fail closed with exit code two otherwise.
    """
    del argv
    data = _read_payload()
    tool_name = data.get("tool_name")
    if isinstance(tool_name, str) and tool_name and tool_name != "Bash":
        return 0
    tool_input = data["tool_input"]
    if tool_input.get("run_in_background") is True:
        return 0
    timeout = tool_input.get("timeout")
    if (
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and timeout > TIMEOUT_MS_MAX
    ):
        return _fail(
            "foreground timeout exceeds limit; set run_in_background=true or "
            "use Monitor"
        )
    command = tool_input["command"]
    outside = _outside_quotes(command)
    if _LOOP_RE.search(outside) and _sleep_total(command) > TOTAL_SLEEP_MAX_S:
        return _fail(
            "foreground loop wait exceeds limit; set run_in_background=true or "
            "use Monitor"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
