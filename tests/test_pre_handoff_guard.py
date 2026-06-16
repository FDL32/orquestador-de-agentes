"""Tests for pre_handoff_guard.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "pre_handoff_guard.py"


def init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with initial commit."""
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
    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def create_checkpoint_tag(repo_path: Path, tag_name: str) -> None:
    """Create an annotated checkpoint tag."""
    subprocess.run(
        ["git", "tag", "-a", tag_name, "-m", "Test checkpoint"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


class TestPreHandoffGuard:
    """Tests for pre_handoff_guard.py script."""

    def test_guard_passes_clean_tree_with_m3(self, tmp_path: Path) -> None:
        """Guard should pass when tree is clean and M3 checkpoint exists."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create work_plan.md with Files Likely Touched
        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        # Commit the .agent directory so it's not untracked
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .agent directory"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create M3 checkpoint on HEAD after all commits
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert output["dirty_tree"] is False
        assert output["missing_checkpoint"] is False
        assert output["checkpoint_misaligned"] is False

    def test_guard_fails_missing_m3(self, tmp_path: Path) -> None:
        """Guard should fail when M3 checkpoint is missing."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create work_plan.md
        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["valid"] is False
        assert output["missing_checkpoint"] is True
        assert output["checkpoint_misaligned"] is False

    def test_guard_fails_misaligned_checkpoint(self, tmp_path: Path) -> None:
        """Guard should fail when M3 checkpoint exists but does not point to HEAD."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create M3 checkpoint on current HEAD (initial commit)
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        # Make a new commit so the checkpoint tag no longer points to HEAD
        (repo / "new_file.txt").write_text("new content")
        subprocess.run(
            ["git", "add", "new_file.txt"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Second commit"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create work_plan.md
        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        # Commit work_plan so tree is clean
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .agent directory"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["valid"] is False
        assert output["missing_checkpoint"] is False
        assert output["checkpoint_misaligned"] is True
        assert output["checkpoint_tag"] == "checkpoint/review-WP-2026-167"

    def test_guard_fails_dirty_tree(self, tmp_path: Path) -> None:
        """Guard should fail when tree has uncommitted changes."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        # Create uncommitted change
        (repo / "dirty_file.txt").write_text("dirty content")
        subprocess.run(
            ["git", "add", "dirty_file.txt"], cwd=repo, check=True, capture_output=True
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["valid"] is False
        assert output["dirty_tree"] is True
        assert "dirty_file.txt" in output["dirty_files"]

    def test_guard_fails_dirty_tree_even_when_file_is_in_scope(
        self, tmp_path: Path
    ) -> None:
        """Guard should block when a tracked in-scope file is modified."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        subprocess.run(
            ["git", "add", ".agent"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .agent directory"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        module = src_dir / "module.py"
        module.write_text("# Module in scope")
        subprocess.run(
            ["git", "add", "src/module.py"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add module"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        module.write_text("# Module updated")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["valid"] is False
        assert output["dirty_tree"] is True
        assert str(Path("src") / "module.py") in output["dirty_files"]

    def test_guard_ignores_live_surfaces(self, tmp_path: Path) -> None:
        """Guard should not flag live surfaces as dirty files."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create live surface files
        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "TURN.md").write_text("# Turn")
        (collab_dir / "STATE.md").write_text("# State")
        (collab_dir / "execution_log.md").write_text("# Execution Log")

        # Add them to git
        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add live surfaces"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create M3 checkpoint on HEAD after all commits
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        # Modify them (should be ignored by guard)
        (collab_dir / "TURN.md").write_text("# Turn updated")
        (collab_dir / "STATE.md").write_text("# State updated")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Should pass because live surfaces are excluded
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert output["dirty_tree"] is False
        assert output["checkpoint_misaligned"] is False

    def test_guard_ignores_session_close_report(self, tmp_path: Path) -> None:
        """Guard should ignore the runtime session close report."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        report_dir = repo / ".agent" / "runtime" / "memory"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "session_close_report.md").write_text("# Session Close Report")

        subprocess.run(
            ["git", "add", ".agent"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add agent scaffolding"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create M3 checkpoint on HEAD after all commits
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        (report_dir / "session_close_report.md").write_text(
            "# Session Close Report\n\n**Generated:** 2026-05-29 12:40:00 UTC\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert output["dirty_tree"] is False
        assert output["checkpoint_misaligned"] is False

    def test_guard_reports_scope_discrepancy_non_blocking(self, tmp_path: Path) -> None:
        """Guard should report scope discrepancy in addition to blocking dirty tree."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        # Create work_plan.md with limited scope
        collab_dir = repo / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text(
            "# Work Plan\n\n## Files Likely Touched\n- `src/module.py`\n"
        )

        # Commit the .agent directory so it's not untracked
        subprocess.run(
            ["git", "add", ".agent"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .agent directory"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create file in scope
        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "module.py").write_text("# Module in scope")

        # Create file out of scope
        (repo / "out_of_scope.txt").write_text("out of scope")

        # Add and commit in-scope file
        subprocess.run(
            ["git", "add", "src/module.py"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add module"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Modify both files
        (src_dir / "module.py").write_text("# Module updated")
        (repo / "out_of_scope.txt").write_text("out of scope updated")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Should block because any uncommitted change makes the tree dirty.
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["valid"] is False
        assert output["dirty_tree"] is True
        assert "out_of_scope.txt" in output["scope_discrepancy"]

    def test_guard_non_git_repo(self, tmp_path: Path) -> None:
        """Guard should pass with warning for non-git repos."""
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert "warnings" in output

    def test_guard_ignores_project_md_live_surface(self, tmp_path: Path) -> None:
        """Guard should not flag PROJECT.md changes as dirty tree.

        WP-2026-172: PROJECT.md is a live surface that gets updated during
        the operational cycle and should not block --mark-ready.
        """
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create and commit PROJECT.md
        (repo / "PROJECT.md").write_text("# Project\ntest content\n")
        subprocess.run(
            ["git", "add", "PROJECT.md"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add PROJECT.md"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-172")

        # Modify PROJECT.md (simulating operational cycle update)
        (repo / "PROJECT.md").write_text(
            "# Project\n**Version:** v9.14.1\n**State:** UPDATED\n"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-172",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Should pass because PROJECT.md is a live surface
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert output["dirty_tree"] is False
        assert output["checkpoint_misaligned"] is False

    def test_guard_ignores_gitignored_files(self, tmp_path: Path) -> None:
        """Guard should ignore files that are in .gitignore."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create .gitignore
        (repo / ".gitignore").write_text("*.log\n__pycache__/\n")

        # Commit .gitignore first
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add .gitignore"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Create M3 checkpoint on HEAD after all commits
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

        # Create ignored files
        (repo / "debug.log").write_text("log content")
        pycache = repo / "__pycache__"
        pycache.mkdir(parents=True, exist_ok=True)
        (pycache / "module.pyc").write_text("cached")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WP-2026-167",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Should pass because ignored files don't count
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["valid"] is True
        assert output["dirty_tree"] is False
        assert output["checkpoint_misaligned"] is False


class TestWorkPlanCommitGuard:
    """Integration tests for WOT-2026-009g: work_plan.md must be committed at handoff.

    Uses run_guard() directly (not CLI) so tests do not depend on motor_checkpoint
    being importable from the script's sys.path — the function path is what matters.
    """

    def test_guard_fails_when_work_plan_uncommitted(self, tmp_path: Path) -> None:
        """Barrier 008b: work_plan.md modified (not committed) must block guard.

        Before fix: work_plan.md was in LIVE_SURFACES_REL and skipped by
        dirty-tree check -> guard returned valid=True (false green).
        After fix: assert_work_plan_committed detects it -> valid=False,
        uncommitted_work_plan=True.
        """
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        from pre_handoff_guard import run_guard

        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create and commit work_plan.md
        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        wp = collab / "work_plan.md"
        wp.write_text("# Work Plan\n- deliverable_type: code\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add work_plan"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        create_checkpoint_tag(repo, "checkpoint/review-WOT-2026-TEST")

        # Simulate 008b incident: modify work_plan.md without committing
        wp.write_text("# Updated plan - NOT committed\n")

        result = run_guard(repo, "WOT-2026-TEST", motor_root=repo)

        assert result["valid"] is False
        assert result.get("uncommitted_work_plan") is True

    def test_guard_passes_when_work_plan_committed(self, tmp_path: Path) -> None:
        """Control: work_plan.md committed + clean tree -> guard passes."""
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        from pre_handoff_guard import run_guard

        repo = tmp_path / "repo"
        init_git_repo(repo)

        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        wp = collab / "work_plan.md"
        wp.write_text("# Work Plan\n- deliverable_type: code\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add work_plan"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        create_checkpoint_tag(repo, "checkpoint/review-WOT-2026-TEST")

        result = run_guard(repo, "WOT-2026-TEST", motor_root=repo)

        assert result["valid"] is True
        assert result.get("uncommitted_work_plan") is False

    def test_guard_passes_live_surfaces_dirty_work_plan_committed(
        self, tmp_path: Path
    ) -> None:
        """Non-regression: work_plan.md committed + STATE/TURN dirty -> still passes."""
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        from pre_handoff_guard import run_guard

        repo = tmp_path / "repo"
        init_git_repo(repo)

        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        wp = collab / "work_plan.md"
        wp.write_text("# Work Plan\n- deliverable_type: code\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add work_plan"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        create_checkpoint_tag(repo, "checkpoint/review-WOT-2026-TEST")

        # Dirty live surfaces (must not cause failure)
        (collab / "STATE.md").write_text("ACTIVE_TICKET: TEST\n")
        (collab / "TURN.md").write_text("# TURN\nROL: BUILDER\n")

        result = run_guard(repo, "WOT-2026-TEST", motor_root=repo)

        assert result["valid"] is True, (
            f"Live-surface dirty must not block when work_plan.md is committed. "
            f"result={result}"
        )
        assert result.get("uncommitted_work_plan") is False
