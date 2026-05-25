"""Tests for launcher preflight import checks (WP-2026-118).

These tests verify that the launcher correctly detects import failures
in critical bus modules before opening any terminal windows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_import_preflight_success():
    """Test that preflight passes when all critical modules import cleanly.

    Before: No preflight check exists.
    During: Runs Python import check for bus.event_bus, bus.review_bridge,
            and agent_controller modules.
    After: Returns exit code 0 if all imports succeed.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}'); "
            f"sys.path.insert(0, r'{PROJECT_ROOT / '.agent'}'); "
            "__import__('bus.event_bus'); "
            "__import__('bus.review_bridge'); "
            "__import__('agent_controller')",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )
    assert result.returncode == 0, f"Preflight should pass. stderr: {result.stderr}"


def test_import_preflight_detects_broken_module(monkeypatch, tmp_path):
    """Test that preflight fails when a critical module has import errors.

    Before: Import errors would only be detected at runtime.
    During: Simulates a broken bus module by injecting an import error.
    After: Import fails with non-zero exit code, launcher would abort.
    """
    # Create a fake broken module
    broken_bus_dir = tmp_path / "bus"
    broken_bus_dir.mkdir()
    (broken_bus_dir / "__init__.py").write_text("")
    (broken_bus_dir / "event_bus.py").write_text("import nonexistent_module_xyz")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, r'{tmp_path}'); "
            "__import__('bus.event_bus')",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )
    assert result.returncode != 0, "Preflight should detect broken import"
    assert (
        "nonexistent_module_xyz" in result.stderr
        or "ModuleNotFoundError" in result.stderr
    )


def test_critical_modules_exist():
    """Test that all critical modules required by preflight actually exist.

    Before: Modules could be missing and only fail at runtime.
    During: Checks file existence of critical module paths.
    After: All critical module files are confirmed to exist.
    """
    critical_paths = [
        PROJECT_ROOT / "bus" / "__init__.py",
        PROJECT_ROOT / "bus" / "event_bus.py",
        PROJECT_ROOT / "bus" / "review_bridge.py",
        PROJECT_ROOT / ".agent" / "agent_controller.py",
    ]

    for path in critical_paths:
        assert path.exists(), f"Critical module path missing: {path}"


def test_bus_event_bus_imports_cleanly():
    """Test that bus.event_bus imports without errors.

    WP-2026-118: This is one of the critical modules checked at launch.
    """
    try:
        import bus.event_bus

        assert hasattr(bus.event_bus, "EventBus")
        assert hasattr(bus.event_bus, "EventRecord")
    except ImportError as e:
        pytest.fail(f"bus.event_bus failed to import: {e}")


def test_bus_review_bridge_imports_cleanly():
    """Test that bus.review_bridge imports without errors.

    WP-2026-118: This is one of the critical modules checked at launch.
    """
    try:
        import bus.review_bridge

        assert hasattr(bus.review_bridge, "ReviewBridge")
        assert hasattr(bus.review_bridge, "ReviewDecision")
    except ImportError as e:
        pytest.fail(f"bus.review_bridge failed to import: {e}")


def test_agent_controller_imports_cleanly():
    """Test that agent_controller imports without errors.

    WP-2026-118: This is one of the critical modules checked at launch.
    """
    try:
        import agent_controller

        assert hasattr(agent_controller, "get_human_gate_threshold")
    except ImportError as e:
        pytest.fail(f"agent_controller failed to import: {e}")
