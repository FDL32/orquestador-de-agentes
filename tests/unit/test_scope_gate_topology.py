"""Tests for topology-aware FLT namespace parsing (WOT-2026-009b).

Verifica que parse_flt_namespaced distingue ### repo_motor / ### repo_destino,
que parse_raw_flt_paths en motor_checkpoint excluye rutas de ### repo_destino,
y que la backward-compatibility de FLT plano se mantiene.
"""

from __future__ import annotations

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import motor_checkpoint  # noqa: E402
import scope_gate  # noqa: E402


_MOTOR = Path("/fake/motor")
_DESTINO = Path("/fake/destino")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NAMESPACED_MOTOR_ONLY = (
    "# Work Plan\n\n"
    "## Files Likely Touched\n\n"
    "### repo_motor\n"
    "- `.agent/scope_gate.py`\n"
    "- `.agent/agent_controller.py`\n\n"
    "## Criterios\n"
)

_NAMESPACED_BOTH = (
    "# Work Plan\n\n"
    "## Files Likely Touched\n\n"
    "### repo_motor\n"
    "- `.agent/scope_gate.py`\n\n"
    "### repo_destino\n"
    "- `.agent/docs/foo.md`\n\n"
    "## Otro\n"
)

_NAMESPACED_DESTINO_ONLY = (
    "# Work Plan\n\n"
    "## Files Likely Touched\n\n"
    "### repo_destino\n"
    "- `.agent/docs/bar.md`\n\n"
    "## Otro\n"
)

_FLAT_MOTOR_AUTH = (
    "# Work Plan\n\n"
    "- **delivery_authority:** repo_motor\n\n"
    "## Files Likely Touched\n\n"
    "- `.agent/scope_gate.py`\n"
    "- `scripts/foo.py`\n\n"
    "## Criterios\n"
)

_FLAT_DESTINO_AUTH = (
    "# Work Plan\n\n"
    "- **delivery_authority:** repo_destino\n\n"
    "## Files Likely Touched\n\n"
    "- `.agent/docs/foo.md`\n\n"
    "## Otro\n"
)

_NO_FLT = "# Work Plan\n\n## Objetivo\n\nHacer algo.\n"

_NAMESPACED_UNKNOWN_NS = (
    "# Work Plan\n\n"
    "## Files Likely Touched\n\n"
    "### repo_motor\n"
    "- `.agent/scope_gate.py`\n\n"
    "### otros\n"
    "- `should_be_ignored.py`\n\n"
    "## Otro\n"
)


# ---------------------------------------------------------------------------
# parse_flt_namespaced tests
# ---------------------------------------------------------------------------


def test_namespaced_motor_only_paths_in_motor_bucket():
    result = scope_gate.parse_flt_namespaced(
        _NAMESPACED_MOTOR_ONLY,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert str((_MOTOR / ".agent/scope_gate.py").resolve()) in result["motor"]
    assert str((_MOTOR / ".agent/agent_controller.py").resolve()) in result["motor"]
    assert result["destino"] == set()


def test_namespaced_both_buckets_separated():
    result = scope_gate.parse_flt_namespaced(
        _NAMESPACED_BOTH,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert str((_MOTOR / ".agent/scope_gate.py").resolve()) in result["motor"]
    assert str((_DESTINO / ".agent/docs/foo.md").resolve()) in result["destino"]
    # Motor path NOT in destino bucket and vice versa
    assert str((_DESTINO / ".agent/scope_gate.py").resolve()) not in result["destino"]
    assert str((_MOTOR / ".agent/docs/foo.md").resolve()) not in result["motor"]


def test_namespaced_destino_only_motor_bucket_empty():
    result = scope_gate.parse_flt_namespaced(
        _NAMESPACED_DESTINO_ONLY,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert result["motor"] == set()
    assert str((_DESTINO / ".agent/docs/bar.md").resolve()) in result["destino"]


def test_flat_flt_motor_authority_goes_to_motor_bucket():
    result = scope_gate.parse_flt_namespaced(
        _FLAT_MOTOR_AUTH,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert str((_MOTOR / ".agent/scope_gate.py").resolve()) in result["motor"]
    assert str((_MOTOR / "scripts/foo.py").resolve()) in result["motor"]
    assert result["destino"] == set()


def test_flat_flt_destino_authority_goes_to_destino_bucket():
    result = scope_gate.parse_flt_namespaced(
        _FLAT_DESTINO_AUTH,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_destino",
    )
    assert str((_DESTINO / ".agent/docs/foo.md").resolve()) in result["destino"]
    assert result["motor"] == set()


def test_no_flt_section_returns_empty_buckets():
    result = scope_gate.parse_flt_namespaced(
        _NO_FLT,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert result["motor"] == set()
    assert result["destino"] == set()


def test_unknown_namespace_lines_ignored():
    result = scope_gate.parse_flt_namespaced(
        _NAMESPACED_UNKNOWN_NS,
        motor_root=_MOTOR,
        project_root=_DESTINO,
        delivery_authority="repo_motor",
    )
    assert str((_MOTOR / ".agent/scope_gate.py").resolve()) in result["motor"]
    # Lines under ### otros must NOT appear in either bucket
    assert not any("should_be_ignored" in p for p in result["motor"])
    assert not any("should_be_ignored" in p for p in result["destino"])


# ---------------------------------------------------------------------------
# parse_flt_raw_paths / parse_flt_raw_buckets tests
# ---------------------------------------------------------------------------


def test_raw_buckets_keep_namespaces_separate():
    result = scope_gate.parse_flt_raw_buckets(
        _NAMESPACED_BOTH, delivery_authority="repo_motor"
    )
    assert result["motor"] == {".agent/scope_gate.py"}
    assert result["destino"] == {".agent/docs/foo.md"}


def test_raw_paths_authority_target_uses_delivery_authority():
    result = scope_gate.parse_flt_raw_paths(
        _FLAT_DESTINO_AUTH,
        delivery_authority="repo_destino",
        target="authority",
    )
    assert result == {".agent/docs/foo.md"}


def test_raw_paths_all_target_returns_union():
    result = scope_gate.parse_flt_raw_paths(
        _NAMESPACED_BOTH,
        delivery_authority="repo_motor",
        target="all",
    )
    assert result == {".agent/scope_gate.py", ".agent/docs/foo.md"}


# ---------------------------------------------------------------------------
# parse_raw_flt_paths (motor_checkpoint) namespace-aware tests
# ---------------------------------------------------------------------------


def test_raw_flt_motor_only_namespace():
    paths = motor_checkpoint.parse_raw_flt_paths(_NAMESPACED_MOTOR_ONLY)
    assert ".agent/scope_gate.py" in paths
    assert ".agent/agent_controller.py" in paths


def test_raw_flt_excludes_destino_namespace():
    paths = motor_checkpoint.parse_raw_flt_paths(_NAMESPACED_BOTH)
    assert ".agent/scope_gate.py" in paths
    # Destino path must NOT appear in raw motor paths
    assert ".agent/docs/foo.md" not in paths


def test_raw_flt_destino_only_returns_empty():
    paths = motor_checkpoint.parse_raw_flt_paths(_NAMESPACED_DESTINO_ONLY)
    assert paths == set()


def test_raw_flt_flat_backward_compat():
    paths = motor_checkpoint.parse_raw_flt_paths(_FLAT_MOTOR_AUTH)
    assert ".agent/scope_gate.py" in paths
    assert "scripts/foo.py" in paths


def test_raw_flt_no_section_returns_empty():
    paths = motor_checkpoint.parse_raw_flt_paths(_NO_FLT)
    assert paths == set()
