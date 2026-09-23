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

"never excludes" se refiere a exclusion MUTUA (locks): no excluye archivos por
su contenido o politica. Filtrar las salidas del PROPIO medidor, pasadas
explicitamente por el llamador en ``ignore_paths``, no lo es.

Before: ``worktree`` is a git working tree about to be measured.
During: three read-only git queries per snapshot (``rev-parse HEAD``, ``status
    --porcelain -z``, and the stash reflog). No writes of any kind.
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


def _parse_porcelain_z(porcelain_z: str, ignore_paths: frozenset[str]) -> str:
    """Parse ``git status --porcelain -z`` output and reconstruct .status text.

    Entries are NUL-separated. Each entry starts with a 2-char status, then a
    optional space + rename-old path, then NUL. Renames consume two entries:
    status+old_path\\0new_path\\0.

    When *ignore_paths* is non-empty, entries whose path (or both old and new
    for renames) match exactly are dropped. The remaining entries are
    reconstructed to text form ``"{status} {path}\\n"`` joined by ``\\n``.

    When *ignore_paths* is empty, the reconstructed text is byte-identical to
    what ``git status --porcelain`` (without ``-z``) would produce for the same
    tree -- provided there are no paths with spaces/unicode/renames.
    """
    if not porcelain_z:
        return ""

    entries: list[tuple[str, str]] = []  # (status, path)
    raw_entries = porcelain_z.split("\0")
    i = 0
    while i < len(raw_entries):
        entry = raw_entries[i]
        if not entry:
            i += 1
            continue
        if len(entry) >= 3:
            status = entry[:2]
            path = entry[3:] if entry[2] == " " else entry[2:]
            # Handle renames: consume the next entry as the new path
            if status[0] == "R" and i + 1 < len(raw_entries):
                new_path = raw_entries[i + 1]
                if new_path:
                    # For filtering: drop only if BOTH old and new are in ignore_paths
                    if (
                        ignore_paths
                        and path in ignore_paths
                        and new_path in ignore_paths
                    ):
                        i += 2
                        continue
                    entries.append((status, new_path))
                    i += 2
                    continue
                else:
                    i += 1
                    continue
            else:
                if ignore_paths and path in ignore_paths:
                    i += 1
                    continue
                entries.append((status, path))
        i += 1

    # Reconstruct text: "{status} {path}\n" joined by \n, with trailing \n
    if not entries:
        return ""
    lines = [f"{status} {path}" for status, path in entries]
    return "\n".join(lines) + "\n"


def capture_state(
    worktree: Path, *, ignore_paths: frozenset[str] = frozenset()
) -> WorktreeState:
    """Snapshot the tree identity immediately BEFORE a measurement.

    Args:
        worktree: The git working tree to snapshot.
        ignore_paths: Exact relative paths to exclude from the status snapshot.
            Uses NUL-separated porcelain parsing (``--porcelain -z``) so paths
            with spaces/unicode are handled correctly. A rename is filtered
            only when BOTH the old and new paths are in *ignore_paths*.
    """
    return WorktreeState(
        head=_git(worktree, "rev-parse", "HEAD").strip(),
        status=_parse_porcelain_z(
            _git(worktree, "status", "--porcelain", "-z"), ignore_paths
        ),
        head_reflog_len=_head_reflog_len(worktree),
    )


def verify_unchanged(
    worktree: Path, pre: WorktreeState, *, ignore_paths: frozenset[str] = frozenset()
) -> None:
    """Raise if the tree moved since ``pre``; return None if it held still.

    Args:
        worktree: The git working tree to check.
        pre: The pre-snapshot to compare against.
        ignore_paths: Same as ``capture_state``; both pre and post use the
            same set so the comparison is fair.
    """
    post = capture_state(worktree, ignore_paths=ignore_paths)
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
