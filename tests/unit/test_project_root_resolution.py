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


class TestMangledRootGuard:
    """CTL-2026-007b: fail closed on a mangled AGENT_PROJECT_ROOT.

    A Windows absolute path mis-parsed as a single relative segment (because the
    destination ran under a POSIX-flavoured interpreter) must NOT silently
    resolve into a spurious directory under cwd. The guard detects the mangle
    signature and raises ProjectRootError.
    """

    def test_is_mangled_root_detects_collapsed_absolute(self) -> None:
        """Absolute-looking raw whose resolved tail is not the intended name."""
        from runtime.project_root import _is_mangled_root

        raw = r"C:\Users\testuser\Proyectos_Python\Crear_Texto_LLM"
        # Simulate the POSIX-flavour mangle: the whole value collapsed into one
        # segment joined under cwd, so the resolved tail is the raw blob, not
        # "Crear_Texto_LLM".
        mangled_resolved = Path.cwd() / "UserstestuserProyectos_PythonCrear_Texto_LLM"
        assert _is_mangled_root(raw, mangled_resolved) is True

    def test_is_mangled_root_accepts_genuine_absolute(self) -> None:
        """A correctly resolved absolute path is not flagged."""
        from runtime.project_root import _is_mangled_root

        raw = r"C:\Users\testuser\Proyectos_Python\Crear_Texto_LLM"
        good_resolved = Path(raw).resolve()
        # Only meaningful where the local flavour parses C:\ as absolute; if it
        # does, the guard must accept it. If it does not (POSIX flavour), the
        # mangle detection legitimately fires and this assertion is skipped.
        if good_resolved.is_absolute() and Path(raw).is_absolute():
            assert _is_mangled_root(raw, good_resolved) is False

    def test_is_mangled_root_allows_relative_legacy_root(self) -> None:
        """A genuinely relative root (legacy/test usage) is allowed."""
        from runtime.project_root import _is_mangled_root

        assert (
            _is_mangled_root("some/relative/root", Path("some/relative/root").resolve())
            is False
        )

    def test_resolve_raises_on_mangled_env(self) -> None:
        """resolve_project_root fails closed when the value is mangled.

        Forces the mangle signature via _is_mangled_root so the test is
        deterministic regardless of the running interpreter's path flavour.
        """
        import runtime.project_root as pr

        clear_cache()
        with (
            patch.dict(os.environ, {"AGENT_PROJECT_ROOT": r"C:\Users\x\proj"}),
            patch.object(pr, "_is_mangled_root", return_value=True),
            pytest.raises(pr.ProjectRootError),
        ):
            pr.resolve_project_root()
        clear_cache()

    def test_resolve_succeeds_on_clean_env(self) -> None:
        """A clean absolute root still resolves normally (no false positive)."""
        import runtime.project_root as pr

        clear_cache()
        clean = Path(__file__).resolve().parent
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": str(clean)}):
            assert pr.resolve_project_root() == clean
        clear_cache()
