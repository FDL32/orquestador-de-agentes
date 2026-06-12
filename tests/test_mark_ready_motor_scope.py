# WT-2026-232a: Tests for motor-aware scope gate in mark-ready.
# All tests use real git repos in tmp_path with monkeypatched globals.

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

from tests.test_pre_handoff_guard import init_git_repo


GIT_BIN = "git"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GIT_BIN, *args], capture_output=True, text=True, cwd=cwd, timeout=30
    )


def _create_file(repo: Path, rel: str, content: str = "content") -> Path:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


def _create_work_plan(
    plan_dir: Path, ticket_id: str = "WT-2026-232a", flt_paths: list[str] | None = None
) -> Path:
    """Create work_plan.md with Files Likely Touched section."""
    flt = flt_paths or [".agent/agent_controller.py"]
    flt_lines = "\n".join(f"- `{p}`" for p in flt)
    wp = plan_dir / "work_plan.md"
    wp.write_text(
        f"# Work Plan\n\n"
        f"## Metadata\n"
        f"- **ID:** {ticket_id}\n"
        f"- **Estado:** APPROVED\n"
        f"- **deliverable_type:** code\n\n"
        f"## Files Likely Touched\n{flt_lines}\n"
    )
    return wp


def _setup_multi_repo(
    tmp_path: Path,
    ticket_id: str = "WT-2026-232a",
    motor_flt: list[str] | None = None,
) -> tuple[Path, Path, Path, Path, str]:
    """Create motor + dest repos with work_plan and exec_log.

    Returns (motor, dest, work_plan_path, exec_log_path, plan_content).
    """
    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

    collab_dir = dest / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)

    flt = motor_flt or [".agent/agent_controller.py"]
    wp = _create_work_plan(collab_dir, ticket_id, flt)
    exec_log = collab_dir / "execution_log.md"
    exec_log.write_text("# Execution Log\n\n**Estado:** IN_PROGRESS\n\n")
    runtime_dir = dest / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    plan_content = wp.read_text()
    return motor, dest, wp, exec_log, plan_content


def _monkeypatch_mark_ready(
    monkeypatch,
    agent_controller,
    motor: Path,
    dest: Path,
    wp: Path,
    exec_log: Path,
    plan_content: str,
    plan_id: str = "WT-2026-232a",
) -> None:
    """Set up standard monkeypatches for testing _handle_mark_ready.

    Disables bus, evidence gates, pre-handoff guard, and side-effect emissions
    so the scope gate logic can be tested in isolation.
    """
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
    monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
    monkeypatch.setattr(
        agent_controller,
        "_load_mark_ready_context",
        lambda: (plan_content, exec_log.read_text(), plan_id),
    )
    monkeypatch.setattr(
        agent_controller,
        "_ensure_active_builder_round",
        lambda *a, **kw: (True, None, None),
    )
    monkeypatch.setattr(
        agent_controller,
        "_check_implementation_evidence",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        agent_controller,
        "_run_pre_handoff_guard",
        lambda *a, **kw: {"valid": True},
    )
    monkeypatch.setattr(agent_controller, "_emit_builder_exit", lambda *a, **kw: None)
    monkeypatch.setattr(
        agent_controller, "_sync_mark_ready_targets", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        agent_controller, "_reset_circuit_breaker", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        agent_controller, "_release_builder_lock", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        agent_controller, "_auto_archive_closed_artifacts", lambda: None
    )


def _create_checkpoint(
    motor: Path, file_rel: str, ticket_id: str, content: str = "code"
) -> None:
    """Create a tracked file, commit it with ticket_id, and tag as checkpoint."""
    f = _create_file(motor, file_rel, content)
    _git(["add", str(f)], cwd=motor)
    _git(["commit", "-m", f"feat({ticket_id}): implement {file_rel}"], cwd=motor)
    _git(
        ["tag", "-a", f"checkpoint/review-{ticket_id}", "-m", f"M3 for {ticket_id}"],
        cwd=motor,
    )


# ---------------------------------------------------------------------------
# TP-01: motor commit inside FLT -> mark-ready passes without --scope-override
# ---------------------------------------------------------------------------


class TestMotorScopeInsideFLT:
    """TP-01: productive motor changes within FLT -> mark-ready passes."""

    def test_motor_commit_inside_flt_passes(self, tmp_path: Path, monkeypatch) -> None:
        """Motor checkpoint with files inside FLT passes mark-ready."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)
        _create_checkpoint(motor, ".agent/agent_controller.py", "WT-2026-232a")

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        # Should pass without scope-override
        assert result == 0, f"Expected 0 (pass), got {result}"

    def test_motor_commit_inside_flt_json_output(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Verify JSON output contains marked_ready status."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)
        _create_checkpoint(motor, ".agent/agent_controller.py", "WT-2026-232a")

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        old_stdout = sys.stdout
        captured = StringIO()
        sys.stdout = captured
        try:
            result = agent_controller._handle_mark_ready(
                scope_override=None, json_output=True, force_mode=False
            )
        finally:
            sys.stdout = old_stdout

        assert result == 0
        output = json.loads(captured.getvalue().strip())
        assert output["status"] == "marked_ready"


# ---------------------------------------------------------------------------
# TP-02: motor commit outside FLT -> blocks with motor-relative paths
# ---------------------------------------------------------------------------


class TestMotorScopeOutsideFLT:
    """TP-02: motor checkpoint with files outside FLT -> blocks."""

    def test_motor_commit_outside_flt_blocks(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Motor checkpoint outside FLT blocks showing motor-relative paths."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(
            tmp_path, motor_flt=[".agent/agent_controller.py"]
        )
        # Create checkpoint touching a file NOT in FLT
        _create_checkpoint(motor, "src/outside.py", "WT-2026-232a")

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        assert result == 1, f"Expected 1 (blocked), got {result}"
        captured = capsys.readouterr()
        assert (
            "outside Files Likely Touched" in captured.out or "outside" in captured.out
        )


# ---------------------------------------------------------------------------
# TP-03: no motor evidence -> blocks
# ---------------------------------------------------------------------------


class TestMotorNoEvidence:
    """TP-03: no motor checkpoint or evidence -> blocks."""

    def test_no_motor_checkpoint_blocks(self, tmp_path: Path, monkeypatch) -> None:
        """No checkpoint tag exists; mark-ready blocks."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)
        # Motor has a commit but NO checkpoint tag
        _create_file(motor, ".agent/agent_controller.py", "code")
        _git(["add", "."], cwd=motor)
        _git(["commit", "-m", "feat: implement without checkpoint"], cwd=motor)

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        assert result == 1, f"Expected 1 (blocked), got {result}"

    def test_stale_ancestor_checkpoint_blocks(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Ancestor checkpoints must block when they do not anchor the current HEAD."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)
        _create_checkpoint(motor, ".agent/agent_controller.py", "WT-2026-232a")
        _create_file(motor, "README.md", "post-checkpoint change")
        _git(["add", "."], cwd=motor)
        _git(["commit", "-m", "feat: commit after checkpoint"], cwd=motor)

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        assert result == 1, f"Expected 1 (blocked), got {result}"


# ---------------------------------------------------------------------------
# TP-04: FLT resolved against motor, not destination
# ---------------------------------------------------------------------------


class TestFLTResolvedMotorRelative:
    """TP-04: FLT parsing resolves motor-relative paths."""

    def test_flt_not_resolved_against_destination(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Destination has homonymous file but motor checkpoint uses motor-relative FLT."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)

        # Create homonymous file in destination (shouldn't affect scope)
        _create_file(dest, ".agent/agent_controller.py", "dest version")

        # Motor checkpoint touches .agent/agent_controller.py (motor-relative FLT)
        _create_checkpoint(motor, ".agent/agent_controller.py", "WT-2026-232a")

        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        assert result == 0, f"Expected 0 (pass), got {result}"


# ---------------------------------------------------------------------------
# TP-05: stale/historical ticket commit not at checkpoint -> blocks
# ---------------------------------------------------------------------------


class TestStaleCommitRejected:
    """TP-05: historical commit with ticket_id but no valid checkpoint -> blocks."""

    def test_stale_commit_not_at_checkpoint_blocks(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Checkpoint tag exists but points to a stale commit not reachable from HEAD."""
        import agent_controller

        motor, dest, wp, exec_log, plan_content = _setup_multi_repo(tmp_path)

        # Create commit on a branch that is NOT merged
        _git(["checkout", "-b", "stale-branch"], cwd=motor)
        _create_checkpoint(motor, "src/stale.py", "WT-2026-232a")

        # Go back to main branch and create divergent history
        _git(["checkout", "main"], cwd=motor)
        _create_file(motor, "README.md", "new content")
        _git(["add", "."], cwd=motor)
        _git(["commit", "-m", "divergent change on main"], cwd=motor)

        # The checkpoint tag from stale-branch is NOT an ancestor of HEAD
        _monkeypatch_mark_ready(
            monkeypatch, agent_controller, motor, dest, wp, exec_log, plan_content
        )

        result = agent_controller._handle_mark_ready(
            scope_override=None, json_output=True, force_mode=False
        )
        assert result == 1, f"Expected 1 (blocked), got {result}"


# ---------------------------------------------------------------------------
# Regression: WT-2026-231a pre-handoff still works
# ---------------------------------------------------------------------------


class TestRegressionPreHandoff:
    """Regression: pre-handoff still commits and tags motor."""

    def test_pre_handoff_still_commits_motor(self, tmp_path: Path, monkeypatch) -> None:
        """Pre-handoff commits motor changes within FLT (WT-2026-231a regression)."""
        import agent_controller

        motor, dest, wp, exec_log, _plan_content = _setup_multi_repo(tmp_path)

        # Create tracked productive file inside FLT, then modify it
        tracked = _create_file(motor, ".agent/agent_controller.py", "original")
        _git(["add", str(tracked)], cwd=motor)
        _git(["commit", "-m", "add tracked file"], cwd=motor)
        tracked.write_text("def new_handler(): pass")

        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
        monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
        monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
        # Bypass stale-Builder-shell guard so test works regardless of
        # AGENT_BUILDER_TICKET in the calling shell (same pattern as
        # _monkeypatch_mark_ready uses for mark-ready tests).
        monkeypatch.setattr(
            agent_controller,
            "_ensure_active_builder_round",
            lambda *a, **kw: (True, None, None),
        )

        result = agent_controller._handle_pre_handoff(json_output=True)

        assert result == 0, f"Expected 0 (committed), got {result}"

        # Verify commit exists in motor with ticket ID
        log = _git(["log", "--oneline", "-5"], cwd=motor)
        assert "WT-2026-232a" in log.stdout, (
            f"Expected ticket ID in commit message, got:\n{log.stdout}"
        )

        # Verify checkpoint tag exists
        tag_check = _git(["rev-parse", "checkpoint/review-WT-2026-232a"], cwd=motor)
        assert tag_check.returncode == 0, "Checkpoint tag should exist"


# ---------------------------------------------------------------------------
# Unit test for _resolve_motor_checkpoint_files
# ---------------------------------------------------------------------------


class TestResolveMotorCheckpointFiles:
    """Direct unit tests for _resolve_motor_checkpoint_files helper."""

    def test_valid_checkpoint_returns_files(self, tmp_path: Path) -> None:
        """Valid checkpoint tag returns the files from that commit."""
        import agent_controller

        motor = tmp_path / "motor"
        init_git_repo(motor)

        _create_checkpoint(motor, "src/feature.py", "TICKET-1")

        valid, files, error = agent_controller._resolve_motor_checkpoint_files(
            motor, "TICKET-1"
        )
        assert valid, f"Expected valid checkpoint, got error: {error}"
        assert "src/feature.py" in files, f"Expected src/feature.py in {files}"

    def test_checkpoint_includes_contiguous_ticket_commits(
        self, tmp_path: Path
    ) -> None:
        """Scope evidence includes every contiguous ticket commit before the tag."""
        import agent_controller

        motor = tmp_path / "motor"
        init_git_repo(motor)

        _create_file(motor, "src/outside.py", "first")
        _git(["add", "."], cwd=motor)
        _git(["commit", "-m", "feat(TICKET-1): first delivery commit"], cwd=motor)
        _create_checkpoint(motor, "src/inside.py", "TICKET-1")

        valid, files, error = agent_controller._resolve_motor_checkpoint_files(
            motor, "TICKET-1"
        )

        assert valid, error
        assert files == {"src/outside.py", "src/inside.py"}

    def test_missing_tag_returns_invalid(self, tmp_path: Path) -> None:
        """Missing checkpoint tag returns invalid."""
        import agent_controller

        motor = tmp_path / "motor"
        init_git_repo(motor)

        valid, _files, error = agent_controller._resolve_motor_checkpoint_files(
            motor, "NONEXISTENT"
        )
        assert not valid
        assert "not found" in error

    def test_non_ancestor_tag_returns_invalid(self, tmp_path: Path) -> None:
        """Tag pointing to non-ancestor commit returns invalid."""
        import agent_controller

        motor = tmp_path / "motor"
        init_git_repo(motor)

        # Create commit on detached branch, tag it, then diverge.
        # Capture the default branch first: git init yields main or master
        # depending on host config (CI runners default to master), and a
        # silent failed checkout would put the divergent commit ON TOP of
        # the tag, turning this into the wrong scenario.
        base_branch = _git(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=motor
        ).stdout.strip()
        _git(["checkout", "-b", "orphan-branch"], cwd=motor)
        _create_checkpoint(motor, "src/orphan.py", "TICKET-1")
        checkout = _git(["checkout", base_branch], cwd=motor)
        assert checkout.returncode == 0, checkout.stderr
        _create_file(motor, "README.md", "divergent")
        _git(["add", "."], cwd=motor)
        _git(["commit", "-m", "divergent change"], cwd=motor)

        valid, _files, error = agent_controller._resolve_motor_checkpoint_files(
            motor, "TICKET-1"
        )
        assert not valid
        assert "not an ancestor" in error

    def test_ancestor_but_not_head_returns_invalid(self, tmp_path: Path) -> None:
        """Tag on an older ancestor commit must fail; handoff requires tag == HEAD."""
        import agent_controller

        motor = tmp_path / "motor"
        init_git_repo(motor)

        _create_checkpoint(motor, "src/base.py", "TICKET-1")
        _create_file(motor, "src/newer.py", "newer")
        _git(["add", "."], cwd=motor)
        _git(
            ["commit", "-m", "feat(TICKET-1): newer commit after checkpoint"],
            cwd=motor,
        )

        valid, _files, error = agent_controller._resolve_motor_checkpoint_files(
            motor, "TICKET-1"
        )
        assert not valid
        assert "stale" in error


class TestFallbackCheckpointMotor:
    """Fallback only repairs a missing destination checkpoint."""

    def test_dirty_tree_remains_blocked(self, tmp_path: Path, monkeypatch) -> None:
        """A motor checkpoint must not hide an independent dirty-tree failure."""
        import agent_controller

        motor = tmp_path / "motor"
        dest = tmp_path / "dest"
        init_git_repo(motor)
        init_git_repo(dest)
        _create_checkpoint(motor, "src/feature.py", "WT-2026-232a")
        monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)

        result = agent_controller._fallback_checkpoint_motor(
            {
                "valid": False,
                "missing_checkpoint": True,
                "dirty_tree": True,
                "dirty_files": ["uncommitted.py"],
            },
            "WT-2026-232a",
        )

        assert result["valid"] is False
        assert result["missing_checkpoint"] is True
        assert result["dirty_tree"] is True
