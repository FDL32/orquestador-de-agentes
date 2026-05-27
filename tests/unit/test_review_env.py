"""Tests for _review_env() environment isolation (WP-2026-129)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


class TestReviewEnvIsolation:
    """Test that _review_env() isolates the review home while preserving vars."""

    def test_review_env_redirects_home_vars(self, tmp_path: Path, monkeypatch) -> None:
        """Test _review_env() redirects HOME/USERPROFILE to a scratch home."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        source_home = tmp_path / "source-home"
        source_auth = source_home / ".local" / "share" / "opencode" / "auth.json"
        source_auth.parent.mkdir(parents=True, exist_ok=True)
        source_auth.write_text('{"token": "dummy"}', encoding="utf-8")

        scratch_home = tmp_path / "scratch-home"
        monkeypatch.setenv("HOME", str(source_home))
        monkeypatch.setenv("USERPROFILE", str(source_home))
        monkeypatch.setattr(
            tempfile, "mkdtemp", lambda prefix, dir=None: str(scratch_home)
        )

        review_env = bridge._review_env()

        assert review_env["HOME"] == str(scratch_home)
        assert review_env["USERPROFILE"] == str(scratch_home)
        assert review_env["XDG_CONFIG_HOME"] == str(scratch_home / ".config")
        assert review_env["XDG_DATA_HOME"] == str(scratch_home / ".local" / "share")
        assert review_env["XDG_STATE_HOME"] == str(scratch_home / ".local" / "state")

        copied_auth = scratch_home / ".local" / "share" / "opencode" / "auth.json"
        assert copied_auth.exists()
        assert copied_auth.read_text(encoding="utf-8") == '{"token": "dummy"}'

    def test_review_env_is_copy_not_reference(self, tmp_path: Path) -> None:
        """Test _review_env() returns a copy, not os.environ reference."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()

        review_env["TEST_VAR"] = "test_value"
        assert "TEST_VAR" not in os.environ

    def test_review_env_inherits_non_home_process_vars(self, tmp_path: Path) -> None:
        """Test _review_env() still preserves ordinary process environment variables."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_env = bridge._review_env()

        for key, value in os.environ.items():
            if key in {
                "HOME",
                "USERPROFILE",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
            }:
                continue
            assert key in review_env
            assert review_env[key] == value


class TestManagerBackendFallback:
    """Test that _get_manager_backend() uses opencode as fallback."""

    def test_get_manager_backend_fallback_opencode(self, tmp_path: Path) -> None:
        """Test _get_manager_backend() returns 'opencode' when agents.json is missing."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        backend = bridge._get_manager_backend()
        assert backend == "opencode"

    def test_get_manager_backend_no_codex_fallback(self, tmp_path: Path) -> None:
        """Test _get_manager_backend() does not fallback to 'codex'."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        backend = bridge._get_manager_backend()
        assert backend != "codex"
