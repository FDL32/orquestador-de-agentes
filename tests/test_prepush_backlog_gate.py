"""Regression: WOT-2026-015g — backlog contract gate in closeout-mode.

Background: check_backlog_contract.validate_backlog already detected terminal
tickets (completed/done/closed/absorbed) in the live backlog, but --session-close
never invoked it, so 4 sessions on 2026-06-27 closed green while the live queue
held 10 `completed` rows. This gate wires that detection into run_preflight_check
ONLY in closeout-mode, blocking the close until terminals are archived.

These tests are the barrier: a live backlog with a `completed` row in closeout
mode MUST fail; without the gate (or outside closeout) it must not.
"""

from __future__ import annotations

from pathlib import Path

from scripts.prepush_check import run_backlog_contract_check


LIVE_HEADER = (
    "# Backlog (cola viva)\n\n## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|---|---|---|---|---|---|---|---|\n"
)
ROW_PENDING = "| Alta | WOT-2026-900a | x | s | pending | - | session-test | - |\n"
ROW_COMPLETED = "| Alta | WOT-2026-901a | y | s | completed | - | session-test | - |\n"


def _write_backlog(root: Path, rows: str) -> None:
    p = root / ".agent" / "collaboration" / "backlog.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(LIVE_HEADER + rows, encoding="utf-8")


def test_clean_live_queue_passes(tmp_path: Path) -> None:
    """Solo estados vivos -> gate pasa."""
    _write_backlog(tmp_path, ROW_PENDING)
    result = run_backlog_contract_check(tmp_path)
    assert result.passed is True
    assert result.is_blocking is True


def test_completed_in_live_queue_fails_and_blocks(tmp_path: Path) -> None:
    """BARRERA: un completed en cola viva bloquea el cierre (sin el gate, pasaria)."""
    _write_backlog(tmp_path, ROW_PENDING + ROW_COMPLETED)
    result = run_backlog_contract_check(tmp_path)
    assert result.passed is False
    assert result.is_blocking is True
    assert "WOT-2026-901a" in result.output
    assert "_archive" in result.output  # apunta a la accion correcta


def test_missing_backlog_does_not_block(tmp_path: Path) -> None:
    """Sin backlog.md no hay cola viva que validar -> no bloquea."""
    result = run_backlog_contract_check(tmp_path)
    assert result.passed is True
    assert "skipped" in result.output.lower()


def test_preflight_closeout_mode_includes_gate(tmp_path: Path, monkeypatch) -> None:
    """run_preflight_check en closeout_mode ejecuta el gate; sin el flag, no.

    Aislamos los otros gates (que tocan ruff/git/subprocess) para probar solo que
    el backlog gate se incluye/excluye segun closeout_mode y decide el exit code.
    """
    import scripts.prepush_check as pc

    ok = pc.CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_portable_memory_archive_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_validate_all",
        # WOT-2026-024w: dos gates nuevos de closeout que leen bus/git; se aislan
        # aqui como los demas para probar SOLO la inclusion del backlog gate.
        "run_closeout_reconciliation_check",
        "run_motor_destination_integration_check",
        # WOT-2026-023m(c): CF gate reads the real motor CF triple; isolate it here
        # so this test probes ONLY the backlog gate's inclusion.
        "run_contract_formation_check",
    ):
        monkeypatch.setattr(pc, fn, lambda *a, **k: ok)

    # backlog con completed: en closeout-mode debe bloquear (exit 1)
    _write_backlog(tmp_path, ROW_COMPLETED)
    assert pc.run_preflight_check(tmp_path, closeout_mode=True) == 1
    # fuera de closeout-mode, el gate de backlog NO corre -> exit 0
    assert pc.run_preflight_check(tmp_path, closeout_mode=False) == 0
