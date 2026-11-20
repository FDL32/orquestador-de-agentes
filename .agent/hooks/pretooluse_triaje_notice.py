"""Emit an informational notice for inline triaje delegation attempts."""

import json
import os
import re
import sys
from pathlib import Path


TOOLS = {"Agent", "Task", "mcp__t3-code__delegate_task"}
RE_ACTIVE = re.compile(r"^ACTIVA(\s|$)")
NOTICE = (
    "This request appears to be triaje work. The rule requires opening a role=triaje "
    "session with its cell (triador/revisor) before triaging. This notice is "
    "informational only and does not block the call."
)


def _active(status):
    """Apply the canonical active-session predicate.

    Before: ``status`` is an arbitrary registry value.
    During: deliberately copies ``check_cell_conformance.is_activa``'s
        ``^ACTIVA`` word-boundary behavior.
    After: returns true only for ACTIVA followed by whitespace or end of text.
    """
    return bool(RE_ACTIVE.match(str(status or "")))


def _normalize_thread(value):
    """Normalize only the optional mcp thread prefix.

    Before: ``value`` is an environment or registry thread identifier.
    During: removes one leading ``mcp:`` and preserves every other character.
    After: returns a comparable string or an empty string for non-text values.
    """
    if not isinstance(value, str):
        return ""
    return value[4:] if value.startswith("mcp:") else value


def _registry_candidates():
    """Yield registry paths in the required flight/project order.

    Before: environment variables may be absent or malformed.
    During: builds ``FLIGHT_DIR/session_registry.json`` first (yielded without
        an existence check), then every ``AGENT_PROJECT_ROOT/.agent/runtime/
        flight/*/session_registry.json`` match newest-mtime-first, skipping
        duplicates.
    After: yields those candidate paths in order without reading their
        contents; a path that does not exist is harmless because the caller
        treats an unreadable candidate as "no sessions here" and moves on.
    """
    seen = set()
    flight_dir = os.environ.get("FLIGHT_DIR")
    if flight_dir:
        path = Path(flight_dir) / "session_registry.json"
        seen.add(path)
        yield path

    project_root = os.environ.get("AGENT_PROJECT_ROOT")
    if not project_root:
        return
    flight_root = Path(project_root) / ".agent" / "runtime" / "flight"
    try:
        candidates = sorted(
            flight_root.glob("*/session_registry.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except BaseException:
        return
    for path in candidates:
        if path not in seen:
            seen.add(path)
            yield path


def _load_sessions():
    """Load the first valid session registry candidate.

    Before: candidates come from ``FLIGHT_DIR`` then ``AGENT_PROJECT_ROOT``.
    During: reads and validates the ``sessions`` list, trying the next location
        when a candidate is absent or unreadable.
    After: returns a list of session dictionaries or ``None`` on any failure.
    """
    for path in _registry_candidates():
        sessions = _read_sessions(path)
        if sessions is not None:
            return sessions
    return None


def _read_sessions(path):
    """Read and validate one registry path without exposing any failure.

    Before: ``path`` may be missing, malformed, or unreadable.
    During: decodes JSON and accepts only a list of dictionaries.
    After: returns valid sessions or ``None`` for every failure mode.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if isinstance(sessions, list) and all(
            isinstance(item, dict) for item in sessions
        ):
            return sessions
    except BaseException:
        return None
    return None


def _strings(value):
    """Recursively yield every string contained in a JSON-like value.

    Before: ``value`` is any decoded ``tool_input`` structure.
    During: traverses dictionaries, lists, tuples, and scalar values safely.
    After: yields only textual leaves, including values under new keys.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _has_triaje_pattern(tool_input):
    """Check the two required term groups across all nested input strings.

    Before: ``tool_input`` is the event's decoded input object.
    During: case-folds the recursive string stream and searches both groups.
    After: returns true only when a triaj/triage term and a backlog/fichas/tickets
        term are both present.
    """
    text = " ".join(_strings(tool_input)).casefold()
    return bool(
        re.search(r"triaj|triage", text) and re.search(r"backlog|fichas|tickets", text)
    )


def _discriminates(sessions):
    """Apply the two T3 thread discriminator branches.

    Before: ``sessions`` is a validated registry list.
    During: with a tid, matches an active orquestadora; without a tid, requires
        no active triaje session.
    After: returns the informational-notice decision without side effects.
    """
    raw_tid = os.environ.get("T3_THREAD_ID")
    if raw_tid is not None:
        tid = _normalize_thread(raw_tid)
        return any(
            session.get("role") == "orquestadora"
            and _active(session.get("status"))
            and _normalize_thread(session.get("threadId")) == tid
            for session in sessions
        )
    return not any(
        session.get("role") == "triaje" and _active(session.get("status"))
        for session in sessions
    )


def main():
    """Process one PreToolUse event with total fail-open behavior.

    Before: stdin may contain any bytes and the environment may be incomplete.
    During: validates the tool, pattern, registry, and role discriminator.
    After: emits one JSON notice only when every predicate matches; all failures
        return zero with empty output streams.
    """
    try:
        event = json.loads(sys.stdin.buffer.read())
        if not isinstance(event, dict) or event.get("tool_name") not in TOOLS:
            return 0
        if not _has_triaje_pattern(event.get("tool_input")):
            return 0
        sessions = _load_sessions()
        if sessions is None or not _discriminates(sessions):
            return 0
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": NOTICE,
                    }
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
    except BaseException:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(0)
