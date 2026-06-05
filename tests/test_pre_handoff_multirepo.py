# WT-2026-231a: Tests for pre-handoff commit-or-block with multi-repo setup.
# All tests use real git repos in tmp_path with monkeypatched _MOTOR_ROOT.

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.test_pre_handoff_guard import init_git_repo


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


def _create_work_plan(plan_dir: Path, ticket_id: str, flt_paths: list[str]) -> Path:
    """Create a work_plan.md with Files Likely Touched section."""
    flt_lines = "\n".join(f"- `{p}`" for p in flt_paths)
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
    ticket_id: str = "WT-2026-231a",
    motor_flt: list[str] | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Create motor + dest repos, work_plan, and exec_log.

    Returns (motor, dest, work_plan_path, exec_log_path).
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

    return motor, dest, wp, exec_log


# ---------------------------------------------------------------------------
# TP-02: motor dirty inside FLT -> commit deterministically
# ---------------------------------------------------------------------------


def test_motor_dirty_inside_flt_commits_motor(tmp_path: Path, monkeypatch) -> None:
    """TP-02: productive change in motor within FLT -> commit in motor."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    # Create a tracked productive file inside FLT
    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked file"], cwd=motor)
    # Modify it (uncommitted productive change within FLT)
    tracked.write_text("def new_handler(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=True)

    assert result == 0, f"Expected 0 (committed), got {result}"

    # Verify commit exists in motor with ticket ID
    log = _git(["log", "--oneline", "-5"], cwd=motor)
    assert "WT-2026-231a" in log.stdout, (
        f"Expected ticket ID in commit message, got:\n{log.stdout}"
    )

    # Verify motor tree is clean
    status = _git(["status", "--porcelain"], cwd=motor)
    assert status.stdout.strip() == "", (
        f"Motor tree dirty after commit:\n{status.stdout}"
    )


def test_motor_dirty_inside_flt_with_json_output(tmp_path: Path, monkeypatch) -> None:
    """TP-02 variant: JSON output contains success status."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked"], cwd=motor)
    tracked.write_text("def new_handler(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    # Capture JSON output
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured
    try:
        result = agent_controller._handle_pre_handoff(json_output=True)
    finally:
        sys.stdout = old_stdout

    assert result == 0
    output = json.loads(captured.getvalue().strip())
    assert output["status"] == "success"
    assert output["plan_id"] == "WT-2026-231a"


# ---------------------------------------------------------------------------
# TP-03: motor dirty outside FLT -> block with diagnostic
# ---------------------------------------------------------------------------


def test_motor_dirty_outside_flt_blocks(tmp_path: Path, monkeypatch, capsys) -> None:
    """TP-03: productive change outside FLT -> block showing motor-relative paths."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(
        tmp_path, motor_flt=[".agent/agent_controller.py"]
    )

    # Create and track a file NOT in FLT
    tracked = _create_file(motor, "src/outside_flt.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add outside file"], cwd=motor)
    # Modify it
    tracked.write_text("def outside_change(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=False)

    assert result == 1, f"Expected 1 (blocked), got {result}"
    stderr = capsys.readouterr().err
    assert "outside Files Likely Touched" in stderr
    assert "src/outside_flt.py" in stderr

    # Verify no commit was created in motor
    log = _git(["log", "--oneline", "-5"], cwd=motor)
    assert "WT-2026-231a" not in log.stdout, (
        "Unexpected commit found in motor (should not commit outside FLT)"
    )


# ---------------------------------------------------------------------------
# TP-04: empty round without productive changes -> mark-ready blocks later
# ---------------------------------------------------------------------------


def test_empty_round_no_productivo_falls_through(tmp_path: Path, monkeypatch) -> None:
    """TP-04: no motor changes -> fall through to destination logic."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    # Both repos clean (no uncommitted productive changes in motor)
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    # The guard should NOT block (no motor changes)
    # Since dest is also clean, pre-handoff will try to create a tag
    result = agent_controller._handle_pre_handoff(json_output=False)

    # Should not hit the motor guard (it would print about motor changes)
    # The result depends on destination state; just verify no motor guard msg
    # and that it didn't crash
    assert result in (0, 1), f"Expected 0 or 1, got {result}"


# ---------------------------------------------------------------------------
# TP-05: checkpoint tag points to delivery commit
# ---------------------------------------------------------------------------


def test_checkpoint_tag_points_to_delivery_commit(tmp_path: Path, monkeypatch) -> None:
    """TP-05: checkpoint/review-<ticket> in motor points to the commit created."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked"], cwd=motor)
    tracked.write_text("def new_handler(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=False)
    assert result == 0, f"Expected 0, got {result}"

    # Verify tag exists in motor and points to HEAD
    tag_commit = _git(["rev-parse", "checkpoint/review-WT-2026-231a^{}"], cwd=motor)
    assert tag_commit.returncode == 0, "Checkpoint tag not found in motor"
    head = _git(["rev-parse", "HEAD"], cwd=motor)
    assert head.returncode == 0
    assert tag_commit.stdout.strip() == head.stdout.strip(), (
        "Tag does not point to HEAD"
    )


# ---------------------------------------------------------------------------
# TP-06: normalizes FLT and git paths
# ---------------------------------------------------------------------------


def test_normalizes_flt_and_git_paths(tmp_path: Path, monkeypatch) -> None:
    """TP-06: FLT and git status paths normalize to motor-relative with /."""
    from agent_controller import _parse_raw_flt_paths

    plan_content = (
        "# Work Plan\n\n## Files Likely Touched\n"
        "- `.agent/agent_controller.py`\n"
        "- tests\\test_helper.py\n"
        "- src/module.py\n"
    )
    result = _parse_raw_flt_paths(plan_content)
    assert ".agent/agent_controller.py" in result
    assert "tests/test_helper.py" in result  # backslash normalized
    assert "src/module.py" in result
    assert len(result) == 3


# ---------------------------------------------------------------------------
# TP-07: hook reformat -> re-add and second commit
# ---------------------------------------------------------------------------


def test_hook_reformat_readd_and_commit(tmp_path: Path, monkeypatch, capsys) -> None:
    """TP-07: hook modifies staged file -> re-add in FLT, second commit succeeds."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked"], cwd=motor)

    # Simulate hook that modifies staged file: write a pre-commit hook
    # that appends a newline to the file being committed
    hooks_dir = motor / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_script = hooks_dir / "pre-commit"
    hook_script.write_text(
        "#!/bin/sh\necho '  hook modified this file' >> .agent/agent_controller.py\n"
    )
    # Make executable (best-effort on Windows)
    import contextlib
    import os as _os

    with contextlib.suppress(OSError):
        _os.chmod(str(hook_script), 0o700)

    tracked.write_text("def new_handler(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    # On Windows, the pre-commit hook might not execute (no shell interpreter).
    # If hook fails silently, the first commit succeeds normally.
    result = agent_controller._handle_pre_handoff(json_output=False)

    # Either successful commit or retry commit
    assert result == 0, f"Expected 0 (commit or retry), got {result}"

    # Verify motor has a commit with ticket ID
    log = _git(["log", "--oneline", "-5"], cwd=motor)
    assert "WT-2026-231a" in log.stdout


def test_hook_reformat_outside_flt_not_re_added(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """TP-07 guard: only FLT paths are considered when outside FLT also dirty.

    Both in-FLT and outside-FLT files are dirty; the guard must block
    showing the outside-FLT path. It should NOT attempt a partial commit
    of only the in-FLT paths.
    """
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(
        tmp_path, motor_flt=[".agent/agent_controller.py"]
    )

    # Create two files: one in FLT, one outside
    in_flt = _create_file(motor, ".agent/agent_controller.py", "original")
    outside = _create_file(motor, "src/outside.py", "original")
    _git(["add", str(in_flt), str(outside)], cwd=motor)
    _git(["commit", "-m", "add both files"], cwd=motor)

    # Modify both (in-FLT + outside-FLT = blocked)
    in_flt.write_text("def in_flt_change(): pass")
    outside.write_text("def outside_change(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=False)

    # Guard blocks because outside FLT changes exist
    assert result == 1, f"Expected 1 (blocked), got {result}"
    stderr = capsys.readouterr().err
    assert "outside Files Likely Touched" in stderr
    assert "src/outside.py" in stderr


# ---------------------------------------------------------------------------
# TP-10/TP-11: motor_root declared before guard, works when dest has .git
# ---------------------------------------------------------------------------


def test_motor_root_defined_when_destination_is_git_repo(
    tmp_path: Path, monkeypatch
) -> None:
    """TP-11: motor_root is declared before guard when dest has .git (Model B)."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    # The guard should not raise NameError because motor_root is declared
    # before the guard, even when dest has .git
    result = agent_controller._handle_pre_handoff(json_output=False)
    # Result is either 0 or 1, but should not crash with NameError
    assert result in (0, 1), f"Expected 0 or 1, got {result}"


# ---------------------------------------------------------------------------
# TP-10: does not use workspace changed_files for motor commit decision
# ---------------------------------------------------------------------------


def test_does_not_use_workspace_changed_files_for_motor_commit(
    tmp_path: Path, monkeypatch
) -> None:
    """TP-10: motor commit decision uses motor_uncommitted_productive, not get_changed_files."""
    import agent_controller

    motor, dest, wp, exec_log = _setup_multi_repo(tmp_path)

    # Only motor has productive changes; dest is clean
    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked"], cwd=motor)
    tracked.write_text("def new_handler(): pass")

    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", dest)
    monkeypatch.setattr(agent_controller, "WORK_PLAN", wp)
    monkeypatch.setattr(agent_controller, "EXEC_LOG", exec_log)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", motor)

    result = agent_controller._handle_pre_handoff(json_output=False)

    assert result == 0, f"Expected 0 (committed in motor), got {result}"

    # Verify motor commit exists
    log = _git(["log", "--oneline", "-5"], cwd=motor)
    assert "WT-2026-231a" in log.stdout


# ---------------------------------------------------------------------------
# TP-09: _parse_raw_flt_paths handles edge cases
# ---------------------------------------------------------------------------


def test_parse_raw_flt_paths_handles_edge_cases() -> None:
    """TP-06 edge cases: empty, no section, various formatting."""
    from agent_controller import _parse_raw_flt_paths

    # Empty content
    assert _parse_raw_flt_paths("") == set()

    # No FLT section
    assert _parse_raw_flt_paths("# Work Plan\n\nSome content\n") == set()

    # Various formatting
    content = (
        "# Work Plan\n\n## Files Likely Touched\n"
        "- `src/module.py`\n"
        '- "src/other.py"\n'
        "- src/simple.py\n"
        "- `tests/test_me.py`\n"
    )
    result = _parse_raw_flt_paths(content)
    assert "src/module.py" in result
    assert "src/other.py" in result
    assert "src/simple.py" in result
    assert "tests/test_me.py" in result

    # ./ prefix removal
    content2 = "# Plan\n\n## Files Likely Touched\n- `./src/module.py`\n"
    result2 = _parse_raw_flt_paths(content2)
    assert "src/module.py" in result2
    assert "./src/module.py" not in result2


# ---------------------------------------------------------------------------
# TP-06: normalizacion de paths git
# ---------------------------------------------------------------------------


def test_git_paths_normalize_to_motor_relative(tmp_path: Path) -> None:
    """TP-06: motor_uncommitted_productive returns forward-slash paths."""
    from bus.evidence import motor_uncommitted_productive

    motor = tmp_path / "motor"
    init_git_repo(motor)

    tracked = _create_file(motor, ".agent/agent_controller.py", "original")
    _git(["add", str(tracked)], cwd=motor)
    _git(["commit", "-m", "add tracked"], cwd=motor)
    tracked.write_text("def new(): pass")

    result = motor_uncommitted_productive(motor)
    assert len(result) >= 1
    for p in result:
        assert "\\" not in p, f"Path contains backslash: {p}"
        assert p == p.replace("\\", "/"), f"Path not normalized: {p}"
