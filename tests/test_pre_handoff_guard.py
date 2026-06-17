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


def commit_ticket_marker(repo_path: Path, ticket_id: str) -> None:
    """Create a commit whose message names the ticket (WOT-2026-010i).

    The commit-visible barrier requires a repo_motor commit naming the active
    ticket for code/mixed handoffs. Tests that drive run_guard end-to-end with
    a code deliverable_type must therefore have such a commit, mirroring real
    handoff flow where the Builder commits productive work before --mark-ready.
    """
    marker = repo_path / f".ticket_marker_{ticket_id}.txt"
    marker.write_text(f"productive change for {ticket_id}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", marker.name], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", f"{ticket_id}: productive change"],
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


def write_green_last_run(repo_path: Path, ticket_id: str | None = None) -> None:
    """Write a fresh-green last-run.json so the WOT-2026-010c gate passes.

    Required precondition for any guard test that expects valid=True: the
    canonical-suite gate demands status==finished + exit_code==0 +
    tested_commit_sha==HEAD. Writes it against the repo's current HEAD.

    WOT-2026-010i: when ``ticket_id`` is given, also lands a commit naming the
    ticket BEFORE capturing HEAD, so the commit-visible barrier is satisfied
    and the subsequent M3 checkpoint still aligns to the final HEAD.
    """
    if ticket_id is not None:
        commit_ticket_marker(repo_path, ticket_id)

    # Replicate the motor .gitignore so the ephemeral artifact does not dirty
    # the handoff tree (the real motor ignores .agent/runtime/pytest-safe/).
    # Commit the .gitignore first so HEAD reflects a clean tree, then write the
    # last-run.json (now ignored) against that committed HEAD.
    gitignore = repo_path / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "pytest-safe" not in existing:
        gitignore.write_text(
            existing + "\n.agent/runtime/pytest-safe/\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", ".gitignore"], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ignore pytest-safe runtime"],
            cwd=repo_path,
            capture_output=True,
        )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout.strip()
    d = repo_path / ".agent" / "runtime" / "pytest-safe"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last-run.json").write_text(
        json.dumps(
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": head,
                "level": "all",
                "args_mode": "default_discovery",
            }
        ),
        encoding="utf-8",
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
        write_green_last_run(repo, ticket_id="WP-2026-167")
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
        write_green_last_run(repo, ticket_id="WP-2026-167")
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
        write_green_last_run(repo, ticket_id="WP-2026-167")
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
        write_green_last_run(repo, ticket_id="WP-2026-167")
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
        write_green_last_run(repo, ticket_id="WP-2026-172")
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
        write_green_last_run(repo, ticket_id="WP-2026-167")
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
        write_green_last_run(repo, ticket_id="WOT-2026-TEST")
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
        write_green_last_run(repo, ticket_id="WOT-2026-TEST")
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

    def test_guard_fails_closed_when_helper_raises(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Fail-closed: if assert_work_plan_committed raises, run_guard must BLOCK.

        A broken guard must never become a silent pass — that would reopen the
        008b false green. Monkeypatch the helper to raise and confirm run_guard
        returns valid=False with a work_plan_guard_error diagnostic.
        """
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import pre_handoff_guard
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

        # Force the helper to raise, simulating API drift / bug.
        class _BrokenModule:
            @staticmethod
            def assert_work_plan_committed(**_kwargs):
                raise RuntimeError("simulated guard failure")

        monkeypatch.setattr(
            pre_handoff_guard, "_import_motor_checkpoint", lambda: _BrokenModule()
        )

        result = run_guard(repo, "WOT-2026-TEST", motor_root=repo)

        assert result["valid"] is False, (
            "Fail-closed: a raising helper must block the handoff, not pass. "
            f"result={result}"
        )
        assert result.get("work_plan_guard_error"), (
            "Expected work_plan_guard_error diagnostic when helper raises."
        )


class TestCanonicalSuiteGreenGate:
    """WOT-2026-010c: handoff requires a fresh green run_pytest_safe.

    The gate reads <motor>/.agent/runtime/pytest-safe/last-run.json and requires
    status==finished + exit_code==0 + tested_commit_sha==HEAD(motor). Fail-closed.
    deliverable_type doc/research/analysis -> auditable skip, not a block.
    """

    @staticmethod
    def _write_last_run(motor: Path, payload: dict) -> Path:
        d = motor / ".agent" / "runtime" / "pytest-safe"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "last-run.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    @staticmethod
    def _head_sha(repo: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        return r.stdout.strip()

    def _import_guard(self):
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import pre_handoff_guard

        return pre_handoff_guard

    def test_missing_last_run_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert diag.get("canonical_suite_required") is True
        assert "last_run_json" in diag
        assert "remediation" in diag

    def test_corrupt_json_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        d = motor / ".agent" / "runtime" / "pytest-safe"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last-run.json").write_text("{not valid json", encoding="utf-8")
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert diag.get("canonical_suite_error")

    def test_status_not_finished_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "started",
                "exit_code": 0,
                "tested_commit_sha": self._head_sha(motor),
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert "finished" in diag.get("reason", "").lower()

    def test_exit_code_nonzero_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "finished",
                "exit_code": 1,
                "tested_commit_sha": self._head_sha(motor),
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert (
            "exit_code" in diag.get("reason", "").lower()
            or "failed" in diag.get("reason", "").lower()
        )

    def test_stale_sha_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        # last-run against a different (old) sha, then a new commit moves HEAD
        self._write_last_run(
            motor,
            {"status": "finished", "exit_code": 0, "tested_commit_sha": "deadbeef" * 5},
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert (
            "stale" in diag.get("reason", "").lower()
            or "sha" in diag.get("reason", "").lower()
        )

    def test_fresh_green_passes(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": self._head_sha(motor),
                "level": "all",
                "args_mode": "default_discovery",
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is True, f"fresh green run must pass: {diag}"

    def test_focal_level_unit_blocks(self, tmp_path: Path) -> None:
        """WOT-2026-010q: level='unit' must block handoff even if fresh+green."""
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": self._head_sha(motor),
                "level": "unit",
                "args_mode": "default_discovery",
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert "not_full_suite" in diag.get("reason", "")
        assert "python scripts/run_pytest_safe.py --level all" in diag.get(
            "canonical_suite_error", ""
        )

    def test_explicit_args_blocks(self, tmp_path: Path) -> None:
        """WOT-2026-010q: level='all' + args_mode='explicit_args' must block handoff."""
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": self._head_sha(motor),
                "level": "all",
                "args_mode": "explicit_args",
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert "not_full_suite" in diag.get("reason", "")
        assert "python scripts/run_pytest_safe.py --level all" in diag.get(
            "canonical_suite_error", ""
        )

    def test_canonical_suite_passes_all_fields(self, tmp_path: Path) -> None:
        """WOT-2026-010q: level='all' + args_mode='default_discovery' allows handoff."""
        guard = self._import_guard()
        motor = tmp_path / "motor"
        init_git_repo(motor)
        self._write_last_run(
            motor,
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": self._head_sha(motor),
                "level": "all",
                "args_mode": "default_discovery",
            },
        )
        ok, diag = guard.assert_canonical_suite_green(motor, "code")
        assert ok is True, f"canonical suite must pass: {diag}"
        assert diag.get("level") == "all"
        assert diag.get("args_mode") == "default_discovery"


# =============================================================================
# Tests for WOT-2026-010d: Pause/Resume functionality in pre_handoff_guard
# =============================================================================


class TestPreHandoffGuardWithPause(TestPreHandoffGuard):
    """Tests for detecting active pauses during handoff (WOT-2026-010d integration)."""

    def test_handoff_guard_detects_active_pause(self, tmp_path: Path) -> None:
        """pre_handoff_guard must detect an active pause and block handoff."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create active pause artifact
        collab_dir = repo / ".agent" / "collaboration" / "paused"
        collab_dir.mkdir(parents=True, exist_ok=True)
        pause_artifact = collab_dir / "WOT-2026-010d.json"
        pause_artifact.write_text(
            json.dumps(
                {
                    "ticket_id": "WOT-2026-010d",
                    "status": "PAUSED",
                    "reason": "Pausing for hotfix",
                    "timestamp": "2026-06-16T12:00:00+00:00",
                },
                indent=2,
            )
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WOT-2026-010d",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Handoff must be blocked
        assert result.returncode != 0, "Handoff guard must block with active pause"
        output = json.loads(result.stdout)
        assert output.get("valid") is False

    def test_handoff_guard_detects_corrupted_pause(self, tmp_path: Path) -> None:
        """pre_handoff_guard must detect and report corrupted pause artifacts."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create corrupted pause artifact
        collab_dir = repo / ".agent" / "collaboration" / "paused"
        collab_dir.mkdir(parents=True, exist_ok=True)
        pause_artifact = collab_dir / "WOT-2026-010d.json"
        pause_artifact.write_text("{invalid json without closing")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WOT-2026-010d",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Handoff must be blocked due to corrupted artifact
        assert result.returncode != 0
        output = json.loads(result.stdout) if result.stdout else {}
        assert output.get("valid") is False or "paused" in result.stderr.lower()

    def test_handoff_succeeds_without_pause(self, tmp_path: Path) -> None:
        """Handoff proceeds normally when no pause is present."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create minimal work_plan.md
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

        # Create M3 checkpoint
        write_green_last_run(repo, ticket_id="WOT-2026-010d")
        create_checkpoint_tag(repo, "checkpoint/review-WOT-2026-010d")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WOT-2026-010d",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # Should pass (no pause blocking)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output.get("valid") is True


class TestRunnerWritesTestedSha:
    """WOT-2026-010c: run_pytest_safe records tested_commit_sha for the gate."""

    def test_motor_head_sha_matches_git(self) -> None:
        """run_pytest_safe._motor_head_sha returns the motor HEAD SHA."""
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import run_pytest_safe

        motor_root = SCRIPT_PATH.parent.parent
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=motor_root,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert run_pytest_safe._motor_head_sha() == expected

    def test_gate_blocks_when_sha_differs_from_head(self, tmp_path: Path) -> None:
        """If tested_commit_sha != HEAD, the gate blocks even with exit_code 0."""
        import sys

        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import pre_handoff_guard

        motor = tmp_path / "motor"
        init_git_repo(motor)
        d = motor / ".agent" / "runtime" / "pytest-safe"
        d.mkdir(parents=True, exist_ok=True)
        # Green run but against an old/foreign sha.
        (d / "last-run.json").write_text(
            json.dumps(
                {
                    "status": "finished",
                    "exit_code": 0,
                    "tested_commit_sha": "0" * 40,
                }
            ),
            encoding="utf-8",
        )
        ok, diag = pre_handoff_guard.assert_canonical_suite_green(motor, "code")
        assert ok is False
        assert "stale" in diag.get("reason", "").lower()


class TestCanonicalSuiteDiagPropagation:
    """WOT-2026-010c review fix: the structured diag must reach the CLI/JSON.

    The controller's _fail_closeout propagates guard_result["canonical_suite"],
    so the script must emit it in --json output when the suite is not fresh-green.
    """

    def test_cli_json_includes_canonical_suite_diag(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        init_git_repo(repo)
        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            "# Work Plan\n- **deliverable_type:** code\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "wp"], cwd=repo, check=True, capture_output=True
        )
        create_checkpoint_tag(repo, "checkpoint/review-WOT-2026-TEST")
        # Red suite (exit_code 1) fresh against HEAD.
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()
        d = repo / ".agent" / "runtime" / "pytest-safe"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last-run.json").write_text(
            json.dumps(
                {"status": "finished", "exit_code": 1, "tested_commit_sha": head}
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--project-root",
                str(repo),
                "--ticket-id",
                "WOT-2026-TEST",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )
        output = json.loads(result.stdout)
        assert output["valid"] is False
        cs = output.get("canonical_suite")
        assert cs is not None, "canonical_suite must be present in CLI JSON"
        assert cs.get("canonical_suite_required") is True
        # The structured self-service fields must all be present.
        for field in (
            "reason",
            "remediation",
            "last_run_json",
            "canonical_suite_error",
        ):
            assert field in cs, f"missing {field} in canonical_suite diag"


# =============================================================================
# WOT-2026-010i: Forbidden Surfaces handoff barrier
# =============================================================================


class TestForbiddenSurfacesBarrier:
    """A diff touching a declared Forbidden Surface must block handoff."""

    def _import_guard(self):
        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import pre_handoff_guard

        return pre_handoff_guard

    @staticmethod
    def _write_work_plan(repo: Path, forbidden_lines: str) -> None:
        collab = repo / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            "# Work Plan\n\n"
            "## Files Likely Touched\n\n"
            "- `scripts/foo.py`\n\n"
            "## Forbidden Surfaces\n\n"
            f"{forbidden_lines}\n",
            encoding="utf-8",
        )

    def test_changed_file_in_forbidden_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        repo = tmp_path / "repo"
        init_git_repo(repo)
        self._write_work_plan(repo, "- `scripts/run_pytest_safe.py`\n")

        changed = {str((repo / "scripts" / "run_pytest_safe.py").resolve())}
        hits = guard.check_forbidden_surfaces(
            changed_files=changed, project_root=repo, motor_root=None
        )
        assert hits, "a changed file in Forbidden Surfaces must be reported"
        assert "run_pytest_safe.py" in hits[0]

    def test_changed_file_not_forbidden_passes(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        repo = tmp_path / "repo"
        init_git_repo(repo)
        self._write_work_plan(repo, "- `scripts/run_pytest_safe.py`\n")

        changed = {str((repo / "scripts" / "foo.py").resolve())}
        hits = guard.check_forbidden_surfaces(
            changed_files=changed, project_root=repo, motor_root=None
        )
        assert hits == [], "a non-forbidden changed file must not be flagged"

    def test_conceptual_forbidden_entry_not_a_false_path(self, tmp_path: Path) -> None:
        """Conceptual entries like 'cache pytest' are not concrete paths and
        must not produce spurious matches (no false positive from prose)."""
        guard = self._import_guard()
        repo = tmp_path / "repo"
        init_git_repo(repo)
        self._write_work_plan(repo, "- cache pytest\n- xdist/sharding\n")

        changed = {str((repo / "scripts" / "foo.py").resolve())}
        hits = guard.check_forbidden_surfaces(
            changed_files=changed, project_root=repo, motor_root=None
        )
        assert hits == []


# =============================================================================
# WOT-2026-010i: commit-visible barrier for code/mixed
# =============================================================================


class TestCommitVisibleBarrier:
    """code/mixed packets must carry a repo_motor commit naming the ticket."""

    def _import_guard(self):
        sys.path.insert(0, str(SCRIPT_PATH.parent))
        import pre_handoff_guard

        return pre_handoff_guard

    @staticmethod
    def _commit(repo: Path, message: str) -> None:
        (repo / f"f_{abs(hash(message)) % 10000}.txt").write_text(message)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    def test_code_without_visible_commit_blocks(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        repo = tmp_path / "motor"
        init_git_repo(repo)
        self._commit(repo, "unrelated change without ticket")

        ok, diag = guard.assert_ticket_commit_visible(
            ticket_id="WOT-2026-010i",
            deliverable_type="code",
            motor_root=repo,
        )
        assert ok is False
        assert diag.get("reason") == "no_visible_commit"
        assert "WOT-2026-010i" in diag.get("remediation", "")

    def test_mixed_with_visible_commit_passes(self, tmp_path: Path) -> None:
        guard = self._import_guard()
        repo = tmp_path / "motor"
        init_git_repo(repo)
        self._commit(repo, "WOT-2026-010i: harden handoff barriers")

        ok, diag = guard.assert_ticket_commit_visible(
            ticket_id="WOT-2026-010i",
            deliverable_type="mixed",
            motor_root=repo,
        )
        assert ok is True
        assert diag.get("reason") == "commit_visible"

    def test_analysis_exempt_without_commit(self, tmp_path: Path) -> None:
        """Documentation/analysis tickets do not require a code commit."""
        guard = self._import_guard()
        repo = tmp_path / "motor"
        init_git_repo(repo)
        self._commit(repo, "unrelated change without ticket")

        ok, diag = guard.assert_ticket_commit_visible(
            ticket_id="WOT-2026-010i",
            deliverable_type="analysis",
            motor_root=repo,
        )
        assert ok is True
        assert diag.get("reason") == "deliverable_type_exempt"

    def test_git_failure_fails_closed_for_code(self, tmp_path: Path) -> None:
        """A git failure for a code ticket must block (fail-closed), not pass."""
        guard = self._import_guard()

        def _boom(*_a, **_k):
            raise FileNotFoundError("git not found")

        ok, diag = guard.assert_ticket_commit_visible(
            ticket_id="WOT-2026-010i",
            deliverable_type="code",
            motor_root=tmp_path,
            run_fn=_boom,
        )
        assert ok is False
        assert diag.get("reason") == "git_log_failed"
