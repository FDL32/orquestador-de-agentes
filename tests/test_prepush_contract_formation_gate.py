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
from scripts.prepush_check import (
    run_contract_formation_check,
    run_workspace_contract_formation_check,
)


# WOT-2026-026l parte A: the motor CF gate (run_contract_formation_check) only
# ever validated the MOTOR triple; the workspace (repo_destino) ticket_contracts.md
# -- where 72 contracts and 20 live CF errors sit -- was NEVER looked at. That is
# the scope hole 026l names ("barrera del alcance, no solo del mecanismo"). This
# sibling check extends coverage to the workspace surface as an INFORMATIONAL WARN
# (passed=False + is_blocking=False), because the historical debt is not cleaned
# yet (part B) and blocking would paralyse every close. The WARN is specific:
# it names the file, the error count, and the owner sub-ticket.
#
# CRITICAL contract (Codex contract-audit): in this runner, run_preflight_check
# prints result.output ONLY when `not result.passed` (prepush_check.py). A WARN
# modelled as passed=True would be INVISIBLE -- the very invisible-debt failure
# 026l fights. So WARN == passed=False + is_blocking=False, never passed=True.


def _valid_ws_contract() -> str:
    """A minimal workspace ticket_contracts.md that passes CF (terminal + trace)."""
    return (
        "# Ticket Contracts\n\n"
        "## T-999Z-001 -- ejemplo terminal limpio\n\n"
        "- **status:** completed\n"
        "- closed: 2026-07-21 commit:deadbee\n"
    )


def _invalid_ws_contract() -> str:
    """A workspace ticket_contracts.md with a REAL CF error (live contract, no
    status) -- the validator rejects it (not a loose text assert)."""
    return (
        "# Ticket Contracts\n\n"
        "## T-888Y-001 -- contrato vivo sin status (error CF real)\n\n"
        "- **deliverable_type:** code\n"
    )


def _write_ws_tickets(project_root: Path, body: str) -> Path:
    fp = project_root / ".agent" / "planning" / "ticket_contracts.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(body, encoding="utf-8")
    return fp


def test_workspace_cf_debt_warns_not_blocks(tmp_path: Path, monkeypatch) -> None:
    """A workspace ticket_contracts.md with a real CF error -> WARN: passed=False
    (so the output PRINTS), is_blocking=False (so it never forces exit 1). The
    WARN names the file, the error count, and the owner sub-ticket.

    MUTATION with teeth: a workspace with the SAME structure but VALID contract
    emits no WARN (test_workspace_cf_clean_no_warn). Reverting the extension
    (returning a blanket passed=True) would make this test fail on the printed
    output assertions."""
    motor = tmp_path / "motor"
    motor.mkdir()
    ws = tmp_path / "destino"
    ws.mkdir()
    monkeypatch.setattr(pc, "_MOTOR_ROOT", motor)
    _write_ws_tickets(ws, _invalid_ws_contract())

    result = run_workspace_contract_formation_check(ws)
    assert result.passed is False, (
        "a workspace with live CF debt must surface (passed=False) so the runner "
        f"PRINTS the output; got passed=True which hides it: {result.output}"
    )
    assert result.is_blocking is False, (
        "part A is a WARN while part B (historical hygiene) is pending: it must "
        "NOT block the close"
    )
    assert "ticket_contracts.md" in result.output
    assert "error" in result.output.lower()
    assert "026m" in result.output, (
        "the WARN must name the owner sub-ticket (WOT-2026-026m) so it is "
        "accionable, not anonymous noise"
    )


def test_workspace_cf_clean_no_warn(tmp_path: Path, monkeypatch) -> None:
    """MUTATION pair: a workspace whose ticket_contracts.md is CF-clean emits NO
    WARN (passed=True). This is what makes the debt test non-tautological: the
    same code path, one valid vs one invalid contract, flips the verdict."""
    motor = tmp_path / "motor"
    motor.mkdir()
    ws = tmp_path / "destino"
    ws.mkdir()
    monkeypatch.setattr(pc, "_MOTOR_ROOT", motor)
    _write_ws_tickets(ws, _valid_ws_contract())

    result = run_workspace_contract_formation_check(ws)
    assert result.passed is True, f"a CF-clean workspace must not warn: {result.output}"
    assert result.is_blocking is False


def test_workspace_check_skips_when_project_root_is_motor(
    tmp_path: Path, monkeypatch
) -> None:
    """When project_root == _MOTOR_ROOT (dogfooding the motor itself, no separate
    destino), the workspace check must SKIP: that ticket_contracts.md is already
    validated inside the motor triple by run_contract_formation_check. Resolving
    both paths avoids a false 'distinct' from casing/symlinks (Codex Q1)."""
    motor = tmp_path / "motor"
    (motor / ".agent" / "planning").mkdir(parents=True)
    _write_ws_tickets(motor, _invalid_ws_contract())
    monkeypatch.setattr(pc, "_MOTOR_ROOT", motor)

    result = run_workspace_contract_formation_check(motor)
    assert result.passed is True, (
        "project_root == motor must skip the workspace check (already covered by "
        f"the motor triple), not double-report: {result.output}"
    )
    assert "skip" in result.output.lower()


def test_workspace_check_skips_when_no_ticket_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    """A destino without a ticket_contracts.md -> skip (nothing to validate)."""
    motor = tmp_path / "motor"
    motor.mkdir()
    ws = tmp_path / "destino"
    ws.mkdir()
    monkeypatch.setattr(pc, "_MOTOR_ROOT", motor)
    result = run_workspace_contract_formation_check(ws)
    assert result.passed is True
    assert "skip" in result.output.lower()


def test_motor_cf_valid_passes() -> None:
    """El CF REAL del motor esta bien formado -> gate pasa (0 structure errors).

    WOT-2026-024h: el conjunto es VARIABLE (ticket_contracts.md ya no se versiona);
    lo que se afirma es que lo que EXISTE valida, no que existan los tres.
    """
    result = run_contract_formation_check(Path(__file__).resolve().parents[1])
    assert result.passed is True
    assert result.is_blocking is True
    assert "0 structure errors" in result.output


def test_charter_and_plan_still_validated_without_tickets(
    tmp_path: Path, monkeypatch
) -> None:
    """WOT-2026-024h (anti falso-verde): sin ticket_contracts.md, charter y
    plan_graph SIGUEN validandose.

    Es la mitad que impide que la retirada del seed (024h) apague de rebote la
    barrera que 023m(c) acababa de encender: con la condicion AND original, un
    motor sin tickets devolvia 'skipped' y un plan_graph MALFORMADO pasaba el
    cierre sin que nadie lo mirase. Aqui no hay tickets Y el plan_graph esta roto:
    el gate DEBE bloquear.
    """
    real_root = Path(__file__).resolve().parents[1]
    (tmp_path / "repo_charter.md").write_text(
        (real_root / "repo_charter.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "plan_graph.md").write_text(
        "# Plan Graph\n\n## PLAN-001\n\n"
        "### Impact Simulation\n\n"
        "- PLAN-001-001: paralelizable: bogus-value\n",
        encoding="utf-8",
    )
    assert not (tmp_path / ".agent" / "planning" / "ticket_contracts.md").exists()
    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)

    result = run_contract_formation_check(tmp_path)

    assert result.passed is False, (
        "sin tickets, un plan_graph malformado debe SEGUIR bloqueando; "
        f"got: {result.output}"
    )
    assert "skipped" not in result.output.lower()


def test_malformed_cf_blocks(tmp_path: Path, monkeypatch) -> None:
    """BARRERA: si el validador reporta errores, el gate bloquea el cierre.

    Redirige _MOTOR_ROOT a un tmp con un plan_graph MALFORMADO (paralelizable
    invalido en un bloque no-terminal). Sin el gate, ese plan_graph roto no
    rompia nada; con el gate, bloquea.
    """
    charter = tmp_path / "repo_charter.md"
    plan_graph = tmp_path / "plan_graph.md"
    # Copy the real (valid) charter so ONLY plan_graph is the defect.
    real_root = Path(__file__).resolve().parents[1]
    charter.write_text(
        (real_root / "repo_charter.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # WOT-2026-024h: the motor no longer versions ticket_contracts.md, so the
    # fixture no longer copies one. Only plan_graph is the defect under test.
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
