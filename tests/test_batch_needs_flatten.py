"""Regression: WOT-2026-015d — needs_flatten detection in batch controller.

A destination with nested product (publica/repo, z_automatizacion/publica/repo)
or an embedded legacy engine (agent_system/, orquestacion_agentes/ carrying its
own agent_controller.py) must be flagged needs_flatten, and next_action must be
RUN_FLATTEN BEFORE Contract Formation: contracts on provisional topology assume
paths that disappear after flattening.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.batch_destination_controller import (
    RepoSpec,
    _detect_needs_flatten,
    build_manifest,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _adopted(root: Path, motor: Path) -> None:
    _write(
        root / ".agent/config/motor_destination_link.json",
        json.dumps({"motor_root": str(motor), "adopted": True}),
    )


def test_detect_nested_product(tmp_path: Path) -> None:
    (tmp_path / "publica/repo/src").mkdir(parents=True)
    r = _detect_needs_flatten(tmp_path)
    assert r["needs_flatten"] is True
    assert "nested_product:publica/repo" in r["signals"]


def test_detect_nested_product_z_automatizacion(tmp_path: Path) -> None:
    (tmp_path / "z_automatizacion/publica/repo/src").mkdir(parents=True)
    r = _detect_needs_flatten(tmp_path)
    assert r["needs_flatten"] is True
    assert "nested_product:z_automatizacion/publica/repo" in r["signals"]


def test_detect_embedded_legacy(tmp_path: Path) -> None:
    _write(tmp_path / "orquestacion_agentes/.agent/agent_controller.py", "# legacy\n")
    r = _detect_needs_flatten(tmp_path)
    assert r["needs_flatten"] is True
    assert any("embedded_legacy" in s for s in r["signals"])


def test_legacy_dir_without_controller_is_not_flagged(tmp_path: Path) -> None:
    """Un dir con nombre legacy pero SIN agent_controller.py no cuenta."""
    (tmp_path / "agent_system/docs").mkdir(parents=True)
    r = _detect_needs_flatten(tmp_path)
    assert r["needs_flatten"] is False
    assert r["signals"] == []


def test_clean_flat_repo_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    r = _detect_needs_flatten(tmp_path)
    assert r["needs_flatten"] is False


def test_needs_flatten_blocks_before_contract_formation(tmp_path: Path) -> None:
    """BARRERA: repo adoptado + nested product -> RUN_FLATTEN (no RUN_CONTRACT_FORMATION)."""
    motor = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted(repo, motor)
    # planning frozen (haria contract_ready=True si no fuera por needs_flatten)
    _write(repo / ".agent/planning/repo_charter.md", "# c\n")
    _write(repo / ".agent/planning/plan_graph.md", "# p\n")
    _write(repo / ".agent/planning/ticket_contracts.md", "status: frozen\n")
    # topologia provisional
    (repo / "publica/repo/src").mkdir(parents=True)

    row = build_manifest([RepoSpec(path=repo, name="repo")], motor)["repos"][0]
    assert row["states"]["needs_flatten"] is True
    assert row["next_action"] == "RUN_FLATTEN"
    assert "nested_product:publica/repo" in row["flatten_signals"]


def test_flat_adopted_repo_reaches_contract_formation(tmp_path: Path) -> None:
    """Sin topologia provisional, un repo adoptado sin contrato -> RUN_CONTRACT_FORMATION."""
    motor = tmp_path / "motor"
    repo = tmp_path / "repo"
    _adopted(repo, motor)
    (repo / "src").mkdir()

    row = build_manifest([RepoSpec(path=repo, name="repo")], motor)["repos"][0]
    assert row["states"]["needs_flatten"] is False
    assert row["next_action"] == "RUN_CONTRACT_FORMATION"
