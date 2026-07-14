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

Before: run from a git worktree (pre-commit sets cwd to the repo root).
During: no-ops unless ALL THREE hold -- this is the motor (MANIFEST.distribute),
        HEAD is detached, and a sibling `*_dev` worktree exists. Any other shape
        (a destination repo, a branch checkout, a single-worktree motor with no
        `_dev`) is legitimate and passes.
After:  exit 0 = safe to commit. exit 1 = committing here would strand the work
        on a detached HEAD; commit from the `_dev` worktree instead.

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

    dev = _find_dev_worktree(root)
    if dev is None:
        # No _dev worktree: this checkout is all there is, so a detached commit
        # here is the user's own business (single-checkout setups are valid).
        return 0, ""

    if env.get(ESCAPE_ENV, "").strip() == "1":
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
