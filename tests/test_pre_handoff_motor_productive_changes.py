# WT-2026-228a: Tests for pre-handoff barrier detecting uncommitted productive
# changes in repo_motor. All tests use real git repos in tmp_path.

import subprocess
from pathlib import Path

from bus.evidence import motor_uncommitted_productive

from tests.test_pre_handoff_guard import init_git_repo


# ---------------------------------------------------------------------------
# Helpers
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


def _create_file(repo: Path, rel: str, content: str = "content") -> Path:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


def test_motor_uncommitted_productive_no_changes(tmp_path: Path) -> None:
    """TP-06 baseline: clean motor with no changes returns empty list."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_unstaged_productive(tmp_path: Path) -> None:
    """TP-02: unstaged modification to tracked productive file is detected."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("def new_func(): pass")
    result = motor_uncommitted_productive(motor)
    assert len(result) == 1
    assert "bus/evidence.py" in result[0]


def test_motor_uncommitted_productive_staged_productive(tmp_path: Path) -> None:
    """TP-02 variant: staged productive file is detected."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    f = _create_file(motor, ".agent/agent_controller.py", "new_code = True")
    _git(["add", str(f)], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert len(result) == 1
    assert ".agent/agent_controller.py" in result[0]


def test_motor_uncommitted_productive_untracked_productive(tmp_path: Path) -> None:
    """ALTO-2 fix: untracked productive file (never git add) is detected.

    A Builder can create bus/new_feature.py without running git add.
    Without git ls-files --others, this file would be invisible to the barrier.
    """
    motor = tmp_path / "motor"
    init_git_repo(motor)
    # Create a new productive file without staging it
    _create_file(motor, "bus/new_feature.py", "def new_feature(): pass")
    result = motor_uncommitted_productive(motor)
    assert len(result) == 1
    assert "bus/new_feature.py" in result[0]


def test_motor_uncommitted_productive_untracked_docs_not_blocked(
    tmp_path: Path,
) -> None:
    """ALTO-2 fix: untracked docs/collaboration files do NOT block."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _create_file(motor, ".agent/collaboration/TURN.md", "# turn")
    _create_file(motor, "PROJECT.md", "# project")
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_docs_only(tmp_path: Path) -> None:
    """TP-04: staged docs/collaboration-only changes do NOT block."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _create_file(motor, ".agent/collaboration/TURN.md", "# turn")
    _create_file(motor, "PROJECT.md", "# project")
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_clean_with_ticket_commit(tmp_path: Path) -> None:
    """TP-05: clean motor with commit WT-2026-228a passes (no uncommitted)."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _create_file(motor, "bus/evidence.py", "def new_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): add barrier"], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_motor_uncommitted_productive_clean_no_ticket_commit(tmp_path: Path) -> None:
    """TP-06: clean motor without ticket commit passes pre-handoff barrier."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _create_file(motor, "bus/evidence.py", "def new_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat: something unrelated"], cwd=motor)
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_no_auto_commit(tmp_path: Path) -> None:
    """TP-07: motor_uncommitted_productive does not auto-commit."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")
    before = motor_uncommitted_productive(motor)
    assert len(before) == 1
    status = _git(["status", "--porcelain"], cwd=motor)
    assert "bus/evidence.py" in status.stdout
    assert "M" in status.stdout


def test_recent_commit_not_confused_with_dirty(tmp_path: Path) -> None:
    """TP-10: motor with recent ticket commit + clean tree does NOT block."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    _create_file(motor, "bus/evidence.py", "def committed_func(): pass")
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): block pre-handoff"], cwd=motor)
    status = _git(["status", "--porcelain"], cwd=motor)
    assert status.stdout.strip() == ""
    result = motor_uncommitted_productive(motor)
    assert result == []


def test_canonical_message(tmp_path: Path) -> None:
    """TP-03: canonical message and file list are produced correctly."""
    motor = tmp_path / "motor"
    init_git_repo(motor)
    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty")
    uncommitted = motor_uncommitted_productive(motor)

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
    """Regression: without the barrier, motor dirty files are invisible.

    Simulates the pre-fix behavior: _handle_pre_handoff uses git_root=dest,
    so git status in dest shows nothing dirty. Verifies the fix detects it.
    """
    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")

    # Pre-fix behavior: git status in workspace (dest) sees nothing
    git_root = dest
    status = _git(["status", "--porcelain"], cwd=git_root)
    assert status.stdout.strip() == ""

    # Fix: motor_uncommitted_productive detects the dirty file in motor
    uncommitted = motor_uncommitted_productive(motor)
    assert len(uncommitted) == 1
    assert "bus/evidence.py" in uncommitted[0]

    # After committing, barrier passes
    _git(["add", "bus/evidence.py"], cwd=motor)
    _git(["commit", "-m", "feat(WT-2026-228a): fix"], cwd=motor)
    assert motor_uncommitted_productive(motor) == []


# ---------------------------------------------------------------------------
# End-to-end: _handle_pre_handoff barrier
# ---------------------------------------------------------------------------


def _create_work_plan(plan_dir: Path, ticket_id: str) -> Path:
    wp = plan_dir / "work_plan.md"
    wp.write_text(
        f"# Work Plan\n\n**ID:** {ticket_id}\n**Estado:** APPROVED\n"
        f"**deliverable_type:** code\n\n## Files Likely Touched\n- bus/evidence.py\n"
    )
    return wp


def test_pre_handoff_auto_commits_motor_dirty_within_flt(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """E2E TP-02: _handle_pre_handoff auto-commits productive changes inside FLT."""
    import agent_controller

    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

    tracked = _create_file(motor, "bus/evidence.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    tracked.write_text("dirty content")

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

    captured = capsys.readouterr()
    assert result == 0, f"Expected return 0 (auto-commit), got {result}"
    assert (
        "Productive changes in repo_motor outside Files Likely Touched:"
        not in captured.err
    )
    assert (
        "[OK] Committed in repo_motor: chore(WT-2026-228a): pre-handoff checkpoint"
        in captured.out
    )
    assert (
        "[OK] Pre-handoff complete for WT-2026-228a. Motor committed." in captured.out
    )
    status = _git(["status", "--porcelain"], cwd=motor)
    assert status.stdout.strip() == ""
    log = _git(["log", "--oneline", "-1"], cwd=motor)
    assert "WT-2026-228a" in log.stdout


def test_pre_handoff_blocks_on_motor_untracked(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """E2E ALTO-2: _handle_pre_handoff returns 1 when motor has untracked productive file."""
    import agent_controller

    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

    # Create untracked productive file (never git add)
    _create_file(motor, "bus/new_feature.py", "def new_feature(): pass")

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

    assert result == 1, f"Expected return 1 (blocked on untracked), got {result}"
    stderr_text = capsys.readouterr().err
    assert (
        "Productive changes in repo_motor outside Files Likely Touched:" in stderr_text
    )
    assert "bus/new_feature.py" in stderr_text


def test_pre_handoff_passes_with_clean_motor(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """E2E TP-05/06: _handle_pre_handoff does not block when motor is clean."""
    import agent_controller

    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)

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
    assert "Uncommitted productive changes in repo_motor:" not in stderr_text
    if result == 1:
        assert "Uncommitted productive changes" not in stderr_text
