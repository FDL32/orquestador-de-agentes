"""WOT-2026-136d: end-to-end test for roster adoption in agent_controller.py --session-close.

This test exercises the product path: agent_controller.py --session-close with
FLIGHT_ROSTER_PATH exported and --acting-thread passed, verifying that the roster
gate returns PASS/FAIL/SKIP as expected.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def hermetic_project_root(tmp_path_factory):
    """Minimal project-root skeleton to exercise agent_controller.py --session-close
    hermetically. Built ONCE per module (reused across the 4 cases of this file);
    each test writes its OWN fixture_roster inside to avoid sharing mutable state.
    """
    root = tmp_path_factory.mktemp("wot136d_hermetic")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=a@a",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )
    (root / ".agent" / "config").mkdir(parents=True)
    link = {"motor_root": str(MOTOR_ROOT).replace("\\\\", "/"), "ticket_prefix": "WOT"}
    (root / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps(link, indent=2) + "\n", encoding="utf-8"
    )
    (root / ".agent" / "runtime" / "events").mkdir(parents=True)
    (root / ".agent" / "runtime" / "events" / "events.jsonl").write_text(
        "", encoding="utf-8"
    )
    (root / ".agent" / "collaboration").mkdir(parents=True)
    (root / ".agent" / "collaboration" / "backlog.md").write_text(
        "# Backlog\n\n## Vista rapida\n\n"
        "| Prioridad | ID | Descripcion | Estado | Commit |\n"
        "|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    return root


def _write_fixture_roster(root: Path, *, estado_matches: bool) -> Path:
    fixture_dir = root / "fixture_roster"
    fixture_dir.mkdir(exist_ok=True)
    roster = {
        "active_roles": {"orquestador": {"threadId": "test-thread-1", "version": 1}}
    }
    (fixture_dir / "flight_roster.json").write_text(
        json.dumps(roster, indent=2) + "\n", encoding="utf-8"
    )
    (fixture_dir / "session_registry.json").write_text(
        json.dumps({"sessions": []}, indent=2) + "\n", encoding="utf-8"
    )
    (fixture_dir / "roster_changes.jsonl").write_text("", encoding="utf-8")
    return fixture_dir / "flight_roster.json"


def _run_session_close(root: Path, roster_path: Path | None, acting_thread: str | None):
    cmd = [
        sys.executable,
        str(MOTOR_ROOT / ".agent" / "agent_controller.py"),
        "--project-root",
        str(root),
        "--session-close",
        "--ticket",
        "WOT-9999-999z",
        "--skip-gates",
        "--skip-slow",
        "--force",
    ]
    if acting_thread:
        cmd.extend(["--acting-thread", acting_thread])
    env = os.environ.copy()
    if roster_path is not None:
        env["FLIGHT_ROSTER_PATH"] = str(roster_path)
    elif "FLIGHT_ROSTER_PATH" in env:
        del env["FLIGHT_ROSTER_PATH"]
    start = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - start
    report_path = root / ".agent" / "runtime" / "memory" / "session_close_report.md"
    report_text = (
        report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    )
    return result, elapsed, report_text


def _roster_step_status(report_text: str) -> str | None:
    import re

    m = re.search(r"\|\s*roster_matches_acting_thread\s*\|\s*(\w+)\s*\|", report_text)
    return m.group(1) if m else None


def test_roster_step_pass_when_acting_thread_matches(hermetic_project_root):
    roster_path = _write_fixture_roster(hermetic_project_root, estado_matches=True)
    result, elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, "test-thread-1"
    )
    assert elapsed < 60, f"excedio presupuesto: {elapsed}s"
    assert _roster_step_status(report) == "PASS", report
    assert result.returncode == 0, result.stdout + result.stderr


def test_roster_step_fail_when_acting_thread_mismatches(hermetic_project_root):
    roster_path = _write_fixture_roster(hermetic_project_root, estado_matches=True)
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, "otro-hilo-distinto"
    )
    assert _roster_step_status(report) == "FAIL", report
    assert result.returncode == 1


def test_roster_step_skip_without_flight_roster_path(hermetic_project_root):
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, None, "test-thread-1"
    )
    assert _roster_step_status(report) == "SKIP", report
    assert result.returncode == 0, result.stdout + result.stderr


def test_roster_step_fail_without_acting_thread(hermetic_project_root):
    roster_path = _write_fixture_roster(hermetic_project_root, estado_matches=True)
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, None
    )
    assert _roster_step_status(report) == "FAIL", report
    assert result.returncode == 1


def test_roster_step_mutation_m2_retirar_acting_thread_forwarding():
    """MUTACION CAUSAL M2 (la mide el MANAGER en copia tmp, NO la ejecutes tu de forma
    destructiva sobre el working tree real). Este test queda como PLACEHOLDER documental:
    deja un comentario citando que la mutacion real (retirar .agent/agent_controller.py:7175-7176,
    el bloque `if acting_thread: cmd.extend(["--acting-thread", acting_thread])`) la mide el
    Manager por fuera de la suite, con copy-restore y diff vacio. NO implementes aqui un
    monkeypatch que borre codigo de produccion.
    """
    pytest.skip(
        "Mutacion M2 medida por el Manager fuera de la suite (copy-restore en tmp)"
    )
