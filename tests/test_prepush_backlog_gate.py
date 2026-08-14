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
ROW_PENDING = "| Alta | WOT-2026-900a | x deliverable_type: code | s | pending | - | session-test | - |\n"
ROW_COMPLETED = "| Alta | WOT-2026-901a | y deliverable_type: code | s | completed | - | session-test | - |\n"


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


def test_closeout_gate_catches_archived_row_with_live_state(tmp_path: Path) -> None:
    """WOT-2026-026t: el gate de closeout ve la fuga INVERSA, no solo la evidente.

    El caso evidente (un estado terminal en la cola viva) ya lo cubria
    `validate_backlog`. El inverso -- una fila ARCHIVADA que conserva estado vivo,
    o sea trabajo pendiente guardado como historia -- lo detecta
    `validate_archive_states`, y esa funcion se entrego cableada SOLO en la CLI:
    el camino de `--session-close` (el automatizado, donde importa) no la
    invocaba. Lo caso una pasada adversarial externa.

    MUTACION ALCANZABLE: quitar `validate_archive_states(project_root)` de
    `run_backlog_contract_check` -> este test pasa a VERDE con la fila rota, que
    es exactamente el falso verde que el ticket cierra.
    """
    import scripts.prepush_check as pc

    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    # Cola viva bien formada y VACIA de terminales: el defecto no esta aqui.
    (collab / "backlog.md").write_text(
        "## Vista rapida\n\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    # La fuga: archivada pero todavia `pending`.
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Media | WOT-2026-0B1B | titulo | motor/scope | pending | - | origen | - |\n",
        encoding="utf-8",
    )

    result = pc.run_backlog_contract_check(tmp_path)

    assert result.passed is False, "el gate de closeout debe BLOQUEAR la fuga inversa"
    assert result.is_blocking is True
    assert "NON-terminal state 'pending'" in result.output


def test_closeout_gate_catches_terminal_row_without_landing_evidence(
    tmp_path: Path,
) -> None:
    """WOT-2026-054b: CUARTA vez el mismo patron -- guard escrito, guard sin cablear.

    `validate_archive_landing_evidence` se entrego SOLO en la CLI standalone:
    `run_backlog_contract_check` importaba cuatro validadores y este no estaba
    entre ellos, asi que el contrato de landing evidence era una NORMA, no una
    barrera -- literalmente la leccion que el docstring de esa funcion dice
    haber aprendido ya tres veces. Lo caso la lente-lector-FS de un bucle de
    gobierno de 4 lentes (2026-08-14).

    MUTACION ALCANZABLE: quitar `validate_archive_landing_evidence(project_root)`
    de `run_backlog_contract_check` -> este test pasa a VERDE con la fila sin
    evidencia, que es el falso verde que el ticket cierra.
    """
    import scripts.prepush_check as pc

    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "## Vista rapida\n\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    # Fila NUEVA (id fuera del censo legacy) archivada como terminal SIN aterrizaje.
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Media | WOT-2026-0C1C | titulo | motor/scope | completed | - | origen | - |\n",
        encoding="utf-8",
    )

    result = pc.run_backlog_contract_check(tmp_path)

    assert result.passed is False, "una fila terminal sin aterrizaje debe BLOQUEAR"
    assert result.is_blocking is True
    assert "WOT-2026-0C1C" in result.output
    assert "no landing evidence" in result.output


def test_closeout_gate_exempts_censused_legacy_row(tmp_path: Path) -> None:
    """WOT-2026-054b: el baseline legacy exime, pero SOLO el par (id, celda) censado.

    Las 86 filas historicas sin aterrizaje se congelaron por PAR -- forma dict de
    `_ARCHIVE_ARITY_LEGACY_BASELINE`, no frozenset de ids -- porque un id pelado
    eximiria ese ticket PARA SIEMPRE: reescribir la fila con otra ausencia
    distinta pasaria en silencio. Este test pinea ambas mitades del contrato.
    """
    import scripts.check_backlog_contract as cbc
    import scripts.prepush_check as pc

    censused_id, censused_cell = next(
        (k, v) for k, v in cbc._LANDING_EVIDENCE_LEGACY_BASELINE.items() if v == "-"
    )

    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "## Vista rapida\n\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    archive = collab / "_archive" / "backlog_done.md"

    # (a) el par censado EXACTO -> exento.
    archive.write_text(
        f"| Media | {censused_id} | t | motor/s | completed | - | origen | {censused_cell} |\n",
        encoding="utf-8",
    )
    assert pc.run_backlog_contract_check(tmp_path).passed is True

    # (b) MISMO id, celda REESCRITA a otra ausencia -> el baseline NO lo cubre.
    archive.write_text(
        f"| Media | {censused_id} | t | motor/s | completed | - | origen | pendiente |\n",
        encoding="utf-8",
    )
    result = pc.run_backlog_contract_check(tmp_path)
    assert result.passed is False, "cambiar la celda censada debe expulsar del baseline"
    assert censused_id in result.output
