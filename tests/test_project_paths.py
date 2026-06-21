#!/usr/bin/env python3
"""
Unit tests for project_paths.py
"""

import sys
from pathlib import Path


# Add agent_system to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.project_paths import ProjectPathsResolver, _find_agent_dirs


def _make_agent_dir(base: Path) -> Path:
    agent_dir = base / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent_controller.py").touch()
    return agent_dir


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


class TestFindAgentDirsRobustness:
    """WOT-2026-013d: _find_agent_dirs must replace the bare rglob('.agent') that
    crashed when a sandbox subtree vanished mid-scan under xdist, prune the volatile
    sandbox, and find nested .agent dirs."""

    def test_finds_nested_agent_dirs(self, tmp_path):
        _make_agent_dir(tmp_path)
        _make_agent_dir(tmp_path / "sub")
        found = {d.resolve() for d in _find_agent_dirs(tmp_path)}
        assert (tmp_path / ".agent").resolve() in found
        assert (tmp_path / "sub" / ".agent").resolve() in found

    def test_prunes_sandbox_subtree(self, tmp_path):
        _make_agent_dir(tmp_path)
        sandbox_agent = tmp_path / "tests" / "sandbox" / "test_runtime" / "session_9"
        _make_agent_dir(sandbox_agent)
        found = {d.resolve() for d in _find_agent_dirs(tmp_path)}
        assert (tmp_path / ".agent").resolve() in found
        assert sandbox_agent.resolve() / ".agent" not in found, (
            "resolver descended into the volatile sandbox subtree (013d regression)"
        )

    def test_tolerates_vanished_subdir(self, tmp_path, monkeypatch):
        """FAIL-without/PASS-with: a subdir deleted during the walk must not crash
        _find_agent_dirs (bare rglob raised FileNotFoundError here)."""
        _make_agent_dir(tmp_path)
        doomed = tmp_path / "doomed"
        doomed.mkdir()
        (doomed / "x.txt").write_text("x")

        import os as _os

        real_scandir = _os.scandir

        def _scandir_then_delete(path):
            it = real_scandir(path)
            # On Linux, scandir may receive a directory fd (int) from os.walk.
            if isinstance(path, (str, bytes, _os.PathLike)) and doomed.exists():
                scan_root = Path(path)
            else:
                scan_root = None
            if scan_root == tmp_path and doomed.exists():
                import shutil as _sh

                _sh.rmtree(doomed, ignore_errors=True)
            return it

        monkeypatch.setattr(_os, "scandir", _scandir_then_delete)
        found = {d.resolve() for d in _find_agent_dirs(tmp_path)}
        assert (tmp_path / ".agent").resolve() in found
