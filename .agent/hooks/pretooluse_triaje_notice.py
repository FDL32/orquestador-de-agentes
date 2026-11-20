"""Emit an informational triaje notice for the active coordinator only.

Before: Claude Code provides a JSON PreToolUse payload and this hook must not
assume topology environment variables exist.
During: the hook discovers the registry from the payload cwd, resolves the
Claude session through a bounded provider-log probe, and applies the complete
coordinator/pattern discriminator.
After: every malformed, unavailable, or non-matching case is silent and
successful; a match prints only additionalContext JSON.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SUPPORTED_TOOLS = {"Agent", "Task", "mcp__t3-code__delegate_task"}
ACTIVE_PREFIX = re.compile(r"^ACTIVA(?:\s|$)")
MCP_LOG_NAME = re.compile(r"events\.mcp-([0-9a-f-]+)\.log$", re.IGNORECASE)


def _find_project_root(cwd: Path) -> Path:
    """Find the nearest project marker from the payload cwd.

    Before: ``cwd`` is the only topology input available to the hook.
    During: parents are inspected for ``.claude``.
    After: the nearest marked directory is returned, or the original cwd.
    """
    try:
        current = cwd.resolve()
        for candidate in (current, *current.parents):
            if (candidate / ".claude").is_dir():
                return candidate
    except (OSError, RuntimeError, ValueError):
        pass
    return cwd


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read one UTF-8-sig JSON object without propagating I/O failures.

    Before: a candidate registry or link may be missing, malformed, or
    inaccessible.
    During: it is decoded with the PowerShell-compatible UTF-8 signature mode.
    After: a dictionary is returned only for valid JSON objects.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _linked_roots(root: Path) -> list[Path]:
    """Resolve project, motor, and destination roots from local topology.

    Before: ``root`` is the project marker found from payload cwd.
    During: a worktree gitdir and any local motor-destination link are read.
    After: roots eligible to contain flight state are returned.
    """
    roots = [root]
    link_paths = [root / ".agent" / "config" / "motor_destination_link.json"]
    git_path = root / ".git"
    try:
        if git_path.is_file():
            first = git_path.read_text(encoding="utf-8").strip()
            if first.lower().startswith("gitdir:"):
                git_dir = Path(first.split(":", 1)[1].strip()).resolve()
                for component in (git_dir, *git_dir.parents):
                    if component.name == ".git":
                        roots.append(component.parent)
                        link_paths.append(
                            component.parent
                            / ".agent"
                            / "config"
                            / "motor_destination_link.json"
                        )
                        break
        elif git_path.is_dir():
            link_paths.append(
                root / ".agent" / "config" / "motor_destination_link.json"
            )
    except (OSError, UnicodeError, RuntimeError, ValueError):
        pass

    for link_path in link_paths:
        link = _read_json(link_path)
        if link is None or not isinstance(link.get("destination_root"), str):
            continue
        try:
            roots.append(Path(link["destination_root"]))
        except (TypeError, ValueError):
            continue
    return roots


def _flight_registries(root: Path) -> set[Path]:
    """Yield flight registries found directly under one candidate root.

    Before: ``root`` may lack the runtime tree entirely or be unreadable.
    During: the ``.agent/runtime/flight/*/session_registry.json`` glob runs
        inside a broad error boundary.
    After: an empty set is returned on any failure, otherwise the matched paths.
    """
    try:
        return set(
            (root / ".agent" / "runtime" / "flight").glob("*/session_registry.json")
        )
    except (OSError, RuntimeError, ValueError):
        return set()


def _registry_candidates(root: Path) -> list[Path]:
    """Collect registry candidates from the project and linked destination.

    Before: ``root`` is resolved from the payload cwd.
    During: local flight registries, a local destination link, and the motor
        link reached through a worktree gitdir are considered.
    After: existing registry paths are returned newest-first, without env-based
        discovery.
    """
    candidates: set[Path] = set()
    for candidate_root in _linked_roots(root):
        candidates.update(_flight_registries(candidate_root))
    return sorted(
        (path for path in candidates if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _load_registry(root: Path) -> dict[str, Any] | None:
    """Load the newest valid session registry for ``root``.

    Before: candidates may include a newer but broken registry.
    During: each candidate is validated for a sessions list of dictionaries.
    After: the first valid registry is returned, otherwise ``None``.
    """
    for path in _registry_candidates(root):
        data = _read_json(path)
        if (
            data is not None
            and isinstance(data.get("sessions"), list)
            and all(isinstance(session, dict) for session in data["sessions"])
        ):
            return data
    return None


def _strings(value: Any) -> Iterator[str]:
    """Yield every string key and value recursively from a tool input.

    Before: tool input can contain nested dictionaries, lists, or scalar data.
    During: dictionary keys and values are traversed recursively.
    After: every encountered string is yielded exactly at its location.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _has_pattern(tool_input: Any) -> bool:
    """Return whether recursive strings contain both required term groups.

    Before: the tool input has already passed the supported-tool gate.
    During: all strings are case-folded and checked for the two lexical groups.
    After: true means one triaje/triage term and one backlog/fichas/tickets term
        were found, regardless of nesting or which string held each term.
    """
    text = "\n".join(_strings(tool_input)).casefold()
    return ("triaj" in text or "triage" in text) and any(
        term in text for term in ("backlog", "fichas", "tickets")
    )


def _session_id(payload: dict[str, Any]) -> str | None:
    """Get the Claude session id, falling back to transcript basename.

    Before: measured payloads normally contain session_id, but older payloads
        may only carry transcript_path.
    During: the basename is stripped of its JSONL suffix when needed.
    After: a non-empty session identifier or ``None`` is returned.
    """
    value = payload.get("session_id")
    if isinstance(value, str) and value:
        return value
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        name = Path(transcript).name
        if name.lower().endswith(".jsonl"):
            name = name[:-6]
        return name or None
    return None


def _thread_for_session(session_id: str) -> str | None:
    """Resolve a session id through a bounded, fragile provider-log probe.

    Before: provider logs are an undocumented T3 source and may change format;
        the bare-UUID match is also ambiguous because foreign UUIDs may be
        quoted in another log's first 8 KB (declared attribution limit: first
        match in mtime order wins, and failure stays silent).
    During: an empty session id is rejected up front, at most the newest 16
        logs are read, only through their first 8192 bytes; a matching
        filename UUID supplies the thread id.
    After: ``mcp:<uuid>`` is returned, or resolution fails silently without a
        wider scan.
    """
    if not session_id:
        return None
    try:
        log_dir = Path.home() / ".t3" / "userdata" / "logs" / "provider"
        logs = sorted(
            log_dir.glob("events.mcp-*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:16]
        needle = session_id.encode("utf-8")
        for path in logs:
            with path.open("rb") as handle:
                if needle not in handle.read(8192):
                    continue
            match = MCP_LOG_NAME.search(path.name)
            if match:
                return "mcp:" + match.group(1)
    except (OSError, UnicodeError, RuntimeError, ValueError):
        pass
    return None


def _same_thread(left: Any, right: str) -> bool:
    """Compare two thread identifiers ignoring one optional mcp prefix.

    Before: registry ids usually carry ``mcp:`` and the log-derived id does too.
    During: exactly one leading ``mcp:`` is stripped from each string side.
    After: true only when both sides are strings equal after normalization.
    """
    if not isinstance(left, str):
        return False
    return left.removeprefix("mcp:") == right.removeprefix("mcp:")


def _should_notice(payload: dict[str, Any]) -> bool:
    """Apply the complete fail-open coordinator and pattern discriminator.

    Before: payload is a dictionary parsed from a PreToolUse event.
    During: supported tool, registry, resolved thread, active coordinator
        session, and recursive two-group pattern are checked in order.
    After: true only for the active registry coordinator; all other paths are
        false without raising.
    """
    if payload.get("tool_name") not in SUPPORTED_TOOLS:
        return False
    if not _has_pattern(payload.get("tool_input")):
        return False
    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value:
        return False
    registry = _load_registry(_find_project_root(Path(cwd_value)))
    session_id = _session_id(payload)
    if registry is None or session_id is None:
        return False
    thread_id = _thread_for_session(session_id)
    active_code = registry.get("orquestador_activo")
    if not isinstance(active_code, str) or thread_id is None:
        return False
    for session in registry["sessions"]:
        if (
            _same_thread(session.get("threadId"), thread_id)
            and session.get("code") == active_code
            and session.get("role") == "orquestadora"
            and isinstance(session.get("status"), str)
            and ACTIVE_PREFIX.match(session["status"])
        ):
            return True
    return False


def _main() -> int:
    """Read one event and emit only the informational context when matched.

    Before: stdin may be malformed or unavailable.
    During: JSON object validation and all hook logic are contained in a broad
        fail-open boundary.
    After: stdout is empty for every non-match; a match emits compact JSON.
    """
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or not _should_notice(payload):
            return 0
        notice = (
            "Aviso informativo WOT-2026-176e: este lanzamiento coincide con una "
            "solicitud de triaje que menciona backlog, fichas o tickets. "
            "La comprobación no bloquea la operación; continúa según el flujo "
            "de la coordinadora activa."
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": notice,
                    }
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(_main())
