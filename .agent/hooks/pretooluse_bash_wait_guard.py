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
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TIMEOUT_MS_MAX = 300000
TOTAL_SLEEP_MAX_S = 300
# GNU sleep accepts SEVERAL duration operands and sums them (``sleep 2m 9m``
# waits 11 minutes). Capture the whole run of duration operands after each
# ``sleep`` so the total is not silently truncated to the first operand.
_SLEEP_RE = re.compile(r"\bsleep\b((?:\s+[0-9]+(?:\.[0-9]+)?[smhdSMHD]?)+)")
_DURATION_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)([smhdSMHD]?)")
_LOOP_RE = re.compile(r"\b(?:while|until)\b")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
TELEMETRY_FILE = Path(".agent/runtime/telemetry/tool_usage.jsonl")
_detached_call_count = 0
_AMPERSAND_RE = re.compile(r"(?<![&|>])&(?![&>])")


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
    During: scan outside quotes, and for EVERY ``sleep`` sum all of its duration
    operands (GNU sleep sums multiple operands: ``sleep 2m 9m`` waits 660 s).
    After: return a non-negative float; the sum is a conservative per-iteration
    bound for a loop, not an attempt to model shell control flow.
    """
    total = 0.0
    for match in _SLEEP_RE.finditer(_outside_quotes(command)):
        for operand in _DURATION_RE.finditer(match.group(1)):
            total += float(operand.group(1)) * _UNIT_SECONDS[operand.group(2).lower()]
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


def _without_arithmetic(command: str) -> str:
    """Blank balanced shell arithmetic expressions.

    Before: ``command`` is already stripped of quoted shell interiors.
    During: scan from each ``$((`` opener while tracking nested parentheses.
    After: return the text with each arithmetic expression replaced by a single
    space, so operators inside them cannot be mistaken for detached launches.
    Unclosed arithmetic text is blanked through the end conservatively.
    """
    result: list[str] = []
    index = 0
    while index < len(command):
        if command.startswith("$((", index):
            depth = 2
            index += 3
            while index < len(command) and depth:
                if command[index] == "(":
                    depth += 1
                elif command[index] == ")":
                    depth -= 1
                index += 1
            result.append(" ")
            continue
        result.append(command[index])
        index += 1
    return "".join(result)


def _detect_detached_launch(command: str) -> str | None:
    """Detect a detached launch in unquoted shell text.

    Before: ``command`` is the Bash command from a validated tool payload.
    During: remove quoted and arithmetic text, then match one detached-launch
    signal while excluding shell operators and descriptor redirections.
    After: return the stable signal name, or ``None`` when no signal matches.
    Heredocs, comments and backticks are intentionally outside this detector.
    """
    outside = _outside_quotes(command)
    searchable = _without_arithmetic(outside)
    for signal, pattern in (
        ("nohup", re.compile(r"\bnohup\b")),
        ("setsid", re.compile(r"\bsetsid\b")),
        ("disown", re.compile(r"\bdisown\b")),
        ("start /b", re.compile(r"\bstart\s+/b\b", re.IGNORECASE)),
        ("Start-Process", re.compile(r"\bStart-Process\b", re.IGNORECASE)),
    ):
        if pattern.search(searchable):
            return signal
    if _AMPERSAND_RE.search(searchable):
        return "ampersand"
    return None


def _record_detached_launch(data: dict[str, Any], signal: str) -> None:
    """Append one detached-launch usage row, allowing all I/O failures.

    Before: ``data`` is a validated PreToolUse payload and ``signal`` is a
    detector result.
    During: increment the process-local call counter and append the exact
    eight-field telemetry schema to the shared relative sink.
    After: return without raising, including when the sink cannot be written.
    """
    global _detached_call_count
    call_count = _detached_call_count
    _detached_call_count += 1
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": "tool_usage",
        "signal": signal,
        "source": "pretooluse_bash_wait_guard",
        "tool": "Bash",
        "context": f"detached_launch {signal}",
        "session_id": data.get("session_id", "unknown"),
        "call_count": call_count,
    }
    try:
        TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TELEMETRY_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return


def _warn_detached_launch(data: dict[str, Any], signal: str) -> None:
    """Warn about a detached launch without changing the hook decision.

    Before: ``data`` and ``signal`` identify one detected Bash launch.
    During: attempt telemetry and emit one Claude hook-specific JSON object.
    After: return zero-equivalent control even if telemetry or stdout handling
    raises; the warning is deliberately fail-open.
    """
    with suppress(Exception):
        _record_detached_launch(data, signal)
    with suppress(Exception):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": (
                            "no habra notificacion al terminar; usa "
                            "run_in_background o Monitor"
                        ),
                    }
                }
            )
        )


def main(argv: list[str] | None = None) -> int:
    """Decide whether a Bash tool call may wait in the foreground.

    Before: stdin supplies a valid PreToolUse payload with a command string.
    During: allow non-Bash and background calls, fail closed on a ``timeout``
    whose type is not a non-boolean number, reject excessive numeric timeout,
    and reject a foreground while/until whose conservative sleep sum (summing
    every operand of each GNU sleep) exceeds 300s.
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
    if "timeout" in tool_input:
        timeout = tool_input["timeout"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            return _fail(
                "timeout presente con un tipo no numerico (se esperaban "
                "milisegundos enteros): fail-closed"
            )
        if timeout > TIMEOUT_MS_MAX:
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
    with suppress(Exception):
        signal = _detect_detached_launch(command)
        if signal:
            _warn_detached_launch(data, signal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
