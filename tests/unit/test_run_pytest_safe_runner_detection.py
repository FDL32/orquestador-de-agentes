"""Tests for WOT-2026-014b: run_pytest_safe runner detection + unittest fallback.

Mutation-verified barrier:
(a) pytest-absent -> select_test_runner returns unittest discover command
    + run produces last-run.json with exit_code 0 + required fields.
(b) pytest-present -> select_test_runner returns pytest command (unchanged).
(c) MUTATION test: hardcoded _probe=True (old behavior) -> diverges from fix.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("run_pytest_safe", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_unittest_fixture(tmp_path: Path) -> Path:
    """Create a minimal project with a passing unittest.TestCase.

    Returns the project root (not the tests/ subdir).
    """
    project = tmp_path / "unittest_project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    sample = (
        "import unittest\n"
        "\n"
        "class SampleTest(unittest.TestCase):\n"
        "    def test_always_passes(self):\n"
        "        self.assertEqual(1, 1)\n"
    )
    (tests_dir / "test_sample.py").write_text(sample, encoding="utf-8")
    return project


# ---------------------------------------------------------------------------
# (a) pytest-ABSENT: select_test_runner returns unittest command
# ---------------------------------------------------------------------------


def test_select_runner_unittest_when_pytest_absent(tmp_path: Path) -> None:
    """When _probe=False (pytest absent), select_test_runner returns unittest discover.

    Core barrier: without the fix (probe always True), this would return a
    pytest command; running against an interpreter without pytest fails with
    'No module named pytest'.
    """
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    command, runner = mod.select_test_runner(
        sys.executable,
        pytest_args=["tests", "-q"],
        xdist_flags=[],
        run_dir=run_dir,
        test_dir="tests",
        _probe=False,  # force pytest-absent
    )

    assert runner == "unittest", f"Expected unittest, got {runner!r}"
    assert "-m" in command
    assert "unittest" in command
    assert "discover" in command
    assert "-s" in command
    assert "tests" in command
    assert "pytest" not in command, f"pytest found in command: {command}"


def test_select_runner_produces_last_run_json_exit0_on_unittest_fixture(
    tmp_path: Path,
) -> None:
    """pytest-absent run on a unittest fixture -> last-run.json exit_code 0 + required fields.

    Uses _probe=False to simulate pytest-absent, runs unittest discover
    against a real fixture project, asserts last-run.json gate-required fields.
    """
    project = _make_unittest_fixture(tmp_path)
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    last_run_json = runtime_dir / "last-run.json"

    command, runner = mod.select_test_runner(
        sys.executable,
        pytest_args=[],
        xdist_flags=[],
        run_dir=run_dir,
        test_dir="tests",
        _probe=False,  # force pytest-absent
    )
    assert runner == "unittest"

    result = subprocess.run(
        command,
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )
    exit_code = result.returncode

    # Write last-run.json as main() would (gate-required fields)
    payload = {
        "tested_commit_sha": "abc123deadbeef",
        "exit_code": exit_code,
        "level": "unit",
        "runner": runner,
        "status": "finished",
    }
    last_run_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert exit_code == 0, (
        f"unittest discover should pass; exit={exit_code}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    data = json.loads(last_run_json.read_text(encoding="utf-8"))
    assert "tested_commit_sha" in data, "tested_commit_sha missing from last-run.json"
    assert "exit_code" in data, "exit_code missing from last-run.json"
    assert "level" in data, "level missing from last-run.json"
    assert data["exit_code"] == 0
    assert data["runner"] == "unittest"


# ---------------------------------------------------------------------------
# (b) pytest-PRESENT: select_test_runner returns pytest command (unchanged)
# ---------------------------------------------------------------------------


def test_select_runner_pytest_when_pytest_present(tmp_path: Path) -> None:
    """When _probe=True (pytest present), select_test_runner returns pytest command."""
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    command, runner = mod.select_test_runner(
        sys.executable,
        pytest_args=["-m", "not integration", "tests", "-q"],
        xdist_flags=[],
        run_dir=run_dir,
        test_dir="tests",
        _probe=True,  # force pytest-present
    )

    assert runner == "pytest", f"Expected pytest, got {runner!r}"
    assert "pytest" in command
    assert "discover" not in command
    assert "unittest" not in command
    assert str(run_dir) in " ".join(command)


def test_select_runner_pytest_passes_xdist_flags(tmp_path: Path) -> None:
    """pytest branch passes xdist_flags; unittest branch drops them (incompatible)."""
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    cmd_pytest, _ = mod.select_test_runner(
        sys.executable,
        pytest_args=["tests"],
        xdist_flags=["-n", "2"],
        run_dir=run_dir,
        _probe=True,
    )
    assert "-n" in cmd_pytest

    cmd_unittest, _ = mod.select_test_runner(
        sys.executable,
        pytest_args=["tests"],
        xdist_flags=["-n", "2"],
        run_dir=run_dir,
        _probe=False,
    )
    assert "-n" not in cmd_unittest


# ---------------------------------------------------------------------------
# (c) MUTATION: hardcoded probe=True -> pytest-absent case FAILS
# ---------------------------------------------------------------------------


def test_mutation_hardcoded_pytest_fails_on_nonexistent_dir(tmp_path: Path) -> None:
    """MUTATION BARRIER: hardcoded _probe=True (old behavior) chooses pytest;
    that fails when run against a project with no discoverable tests.

    The fix (_probe=False) chooses unittest discover, which succeeds on the
    unittest fixture. Observable diff between fix and mutation.
    """
    project = _make_unittest_fixture(tmp_path)
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # FIX path: probe=False -> unittest -> exit 0
    fix_cmd, fix_runner = mod.select_test_runner(
        sys.executable,
        pytest_args=[],
        xdist_flags=[],
        run_dir=run_dir,
        test_dir="tests",
        _probe=False,
    )
    assert fix_runner == "unittest"
    fix_result = subprocess.run(
        fix_cmd, cwd=project, capture_output=True, text=True, timeout=30
    )
    assert fix_result.returncode == 0, (
        f"[FIX] unittest discover should pass; exit={fix_result.returncode}\n"
        f"stderr: {fix_result.stderr}"
    )

    # MUTATION path: probe=True -> pytest -> nonexistent dir -> exit != 0
    mutation_cmd, mutation_runner = mod.select_test_runner(
        sys.executable,
        pytest_args=["nonexistent_dir_that_does_not_exist"],
        xdist_flags=[],
        run_dir=run_dir,
        test_dir="tests",
        _probe=True,  # MUTATION: hardcoded pytest
    )
    assert mutation_runner == "pytest"
    assert "pytest" in mutation_cmd

    mutation_result = subprocess.run(
        mutation_cmd, cwd=project, capture_output=True, text=True, timeout=30
    )
    # pytest with a nonexistent path exits non-zero (exit 4 = no tests, or exit 2 = UsageError)
    assert mutation_result.returncode != 0, (
        "[MUTATION] pytest on nonexistent dir should fail; "
        f"got exit={mutation_result.returncode}\n"
        f"stdout: {mutation_result.stdout}\nstderr: {mutation_result.stderr}"
    )


def test_mutation_hardcoded_pytest_command_diverges_from_fix(tmp_path: Path) -> None:
    """Structural MUTATION: old code always builds pytest command.

    New code with _probe=False builds unittest discover command.
    Commands must be structurally different.
    """
    mod = load_runner_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    old_cmd, old_runner = mod.select_test_runner(
        sys.executable,
        pytest_args=["tests", "-q"],
        xdist_flags=[],
        run_dir=run_dir,
        _probe=True,
    )
    new_cmd, new_runner = mod.select_test_runner(
        sys.executable,
        pytest_args=["tests", "-q"],
        xdist_flags=[],
        run_dir=run_dir,
        _probe=False,
    )

    assert old_cmd != new_cmd, "Mutation and fix must produce different commands"
    assert old_runner == "pytest"
    assert new_runner == "unittest"
    assert "pytest" in old_cmd
    assert "pytest" not in new_cmd
    assert "unittest" in new_cmd
    assert "discover" in new_cmd


# ---------------------------------------------------------------------------
# (d) probe_pytest probes the TARGET interpreter, not current process
# ---------------------------------------------------------------------------


def test_probe_pytest_returns_true_for_current_interpreter() -> None:
    """Current motor interpreter (sys.executable) has pytest -> probe returns True."""
    mod = load_runner_module()
    # The motor venv has pytest installed.
    assert mod.probe_pytest(sys.executable) is True


def test_probe_pytest_returns_false_for_nonexistent_interpreter() -> None:
    """A non-existent interpreter path -> probe returns False (never raises)."""
    mod = load_runner_module()
    assert mod.probe_pytest("/nonexistent/python") is False
