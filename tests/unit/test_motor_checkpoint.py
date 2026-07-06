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


def test_parse_raw_flt_paths_mixed_falls_back_to_builder() -> None:
    """WOT-2026-019j: parse_raw_flt_paths(deliverable_type="mixed") falls back
    to ## Builder when ## Files Likely Touched is absent, same contract as
    scope_gate.parse_flt_raw_paths."""
    import motor_checkpoint

    plan = (
        "# Work Plan\n\n"
        "## Metadata\n\n"
        "- **deliverable_type:** mixed\n\n"
        "## Builder\n\n"
        "- `.agent/scope_gate.py`\n"
        "- `scripts/foo.py`\n\n"
        "## Otro\n"
    )

    paths = motor_checkpoint.parse_raw_flt_paths(plan, deliverable_type="mixed")

    assert paths == {".agent/scope_gate.py", "scripts/foo.py"}


def test_parse_raw_flt_paths_code_default_ignores_builder() -> None:
    """WOT-2026-019j regression guard: deliverable_type="code" (default) must
    NOT fall back to ## Builder, preserving pre-fix behavior byte for byte."""
    import motor_checkpoint

    plan = (
        "# Work Plan\n\n"
        "## Metadata\n\n"
        "- **deliverable_type:** code\n\n"
        "## Builder\n\n"
        "- `.agent/scope_gate.py`\n"
    )

    paths = motor_checkpoint.parse_raw_flt_paths(plan)

    assert paths == set()


def _make_commit(repo: Path, fname: str, content: str, subject: str) -> str:
    """Write fname, commit it with subject, return the new commit SHA."""
    (repo / fname).write_text(content, encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", fname], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", subject], cwd=repo, check=True, capture_output=True
    )
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return rev.stdout.strip()


def _tag_at(repo: Path, tag: str, sha: str) -> None:
    """(Re)create an annotated tag pointing at sha."""
    subprocess.run(["git", "tag", "-d", tag], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"M3 {tag}", sha],
        cwd=repo,
        check=True,
        capture_output=True,
    )


class TestResolveMotorCheckpointFilesNonHead:
    """WOT-2026-019q: batch-close a ticket whose M3 is not HEAD, without
    accepting empty deliveries. Fixtures use real git via subprocess, same
    pattern as _init_git_repo/_add_committed_work_plan above (no git mocks).
    """

    def test_buried_ticket_with_real_m3_closes_and_recovers_own_files(
        self, tmp_path: Path
    ) -> None:
        """Ticket A's M3 points at A's own commit, buried under ticket B's
        commit (HEAD). Must close ok=True and recover ONLY file_a.py."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        ticket_a = "WOT-2026-AAA"
        ticket_b = "WOT-2026-BBB"

        sha_a = _make_commit(repo, "file_a.py", "a = 1\n", f"{ticket_a}: implement A")
        _tag_at(repo, f"checkpoint/review-{ticket_a}", sha_a)
        # Bury ticket A under ticket B's commit (B becomes HEAD).
        _make_commit(repo, "file_b.py", "b = 2\n", f"{ticket_b}: implement B")

        ok, files, err = motor_checkpoint.resolve_motor_checkpoint_files(repo, ticket_a)

        assert ok is True, f"buried ticket A should close canonically; err={err!r}"
        assert files == {"file_a.py"}

    def test_topmost_ticket_head_unchanged_behavior(self, tmp_path: Path) -> None:
        """Control/no-regression: M3 at HEAD (topmost ticket) behaves exactly
        as before the fix: ok=True, files == its own diff."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        ticket_a = "WOT-2026-AAA"
        ticket_b = "WOT-2026-BBB"

        sha_a = _make_commit(repo, "file_a.py", "a = 1\n", f"{ticket_a}: implement A")
        _tag_at(repo, f"checkpoint/review-{ticket_a}", sha_a)
        sha_b = _make_commit(repo, "file_b.py", "b = 2\n", f"{ticket_b}: implement B")
        _tag_at(repo, f"checkpoint/review-{ticket_b}", sha_b)

        ok, files, err = motor_checkpoint.resolve_motor_checkpoint_files(repo, ticket_b)

        assert ok is True, f"topmost ticket B should close as before; err={err!r}"
        assert files == {"file_b.py"}

    def test_empty_closeout_commit_is_rejected(self, tmp_path: Path) -> None:
        """M3 pointing at an empty closeout commit (cero files) must be
        rejected explicitly with 'refusing empty closeout'.

        A ticket B commit is interposed between A's real commit and the
        empty closeout commit so the first-parent contiguity walk from the
        closeout commit is cut by B's subject (no ticket_a id) before it
        would otherwise reach A's real, non-empty commit -- matching the
        Fase 0 repro fixture exactly (base -> A -> B -> A closeout)."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        ticket_a = "WOT-2026-AAA"
        ticket_b = "WOT-2026-BBB"
        _make_commit(repo, "file_a.py", "a = 1\n", f"{ticket_a}: implement A")
        _make_commit(repo, "file_b.py", "b = 2\n", f"{ticket_b}: implement B")

        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", f"{ticket_a}: closeout"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        empty_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _tag_at(repo, f"checkpoint/review-{ticket_a}", empty_head)

        ok, files, err = motor_checkpoint.resolve_motor_checkpoint_files(repo, ticket_a)

        assert ok is False
        assert "refusing empty closeout" in err, f"unexpected error message: {err!r}"
        assert files == set()

    def test_non_ancestor_still_rejected(self, tmp_path: Path) -> None:
        """No-regression (Step 2): M3 tagged on a lateral branch not merged
        into HEAD must still be rejected with 'not an ancestor of HEAD'."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        ticket_a = "WOT-2026-AAA"
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        subprocess.run(
            ["git", "checkout", "-b", "lateral"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        sha_a = _make_commit(repo, "file_a.py", "a = 1\n", f"{ticket_a}: implement A")
        _tag_at(repo, f"checkpoint/review-{ticket_a}", sha_a)

        # Move main-line HEAD back to base (lateral commit not an ancestor).
        subprocess.run(
            ["git", "checkout", "master"],
            cwd=repo,
            capture_output=True,
        )
        checkout_main = subprocess.run(
            ["git", "checkout", "main"],
            cwd=repo,
            capture_output=True,
        )
        if checkout_main.returncode != 0:
            subprocess.run(
                ["git", "checkout", base_sha],
                cwd=repo,
                check=True,
                capture_output=True,
            )

        ok, files, err = motor_checkpoint.resolve_motor_checkpoint_files(repo, ticket_a)

        assert ok is False
        assert "not an ancestor of HEAD" in err, f"unexpected error message: {err!r}"
        assert files == set()

    def test_subject_without_ticket_id_still_rejected(self, tmp_path: Path) -> None:
        """No-regression (Step 4): M3 pointing at a real, ancestor commit
        whose subject does NOT contain the ticket_id must still be rejected."""
        import motor_checkpoint

        repo = tmp_path / "repo"
        _init_git_repo(repo)

        ticket_a = "WOT-2026-AAA"
        sha_a = _make_commit(repo, "file_a.py", "a = 1\n", "unrelated: implement A")
        _tag_at(repo, f"checkpoint/review-{ticket_a}", sha_a)

        ok, files, err = motor_checkpoint.resolve_motor_checkpoint_files(repo, ticket_a)

        assert ok is False
        assert "does not contain" in err, f"unexpected error message: {err!r}"
        assert files == set()
