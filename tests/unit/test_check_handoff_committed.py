"""Tests for check_handoff_committed.py (WOT-2026-040t, Pieza 1).

The rejector is a MURO: it answers "is this worktree in a state that can be
handed off / audited?" and nothing else. These tests drive it against REAL git
repositories in ``tmp_path`` (no subprocess mocking): the failure modes it
closes (F1/F3/F7) are all about what git actually reports, so a mocked git
would test the mock, not the barrier.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parent.parent.parent / "scripts" / "check_handoff_committed.py"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with an initial commit."""
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init")
    _git(repo_path, "config", "user.email", "test@example.com")
    _git(repo_path, "config", "user.name", "Test User")
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-m", "Initial commit")


def run_check(repo: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the rejector as a subprocess (the way a gate invokes it)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--worktree", str(repo)],
        capture_output=True,
        text=True,
    )


def test_clean_committed_worktree_passes(tmp_path: Path) -> None:
    """A clean worktree whose work is committed is a valid handoff state."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    result = run_check(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "HANDOFF_OK" in result.stdout


def test_dirty_working_tree_is_rejected_naming_files(tmp_path: Path) -> None:
    """Uncommitted modifications reject the handoff AND name the files.

    Naming the files is part of the contract: a rejector that says only "dirty"
    forces the operator to go re-measure, which is the very re-measurement the
    barrier exists to make unnecessary.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("# Modified\n", encoding="utf-8")

    result = run_check(repo)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "HANDOFF_REJECTED" in result.stdout
    assert "README.md" in result.stdout


def test_untracked_file_is_rejected(tmp_path: Path) -> None:
    """Untracked work is limbo work (F7): it must reject, not pass silently."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "new_module.py").write_text("x = 1\n", encoding="utf-8")

    result = run_check(repo)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "new_module.py" in result.stdout


def test_pending_stash_is_rejected_even_with_clean_tree(tmp_path: Path) -> None:
    """THE mutation-critical case (F3): refs/stash is global to the repo.

    A stash pushed by ANOTHER flight is indistinguishable from limbo work of
    this one, and it is invisible in ``git status``. A rejector that only looks
    at the working tree passes this case -- which is exactly the hole that let
    the 027h incident happen.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("# stashed change\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "some-other-flight-verification")

    # Precondition: the working tree is now CLEAN. Only the stash betrays it.
    status = _git(repo, "status", "--porcelain").stdout
    assert status.strip() == "", "test setup: tree should be clean after stash"

    result = run_check(repo)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "HANDOFF_REJECTED" in result.stdout
    assert "stash" in result.stdout.lower()


def test_rejector_never_suggests_a_remedy(tmp_path: Path) -> None:
    """FRONTERA (anti-maker): it REPORTS and REJECTS, never prescribes.

    Suggesting ``git commit``/``git stash drop`` would make the barrier a maker
    and would, in the drop case, propose destroying the only copy of the work.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("# Modified\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "pending")
    (repo / "other.py").write_text("y = 2\n", encoding="utf-8")

    result = run_check(repo)
    combined = (result.stdout + result.stderr).lower()

    assert result.returncode == 1
    for forbidden in ("git commit", "git stash drop", "git add", "git reset"):
        assert forbidden not in combined, f"rejector suggested a remedy: {forbidden}"


def test_reports_the_head_sha_that_must_be_audited(tmp_path: Path) -> None:
    """On pass, the rejector EMITS the SHA (Pieza 2 audits that exact SHA).

    Pieza 2 must not re-read HEAD later: between rejector and auditor HEAD can
    move. The SHA is therefore an output of this barrier, not a lookup.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    expected = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = run_check(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def test_prepush_wiring_is_blocking_and_reports_the_rejection(tmp_path: Path) -> None:
    """The guard is WIRED into the closeout path AND blocks there.

    A guard nobody invokes is a norm, not a barrier (024u). This drives the real
    prepush wrapper against a dirty repo: it must come back failed AND blocking.
    A WARN-only wiring would be the never-blocks-reporter shape (M20) and would
    have let the 027h incident through unchanged.
    """
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    try:
        from prepush_check import run_handoff_committed_check
    finally:
        sys.path.pop(0)

    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "leftover.py").write_text("z = 3\n", encoding="utf-8")

    result = run_handoff_committed_check(motor_root=repo)

    assert result.passed is False
    assert result.is_blocking is True
    assert "leftover.py" in result.output

    # And it passes once the work is anchored to a commit.
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "anchor the work")
    assert run_handoff_committed_check(motor_root=repo).passed is True


def test_non_git_path_fails_closed(tmp_path: Path) -> None:
    """Not a git repo -> cannot prove committed state -> reject (fail-closed)."""
    plain = tmp_path / "plain"
    plain.mkdir()

    result = run_check(plain)

    assert result.returncode != 0
