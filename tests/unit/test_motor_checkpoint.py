"""Tests for assert_work_plan_committed in motor_checkpoint.py — WOT-2026-009g.

TDD order: tests written BEFORE implementation.
Expected pre-fix behavior: all tests FAIL (helper does not exist yet).
Expected post-fix behavior: all tests PASS.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _init_git_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _add_committed_work_plan(repo_path: Path) -> Path:
    """Create and commit work_plan.md; return its absolute path."""
    collab = repo_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    wp = collab / "work_plan.md"
    wp.write_text("# Work Plan\n- deliverable_type: code\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add work_plan"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    return wp


class TestAssertWorkPlanCommitted:
    """Unit tests for motor_checkpoint.assert_work_plan_committed."""

    def test_committed_returns_true(self, tmp_path: Path) -> None:
        """When work_plan.md is committed and clean, helper returns (True, diag)."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _add_committed_work_plan(repo)

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is True
        assert diag.get("uncommitted_work_plan") is not True

    def test_unstaged_modification_returns_false(self, tmp_path: Path) -> None:
        """Unstaged modification to work_plan.md → committed=False, diag filled."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        wp = _add_committed_work_plan(repo)

        # Modify without staging
        wp.write_text("# Modified Work Plan\n")

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False
        assert diag.get("uncommitted_work_plan") is True
        assert ".agent/collaboration/work_plan.md" in diag.get("path", "")
        assert "git add" in diag.get("remediation", "")

    def test_staged_modification_returns_false(self, tmp_path: Path) -> None:
        """Staged (but not committed) work_plan.md → committed=False."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        wp = _add_committed_work_plan(repo)

        wp.write_text("# Staged Work Plan\n")
        subprocess.run(
            ["git", "add", str(wp)], cwd=repo, check=True, capture_output=True
        )

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False
        assert diag.get("uncommitted_work_plan") is True

    def test_untracked_work_plan_returns_false(self, tmp_path: Path) -> None:
        """Untracked work_plan.md (never committed) → committed=False."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        # Create work_plan.md but do NOT commit it
        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text("# Untracked Work Plan\n")

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False
        assert diag.get("uncommitted_work_plan") is True

    def test_deleted_work_plan_returns_false(self, tmp_path: Path) -> None:
        """Deleted (tracked, now missing) work_plan.md → committed=False."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        wp = _add_committed_work_plan(repo)

        wp.unlink()

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False
        assert diag.get("uncommitted_work_plan") is True

    def test_control_other_live_surfaces_dirty_does_not_fail(
        self, tmp_path: Path
    ) -> None:
        """Control: work_plan.md committed + STATE/TURN/execution_log dirty → ok=True.

        This is the non-regression test: the helper only checks work_plan.md,
        not other live surfaces.
        """
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _add_committed_work_plan(repo)

        # Dirty live surfaces (not work_plan.md)
        collab = repo / ".agent" / "collaboration"
        (collab / "STATE.md").write_text("ACTIVE_TICKET: TEST\n")
        (collab / "TURN.md").write_text("# TURN\nROL: BUILDER\n")
        (collab / "execution_log.md").write_text("# Log\n- step 1\n")

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is True, (
            f"Helper must not fail when only live surfaces are dirty. diag={diag}"
        )

    def test_delegates_to_scope_gate_not_new_git_parser(self, tmp_path: Path) -> None:
        """Helper must delegate to scope_gate.get_changed_files, not parse git itself."""
        import motor_checkpoint

        calls: list[dict] = []

        def fake_get_changed_files(*, project_root, motor_root, run_fn=None):
            calls.append({"project_root": project_root, "motor_root": motor_root})
            return set()  # clean

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _add_committed_work_plan(repo)

        original = motor_checkpoint.scope_gate.get_changed_files
        motor_checkpoint.scope_gate.get_changed_files = fake_get_changed_files
        try:
            motor_checkpoint.assert_work_plan_committed(
                project_root=repo, motor_root=repo
            )
        finally:
            motor_checkpoint.scope_gate.get_changed_files = original

        assert len(calls) >= 1, (
            "assert_work_plan_committed must call scope_gate.get_changed_files"
        )

    def test_diag_contains_remediation_command(self, tmp_path: Path) -> None:
        """Diag when blocked must include a git add ... && git commit remediation."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        wp = _add_committed_work_plan(repo)
        wp.write_text("# Dirty\n")

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False
        remediation = diag.get("remediation", "")
        assert "git add" in remediation
        assert "git commit" in remediation


class TestRegressionBarrier008b:
    """Barrier: reproduce the 008b incident (work_plan.md dirty at handoff).

    Pre-fix: guard would pass (False green).
    Post-fix: guard must return ok=False with uncommitted_work_plan=True.

    This test uses only assert_work_plan_committed (unit-level barrier).
    The integration-level barrier (pre_handoff_guard.run_guard) is tested
    in tests/test_pre_handoff_guard.py::TestWorkPlanCommitGuard.
    """

    def test_barrier_008b_false_green_is_closed(self, tmp_path: Path) -> None:
        """Incident 008b: work_plan.md modified since last commit.

        With the fix, assert_work_plan_committed must return ok=False.
        Before the fix, work_plan.md was in LIVE_SURFACES_REL and skipped
        by the dirty-tree check — this test confirms that gap is closed.
        """
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        wp = _add_committed_work_plan(repo)

        # Simulate 008b: work_plan.md modified but not committed (handoff incident)
        wp.write_text("# Plan content updated for new ticket — NOT committed\n")

        ok, diag = motor_checkpoint.assert_work_plan_committed(
            project_root=repo, motor_root=repo
        )

        assert ok is False, (
            "Regression barrier 008b: work_plan.md dirty at handoff must be detected. "
            "If ok=True, the false green is still open."
        )
        assert diag.get("uncommitted_work_plan") is True
        assert ".agent/collaboration/work_plan.md" in diag.get("path", "")
