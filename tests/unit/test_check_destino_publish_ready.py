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
    """If --motor-root is omitted, resolve from motor_destination_link.json.

    WOT-2026-014j: hardened from false-green. Previous version used str(tmp_path/motor)
    which is already canonical on Windows/NTFS. We now write a non-canonical path
    (tmp_path/motor/sub/..) to the link JSON and assert the precondition that the
    raw path is not canonical, confirming that .resolve() must be called to collapse it.

    NOTE: This test's rc==0 assertion is not directly mutation-effective for the .resolve()
    call because _stub_validate intercepts _run_validate before motor_root is used further.
    The precondition assert documents the non-canonical input. Mutation-effective coverage
    for this resolve() call is provided by test_motor_link.py and test_run_gates_dispatch.py
    (both verified to FAIL when .resolve() is removed from runtime/motor_link.py:43).
    """
    # Create motor/sub so the dotdot path is traversable
    sub = tmp_path / "motor" / "sub"
    sub.mkdir(parents=True)

    # Build a non-canonical path: tmp_path/motor/sub/.. (dotdot not collapsed)
    raw_motor = str(tmp_path / "motor" / "sub" / "..")

    # Pre-condition: the stored path must be non-canonical (documents test intent)
    assert Path(raw_motor) != Path(raw_motor).resolve(), (
        "WOT-2026-014j precondition: raw motor path must NOT be canonical "
        "(dotdot segment must differ from resolved form)"
    )

    project = _make_project(tmp_path / "destino", "COMPLETED")
    link_dir = project / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": raw_motor}), encoding="utf-8"
    )
    validate_data = _validate_response(errors={})
    with _stub_validate(0, validate_data):
        rc = cdr.main(["--project-root", str(project)])
    assert rc == 0


# WOT-2026-014e: mutation barriers — _resolve_motor_root canonical helper


def test_resolve_motor_root_arg_branch_returns_resolved_path(tmp_path):
    """Barrier: the --motor-root arg branch must return a .resolve()-normalised path.

    Feeds a path with a redundant "sub/.." component so that
    Path(arg) != Path(arg).resolve() even on Windows (tmp_path/sub/.. keeps the
    dotdot literally until resolve() collapses it).  The assertion
    result != raw_path is therefore guaranteed to fail if the production
    code returns the unresolved p instead of p.resolve().

    Mutation-verified: revert production to return p if p.exists() else None
    and this test FAILS with:
        AssertionError: assert WindowsPath("...motor_sub/..")
                              != WindowsPath("...motor_sub/..")
    """
    # Create the subdirectory so the path with dotdot is traversable
    sub = tmp_path / "motor_sub"
    sub.mkdir()
    # Build a non-canonical arg: tmp_path/motor_sub/..
    raw_arg = str(tmp_path / "motor_sub" / "..")
    raw_path = Path(raw_arg)

    # Pre-condition: raw_path exists but is NOT yet normalised
    assert raw_path.exists(), "path must exist for the arg branch to return non-None"
    assert raw_path != raw_path.resolve(), (
        "test pre-condition: raw path must differ from resolved (dotdot not collapsed)"
    )

    result = cdr._resolve_motor_root(tmp_path, raw_arg)

    assert result is not None
    # Must be the resolved (collapsed) path
    assert result == raw_path.resolve()
    # Must NOT be the raw (non-canonical) path
    assert result != raw_path, (
        "arg branch must call .resolve(): returned the raw non-canonical path"
    )


def test_resolve_motor_root_link_branch_delegates_to_canonical_helper(tmp_path):
    """Barrier: the link branch must delegate to runtime.motor_link.resolve_motor_root.

    Mutation: if the function reopened motor_destination_link.json locally (old code),
    patching runtime.motor_link.resolve_motor_root would have no effect and the
    assertion on mock_resolve.called would FAIL.
    """
    from unittest.mock import patch as _patch

    sentinel = tmp_path / "sentinel_motor"
    sentinel.mkdir()

    with _patch(
        "runtime.motor_link.resolve_motor_root", return_value=sentinel.resolve()
    ) as mock_resolve:
        result = cdr._resolve_motor_root(tmp_path, None)

    mock_resolve.assert_called_once_with(tmp_path)
    assert result == sentinel.resolve()


def test_resolve_motor_root_arg_branch_none_when_missing(tmp_path):
    """Arg branch returns None when the supplied path does not exist."""
    result = cdr._resolve_motor_root(tmp_path, str(tmp_path / "nonexistent_motor"))
    assert result is None
