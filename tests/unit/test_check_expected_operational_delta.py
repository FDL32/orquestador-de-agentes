"""Tests for scripts/check_expected_operational_delta.py (WOT-2026-040a).

The guard is the CONTENT validator of PREDICATE v2 condition 8
(`estado_operativo_destino_atribuible`): the `repo_destino`'s dirty tree must be
EXACTLY the expected operational transition of its deployment mode.

Fixtures of BOTH modes are provided, and the negative control is exercised in
BOTH modes (a third foreign file must fail in code-only AND in destino). The five
named failures of the DoD are pinned: third foreign file, extra mutation, ticket
removed != archived, `commit:<sha>` missing/unlanded, and the code-only exception
applied outside code-only.

Mutation-to-prove (DoD MUTATION): the SAME code-only fixture with a third file ->
RED (rc 1); without it -> GREEN (rc 0). Both rc are read from a real subprocess.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _MOTOR_ROOT / "scripts" / "check_expected_operational_delta.py"


def _load(name: str):
    path = _MOTOR_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


delta_guard = _load("check_expected_operational_delta")


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def _code_only_delta(**overrides):
    base = {
        "schema": "expected-operational-delta/v1",
        "mode": "code-only",
        "changed_paths": [
            ".agent/collaboration/backlog.md",
            ".agent/collaboration/_archive/backlog_done.md",
        ],
        "live_queue_removed": [{"ticket": "WOT-2026-040a"}],
        "archive_added": [
            {
                "ticket": "WOT-2026-040a",
                "state": "completed",
                "reactivation": "commit:abc1234",
                "landed": True,
            }
        ],
        "extra_hunks": 0,
    }
    base.update(overrides)
    return base


def _destino_delta(**overrides):
    base = {
        "schema": "expected-operational-delta/v1",
        "mode": "destino",
        "changed_paths": [
            ".agent/collaboration/STATE.md",
            ".agent/collaboration/TURN.md",
            ".agent/collaboration/work_plan.md",
            ".agent/collaboration/execution_log.md",
            "orchestrator_pipeline/reports/audit_autonomous_batch_20261012-0000.md",
            "orchestrator_pipeline/reports/audit_autonomous_batch_20261012-0000.json",
        ],
        "extra_hunks": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# PASS: the expected transition, in BOTH modes
# ---------------------------------------------------------------------------


def test_code_only_expected_transition_passes() -> None:
    findings = delta_guard.validate_delta("code-only", _code_only_delta())
    assert findings == [], f"unexpected findings: {findings}"


def test_destino_expected_transition_passes() -> None:
    findings = delta_guard.validate_delta("destino", _destino_delta())
    assert findings == [], f"unexpected findings: {findings}"


# ---------------------------------------------------------------------------
# FAIL: third foreign file -- negative control in BOTH modes
# ---------------------------------------------------------------------------


def test_code_only_third_foreign_file_fails() -> None:
    delta = _code_only_delta(
        changed_paths=[
            ".agent/collaboration/backlog.md",
            ".agent/collaboration/_archive/backlog_done.md",
            "src/leaked_secret.py",
        ]
    )
    findings = delta_guard.validate_delta("code-only", delta)
    assert "foreign_file" in _codes(findings), findings


def test_destino_third_foreign_file_fails() -> None:
    delta = _destino_delta(
        changed_paths=[
            *_destino_delta()["changed_paths"],
            "src/leaked_secret.py",
        ]
    )
    findings = delta_guard.validate_delta("destino", delta)
    assert "foreign_file" in _codes(findings), findings


# ---------------------------------------------------------------------------
# FAIL: extra mutation (a permitted file with an extra hunk)
# ---------------------------------------------------------------------------


def test_extra_mutation_fails_in_code_only() -> None:
    findings = delta_guard.validate_delta("code-only", _code_only_delta(extra_hunks=1))
    assert "extra_mutation" in _codes(findings), findings


def test_extra_mutation_fails_in_destino() -> None:
    findings = delta_guard.validate_delta("destino", _destino_delta(extra_hunks=2))
    assert "extra_mutation" in _codes(findings), findings


# ---------------------------------------------------------------------------
# FAIL: ticket removed != archived
# ---------------------------------------------------------------------------


def test_ticket_removed_not_archived_fails() -> None:
    delta = _code_only_delta(
        archive_added=[
            {
                "ticket": "WOT-2026-999z",
                "state": "completed",
                "reactivation": "commit:abc1234",
                "landed": True,
            }
        ]
    )
    findings = delta_guard.validate_delta("code-only", delta)
    assert "ticket_mismatch" in _codes(findings), findings


# ---------------------------------------------------------------------------
# FAIL: missing commit cell / not landed / non-terminal state
# ---------------------------------------------------------------------------


def test_missing_commit_cell_fails() -> None:
    delta = _code_only_delta(
        archive_added=[
            {
                "ticket": "WOT-2026-040a",
                "state": "completed",
                "reactivation": "-",
                "landed": True,
            }
        ]
    )
    findings = delta_guard.validate_delta("code-only", delta)
    assert "missing_commit" in _codes(findings), findings


def test_unlanded_commit_fails() -> None:
    delta = _code_only_delta(
        archive_added=[
            {
                "ticket": "WOT-2026-040a",
                "state": "completed",
                "reactivation": "commit:abc1234",
                "landed": False,
            }
        ]
    )
    findings = delta_guard.validate_delta("code-only", delta)
    assert "not_landed" in _codes(findings), findings


def test_non_terminal_state_fails() -> None:
    delta = _code_only_delta(
        archive_added=[
            {
                "ticket": "WOT-2026-040a",
                "state": "pending",
                "reactivation": "commit:abc1234",
                "landed": True,
            }
        ]
    )
    findings = delta_guard.validate_delta("code-only", delta)
    assert "non_terminal_state" in _codes(findings), findings


# ---------------------------------------------------------------------------
# FAIL: the code-only exception applied OUTSIDE code-only
# ---------------------------------------------------------------------------


def test_code_only_delta_outside_code_only_fails() -> None:
    findings = delta_guard.validate_delta("destino", _code_only_delta())
    assert "outside_mode" in _codes(findings), findings


def test_mode_mismatch_fails() -> None:
    findings = delta_guard.validate_delta("destino", _code_only_delta())
    assert "mode_mismatch" in _codes(findings), findings


# ---------------------------------------------------------------------------
# CLI: real exit codes, and the MUTATION pair (third file -> RED, none -> GREEN)
# ---------------------------------------------------------------------------


def _run_cli(delta: dict, mode: str, tmp_path: Path) -> int:
    delta_path = tmp_path / "delta.json"
    delta_path.write_text(json.dumps(delta), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_GUARD),
            "--mode",
            mode,
            "--delta",
            str(delta_path),
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode


def test_cli_returns_ok_for_expected_transition(tmp_path: Path) -> None:
    assert _run_cli(_code_only_delta(), "code-only", tmp_path) == 0
    assert _run_cli(_destino_delta(), "destino", tmp_path) == 0


def test_mutation_pair_third_file_red_then_green(tmp_path: Path) -> None:
    """DoD MUTATION: the SAME fixture, with and without a third foreign file."""
    with_third = _code_only_delta(
        changed_paths=[
            ".agent/collaboration/backlog.md",
            ".agent/collaboration/_archive/backlog_done.md",
            "src/leaked_secret.py",
        ]
    )
    assert _run_cli(with_third, "code-only", tmp_path) == 1, "mutation must go RED"
    assert _run_cli(_code_only_delta(), "code-only", tmp_path) == 0, "must go GREEN"


def test_cli_usage_error_on_unreadable_delta(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(_GUARD),
            "--mode",
            "code-only",
            "--delta",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_cli_json_verdict_shape(tmp_path: Path) -> None:
    delta_path = tmp_path / "delta.json"
    delta_path.write_text(json.dumps(_destino_delta()), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_GUARD),
            "--mode",
            "destino",
            "--delta",
            str(delta_path),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["findings"] == []
    assert payload["mode"] == "destino"
