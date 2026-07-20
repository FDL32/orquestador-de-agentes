"""Regression: WOT-2026-023m(c) — contract-formation gate wired in closeout-mode.

Background: validate_contract_formation validated the STRUCTURE of the motor CF
triple (repo_charter.md + plan_graph.md + .agent/planning/ticket_contracts.md)
but was a guard NOBODY invoked (declared in guard_wiring_policy.yaml::known_unwired,
owner 023m): a malformed plan_graph broke no gate = laboratory green. This gate
wires it into run_preflight_check ONLY in closeout-mode, over the motor CF triple.

These tests are the barrier: a malformed CF file in closeout mode MUST block the
close; a well-formed triple passes; a missing triple skips (non-blocking).
The wiring itself (import visible to check_guard_wiring) is asserted in
test_check_guard_wiring.py::test_real_repo_wired_set_is_exactly_expected.
"""

from __future__ import annotations

from pathlib import Path

import scripts.prepush_check as pc
from scripts.prepush_check import run_contract_formation_check


def test_motor_cf_triple_valid_passes() -> None:
    """The real motor CF triple is well-formed -> gate passes (0 structure errors)."""
    result = run_contract_formation_check(Path(__file__).resolve().parents[1])
    assert result.passed is True
    assert result.is_blocking is True
    assert "0 structure errors" in result.output


def test_malformed_cf_blocks(tmp_path: Path, monkeypatch) -> None:
    """BARRERA: si el validador reporta errores, el gate bloquea el cierre.

    Redirige _MOTOR_ROOT a un tmp con un plan_graph MALFORMADO (paralelizable
    invalido en un bloque no-terminal). Sin el gate, ese plan_graph roto no
    rompia nada; con el gate, bloquea.
    """
    charter = tmp_path / "repo_charter.md"
    plan_graph = tmp_path / "plan_graph.md"
    tickets = tmp_path / ".agent" / "planning" / "ticket_contracts.md"
    tickets.parent.mkdir(parents=True, exist_ok=True)
    # Copy the real (valid) charter + tickets so ONLY plan_graph is the defect.
    real_root = Path(__file__).resolve().parents[1]
    charter.write_text(
        (real_root / "repo_charter.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    tickets.write_text(
        (real_root / ".agent" / "planning" / "ticket_contracts.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    # Malform the plan_graph: an invalid `paralelizable` value the validator rejects.
    plan_graph.write_text(
        "# Plan Graph\n\n## PLAN-001\n\n"
        "### Impact Simulation\n\n"
        "- PLAN-001-001: paralelizable: bogus-value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    result = run_contract_formation_check(tmp_path)
    assert result.passed is False, (
        f"expected block on malformed CF, got: {result.output}"
    )
    assert result.is_blocking is True


def test_missing_cf_triple_does_not_block(tmp_path: Path, monkeypatch) -> None:
    """Un motor sin CF materializado -> skip no bloqueante (backward-compat)."""
    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    result = run_contract_formation_check(tmp_path)
    assert result.passed is True
    assert "skipped" in result.output.lower()
