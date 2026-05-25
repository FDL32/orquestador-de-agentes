"""Tests for _review_env() environment inheritance (WP-2026-129).

Before: _review_env() redirected HOME, USERPROFILE, CODEX_HOME to .codex.
After: _review_env() preserves the inherited process environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


class TestReviewEnvInheritance:
    """Test that _review_env() preserves inherited environment."""

    def test_review_env_preserves_home(self, tmp_path: Path) -> None:
        """Test _review_env() does not redirect HOME to .codex."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()
        original_home = os.environ.get("HOME")

        # Should preserve original HOME, not redirect to .codex
        assert review_env.get("HOME") == original_home
        if original_home is not None:
            assert ".codex" not in original_home

    def test_review_env_preserves_userprofile(self, tmp_path: Path) -> None:
        """Test _review_env() does not redirect USERPROFILE to .codex."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()
        original_userprofile = os.environ.get("USERPROFILE")

        # Should preserve original USERPROFILE, not redirect to .codex
        assert review_env.get("USERPROFILE") == original_userprofile
        if original_userprofile is not None:
            assert ".codex" not in original_userprofile

    def test_review_env_preserves_codex_home_unset(self, tmp_path: Path) -> None:
        """Test _review_env() does not set CODEX_HOME artificially."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()
        original_codex_home = os.environ.get("CODEX_HOME")

        # Should preserve original CODEX_HOME (or lack thereof)
        assert review_env.get("CODEX_HOME") == original_codex_home
        # If it was unset, it should remain unset
        if original_codex_home is None:
            assert "CODEX_HOME" not in review_env

    def test_review_env_is_copy_not_reference(self, tmp_path: Path) -> None:
        """Test _review_env() returns a copy, not os.environ reference."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()

        # Modifying the returned env should not affect os.environ
        review_env["TEST_VAR"] = "test_value"
        assert "TEST_VAR" not in os.environ

    def test_review_env_inherits_all_process_vars(self, tmp_path: Path) -> None:
        """Test _review_env() inherits all process environment variables."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()

        # All original env vars should be present
        for key, value in os.environ.items():
            assert key in review_env
            assert review_env[key] == value


class TestManagerBackendFallback:
    """Test that _get_manager_backend() uses opencode as fallback."""

    def test_get_manager_backend_fallback_opencode(self, tmp_path: Path) -> None:
        """Test _get_manager_backend() returns 'opencode' when agents.json is missing."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # No agents.json exists, should fallback to opencode
        backend = bridge._get_manager_backend()
        assert backend == "opencode"

    def test_get_manager_backend_no_codex_fallback(self, tmp_path: Path) -> None:
        """Test _get_manager_backend() does not fallback to 'codex'."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        backend = bridge._get_manager_backend()

        # Should never return 'codex' as fallback anymore
        assert backend != "codex"
