#!/usr/bin/env python3
"""Eval test for .agent/hooks/guard_paths.py.

Verifies the hook blocks protected paths and commands in-process,
without subprocess and without touching the production bus.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def guard_paths_module():
    """Load the real hook module in-process."""
    script_path = (
        Path(__file__).parent.parent.parent / ".agent" / "hooks" / "guard_paths.py"
    )
    spec = importlib.util.spec_from_file_location("guard_paths", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.eval


class TestProtectedPathDetection:
    """Tests for protected path detection."""

    def test_in_process_blocks_privada_path(self, guard_paths_module, tmp_path: Path):
        """The hook blocks a path containing 'privada'."""
        config = {"profiles": {"default": {"write_roots": []}}}
        data = {"tool_input": {"file_path": str(tmp_path / "privada" / "secret.json")}}

        code, reason = guard_paths_module.evaluate_tool_request(
            data,
            config,
            repo_root=tmp_path,
        )

        assert code == 2
        assert reason is not None
        assert "guard_paths:" in reason.lower()

    def test_in_process_allows_safe_path(self, guard_paths_module, tmp_path: Path):
        """The hook allows a safe path within write_root."""
        safe_dir = tmp_path / "skills"
        safe_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "profiles": {
                "default": {
                    "write_roots": [str(safe_dir)],
                }
            }
        }
        data = {"tool_input": {"file_path": str(safe_dir / "test.py")}}

        code, reason = guard_paths_module.evaluate_tool_request(
            data,
            config,
            repo_root=tmp_path,
        )

        assert code == 0
        assert reason is None


class TestBlockedCommandDetection:
    """Tests for blocked command detection."""

    def test_in_process_blocks_protected_command_ref(self, guard_paths_module):
        """The hook blocks a command that references .env."""
        config = {"profiles": {"default": {}}}
        data = {"tool_input": {"command": "cat .env"}}

        code, reason = guard_paths_module.evaluate_tool_request(data, config)

        assert code == 2
        assert reason is not None
        assert "guard_paths:" in reason.lower()

    def test_in_process_allows_safe_command(self, guard_paths_module):
        """The hook allows a safe command."""
        config = {"profiles": {"default": {}}}
        data = {"tool_input": {"command": "ls -la"}}

        code, reason = guard_paths_module.evaluate_tool_request(data, config)

        assert code == 0
        assert reason is None
