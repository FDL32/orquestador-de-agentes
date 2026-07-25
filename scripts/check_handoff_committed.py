#!/usr/bin/env python3
"""Reject a handoff/audit whose work is not anchored to an immutable commit.

WOT-2026-040t, Pieza 1 -- the core barrier. Closes failure modes F1 (state race),
F3 (global cross-flight stash) and F7 (work in limbo) measured in
``INCIDENT_20260725_worktree_state_race``.

ROOT CAUSE this exists to cut: an auditor that measures a MUTABLE working tree
instead of an IMMUTABLE commit. Three measurements of the same tree contradicted
each other on 2026-07-25 because the flight was stashing while the orchestrator
audited. A commit cannot be stashed out from under an auditor; a working tree
can. So the discipline "commit before handoff" -- until now a NORM that depended
on someone remembering -- becomes a MECHANISM here.

FRONTERA (hard, per the blindado plan): this is a MURO, not a maker.
  * It VERIFIES and REJECTS. It never commits, stashes, drops or resets.
  * It never SUGGESTS a remedy either. Proposing ``git stash drop`` would have
    proposed destroying the only copy of 480 lines of WOT-2026-027h's work on
    the very day this ticket was built. Choosing the remedy is the operator's
    call; this barrier only states the facts that block.
  * It does not manage flight lifecycle. If it starts to, STOP (024u/025c).

STASH POLICY (adjudicated by the 1->9->2 loop): ANY entry in ``git stash list``
blocks. ``refs/stash`` is global to the repository, shared across every worktree,
so a stash pushed by another flight is indistinguishable from limbo work of this
one -- and it is invisible to ``git status``. Being lenient here reopens F3.

Before: ``worktree`` is a path that should be a git working tree containing work
    that is about to be handed off for audit, closeout or push.
During: runs three read-only git queries (``rev-parse``, ``status --porcelain``,
    ``stash list``). No writes, no network, no mutation of any kind.
After: exit 0 and ``HANDOFF_OK`` plus the HEAD SHA on stdout when the state is
    auditable; exit 1 and ``HANDOFF_REJECTED`` plus the blocking facts when it is
    not; exit 2 when the state cannot be determined at all (git missing, path is
    not a repository) -- fail-closed, because an unprovable state is not a
    proven-clean one.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_UNDETERMINED = 2

_GIT_TIMEOUT = 30


class GitUnavailableError(RuntimeError):
    """The worktree's git state could not be read at all."""


class SurfaceAbsentError(RuntimeError):
    """The declared surface is not present (as a file) at the audited SHA.

    Raised as NO AUDITABLE -- deliberately NOT a content verdict. On 2026-07-25
    the sister audit met a stashed tree and correctly refused to judge rather
    than emitting SHIP over the void; this makes that refusal a mechanism.
    """


def _git(worktree: Path, *args: str) -> str:
    """Run a read-only git command in ``worktree`` and return stdout.

    Raises GitUnavailableError when git is absent, times out, or the path is not
    a repository. The caller turns that into a fail-closed exit, never a pass.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, git resolved from PATH
            ["git", *args],  # noqa: S607 - git resolved from PATH by design
            cwd=str(worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GitUnavailableError("git no esta disponible en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitUnavailableError(
            f"git excedio {_GIT_TIMEOUT}s: {' '.join(args)}"
        ) from exc
    except OSError as exc:
        raise GitUnavailableError(
            f"no se pudo ejecutar git en {worktree}: {exc}"
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        first = detail[0] if detail else f"git {' '.join(args)} fallo"
        raise GitUnavailableError(first)
    return proc.stdout


def head_sha(worktree: Path) -> str:
    """Return the exact HEAD SHA that a downstream auditor must audit.

    Pieza 2 consumes THIS value rather than re-reading HEAD: between the rejector
    and the auditor, HEAD can move, and a re-read would silently audit a
    different commit than the one this barrier cleared.
    """
    return _git(worktree, "rev-parse", "HEAD").strip()


def dirty_entries(worktree: Path) -> list[str]:
    """Return ``git status --porcelain`` lines (modified, staged, untracked)."""
    raw = _git(worktree, "status", "--porcelain")
    return [line for line in raw.splitlines() if line.strip()]


def stash_entries(worktree: Path) -> list[str]:
    """Return ``git stash list`` lines. Any entry blocks (see STASH POLICY)."""
    raw = _git(worktree, "stash", "list")
    return [line for line in raw.splitlines() if line.strip()]


def read_surface_at_sha(worktree: Path, sha: str, paths: list[str]) -> dict[str, str]:
    """Read the declared surface FROM A COMMIT, never from the working tree.

    WOT-2026-040t, Pieza 2 -- closes F8 (audit over an unstable tree). The
    auditor's source of truth becomes ``git show <sha>:<path>``: a commit cannot
    be stashed, reset or checked out from under the reader, so the three
    contradictory measurements of 2026-07-25 become unreachable by construction.

    ``sha`` MUST be the SHA that the rejector (Pieza 1) emitted, passed through
    explicitly. This function never resolves HEAD itself: between the rejector
    clearing a state and the auditor reading it, HEAD can advance, and a re-read
    would attach the verdict to a commit nobody cleared.

    Before: ``worktree`` is a git working tree; ``sha`` is a commit-ish that the
        rejector already cleared; ``paths`` are repo-relative surface paths.
    During: one ``git cat-file -t`` (type barrier) plus one ``git show`` per
        path. Read-only; touches no file on disk.
    After: returns ``{path: content}`` for every requested path. Raises
        SurfaceAbsentError (NO AUDITABLE) if any path is missing at that SHA, is
        not a regular file (a directory would otherwise yield a tree listing
        that reads like content), or if the SHA itself cannot be resolved.
        Raises GitUnavailableError if git cannot run at all.
    """
    missing: list[str] = []
    surface: dict[str, str] = {}

    for path in paths:
        spec = f"{sha}:{path}"
        try:
            kind = _git(worktree, "cat-file", "-t", spec).strip()
        except GitUnavailableError:
            missing.append(path)
            continue
        if kind != "blob":
            # A tree (directory) or tag is not an auditable surface file.
            missing.append(path)
            continue
        try:
            surface[path] = _git(worktree, "show", spec)
        except GitUnavailableError:
            missing.append(path)

    if missing:
        raise SurfaceAbsentError(
            "NO AUDITABLE: la superficie declarada no existe como fichero en el "
            f"SHA auditado ({sha}). Ausente(s): {', '.join(sorted(missing))}. "
            "Esto NO es un veredicto de contenido: el estado no es auditable."
        )
    return surface


def evaluate(worktree: Path) -> tuple[int, list[str]]:
    """Decide whether ``worktree`` is in a valid handoff state.

    Before: ``worktree`` is an existing filesystem path.
    During: reads HEAD, working-tree status and the stash list. Read-only.
    After: returns ``(exit_code, report_lines)``. Never raises for an ordinary
        dirty/stashed tree -- that is a verdict, not an error. Undeterminable
        state returns EXIT_UNDETERMINED with the diagnostic.
    """
    try:
        sha = head_sha(worktree)
        dirty = dirty_entries(worktree)
        stashes = stash_entries(worktree)
    except GitUnavailableError as exc:
        return EXIT_UNDETERMINED, [
            "HANDOFF_UNDETERMINED: no se pudo leer el estado git del worktree.",
            f"  worktree: {worktree}",
            f"  motivo: {exc}",
            "  Un estado no demostrable no es un estado limpio: se rechaza.",
        ]

    blockers: list[str] = []
    if dirty:
        blockers.append(
            f"  trabajo sin commitear en el working-tree ({len(dirty)} entrada(s)):"
        )
        blockers.extend(f"    {line}" for line in dirty)
    if stashes:
        blockers.append(
            f"  stash pendiente en el repositorio ({len(stashes)} entrada(s); "
            "refs/stash es GLOBAL a todos los worktrees):"
        )
        blockers.extend(f"    {line}" for line in stashes)

    if blockers:
        return EXIT_REJECTED, [
            "HANDOFF_REJECTED: el trabajo no esta anclado a un commit inmutable.",
            f"  worktree: {worktree}",
            f"  HEAD: {sha}",
            *blockers,
            "  Un auditor que midiera este arbol mediria un estado mutable.",
        ]

    return EXIT_OK, [
        "HANDOFF_OK: el worktree esta limpio y su trabajo esta commiteado.",
        f"  worktree: {worktree}",
        f"  HEAD: {sha}",
        f"  SHA_A_AUDITAR: {sha}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rechaza un handoff/auditoria cuyo trabajo no este commiteado "
            "(WOT-2026-040t). Solo verifica: no commitea, no stashea, no sugiere."
        )
    )
    parser.add_argument(
        "--worktree",
        default=".",
        help="Ruta del working tree a verificar (por defecto: cwd).",
    )
    args = parser.parse_args(argv)

    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        print(
            f"HANDOFF_UNDETERMINED: la ruta no existe o no es un directorio: {worktree}"
        )
        return EXIT_UNDETERMINED

    code, lines = evaluate(worktree)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
