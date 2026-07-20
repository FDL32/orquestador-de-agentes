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


# ---------------------------------------------------------------------------
# WOT-2026-023t: freshness gate (--live-backlog). A schema-valid DAG can be
# DEAD: the inaugural run consumed a DAG whose recommended_start ticket was
# already closed and archived, and only a human caught it. Freshness is
# SEMANTIC (every DAG ticket still pending in the live queue), NOT
# `state_at_triage.motor == HEAD` (the motor HEAD advances with every close of
# the batch itself; an equality gate would self-block after the first ticket).
# ---------------------------------------------------------------------------


def _run_with(dag_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), str(SCRIPT_PATH), str(dag_path), *extra],
        capture_output=True,
        text=True,
    )


def _write_backlog(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "backlog.md"
    header = "| Prio | Ticket | Descripcion | Dominio | Estado | Dep | Origen | Nota |"
    sep = "|---|---|---|---|---|---|---|---|"
    path.write_text("\n".join([header, sep, *rows]) + "\n", encoding="utf-8")
    return path


def _pending_row(ticket: str) -> str:
    return f"| Media | {ticket} | descripcion breve | motor/x | pending | - | s | - |"


_DAG_TICKETS = ("WOT-2026-022i", "WOT-2026-021k", "WOT-2026-019z")


def test_live_backlog_all_pending_passes(tmp_path: Path) -> None:
    backlog = _write_backlog(tmp_path, [_pending_row(t) for t in _DAG_TICKETS])
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--live-backlog", str(backlog)
    )
    assert result.returncode == 0, result.stderr


def test_live_backlog_dead_ticket_fails(tmp_path: Path) -> None:
    """DoD mutation at artifact level: a DAG citing a ticket whose live row is
    `completed` (archived shape) must FAIL with exit != 0 naming the ticket."""
    rows = [
        _pending_row("WOT-2026-022i"),
        _pending_row("WOT-2026-021k"),
        "| Media | WOT-2026-019z | cerrado hace dias | motor/x | completed |"
        " - | s | commit:abc1234 |",
    ]
    backlog = _write_backlog(tmp_path, rows)
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--live-backlog", str(backlog)
    )
    assert result.returncode == 1
    assert "WOT-2026-019z" in result.stderr
    assert "frescura" in result.stderr


def test_live_backlog_absent_ticket_fails(tmp_path: Path) -> None:
    """A DAG ticket with NO row at all in the live queue is equally dead."""
    backlog = _write_backlog(
        tmp_path, [_pending_row("WOT-2026-022i"), _pending_row("WOT-2026-021k")]
    )
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--live-backlog", str(backlog)
    )
    assert result.returncode == 1
    assert "WOT-2026-019z" in result.stderr


def test_live_backlog_pending_in_prose_does_not_count(tmp_path: Path) -> None:
    """Cell-based rule (WOT-2026-024c trap): a row whose STATE cell is
    `completed` must not be revived because the word 'pending' or the ticket id
    appear again INSIDE a prose cell."""
    rows = [
        _pending_row("WOT-2026-022i"),
        _pending_row("WOT-2026-021k"),
        "| Media | WOT-2026-019z | quedo pending mucho tiempo, ver WOT-2026-019z |"
        " motor/x | completed | - | s | - |",
    ]
    backlog = _write_backlog(tmp_path, rows)
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--live-backlog", str(backlog)
    )
    assert result.returncode == 1, (
        "a completed row must NOT count as pending via prose mentions"
    )


def test_live_backlog_missing_file_fails(tmp_path: Path) -> None:
    """Fail-closed: pointing the gate at a nonexistent backlog is an error,
    never a silent skip."""
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()),
        "--live-backlog",
        str(tmp_path / "nope.md"),
    )
    assert result.returncode == 1
    assert "no existe" in result.stderr


def test_head_sha_mismatch_warns_but_passes(tmp_path: Path) -> None:
    """state_at_triage.motor != HEAD -> WARN with premise re-check, NEVER a
    block (the HEAD advances with every close of the batch itself)."""
    result = _run_with(_write_dag(tmp_path, _valid_dag()), "--head-sha", "fff999")
    assert result.returncode == 0, result.stderr
    assert "WARN" in result.stderr
    assert "abc123" in result.stderr


def test_head_sha_match_no_warning(tmp_path: Path) -> None:
    """Matching SHA (prefix-tolerant) emits no warning."""
    result = _run_with(_write_dag(tmp_path, _valid_dag()), "--head-sha", "abc123")
    assert result.returncode == 0
    assert "WARN" not in result.stderr


# ---------------------------------------------------------------------------
# WOT-2026-023u: `depends_on_groups` models REAL dependency (consumes an
# artifact/state of A, or shares a serialized surface), NOT order preference.
# Two groups with no dependency edge and no shared surface are INDEPENDENT:
# their order in the `groups[]` list must NOT serialize them, and the
# containment freeze must never cascade from one to the other. The inaugural
# run (2026-07-13) chained G1->G2->G3 by preference; G1 stopped and containment
# would have frozen G2/G3 that depended on nothing.
#
# NOT tautological (the trap the design warns about): the validator cannot
# detect a "disguised preference" from semantics alone (025f-shaped oracle).
# So the contract is pinned by the ASYMMETRY the validator CAN enforce:
#   (c1) independent groups pass in EITHER list order (order is not contract);
#   (c2) the SAME pair, once it shares a REAL surface with no dependency,
#        FAILS (check 4) -- serialization is demanded by real surface, not by
#        list position. The mutation from (c1) to (c2) is a single shared
#        surface, and it flips the verdict: that is what makes (c1) meaningful.
# ---------------------------------------------------------------------------


def _two_independent_groups() -> dict[str, Any]:
    """A minimal valid DAG with exactly G2 and G3, no dependency edge between
    them, and DISJOINT shared_surfaces -- genuinely independent."""
    return {
        "schema": "autonomous-batch-dag/v1",
        "generated_at": "2026-07-13T00:00:00Z",
        "state_at_triage": {"motor": "abc123", "workspace": "def456", "dirty": 0},
        "groups": [
            {
                "id": "G2",
                "tickets": ["WOT-2026-023q"],
                "depends_on_groups": [],
                "blocks_groups": [],
                "shared_surfaces": ["scripts/g2_only.py"],
                "class": "M",
                "autonomy_mode": "autonomous",
                "common_gate": "pytest tests/unit/test_g2.py",
                "recovery_owner_stage": "BUILDER",
                "max_recovery_attempts": 2,
            },
            {
                "id": "G3",
                "tickets": ["WOT-2026-023s"],
                "depends_on_groups": [],
                "blocks_groups": [],
                "shared_surfaces": ["scripts/g3_only.py"],
                "class": "S",
                "autonomy_mode": "autonomous",
                "common_gate": "pytest tests/unit/test_g3.py",
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


def test_023u_independent_groups_pass_in_either_list_order(tmp_path: Path) -> None:
    """(c1) Independent groups (no dependency edge, disjoint surfaces) validate
    regardless of their position in `groups[]`. The list order is NOT the DAG:
    a preference like 'G2 before G3' has no place in depends_on_groups, so
    reversing the list must not change the verdict. Both orders -> exit 0."""
    dag = _two_independent_groups()
    forward = _run(_write_dag(tmp_path, dag, "forward.json"))
    assert forward.returncode == 0, (
        f"G2 before G3 (independent) must validate: {forward.stderr}"
    )

    reversed_dag = copy.deepcopy(dag)
    reversed_dag["groups"] = list(reversed(reversed_dag["groups"]))
    backward = _run(_write_dag(tmp_path, reversed_dag, "backward.json"))
    assert backward.returncode == 0, (
        "reversing the groups[] list must NOT change the verdict for "
        f"independent groups -- list order is not a dependency: {backward.stderr}"
    )


def test_023u_same_pair_sharing_real_surface_without_dep_fails(
    tmp_path: Path,
) -> None:
    """(c2) MUTATION that makes (c1) non-tautological: take the SAME independent
    pair and give them a REAL shared surface with no dependency edge. Now
    check 4 must reject them -- serialization is demanded by a real surface,
    not by list position. Revert the shared surface (back to c1) -> exit 0;
    add it -> exit 1. That exit-code pair is the contract's teeth."""
    dag = _two_independent_groups()
    # The ONLY change vs the passing (c1) fixture: a genuinely shared surface.
    dag["groups"][0]["shared_surfaces"] = ["scripts/g2_only.py", "shared/race.py"]
    dag["groups"][1]["shared_surfaces"] = ["scripts/g3_only.py", "shared/race.py"]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1, (
        "independent groups sharing a REAL surface must be rejected (check 4): "
        "the shared surface IS a real dependency and demands serialization"
    )
    assert "solapamiento" in result.stderr.lower()
