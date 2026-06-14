"""Portability/security gate for tracked .claude/settings.json (WOT-2026-003c).

Two invariants for a *tracked* (versioned) Claude settings file:

1. No personal permission grants. ``permissions.allow`` is operator config and
   must live in the gitignored ``settings.local.json``, never in the tracked
   file (otherwise paths/domains/broad grants propagate to every clone).

2. No fail-open security hooks. A PreToolUse hook that gates Write/Edit/MultiEdit
   must FAIL CLOSED (non-zero exit) when its guard cannot be resolved. A hook
   that falls back to ``sys.exit(0)`` when the guard is missing silently allows
   writes while appearing protected (false green). This is verified
   dynamically: each relevant hook is executed in an isolated temp dir (no
   ``.claude``/link to resolve a guard) with a benign payload; it must exit
   non-zero.

Before: a path to a ``.claude/settings.json`` (or a dir/repo-root containing one).
During: parses JSON; runs each gating hook command in an isolated sandbox.
After: prints violations and returns exit code 0 (clean) or 1 (violations).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


_GATING_TOKENS = ("Write", "Edit", "MultiEdit")
_BENIGN_PAYLOAD = b'{"tool_name":"Write","tool_input":{"file_path":"x.txt"}}'


def check_no_personal_grants(settings: dict) -> list[str]:
    """Return violations if the tracked settings hold personal permission grants.

    Before: ``settings`` is the parsed settings.json dict.
    During: inspects ``permissions.allow``.
    After: returns a list of violation strings (empty if clean).
    """
    violations: list[str] = []
    allow = settings.get("permissions", {}).get("allow") or []
    if allow:
        violations.append(
            "permissions.allow present in tracked settings "
            f"({len(allow)} grant(s)); move operator grants to the gitignored "
            "settings.local.json. Offending: " + ", ".join(map(str, allow[:5]))
        )
    return violations


def _iter_gating_hook_commands(settings: dict):
    """Yield (matcher, command) for PreToolUse command-hooks that gate writes."""
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        matcher = entry.get("matcher", "")
        if not any(tok in matcher for tok in _GATING_TOKENS):
            continue
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command" and hook.get("command"):
                yield matcher, hook["command"]


def check_hooks_fail_closed(settings: dict) -> list[str]:
    """Return violations for any write-gating hook that does NOT fail closed.

    Before: ``settings`` is the parsed settings.json dict.
    During: runs each gating hook command in an isolated temp dir (no resolvable
        guard) with a benign payload; a secure hook must exit non-zero there.
    After: returns a list of violation strings (empty if all fail closed).
    """
    violations: list[str] = []
    for matcher, command in _iter_gating_hook_commands(settings):
        with tempfile.TemporaryDirectory(prefix="claude_hook_gate_") as sandbox:
            try:
                # shell=True is intentional: the gate must execute the hook
                # command exactly as Claude Code runs it (a shell command
                # string), to observe its real fail-open/closed behaviour. The
                # command comes from the repo's own tracked settings.json, run
                # against a benign payload in an isolated sandbox.
                result = subprocess.run(  # noqa: S602
                    command,
                    shell=True,
                    input=_BENIGN_PAYLOAD,
                    cwd=sandbox,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                violations.append(
                    f"hook (matcher={matcher!r}) timed out; cannot confirm fail-closed"
                )
                continue
            if result.returncode == 0:
                violations.append(
                    f"FAIL-OPEN hook (matcher={matcher!r}): exited 0 with no resolvable "
                    "guard; a security hook must fail closed (non-zero) when its guard "
                    "is missing"
                )
    return violations


def check_settings_file(path: Path) -> list[str]:
    """Check one settings.json file. Returns violations (empty if clean)."""
    if not path.exists():
        return []  # nothing tracked to check
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path}: cannot parse settings JSON ({exc})"]
    return check_no_personal_grants(settings) + check_hooks_fail_closed(settings)


def _resolve_settings_path(arg: str | None) -> Path:
    """Resolve the settings.json path from an optional file/dir argument."""
    if arg is None:
        return Path(".claude/settings.json")
    p = Path(arg)
    if p.is_dir():
        return p / ".claude" / "settings.json"
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = _resolve_settings_path(argv[0] if argv else None)
    violations = check_settings_file(path)
    if violations:
        print(f"[check-claude-settings-portability] {path}: NOT portable/secure:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"[check-claude-settings-portability] {path}: OK (portable, fail-closed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
