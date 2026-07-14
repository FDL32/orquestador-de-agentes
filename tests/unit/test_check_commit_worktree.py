"""Tests for scripts/check_commit_worktree.py (WOT-2026-024s).

Every branch that returns 0 needs a mutation that can REACH it (lesson 021u): an
exemption that is dead code passes just as green as one that works. And every
branch that returns 0 is also a way for the guard to LIE, which is what the last
three tests here are about -- they were added after an adversarial audit found
the guard turning "I don't know" into "go ahead":

- `_git_current_branch()` returns None for a detached HEAD *and* for a missing
  git. `_find_dev_worktree()` returns None when no _dev exists *and* when the
  worktree query fails. With git broken, both fired, and the guard waved through
  the exact commit it exists to stop.
- `_dev` itself can be detached (conflicted rebase, bisect). The guard blocked
  that commit and told the user to go commit in _dev -- where they already were.

These tests are hermetic: they drive check() with a synthetic root and a fake
environment, monkeypatching the git helpers. They never consult the real
worktree, so their verdict is decided by the code under test and not by the
state of the developer's disk (the failure mode that WOT-2026-020q taught us).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "check_commit_worktree",
    Path(__file__).resolve().parents[2] / "scripts" / "check_commit_worktree.py",
)
ccw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ccw)


def _motor(tmp_path: Path) -> Path:
    """A directory that looks like the motor (carries MANIFEST.distribute)."""
    (tmp_path / "MANIFEST.distribute").write_text("AGENTS.md\n", encoding="utf-8")
    return tmp_path


def _fake_git(
    monkeypatch,
    *,
    branch: str | None,
    dev: Path | None,
    worktrees: list[Path] | None = None,
) -> None:
    """Fake the three git helpers.

    `worktrees` defaults to a non-empty list: a working `git worktree list` ALWAYS
    names at least the current worktree, so the empty list is not a neutral default
    -- it is the signal that the query failed. Tests that want that must ask for it.
    """
    monkeypatch.setattr(ccw, "_git_current_branch", lambda _root: branch)
    monkeypatch.setattr(ccw, "_find_dev_worktree", lambda _root: dev)
    monkeypatch.setattr(
        ccw,
        "_git_worktree_list",
        lambda root: [root] if worktrees is None else worktrees,
    )


def test_blocks_commit_from_detached_motor_with_dev_worktree(tmp_path, monkeypatch):
    """The incident of 2026-07-14: motor + detached + a _dev worktree exists.

    Mutation: drop the detached check (treat every checkout as on-a-branch) ->
    this test fails. It is the only branch that returns non-zero.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=tmp_path / "motor_dev")

    code, msg = ccw.check(root, env={})

    assert code == 1
    assert "DETACHED" in msg
    assert "_dev" in msg


def test_allows_commit_when_on_a_branch(tmp_path, monkeypatch):
    """_dev itself: motor, but HEAD is on `main`. Commits land somewhere.

    Mutation: make the guard ignore the branch and block on the motor alone ->
    this test fails (and every commit in _dev would be blocked).
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch="main", dev=tmp_path / "motor_dev")

    assert ccw.check(root, env={})[0] == 0


def test_allows_commit_in_a_repo_that_is_not_the_motor(tmp_path, monkeypatch):
    """A destination repo: detached or not, this guard is none of its business.

    Mutation: drop the MANIFEST.distribute check -> this test fails, and the
    guard would start blocking commits in every destination repo.
    """
    root = tmp_path  # no MANIFEST.distribute
    _fake_git(monkeypatch, branch=None, dev=tmp_path / "motor_dev")

    assert ccw.check(root, env={})[0] == 0


def test_allows_detached_commit_when_there_is_no_dev_worktree(tmp_path, monkeypatch):
    """A single-checkout motor: there is nowhere else to commit, so allow it.

    Mutation: drop the _dev lookup -> this test fails, and a perfectly valid
    single-worktree clone could no longer commit at all.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=None)

    assert ccw.check(root, env={})[0] == 0


def test_escape_hatch_allows_but_warns_loudly(tmp_path, monkeypatch):
    """A declared exception passes -- and says so. A silent override becomes a habit.

    Mutation: make the escape hatch return silently -> this test fails on the
    message assertion.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=tmp_path / "motor_dev")

    code, msg = ccw.check(root, env={ccw.ESCAPE_ENV: "1"})

    assert code == 0
    assert "WARNING" in msg
    assert ccw.ESCAPE_ENV in msg


def test_escape_hatch_only_honours_the_exact_value(tmp_path, monkeypatch):
    """A truthy-looking value is not an override: only "1" is.

    Guards against the classic `if env.get(X):` which any non-empty string opens.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=tmp_path / "motor_dev")

    assert ccw.check(root, env={ccw.ESCAPE_ENV: "false"})[0] == 1
    assert ccw.check(root, env={ccw.ESCAPE_ENV: "0"})[0] == 1
    assert ccw.check(root, env={ccw.ESCAPE_ENV: ""})[0] == 1


def test_an_unreadable_worktree_list_fails_closed(tmp_path, monkeypatch):
    """FAIL-OPEN, closed (found by an adversarial audit of this very guard).

    A working `git worktree list` always names at least the current worktree, so an
    empty list can ONLY mean the query failed -- git missing, not a repo, non-zero
    exit. The old code fed that into `_find_dev_worktree() is None -> return 0` and
    waved the commit through: two "I don't know"s cancelling into "go ahead".

    That is not a theoretical hole. With git off the PATH, `_git_current_branch()`
    ALSO returns None, so the guard saw "detached, no _dev" and allowed exactly the
    commit it exists to stop.

    Mutation: go back to trusting `_find_dev_worktree() is None` -> this test fails.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=None, worktrees=[])

    code, msg = ccw.check(root, env={})

    assert code == 2, "no poder determinar la topologia no es permiso para commitear"
    assert "cannot enumerate" in msg


def test_the_escape_hatch_still_works_when_the_topology_is_unreadable(
    tmp_path, monkeypatch
):
    """...but a DECLARED exception must survive the fail-closed, or the rescue path is
    dead exactly when it is needed (a rescue often happens on a broken checkout).

    The falso-rojo twin of the test above. Mutation: fail closed unconditionally,
    ignoring the escape hatch -> this test fails.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=None, worktrees=[])

    assert ccw.check(root, env={ccw.ESCAPE_ENV: "1"})[0] == 0


def test_allows_a_detached_head_inside_dev_itself(tmp_path, monkeypatch):
    """FALSE RED, closed. `_dev` can legitimately be detached: a conflicted rebase, a
    bisect, a checkout of an old SHA.

    The old code saw "motor + detached + a _dev exists" and blocked -- printing "commit
    from the _dev worktree instead" to someone who was already standing in _dev. A guard
    whose error message is impossible to obey teaches people to bypass it.

    Mutation: drop the `dev == root` check -> this test fails.
    """
    root = _motor(tmp_path)
    _fake_git(monkeypatch, branch=None, dev=root, worktrees=[root])

    assert ccw.check(root, env={})[0] == 0
