"""Tests for read_surface_at_sha (WOT-2026-040t, Pieza 2).

Pieza 1 proves a worktree is anchored to a commit and EMITS that SHA. Pieza 2 is
the other half: the auditor must actually READ that SHA, not the working tree.
Reading the tree is what produced three contradictory measurements of the same
"tree" on 2026-07-25 (F8).

These tests use real git repos in tmp_path. The decisive shape is DIVERGENCE:
commit content X, then dirty the same file to Y, and assert the helper returns X.
A helper that quietly read the filesystem would return Y and fail here.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from check_handoff_committed import (
    SurfaceAbsentError,
    read_surface_at_sha,
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


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_reads_committed_content_not_the_dirty_working_tree(tmp_path: Path) -> None:
    """THE test for F8: committed content and working-tree content DIVERGE.

    This is the exact 027h shape -- the auditor looked at a tree that had been
    changed under it. The helper must be immune by construction.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    target = repo / "surface.py"
    target.write_text("VERSION = 'committed'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add surface")
    sha = _head(repo)

    # Now dirty the SAME file, as a concurrent flight would.
    target.write_text("VERSION = 'mutated-under-the-auditor'\n", encoding="utf-8")

    content = read_surface_at_sha(repo, sha, ["surface.py"])

    assert content["surface.py"] == "VERSION = 'committed'\n"
    assert "mutated-under-the-auditor" not in content["surface.py"]
    # And the working tree really did diverge (guards against a vacuous pass).
    assert "mutated" in target.read_text(encoding="utf-8")


def test_reads_content_even_when_the_file_is_deleted_from_the_tree(
    tmp_path: Path,
) -> None:
    """A stash/checkout can remove the file entirely; the SHA still has it.

    Codex's BLOCK on 027h came from Test-Path returning False on a stashed tree.
    Reading the SHA makes that whole failure mode unreachable.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    target = repo / "surface.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add surface")
    sha = _head(repo)

    target.unlink()
    assert not target.exists()

    content = read_surface_at_sha(repo, sha, ["surface.py"])
    assert content["surface.py"] == "x = 1\n"


def test_absent_surface_raises_not_auditable(tmp_path: Path) -> None:
    """BARRERA DE PRESENCIA: a surface absent at the SHA is NOT AUDITABLE.

    It must never be a content verdict. An auditor that treated "file missing"
    as "nothing wrong here" would emit SHIP over the void.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    sha = _head(repo)

    with pytest.raises(SurfaceAbsentError) as excinfo:
        read_surface_at_sha(repo, sha, ["never_existed.py"])

    message = str(excinfo.value)
    assert "NO AUDITABLE" in message
    assert "never_existed.py" in message


def test_partial_presence_still_rejects_naming_the_missing_one(
    tmp_path: Path,
) -> None:
    """One present + one absent is still NOT AUDITABLE, and says which is absent."""
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "present.py").write_text("a = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add present")
    sha = _head(repo)

    with pytest.raises(SurfaceAbsentError) as excinfo:
        read_surface_at_sha(repo, sha, ["present.py", "absent.py"])

    message = str(excinfo.value)
    assert "absent.py" in message
    assert "present.py" not in message.replace("absent.py", "")


def test_audits_the_exact_sha_passed_not_current_head(tmp_path: Path) -> None:
    """THE anti-phantom-SHA test: HEAD moves after the rejector cleared a SHA.

    Between Pieza 1 emitting a SHA and the auditor running, HEAD can advance.
    A helper that re-read HEAD would silently audit a DIFFERENT commit than the
    one that was cleared -- a false verdict attached to the wrong evidence.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    target = repo / "surface.py"
    target.write_text("VERSION = 'first'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "first")
    cleared_sha = _head(repo)

    # HEAD advances (another commit lands) AFTER the rejector cleared cleared_sha.
    target.write_text("VERSION = 'second'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "second")
    assert _head(repo) != cleared_sha

    content = read_surface_at_sha(repo, cleared_sha, ["surface.py"])

    assert content["surface.py"] == "VERSION = 'first'\n"


def test_unknown_sha_fails_closed(tmp_path: Path) -> None:
    """A SHA git cannot resolve is unprovable state -> reject, never pass."""
    repo = tmp_path / "repo"
    init_git_repo(repo)

    with pytest.raises(SurfaceAbsentError):
        read_surface_at_sha(repo, "0" * 40, ["README.md"])


def test_directory_path_is_not_mistaken_for_an_auditable_file(
    tmp_path: Path,
) -> None:
    """``git show <sha>:<dir>`` succeeds and prints a tree listing.

    Without a type check the helper would hand the auditor a directory listing
    dressed up as file content -- a plausible-looking string that is not the
    surface. It must be NOT AUDITABLE instead.
    """
    repo = tmp_path / "repo"
    init_git_repo(repo)
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("m = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add pkg")
    sha = _head(repo)

    with pytest.raises(SurfaceAbsentError):
        read_surface_at_sha(repo, sha, ["pkg"])
