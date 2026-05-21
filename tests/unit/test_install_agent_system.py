"""Tests for scripts/install_agent_system.py."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.install_agent_system import (
    _detect_host_setup,
    _maybe_invoke_host_setup,
    detect_destination_residues,
    ensure_hooks_config_integrity,
    flip_profile_in_destination,
    write_motor_destination_link,
)


def _write_min_agent_tree(root: Path) -> Path:
    agent_dir = root / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent_controller.py").write_text("# controller\n", encoding="utf-8")
    (agent_dir / ".version_manifest.json").write_text(
        json.dumps({"version": "v9.5.0+"}), encoding="utf-8"
    )
    (agent_dir / "config").mkdir(parents=True, exist_ok=True)
    (agent_dir / "config" / "hooks_config.json").write_text(
        json.dumps({"version": "1.0", "enabled": True}), encoding="utf-8"
    )
    (agent_dir / "rules").mkdir(parents=True, exist_ok=True)
    (agent_dir / "rules" / "core.md").write_text("# core\n", encoding="utf-8")
    (agent_dir / "collaboration").mkdir(parents=True, exist_ok=True)
    (agent_dir / "collaboration" / "work_plan.md").write_text(
        "# local work plan\n", encoding="utf-8"
    )
    (agent_dir / "runtime").mkdir(parents=True, exist_ok=True)
    (agent_dir / "runtime" / "memory").mkdir(parents=True, exist_ok=True)
    (agent_dir / "runtime" / "memory" / "observations.jsonl").write_text(
        "", encoding="utf-8"
    )
    return agent_dir


def test_detect_destination_residues_ignores_local_dirs(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source_agent = _write_min_agent_tree(source)
    dest_agent = _write_min_agent_tree(dest)

    # Canonical residue candidates
    (dest_agent / "legacy.md").write_text("legacy\n", encoding="utf-8")
    (dest_agent / "config" / "old.json").write_text("{}", encoding="utf-8")
    (dest_agent / "__pycache__").mkdir(parents=True, exist_ok=True)
    (dest_agent / "__pycache__" / "ghost.pyc").write_text("x", encoding="utf-8")
    (dest_agent / "nested").mkdir(parents=True, exist_ok=True)
    (dest_agent / "nested" / "child.txt").write_text("x", encoding="utf-8")

    # Preserved local state must not be treated as residue.
    (dest_agent / "collaboration" / "execution_log.md").write_text(
        "local\n", encoding="utf-8"
    )
    (dest_agent / "runtime" / "memory" / "session.json").write_text(
        "{}", encoding="utf-8"
    )

    residues = detect_destination_residues(source_agent, dest_agent)
    residue_set = {rel.as_posix() for rel in residues}

    assert "legacy.md" in residue_set
    assert "config/old.json" in residue_set
    assert "__pycache__" in residue_set
    assert "nested" in residue_set
    assert "collaboration/execution_log.md" not in residue_set
    assert "runtime/memory/session.json" not in residue_set


def test_ensure_hooks_config_integrity_validates(tmp_path):
    """Verify that hooks_config.json is readable and has expected structure."""
    agent_dir = _write_min_agent_tree(tmp_path)
    hooks_config = agent_dir / "config" / "hooks_config.json"

    # Should validate without modifying version
    ok = ensure_hooks_config_integrity(agent_dir, dry_run=False)

    assert ok is True
    # Version field should remain unchanged (not overwritten by core version)
    data = json.loads(hooks_config.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"  # Original schema version, unchanged


def test_install_agent_system_flips_profile(tmp_path):
    """Verify that flip_profile_in_destination flips active_profile from engine-dev to host-project."""
    from scripts.install_agent_system import flip_profile_in_destination

    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    config_dir = agent_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    agents_json = config_dir / "agents.json"
    agents_json.write_text(
        json.dumps({"schema_version": "1.1", "active_profile": "engine-dev"}),
        encoding="utf-8",
    )

    flip_profile_in_destination(agent_dir, dry_run=False)

    data = json.loads(agents_json.read_text(encoding="utf-8"))
    assert data["active_profile"] == "host-project"


# =============================================================================
# Host setup hook tests (WP-2026-094)
# =============================================================================


def test_detect_host_setup_returns_none_when_absent(tmp_path):
    """When no host-setup.{sh,ps1} exists, _detect_host_setup returns None."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    # Create some other files, but not host-setup
    (agent_dir / "other.txt").write_text("x", encoding="utf-8")

    result = _detect_host_setup(tmp_path)
    assert result is None


def test_detect_host_setup_finds_sh_file(tmp_path):
    """When host-setup.sh exists, _detect_host_setup returns its Path."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.sh"
    hook.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")

    result = _detect_host_setup(tmp_path)
    assert result == hook


def test_detect_host_setup_finds_ps1_file_when_sh_absent(tmp_path):
    """When only host-setup.ps1 exists, _detect_host_setup returns its Path."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.ps1"
    hook.write_text("# PowerShell script\nWrite-Host ok\n", encoding="utf-8")

    result = _detect_host_setup(tmp_path)
    assert result == hook


def test_detect_host_setup_prefers_sh_over_ps1(tmp_path):
    """When both exist, _detect_host_setup returns .sh first (priority order)."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook_sh = agent_dir / "host-setup.sh"
    hook_ps1 = agent_dir / "host-setup.ps1"
    hook_sh.write_text("#!/usr/bin/env bash\necho sh\n", encoding="utf-8")
    hook_ps1.write_text("# PowerShell\nWrite-Host ps1\n", encoding="utf-8")

    result = _detect_host_setup(tmp_path)
    assert result == hook_sh


def test_maybe_invoke_skips_when_user_declines(tmp_path, capsys):
    """When user declines (input='n'), hook is NOT executed and returns 0."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.sh"
    hook.write_text("#!/usr/bin/env bash\necho should_not_run\n", encoding="utf-8")

    rc = _maybe_invoke_host_setup(tmp_path, auto_yes=False, input_fn=lambda _: "n")

    assert rc == 0
    out = capsys.readouterr().out
    assert "Skipped by user" in out


def test_maybe_invoke_propagates_failure_exit_code(tmp_path, monkeypatch):
    """When hook fails with exit code N, _maybe_invoke_host_setup returns N (does not mask)."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.sh"
    hook.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")

    # Mock subprocess.run to return a failed result
    fake_result = type("R", (), {"returncode": 7})()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

    rc = _maybe_invoke_host_setup(tmp_path, auto_yes=True)

    assert rc == 7


def test_dry_run_does_not_execute(tmp_path, monkeypatch, capsys):
    """When dry_run=True, hook is NOT executed and prints 'Would invoke'."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.sh"
    hook.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")

    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(a))

    rc = _maybe_invoke_host_setup(tmp_path, auto_yes=True, dry_run=True)

    assert rc == 0
    assert called == []  # subprocess.run was NOT called
    out = capsys.readouterr().out
    assert "Would invoke" in out


def test_maybe_invoke_auto_yes_skips_prompt(tmp_path, monkeypatch, capsys):
    """When auto_yes=True, no prompt is shown and hook executes directly."""
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    hook = agent_dir / "host-setup.sh"
    hook.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")

    # Mock subprocess.run to return success
    fake_result = type("R", (), {"returncode": 0})()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

    rc = _maybe_invoke_host_setup(tmp_path, auto_yes=True)

    assert rc == 0
    out = capsys.readouterr().out
    # Should NOT contain the prompt text
    assert "Execute this script?" not in out


# =============================================================================
# Motor-destination link tests (WP-2026-123)
# =============================================================================


def test_write_motor_destination_link_creates_file(tmp_path):
    """Verify that write_motor_destination_link creates the link file with correct schema."""
    from scripts.install_agent_system import MANIFEST_WORKSPACE_VERSION

    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor"
    motor_root.mkdir(parents=True, exist_ok=True)
    destination_root = tmp_path

    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version="v9.14.0",
        destination_id="test-dest",
        dry_run=False,
    )

    link_file = project_agent / "config" / "motor_destination_link.json"
    assert link_file.exists()

    data = json.loads(link_file.read_text(encoding="utf-8"))
    assert data["motor_root"] == str(motor_root.resolve())
    assert data["destination_root"] == str(destination_root.resolve())
    assert data["motor_version"] == "v9.14.0"
    assert data["destination_id"] == "test-dest"
    assert "created_at" in data
    assert data["manifest_version"] == MANIFEST_WORKSPACE_VERSION


def test_write_motor_destination_link_default_destination_id(tmp_path):
    """When destination_id is None, it defaults to destination_root.name."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor"
    motor_root.mkdir(parents=True, exist_ok=True)
    destination_root = tmp_path / "my_project"
    destination_root.mkdir(parents=True, exist_ok=True)

    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version="v9.14.0",
        destination_id=None,
        dry_run=False,
    )

    link_file = project_agent / "config" / "motor_destination_link.json"
    data = json.loads(link_file.read_text(encoding="utf-8"))
    assert data["destination_id"] == "my_project"


def test_write_motor_destination_link_unknown_version(tmp_path):
    """When motor_version is None, it defaults to 'unknown'."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor"
    motor_root.mkdir(parents=True, exist_ok=True)
    destination_root = tmp_path

    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version=None,
        dry_run=False,
    )

    link_file = project_agent / "config" / "motor_destination_link.json"
    data = json.loads(link_file.read_text(encoding="utf-8"))
    assert data["motor_version"] == "unknown"


def test_write_motor_destination_link_dry_run(tmp_path, capsys):
    """When dry_run=True, no file is written but message is printed."""
    project_agent = tmp_path / ".agent"
    project_agent.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor"
    motor_root.mkdir(parents=True, exist_ok=True)
    destination_root = tmp_path

    write_motor_destination_link(
        project_agent=project_agent,
        motor_root=motor_root,
        destination_root=destination_root,
        motor_version="v9.14.0",
        dry_run=True,
    )

    link_file = project_agent / "config" / "motor_destination_link.json"
    assert not link_file.exists()

    out = capsys.readouterr().out
    assert "Would write motor-destination link" in out
