#!/usr/bin/env python3
"""
Unit tests for project_paths.py
"""

import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest


# Add agent_system to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.project_paths import ProjectPathsResolver


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_AGENT_DIR = PROJECT_ROOT / ".agent"


def _make_agent_dir(base: Path) -> Path:
    agent_dir = base / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent_controller.py").touch()
    return agent_dir


def _restore_backup_agent_dir(backup_dir: Path) -> None:
    """Restore .agent directory from backup with retries."""
    for attempt in range(3):
        if _try_restore_backup_agent_dir(backup_dir):
            return
        time.sleep(0.1 * (attempt + 1))
    # Fallback: copy if rename failed
    if backup_dir.exists() and not REPO_AGENT_DIR.exists():
        shutil.copytree(backup_dir, REPO_AGENT_DIR, dirs_exist_ok=True)
    shutil.rmtree(backup_dir, ignore_errors=True)


def _try_restore_backup_agent_dir(backup_dir: Path) -> bool:
    """Try restoring .agent with a single rename attempt."""
    try:
        if REPO_AGENT_DIR.exists():
            shutil.rmtree(REPO_AGENT_DIR, ignore_errors=True)
        backup_dir.rename(REPO_AGENT_DIR)
        return True
    except PermissionError:
        return False


@contextmanager
def _hide_repo_agent_dir():
    if not REPO_AGENT_DIR.exists():
        yield
        return

    backup_dir = REPO_AGENT_DIR.with_name(
        f".agent.__hidden_for_tests__{uuid.uuid4().hex}"
    )
    REPO_AGENT_DIR.rename(backup_dir)
    try:
        yield
    finally:
        if REPO_AGENT_DIR.exists():
            shutil.rmtree(REPO_AGENT_DIR, ignore_errors=True)
        if backup_dir.exists():
            _restore_backup_agent_dir(backup_dir)


@pytest.fixture(autouse=True)
def isolate_repo_agent_dir():
    """Hide the real repo .agent tree so these tests only see their fixture tree."""
    with _hide_repo_agent_dir():
        yield


class TestProjectPathsResolver:
    """Test ProjectPathsResolver."""

    def test_no_agent_dir(self, tmp_path):
        """Test when no .agent directory exists."""
        resolver = ProjectPathsResolver(tmp_path)
        result = resolver.resolve_paths()
        assert result["project_root"] is None
        assert result["agent_dir"] is None
        assert result["drift_type"] is None
        assert "No .agent directory found" in result["message"]

    def test_single_agent_dir_at_root(self, tmp_path):
        """Test single .agent at project root."""
        agent_dir = _make_agent_dir(tmp_path)

        resolver = ProjectPathsResolver(tmp_path)
        result = resolver.resolve_paths()
        assert result["project_root"] == str(tmp_path.resolve())
        assert result["agent_dir"] == str(agent_dir)
        assert result["drift_detected"] is False
        assert result["drift_type"] == "none"
        assert "Paths resolved successfully" in result["message"]

    def test_manifest_only_agent_dir_at_root(self, tmp_path):
        """Test canonical .agent resolution when only manifests exist."""
        agent_dir = tmp_path / ".agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "project_manifest.toml").write_text(
            "[project]\nid = 'demo'\nversion = '1.0.0'\n"
        )
        (agent_dir / ".version_manifest.json").write_text(
            '{"agent_core_version": "1.0.0", "status": "canonical", "confidence": "high", "last_updated": "2026-05-13T10:00:00+02:00", "components": {"agent_controller": "1.0.0", "hooks": "1.0.0", "rules": "1.0.0"}, "markers_validated": true, "drift_detected": false}'
        )

        resolver = ProjectPathsResolver(tmp_path)
        result = resolver.resolve_paths()
        assert result["project_root"] == str(tmp_path.resolve())
        assert result["agent_dir"] == str(agent_dir)
        assert result["drift_detected"] is False
        assert result["drift_type"] == "none"

    def test_multiple_agent_dirs_drift(self, tmp_path):
        """Test multiple .agent directories cause drift."""
        root_agent = _make_agent_dir(tmp_path)

        sub_agent = tmp_path / "subdir" / ".agent"
        sub_agent.mkdir(parents=True)

        # Add a backup .agent that should be ignored
        backup_agent = root_agent / "backups" / "backup_1" / ".agent"
        backup_agent.mkdir(parents=True)

        resolver = ProjectPathsResolver(tmp_path)
        result = resolver.resolve_paths()
        assert result["project_root"] is None
        assert result["agent_dir"] is None
        assert result["drift_detected"] is True
        assert result["drift_type"] == "multiple_agent_dirs"
        assert "Multiple .agent directories found" in result["message"]

    def test_get_project_root_none(self, tmp_path):
        """Test get_project_root returns None when no agent dir."""
        resolver = ProjectPathsResolver(tmp_path)
        assert resolver.get_project_root() is None

    def test_get_project_root_exists(self, tmp_path):
        """Test get_project_root returns Path when agent dir exists."""
        _make_agent_dir(tmp_path)

        resolver = ProjectPathsResolver(tmp_path)
        root = resolver.get_project_root()
        assert root == tmp_path.resolve()

    def test_get_agent_dir_none(self, tmp_path):
        """Test get_agent_dir returns None when no agent dir."""
        resolver = ProjectPathsResolver(tmp_path)
        assert resolver.get_agent_dir() is None

    def test_get_agent_dir_exists(self, tmp_path):
        """Test get_agent_dir returns Path when agent dir exists."""
        agent_dir = _make_agent_dir(tmp_path)

        resolver = ProjectPathsResolver(tmp_path)
        ag_dir = resolver.get_agent_dir()
        assert ag_dir == agent_dir

    def test_has_drift_false(self, tmp_path):
        """Test has_drift returns False when no drift."""
        (tmp_path / ".agent").mkdir()

        resolver = ProjectPathsResolver(tmp_path)
        assert resolver.has_drift() is False

    def test_has_drift_true(self, tmp_path):
        """Test has_drift returns True when multiple agent dirs."""
        _make_agent_dir(tmp_path)
        sub_agent = tmp_path / "subdir" / ".agent"
        sub_agent.mkdir(parents=True)

        resolver = ProjectPathsResolver(tmp_path)
        assert resolver.has_drift() is True

    def test_get_drift_info(self, tmp_path):
        """Test get_drift_info returns correct dict."""
        resolver = ProjectPathsResolver(tmp_path)
        info = resolver.get_drift_info()
        assert "drift_detected" in info
        assert "drift_type" in info
        assert "message" in info

    def test_resolve_from_subdir(self, tmp_path):
        """Test resolution works when starting from a subdirectory."""
        agent_dir = _make_agent_dir(tmp_path)

        subdir = tmp_path / "some" / "deep" / "subdir"
        subdir.mkdir(parents=True)

        resolver = ProjectPathsResolver(subdir)
        result = resolver.resolve_paths()
        assert result["project_root"] == str(tmp_path.resolve())
        assert result["agent_dir"] == str(agent_dir)
        assert result["drift_detected"] is False

    def test_resolve_from_deep_subdir(self, tmp_path):
        """Test resolution works beyond five nested levels."""
        agent_dir = _make_agent_dir(tmp_path)

        deep_subdir = tmp_path
        for part in (
            "level1",
            "level2",
            "level3",
            "level4",
            "level5",
            "level6",
            "level7",
        ):
            deep_subdir = deep_subdir / part
        deep_subdir.mkdir(parents=True)

        resolver = ProjectPathsResolver(deep_subdir)
        result = resolver.resolve_paths()
        assert result["project_root"] == str(tmp_path.resolve())
        assert result["agent_dir"] == str(agent_dir)
        assert result["drift_detected"] is False
