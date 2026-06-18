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


def test_archiver_moves_without_committing_then_guard_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    collab = repo / ".agent" / "collaboration"
    collab.mkdir(parents=True)

    # An active ticket (work_plan) plus a CLOSED ticket's STRATEGY/AUDIT.
    (collab / "work_plan.md").write_text("# Work Plan: WOT-2026-777x\n")
    (collab / "STRATEGY_WOT-2026-666w.md").write_text("strategy of a closed ticket\n")
    (collab / "AUDIT_WOT-2026-666w.md").write_text("audit of a closed ticket\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")

    # Run the REAL archiver: active ticket is WOT-2026-777x, so the 666w pair is
    # archived. The archiver moves files; it must not commit.
    result = archiver.archive_collaboration_artifacts(
        collab, active_wp_override="WOT-2026-777x"
    )
    assert result["archived"], "expected the closed pair to be archived"

    # Git now sees delete+untracked (the archiver did NOT commit). Plain porcelain
    # collapses the new dir to _archive/; the guard uses --untracked-files=all to
    # see the individual archived file (verified below via the guard itself).
    status = _git(repo, "status", "--porcelain")
    assert "D " in status or " D" in status
    assert "_archive/" in status

    # The guard catches exactly this limbo with the stable reason.
    guard = dhc.check_archive_rename_complete(repo)
    assert guard.passed is False
    assert "archive_rename_uncommitted" in " ".join(guard.details or [])

    # After staging both sides (the remediation), the limbo is gone.
    _git(repo, "add", "-A", ".agent/collaboration")
    guard_after = dhc.check_archive_rename_complete(repo)
    assert guard_after.passed is True
