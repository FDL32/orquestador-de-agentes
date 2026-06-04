"""
Tests for WT-2026-221a: topology verification before Builder relaunch.

Covers:
- TP-01: Seam real de relaunch y verificacion de topologia.
- TP-02: Root/topologia invalidos bloquean relaunch con evidencia observable.
- TP-05: Reproduccion verificable de la familia seq 578.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bus.supervisor import SequentialTicketSupervisor, SupervisorState


def _write_collab_artifacts(
    collab_dir: Path,
    ticket_id: str = "WT-2026-221a",
    status: str = "APPROVED",
) -> None:
    """Write minimal canonical collaboration artifacts for testing."""
    collab_dir.mkdir(parents=True, exist_ok=True)

    # work_plan.md
    (collab_dir / "work_plan.md").write_text(
        "# Work Ticket - " + ticket_id + "\n\n"
        "## Metadata\n"
        "- **ID:** " + ticket_id + "\n"
        "- **Estado:** " + status + "\n"
        "- **deliverable_type:** code\n",
        encoding="utf-8",
    )

    # TURN.md
    (collab_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | " + ticket_id + " |\n"
        "| **Tipo** | IMPLEMENT |\n"
        "| **Accion** | IMPLEMENT |\n"
        "\n"
        "## Blockers from Manager\n"
        "- No hacer rediseno grande.\n"
        "\n"
        "## Estado del Sistema\n\n"
        "| Archivo | Estado |\n"
        "|---------|--------|\n"
        "| work_plan.md | IN_PROGRESS |\n",
        encoding="utf-8",
    )

    # STATE.md
    (collab_dir / "STATE.md").write_text(
        "ACTIVE_TICKET: " + ticket_id + "\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )

    # execution_log.md
    (collab_dir / "execution_log.md").write_text(
        "# Execution Log\n\n"
        "**Estado:** IN_PROGRESS\n\n"
        "## " + ticket_id + "\n"
        "- Inicio: 2026-06-04.\n"
        "- Objetivo: verificar topologia.\n",
        encoding="utf-8",
    )


def _write_motor_link(project_root: Path, motor_root: Path | None = None) -> Path:
    """Write a minimal motor_destination_link.json for testing."""
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link_path = config_dir / "motor_destination_link.json"
    target = str(motor_root or project_root)
    link_path.write_text(
        json.dumps({"motor_root": target}, indent=2),
        encoding="utf-8",
    )
    return link_path


def _make_supervisor(project_root: Path) -> SequentialTicketSupervisor:
    """Create a SequentialTicketSupervisor with tmp_path as project_root."""
    runtime_dir = project_root / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    # Create bus events directory (needed by EventBus)
    (runtime_dir / "events").mkdir(parents=True, exist_ok=True)
    return SequentialTicketSupervisor(
        project_root=project_root,
        collaboration_dir=project_root / ".agent" / "collaboration",
        runtime_dir=runtime_dir,
    )


# ---------------------------------------------------------------------------
# Tests: topology verification
# ---------------------------------------------------------------------------


def test_topology_pass_when_all_present(tmp_path: Path) -> None:
    """TP-02: Topologia valida pasa la verificacion."""
    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-221a")
    _write_motor_link(tmp_path, motor_root=tmp_path)
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert is_valid, f"Expected valid topology, got: {msg}"
    assert msg == ""


def test_topology_fail_missing_collaboration(tmp_path: Path) -> None:
    """TP-02: Falta directorio collaboration -> invalido."""
    _write_motor_link(tmp_path, motor_root=tmp_path)
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert not is_valid
    assert "Collaboration dir missing" in msg


def test_topology_pass_missing_work_plan(tmp_path: Path) -> None:
    """TP-02: Falta work_plan.md permite pasar (artefacto opcional)."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    _write_motor_link(tmp_path, motor_root=tmp_path)
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert is_valid, f"Missing optional artifact should pass: {msg}"


def test_topology_fail_empty_work_plan(tmp_path: Path) -> None:
    """TP-02: work_plan.md existente pero vacio -> invalido."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text("", encoding="utf-8")
    (collab / "TURN.md").write_text("content", encoding="utf-8")
    (collab / "STATE.md").write_text("content", encoding="utf-8")
    _write_motor_link(tmp_path, motor_root=tmp_path)
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert not is_valid
    assert "work_plan.md is empty" in msg


def test_topology_pass_missing_motor_link(tmp_path: Path) -> None:
    """TP-02: Sin motor_destination_link.json permite pasar (Model A / test)."""
    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-221a")
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert is_valid, f"Missing motor link should pass: {msg}"


def test_topology_fail_invalid_motor_link(tmp_path: Path) -> None:
    """TP-02: motor_destination_link.json con motor_root inexistente -> invalido."""
    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-221a")
    # Write link pointing to non-existent root
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "motor_destination_link.json").write_text(
        '{"motor_root": "Z:\\\\nonexistent_path_xyz"}', encoding="utf-8"
    )
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert not is_valid
    assert "motor_root" in msg.lower() or "Motor root" in msg


def test_topology_fail_ticket_mismatch(tmp_path: Path) -> None:
    """TP-02/TP-05: Ticket en STATE.md no coincide con relaunch -> invalido.
    Reproduce la familia de error seq 578: relaunch intentado con ticket
    distinto al que el proyecto destino tiene activo."""
    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-208")  # different ticket
    _write_motor_link(tmp_path, motor_root=tmp_path)
    supervisor = _make_supervisor(tmp_path)

    is_valid, msg = supervisor._verify_relaunch_topology("WT-2026-221a")
    assert not is_valid
    assert "Ticket mismatch" in msg
    assert "WT-2026-208" in msg


# ---------------------------------------------------------------------------
# Tests: integration into _relaunch_builder (via topology seam)
# ---------------------------------------------------------------------------


def test_relaunch_blocks_on_invalid_topology(tmp_path: Path) -> None:
    """TP-02: _relaunch_builder retorna False y emite topology_invalid
    cuando la topologia es invalida (sin collaboration)."""
    supervisor = _make_supervisor(tmp_path)
    # No motor link -> topology will fail

    result = supervisor._relaunch_builder("WT-2026-221a", trigger_seq=1)
    assert result is False, "relaunch deberia bloquearse con topologia invalida"

    # Verify topology_invalid event was emitted
    events = supervisor.event_bus.read_events(
        ticket_id="WT-2026-221a",
        event_type="BUILDER_RELAUNCH_ATTEMPTED",
    )
    assert len(events) >= 1
    last_event = events[-1]
    assert last_event.payload.get("outcome") == "topology_invalid"
    assert "Topology invalid" in last_event.payload.get("stderr_tail", "")
    assert last_event.payload.get("launcher_exit_code") == -1
    assert last_event.payload.get("verify_signal") == "none"


# ---------------------------------------------------------------------------
# Tests: WT-2026-224a — Overlap guard via _builder_alive()
# ---------------------------------------------------------------------------


def test_relaunch_suppressed_when_lock_fresh(tmp_path: Path) -> None:
    """TP-02, TP-05: _relaunch_builder suprime relaunch cuando el lock
    esta fresco y no hay BUILDER_EXIT posterior.

    Reproduce el overlap: round N sigue activo con builder_lock.txt
    recien escrito, supervisor detecta la senal y NO spawnear un
    Builder nuevo. Verifica que el evento lleve outcome=skipped_alive
    y que nunca se ejecute la topologia ni el launcher.
    """
    import json

    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-224a")

    supervisor = _make_supervisor(tmp_path)
    supervisor.save_state(
        SupervisorState(
            active_ticket="WT-2026-224a",
            loop_current_round=5,
        )
    )

    # Write builder_lock.txt with fresh started_at (10 seconds ago),
    # no BUILDER_EXIT event on the bus -> _builder_alive() returns True
    lock = supervisor.runtime_dir / "builder_lock.txt"
    started_at = datetime.now(timezone.utc).isoformat()
    lock.write_text(
        json.dumps(
            {
                "ticket_id": "WT-2026-224a",
                "started_at": started_at,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Call _relaunch_builder — should suppress immediately
    result = supervisor._relaunch_builder("WT-2026-224a", trigger_seq=42)

    # Builder alive is not an error; returns True
    assert result is True

    events = supervisor.event_bus.read_events(
        ticket_id="WT-2026-224a",
        event_type="BUILDER_RELAUNCH_ATTEMPTED",
    )
    assert len(events) >= 1
    last_event = events[-1]
    payload = last_event.payload
    assert payload["outcome"] == "skipped_alive", (
        f"Expected skipped_alive, got {payload.get('outcome')}"
    )
    assert payload["round"] == 5
    assert payload.get("launcher_exit_code") is None
    assert payload.get("verify_signal") == "none"
    assert payload.get("trigger_seq") == 42
    assert "Builder alive" in payload.get("stderr_tail", "")

    # Verify log was persisted
    assert (supervisor.runtime_dir / "logs" / "launcher_last.log").exists()


def test_relaunch_proceeds_when_builder_dead(tmp_path: Path) -> None:
    """TP-03: _relaunch_builder NO suprime el relaunch cuando no hay
    builder_lock.txt (Builder muerto).

    El supervisor debe pasar la barrera de _builder_alive() y
    continuar hacia la verificacion de topologia o lanzamiento.
    """
    collab = tmp_path / ".agent" / "collaboration"
    _write_collab_artifacts(collab, ticket_id="WT-2026-224a")
    _write_motor_link(tmp_path, motor_root=tmp_path)

    supervisor = _make_supervisor(tmp_path)
    supervisor.save_state(
        SupervisorState(
            active_ticket="WT-2026-224a",
            loop_current_round=1,
        )
    )

    # NO builder_lock.txt — _builder_alive() devuelve False.
    # Call _relaunch_builder: the barrier does NOT block because
    # _builder_alive() == False. The code proceeds to topology check
    # (which passes with valid setup) then to launcher execution.
    # The result may be False (pwsh not found in test env), but the
    # key assertion is that the event outcome is NOT skipped_alive.
    supervisor._relaunch_builder("WT-2026-224a", trigger_seq=7)

    events = supervisor.event_bus.read_events(
        ticket_id="WT-2026-224a",
        event_type="BUILDER_RELAUNCH_ATTEMPTED",
    )
    assert len(events) >= 1
    last_event = events[-1]
    payload = last_event.payload
    assert payload["outcome"] != "skipped_alive", (
        "relaunch should NOT be skipped when builder is dead"
    )
    assert payload["round"] == 1
    assert payload.get("trigger_seq") == 7
