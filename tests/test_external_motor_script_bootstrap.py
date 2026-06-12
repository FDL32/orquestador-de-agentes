"""Regression tests for motor-owned scripts executed from repo_destino."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script_name",
    [
        "session_close_observations.py",
        "memory_consolidate.py",
    ],
)
def test_motor_script_help_runs_from_external_cwd(
    script_name: str,
    tmp_path: Path,
) -> None:
    """Absolute-path execution must resolve bus/runtime from repo_motor."""
    motor_root = Path(__file__).resolve().parents[1]
    script_path = motor_root / "scripts" / script_name

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
