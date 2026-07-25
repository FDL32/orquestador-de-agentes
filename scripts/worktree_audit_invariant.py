#!/usr/bin/env python3
"""Invalidate a measurement taken over a tree that moved underneath it.

WOT-2026-040t, Pieza 4. Piezas 1-3 make the HANDOFF immutable (commit, audit the
SHA, commit even a decision). They do not close the remaining window: the
orchestrator's own closeout suite runs pytest with ``cwd=PROJECT_ROOT`` over the
LIVE working tree, and that run takes minutes (measured 2026-07-25: 371s). A
concurrent flight can stash, reset or checkout inside that window -- which is
exactly how the contaminated ``8 failed / 4899 passed`` run happened.

NOT A LOCK -- redesign adjudicated by Codex in the 1->9->2 loop. A lock file only
works if every actor honours it, and an actor that never heard of it writes
anyway; that is a decorative promise of exclusion. This instead promises
DETECTION, which it can actually keep: snapshot the tree's identity before and
after, and if it differs, the measurement is INVALID -- not a content verdict,
just "this result describes no single state".

The distinction matters for what callers may conclude. An invalidated run is not
a red run: it is a run that must be REPEATED. Reporting it as failure would be as
wrong as reporting it as success.

FRONTERA (hard): two snapshots and a comparison. It never mutates, never
restores, never excludes. If it starts to resemble concurrency control, STOP and
file it (024u/025c).

Before: ``worktree`` is a git working tree about to be measured.
During: three read-only git queries per snapshot (``rev-parse HEAD``, ``status
    --porcelain``, and the stash reflog). No writes of any kind.
After: ``capture_state`` returns an opaque snapshot; ``verify_unchanged`` returns
    None when the state is identical and raises AuditInvariantViolationError
    otherwise. ``GitStateUnavailableError`` propagates when git cannot be read -- an
    unverifiable window is never silently treated as a stable one.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


_GIT_TIMEOUT = 30


class GitStateUnavailableError(RuntimeError):
    """The worktree state could not be read, so stability cannot be proven."""


class AuditInvariantViolationError(RuntimeError):
    """The tree changed during the measurement window: the result is invalid."""


@dataclass(frozen=True)
class WorktreeState:
    """Identity of a working tree at one instant.

    ``head_reflog_len`` rather than the stash LIST is deliberate, and the choice
    was made by measurement, not by reasoning. The list is identical before and
    after a push+pop pair, so a flight that stashes and restores inside the
    window leaves no trace in it -- yet the suite spent part of its run against a
    tree missing that work. The stash's OWN reflog is no better: probing showed
    ``git stash pop`` deletes ``refs/stash`` outright when it pops the last
    entry, taking that reflog with it.

    HEAD's reflog is the durable trace for GIT-MEDIATED mutation. Stash push/pop
    each write a ``reset: moving to HEAD`` entry there, and it is append-only for
    the window's duration. This is precisely the signature the 2026-07-25
    incident recorded ("reflog: 3x reset: moving to HEAD").

    SCOPE, measured -- what this snapshot does NOT see (WOT-2026-040t, found by
    adversarial audit; verified byte-exact, not reasoned):
      * a transient plain-file edit REVERTED to the identical bytes inside the
        window. No git command runs, so HEAD, status and reflog are all
        unchanged and the churn is invisible.
      * dirty -> differently-dirty churn. ``status --porcelain`` prints the same
        ` M file.py` line for content ``v2`` and ``v3``.
    Both are editor-level writes, not the stash/reset/checkout family this is
    built to catch. Stating the limit here rather than implying total coverage:
    a barrier believed to see more than it does is worse than a narrow one, and
    closing these would mean hashing tree content, a different mechanism.
    """

    head: str
    status: str
    head_reflog_len: int


def _git(worktree: Path, *args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, git resolved from PATH
            ["git", *args],  # noqa: S607
            cwd=str(worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GitStateUnavailableError("git no esta disponible en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitStateUnavailableError(f"git excedio {_GIT_TIMEOUT}s") from exc
    except OSError as exc:
        raise GitStateUnavailableError(f"no se pudo ejecutar git: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise GitStateUnavailableError(detail[0] if detail else "git fallo")
    return proc.stdout


def _head_reflog_len(worktree: Path) -> int:
    """Count HEAD reflog entries; 0 when there is no reflog yet."""
    try:
        raw = _git(worktree, "reflog", "show", "HEAD", "--format=%H")
    except GitStateUnavailableError:
        return 0
    return len([line for line in raw.splitlines() if line.strip()])


def capture_state(worktree: Path) -> WorktreeState:
    """Snapshot the tree identity immediately BEFORE a measurement."""
    return WorktreeState(
        head=_git(worktree, "rev-parse", "HEAD").strip(),
        status=_git(worktree, "status", "--porcelain"),
        head_reflog_len=_head_reflog_len(worktree),
    )


def verify_unchanged(worktree: Path, pre: WorktreeState) -> None:
    """Raise if the tree moved since ``pre``; return None if it held still."""
    post = capture_state(worktree)
    if post == pre:
        return

    diffs: list[str] = []
    if post.head != pre.head:
        diffs.append(f"  HEAD: {pre.head} -> {post.head}")
    if post.status != pre.status:
        diffs.append(
            f"  status --porcelain cambio "
            f"({len(pre.status.splitlines())} -> {len(post.status.splitlines())} "
            "entrada(s))"
        )
    if post.head_reflog_len != pre.head_reflog_len:
        diffs.append(
            f"  reflog de HEAD: {pre.head_reflog_len} -> {post.head_reflog_len} "
            "(hubo stash/reset durante la ventana, aunque el estado final "
            "coincida)"
        )

    raise AuditInvariantViolationError(
        "MEDICION INVALIDADA: el arbol cambio durante la ventana de medicion.\n"
        + "\n".join(diffs)
        + "\n  Esto NO es un veredicto de contenido: el resultado no describe "
        "ningun estado unico y debe REPETIRSE sobre un arbol quieto."
    )
