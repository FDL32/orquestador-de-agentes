"""Canonical Claude PreToolUse guard entrypoint (WOT-2026-003c).

The tracked ``.claude/settings.json`` write-gating hook must invoke EXACTLY
``canonical_hook_command()`` -- a fixed bootstrap that locates this script (the
repo's own copy, or the motor's via ``motor_destination_link.json`` for a
host-extends destino) and runs it with ``cwd=<repo_root>``. Keeping the hook
command fixed lets the portability gate validate it STATICALLY instead of
executing an arbitrary shell string from the very file it audits.

This entrypoint then:
- resolves ``repo_root`` (nearest ``.claude`` ancestor),
- locates the canonical ``guard_paths.py`` (repo-own, or motor via link),
- runs it with ``cwd=repo_root`` so guard_paths evaluates the correct root,
- and FAILS CLOSED (exit 2, actionable message) when the guard cannot be
  resolved -- never a silent ``exit 0`` (no false green).

Before: the hook payload (Claude tool_use JSON) arrives on stdin.
During: pure resolution + a single subprocess to guard_paths; no mutation here.
After: exits with guard_paths' return code, or 2 when the guard is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_FAIL_CLOSED_MSG = (
    "SECURITY HOOK INACTIVE: guard_paths.py could not be resolved "
    "(repo guard or motor link missing); write blocked (fail-closed). "
    "Recovery: run install --sync from repo_motor with --project-root <repo_destino>."
)


def resolve_repo_root(start: str | None = None) -> Path:
    """Nearest ancestor containing ``.claude`` (the project being edited)."""
    base = Path(start or ".").resolve()
    for candidate in [base, *base.parents]:
        if (candidate / ".claude").exists():
            return candidate
    return base


def resolve_guard_paths(repo_root: Path) -> Path | None:
    """Locate the canonical guard_paths.py: repo-own first, then motor via link.

    Returns None (caller fails closed) when neither resolves or the link is
    malformed -- the guard must never be assumed present.
    """
    own = repo_root / ".agent" / "hooks" / "guard_paths.py"
    if own.exists():
        return own
    link = repo_root / ".agent" / "config" / "motor_destination_link.json"
    if link.exists():
        try:
            motor_root = Path(
                json.loads(link.read_text(encoding="utf-8"))["motor_root"]
            )
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None
        cand = motor_root / ".agent" / "hooks" / "guard_paths.py"
        if cand.exists():
            return cand
    return None


def canonical_hook_command() -> str:
    """The exact command a tracked .claude/settings.json hook must use.

    Single source of truth shared by the settings builder and the portability
    gate. A minimal bootstrap that locates this entrypoint (own or via link)
    and runs it with ``cwd=<repo_root>``; fails closed if the entrypoint is not
    found.
    """
    boot = (
        "import sys,json,subprocess; from pathlib import Path; "
        "r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) "
        "if (p/'.claude').exists()),Path('.').resolve()); "
        "e=r/'.agent'/'hooks'/'claude_guard_entry.py'; "
        "l=r/'.agent'/'config'/'motor_destination_link.json'; "
        "e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8'))['motor_root'])"
        "/'.agent'/'hooks'/'claude_guard_entry.py') if l.exists() else e); "
        "sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),"
        "cwd=str(r)).returncode) if e.exists() else "
        "(sys.stderr.write('SECURITY HOOK INACTIVE: claude_guard_entry.py not found; "
        "write blocked (fail-closed).'),sys.exit(2))"
    )
    return 'python -c "' + boot + '"'


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo_root = resolve_repo_root(argv[0] if argv else None)
    data = sys.stdin.buffer.read()
    guard = resolve_guard_paths(repo_root)
    if guard is None:
        sys.stderr.write(_FAIL_CLOSED_MSG)
        return 2
    # Trusted: guard is the canonical guard_paths.py resolved above; no shell.
    return subprocess.run(  # noqa: S603
        [sys.executable, str(guard)], input=data, cwd=str(repo_root)
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
