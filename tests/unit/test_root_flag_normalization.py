"""Regression tests for root flag normalization (WOT-2026-043r).

Before: create isolated real filesystem and git fixtures.
During: invoke each production script through subprocess with relative and
absolute root arguments.
After: verify both forms have identical, discriminating return codes.

The literal pre-fix pairs were: prefix_resolver relative rc 0 with
``0 prefixes mapped`` versus absolute rc 1 with ``DUPLICATE``;
check_worktree_topology relative rc 2 with ``prefijo desconocido`` versus
absolute rc 1 with ``necesita el workspace``; delivery_hygiene_check relative
rc 0 with a false-green ``SKIP`` versus absolute rc 1 with ``MISPLACED``.
The relative form could therefore produce an empty or false green result.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_check_worktree_topology import (
    _make_git_tree,
    _make_link,
    _make_linked_worktree,
)


def _run_script(
    script: Path, args: list[str], cwd: Path, ceiling: Path
) -> subprocess.CompletedProcess[str]:
    """Before: receive one production script invocation.

    During: run the absolute script path without a shell or output pipe.

    After: return the subprocess result with its real return code.
    """
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prefix_resolver_root_forms_have_same_duplicate_result(
    tmp_path: Path,
) -> None:
    """Before: create two WOT links under a non-git sandbox.

    During: invoke prefix_resolver with relative and absolute motor roots.

    After: both real invocations return duplicate-prefix rc 1.
    """
    sandbox = tmp_path / "sandbox"
    motor = sandbox / "motor"
    dest_a = sandbox / "destA"
    dest_b = sandbox / "destB"
    for destination in (motor, dest_a, dest_b):
        destination.mkdir(parents=True)
    for destination in (dest_a, dest_b):
        link = destination / ".agent" / "config" / "motor_destination_link.json"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text(
            json.dumps(
                {
                    "motor_root": str(motor.resolve()),
                    "destination_root": str(destination.resolve()),
                    "ticket_prefix": "WOT",
                    "destination_id": destination.name,
                }
            ),
            encoding="utf-8",
        )

    script = Path(__file__).resolve().parents[2] / "scripts" / "prefix_resolver.py"
    relative = _run_script(script, ["--verify", "--motor-root", "."], motor, tmp_path)
    absolute = _run_script(
        script,
        ["--verify", "--motor-root", str(motor.resolve())],
        motor,
        tmp_path,
    )

    assert relative.args[1] == absolute.args[1] == str(script)
    assert relative.returncode == absolute.returncode == 1
    assert "DUPLICATE prefix 'WOT'" in relative.stdout + relative.stderr
    assert "DUPLICATE prefix 'WOT'" in absolute.stdout + absolute.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_topology_root_forms_have_same_missing_workspace_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: create the canonical motor and linked CTL destination topology.

    During: invoke check_worktree_topology from motor_dev without project-root.

    After: both real invocations return the same missing-workspace rc 1.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    motor, motor_dev = _make_git_tree(tmp_path)
    destination = _make_linked_worktree(tmp_path, "dest_ctl")
    _make_link(destination, motor, "CTL", "dest_ctl")
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "check_worktree_topology.py"
    )

    relative = _run_script(
        script,
        ["--ticket", "CTL-2026-001a", "--motor-root", "."],
        motor_dev,
        tmp_path,
    )
    absolute = _run_script(
        script,
        ["--ticket", "CTL-2026-001a", "--motor-root", str(motor.resolve())],
        motor_dev,
        tmp_path,
    )

    assert relative.args[1] == absolute.args[1] == str(script)
    assert relative.returncode == absolute.returncode == 1
    assert "necesita el workspace" in relative.stdout + relative.stderr
    assert "necesita el workspace" in absolute.stdout + absolute.stderr


def test_delivery_hygiene_root_forms_have_same_misplaced_backlog_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: create a git destination with a motor workspace declaration.

    During: invoke delivery_hygiene_check with relative and absolute roots.

    After: both real invocations return the misplaced-backlog rc 1.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "fixture"
    motor = root / "motor"
    motor_workspace = root / "motor_ws"
    project = root / "p"
    for path in (motor, motor_workspace, project):
        path.mkdir(parents=True)
    (motor / ".agent" / "config").mkdir(parents=True)
    (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
        "motor_ws", encoding="ascii"
    )
    motor_link = motor_workspace / ".agent" / "config"
    motor_link.mkdir(parents=True)
    (motor_link / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor.resolve()),
                "destination_root": str(motor_workspace.resolve()),
                "ticket_prefix": "ABC",
            }
        ),
        encoding="ascii",
    )
    (project / ".agent" / "collaboration").mkdir(parents=True)
    (project / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: noop\n        stages: [commit]\n",
        encoding="ascii",
    )
    (project / ".agent" / "collaboration" / "backlog.md").write_text(
        "| Media | ABC-2026-001a | row | pending | - | "
        "delivery_authority: repo_motor |\n",
        encoding="ascii",
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(project)],
        check=True,
        capture_output=True,
        text=True,
    )
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "delivery_hygiene_check.py"
    )
    common = ["--project-root", str(project), "--no-tree-check"]
    relative = _run_script(script, ["--motor-root", ".", *common], motor, tmp_path)
    absolute = _run_script(
        script,
        ["--motor-root", str(motor.resolve()), *common],
        motor,
        tmp_path,
    )

    assert relative.args[1] == absolute.args[1] == str(script)
    assert relative.returncode == absolute.returncode == 1
    assert "BACKLOG_DELIVERY_AUTHORITY_MISPLACED" in (relative.stdout + relative.stderr)
    assert "BACKLOG_DELIVERY_AUTHORITY_MISPLACED" in (absolute.stdout + absolute.stderr)
