#!/usr/bin/env python3
"""Guard paths hook - profile-aware security guard for PreToolUse events."""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import suppress
from pathlib import Path


# Constants
DEFAULT_ALLOWLIST: dict[str, list[str]] = {
    "write_roots": [],
    "blocked_command_patterns": [],
}

SECURITY_LOG_PATH = Path.home() / ".kilo" / "security.log"

PROTECTED_PATH_PATTERNS = (
    r"privada",
    r"secrets?",
    r"credentials?",
    r"\.git",
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
    path: str, allowlist: dict[str, list[str]], config: dict[str, object]
) -> tuple[bool, str]:
    """Check if a path is protected and should be blocked.

    Returns (is_blocked, reason) where reason is empty if not blocked.
    """
    try:
        path_obj = Path(path).resolve()
    except (OSError, ValueError) as e:
        return True, f"path invalido: {e}"

    # Get repo root from environment or current working directory
    try:
        repo_root = Path(os.getcwd()).resolve()
    except (OSError, ValueError):
        return True, "directorio actual no accesible"

    # Check if path is outside repo - fail closed
    if not _is_within_repo(path_obj, repo_root):
        return True, "fuera del repo"

    # Check protected patterns - fail closed
    # Special check for protected filenames - fail closed
    filename = path_obj.name.lower()
    if filename in PROTECTED_FILENAMES:
        return True, f"archivo protegido: {filename}"

    path_str = str(path_obj)
    pattern = _matches_any_pattern(path_str, PROTECTED_PATH_PATTERNS)
    if pattern:
        return True, f"ruta protegida por patron: {pattern}"

    # Check write roots if specified - fail closed if no roots configured
    write_roots = allowlist.get("write_roots", [])
    if write_roots and not _is_allowed_write_root(path_obj, repo_root, write_roots):
        return True, f"fuera de write_roots permitidos: {write_roots}"

    return False, ""


def _is_blocked_command(command: str, config: dict[str, object]) -> tuple[bool, str]:
    """Check if a command is blocked.

    Returns (is_blocked, reason) where reason is empty if not blocked.
    """
    if not command or not isinstance(command, str):
        return True, "comando vacio o invalido"

    # Path traversal patterns - fail closed
    if re.search(r"\.\./|\.\.\\", command):
        return True, "path traversal detectado"

    # Protected file references - fail closed
    ref = _matches_any_pattern(command, PROTECTED_COMMAND_REFS)
    if ref:
        return True, f"referencia a datos sensibles: {ref}"

    # Dangerous commands - fail closed
    pattern = _matches_any_pattern(command, DANGEROUS_COMMAND_PATTERNS)
    if pattern:
        return True, f"comando destructivo bloqueado: {pattern}"

    # Custom blocked patterns from config
    blocked_patterns = config.get("blocked_command_patterns", [])
    if isinstance(blocked_patterns, list):
        for pattern in blocked_patterns:
            if isinstance(pattern, str) and re.search(pattern, command):
                return True, f"comando bloqueado por configuracion: {pattern}"

    return False, ""


# Hook logic - read from stdin when called as script
if __name__ == "__main__":
    # Read from stdin
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        data = {}

    # Load agents.json directly (do not import agents_config.py).
    # GUARD_PATHS_CONFIG env var overrides the path — used in tests.
    _config_override = os.environ.get("GUARD_PATHS_CONFIG")
    config_path = (
        Path(_config_override)
        if _config_override
        else Path(__file__).resolve().parent.parent / "config" / "agents.json"
    )
    config = _read_json(config_path)

    # Resolve strictness profile — fail-closed on config corruption.
    # Legacy configs (no strictness_profile / no profiles key) get base protection only.
    # Configs that declare both keys must be internally consistent; mismatch → block.
    profile_name = config.get("strictness_profile")
    profiles = config.get("profiles")

    if profile_name is not None and profiles is not None:
        profile_config = profiles.get(profile_name)
        if not isinstance(profile_config, dict):
            print(
                f"guard_paths: perfil '{profile_name}' no encontrado en profiles — config invalida",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        profile_config = {}

    # Build allowlist from profile
    allowlist = {
        "write_roots": profile_config.get("write_roots", []),
        "blocked_command_patterns": profile_config.get("blocked_command_patterns", []),
    }

    # Claude Code PreToolUse sends: {"tool_name": "...", "tool_input": {...}}
    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        # Check file paths (Write, Edit tools)
        paths = _tool_paths(tool_input)
        for path in paths:
            blocked, reason = _is_protected_path(path, allowlist, config)
            if blocked:
                print(f"guard_paths: {reason}", file=sys.stderr)
                sys.exit(2)

        # Check shell commands (Bash tool sends command inside tool_input)
        command = tool_input.get("command", "")
        if command:
            blocked, reason = _is_blocked_command(command, allowlist)
            if blocked:
                print(f"guard_paths: {reason}", file=sys.stderr)
                sys.exit(2)

    # All checks passed
    sys.exit(0)
