"""Portability/security gate for a tracked .claude/settings.json (WOT-2026-003c).

Invariants enforced on a *tracked* (versioned) Claude settings file:

1. No personal permission grants. ``permissions.allow`` is operator config and
   must live in the gitignored ``settings.local.json``, never in the tracked
   file (otherwise paths/domains/broad grants propagate to every clone).

2. A write guard MUST exist. There has to be a PreToolUse hook whose matcher
   covers Write, Edit AND MultiEdit. A *deleted* guard is as unsafe as a
   fail-open one, so an absent/partial hook is a violation.

3. The hook command must be the canonical entrypoint bootstrap
   (``claude_guard_entry.canonical_hook_command()``) -- nothing else. This is a
   STATIC check: the gate never executes the (potentially arbitrary) command
   string from the file it audits.

4. The canonical entrypoint itself must FAIL CLOSED. ``claude_guard_entry.py``
   (a trusted, versioned script) is executed in an isolated sandbox with no
   resolvable guard and must exit non-zero -- catching a fail-open regression
   in the entrypoint without ever running an untrusted settings command.

Before: a path to a ``.claude/settings.json`` (or a dir/repo-root with one).
During: parses JSON; static checks; one subprocess of the *trusted* entrypoint.
After: prints violations and returns exit code 0 (clean) or 1 (violations).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENTRYPOINT = _PROJECT_ROOT / ".agent" / "hooks" / "claude_guard_entry.py"

# Import the canonical entrypoint module (single source of truth for the
# allowed hook command).
sys.path.insert(0, str(_PROJECT_ROOT / ".agent" / "hooks"))
import claude_guard_entry  # noqa: E402


_GATING_TOKENS = ("Write", "Edit", "MultiEdit")
_BENIGN_PAYLOAD = b'{"tool_name":"Write","tool_input":{"file_path":"x.txt"}}'


def check_no_personal_grants(settings: dict) -> list[str]:
    """Violations if the tracked settings hold personal permission grants."""
    violations: list[str] = []
    allow = settings.get("permissions", {}).get("allow") or []
    if allow:
        violations.append(
            "permissions.allow present in tracked settings "
            f"({len(allow)} grant(s)); move operator grants to the gitignored "
            "settings.local.json. Offending: " + ", ".join(map(str, allow[:5]))
        )
    return violations


def _gating_entries(settings: dict) -> list[dict]:
    """PreToolUse entries whose matcher references a write tool."""
    return [
        entry
        for entry in settings.get("hooks", {}).get("PreToolUse", [])
        if any(tok in entry.get("matcher", "") for tok in _GATING_TOKENS)
    ]


def check_write_guard_present(settings: dict) -> list[str]:
    """Require a PreToolUse hook covering Write, Edit AND MultiEdit.

    An absent or partial write guard is a violation: a deleted barrier is as
    dead as a fail-open one.
    """
    entries = _gating_entries(settings)
    if not entries:
        return [
            "no PreToolUse hook gates writes; a tracked settings.json must keep a "
            "Write|Edit|MultiEdit guard (a deleted guard is as unsafe as fail-open)"
        ]
    covered: set[str] = set()
    for entry in entries:
        matcher = entry.get("matcher", "")
        covered |= {tok for tok in _GATING_TOKENS if tok in matcher}
    missing = [tok for tok in _GATING_TOKENS if tok not in covered]
    if missing:
        return [f"write-guard matcher does not cover: {', '.join(missing)}"]
    return []


def check_command_is_canonical(settings: dict) -> list[str]:
    """Each write-gating hook command must equal the canonical entrypoint bootstrap.

    Static check: rejects arbitrary commands in tracked settings without ever
    executing them.
    """
    canonical = claude_guard_entry.canonical_hook_command()
    non_canonical = any(
        hook.get("type") == "command" and hook.get("command") != canonical
        for entry in _gating_entries(settings)
        for hook in entry.get("hooks", [])
    )
    if non_canonical:
        return [
            "write-gating hook command is not the canonical claude_guard_entry "
            "bootstrap; arbitrary commands in a tracked settings.json are rejected"
        ]
    return []


def check_entrypoint_fails_closed() -> list[str]:
    """The canonical entrypoint must exit non-zero with no resolvable guard."""
    if not _ENTRYPOINT.exists():
        return [f"canonical entrypoint missing: {_ENTRYPOINT}"]
    with tempfile.TemporaryDirectory(prefix="claude_guard_gate_") as sandbox:
        # Mark the sandbox itself as a repo root (a .claude with NO guard/link)
        # so the entrypoint resolves repo_root HERE and finds no guard --
        # robust regardless of where the system temp dir lives (e.g. a hermetic
        # test env whose TMP is inside a real repo).
        (Path(sandbox) / ".claude").mkdir()
        try:
            # Trusted: runs the repo's own canonical entrypoint (no shell, no
            # settings-supplied string) to verify it fails closed.
            result = subprocess.run(  # noqa: S603
                [sys.executable, str(_ENTRYPOINT), sandbox],
                input=_BENIGN_PAYLOAD,
                cwd=sandbox,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ["canonical entrypoint timed out; cannot confirm fail-closed"]
    if result.returncode == 0:
        return [
            "canonical entrypoint exited 0 with no resolvable guard "
            "(fail-open regression in claude_guard_entry.py)"
        ]
    return []


def check_settings_file(path: Path) -> list[str]:
    """Check one settings.json file. Returns violations (empty if clean)."""
    if not path.exists():
        return []  # nothing tracked to check
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path}: cannot parse settings JSON ({exc})"]
    return (
        check_no_personal_grants(settings)
        + check_write_guard_present(settings)
        + check_command_is_canonical(settings)
        + check_entrypoint_fails_closed()
    )


def _resolve_settings_path(arg: str | None) -> Path:
    """Resolve the settings.json path from an optional file/dir argument."""
    if arg is None:
        return Path(".claude/settings.json")
    p = Path(arg)
    if p.is_dir():
        return p / ".claude" / "settings.json"
    return p


def _discover_destinations(motor_root: Path) -> list[Path]:
    """Find destination repos under parent(motor_root) that have motor_destination_link.json."""
    destinations: list[Path] = []
    parent = motor_root.parent
    if not parent.is_dir():
        return destinations
    for child in sorted(parent.iterdir()):
        if not child.is_dir():
            continue
        link = child / ".agent" / "config" / "motor_destination_link.json"
        if not link.exists():
            continue
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
            dest_root = data.get("destination_root")
            if dest_root:
                p = Path(dest_root)
                if p.is_dir():
                    destinations.append(p)
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return destinations


def check_hook_file_exists(dest_root: Path) -> list[str]:
    """Verify the hook file referenced by the canonical command exists for this destination.

    The canonical command resolves claude_guard_entry.py via:
    1. dest_root/.agent/hooks/claude_guard_entry.py (local)
    2. motor_root via motor_destination_link.json (remote)
    If neither exists, the entrypoint exits 2 (fail-closed), but the operator
    should know the hook file is missing so they can fix it.
    """
    local = dest_root / ".agent" / "hooks" / "claude_guard_entry.py"
    if local.exists():
        return []
    link = dest_root / ".agent" / "config" / "motor_destination_link.json"
    if link.exists():
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
            motor_root = data.get("motor_root")
            if motor_root:
                motor_hook = (
                    Path(motor_root) / ".agent" / "hooks" / "claude_guard_entry.py"
                )
                if motor_hook.exists():
                    return []
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return [
        "claude_guard_entry.py not found locally nor via motor_destination_link.json; "
        "write guard will fail-closed (exit 2) but the hook file is missing"
    ]


def fleet_check(
    motor_root: Path,
) -> tuple[list[tuple[str, str]], list[str], list[tuple[str, str]]]:
    """Check all destinations. Returns (violations, sin_settings, missing_hook_files).

    Each violation is (dest_name, message).
    """
    destinations = _discover_destinations(motor_root)
    violations: list[tuple[str, str]] = []
    sin_settings: list[str] = []
    missing_hook: list[tuple[str, str]] = []
    for dest in destinations:
        settings_path = dest / ".claude" / "settings.json"
        if not settings_path.exists():
            sin_settings.append(dest.name)
            continue
        violations.extend(
            (dest.name, msg) for msg in check_settings_file(settings_path)
        )
        missing_hook.extend((dest.name, msg) for msg in check_hook_file_exists(dest))
    return violations, sin_settings, missing_hook


def _report_fleet(
    violations: list[tuple[str, str]],
    sin_settings: list[str],
    missing_hook: list[tuple[str, str]],
) -> int:
    """Print fleet report and return exit code."""
    if violations:
        print("[FLEET] Destinations with VIOLATIONS:")
        for name, msg in violations:
            print(f"  [{name}] {msg}")
    if missing_hook:
        print("[FLEET] Destinations with missing hook file:")
        for name, msg in missing_hook:
            print(f"  [{name}] {msg}")
    if sin_settings:
        print("[FLEET] Destinations WITHOUT .claude/settings.json (no write guard):")
        for name in sin_settings:
            print(f"  [{name}]")
    if not violations and not sin_settings and not missing_hook:
        print("[FLEET] All destinations have valid .claude/settings.json")
    print(
        f"[FLEET] Summary: {len(sin_settings)} without settings, "
        f"{len(violations)} violations, {len(missing_hook)} missing hook files"
    )
    return 1 if violations or sin_settings or missing_hook else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Portability/security gate for tracked .claude/settings.json"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to settings.json or directory containing .claude/settings.json",
    )
    parser.add_argument(
        "--fleet",
        action="store_true",
        help="Check .claude/settings.json across all destination repos under parent(motor_root)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.fleet:
        v, ss, mh = fleet_check(_PROJECT_ROOT)
        return _report_fleet(v, ss, mh)

    path = _resolve_settings_path(args.path)
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
