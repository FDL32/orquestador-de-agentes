"""Regression: memory_context --status must expose the resolved project root.

Background: the destination adoption gate `memory_points_to_destination` in
scripts/mark_destination_adopted.py runs `memory_context.py --status` and asserts
that the destination path appears in stdout. Before the fix, `_format_status`
printed only the L1/L2/L3 tier flags and never the root, so the gate was
impossible to pass for ANY destination (false blocker). These tests pin the root
line in `--status` so a clean destination with valid memory passes the gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import scripts.memory_context as memory_context
from runtime.project_root import resolve_project_root


MOTOR_ROOT = Path(__file__).resolve().parent.parent


def _seed_destination(root: Path) -> None:
    """Create a minimal destination with a valid L2 memory tier."""
    mem = root / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "memory_rules.md").write_text("# rules\n", encoding="utf-8")


def test_format_status_includes_resolved_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    """_format_status must print 'Project root: <resolved>' for the active root."""
    _seed_destination(tmp_path)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    resolve_project_root.cache_clear()
    try:
        out = memory_context._format_status()
    finally:
        resolve_project_root.cache_clear()

    assert "Project root:" in out
    assert str(tmp_path.resolve()) in out


def test_status_subprocess_exposes_destination_path(tmp_path: Path) -> None:
    """End-to-end: the same invocation the adoption gate uses must echo the root.

    This mirrors mark_destination_adopted.py: run the real CLI with
    AGENT_PROJECT_ROOT set to the destination and assert the destination path is
    in stdout. Guards against the false blocker returning.
    """
    _seed_destination(tmp_path)
    env = {
        "AGENT_PROJECT_ROOT": str(tmp_path),
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
    }
    result = subprocess.run(
        [sys.executable, str(MOTOR_ROOT / "scripts/memory_context.py"), "--status"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert str(tmp_path) in combined or str(tmp_path.resolve()) in combined
