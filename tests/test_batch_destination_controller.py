from __future__ import annotations

import json
from pathlib import Path

from scripts.batch_destination_controller import (
    RepoSpec,
    _count_items,
    _validate_is_clean,
    build_manifest,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _adopted_repo(root: Path, motor_root: Path) -> None:
    _write(
        root / ".agent/config/motor_destination_link.json",
        json.dumps({"motor_root": str(motor_root)}),
    )
    _write(root / "PROJECT.md", "Ticket prefix: TST\n")


def _contract_ready_repo(root: Path) -> None:
    _write(root / ".agent/planning/repo_charter.md", "# Charter\n")
    _write(root / ".agent/planning/plan_graph.md", "# Plan Graph\n")
    _write(root / ".agent/planning/ticket_contracts.md", "status: frozen\n")


# --- adoption / contract formation ---------------------------------------


def test_adopted_repo_still_requires_contract_formation(tmp_path: Path) -> None:
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)

    manifest = build_manifest([RepoSpec(path=repo, name="repo")], motor_root)
    row = manifest["repos"][0]

    assert row["states"]["adopted"] is True
    assert row["states"]["contract_ready"] is False
    assert row["states"]["contract_formation_required"] is True
    assert row["next_action"] == "RUN_CONTRACT_FORMATION"


def test_manifest_keeps_evidence_per_repo(tmp_path: Path) -> None:
    motor_root = tmp_path / "motor"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _adopted_repo(repo_a, motor_root)
    _adopted_repo(repo_b, motor_root)

    manifest = build_manifest(
        [RepoSpec(path=repo_a, name="repo-a"), RepoSpec(path=repo_b, name="repo-b")],
        motor_root,
    )

    assert len(manifest["repos"]) == 2
    for row in manifest["repos"]:
        assert row["evidence"]
        assert any(item["type"] == "path" for item in row["evidence"])
        assert str(tmp_path / row["repo"]) in row["evidence"][0]["path"]


def test_inter_repo_recheck_detects_shared_surfaces(tmp_path: Path) -> None:
    motor_root = tmp_path / "motor"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _adopted_repo(repo_a, motor_root)
    _adopted_repo(repo_b, motor_root)

    manifest = build_manifest(
        [
            RepoSpec(path=repo_a, name="repo-a", shared_surfaces=("api:orders",)),
            RepoSpec(path=repo_b, name="repo-b", shared_surfaces=("api:orders",)),
        ],
        motor_root,
    )

    assert manifest["inter_repo_recheck"]["required"] is True
    assert manifest["inter_repo_recheck"]["overlaps"] == [
        {"surface": "api:orders", "repos": ["repo-a", "repo-b"]}
    ]


# --- four-layer publication model ----------------------------------------


def test_classified_verdict_alone_is_not_publishable(tmp_path: Path) -> None:
    """classify_publication verdict is [RELATO]; publishable needs all 3 layers."""
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)
    _contract_ready_repo(repo)
    _write(
        repo / "orchestrator_pipeline/reports/publication_manifest.json",
        json.dumps({"verdict": "LISTO_PARA_PUBLICAR"}),
    )

    row = build_manifest([RepoSpec(path=repo, name="repo")], motor_root)["repos"][0]

    assert row["states"]["publication_classified"] is True
    assert row["states"]["publication_audit_passed"] is False
    assert row["states"]["publishable"] is False  # no local gate, no Pass B
    assert row["publication_verdict_is_relato"] is True
    # Without read-only gates, integration is unproven: cannot reason about
    # publication yet. The classify verdict alone never short-circuits the floor.
    assert row["next_action"] == "RUN_READONLY_GATES"


def test_publishable_requires_audit_pass_b(tmp_path: Path) -> None:
    """All three layers present -> publishable; missing audit -> not yet."""
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)
    _contract_ready_repo(repo)
    reports = repo / "orchestrator_pipeline/reports"
    _write(
        reports / "publication_manifest.json",
        json.dumps({"verdict": "LISTO_PARA_PUBLICAR"}),
    )

    # Without Pass B closeout: integrated_local injected via gate-free helper path.
    # Simulate local integration by running the read-only gate against a fake
    # controller that returns a clean (dict-shaped) validate payload.
    _install_fake_controller(motor_root, errors={}, warnings={})
    _install_fake_memory(motor_root, prints=str(repo.resolve()))

    row = build_manifest(
        [RepoSpec(path=repo, name="repo")], motor_root, run_readonly_gates=True
    )["repos"][0]
    assert row["states"]["integrated_local"] is True
    assert row["states"]["publication_classified"] is True
    assert row["states"]["publication_audit_passed"] is False
    assert row["states"]["publishable"] is False
    assert row["next_action"] == "RUN_AUDIT_GIT_PUBLICATION_PASS_B"

    # Now add the adversarial Pass B evidence.
    _write(
        reports / "publication_audit_20260629.json",
        json.dumps({"verdict": "LISTO_PARA_PUBLICAR"}),
    )
    row2 = build_manifest(
        [RepoSpec(path=repo, name="repo")], motor_root, run_readonly_gates=True
    )["repos"][0]
    assert row2["states"]["publication_audit_passed"] is True
    assert row2["states"]["publishable"] is True
    assert row2["next_action"] == "READY_FOR_REMOTE_PUBLICATION"


def test_closed_pending_ci_separate_from_publishable(tmp_path: Path) -> None:
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)
    _contract_ready_repo(repo)
    _write(
        repo / "orchestrator_pipeline/reports/closeout_TST-2026-001a.md",
        "state: CLOSED_PENDING_CI\n",
    )
    # CI-pending only surfaces as next_action once the local gate floor is met.
    _install_fake_controller(motor_root, errors={}, warnings={})
    _install_fake_memory(motor_root, prints=str(repo.resolve()))

    row = build_manifest(
        [RepoSpec(path=repo, name="repo")], motor_root, run_readonly_gates=True
    )["repos"][0]

    assert row["states"]["integrated_local"] is True
    assert row["states"]["closed_pending_ci"] is True
    assert row["states"]["publishable"] is False
    assert row["next_action"] == "WAIT_FOR_CI_RECHECK"


# --- read-only gate branch (GAP-4) + validate shape (BUG-1/2) -------------


def test_validate_is_clean_handles_dict_shape() -> None:
    """The canonical validate shape uses dicts of category->list, not ints."""
    assert _validate_is_clean(json.dumps({"errors": {}, "warnings": {}})) is True
    assert (
        _validate_is_clean(json.dumps({"errors": {"bus": ["x"]}, "warnings": {}}))
        is False
    )
    assert (
        _validate_is_clean(json.dumps({"errors": {}, "warnings": {"drift": ["w"]}}))
        is False
    )
    # legacy int shape still works
    assert _validate_is_clean(json.dumps({"errors": 0, "warnings": 0})) is True
    assert _validate_is_clean(json.dumps({"errors": 1, "warnings": 0})) is False
    # garbage / non-json fails closed
    assert _validate_is_clean("not json") is False
    assert _validate_is_clean(json.dumps([])) is False


def test_count_items_shapes() -> None:
    assert _count_items(None) == 0
    assert _count_items({}) == 0
    assert _count_items({"a": ["x", "y"], "b": []}) == 2
    assert _count_items(["x", "y", "z"]) == 3
    assert _count_items(5) == 5


def test_readonly_gate_detects_dirty_validate(tmp_path: Path) -> None:
    """GAP-4: exercise the run_readonly_gates branch with a non-clean validate."""
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)
    _contract_ready_repo(repo)
    _install_fake_controller(motor_root, errors={"bus": ["bus_drift"]}, warnings={})
    _install_fake_memory(motor_root, prints=str(repo.resolve()))

    row = build_manifest(
        [RepoSpec(path=repo, name="repo")], motor_root, run_readonly_gates=True
    )["repos"][0]

    assert row["states"]["integrated_local"] is False
    assert row["states"]["agent_project_root_verified"] is True
    assert row["next_action"] == "RUN_ORCHESTRATOR_PIPELINE_FOR_REPO"
    # both gate commands are recorded as evidence
    assert sum(1 for e in row["evidence"] if e["type"] == "command") == 2


def test_readonly_gate_flags_wrong_project_root(tmp_path: Path) -> None:
    """If memory status does not echo the repo root, AGENT_PROJECT_ROOT is wrong."""
    motor_root = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted_repo(repo, motor_root)
    _contract_ready_repo(repo)
    _install_fake_controller(motor_root, errors={}, warnings={})
    _install_fake_memory(motor_root, prints="C:/some/other/motor/path")

    row = build_manifest(
        [RepoSpec(path=repo, name="repo")], motor_root, run_readonly_gates=True
    )["repos"][0]

    assert row["states"]["agent_project_root_verified"] is False
    assert row["next_action"] == "FIX_AGENT_PROJECT_ROOT_FOR_REPO"


# --- fakes ---------------------------------------------------------------


def _install_fake_controller(
    motor_root: Path, *, errors: object, warnings: object
) -> None:
    """Write a fake .agent/agent_controller.py that prints a validate JSON."""
    payload = json.dumps({"errors": errors, "warnings": warnings})
    script = f"import sys\nprint({payload!r})\nsys.exit(0)\n"
    _write(motor_root / ".agent/agent_controller.py", script)


def _install_fake_memory(motor_root: Path, *, prints: str) -> None:
    """Write a fake scripts/memory_context.py that echoes a root path."""
    script = f"import sys\nprint({prints!r})\nsys.exit(0)\n"
    _write(motor_root / "scripts/memory_context.py", script)
