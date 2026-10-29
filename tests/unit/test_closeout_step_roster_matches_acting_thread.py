#!/usr/bin/env python3
"""WOT-2026-136c: cableado test for step_roster_matches_acting_thread in gates.py.

This test verifies that the exit code mapping in step_roster_matches_acting_thread
is correct, and that dry_run=True skips the subprocess call entirely.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


# Check if the step function exists yet (Phase 3+ only)
try:
    from scripts.closeout_steps.gates import step_roster_matches_acting_thread
    from scripts.session_closeout import StepResult
except ImportError:
    pytest.skip(
        "step_roster_matches_acting_thread not yet implemented",
        allow_module_level=True,
    )


class _MockResult:
    """Minimal mock of a subprocess.CompletedProcess."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create minimal project structure."""
    return tmp_path


def test_exit_code_0_is_pass(tmp_path: Path) -> None:
    """Test: returncode=0 -> StepResult(status='PASS', blocking=True)."""

    def mock_run(name, args, cwd, timeout=None):
        return _MockResult(0, "[roster-check] OK")

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: r.stdout or "",
        step_result_cls=StepResult,
    )
    assert result.status == "PASS"
    assert result.blocking is True


def test_exit_code_1_is_fail(tmp_path: Path) -> None:
    """Test: returncode=1 -> StepResult(status='FAIL', blocking=True)."""

    def mock_run(name, args, cwd, timeout=None):
        return _MockResult(1, "(c) Violacion: doble ACTIVA")

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: r.stdout or "",
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True


def test_exit_code_3_is_skip(tmp_path: Path) -> None:
    """Test: returncode=3 -> StepResult(status='SKIP', blocking=False)."""

    def mock_run(name, args, cwd, timeout=None):
        return _MockResult(3, "[roster-check] N/A: no roster found")

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: r.stdout or "",
        step_result_cls=StepResult,
    )
    assert result.status == "SKIP"
    assert result.blocking is False


def test_exit_code_1_with_na_in_stdout_is_still_fail(tmp_path: Path) -> None:
    """Test: returncode=1 but stdout contains 'N/A' -> still FAIL (not reclasified by text).

    This is the adversarial case from BA07 [MINOR] 9: a PASS real whose note mentions
    'N/A' by another reason should still be PASS when rc=0; but here rc=1 so it's FAIL
    regardless of text content.
    """

    def mock_run(name, args, cwd, timeout=None):
        return _MockResult(1, "[roster-check] VIOLATION: (d) nota_gap N/A")

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: r.stdout or "",
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True


def test_exit_code_7_is_fail(tmp_path: Path) -> None:
    """Test: returncode=7 (unknown) -> StepResult(status='FAIL', blocking=True)."""

    def mock_run(name, args, cwd, timeout=None):
        return _MockResult(7, "unexpected error")

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: r.stdout or "",
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True


def test_timeout_expired_is_fail(tmp_path: Path) -> None:
    """Test: TimeoutExpired -> StepResult(status='FAIL', blocking=True)."""

    def mock_run(name, args, cwd, timeout=None):
        raise subprocess.TimeoutExpired(args, 60)

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: "",
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True


def test_file_not_found_is_fail(tmp_path: Path) -> None:
    """Test: FileNotFoundError -> StepResult(status='FAIL', blocking=True)."""

    def mock_run(name, args, cwd, timeout=None):
        raise FileNotFoundError(str(args[0]))

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=False,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: "",
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True


def test_dry_run_skips_subprocess(tmp_path: Path) -> None:
    """Test: dry_run=True -> SKIP without calling run_script_fn."""
    called = {"flag": False}

    def mock_run(name, args, cwd, timeout=None):
        called["flag"] = True
        return _MockResult(0)

    result = step_roster_matches_acting_thread(
        project_root=tmp_path,
        dry_run=True,
        acting_thread="mcp:test",
        roster_path=str(tmp_path / "roster.json"),
        registry_path=str(tmp_path / "registry.json"),
        changes_log=str(tmp_path / "changes.jsonl"),
        run_script_fn=mock_run,
        process_diagnostic_fn=lambda r: "",
        step_result_cls=StepResult,
    )
    assert called["flag"] is False, "dry_run=True must NOT call run_script_fn"
    assert result.status == "SKIP"
    assert result.blocking is False


def test_run_closeout_calls_roster_step_and_blocks_on_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1: run_closeout must call _step_roster_matches_acting_thread and block on FAIL.

    Mutation proof (self-verified): retiring the call-site inside run_closeout
    makes this test FAIL because the fake is never invoked.
    """
    wp_dir = tmp_path / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True, exist_ok=True)
    (wp_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WOT-2026-0001\n",
        encoding="utf-8",
    )

    roster_call: dict = {"invoked": False, "kwargs": None}

    def _fake_roster(
        project_root,
        dry_run,
        acting_thread="",
        roster_path=None,
        registry_path=None,
        changes_log=None,
    ):
        roster_call["invoked"] = True
        roster_call["kwargs"] = {
            "project_root": project_root,
            "acting_thread": acting_thread,
            "roster_path": roster_path,
            "registry_path": registry_path,
            "changes_log": changes_log,
        }
        return StepResult(
            name="roster_matches_acting_thread",
            status="FAIL",
            detail="faked",
            blocking=True,
        )

    def _fake_prepush(project_root, dry_run, skip_gates=False):
        return StepResult(
            name="prepush_check", status="PASS", detail="faked", blocking=True
        )

    monkeypatch.setattr(
        "scripts.session_closeout._step_roster_matches_acting_thread",
        _fake_roster,
    )
    monkeypatch.setattr(
        "scripts.session_closeout._step_prepush_check",
        _fake_prepush,
    )

    import scripts.session_closeout as session_closeout

    exit_code = session_closeout.run_closeout(
        tmp_path,
        dry_run=False,
        acting_thread="mcp:test-thread",
        roster_path="/fake/roster.json",
        registry_path="/fake/registry.json",
        changes_log="/fake/changes.jsonl",
    )

    assert roster_call["invoked"] is True, (
        "run_closeout must call _step_roster_matches_acting_thread; it did not "
        "(this is the exact defect measured by the reviewer: retiring the "
        "call-site leaves prior tests green because they call the step directly, "
        "never through run_closeout)"
    )
    assert roster_call["kwargs"]["acting_thread"] == "mcp:test-thread"
    assert roster_call["kwargs"]["roster_path"] == "/fake/roster.json"
    assert roster_call["kwargs"]["registry_path"] == "/fake/registry.json"
    assert roster_call["kwargs"]["changes_log"] == "/fake/changes.jsonl"
    assert exit_code == 1  # early-exit from the faked roster FAIL


def test_run_closeout_roster_step_pass_appears_in_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1: when roster step PASSES, the report must continue and include the StepResult.

    The report.steps list must contain the roster StepResult when it passes.
    """
    wp_dir = tmp_path / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True, exist_ok=True)
    (wp_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WOT-2026-0001\n",
        encoding="utf-8",
    )

    roster_call: dict = {"invoked": False}

    def _fake_roster(
        project_root,
        dry_run,
        acting_thread="",
        roster_path=None,
        registry_path=None,
        changes_log=None,
    ):
        roster_call["invoked"] = True
        return StepResult(
            name="roster_matches_acting_thread",
            status="PASS",
            detail="faked OK",
            blocking=True,
        )

    def _fake_prepush(project_root, dry_run, skip_gates=False):
        return StepResult(
            name="prepush_check", status="PASS", detail="faked", blocking=True
        )

    monkeypatch.setattr(
        "scripts.session_closeout._step_roster_matches_acting_thread",
        _fake_roster,
    )
    monkeypatch.setattr(
        "scripts.session_closeout._step_prepush_check",
        _fake_prepush,
    )

    import scripts.session_closeout as session_closeout

    exit_code = session_closeout.run_closeout(
        tmp_path,
        dry_run=False,
        acting_thread="mcp:test-thread",
        roster_path="/fake/roster.json",
        registry_path="/fake/registry.json",
        changes_log="/fake/changes.jsonl",
    )

    assert roster_call["invoked"] is True
    # exit code 0: roster PASS does not block; closeout continues
    assert exit_code == 0


# --- Phase 2.4: Docstring tests ---


def test_docstring_does_not_contain_old_dormant_phrase() -> None:
    """Test 2.4 (b): docstring must NOT contain the old false phrase about guard
    being dormant until FLIGHT_ROSTER_PATH is exported and --acting-thread is passed.
    """
    doc = step_roster_matches_acting_thread.__doc__
    assert doc is not None
    assert (
        "the guard is dormant until FLIGHT_ROSTER_PATH is exported and --acting-thread is passed together"
        not in doc
    ), "Docstring must not contain the old false phrase about guard dormancy"


def test_docstring_mentions_acting_thread_with_fail() -> None:
    """Test 2.4 (c): docstring must mention --acting-thread together with FAIL
    (two separate 'in' assertions, no regex).
    """
    doc = step_roster_matches_acting_thread.__doc__
    assert doc is not None
    assert "--acting-thread" in doc, "Docstring must mention --acting-thread"
    assert "FAIL" in doc, "Docstring must mention FAIL"
