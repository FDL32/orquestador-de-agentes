"""WOT-2026-136d: end-to-end test for roster adoption in agent_controller.py --session-close.

This test exercises the product path: agent_controller.py --session-close with
FLIGHT_ROSTER_PATH exported and --acting-thread passed, verifying that the roster
gate returns PASS/FAIL/SKIP as expected.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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


def _git_output(root: Path, *args: str) -> str:
    """Run git in ``root`` and return its decoded standard output.

    Before: ``root`` is a readable git repository and ``args`` is a valid git
    argument sequence. During: starts git without a shell and captures output.
    After: returns stripped stdout or raises ``CalledProcessError`` when git
    cannot complete.
    """
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _restore_hermetic_motor(motor_root: Path) -> None:
    """Restore the temporary motor and require a clean git status.

    Before: ``motor_root`` is the module-scoped temporary motor created by the
    hermetic fixture. During: resets tracked changes and removes untracked
    files below ``scripts`` only. After: ``git status --porcelain`` is empty;
    git errors propagate to the test so a failed restoration cannot be hidden.
    """
    subprocess.run(["git", "-C", str(motor_root), "reset", "--hard", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(motor_root), "clean", "-fdq", "--", "scripts"],
        check=True,
    )
    assert _git_output(motor_root, "status", "--porcelain") == ""


def _assert_hermetic_motor_clean(motor_root: Path) -> None:
    """Assert the shared temporary motor is clean before a test case.

    Before: the previous case has completed or the module fixture has just
    committed its copied motor. During: reads only the temporary repository's
    porcelain status. After: raises before the close starts if any mutation
    leaked from an earlier case.
    """
    assert _git_output(motor_root, "status", "--porcelain") == ""


@pytest.fixture(scope="module")
def hermetic_close_environment(tmp_path_factory):
    """Build one binary motor copy and one linked destination for this module.

    Before: the test runs on Windows and ``MOTOR_ROOT`` is a tracked git
    worktree. During: copies every tracked working-tree file except ``tests/``
    with ``shutil.copyfile``, initializes a temporary motor with
    ``core.autocrlf=false``, commits it, and creates a destination link plus
    the runtime skeleton required by session close. After: yields paths for
    the module; individual cases restore the motor to a clean status.
    """
    if os.name != "nt":
        pytest.skip("el cierre hermetico requiere Windows y PowerShell del sistema")
    root = tmp_path_factory.mktemp("wot160b_hermetic")
    motor_root = root / "motor"
    destination_root = root / "destination"
    tracked = _git_output(MOTOR_ROOT, "ls-files", "-z").split("\0")
    for relative in tracked:
        if not relative or relative.startswith("tests/"):
            continue
        source = MOTOR_ROOT / relative
        if not source.is_file():
            continue
        target = motor_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    subprocess.run(["git", "init", "-q", str(motor_root)], check=True)
    subprocess.run(
        ["git", "-C", str(motor_root), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(motor_root),
            "-c",
            "user.email=a@a",
            "-c",
            "user.name=a",
            "add",
            "-A",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(motor_root),
            "-c",
            "user.email=a@a",
            "-c",
            "user.name=a",
            "commit",
            "-q",
            "-m",
            "hermetic motor",
        ],
        check=True,
    )
    subprocess.run(["git", "init", "-q", str(destination_root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(destination_root),
            "-c",
            "user.email=a@a",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "destination",
        ],
        check=True,
    )
    (destination_root / ".agent" / "config").mkdir(parents=True)
    (destination_root / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps(
            {"motor_root": str(motor_root).replace("\\", "/"), "ticket_prefix": "WOT"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (destination_root / ".agent" / "runtime" / "events").mkdir(parents=True)
    (destination_root / ".agent" / "runtime" / "events" / "events.jsonl").write_text(
        "", encoding="utf-8"
    )
    (destination_root / ".agent" / "collaboration").mkdir(parents=True)
    (destination_root / ".agent" / "collaboration" / "backlog.md").write_text(
        "# Backlog\n\n## Vista rapida\n\n"
        "| Prioridad | ID | Descripcion | Estado | Commit |\n"
        "|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    yield motor_root, destination_root


@pytest.fixture
def hermetic_close_case(hermetic_close_environment):
    """Provide a clean module motor and restore it around each test case.

    Before: the module fixture has created the temporary motor and destination.
    During: verifies the motor is clean before yielding the shared paths.
    After: restores tracked and ``scripts``-scoped untracked state and verifies
    the motor is clean, so later cases cannot inherit a mutation.
    """
    motor_root, destination_root = hermetic_close_environment
    _assert_hermetic_motor_clean(motor_root)
    try:
        yield motor_root, destination_root
    finally:
        _restore_hermetic_motor(motor_root)


def _write_hermetic_roster(root: Path, thread_id: str = "test-thread-1") -> Path:
    """Write an isolated roster fixture for one hermetic close case.

    Before: ``root`` is the temporary destination owned by the current test.
    During: writes roster, session registry, and change-log fixtures below the
    fixture directory ``root / "fixture_roster"``. After: returns the absolute
    roster path and changes no durable repository state.
    """
    fixture_dir = root / "fixture_roster"
    fixture_dir.mkdir(exist_ok=True)
    (fixture_dir / "flight_roster.json").write_text(
        json.dumps(
            {"active_roles": {"orquestador": {"threadId": thread_id, "version": 1}}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture_dir / "session_registry.json").write_text(
        json.dumps({"sessions": []}, indent=2) + "\n", encoding="utf-8"
    )
    (fixture_dir / "roster_changes.jsonl").write_text("", encoding="utf-8")
    return fixture_dir / "flight_roster.json"


def _write_hermetic_latidos(motor_root: Path, root: Path) -> dict[str, Path]:
    """Write valid coordinator and supervisor latidos for the copied motor.

    Before: ``motor_root`` contains the tracked flight scripts and ``root`` is
    a writable temporary destination. During: writes absolute, valid command
    lines using the test interpreter and system PowerShell without executing
    any alert command. After: returns both latido paths for child-only env
    injection.
    """
    scripts = motor_root / "scripts" / "flight"
    ops = root / "ops"
    ops.mkdir(exist_ok=True)
    python = sys.executable
    coordinator_orders = [
        f"{python} {scripts / 'comms_alert.py'} --scan --ops-dir {ops}",
        f'{python} {scripts / "comms_alert.py"} --event clave --level URGENTE --what "x"',
        f"{python} {scripts / 'flight_stall_check.py'} --ops-dir {ops}",
        f"{python} {scripts / 'flight_stall_check.py'} --self-check",
        f"{python} {scripts / 'quota_tick.py'} > {root / 'quota.txt'}",
        f"{python} {scripts / 'check_latido_alert_wiring.py'} --alert",
        f"{python} {scripts / 'tick_trace.py'} --ops-dir {ops} --coordinator CO-52 "
        f"--roster-sha12 0123456789ab --guard-rc 0 --quota-rc 0 --quota-summary ok",
    ]
    powershell = (
        Path(os.environ["SYSTEMROOT"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    supervisor_orders = [
        f"{powershell} -NoProfile -NonInteractive -File {scripts / 'notify_user.ps1'} "
        "-Title t -Message m",
        f"{python} {scripts / 'quota_tick.py'}",
    ]
    paths = {
        "coordinadora": root / "coordinadora.md",
        "supervisora": root / "supervisora.md",
    }
    paths["coordinadora"].write_text(
        "Latido.\n" + "\n".join(f"- `{order}`" for order in coordinator_orders) + "\n",
        encoding="utf-8",
    )
    paths["supervisora"].write_text(
        "Latido.\n" + "\n".join(f"- `{order}`" for order in supervisor_orders) + "\n",
        encoding="utf-8",
    )
    return paths


def _run_hermetic_session_close(
    motor_root: Path,
    destination_root: Path,
    roster_path: Path,
    latido_paths: dict[str, Path],
    acting_thread: str,
):
    """Run the real session close against the copied motor and linked target.

    Before: the temporary motor and fixture paths are valid; callers may
    intentionally dirty the temporary motor for negative cases.
    During: launches ``agent_controller.py`` from the copied motor, injecting
    roster, latido, and Python variables only into the child environment; no
    ``--alert`` flag is passed. The 180-second subprocess timeout is a guard
    against a hung close, not a performance budget. After: returns the
    subprocess result, elapsed seconds, and complete close report text,
    deleting any stale report first.
    """
    report_path = (
        destination_root / ".agent" / "runtime" / "memory" / "session_close_report.md"
    )
    report_path.unlink(missing_ok=True)
    env = os.environ.copy()
    env["FLIGHT_ROSTER_PATH"] = str(roster_path)
    env["FLIGHT_LATIDO_FILES"] = ";".join(
        f"{role}={path}" for role, path in latido_paths.items()
    )
    env["FLIGHT_PYTHON"] = sys.executable
    command = [
        sys.executable,
        str(motor_root / ".agent" / "agent_controller.py"),
        "--project-root",
        str(destination_root),
        "--session-close",
        "--ticket",
        "WOT-9999-999z",
        "--skip-gates",
        "--skip-slow",
        "--force",
        "--acting-thread",
        acting_thread,
    ]
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=str(destination_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.monotonic() - started
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    return result, elapsed, report


def _assert_hermetic_rows(
    report: str,
    expected: dict[str, tuple[str, str]],
) -> None:
    """Assert exact named closeout rows and print the full report on failure.

    Before: ``report`` is the closeout markdown and ``expected`` maps each
    required step to its exact ``(status, blocking)`` pair. During: reuses the
    existing anchored table parser and compares only named rows. After: every
    expected row matches exactly; an assertion includes the complete report.
    """
    rows, _denominator = _parse_step_table(report)
    for name, expected_row in expected.items():
        actual = [(status, blocking) for step, status, blocking in rows if step == name]
        assert actual == [expected_row], report


def _assert_only_blocking_failures(report: str, expected: list[str]) -> None:
    """Require that a negative close fails only at its intended gate.

    Before: ``report`` is the complete closeout report for one mutation. During:
    parses every anchored row and selects only rows marked ``FAIL`` and
    blocking ``Yes``. After: the ordered failing step names equal ``expected``;
    the complete report is included if an unrelated blocker appears.
    """
    rows, _denominator = _parse_step_table(report)
    actual = [
        name
        for name, status, blocking in rows
        if status == "FAIL" and blocking == "Yes"
    ]
    assert actual == expected, report


def _assert_close_stops_after(report: str, step_name: str) -> None:
    """Require the blocking close report stops immediately after a gate.

    Before: ``report`` contains the complete table from a close expected to
    abort at ``step_name``. During: parses the anchored rows. After: the final
    parsed row is exactly ``step_name``; later execution caused by a removed
    return is reported with the complete report.
    """
    rows, _denominator = _parse_step_table(report)
    assert rows and rows[-1][0] == step_name, report


def _assert_parent_latido_env_absent() -> None:
    """Require the pytest process itself has no flight latido override.

    Before: called at a test boundary where monkeypatch has not changed the
    process environment. During: reads only the current process environment.
    After: raises an assertion if ``FLIGHT_LATIDO_FILES`` leaked into pytest.
    """
    assert "FLIGHT_LATIDO_FILES" not in os.environ


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


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_passes_roster_and_latido_gates(
    hermetic_close_case, monkeypatch
):
    """Run a successful close from the copied motor with child-only latidos.

    Before: the module fixture supplies a clean copied motor and linked
    destination, while pytest has no ``FLIGHT_LATIDO_FILES`` override. During:
    runs the real close with valid roster and coordinator/supervisor latidos.
    After: requires rc 0, exact PASS rows for both blocking gates, and no
    parent-process environment leak.
    """
    del monkeypatch
    _assert_parent_latido_env_absent()
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "test-thread-1"
    )
    assert result.returncode == 0, result.stdout + result.stderr + report
    _assert_hermetic_rows(
        report,
        {
            "roster_matches_acting_thread": ("PASS", "Yes"),
            "latido_alert_wiring": ("PASS", "Yes"),
        },
    )
    _assert_parent_latido_env_absent()


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_rejects_uncommitted_latido_script(hermetic_close_case):
    """Reject a copied script changed after the hermetic commit.

    Before: the copied motor is clean and valid latidos would pass. During:
    appends one byte-level mutation to ``tick_trace.py`` and runs the close.
    After: rc is nonzero, the latido row is blocking FAIL with the exact
    script-diff detail, and the report proves the copied motor path.
    """
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    target = motor_root / "scripts" / "flight" / "tick_trace.py"
    target.write_bytes(target.read_bytes() + b"\n# WOT-2026-160b mutation\n")
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "test-thread-1"
    )
    assert result.returncode != 0, report
    _assert_hermetic_rows(
        report,
        {
            "roster_matches_acting_thread": ("PASS", "Yes"),
            "latido_alert_wiring": ("FAIL", "Yes"),
        },
    )
    _assert_only_blocking_failures(report, ["latido_alert_wiring"])
    _assert_close_stops_after(report, "latido_alert_wiring")
    assert "el script es distinto de HEAD" in report, report
    assert f"--motor-root {motor_root}" in report, report


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_rejects_staged_latido_script(hermetic_close_case):
    """Reject a copied script whose mutation is staged but uncommitted.

    Before: the copied motor is clean and its valid latidos pass. During:
    changes ``tick_trace.py`` once, stages that same change, and runs close.
    After: rc is nonzero, the exact blocking latido row fails, and the report
    names both the HEAD mismatch and staged-index violation.
    """
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    target = motor_root / "scripts" / "flight" / "tick_trace.py"
    target.write_bytes(target.read_bytes() + b"\n# WOT-2026-160b staged mutation\n")
    subprocess.run(
        ["git", "-C", str(motor_root), "add", "scripts/flight/tick_trace.py"],
        check=True,
    )
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "test-thread-1"
    )
    assert result.returncode != 0, report
    _assert_hermetic_rows(
        report,
        {
            "roster_matches_acting_thread": ("PASS", "Yes"),
            "latido_alert_wiring": ("FAIL", "Yes"),
        },
    )
    _assert_only_blocking_failures(report, ["latido_alert_wiring"])
    _assert_close_stops_after(report, "latido_alert_wiring")
    assert "el script es distinto de HEAD" in report, report
    assert "cambios preparados en el indice sin commit" in report, report


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_rejects_coordinator_latido_without_event(hermetic_close_case):
    """Reject valid-looking latidos when the mandatory event order is absent.

    Before: the copied motor, roster, and both valid latidos form the positive
    control. During: removes only the coordinator ``comms_alert.py --event``
    order and runs the real close. After: rc is nonzero and only the exact
    blocking latido row fails for the missing mandatory order.
    """
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    coordinator = latidos["coordinadora"]
    coordinator.write_text(
        "\n".join(
            line
            for line in coordinator.read_text(encoding="utf-8").splitlines()
            if "comms_alert.py --event" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "test-thread-1"
    )
    assert result.returncode != 0, report
    _assert_hermetic_rows(
        report,
        {
            "roster_matches_acting_thread": ("PASS", "Yes"),
            "latido_alert_wiring": ("FAIL", "Yes"),
        },
    )
    _assert_only_blocking_failures(report, ["latido_alert_wiring"])
    _assert_close_stops_after(report, "latido_alert_wiring")
    assert "falta una orden VALIDA de comms_alert.py --event" in report, report


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_rejects_absent_supervisor_latido(hermetic_close_case):
    """Reject a close when one required role has no latido file.

    Before: the copied motor, roster, and both valid latidos form the positive
    control. During: removes only the supervisor entry from the child-only
    ``FLIGHT_LATIDO_FILES`` mapping and runs the real close. After: rc is
    nonzero, only the blocking latido row fails, and the close stops there.
    """
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    latidos.pop("supervisora")
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "test-thread-1"
    )
    assert result.returncode != 0, report
    _assert_hermetic_rows(
        report,
        {
            "roster_matches_acting_thread": ("PASS", "Yes"),
            "latido_alert_wiring": ("FAIL", "Yes"),
        },
    )
    _assert_only_blocking_failures(report, ["latido_alert_wiring"])
    _assert_close_stops_after(report, "latido_alert_wiring")
    assert "supervisora: sin latido" in report, report


@pytest.mark.skipif(
    os.name != "nt",
    reason="el cierre hermetico requiere Windows y PowerShell del sistema",
)
def test_hermetic_close_roster_failure_cuts_before_latido(hermetic_close_case):
    """Stop at the roster gate before evaluating otherwise valid latidos.

    Before: the copied motor, valid roster, and valid latidos form the positive
    control. During: changes only the acting thread passed to the close.
    After: rc is nonzero, the roster row is blocking FAIL, and no latido row is
    present in the complete report.
    """
    motor_root, destination_root = hermetic_close_case
    roster = _write_hermetic_roster(destination_root)
    latidos = _write_hermetic_latidos(motor_root, destination_root)
    result, _elapsed, report = _run_hermetic_session_close(
        motor_root, destination_root, roster, latidos, "otro-hilo-distinto"
    )
    assert result.returncode != 0, report
    _assert_hermetic_rows(
        report,
        {"roster_matches_acting_thread": ("FAIL", "Yes")},
    )
    _assert_only_blocking_failures(report, ["roster_matches_acting_thread"])
    rows, _denominator = _parse_step_table(report)
    assert not _has_step(rows, "latido_alert_wiring"), report


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
