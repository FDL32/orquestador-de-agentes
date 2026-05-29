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

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

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

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

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

    def test_guard_ignores_session_close_report(self, tmp_path: Path) -> None:
        """Guard should ignore the runtime session close report."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

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

    def test_guard_ignores_gitignored_files(self, tmp_path: Path) -> None:
        """Guard should ignore files that are in .gitignore."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create M3 checkpoint
        create_checkpoint_tag(repo, "checkpoint/review-WP-2026-167")

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
