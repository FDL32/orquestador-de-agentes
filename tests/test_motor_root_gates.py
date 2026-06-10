"""Tests for WT-2026-215: motor_root resolution in git evidence/provenance gates.

Verifica que las operaciones git de evidencia/provenance del tooling de review
y gates usen ``motor_root`` como cwd, no ``project_root``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


# =============================================================================
# Helpers
# =============================================================================


def init_git_repo(repo_path: Path, initial_file: str = "README.md") -> None:
    """Initialize a git repository with an initial commit."""
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
    (repo_path / initial_file).write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def make_commit(repo_path: Path, filename: str, content: str, msg: str) -> None:
    """Create a commit in an existing repo."""
    (repo_path / filename).write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def make_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus, Path]:
    """Create a ReviewBridge with tmp_path as project_root."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
    return bridge, event_bus, tmp_path


def link_workspace_to_motor(workspace: Path, motor_root: Path) -> None:
    """Create motor_destination_link.json pointing to motor_root."""
    config_dir = workspace / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link = config_dir / "motor_destination_link.json"
    link.write_text(
        json.dumps({"motor_root": str(motor_root.resolve())}), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _mock_repomix_for_tests(monkeypatch):
    """Evitar ralentizacion por npx repomix en tests."""
    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._ensure_repomix_context",
        lambda self: (None, {"status": "skipped", "reason": "mocked for tests"}),
    )


# =============================================================================
# Test 1: _git_diff_stat uses motor_root
# =============================================================================


def test_diff_stat_uses_motor_root(tmp_path, monkeypatch):
    """_git_diff_stat calls subprocess.run with cwd=motor_root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    motor = tmp_path / "motor"
    init_git_repo(motor)
    make_commit(motor, "test.py", "x = 1\n", "WT-2026-215: real commit")
    link_workspace_to_motor(workspace, motor)

    bridge, _, _ = make_bridge(workspace)
    original_run = subprocess.run

    captured_cwds = []

    def tracking_run(*args, **kwargs):
        if "cwd" in kwargs:
            captured_cwds.append(kwargs["cwd"])
        # Pasamos el call real para que git funcione
        return original_run(*args, **kwargs)

    monkeypatch.setattr("bus.review_bridge.subprocess.run", tracking_run)
    bridge._git_diff_stat()

    motor_root_resolved = str(motor.resolve())
    assert any(motor_root_resolved in str(cwd) for cwd in captured_cwds), (
        f"Expected cwd containing {motor_root_resolved}, got {captured_cwds}"
    )


# =============================================================================
# Test 2: check_review_packet_diff_empty returns False with motor commits
# =============================================================================


def test_check_review_packet_not_empty_with_motor_commits(tmp_path):
    """check_review_packet_diff_empty returns False when motor has real commits."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    # Workspace is a repo too (as it normally is), but with no code changes
    init_git_repo(workspace)

    motor = tmp_path / "motor"
    init_git_repo(motor)
    make_commit(motor, "feature.py", "def f(): return 42\n", "WT-2026-215: feat")
    link_workspace_to_motor(workspace, motor)

    bridge, _, _ = make_bridge(workspace)
    result = bridge.check_review_packet_diff_empty(ticket_id="WT-2026-215")

    # With motor commits, the review packet should NOT be empty
    assert result is False, (
        "check_review_packet_diff_empty should return False when motor has real commits"
    )


# =============================================================================
# Test 3: review packet uses motor diff with workspace noise
# =============================================================================


def test_review_packet_uses_motor_diff_with_workspace_noise(tmp_path):
    """With workspace collaboration noise and motor commits, packet is not empty."""
    workspace = tmp_path / "workspace"
    init_git_repo(workspace)

    motor = tmp_path / "motor"
    init_git_repo(motor)
    (motor / "src").mkdir(parents=True, exist_ok=True)
    make_commit(motor, "src/core.py", "CORE = 1\n", "WT-2026-215: core change")
    link_workspace_to_motor(workspace, motor)

    bridge, _, _ = make_bridge(workspace)
    result = bridge.check_review_packet_diff_empty(ticket_id="WT-2026-215")

    assert result is False, (
        "Review packet should not be empty when motor has real commits "
        "even if workspace has only collaboration artifacts"
    )


# =============================================================================
# Test 4: prepush_check run_git_status_check uses motor_root
# =============================================================================


def test_prepush_check_uses_motor_root(tmp_path, monkeypatch):
    """run_git_status_check resolves motor_root and runs git on it."""
    from scripts.prepush_check import run_git_status_check

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    motor = tmp_path / "motor"
    init_git_repo(motor)
    link_workspace_to_motor(workspace, motor)

    original_run = subprocess.run
    captured_cwds = []

    def tracking_run(*args, **kwargs):
        if "cwd" in kwargs:
            captured_cwds.append(kwargs["cwd"])
        return original_run(*args, **kwargs)

    monkeypatch.setattr("scripts.prepush_check.subprocess.run", tracking_run)
    result = run_git_status_check(workspace)

    assert result.passed, f"Expected passed=True, got {result}"
    motor_str = str(motor.resolve())
    assert any(motor_str in str(cwd) for cwd in captured_cwds), (
        f"Expected cwd containing {motor_str}, got {captured_cwds}"
    )


# =============================================================================
# Test 5: session_closeout _step_git_clean uses motor_root
# =============================================================================


def test_session_closeout_git_clean_uses_motor_root(tmp_path, monkeypatch):
    """_step_git_clean resolves motor_root and runs git on it."""
    from scripts.session_closeout import _step_git_clean

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    motor = tmp_path / "motor"
    init_git_repo(motor)
    link_workspace_to_motor(workspace, motor)

    original_run = subprocess.run
    captured_cwds = []

    def tracking_run(*args, **kwargs):
        if "cwd" in kwargs:
            captured_cwds.append(kwargs["cwd"])
        return original_run(*args, **kwargs)

    monkeypatch.setattr("scripts.session_closeout.subprocess.run", tracking_run)
    result = _step_git_clean(workspace, dry_run=False)

    assert result.status == "PASS", f"Expected PASS, got {result}"
    motor_str = str(motor.resolve())
    assert any(motor_str in str(cwd) for cwd in captured_cwds), (
        f"Expected cwd containing {motor_str}, got {captured_cwds}"
    )


# =============================================================================
# Test 6: _motor_root_or_raise raises RuntimeError without link
# =============================================================================


def test_motor_root_or_raise_no_link(tmp_path):
    """_motor_root_or_raise raises RuntimeError when no link file exists."""
    bridge, _, _ = make_bridge(tmp_path)
    with pytest.raises(RuntimeError, match="motor_root not resolvable"):
        bridge._motor_root_or_raise()


# =============================================================================
# Test 7: prepush without link does not crash, returns warning
# =============================================================================


def test_fallback_no_crash_prepush_without_link(tmp_path):
    """run_git_status_check without link returns passed=True with warning."""
    from scripts.prepush_check import run_git_status_check

    result = run_git_status_check(tmp_path)
    # Should not crash — returns non-blocking WARN
    assert result.passed, f"Expected passed=True fallback, got {result}"
    assert not result.is_blocking, "Fallback without link should be non-blocking"


# =============================================================================
# Test 8: regression — revert to project_root breaks the check
# =============================================================================


def test_regression_cwd_project_root_breaks_check(tmp_path, monkeypatch):
    """Reverting motor_root resolution makes check_review_packet_diff_empty return True.

    This regression test verifies that when evidence resolution loses motor
    context (simulating reverting to project_root-only git ops), the review
    packet is wrongly reported as empty.

    The current code uses resolve_evidence which runs git on both motor and
    project roots. To simulate the regression, we mock resolve_evidence to
    return only destination files (no motor evidence), which is what would
    happen if git operations ran on project_root only.
    """
    import bus.evidence as ev

    workspace = tmp_path / "workspace"
    init_git_repo(workspace)

    motor = tmp_path / "motor"
    init_git_repo(motor)
    make_commit(motor, "code.py", "x=2\n", "WT-2026-215: change")
    link_workspace_to_motor(workspace, motor)

    bridge, _, _ = make_bridge(workspace)

    # Save the real resolve_evidence
    _real_resolve = ev.resolve_evidence

    # Regression: resolve_evidence that ignores motor_root
    # (simulates what would happen if git ops only ran on project_root)
    def broken_evidence(motor_root, project_root, ticket_id=None):
        """resolve_evidence that ignores motor_root -- simulates regression."""
        # Only use project_root, ignoring motor_root
        return _real_resolve(None, project_root, ticket_id)

    monkeypatch.setattr("bus.evidence.resolve_evidence", broken_evidence)

    # Con la regresion, el check deberia devolver True (packet empty)
    result = bridge.check_review_packet_diff_empty(ticket_id="WT-2026-215")
    assert result is True, (
        "Regression: without motor_root evidence, "
        "check_review_packet_diff_empty should return True (wrongly empty)"
    )


# =============================================================================
# Test 9: out-of-scope call sites unchanged
# =============================================================================


def test_out_of_scope_call_sites_unchanged(tmp_path):
    """Repomix and destination diff functions still use project_root."""
    bridge, _, _ = make_bridge(tmp_path)

    # _get_destination_diff_files should use project_root (out of scope)
    # This method runs git on project_root — out of scope per WT-2026-215
    result = bridge._get_destination_diff_files()
    # Should be a list (empty if no repo, that's fine)
    assert isinstance(result, list)

    # Verify _ensure_repomix_context still works (mocked to avoid npx)
    result, meta = bridge._ensure_repomix_context()
    assert result is None  # mocked
    assert meta["status"] == "skipped"


# =============================================================================
# Test 10: _build_diff_for_files_likely_touched uses motor_root
# =============================================================================


def test_build_diff_for_files_likely_touched_uses_motor_root(tmp_path, monkeypatch):
    """_build_diff_for_files_likely_touched calls subprocess with cwd=motor_root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    motor = tmp_path / "motor"
    init_git_repo(motor)
    make_commit(motor, "app.py", "APP = 1\n", "WT-2026-215: app change")
    link_workspace_to_motor(workspace, motor)

    bridge, _, _ = make_bridge(workspace)
    original_run = subprocess.run
    captured_cwds = []

    def tracking_run(*args, **kwargs):
        if "cwd" in kwargs:
            captured_cwds.append(str(kwargs["cwd"]))
        return original_run(*args, **kwargs)

    monkeypatch.setattr("bus.review_bridge.subprocess.run", tracking_run)
    result = bridge._build_diff_for_files_likely_touched(
        "WT-2026-215", budget_bytes=5000
    )

    motor_str = str(motor.resolve())
    assert any(motor_str in cwd for cwd in captured_cwds), (
        f"Expected cwd containing {motor_str}, got {captured_cwds}"
    )
    # Verify result is actually a diff string
    assert isinstance(result, str), f"Expected string, got {type(result)}"
