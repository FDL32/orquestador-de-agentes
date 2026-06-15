"""Tests para scripts/check_destino_publish_ready.py (WOT-2026-009f).

Barrera: cada test demuestra que el script distingue correctamente los cuatro
estados publicables con stubs de validate y STATE.md reales en tmp_path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_destino_publish_ready as cdr  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, status: str) -> Path:
    """Create a minimal destino structure with the given STATE.md STATUS."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "STATE.md").write_text(
        f"ACTIVE_TICKET: WOT-TEST\nSTATUS: {status}\n", encoding="utf-8"
    )
    return tmp_path


def _validate_response(errors: dict, warnings: dict | None = None) -> dict:
    return {"errors": errors, "warnings": warnings or {}}


def _stub_validate(rc: int, data: dict):
    """Return a patch for _run_validate that yields (rc, data)."""
    return patch.object(cdr, "_run_validate", return_value=(rc, data))


# ---------------------------------------------------------------------------
# Case 1: drift — errors > 0 -> exit 1
# ---------------------------------------------------------------------------


def test_drift_returns_exit_1(tmp_path):
    project = _make_project(tmp_path, "IN_PROGRESS")
    validate_data = _validate_response(
        errors={"consistency": ["DRIFT: plan=APPROVED pero log=COMPLETED"]}
    )
    with _stub_validate(1, validate_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 1


def test_drift_exit_1_regardless_of_status(tmp_path):
    """Even if STATUS=COMPLETED, errors > 0 must block."""
    project = _make_project(tmp_path, "COMPLETED")
    validate_data = _validate_response(
        errors={"invariants": ["INVARIANT: Missing BUILDER_EXIT"]}
    )
    with _stub_validate(1, validate_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 1


# ---------------------------------------------------------------------------
# Case 2: APPROVED pre-Builder — 0/0 but STATUS=APPROVED -> exit 2
# ---------------------------------------------------------------------------


def test_approved_pre_builder_returns_exit_2(tmp_path):
    project = _make_project(tmp_path, "APPROVED")
    validate_data = _validate_response(errors={})
    with _stub_validate(0, validate_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 2


# ---------------------------------------------------------------------------
# Case 3: READY_FOR_REVIEW — 0/0 -> exit 0
# ---------------------------------------------------------------------------


def test_ready_for_review_returns_exit_0(tmp_path):
    project = _make_project(tmp_path, "READY_FOR_REVIEW")
    validate_data = _validate_response(errors={})
    with _stub_validate(0, validate_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 0


# ---------------------------------------------------------------------------
# Case 4: COMPLETED — 0/0 -> exit 0
# ---------------------------------------------------------------------------


def test_completed_returns_exit_0(tmp_path):
    project = _make_project(tmp_path, "COMPLETED")
    validate_data = _validate_response(errors={})
    with _stub_validate(0, validate_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 0


# ---------------------------------------------------------------------------
# Case 5: configuration error (motor not found) -> exit 3
# ---------------------------------------------------------------------------


def test_missing_motor_root_returns_exit_3(tmp_path, capsys):
    project = _make_project(tmp_path, "COMPLETED")
    rc = cdr.main(["--project-root", str(project)])
    assert rc == 3
    captured = capsys.readouterr()
    assert "motor-root" in captured.err.lower() or "motor_root" in captured.err.lower()


def test_validate_config_error_returns_exit_3(tmp_path):
    project = _make_project(tmp_path, "IN_PROGRESS")
    error_data = {"error": "agent_controller.py not found"}
    with _stub_validate(3, error_data):
        rc = cdr.main(["--project-root", str(project), "--motor-root", str(tmp_path)])
    assert rc == 3


# ---------------------------------------------------------------------------
# Case 6: motor_destination_link.json resolution
# ---------------------------------------------------------------------------


def test_resolves_motor_from_link_json(tmp_path):
    """If --motor-root is omitted, resolve from motor_destination_link.json."""
    motor = tmp_path / "motor"
    motor.mkdir()
    project = _make_project(tmp_path / "destino", "COMPLETED")
    link_dir = project / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )
    validate_data = _validate_response(errors={})
    with _stub_validate(0, validate_data):
        rc = cdr.main(["--project-root", str(project)])
    assert rc == 0
