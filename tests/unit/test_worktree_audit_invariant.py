"""Tests for the pre/post audit invariant (WOT-2026-040t, Pieza 4).

Piezas 1-3 make the HANDOFF immutable. They do not close the window in which the
orchestrator itself runs a ~6-minute suite over the live working tree
(``run_pytest_safe`` launches pytest with ``cwd=PROJECT_ROOT``). During that
window a concurrent flight can still stash, reset or checkout underneath the
measurement -- which is exactly what produced the 8-failed contaminated suite on
2026-07-25.

REDESIGNED per Codex (adjudicated in the 1->9->2 loop): this is NOT a lock. A
lock file only works if every actor honours it, and an actor that has never
heard of it writes anyway -- decorative. Instead the invariant DETECTS the
mutation after the fact and INVALIDATES the measurement. It promises detection,
which it can actually deliver, rather than exclusion, which it cannot.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from worktree_audit_invariant import (
    AuditInvariantViolationError,
    capture_state,
    verify_unchanged,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def init_git_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init")
    _git(repo_path, "config", "user.email", "test@example.com")
    _git(repo_path, "config", "user.name", "Test User")
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-m", "Initial commit")


def test_untouched_tree_keeps_the_measurement_valid(tmp_path: Path) -> None:
    """No mutation during the window -> the measurement stands."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    pre = capture_state(repo)
    # ... a suite runs here, changing nothing ...
    verify_unchanged(repo, pre)  # must not raise


def test_a_file_modified_during_the_window_invalidates(tmp_path: Path) -> None:
    """THE core case: the tree moved under the measurement."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    pre = capture_state(repo)

    (repo / "README.md").write_text("# mutated mid-suite\n", encoding="utf-8")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
        assert "status" in str(exc).lower()
    else:
        raise AssertionError("a mid-window modification must invalidate")


def test_a_stash_during_the_window_invalidates(tmp_path: Path) -> None:
    """THE 027h shape: the flight stashes while the orchestrator measures.

    Note the tree is dirty BEFORE and clean AFTER, so a naive "is it clean now?"
    check would report improvement. Only comparing against the pre-state catches
    that the ground moved.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    pre = capture_state(repo)

    _git(repo, "stash", "push", "-m", "flight-verification")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("a mid-window stash must invalidate")


def test_a_commit_during_the_window_invalidates(tmp_path: Path) -> None:
    """HEAD moving mid-measurement invalidates: the result names another commit."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    pre = capture_state(repo)

    (repo / "new.py").write_text("n = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "landed mid-suite")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "HEAD" in str(exc)
    else:
        raise AssertionError("a mid-window commit must invalidate")


def test_stash_that_is_pushed_and_popped_still_invalidates(tmp_path: Path) -> None:
    """The nastiest shape: mutate and restore, so pre and post LOOK identical.

    A flight that stashes and pops back inside the window leaves HEAD, status
    and the stash list exactly as they were -- yet the suite ran against a tree
    that was, for part of the run, missing its work. That is precisely the
    2026-07-25 contaminated run.

    Recording HEAD's reflog length is what makes this detectable; comparing the
    stash LIST alone would silently pass. The stash's own reflog is no help
    either -- measured: ``git stash pop`` deletes ``refs/stash`` when it pops the
    last entry, taking that reflog with it. HEAD's reflog keeps the
    ``reset: moving to HEAD`` entries that stash writes.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    pre = capture_state(repo)

    _git(repo, "stash", "push", "-m", "transient")
    _git(repo, "stash", "pop")

    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError as exc:
        assert "INVALIDADA" in str(exc)
    else:
        raise AssertionError("a push+pop inside the window must still invalidate")


def test_the_invariant_never_mutates_anything(tmp_path: Path) -> None:
    """It DETECTS; it does not exclude, lock, restore or clean up.

    If this ever starts changing the tree it has become concurrency control and
    the hard stop applies.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "work.py").write_text("w = 1\n", encoding="utf-8")

    before = _git(repo, "status", "--porcelain").stdout
    pre = capture_state(repo)
    try:
        verify_unchanged(repo, pre)
    except AuditInvariantViolationError:  # pragma: no cover - must not happen here
        raise AssertionError("no mutation occurred; must not invalidate") from None
    after = _git(repo, "status", "--porcelain").stdout

    assert before == after
    assert not (repo / ".worktree-audit.lock").exists(), "must not create a lock"
