"""Tests for scripts/validate_batch_dag.py (WOT-2026-022r).

Each rejection test starts from a VALID baseline DAG and mutates it in
exactly ONE way (branch isolation, lesson 021u), except where the test's
whole point is proving a specific property (e.g. dependency-connected
groups MAY share surfaces).

The validator is invoked via subprocess with the venv interpreter;
assertions read `returncode` directly (never `$?` after a pipe).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "validate_batch_dag.py"
PYTHON = Path(sys.executable)


def _valid_dag() -> dict[str, Any]:
    """A fully valid baseline DAG: acyclic, every group gated, schema-clean."""
    return {
        "schema": "autonomous-batch-dag/v1",
        "generated_at": "2026-07-12T00:00:00Z",
        "state_at_triage": {"motor": "abc123", "workspace": "def456", "dirty": 0},
        "groups": [
            {
                "id": "G-LOCKS",
                "tickets": ["WOT-2026-022i"],
                "depends_on_groups": [],
                "blocks_groups": ["G-XDIST"],
                "shared_surfaces": ["scripts/run_pytest_safe.py"],
                "class": "S",
                "autonomy_mode": "hard-stop-with-recovery",
                "common_gate": "pytest tests/unit/test_locks.py",
                "recovery_owner_stage": "BUILDER",
                "max_recovery_attempts": 2,
            },
            {
                "id": "G-XDIST",
                "tickets": ["WOT-2026-021k"],
                "depends_on_groups": ["G-LOCKS"],
                "blocks_groups": [],
                "shared_surfaces": ["scripts/run_pytest_safe.py"],
                "class": "M",
                "autonomy_mode": "autonomous",
                "common_gate": "pytest tests/unit/test_xdist.py",
                "recovery_owner_stage": "BUILDER",
                "max_recovery_attempts": 2,
            },
            {
                "id": "G-DOCS",
                "tickets": ["WOT-2026-019z"],
                "depends_on_groups": [],
                "blocks_groups": [],
                "shared_surfaces": ["docs/README.md"],
                "class": "S",
                "autonomy_mode": "autonomous",
                "common_gate": "pytest tests/unit/test_docs.py",
                "recovery_owner_stage": "BUILDER",
                "max_recovery_attempts": 1,
            },
        ],
        "stop_policy": {
            "hard_stop_causes": ["gate_fail"],
            "recoverable_causes": ["flaky_timeout"],
            "max_unclassified_stops": 1,
        },
        "budget": {"max_tickets_closed": 5, "max_group_recoveries": 3},
    }


def _write_dag(tmp_path: Path, dag: dict[str, Any], name: str = "dag.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(dag, indent=2), encoding="utf-8")
    return path


def _run(dag_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), str(SCRIPT_PATH), str(dag_path)],
        capture_output=True,
        text=True,
    )


def test_valid_dag_passes(tmp_path: Path) -> None:
    dag_path = _write_dag(tmp_path, _valid_dag())
    result = _run(dag_path)
    assert result.returncode == 0, result.stderr


def test_cycle_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    # Make G-LOCKS depend on G-XDIST too -> G-LOCKS -> G-XDIST -> G-LOCKS cycle.
    dag["groups"][0]["depends_on_groups"] = ["G-XDIST"]
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "ciclo" in result.stderr.lower()


def test_missing_common_gate_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    dag["groups"][2]["common_gate"] = ""
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "common_gate" in result.stderr


def test_surface_overlap_between_independent_groups_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    # G-XDIST and G-DOCS are independent (no dependency path between them).
    # Make them share a surface: this must be the ONLY defect.
    dag["groups"][1]["shared_surfaces"] = ["scripts/run_pytest_safe.py", "shared/x.py"]
    dag["groups"][2]["shared_surfaces"] = ["shared/x.py"]
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "solapamiento" in result.stderr.lower()


def test_surface_overlap_between_dependency_connected_groups_allowed(
    tmp_path: Path,
) -> None:
    # G-LOCKS -> G-XDIST already share "scripts/run_pytest_safe.py" in the
    # baseline and are directly dependency-connected: this must pass.
    dag = _valid_dag()
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 0, result.stderr


def test_surface_shared_across_transitive_dependency_path_allowed(
    tmp_path: Path,
) -> None:
    dag = _valid_dag()
    # Build G1 -> G2 -> G3 transitive chain sharing a surface between G1 and G3.
    dag["groups"] = [
        {
            "id": "G1",
            "tickets": ["WOT-2026-030a"],
            "depends_on_groups": [],
            "blocks_groups": ["G2"],
            "shared_surfaces": ["shared/common.py"],
            "class": "S",
            "autonomy_mode": "autonomous",
            "common_gate": "pytest g1",
            "recovery_owner_stage": "BUILDER",
            "max_recovery_attempts": 1,
        },
        {
            "id": "G2",
            "tickets": ["WOT-2026-030b"],
            "depends_on_groups": ["G1"],
            "blocks_groups": ["G3"],
            "shared_surfaces": [],
            "class": "S",
            "autonomy_mode": "autonomous",
            "common_gate": "pytest g2",
            "recovery_owner_stage": "BUILDER",
            "max_recovery_attempts": 1,
        },
        {
            "id": "G3",
            "tickets": ["WOT-2026-030c"],
            "depends_on_groups": ["G2"],
            "blocks_groups": [],
            "shared_surfaces": ["shared/common.py"],
            "class": "S",
            "autonomy_mode": "autonomous",
            "common_gate": "pytest g3",
            "recovery_owner_stage": "BUILDER",
            "max_recovery_attempts": 1,
        },
    ]
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 0, result.stderr


def test_ticket_in_two_groups_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    dag["groups"][2]["tickets"] = ["WOT-2026-022i"]  # already in G-LOCKS
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "dos grupos" in result.stderr


def test_bad_class_value_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    dag["groups"][0]["class"] = "XL"
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "class" in result.stderr


def test_unknown_group_id_in_depends_on_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    dag["groups"][1]["depends_on_groups"] = ["G-GHOST"]
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "desconocido" in result.stderr.lower()


def test_blocks_groups_inconsistent_with_depends_on_rejected(tmp_path: Path) -> None:
    dag = _valid_dag()
    # G-LOCKS blocks G-XDIST, but remove the reciprocal depends_on_groups.
    dag["groups"][1]["depends_on_groups"] = []
    dag_path = _write_dag(tmp_path, dag)
    result = _run(dag_path)
    assert result.returncode == 1
    assert "inconsistencia" in result.stderr.lower()


def test_baseline_is_untouched_by_copy(tmp_path: Path) -> None:
    """Sanity check: deepcopy isolation used by other tests works as expected."""
    original = _valid_dag()
    mutated = copy.deepcopy(original)
    mutated["groups"][0]["class"] = "L"
    assert original["groups"][0]["class"] == "S"


# --------------------------------------------------------------------------- #
# WOT-2026-022w -- the surface scan compared RAW strings, so two INDEPENDENT
# groups could name the SAME file and pass. On Windows all the pairs below are
# one file: the groups would run in parallel and race on writes, which is the
# exact hazard this scan exists to prevent.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("surface_a", "surface_b", "vector"),
    [
        ("Scripts/A.py", "scripts/a.py", "case"),
        ("scripts/a.py", "scripts\\a.py", "separator"),
        ("./scripts/a.py", "scripts/a.py", "redundant ./ prefix"),
        ("Scripts\\A.py", "./scripts/a.py", "all three at once"),
    ],
)
def test_022w_same_file_different_spelling_is_rejected(
    tmp_path: Path, surface_a: str, surface_b: str, vector: str
) -> None:
    """LOAD-BEARING: the same file spelled differently must still collide.

    The groups are INDEPENDENT and the DAG is otherwise fully valid, so the
    overlap is the ONLY defect (branch isolation): nothing else can be what makes
    this fail.

    Mutation: remove the normalization in _normalize_surface -> RED.
    """
    dag = _valid_dag()
    dag["groups"][1]["shared_surfaces"] = [surface_a]
    dag["groups"][2]["shared_surfaces"] = [surface_b]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1, (
        f"{vector}: {surface_a!r} and {surface_b!r} are the SAME file, so two "
        f"independent groups touching them must be rejected; the scan accepted them"
    )
    assert "solapamiento" in result.stderr.lower()


@pytest.mark.parametrize(
    ("surface_a", "surface_b"),
    [
        ("scripts/a.py", "scripts/b.py"),  # different file, same dir
        ("scripts/a.py", "tests/a.py"),  # same name, different dir
    ],
)
def test_022w_genuinely_different_files_still_allowed(
    tmp_path: Path, surface_a: str, surface_b: str
) -> None:
    """The normalization must NOT over-match: distinct files stay independent.

    Without this, "normalize everything" could collapse unrelated paths and
    serialize groups that had no reason to be serialized -- the fix would trade a
    false negative for a false positive.
    """
    dag = _valid_dag()
    dag["groups"][1]["shared_surfaces"] = [surface_a]
    dag["groups"][2]["shared_surfaces"] = [surface_b]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, (
        f"{surface_a!r} and {surface_b!r} are DIFFERENT files: the groups are "
        f"genuinely independent and must not be flagged. stderr: {result.stderr}"
    )


def test_022w_error_message_shows_the_paths_the_user_wrote(tmp_path: Path) -> None:
    """The error must name the ORIGINAL spelling, not the canonical form.

    A user who wrote 'Scripts/A.py' must see 'Scripts/A.py' in the message; showing
    only the normalized 'scripts/a.py' would point at a path they never typed.
    """
    dag = _valid_dag()
    dag["groups"][1]["shared_surfaces"] = ["Scripts/A.py"]
    dag["groups"][2]["shared_surfaces"] = ["scripts/a.py"]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "Scripts/A.py" in result.stderr, (
        "the message must show the path as the user wrote it"
    )
