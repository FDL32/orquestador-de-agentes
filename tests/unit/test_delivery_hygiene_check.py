"""Barrier tests for check_archive_rename_complete (WOT-2026-010u).

Reproduce the delete+untracked limbo a real git repo enters when
archive_collaboration_artifacts.py moves a closed STRATEGY_/AUDIT_ artifact into
_archive/plan_audit/ without committing the rename. The guard must block with a
stable reason and a self-service remediation, without auto-committing or deleting.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "delivery_hygiene_check.py"

_spec = importlib.util.spec_from_file_location("delivery_hygiene_check", MODULE_PATH)
dhc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dhc)


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
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _collab(repo: Path) -> Path:
    d = repo / ".agent" / "collaboration"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _commit_artifact(repo: Path, rel: str, content: str) -> None:
    """Create + commit a tracked artifact so a later move shows as a delete."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel}"], cwd=repo, check=True, capture_output=True
    )


def _simulate_archiver_move(repo: Path, name: str) -> tuple[str, str]:
    """Move a committed collaboration artifact into _archive/plan_audit/ WITHOUT
    committing (what shutil.move in the archiver leaves behind)."""
    old_rel = f".agent/collaboration/{name}"
    new_rel = f".agent/collaboration/_archive/plan_audit/{name}"
    old, new = repo / old_rel, repo / new_rel
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text(old.read_text())
    old.unlink()
    return old_rel, new_rel


def test_uncommitted_archive_rename_blocks(tmp_path: Path) -> None:
    """Barrier: D AUDIT_*.md + ?? _archive/plan_audit/AUDIT_*.md is detected and
    blocked with the stable reason and a remediation naming both paths."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    _commit_artifact(repo, ".agent/collaboration/AUDIT_WOT-2026-999z.md", "audit")
    old_rel, new_rel = _simulate_archiver_move(repo, "AUDIT_WOT-2026-999z.md")

    result = dhc.check_archive_rename_complete(repo)

    assert result.passed is False
    blob = " ".join([result.message, *(result.details or [])])
    assert "archive_rename_uncommitted" in blob
    assert old_rel in blob and new_rel in blob  # origen + destino
    assert "git add" in blob and "git commit" in blob  # remediacion self-service
    # No auto-commit / no delete: the archived copy still exists, original gone.
    assert (repo / new_rel).exists()
    assert not (repo / old_rel).exists()


def test_strategy_and_plan_prefixes_also_detected(tmp_path: Path) -> None:
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    for name in ("STRATEGY_WOT-2026-999z.md", "PLAN_WP-2026-001a.md"):
        _commit_artifact(repo, f".agent/collaboration/{name}", "x")
        _simulate_archiver_move(repo, name)
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is False
    assert "STRATEGY_WOT-2026-999z.md" in " ".join(result.details or [])
    assert "PLAN_WP-2026-001a.md" in " ".join(result.details or [])


def test_bare_delete_without_archived_copy_is_not_flagged(tmp_path: Path) -> None:
    """No false positive: a deletion WITHOUT an archived copy is a normal dirty
    file, not an incomplete rename. This guard must stay silent on it."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    _commit_artifact(repo, ".agent/collaboration/AUDIT_WOT-2026-888y.md", "audit")
    (repo / ".agent" / "collaboration" / "AUDIT_WOT-2026-888y.md").unlink()
    # No copy under _archive/plan_audit/.
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True


def test_unrelated_untracked_file_is_not_flagged(tmp_path: Path) -> None:
    """No false positive for unrelated files."""
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    _collab(repo)
    (repo / "scratch.txt").write_text("noise")
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True


def test_clean_tree_passes(tmp_path: Path) -> None:
    repo = tmp_path / "destino"
    _init_git_repo(repo)
    result = dhc.check_archive_rename_complete(repo)
    assert result.passed is True
    assert "pendientes" in result.message
