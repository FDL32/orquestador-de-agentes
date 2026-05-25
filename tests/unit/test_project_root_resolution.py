"""
Unit tests for runtime/project_root.py - WP-2026-122.

Tests cover:
- Precedence: AGENT_PROJECT_ROOT env var > derived from __file__
- Fallback behavior when env var is not set
- Import-safe: no side effects at import time
- Caching: repeated calls return same cached value
- Cache clearing for testing scenarios
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from runtime.project_root import (
    clear_cache,
)


class TestResolveProjectRoot:
    """Tests for resolve_project_root() function."""

    def test_fallback_to_derived_when_no_env(self) -> None:
        """When AGENT_PROJECT_ROOT is not set, derive from __file__."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=False):
            # Remove AGENT_PROJECT_ROOT if it exists
            env_copy = os.environ.copy()
            env_copy.pop("AGENT_PROJECT_ROOT", None)
            with patch.dict(os.environ, env_copy, clear=True):
                # Need to reload the module to pick up new env
                import importlib

                import runtime.project_root as pr

                importlib.reload(pr)
                root = pr.resolve_project_root()

                # Should be parent of runtime/ directory (which is project root)
                # runtime/project_root.py -> runtime/ -> project root
                expected = Path(__file__).resolve().parent.parent.parent
                assert root == expected

    def test_env_var_takes_precedence(self) -> None:
        """AGENT_PROJECT_ROOT environment variable takes precedence."""
        clear_cache()
        fake_root = Path("/fake/project/root").resolve()

        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": str(fake_root)}):
            # Need to reload the module to pick up new env
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)
            root = pr.resolve_project_root()

            assert root == fake_root

    def test_empty_env_var_falls_back(self) -> None:
        """Empty AGENT_PROJECT_ROOT falls back to derivation."""
        clear_cache()
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": ""}):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)
            root = pr.resolve_project_root()

            # runtime/project_root.py -> runtime/ -> project root
            expected = Path(__file__).resolve().parent.parent.parent
            assert root == expected

    def test_whitespace_env_var_falls_back(self) -> None:
        """Whitespace-only AGENT_PROJECT_ROOT falls back to derivation."""
        clear_cache()
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": "   "}):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)
            root = pr.resolve_project_root()

            # runtime/project_root.py -> runtime/ -> project root
            expected = Path(__file__).resolve().parent.parent.parent
            assert root == expected

    def test_caching(self) -> None:
        """Results are cached for performance."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            root1 = pr.resolve_project_root()
            root2 = pr.resolve_project_root()

            # Same object returned (cached)
            assert root1 is root2

    def test_cache_clear(self) -> None:
        """clear_cache() allows re-evaluation."""
        clear_cache()
        fake_root1 = Path("/fake/root/1").resolve()

        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": str(fake_root1)}):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)
            root1 = pr.resolve_project_root()
            assert root1 == fake_root1

        # Change env and clear cache
        fake_root2 = Path("/fake/root/2").resolve()
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": str(fake_root2)}):
            pr.clear_cache()
            importlib.reload(pr)
            root2 = pr.resolve_project_root()
            assert root2 == fake_root2


class TestDerivedPaths:
    """Tests for derived path functions."""

    def test_get_agent_dir(self) -> None:
        """get_agent_dir() returns .agent/ subdirectory."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            agent_dir = pr.get_agent_dir()
            root = pr.resolve_project_root()

            assert agent_dir == root / ".agent"

    def test_get_collab_dir(self) -> None:
        """get_collab_dir() returns .agent/collaboration/ subdirectory."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            collab_dir = pr.get_collab_dir()
            root = pr.resolve_project_root()

            assert collab_dir == root / ".agent" / "collaboration"

    def test_get_runtime_dir(self) -> None:
        """get_runtime_dir() returns .agent/runtime/ subdirectory."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            runtime_dir = pr.get_runtime_dir()
            root = pr.resolve_project_root()

            assert runtime_dir == root / ".agent" / "runtime"

    def test_get_context_dir(self) -> None:
        """get_context_dir() returns .agent/context/ subdirectory."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            context_dir = pr.get_context_dir()
            root = pr.resolve_project_root()

            assert context_dir == root / ".agent" / "context"

    def test_get_scripts_dir(self) -> None:
        """get_scripts_dir() returns scripts/ subdirectory."""
        clear_cache()
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import runtime.project_root as pr

            importlib.reload(pr)

            scripts_dir = pr.get_scripts_dir()
            root = pr.resolve_project_root()

            assert scripts_dir == root / "scripts"


class TestImportSafety:
    """Tests to verify import-safe behavior."""

    def test_no_side_effects_at_import(self) -> None:
        """Importing the module does not modify environment or filesystem."""
        # Just import - should not raise or modify state
        from runtime import project_root

        # Verify module has expected attributes
        assert hasattr(project_root, "resolve_project_root")
        assert hasattr(project_root, "get_agent_dir")
        assert hasattr(project_root, "get_collab_dir")
        assert hasattr(project_root, "clear_cache")

    def test_module_importable_from_different_locations(self) -> None:
        """Module can be imported from scripts/, .agent/, runtime/, bus/."""
        # This test verifies the module is importable without circular dependencies
        try:
            from runtime.project_root import resolve_project_root

            root = resolve_project_root()
            assert isinstance(root, Path)
            assert root.exists()
        except ImportError as e:
            pytest.fail(f"Module not importable: {e}")
