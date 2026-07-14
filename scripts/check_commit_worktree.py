#!/usr/bin/env python3
"""Pre-commit guard: never commit from the motor's DETACHED consumption checkout.

Why this exists (WOT-2026-024s, incident 2026-07-14)
----------------------------------------------------
The motor is consumed through TWO worktrees of the SAME git repo:

    <motor>_dev   -> branch `main`. Development happens HERE.
    <motor>       -> DETACHED. Consumption only. Never commit.

A session was launched with the primary checkout declared as "the motor" (a
natural reading: it is the directory that carries the repo's name). It worked
there, committed there, and its two commits ended up on a detached HEAD --
reachable from NO branch. They were one `sync_principal.py` away from being
garbage-collected. The work was only recovered because someone noticed.

`check_worktree_topology.py` already detects this and is fail-closed (exit 1),
with the right message. It was never RUN: it requires `--ticket` (it routes by
ticket prefix) and lives in the code-only pipeline's preflight, which that
session skipped. And it is wired into ZERO of the pre-commit hooks -- so the
commits sailed through all of them.

This guard closes the last gap: it needs no ticket, and it runs at the moment
of the commit, which is the last point where the mistake is still cheap.

The invariant is simpler and stronger than the ticket-routing one: a detached
consumption checkout is never a place to commit, whatever the ticket is.

Two ways this guard could have lied (both found by an adversarial audit, both closed)
------------------------------------------------------------------------------------
FAIL-OPEN. `_git_current_branch()` returns None when HEAD is detached *and* when
git is missing or the path is not a repo. `_find_dev_worktree()` returns None
when no `_dev` exists *and* when `git worktree list` fails. Those two "I don't
know"s used to cancel out into "go ahead": with git broken, the guard waved
through the exact commit it exists to stop. A guard that turns ignorance into
permission is not fail-closed, whatever its docstring says.

The discriminant is the EMPTY SET: a `git worktree list` that works always names
at least the current worktree. So an empty list can only mean the query failed
-> exit 2, refuse to judge. "No _dev worktree exists" is a real, legitimate shape
(a single-checkout motor); "I could not enumerate the worktrees" is not.

FALSE RED. `_dev` itself can be detached -- a conflicted rebase, a bisect, a
checkout of an old SHA. The guard used to see "motor + detached + a _dev exists"
and block, even when the checkout it was blocking WAS `_dev`, with a message that
told the user to go commit in the very directory they were standing in.

Before: run from a git worktree (pre-commit sets cwd to the repo root).
During: no-ops unless ALL of these hold -- this is the motor (MANIFEST.distribute),
        HEAD is detached, the worktree list is READABLE, a sibling `*_dev` worktree
        exists, and this checkout is NOT that `_dev`. Any other shape (a destination
        repo, a branch checkout, a single-worktree motor, `_dev` mid-rebase) passes.
After:  exit 0 = safe to commit. exit 1 = committing here would strand the work
        on a detached HEAD; commit from the `_dev` worktree instead.
        exit 2 = the topology could not be determined; refusing to judge.

Escape hatch: set ALLOW_DETACHED_MOTOR_COMMIT=1 for a deliberate, declared
exception (e.g. a rescue operation on a temporary worktree). It is loud on
purpose: an override that is silent is an override that becomes a habit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_worktree_topology import (
    _find_dev_worktree,
    _git_current_branch,
    _git_worktree_list,
)


ESCAPE_ENV = "ALLOW_DETACHED_MOTOR_COMMIT"


def is_motor(root: Path) -> bool:
    """The motor is the repo carrying MANIFEST.distribute (same marker the
    installer and the health collector use to identify it)."""
    return (root / "MANIFEST.distribute").exists()


def check(root: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Return (exit_code, message). See module docstring for the invariant."""
    env = os.environ if env is None else env

    if not is_motor(root):
        return 0, ""

    if _git_current_branch(root) is not None:
        # On a branch: commits land somewhere reachable. Fine.
        return 0, ""

    escaped = env.get(ESCAPE_ENV, "").strip() == "1"

    if not _git_worktree_list(root) and not escaped:
        # A working `git worktree list` always names at least the current worktree.
        # Empty means the query FAILED (git missing, not a repo, non-zero exit). We
        # cannot tell a safe checkout from the dangerous one -- so we do not pretend.
        return 2, (
            f"[commit-worktree] ERROR: cannot enumerate this repo's worktrees ({root}).\n"
            "  Without them I cannot tell the motor's DETACHED consumption checkout\n"
            "  from a legitimate one -- and guessing 'safe' is exactly how the incident\n"
            "  this guard exists to stop happened. Refusing to judge.\n"
            "\n"
            f"  Deliberate exception: {ESCAPE_ENV}=1 git commit ..."
        )

    dev = _find_dev_worktree(root)
    if dev is None:
        # No _dev worktree: this checkout is all there is, so a detached commit
        # here is the user's own business (single-checkout setups are valid).
        return 0, ""

    if dev == root:
        # This IS `_dev`, just detached -- a conflicted rebase, a bisect, an old SHA.
        # Not the consumption checkout, so not this guard's business. Blocking here
        # would print "go commit in _dev" to someone already standing in _dev.
        return 0, ""

    if escaped:
        return 0, (
            f"[commit-worktree] WARNING: committing from the DETACHED motor checkout "
            f"({root}) because {ESCAPE_ENV}=1 was set. The commit will NOT be reachable "
            f"from any branch until you point one at it."
        )

    return 1, (
        "[commit-worktree] ERROR: this is the motor's DETACHED consumption checkout.\n"
        f"  here : {root}  (detached HEAD -- commits land on NO branch)\n"
        f"  _dev : {dev}  (branch main -- development belongs HERE)\n"
        "\n"
        "  A commit made here is reachable from no branch and a sync_principal.py\n"
        "  away from being lost. Move your work to the _dev worktree and commit there.\n"
        "\n"
        f"  Deliberate exception (rescue, etc.): {ESCAPE_ENV}=1 git commit ..."
    )


def main(argv: list[str] | None = None) -> int:
    root = Path.cwd().resolve()
    code, message = check(root)
    if message:
        print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
