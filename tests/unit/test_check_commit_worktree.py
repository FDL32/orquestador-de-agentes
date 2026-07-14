"""Tests for scripts/check_commit_worktree.py (WOT-2026-024s).

The guard has FOUR decision branches, and each one needs a mutation that can
REACH it (lesson 021u): not-the-motor, on-a-branch, no-_dev-worktree, and the
escape hatch. A single "it blocks" test would leave three of them unproven --
an exemption that is dead code passes just as green as one that works.

These tests are hermetic: they drive check() with a synthetic root and a fake
environment, monkeypatching the two git helpers. They never consult the real
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


def _fake_git(monkeypatch, *, branch: str | None, dev: Path | None) -> None:
    monkeypatch.setattr(ccw, "_git_current_branch", lambda _root: branch)
    monkeypatch.setattr(ccw, "_find_dev_worktree", lambda _root: dev)


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
