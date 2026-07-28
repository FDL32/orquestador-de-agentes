#!/usr/bin/env python3
"""Guard paths hook - profile-aware security guard for PreToolUse events."""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import suppress
from pathlib import Path


DEFAULT_ALLOWLIST: dict[str, list[str]] = {
    "write_roots": [],
    "blocked_command_patterns": [],
}

SECURITY_LOG_PATH = Path.home() / ".kilo" / "security.log"

PROTECTED_PATH_PATTERNS = (
    r"privada",
    r"secrets?",
    r"credentials?",
    r"(^|/)\.git(/|$)",
    r"\.env",
    r"token",
    r"api[_-]key",
    r"password",
    r"bearer",
    r"auth",
)

PROTECTED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "secrets.json",
    "credentials.json",
}

PROTECTED_COMMAND_REFS = (
    r"\.env",
    r"secrets?",
    r"credentials?",
    r"token",
    r"api[_-]key",
    r"password",
    r"bearer",
    r"auth",
    r"sk-ant",
    r"sk-[a-z]",
)

DANGEROUS_COMMAND_PATTERNS = (
    r"rm\s+-rf\s+/",
    r"git\s+push\s+--force",
    r"git\s+reset\s+--hard",
    r"dd\s+if=",
    r"mkfs",
    r"fdisk",
    r"format",
    r"del\s+/f\s+/s\s+/q",
)


def _log_security_event(event_type: str, path: str, reason: str) -> None:
    """Log a security event to the security log file."""
    with suppress(OSError):
        SECURITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SECURITY_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{event_type}: {path} - {reason}\n")


def _normalize(path: str) -> str:
    """Normalize path to lowercase with forward slashes."""
    return path.replace("\\", "/").lower()


def _read_json(path: Path) -> dict[str, object]:
    """Read and parse JSON file, returning empty dict on error."""
    with suppress(OSError, json.JSONDecodeError):
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _tool_paths(tool_call: dict[str, object]) -> list[str]:
    """Extract file paths from a tool call."""
    paths = []
    for key, value in tool_call.items():
        if (
            key in ("file_path", "path", "target_path", "new_path")
            and isinstance(value, str)
            and value
        ):
            paths.append(value)
    return paths


def _is_within_repo(path_obj: Path, repo_root: Path) -> bool:
    try:
        path_obj.relative_to(repo_root)
        return True
    except ValueError:
        return False


def _has_repo_marker(candidate: Path) -> bool:
    """Check if a directory has a repo marker (``.claude`` or ``.git``).

    Same fail-closed criterion as ``resolve_repo_root`` in
    ``claude_guard_entry.py`` uses ``.claude`` for the first root; ``.git``
    covers repos without ``.claude`` (e.g. Codex/OpenCode backends).
    """
    return (candidate / ".claude").exists() or (candidate / ".git").exists()


def _resolve_destino_from_target(path_obj: Path, repo_root: Path) -> Path | None:
    """WOT-2026-020a: resolve a destino root from the target path's ancestors.

    Walks the target's ancestors looking for a ``motor_destination_link.json``
    whose ``motor_root`` resolves to ``repo_root`` -- the real topology where
    the link lives in the destino, not the motor. Fail-closed when the link is
    missing, malformed, points to a different motor, or the ancestor lacks a
    repo marker.
    """
    for ancestor in [path_obj, *path_obj.parents]:
        link = ancestor / ".agent" / "config" / "motor_destination_link.json"
        if not link.exists():
            continue
        try:
            motor_root_value = json.loads(link.read_text(encoding="utf-8"))[
                "motor_root"
            ]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None
        try:
            linked_motor = Path(motor_root_value).resolve()
        except (OSError, ValueError):
            return None
        if linked_motor == repo_root and _has_repo_marker(ancestor):
            return ancestor
        return None
    return None


def _read_gitdir_pointer(
    git_marker: Path, anchor: Path, *, require_prefix: bool = True
) -> Path | None:
    """Parse a git pointer file, anchoring relative targets on ``anchor``.

    Before: ``git_marker`` is a git pointer FILE. The two pointer files of a
    worktree use DIFFERENT formats, verified on the real machine (2026-07-28):
    the worktree's own ``.git`` is ``gitdir: <path>``, while the registry's
    ``gitdir`` back-pointer is a BARE path with no prefix. ``require_prefix``
    selects the format; a fixture that writes the prefix on BOTH goes green
    without reproducing the machine.
    During: reads the file as UTF-8, takes the first non-empty line, strips the
    ``gitdir: `` prefix when required, and anchors relative targets on
    ``anchor`` (``git worktree add --relative-paths``, git 2.53, writes both
    pointers relative).
    After: returns the resolved target ``Path``; returns ``None`` on any I/O,
    Unicode, parse or resolution error -- fail-closed, never raises.
    """
    try:
        raw = git_marker.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    target = ""
    for line in raw.splitlines():
        if line.strip():
            target = line.strip()
            break
    if require_prefix:
        if not target.startswith("gitdir: "):
            return None
        target = target[len("gitdir: ") :].strip()
    elif target.startswith("gitdir:"):
        # Fail-closed: the back-pointer format is a BARE path. A prefixed value
        # here is malformed, not a lenient alternative.
        return None
    if not target:
        return None
    try:
        candidate = Path(target)
        if not candidate.is_absolute():
            candidate = anchor / candidate
        return candidate.resolve()
    except (OSError, ValueError):
        return None


def _resolve_motor_worktree(repo_root: Path, path_obj: Path) -> Path | None:
    """WOT-2026-042p Source 4: accept a worktree of the SAME repo as ``repo_root``.

    Before: ``path_obj`` is a target outside ``repo_root``; ``repo_root`` is the
    session root (itself possibly a worktree, e.g. the ``_dev`` motor worktree,
    whose ``.git`` is a FILE, while the canonical checkout's ``.git`` is a DIR).
    During: walks the target's ancestors and, for each candidate root, validates
    a full two-way binding WITHOUT invoking git (``guard_paths`` has zero
    ``subprocess`` usage; adding it would be a regression on a security
    surface): the candidate's ``.git`` must be a FILE pointing at
    ``<session_common>/worktrees/<name>``, that registry directory must exist,
    and its ``gitdir`` back-pointer must point back at the candidate's own
    ``.git``. Requiring ``gd.parent.name == "worktrees"`` plus
    ``gd.parent.parent == session_common`` rejects a NESTED fabricated registry
    (``worktrees/<real>/worktrees/pwned``), which a mere ``"worktrees" in
    gd.parts`` test accepts.
    After: returns the resolved candidate root, or ``None`` for an unrelated
    repo, a fabricated registry, a registry impersonating a real worktree name,
    a candidate whose ``.git`` is a DIRECTORY (the canonical checkout, which
    reaches the guard via ``_is_within_repo`` instead), or any I/O, Unicode,
    parse or resolution error -- fail-closed, never raises.
    """
    session_common = _resolve_git_common_dir(repo_root)
    if session_common is None:
        return None

    for candidate in [path_obj, *path_obj.parents]:
        if (candidate / ".git").is_file():
            # Only the NEAREST candidate carrying a worktree pointer is
            # considered: if it fails validation, do not keep walking up
            # looking for a permissive ancestor (fail-closed).
            return _validate_worktree_binding(candidate, session_common)
    return None


def _validate_worktree_binding(candidate: Path, session_common: Path) -> Path | None:
    """Validate the two-way ``.git`` binding of a single worktree candidate.

    Before: ``candidate/.git`` is a FILE; ``session_common`` is the resolved
    common dir of the session root.
    During: applies the hardened filters -- registry must be a DIRECT child of
    ``<session_common>/worktrees``, must exist as a directory, and its
    ``gitdir`` back-pointer (a BARE path) must resolve to ``candidate/.git``.
    After: returns ``candidate.resolve()`` when every filter passes, else
    ``None`` -- fail-closed, never raises.
    """
    git_marker = candidate / ".git"
    gd = _read_gitdir_pointer(git_marker, candidate)
    if gd is None or gd.parent.name != "worktrees" or not gd.is_dir():
        return None
    back_pointer_file = gd / "gitdir"
    if not back_pointer_file.is_file():
        return None
    back_pointer = _read_gitdir_pointer(back_pointer_file, gd, require_prefix=False)
    if back_pointer is None:
        return None
    try:
        if gd.parent.parent.resolve() != session_common:
            return None
        if back_pointer != git_marker.resolve():
            return None
        return candidate.resolve()
    except (OSError, ValueError):
        return None


def _resolve_git_common_dir(root: Path) -> Path | None:
    """Resolve the shared ``.git`` common dir of ``root``, without invoking git.

    Before: ``root`` is a repo root whose ``.git`` may be a DIRECTORY (canonical
    checkout) or a FILE (a worktree, e.g. the ``_dev`` motor worktree).
    During: a ``.git`` directory IS the common dir; a ``.git`` file points at
    ``<common>/worktrees/<name>``, so the common dir is its grandparent.
    After: returns the resolved common dir, or ``None`` on a missing marker,
    a malformed pointer or any resolution error -- fail-closed, never raises.
    """
    git_marker = root / ".git"
    if git_marker.is_dir():
        try:
            return git_marker.resolve()
        except (OSError, ValueError):
            return None
    if git_marker.is_file():
        gd = _read_gitdir_pointer(git_marker, root)
        if gd is None or gd.parent.name != "worktrees":
            return None
        try:
            return gd.parent.parent.resolve()
        except (OSError, ValueError):
            return None
    return None


def _resolve_extra_root(repo_root: Path, path_obj: Path | None = None) -> Path | None:
    """Resolve a second valid root beyond ``repo_root``.

    Source 1: ``AGENT_PROJECT_ROOT`` env var (already-official orchestrator
    project root, set by entry points after parsing ``--project-root``).
    Source 2 (fallback, only if source 1 is unset/empty): ``destination_root``
    from ``<repo_root>/.agent/config/motor_destination_link.json`` -- same
    fail-safe read pattern as ``resolve_guard_paths`` in
    ``claude_guard_entry.py`` and ``motor_checkpoint.py::resolve_destino_root``.
    Source 3 (WOT-2026-020a, fallback after source 2): walk the target path's
    ancestors looking for a ``motor_destination_link.json`` whose ``motor_root``
    resolves to ``repo_root`` -- the real topology where the link lives in the
    destino, not the motor. Fail-closed when the link is missing, malformed,
    points to a different motor, or the ancestor lacks a repo marker.
    Source 4 (WOT-2026-042p, fallback after source 3): a git worktree of the
    SAME repo as ``repo_root``, validated by a two-way ``.git`` binding read
    from disk without invoking git -- see ``_resolve_motor_worktree``. Unblocks
    flights declaring ``worktree_isolation.required``, which previously died on
    their first write and could only proceed by abusing ``AGENT_PROJECT_ROOT``
    (documented motor-wide for the repo_destino, not for a motor worktree).

    Returns ``None`` (fail-safe, never raises) when no source resolves,
    when the resolved value is malformed, when the resolved path does not
    exist on disk, or when the path lacks a repo marker (``.claude``/``.git``)
    -- WOT-2026-019h: fail-closed against arbitrary dirs widening the write
    surface beyond a known repo.
    """
    env_value = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if env_value:
        try:
            candidate = Path(env_value).resolve()
        except (OSError, ValueError):
            return None
        if candidate.exists() and _has_repo_marker(candidate):
            return candidate
        return None

    link = repo_root / ".agent" / "config" / "motor_destination_link.json"
    try:
        destination_root = json.loads(link.read_text(encoding="utf-8"))[
            "destination_root"
        ]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        destination_root = None
    if isinstance(destination_root, str) and destination_root.strip():
        try:
            candidate = Path(destination_root).resolve()
        except (OSError, ValueError):
            candidate = None
        if candidate is not None and candidate.exists() and _has_repo_marker(candidate):
            return candidate

    if path_obj is not None:
        destino = _resolve_destino_from_target(path_obj, repo_root)
        if destino is not None:
            return destino
        return _resolve_motor_worktree(repo_root, path_obj)

    return None


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def _is_allowed_write_root(
    path_obj: Path, repo_root: Path, write_roots: list[str]
) -> bool:
    return any(path_obj.is_relative_to(repo_root / root) for root in write_roots)


def _is_protected_path(
    path: str,
    allowlist: dict[str, list[str]],
    config: dict[str, object],
    repo_root: Path | None = None,
) -> tuple[bool, str]:
    """Check if a path is protected and should be blocked."""
    try:
        path_obj = Path(path).resolve()
    except (OSError, ValueError) as e:
        return True, f"path invalido: {e}"

    if repo_root is None:
        try:
            repo_root = Path(os.getcwd()).resolve()
        except (OSError, ValueError):
            return True, "directorio actual no accesible"
    else:
        try:
            repo_root = repo_root.resolve()
        except (OSError, ValueError):
            return True, "directorio actual no accesible"

    effective_root = repo_root
    if not _is_within_repo(path_obj, repo_root):
        extra_root = _resolve_extra_root(repo_root, path_obj)
        if extra_root is None or not _is_within_repo(path_obj, extra_root):
            return True, "fuera del repo"
        effective_root = extra_root

    filename = path_obj.name.lower()
    if filename in PROTECTED_FILENAMES:
        return True, f"archivo protegido: {filename}"

    path_str = _normalize(str(path_obj))
    pattern = _matches_any_pattern(path_str, PROTECTED_PATH_PATTERNS)
    if pattern:
        return True, f"ruta protegida por patron: {pattern}"

    write_roots = allowlist.get("write_roots", [])
    if write_roots and not _is_allowed_write_root(
        path_obj, effective_root, write_roots
    ):
        return True, f"fuera de write_roots permitidos: {write_roots}"

    return False, ""


def _is_blocked_command(command: str, config: dict[str, object]) -> tuple[bool, str]:
    """Check if a command is blocked."""
    if not command or not isinstance(command, str):
        return True, "comando vacio o invalido"

    if re.search(r"\.\./|\.\.\\", command):
        return True, "path traversal detectado"

    ref = _matches_any_pattern(command, PROTECTED_COMMAND_REFS)
    if ref:
        return True, f"referencia a datos sensibles: {ref}"

    pattern = _matches_any_pattern(command, DANGEROUS_COMMAND_PATTERNS)
    if pattern:
        return True, f"comando destructivo bloqueado: {pattern}"

    blocked_patterns = config.get("blocked_command_patterns", [])
    if isinstance(blocked_patterns, list):
        for pattern in blocked_patterns:
            if isinstance(pattern, str) and re.search(pattern, command):
                return True, f"comando bloqueado por configuracion: {pattern}"

    return False, ""


def evaluate_tool_request(
    data: dict[str, object],
    config: dict[str, object],
    repo_root: Path | None = None,
) -> tuple[int, str | None]:
    """Evaluate a PreToolUse payload in-process."""
    profile_name = config.get("strictness_profile")
    profiles = config.get("profiles")

    if profile_name is not None and profiles is not None:
        profile_config = profiles.get(profile_name)
        if not isinstance(profile_config, dict):
            return (
                2,
                f"guard_paths: perfil '{profile_name}' no encontrado en profiles - config invalida",
            )
    else:
        profile_config = {}

    allowlist = {
        "write_roots": profile_config.get("write_roots", []),
        "blocked_command_patterns": profile_config.get("blocked_command_patterns", []),
    }

    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        for path in _tool_paths(tool_input):
            blocked, reason = _is_protected_path(
                path, allowlist, config, repo_root=repo_root
            )
            if blocked:
                return 2, f"guard_paths: {reason}"

        command = tool_input.get("command", "")
        if command:
            blocked, reason = _is_blocked_command(command, allowlist)
            if blocked:
                return 2, f"guard_paths: {reason}"

    return 0, None


if __name__ == "__main__":
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        data = {}

    _config_override = os.environ.get("GUARD_PATHS_CONFIG")
    config_path = (
        Path(_config_override)
        if _config_override
        else Path(__file__).resolve().parent.parent / "config" / "agents.json"
    )
    config = _read_json(config_path)

    exit_code, reason = evaluate_tool_request(data, config, repo_root=Path.cwd())
    if exit_code != 0 and reason:
        print(reason, file=sys.stderr)
    sys.exit(exit_code)
