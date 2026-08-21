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
import tempfile
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
    block (the HEAD advances with every close of the batch itself).

    WOT-2026-051f: this test used the placeholder shas `fff999`/`abc123`, which
    resolve to NO commit. Once `--head-sha` began resolving against git, those
    placeholders exercised the new unresolvable branch instead of the staleness
    branch they were written for -- so they now use REAL motor shas. The
    property under test (mismatch -> WARN, never a block) is unchanged.
    """
    head = _motor_sha("HEAD")
    older = _motor_sha("HEAD~1")
    if older == head:
        pytest.skip("historial insuficiente")
    dag = _valid_dag()
    dag["state_at_triage"]["motor"] = head
    result = _run_with(_write_dag(tmp_path, dag), "--head-sha", older)
    assert result.returncode == 0, result.stderr
    assert "WARN" in result.stderr
    assert head in result.stderr


def test_head_sha_match_no_warning(tmp_path: Path) -> None:
    """Matching SHA (prefix-tolerant) emits no warning.

    Prefix tolerance is the POINT: `state_at_triage.motor` holds the short sha
    while the caller passes the full one (or vice versa). Real shas, per the
    note in the test above.
    """
    head = _motor_sha("HEAD")
    dag = _valid_dag()
    dag["state_at_triage"]["motor"] = head[:7]
    result = _run_with(_write_dag(tmp_path, dag), "--head-sha", head)
    assert result.returncode == 0, result.stderr
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


# ---------------------------------------------------------------------------
# WOT-2026-051a: BOM tolerance + pair-completeness shape/content checks.
#
# The pair check landed in WOT-2026-049a with NO tests (verified: `grep
# backlog_triage` over this file returned 0 hits before this block). So these
# tests pin BOTH the new behavior and the 049a contract that was never pinned.
# ---------------------------------------------------------------------------


def _write_pair(
    tmp_path: Path,
    stem: str,
    *,
    md: str | None = "narrativa hermana\n",
    bom: bool = False,
) -> Path:
    """Write a triage pair: `<stem>.json` (+ optional `<stem>.md`).

    `md=None` omits the narrative entirely; `bom=True` prefixes the JSON with
    a UTF-8 BOM, which is what any Windows writer using utf-8-sig produces.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    payload = json.dumps(_valid_dag(), indent=2)
    if bom:
        json_path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    else:
        json_path.write_text(payload, encoding="utf-8")
    if md is not None:
        (tmp_path / f"{stem}.md").write_text(md, encoding="utf-8")
    return json_path


def test_051a_bom_dag_validates_like_its_bomless_twin(tmp_path: Path) -> None:
    """(a) A DAG with a BOM must validate EXACTLY like the same DAG without it.

    Before the fix `read_text(encoding="utf-8")` raised `Unexpected UTF-8 BOM`
    inside the try/except, so the CLI died at PARSE time -- before
    `validate_dag()` and before the 049a pair check ran. Not one validation
    executed. Measured on the destination's own
    `backlog_triage_20260711-0239.json` (bytes efbbbf, exit 1).
    """
    plain = _run(_write_pair(tmp_path / "plain", "backlog_triage_20260101-000000"))
    with_bom = _run(
        _write_pair(tmp_path / "bom", "backlog_triage_20260101-000000", bom=True)
    )
    assert with_bom.returncode == plain.returncode == 0, (
        "a BOM must not change the verdict; utf-8-sig is a strict superset of "
        f"utf-8 (plain={plain.returncode} bom={with_bom.returncode} "
        f"stderr={with_bom.stderr!r})"
    )
    assert "BOM" not in with_bom.stderr


def test_051a_bom_does_not_mask_a_real_error(tmp_path: Path) -> None:
    """(a-MUTATION) The BOM fix must not become a blanket pass.

    A BOM'd DAG that is genuinely INVALID must still be rejected -- proving the
    fix restored parsing rather than short-circuiting validation.
    """
    dag = _valid_dag()
    dag["groups"][0]["class"] = "NOT-A-CLASS"
    path = tmp_path / "backlog_triage_20260101-000000.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(dag, indent=2).encode("utf-8"))
    (tmp_path / "backlog_triage_20260101-000000.md").write_text("x", encoding="utf-8")
    result = _run(path)
    assert result.returncode == 1, "a BOM'd but invalid DAG must still be rejected"
    assert "BOM" not in result.stderr, "it must fail on the CLASS, not on parsing"


def test_051a_missing_md_still_rejected(tmp_path: Path) -> None:
    """The 049a contract itself, never pinned by a test until now."""
    result = _run(_write_pair(tmp_path, "backlog_triage_20260101-000000", md=None))
    assert result.returncode == 1
    assert "par incompleto" in result.stderr.lower()


@pytest.mark.parametrize("blank", ["", "   \n\t  \n"])
def test_051a_empty_md_is_not_a_complete_pair(tmp_path: Path, blank: str) -> None:
    """(e) An EMPTY .md must not count as a complete pair.

    `exists()` alone reads an interrupted run -- one that created the file and
    died before writing it -- as success, which is precisely the failure mode
    049a set out to catch.
    """
    result = _run(_write_pair(tmp_path, "backlog_triage_20260101-000000", md=blank))
    assert result.returncode == 1, (
        "an empty/whitespace-only narrative is an interrupted run, not a pair"
    )
    assert "par incompleto" in result.stderr.lower()


@pytest.mark.parametrize(
    "stem",
    [
        "backlog_triage_output",  # legacy name 049a retired from the contract
        "backlog_triage_NOESFECHA",  # non-timestamp suffix
        "backlog_triage_2026011",  # too short to be YYYYMMDD-HHMMSS
    ],
)
def test_051a_non_timestamp_names_are_ignored_by_pair_check(
    tmp_path: Path, stem: str
) -> None:
    """(d) DECIDED in the ticket: a JSON whose suffix is not YYYYMMDD-HHMMSS is
    IGNORED by the pair check -- empty error list, no error.

    Rationale (not the Builder's call): the CLI validates GENERIC DAGs, so
    demanding an .md sibling from every file starting with `backlog_triage_`
    would break legitimate consumers passing files outside the triage pattern.
    """
    result = _run(_write_pair(tmp_path, stem, md=None))
    assert result.returncode == 0, (
        f"{stem}.json does not match the triage timestamp pattern, so the pair "
        f"check must ignore it (stderr={result.stderr!r})"
    )
    assert "par incompleto" not in result.stderr.lower()


def test_051a_timestamped_name_still_demands_its_pair(tmp_path: Path) -> None:
    """(d-MUTATION) Makes the test above non-tautological: the SAME missing-.md
    situation with a WELL-FORMED timestamp must still be rejected. Otherwise
    'ignore bad names' could silently degrade into 'ignore everything'."""
    result = _run(_write_pair(tmp_path, "backlog_triage_20260808-010534", md=None))
    assert result.returncode == 1, (
        "a canonical triage name must still require its .md sibling"
    )
    assert "par incompleto" in result.stderr.lower()


# ---------------------------------------------------------------------------
# WOT-2026-046h: condition 3 (`contabilidad_completa`) now has teeth.
# Measured on the REAL DAG backlog_triage_20260820-024142.json: `WOT-2026-055h`
# sat in a group while absent from `tickets[]`, and the validator returned
# exit 0 both before AND after that incoherence -- the barrier existed and did
# not bite where the failure happens. Contract:
# prompts/orchestrator_autonomous_ticket_batch.md:741.
# ---------------------------------------------------------------------------


def _roster_dag() -> dict[str, Any]:
    """Baseline + a triage ROSTER (`tickets[]` with classification/evidence)."""
    dag = _valid_dag()
    dag["tickets"] = [
        {"id": t, "classification": "APTO_AUTONOMO", "evidence_label": "VERIFICADO"}
        for t in _DAG_TICKETS
    ]
    return dag


def test_046h_roster_complete_passes(tmp_path: Path) -> None:
    """Positive control: every grouped ticket rostered -> accounting is clean."""
    result = _run(_write_dag(tmp_path, _roster_dag()))
    assert result.returncode == 0, result.stderr


def test_046h_grouped_ticket_absent_from_roster_rejected(tmp_path: Path) -> None:
    """The defect measured on the real DAG: a ticket scheduled in a group but
    never triaged (absent from `tickets[]`) used to pass with exit 0."""
    dag = _roster_dag()
    dag["tickets"] = [e for e in dag["tickets"] if e["id"] != "WOT-2026-019z"]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "WOT-2026-019z" in result.stderr
    assert "contabilidad" in result.stderr


def test_046h_groupless_roster_entry_must_be_enumerated_as_excluded(
    tmp_path: Path,
) -> None:
    """F3 verbatim: a `tickets[]` entry in NO group is triage context and MUST
    be enumerated as excluded, never silently omitted."""
    dag = _roster_dag()
    dag["tickets"].append(
        {
            "id": "WOT-2026-099x",
            "classification": "DISENO_PRIMERO",
            "evidence_label": "INFERIDO",
        }
    )
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "WOT-2026-099x" in result.stderr
    assert "omision silenciosa" in result.stderr


@pytest.mark.parametrize(
    "key", ["requires_human", "premise_verify", "excluded", "excluded_from_flight"]
)
def test_046h_enumerated_exclusion_is_accepted(tmp_path: Path, key: str) -> None:
    """Mutation counterpart: enumerate the same entry and it passes. Every
    accepted key is exercised -- `excluded_from_flight` is not hypothetical, it
    is the name a real closed-flight DAG uses."""
    dag = _roster_dag()
    dag["tickets"].append(
        {
            "id": "WOT-2026-099x",
            "classification": "DISENO_PRIMERO",
            "evidence_label": "INFERIDO",
        }
    )
    dag[key] = [{"id": "WOT-2026-099x", "reason": "decision de producto pendiente"}]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, result.stderr


def test_046h_exclusion_list_schema_variant_is_not_flagged(tmp_path: Path) -> None:
    """Not every `tickets[]` is a roster. A real closed-flight DAG
    (backlog_triage_output_044_CERRADO.json) uses `tickets[]` to enumerate ONLY
    the excluded entries as `{id, note}`, with the flown tickets living solely
    in `groups[]`. Reading that as "untriaged" produced 4 false positives on a
    DAG correct for its own schema variant: the discriminator is SHAPE (a
    roster labels its entries), never count."""
    dag = _valid_dag()
    dag["tickets"] = [
        {"id": "WOT-2026-027d", "note": "DISENO_PRIMERO: decision sin adjudicar."}
    ]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, result.stderr


def test_046h_dag_without_root_tickets_still_valid(tmp_path: Path) -> None:
    """Backward compatibility: this CLI also validates generic DAGs carrying
    only `groups[]`; the accounting universe is well defined without a roster."""
    dag = _valid_dag()
    assert "tickets" not in dag
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, result.stderr


# WOT-2026-046h (F-4): an unlabelled/invalid evidence_label used to pass.


def test_046h_missing_evidence_label_rejected(tmp_path: Path) -> None:
    dag = _roster_dag()
    del dag["tickets"][0]["evidence_label"]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "evidencia" in result.stderr
    assert dag["tickets"][0]["id"] in result.stderr


def test_046h_invalid_evidence_label_rejected(tmp_path: Path) -> None:
    dag = _roster_dag()
    dag["tickets"][0]["evidence_label"] = "SEGURO_SEGURISIMO"
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "SEGURO_SEGURISIMO" in result.stderr


# ---------------------------------------------------------------------------
# WOT-2026-051f: `--head-sha` accepted ANY string. Reproduced with
# `deadbeefdeadbeef...` -- a sha that exists in NO repo -- giving rc=0 plus the
# ORDINARY staleness WARN, indistinguishable from a genuinely stale motor.
# NON-GOAL: staleness semantics unchanged; nothing becomes blocking.
# ---------------------------------------------------------------------------

_UNRESOLVABLE_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _motor_sha(rev: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", rev],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        pytest.skip(f"motor no es un repo git resoluble para {rev}")
    return out.stdout.strip()


def test_051f_unresolvable_sha_gets_its_own_distinct_warning(tmp_path: Path) -> None:
    """DoD (a)+(c): a sha resolving to no commit of the MOTOR emits a warning
    DISTINCT from staleness, and the staleness WARN is NOT also emitted -- the
    whole defect was that both cases produced the same message."""
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--head-sha", _UNRESOLVABLE_SHA
    )
    assert result.returncode == 0, "NON-GOAL: sigue sin bloquear"
    assert "NO resuelve" in result.stderr
    assert "re-verificar" not in result.stderr, (
        "el WARN de staleness no debe emitirse: no hay nada con que comparar"
    )


def test_051f_real_motor_head_is_silent(tmp_path: Path) -> None:
    """DoD (c): the real motor HEAD, matching state_at_triage -> no sha warning."""
    head = _motor_sha("HEAD")
    dag = _valid_dag()
    dag["state_at_triage"]["motor"] = head
    result = _run_with(_write_dag(tmp_path, dag), "--head-sha", head)
    assert result.returncode == 0, result.stderr
    assert "NO resuelve" not in result.stderr
    assert "re-verificar" not in result.stderr


def test_051f_real_but_older_sha_still_warns_staleness(tmp_path: Path) -> None:
    """DoD (b): the LEGITIMATE case (real motor sha != state_at_triage.motor)
    keeps its staleness WARN unchanged."""
    head = _motor_sha("HEAD")
    older = _motor_sha("HEAD~1")
    if older == head:
        pytest.skip("historial insuficiente")
    dag = _valid_dag()
    dag["state_at_triage"]["motor"] = head
    result = _run_with(_write_dag(tmp_path, dag), "--head-sha", older)
    assert result.returncode == 0, result.stderr
    assert "re-verificar" in result.stderr
    assert "NO resuelve" not in result.stderr


# ---------------------------------------------------------------------------
# WOT-2026-055r: `--live-backlog` gave a FALSE RED post-flight -- tickets the
# flight closed have migrated to the archive, so a DAG that was fresh when
# consumed is reported as "DAG muerto". Verified on the real closed flight
# backlog_triage_output_044_CERRADO.json.
# ---------------------------------------------------------------------------


def _git_backlog_repo(tmp_path: Path, rows: list[str]) -> tuple[Path, str]:
    """A throwaway git repo holding a backlog.md; returns (path, sha).

    Its own `.git` is REQUIRED: without it git walks up and answers about the
    REAL tree, so the fixture would not be hermetic (WOT-2026-020r).
    """
    repo = tmp_path / "destino"
    repo.mkdir()

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True
        )

    if run("init").returncode != 0:
        pytest.skip("git no disponible")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    backlog = repo / "backlog.md"
    header = "| Prio | Ticket | Descripcion | Dominio | Estado | Dep | Origen | Nota |"
    sep = "|---|---|---|---|---|---|---|---|"
    backlog.write_text("\n".join([header, sep, *rows]) + "\n", encoding="utf-8")
    run("add", "backlog.md")
    if run("commit", "-m", "triage").returncode != 0:
        pytest.skip("no se pudo commitear el fixture")
    sha = run("rev-parse", "HEAD").stdout.strip()
    return backlog, sha


def test_055r_as_of_revalidates_a_closed_flight(tmp_path: Path) -> None:
    """DoD (a): with --as-of <sha del triaje>, a DAG whose tickets have since
    been closed validates GREEN -- it was fresh when consumed."""
    backlog, sha = _git_backlog_repo(tmp_path, [_pending_row(t) for t in _DAG_TICKETS])
    # The flight closes: every ticket leaves the live queue.
    backlog.write_text(
        "| Prio | Ticket | Descripcion | Dominio | Estado | Dep | Origen | Nota |\n"
        "|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    dag_path = _write_dag(tmp_path, _valid_dag())

    stale = _run_with(dag_path, "--live-backlog", str(backlog))
    assert stale.returncode == 1, "control: la cola viva da el FALSO ROJO"

    fresh = _run_with(dag_path, "--live-backlog", str(backlog), "--as-of", sha)
    assert fresh.returncode == 0, fresh.stderr


def test_055r_as_of_negative_control_dag_not_fresh_at_that_sha(
    tmp_path: Path,
) -> None:
    """DoD (c): a DAG that was NOT fresh at the given sha still fails."""
    backlog, sha = _git_backlog_repo(
        tmp_path,
        [_pending_row("WOT-2026-022i"), _pending_row("WOT-2026-021k")],
    )
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()),
        "--live-backlog",
        str(backlog),
        "--as-of",
        sha,
    )
    assert result.returncode == 1
    assert "WOT-2026-019z" in result.stderr


def test_055r_unresolvable_as_of_fails_closed(tmp_path: Path) -> None:
    """An unresolvable --as-of must NOT degrade into the live read it replaces."""
    backlog, _ = _git_backlog_repo(tmp_path, [_pending_row(t) for t in _DAG_TICKETS])
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()),
        "--live-backlog",
        str(backlog),
        "--as-of",
        _UNRESOLVABLE_SHA,
    )
    assert result.returncode == 1
    assert "no resuelve" in result.stderr.lower()


def test_055r_live_read_declares_it_is_pre_execution_only(tmp_path: Path) -> None:
    """DoD (b): without --as-of the check states its own scope, instead of
    leaving "this is pre-execution only" as folklore."""
    backlog = _write_backlog(tmp_path, [_pending_row(t) for t in _DAG_TICKETS])
    result = _run_with(
        _write_dag(tmp_path, _valid_dag()), "--live-backlog", str(backlog)
    )
    assert result.returncode == 0, result.stderr
    assert "PRE-ejecucion" in result.stderr
    assert "--as-of" in result.stderr


# ---------------------------------------------------------------------------
# Hallazgos del bucle adversarial L700 (nonce 1e366cfe, commit 25bb8ea).
# BA11 REFUTO dos puntos; ambos se reprodujeron antes de tocar nada.
# ---------------------------------------------------------------------------


def test_l700_mixed_roster_does_not_flag_annotated_exclusions(tmp_path: Path) -> None:
    """BA11/P2, reproducido: una `tickets[]` MIXTA -- exclusiones `{id, note}`
    mas UNA entrada etiquetada -- encendia `is_roster` para toda la lista y
    marcaba esas exclusiones anotadas como omision silenciosa.

    La forma se lee ahora POR ENTRADA: un `note` no vacio ES la razon que el
    contrato pide, asi que la entrada cuenta como excluida. El caso medido daba
    2 falsos positivos.
    """
    dag = _valid_dag()
    dag["tickets"] = [
        {"id": "WOT-2026-090x", "note": "DISENO_PRIMERO: decision sin adjudicar"},
        {"id": "WOT-2026-091x", "note": "bloqueada por politica de seguridad"},
        *[
            {
                "id": t,
                "classification": "APTO_AUTONOMO",
                "evidence_label": "VERIFICADO",
            }
            for t in _DAG_TICKETS
        ],
    ]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, result.stderr


def test_l700_entry_without_group_note_or_enumeration_still_rejected(
    tmp_path: Path,
) -> None:
    """Contrapartida del fix anterior: relajar por `note` no puede desactivar la
    deteccion. Una entrada sin grupo, SIN note y SIN enumerar sigue siendo la
    omision silenciosa que F3 prohibe."""
    dag = _valid_dag()
    dag["tickets"] = [
        {"id": t, "classification": "APTO_AUTONOMO", "evidence_label": "VERIFICADO"}
        for t in (*_DAG_TICKETS, "WOT-2026-099z")
    ]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 1
    assert "WOT-2026-099z" in result.stderr
    assert "omision silenciosa" in result.stderr


def test_l700_annotated_exclusion_needs_no_evidence_label(tmp_path: Path) -> None:
    """Misma regla por-entrada en F-4: una exclusion anotada nunca prometio
    `evidence_label`, asi que exigirselo seria el mismo falso positivo."""
    dag = _valid_dag()
    dag["tickets"] = [
        {"id": "WOT-2026-090x", "note": "excluida a proposito"},
        *[
            {
                "id": t,
                "classification": "APTO_AUTONOMO",
                "evidence_label": "VERIFICADO",
            }
            for t in _DAG_TICKETS
        ],
    ]
    result = _run(_write_dag(tmp_path, dag))
    assert result.returncode == 0, result.stderr


def test_l700_unanswerable_resolution_is_not_reported_as_invalid() -> None:
    """BA11/P3: "no comprobable" != "invalido", y aqui queda PINEADO.

    Se llama a `_sha_resolves_in_motor` con un directorio que NO es un repo git
    (su propio tmp, sin `.git`): la pregunta no se puede responder, asi que debe
    devolver None -- nunca False. Con False, el CLI avisaria "NO resuelve" cada
    vez que corre fuera del motor: un cry-wolf. La rama se prueba DIRECTAMENTE
    porque por CLI el motor siempre es resoluble desde SCRIPT_PATH, asi que
    ninguna invocacion de linea de comandos alcanza este camino.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from validate_batch_dag import _sha_resolves_in_motor
    finally:
        sys.path.pop(0)

    # dir=Path.home() a proposito, NO el tmp_path de pytest: en esta suite
    # tempfile esta redirigido a tests/sandbox/test_runtime/, que vive DENTRO
    # del motor -- git haria walk-up y contestaria por el repo REAL. Ese fallo
    # de hermetismo lo cazo este mismo test en su primera version (rc=False en
    # vez de None) y es exactamente la trampa de WOT-2026-020r.
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        outside = Path(tmp) / "sin_repo"
        outside.mkdir()
        assert not (outside / ".git").exists()
        probe = subprocess.run(
            ["git", "-C", str(outside), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            pytest.skip("el directorio de trabajo esta dentro de un repo git")
        verdict = _sha_resolves_in_motor(_UNRESOLVABLE_SHA, outside)

    assert verdict is None, (
        f"fuera de un repo la respuesta debe ser None (incognoscible), no {verdict!r}"
    )


def test_l700_real_motor_resolves_true_and_fake_resolves_false() -> None:
    """Control positivo Y negativo del resolutor, en el repo REAL del motor:
    el HEAD resuelve True y un sha inventado resuelve False. Sin este par, el
    test de arriba pasaria igual con una funcion que devolviera None siempre."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from validate_batch_dag import _sha_resolves_in_motor
    finally:
        sys.path.pop(0)

    assert _sha_resolves_in_motor(_motor_sha("HEAD"), PROJECT_ROOT) is True
    assert _sha_resolves_in_motor(_UNRESOLVABLE_SHA, PROJECT_ROOT) is False
