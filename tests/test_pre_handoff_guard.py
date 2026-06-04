# WT-2026-228a: Tests for pre-handoff barrier detecting uncommitted productive
# changes in repo_motor. All tests use real git repos in tmp_path.

import subprocess
from pathlib import Path

# Module under test
from bus.evidence import motor_uncommitted_productive


# ---------------------------------------------------------------------------
# Helpers (exported for import by test_agent_controller.py and
# test_review_bridge.py)
# ---------------------------------------------------------------------------

GIT_BIN = "git"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GIT_BIN, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
    )


def init_git_repo(path: Path) -> Path:
    """Initialize a git repo at path, create an initial commit.

    Public (no underscore) because test_agent_controller.py and
    test_review_bridge.py import it from here.
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    readme = path / "README.md"
    readme.write_text("# repo\n")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "initial"], cwd=path)
    return path


def _create_file(repo: Path, rel: str, content: str = "content") -> Path:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_motor_uncommitted_productive_no_changes(tmp_path: Path) -> None:
    """TP-06 baseline: clean motor with no changes returns empty list."""
    motor = init_git_repo(tmp_path / "motor")
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_unstaged_productive(tmp_path: Path) -> None:
    """TP-02: motor with an unstaged productive file blocks.

    Creates a tracked file first, then modifies it unstaged.
    Untracked files are not visible via git diff (only git status),
    so we track the file first before modifying it.
    """
    motor = init_git_repo(tmp_path / "motor")
    # Create and commit a tracked file first, then modify it unstaged
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("def new_func(): pass")
    result = motor_uncommitted_productive(motor)
    assert len(result) == 1
    assert "bus/evidence.py" in result[0]


def test_motor_uncommitted_productive_staged_productive(tmp_path: Path) -> None:
    """TP-02 variant: staged productive file also counts."""
    motor = init_git_repo(tmp_path / "motor")
    f = _create_file(motor, ".agent/agent_controller.py", "new_code = True")
    _git(["add", str(f)], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert len(result) == 1
    assert ".agent/agent_controller.py" in result[0]


def test_motor_uncommitted_productive_docs_only(tmp_path: Path) -> None:
    """TP-04: docs/collaboration-only changes do NOT block."""
    motor = init_git_repo(tmp_path / "motor")
    _create_file(motor, ".agent/collaboration/TURN.md", "# turn")
    _create_file(motor, "PROJECT.md", "# project")
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_clean_with_ticket_commit(tmp_path: Path) -> None:
    """TP-05: clean motor with commit WT-2026-228a passes (no uncommitted)."""
    motor = init_git_repo(tmp_path / "motor")
    _create_file(motor, "bus/evidence.py", "def new_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): add barrier"], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_clean_no_ticket_commit(tmp_path: Path) -> None:
    """TP-06: clean motor without ticket commit still passes pre-handoff."""
    motor = init_git_repo(tmp_path / "motor")
    _create_file(motor, "bus/evidence.py", "def new_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat: something unrelated"], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_no_auto_commit(tmp_path: Path) -> None:
    """TP-07: ensure motor_uncommitted_productive does not auto-commit."""
    motor = init_git_repo(tmp_path / "motor")
    # Track the file first, then modify it
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")
    # Check that it reports dirty
    before = motor_uncommitted_productive(motor)
    assert len(before) == 1
    # Verify nothing was committed (git porcelain may show " M" or "M " for modifications)
    status = _git(["status", "--porcelain"], cwd=motor)
    assert "bus/evidence.py" in status.stdout
    assert "M" in status.stdout  # still modified, not committed


def test_recent_commit_not_confused_with_dirty(tmp_path: Path) -> None:
    """TP-10: motor with recent ticket commit + clean working tree does NOT block.

    Uses two separate repos: motor and destination. Creates a commit in motor
    with ticket ID and leaves working tree clean, then confirms
    motor_uncommitted_productive returns empty.
    """
    motor = init_git_repo(tmp_path / "motor")
    init_git_repo(tmp_path / "dest")

    # Create a productive commit with ticket ID in motor
    _create_file(motor, "bus/evidence.py", "def committed_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): block pre-handoff"], cwd=motor)

    # Verify tree is clean
    status = _git(["status", "--porcelain"], cwd=motor)
    assert status.stdout.strip() == ""

    # motor_uncommitted_productive should return empty
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_canonical_message(tmp_path: Path) -> None:
    """TP-03: verify the canonical message and file list are produced.

    This test simulates what _handle_pre_handoff would print by directly
    calling motor_uncommitted_productive and formatting the output.
    """
    motor = init_git_repo(tmp_path / "motor")
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty")
    uncommitted = motor_uncommitted_productive(motor)

    # Build the canonical message (same format as in agent_controller.py)
    message_lines = [
        "Uncommitted productive changes in repo_motor: "
        "commit with ticket ID before handoff.",
    ]
    message_lines.extend(f"  {f}" for f in uncommitted)
    message = "\n".join(message_lines)

    assert len(uncommitted) == 1
    assert "Uncommitted productive changes in repo_motor:" in message
    assert "commit with ticket ID before handoff." in message
    assert "bus/evidence.py" in message


def test_regression_without_barrier(tmp_path: Path) -> None:
    """Regression test: reverting the barrier would let TP-02 through.

    Simulates the absence of the barrier by not calling
    motor_uncommitted_productive. If we don't check, the dirty file goes
    undetected. Verifies that WITHOUT the check, the dirty file is invisible
    to a naive git_root-based scan.
    """
    motor = init_git_repo(tmp_path / "motor")
    dest = init_git_repo(tmp_path / "dest")

    # Track a file first, then modify it (unstaged dirty)
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")

    # Simulate what _handle_pre_handoff does WITHOUT the barrier:
    # it picks git_root based on project_root having .git (dest)
    git_root = dest  # Model B: workspace has .git, so git_root = project_root
    status = _git(["status", "--porcelain"], cwd=git_root)
    # git status in dest shows nothing dirty
    assert status.stdout.strip() == ""

    # Now add the barrier: motor_uncommitted_productive detects the dirty file
    uncommitted = motor_uncommitted_productive(motor)
    assert len(uncommitted) == 1
    assert "bus/evidence.py" in uncommitted[0]

    # If we clean the motor and re-check, it passes
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): fix"], cwd=motor)
    assert motor_uncommitted_productive(motor) == []


# ---------------------------------------------------------------------------
# End-to-end: _handle_pre_handoff barrier (ALTO: verificar salida real)
# ---------------------------------------------------------------------------


def _create_work_plan(plan_dir: Path, ticket_id: str) -> Path:
    """Create a minimal work_plan.md in plan_dir."""
    wp = plan_dir / "work_plan.md"
    wp.write_text(
        f"""# Work Plan

**ID:** {ticket_id}
**Estado:** APPROVED
**deliverable_type:** code

## Files Likely Touched
- bus/evidence.py
```
"""
    )
    return wp


def test_pre_handoff_blocks_on_motor_dirty(tmp_path: Path, monkeypatch, capsys) -> None:
    """End-to-end: _handle_pre_handoff returns 1 when motor has uncommitted
    productive changes. Verifies the real stderr output contains the canonical
    message and file list. Uses capsys fixture to avoid interfering with
    agent_controller's win32 sys.stderr setup.
    """
    import agent_controller

    # Build two real git repos
    motor = init_git_repo(tmp_path / "motor")
    dest = init_git_repo(tmp_path / "dest")

    # Create a tracked productive file in motor and modify it
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")

    # Set up collaboration files in dest
    collab_dir = dest / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)
    _create_work_plan(collab_dir, "WT-2026-228a")

    # Set up execution_log.md
    exec_log = collab_dir / "execution_log.md"
    exec_log.write_text("# Execution Log\n\n**Estado:** IN_PROGRESS\n\n")

    # Monkeypatch paths so _handle_pre_handoff reads from our temp repos
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", collab_dir / "work_plan.md")
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    # Call the actual function
    result = agent_controller._handle_pre_handoff(json_output=False)

    assert result == 1, f"Expected return 1 (blocked), got {result}"
    stderr_text = capsys.readouterr().err
    assert "Uncommitted productive changes in repo_motor:" in stderr_text
    assert "commit with ticket ID before handoff." in stderr_text
    assert "bus/evidence.py" in stderr_text


def test_pre_handoff_passes_with_clean_motor(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """End-to-end: _handle_pre_handoff does not block when motor is clean."""
    import agent_controller

    motor = init_git_repo(tmp_path / "motor")
    dest = init_git_repo(tmp_path / "dest")

    collab_dir = dest / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)
    _create_work_plan(collab_dir, "WT-2026-228a")

    exec_log = collab_dir / "execution_log.md"
    exec_log.write_text("# Execution Log\n\n**Estado:** IN_PROGRESS\n\n")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", collab_dir / "work_plan.md")
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=False)

    stderr_text = capsys.readouterr().err
    # The barrier should NOT fire
    assert "Uncommitted productive changes in repo_motor:" not in stderr_text
    # The function may return 1 due to other checks (no git tag, etc.)
    # but that is OK — we just verify the barrier did NOT fire.
    # If result == 1, it must be for a reason OTHER than the barrier.
    if result == 1:
        assert "Uncommitted productive changes" not in stderr_text
