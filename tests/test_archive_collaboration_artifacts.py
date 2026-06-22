"""Integration barrier (WOT-2026-010u): the real archiver leaves an uncommitted
rename, and check_archive_rename_complete catches it.

This couples the two halves of the contract: the archiver must NOT auto-commit
(it only moves), and the hygiene guard must detect the resulting limbo. Uses the
real archiver and a real git repo, not surrogates.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


archiver = _load(
    "archive_collaboration_artifacts", "scripts/archive_collaboration_artifacts.py"
)
dhc = _load("delivery_hygiene_check", "scripts/delivery_hygiene_check.py")


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _seed_closed_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Build a git repo with an active ticket + a CLOSED ticket's STRATEGY/AUDIT.

    Returns (repo, collaboration_dir). The 666w pair is committed so that a later
    archival move shows up as a delete in git; the active ticket is 777x.
    """
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    collab = repo / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "work_plan.md").write_text("# Work Plan: WOT-2026-777x\n")
    (collab / "STRATEGY_WOT-2026-666w.md").write_text("strategy of a closed ticket\n")
    (collab / "AUDIT_WOT-2026-666w.md").write_text("audit of a closed ticket\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo, collab


def test_archiver_stages_rename_so_no_limbo_inherited(tmp_path: Path) -> None:
    """WOT-2026-013h regression: the real archiver must leave NO uncommitted-rename
    limbo for the next ticket to inherit.

    FAIL-without-fix: before 013h the archiver only ``shutil.move``d, leaving
    ``D old + ?? new`` and ``check_archive_rename_complete`` -> passed=False (the
    recurring 013e/013f/013g reconcile). PASS-with-fix: the archiver now stages
    the rename, so the guard passes immediately with no manual ``git add``.
    """
    repo, collab = _seed_closed_pair(tmp_path)

    result = archiver.archive_collaboration_artifacts(
        collab, active_wp_override="WOT-2026-777x"
    )
    assert result["archived"], "expected the closed pair to be archived"

    # The canonical limbo detector must pass WITHOUT any manual reconcile: the
    # archiver staged the rename itself. This is the behavior that fails before
    # the 013h fix and passes after it.
    guard = dhc.check_archive_rename_complete(repo)
    assert guard.passed is True, (
        f"archiver left an uncommitted-rename limbo (013h regression): {guard.details}"
    )


def test_archiver_stages_but_does_not_commit(tmp_path: Path) -> None:
    """The 013h fix stages the rename but must NOT commit it (no opaque
    auto-commit): the staged rename rides the closeout's own commit.

    Verifies both invariants: (1) git sees a staged rename (R) for the archived
    pair, and (2) HEAD is unchanged (the archiver created no new commit).
    """
    repo, collab = _seed_closed_pair(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    archiver.archive_collaboration_artifacts(collab, active_wp_override="WOT-2026-777x")

    # No commit was created by the archiver.
    head_after = _git(repo, "rev-parse", "HEAD").strip()
    assert head_after == head_before, "archiver must not commit (no opaque auto-commit)"

    # The rename is staged: porcelain shows renamed/added index entries for the
    # archived artifacts, and there is no unstaged delete + untracked pair left.
    staged = _git(repo, "status", "--porcelain").splitlines()
    # Every archived artifact basename appears in a staged (index) entry, not as a
    # bare unstaged delete or untracked file.
    for base in ("STRATEGY_WOT-2026-666w.md", "AUDIT_WOT-2026-666w.md"):
        index_entries = [
            ln for ln in staged if base in ln and ln[:1] in ("R", "A", "D")
        ]
        assert index_entries, f"expected a staged index entry for {base}: {staged}"


def test_archiver_no_git_tree_still_moves(tmp_path: Path) -> None:
    """Fail-open: outside a git tree the archiver still moves the files (no raise),
    and the closeout/mark-ready fail-closed guard remains the safety net.
    """
    # No git init: a plain directory tree.
    collab = tmp_path / "plain" / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "work_plan.md").write_text("# Work Plan: WOT-2026-777x\n")
    (collab / "STRATEGY_WOT-2026-666w.md").write_text("strategy\n")

    result = archiver.archive_collaboration_artifacts(
        collab, active_wp_override="WOT-2026-777x"
    )
    assert result["archived"], "archiver must still move files without a git tree"
    assert not result["errors"], f"no errors expected without git: {result['errors']}"
    moved = collab / "_archive" / "plan_audit" / "STRATEGY_WOT-2026-666w.md"
    assert moved.exists(), "file should have been moved into the archive dir"
