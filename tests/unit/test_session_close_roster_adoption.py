"""WOT-2026-136d: end-to-end test for roster adoption in agent_controller.py --session-close.

This test exercises the product path: agent_controller.py --session-close with
FLIGHT_ROSTER_PATH exported and --acting-thread passed, verifying that the roster
gate returns PASS/FAIL/SKIP as expected.
"""

from __future__ import annotations

import json
import os
import re
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


def _write_fixture_roster(root: Path) -> Path:
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
    env.pop("FLIGHT_LATIDO_FILES", None)
    if roster_path is not None:
        env["FLIGHT_ROSTER_PATH"] = str(roster_path)
    elif "FLIGHT_ROSTER_PATH" in env:
        del env["FLIGHT_ROSTER_PATH"]
    start = time.monotonic()
    report_path = root / ".agent" / "runtime" / "memory" / "session_close_report.md"
    report_path.unlink(missing_ok=True)
    result = subprocess.run(
        cmd,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - start
    report_text = (
        report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    )
    return result, elapsed, report_text


def _parse_step_table(report_text: str) -> tuple[list[tuple[str, str, str]], int]:
    """Parse anchored closeout rows and return statuses plus row denominator.

    Before: ``report_text`` is the markdown report emitted by session close.
    During: matches only complete step-row prefixes, ignoring headers and
        arbitrary detail text (including escaped pipes).
    After: returns ``[(step_name, status, blocking)]`` and the number of parsed rows;
        malformed or absent rows are not counted.
    """
    row_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*"
        r"(PASS|FAIL|WARN|SKIP)\s*\|\s*(Yes|No)\s*\|",
        re.MULTILINE,
    )
    rows = [
        (match.group(1).strip(), match.group(2), match.group(3))
        for match in row_pattern.finditer(report_text)
    ]
    return rows, len(rows)


def _has_step(rows: list[tuple[str, str, str]], name: str) -> bool:
    """Check a step by its row name, independently of status or blocking.

    Before: ``rows`` contains parsed ``(name, status, blocking)`` tuples.
    During: scans the name field of every row without relying on container
        membership semantics for a different element type.
    After: returns ``True`` exactly when a row with ``name`` exists.
    """
    return any(row[0] == name for row in rows)


class TestStepTableParser:
    def test_parser_returns_statuses_and_denominator(self):
        report = (
            "## Steps\n\n"
            "| # | Step | Status | Blocking | Detail |\n"
            "|---|---|---|---|---|\n"
            "| 5 | roster_matches_acting_thread | PASS | Yes | ok |\n"
            "| 6 | latido_alert_wiring | FAIL | Yes | detalle FAIL |\n"
        )
        assert _parse_step_table(report) == (
            [
                ("roster_matches_acting_thread", "PASS", "Yes"),
                ("latido_alert_wiring", "FAIL", "Yes"),
            ],
            2,
        )
        rows, _denominator = _parse_step_table(report)
        assert _has_step(rows, "latido_alert_wiring")

    def test_parser_ignores_fail_in_detail_and_malformed_rows(self):
        report = (
            "texto FAIL fuera de tabla\n"
            "| 5 | roster_matches_acting_thread | PASS | Yes | detalle FAIL |\n"
            "| 6 | malformed | FAIL |\n"
        )
        assert _parse_step_table(report) == (
            [("roster_matches_acting_thread", "PASS", "Yes")],
            1,
        )

    def test_parser_handles_escaped_detail_pipe_and_final_line_without_newline(self):
        report = "| 6 | latido_alert_wiring | FAIL | Yes | a \\| b |"
        assert _parse_step_table(report) == (
            [("latido_alert_wiring", "FAIL", "Yes")],
            1,
        )

    def test_parser_counts_duplicate_names_and_two_failures(self):
        report = (
            "| 1 | same | FAIL | Yes | first |\n"
            "| 2 | same | PASS | No | duplicate name |\n"
            "| 3 | other | FAIL | Yes | second |\n"
        )
        assert _parse_step_table(report) == (
            [
                ("same", "FAIL", "Yes"),
                ("same", "PASS", "No"),
                ("other", "FAIL", "Yes"),
            ],
            3,
        )

    def test_parser_returns_empty_for_empty_or_absent_table(self):
        assert _parse_step_table("") == ([], 0)
        assert _parse_step_table("sin tabla y sin filas FAIL") == ([], 0)


def test_roster_step_pass_when_acting_thread_matches(
    hermetic_project_root, monkeypatch
):
    monkeypatch.setenv("FLIGHT_LATIDO_FILES", "coordinadora=stale-latido.json")
    captured = {}
    real_run = subprocess.run

    def capture_run(*args, **kwargs):
        command = args[0] if args else kwargs.get("args", [])
        if "--session-close" in command:
            captured["env"] = kwargs["env"]
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_run)
    roster_path = _write_fixture_roster(hermetic_project_root)
    result, elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, "test-thread-1"
    )
    assert elapsed < 60, f"excedio presupuesto: {elapsed}s"
    steps, denominator = _parse_step_table(report)
    assert [row for row in steps if row[0] == "roster_matches_acting_thread"] == [
        ("roster_matches_acting_thread", "PASS", "Yes")
    ], report
    assert result.returncode == 1, result.stdout + result.stderr
    assert denominator >= 2, report
    assert {name for name, status, _blocking in steps if status == "FAIL"} == {
        "latido_alert_wiring"
    }, report
    assert [row for row in steps if row[0] == "latido_alert_wiring"] == [
        ("latido_alert_wiring", "FAIL", "Yes")
    ], report
    assert steps[-1][0] == "latido_alert_wiring", report
    assert "FLIGHT_LATIDO_FILES" not in captured["env"]


def test_run_session_close_discards_stale_report_when_subprocess_writes_nothing(
    hermetic_project_root, monkeypatch
):
    report_path = (
        hermetic_project_root
        / ".agent"
        / "runtime"
        / "memory"
        / "session_close_report.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("stale report", encoding="utf-8")

    def no_report_run(*args, **kwargs):
        command = args[0] if args else kwargs.get("args", [])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", no_report_run)
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, None, "test-thread-1"
    )
    assert result.returncode == 0
    assert report == ""


def test_roster_step_fail_when_acting_thread_mismatches(hermetic_project_root):
    report_path = (
        hermetic_project_root
        / ".agent"
        / "runtime"
        / "memory"
        / "session_close_report.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "| 5 | roster_matches_acting_thread | PASS | Yes | stale |\n",
        encoding="utf-8",
    )
    roster_path = _write_fixture_roster(hermetic_project_root)
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, "otro-hilo-distinto"
    )
    steps, denominator = _parse_step_table(report)
    assert [row for row in steps if row[0] == "roster_matches_acting_thread"] == [
        ("roster_matches_acting_thread", "FAIL", "Yes")
    ], report
    assert denominator >= 1, report
    assert not _has_step(steps, "latido_alert_wiring"), report
    assert result.returncode == 1


def test_roster_step_skip_without_flight_roster_path(hermetic_project_root):
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, None, "test-thread-1"
    )
    steps, _denominator = _parse_step_table(report)
    assert [row for row in steps if row[0] == "roster_matches_acting_thread"] == [
        ("roster_matches_acting_thread", "SKIP", "No")
    ], report
    assert result.returncode == 0, result.stdout + result.stderr


def test_roster_step_fail_without_acting_thread(hermetic_project_root):
    roster_path = _write_fixture_roster(hermetic_project_root)
    result, _elapsed, report = _run_session_close(
        hermetic_project_root, roster_path, None
    )
    steps, _denominator = _parse_step_table(report)
    assert [row for row in steps if row[0] == "roster_matches_acting_thread"] == [
        ("roster_matches_acting_thread", "FAIL", "Yes")
    ], report
    assert not _has_step(steps, "latido_alert_wiring"), report
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
