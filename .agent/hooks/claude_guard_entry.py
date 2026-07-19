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


def _payload_paths(data: bytes) -> list[str]:
    """Extract candidate file paths from a raw PreToolUse payload.

    Mirrors ``guard_paths._tool_paths``'s key criterion (``file_path``,
    ``path``, ``target_path``, ``new_path`` under ``tool_input``) without
    importing ``guard_paths`` -- this runs BEFORE the guard is resolved, so it
    must stay a pure data-shape read, never a security decision. Returns an
    empty list (never raises) on any malformed/missing payload.
    """
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(parsed, dict):
        return []
    tool_input = parsed.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return []
    paths = []
    for key, value in tool_input.items():
        if (
            key in ("file_path", "path", "target_path", "new_path")
            and isinstance(value, str)
            and value
        ):
            paths.append(value)
    return paths


def _linked_root(repo_root: Path) -> Path | None:
    """Resolve the other authorized root linked to ``repo_root``, if any.

    Direction 1 (repo_root is a destino): read its own
    ``motor_destination_link.json`` and return ``motor_root``.
    Direction 2 (repo_root is the motor): the link lives only in a destino,
    never in the motor itself, so walk no further than checking whether the
    caller already knows a destino -- this function only covers direction 1.
    Direction 2 is resolved separately in ``_authorized_roots`` by asking each
    payload path's own ancestors (the same fail-closed pattern as
    ``guard_paths._resolve_destino_from_target``), since the motor has no
    link file to read outward from.

    Returns ``None`` (never raises) when the link is absent or malformed.
    """
    link = repo_root / ".agent" / "config" / "motor_destination_link.json"
    if not link.exists():
        return None
    try:
        motor_root_value = json.loads(link.read_text(encoding="utf-8"))["motor_root"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None
    try:
        return Path(motor_root_value).resolve()
    except (OSError, ValueError):
        return None


def _destino_linked_to_motor(path_obj: Path, motor_root: Path) -> Path | None:
    """WOT-2026-038c: find a destino root, ancestor of ``path_obj``, linked to ``motor_root``.

    Same fail-closed walk as ``guard_paths._resolve_destino_from_target``:
    only an ancestor of the TARGET path that carries a
    ``motor_destination_link.json`` whose ``motor_root`` resolves to this
    motor -- AND that itself has a repo marker (``.claude``/``.git``) -- is
    accepted. A directory with a forged ``.claude``/``.git`` but no matching
    link is rejected; an unrelated link (pointing to a different motor) is
    rejected too. Never returns an unvetted/arbitrary directory.
    """
    for ancestor in [path_obj, *path_obj.parents]:
        link = ancestor / ".agent" / "config" / "motor_destination_link.json"
        if not link.exists():
            continue
        try:
            linked_motor_value = json.loads(link.read_text(encoding="utf-8"))[
                "motor_root"
            ]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None
        try:
            linked_motor = Path(linked_motor_value).resolve()
        except (OSError, ValueError):
            return None
        if linked_motor == motor_root and (
            (ancestor / ".claude").exists() or (ancestor / ".git").exists()
        ):
            return ancestor
        return None
    return None


def _authorized_roots(repo_root: Path, payload_paths: list[str]) -> list[Path]:
    """Build the set of authorized roots for this invocation.

    R1: ``repo_root`` itself (today's only root).
    R2: the linked root in EITHER direction --
        - if ``repo_root`` is a destino, its own link names the motor;
        - if ``repo_root`` is the motor (no link of its own), each payload
          path's ancestors are searched for a destino whose link points back
          at this motor (WOT-2026-038c).
    Only roots with a repo marker and a verifiable link are included --
    never an arbitrary nearest-marker directory (that would let a forged
    ``.claude``/``.git`` widen the write surface).
    """
    roots = [repo_root]
    linked = _linked_root(repo_root)
    if linked is not None and (
        (linked / ".claude").exists() or (linked / ".git").exists()
    ):
        roots.append(linked)
    for raw in payload_paths:
        try:
            candidate_path = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        destino = _destino_linked_to_motor(candidate_path, repo_root)
        if destino is not None and destino not in roots:
            roots.append(destino)
    return roots


def _select_root_for_paths(roots: list[Path], payload_paths: list[str]) -> Path | None:
    """Return the FIRST authorized root that contains ALL payload paths.

    Fail-closed semantics for bulk payloads (WOT-2026-038c): if any path in
    the payload falls outside every authorized root, no single root can
    honestly claim to cover the whole request, so the caller must fall back
    to the original (unauthorized-widening) root and let ``guard_paths``
    reject it. Returns ``None`` when there are no payload paths (nothing to
    resolve) or no root covers all of them.
    """
    if not payload_paths:
        return None
    try:
        resolved = [Path(raw).resolve() for raw in payload_paths]
    except (OSError, ValueError):
        return None
    for root in roots:
        if all(_path_is_within(p, root) for p in resolved):
            return root
    return None


def _path_is_within(path_obj: Path, root: Path) -> bool:
    try:
        path_obj.relative_to(root)
        return True
    except ValueError:
        return False


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

    # WOT-2026-038c: the settings.json boot invokes this with cwd=<cwd-root>
    # and NO argv, so repo_root above reflects only the caller's cwd. When
    # the payload's file_path(s) live in a DIFFERENT but AUTHORIZED root
    # (motor<->destino link), re-target the guard invocation's cwd to that
    # root instead of blocking as "fuera del repo". Fail-closed: if any
    # payload path falls outside every authorized root, keep the original
    # repo_root (guard_paths will correctly reject it).
    payload_paths = _payload_paths(data)
    effective_root = repo_root
    if payload_paths:
        roots = _authorized_roots(repo_root, payload_paths)
        selected = _select_root_for_paths(roots, payload_paths)
        if selected is not None:
            effective_root = selected

    guard = resolve_guard_paths(effective_root)
    if guard is None:
        sys.stderr.write(_FAIL_CLOSED_MSG)
        return 2
    # Trusted: guard is the canonical guard_paths.py resolved above; no shell.
    return subprocess.run(  # noqa: S603
        [sys.executable, str(guard)], input=data, cwd=str(effective_root)
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
