"""Tests for runtime/motor_link.py - external-motor topology helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from runtime.motor_link import (
    resolve_motor_controller,
    resolve_motor_root,
    resolve_motor_script,
)


@pytest.fixture
def fake_project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with a motor_destination_link.json."""
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def fake_motor_root(tmp_path: Path) -> Path:
    """Create a temporary motor root with .agent/agent_controller.py."""
    motor = tmp_path / "fake_motor"
    agent_dir = motor / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    # Create agent_controller.py
    controller = agent_dir / "agent_controller.py"
    controller.write_text("# fake controller", encoding="utf-8")
    # Create a script
    scripts_dir = motor / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prepush = scripts_dir / "prepush_check.py"
    prepush.write_text("# fake prepush", encoding="utf-8")
    return motor


def _write_link_file(project_root: Path, motor_root: Path) -> Path:
    """Write motor_destination_link.json to project config dir."""
    link_path = project_root / ".agent" / "config" / "motor_destination_link.json"
    data = {"motor_root": str(motor_root.resolve())}
    link_path.write_text(json.dumps(data), encoding="utf-8")
    return link_path


def test_resolve_motor_root_returns_none_when_no_link(fake_project_root: Path):
    """When no motor_destination_link.json exists, returns None."""
    result = resolve_motor_root(fake_project_root)
    assert result is None


def test_resolve_motor_root_returns_motor_root(
    fake_project_root: Path, fake_motor_root: Path
):
    """When link file points to an existing motor root, returns its path."""
    _write_link_file(fake_project_root, fake_motor_root)
    result = resolve_motor_root(fake_project_root)
    assert result == fake_motor_root.resolve()


def test_resolve_motor_root_returns_none_for_bad_json(fake_project_root: Path):
    """When link file has invalid JSON, returns None."""
    link_path = fake_project_root / ".agent" / "config" / "motor_destination_link.json"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.write_text("not valid json", encoding="utf-8")
    result = resolve_motor_root(fake_project_root)
    assert result is None


def test_resolve_motor_root_returns_none_for_missing_dir(fake_project_root: Path):
    """When motor_root in link points to non-existent dir, returns None."""
    link_path = fake_project_root / ".agent" / "config" / "motor_destination_link.json"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    missing_path = fake_project_root / "does_not_exist_12345"
    data = {"motor_root": str(missing_path)}
    link_path.write_text(json.dumps(data), encoding="utf-8")
    result = resolve_motor_root(fake_project_root)
    assert result is None


def test_resolve_motor_controller_returns_none_when_no_root(fake_project_root: Path):
    """When no motor root is resolved, returns None."""
    result = resolve_motor_controller(fake_project_root)
    assert result is None


def test_resolve_motor_controller_points_to_agent_controller(
    fake_project_root: Path, fake_motor_root: Path
):
    """When motor root is resolved, returns path to agent_controller.py."""
    _write_link_file(fake_project_root, fake_motor_root)
    result = resolve_motor_controller(fake_project_root)
    expected = fake_motor_root.resolve() / ".agent" / "agent_controller.py"
    assert result == expected
    assert result.exists()


def test_resolve_motor_script_returns_none_when_no_root(fake_project_root: Path):
    """When no motor root is resolved, returns None."""
    result = resolve_motor_script(fake_project_root, "prepush_check.py")
    assert result is None


def test_resolve_motor_script_points_to_script(
    fake_project_root: Path, fake_motor_root: Path
):
    """When motor root is resolved, returns path to the script."""
    _write_link_file(fake_project_root, fake_motor_root)
    result = resolve_motor_script(fake_project_root, "prepush_check.py")
    expected = fake_motor_root.resolve() / "scripts" / "prepush_check.py"
    assert result == expected
    assert result.exists()


def test_resolve_motor_script_returns_none_for_missing_script(
    fake_project_root: Path, fake_motor_root: Path
):
    """When the requested script does not exist in the motor, returns None."""
    _write_link_file(fake_project_root, fake_motor_root)
    result = resolve_motor_script(fake_project_root, "nonexistent_script.py")
    assert result is None
