"""
Tests for WT-2026-221a: evidence-linked capsule and valid relaunch path.

Covers:
- TP-03: Relaunch valido genera capsula fresh evidence-linked.
- TP-04: Capsula distingue hechos, blockers, hipotesis y siguiente accion.
- TP-05: Reproduccion verificable del camino valido de relaunch.
- TP-06: Capsula no se recicla stale entre relaunches.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from bus.supervisor import SequentialTicketSupervisor


def _write_collab_artifacts(
    collab_dir: Path,
    ticket_id: str = "WT-2026-221a",
) -> None:
    """Write minimal canonical collaboration artifacts."""
    collab_dir.mkdir(parents=True, exist_ok=True)
    (collab_dir / "work_plan.md").write_text(
        "# Work Ticket - " + ticket_id + "\n\n"
        "## Metadata\n"
        "- **ID:** " + ticket_id + "\n"
        "- **Title:** Relaunch CEM\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n",
        encoding="utf-8",
    )
    (collab_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | " + ticket_id + " |\n"
        "\n"
        "## Blockers from Manager\n"
        "- No hacer rediseno grande.\n"
        "- No tocar scope de WT-2026-221b.\n"
        "\n"
        "## Estado del Sistema\n\n"
        "| work_plan.md | IN_PROGRESS |\n",
        encoding="utf-8",
    )
    (collab_dir / "STATE.md").write_text(
        "ACTIVE_TICKET: " + ticket_id + "\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collab_dir / "execution_log.md").write_text(
        "# Execution Log\n\n"
        "**Estado:** IN_PROGRESS\n\n"
        "## " + ticket_id + "\n"
        "- Inicio: 2026-06-04.\n"
        "- Objetivo: implementar capsula evidence-linked.\n"
        "- Estado: IN_PROGRESS.\n"
        "- Pendiente: ejecutar tests.\n",
        encoding="utf-8",
    )


def _write_motor_link(project_root: Path) -> None:
    """Write minimal motor_destination_link.json."""
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(project_root)}, indent=2),
        encoding="utf-8",
    )


def _make_supervisor(project_root: Path) -> SequentialTicketSupervisor:
    """Create supervisor with tmp_path as project root."""
    runtime_dir = project_root / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "events").mkdir(parents=True, exist_ok=True)
    return SequentialTicketSupervisor(
        project_root=project_root,
        collaboration_dir=project_root / ".agent" / "collaboration",
        runtime_dir=runtime_dir,
    )


# ---------------------------------------------------------------------------
# Tests: capsule generation
# ---------------------------------------------------------------------------


def test_capsule_contains_four_sections(tmp_path: Path) -> None:
    """TP-04: La capsula generada contiene los 4 bloques requeridos."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "## 1. Hechos Verificados" in capsule
    assert "## 2. Blockers del Manager" in capsule
    assert "## 3. Hipotesis / Puntos No Verificados" in capsule
    assert "## 4. Siguiente Accion Esperada" in capsule


def test_capsule_contains_ticket_id(tmp_path: Path) -> None:
    """TP-04: La capsula referencia el ticket correcto."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "WT-2026-221a" in capsule


def test_capsule_contains_hechos_from_work_plan(tmp_path: Path) -> None:
    """TP-03: Hechos incluyen metadatos de work_plan.md."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "ID: WT-2026-221a" in capsule
    assert "Title: Relaunch CEM" in capsule
    assert "Estado: APPROVED" in capsule


def test_capsule_contains_blockers_from_turn(tmp_path: Path) -> None:
    """TP-03: Blockers extraidos de TURN.md."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "No hacer rediseno grande" in capsule


def test_capsule_contains_source_attribution(tmp_path: Path) -> None:
    """TP-03: Capsula referencia fuentes canonicas."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "work_plan.md" in capsule
    assert "TURN.md" in capsule
    assert "STATE.md" in capsule
    assert "execution_log.md" in capsule
    assert "bus events" in capsule


def test_capsule_persisted_to_runtime_dir(tmp_path: Path) -> None:
    """TP-03: Capsula se persiste en .agent/runtime/relaunch_capsule.md."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    supervisor._build_relaunch_capsule("WT-2026-221a")
    capsule_path = tmp_path / ".agent" / "runtime" / "relaunch_capsule.md"
    assert capsule_path.exists()
    content = capsule_path.read_text(encoding="utf-8")
    assert "Capsula de Relaunch" in content


def test_capsule_is_fresh_each_call(tmp_path: Path) -> None:
    """TP-06: Capsula se regenera fresh en cada llamada, no se recicla."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule_1 = supervisor._build_relaunch_capsule("WT-2026-221a")
    time.sleep(0.02)  # ensure different timestamp
    capsule_2 = supervisor._build_relaunch_capsule("WT-2026-221a")
    # Timestamps will differ confirming freshness
    assert capsule_1 != capsule_2, "Capsula debe ser fresca en cada llamada"


def test_capsule_includes_siguiente_accion_for_ticket(tmp_path: Path) -> None:
    """TP-04: Siguiente accion referencia el ticket a implementar."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    supervisor = _make_supervisor(tmp_path)

    capsule = supervisor._build_relaunch_capsule("WT-2026-221a")
    assert "Implementar WT-2026-221a" in capsule


# ---------------------------------------------------------------------------
# Tests: capsule generation in valid relaunch flow
# ---------------------------------------------------------------------------


def test_relaunch_generates_capsule_when_topology_valid(tmp_path, monkeypatch) -> None:
    """TP-03: _relaunch_builder genera capsula cuando topologia es valida.
    Verifica que el archivo de capsula existe tras el relaunch."""
    _write_collab_artifacts(tmp_path / ".agent" / "collaboration")
    _write_motor_link(tmp_path)
    runtime_dir = tmp_path / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "events").mkdir(parents=True, exist_ok=True)

    # Create mock launcher script so _resolve_launcher_path succeeds
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "launch_agent_terminals.ps1").write_text(
        "# mock launcher", encoding="utf-8"
    )

    supervisor = _make_supervisor(tmp_path)

    # Mock launcher execution to avoid real subprocess call
    monkeypatch.setattr(
        supervisor,
        "_run_launcher_subprocess",
        lambda cmd: (0, "mocked success", ""),
    )

    # Mock _verify_builder_start to return verified (avoids polling)
    monkeypatch.setattr(
        supervisor,
        "_verify_builder_start",
        lambda **kw: ("builder_started_verified", "builder_lock"),
    )

    result = supervisor._relaunch_builder("WT-2026-221a", trigger_seq=1)
    assert result is True, "relaunch deberia ser exitoso con topologia valida"

    # Capsula debe existir
    capsule_path = tmp_path / ".agent" / "runtime" / "relaunch_capsule.md"
    assert capsule_path.exists(), "capsula debe generarse durante relaunch valido"
    content = capsule_path.read_text(encoding="utf-8")
    assert "## 1. Hechos Verificados" in content
    assert "## 2. Blockers del Manager" in content


def test_relaunch_invalid_does_not_generate_capsule(tmp_path, monkeypatch) -> None:
    """TP-02: Relaunch invalido (topologia fallida) NO genera capsula."""
    supervisor = _make_supervisor(tmp_path)
    # No collab dir + no motor link -> topology fails

    result = supervisor._relaunch_builder("WT-2026-221a", trigger_seq=1)
    assert result is False

    capsule_path = tmp_path / ".agent" / "runtime" / "relaunch_capsule.md"
    assert not capsule_path.exists(), (
        "capsula no debe generarse si topologia es invalida"
    )

    events = supervisor.event_bus.read_events(
        ticket_id="WT-2026-221a",
        event_type="BUILDER_RELAUNCH_ATTEMPTED",
    )
    assert len(events) >= 1
    assert events[-1].payload.get("outcome") == "topology_invalid"


def test_capsule_not_present_after_clean_state(tmp_path: Path) -> None:
    """TP-06: Sin generar capsula, el archivo no existe (no stale)."""
    capsule_path = tmp_path / ".agent" / "runtime" / "relaunch_capsule.md"
    assert not capsule_path.exists(), "no debe haber capsula stale antes del relaunch"


class TestCapsuleHipotesisFromLog:
    """Barrera: _capsule_hipotesis_from_log solo extrae markers canonicos.

    'pendiente' no debe disparar (falso positivo historico).
    'hipotesis:' y '[hipotesis]' deben disparar (contrato canonico).
    """

    def test_pendiente_does_not_trigger(self, tmp_path: Path) -> None:
        """'pendiente' en el log NO debe aparecer en hipotesis de la capsula."""
        log = tmp_path / "execution_log.md"
        log.write_text(
            "**Estado:** IN_PROGRESS\n\n"
            "- Fase 1 completada.\n"
            "- Pendiente: ejecutar rerun global antes de cerrar.\n"
            "- pendiente de contrastar contra contrato de produccion.\n",
            encoding="utf-8",
        )
        result = SequentialTicketSupervisor._capsule_hipotesis_from_log(log)
        assert result == [], f"'pendiente' no debe disparar hipotesis; got: {result}"

    def test_hipotesis_prefix_triggers(self, tmp_path: Path) -> None:
        """'hipotesis:' debe aparecer en hipotesis de la capsula."""
        log = tmp_path / "execution_log.md"
        log.write_text(
            "**Estado:** IN_PROGRESS\n\n"
            "- Fase 1 completada.\n"
            "- hipotesis: fallo puede deberse a cache stale.\n"
            "- Pendiente: rerun global.\n",
            encoding="utf-8",
        )
        result = SequentialTicketSupervisor._capsule_hipotesis_from_log(log)
        assert len(result) == 1
        assert "hipotesis:" in result[0].lower()

    def test_bracket_hipotesis_triggers(self, tmp_path: Path) -> None:
        """'[hipotesis]' debe aparecer en hipotesis de la capsula."""
        log = tmp_path / "execution_log.md"
        log.write_text(
            "- [hipotesis] comportamiento puede variar segun cwd.\n",
            encoding="utf-8",
        )
        result = SequentialTicketSupervisor._capsule_hipotesis_from_log(log)
        assert len(result) == 1

    def test_missing_log_returns_empty(self, tmp_path: Path) -> None:
        """Log ausente devuelve lista vacia, no excepcion ni fallback generico."""
        result = SequentialTicketSupervisor._capsule_hipotesis_from_log(
            tmp_path / "nonexistent.md"
        )
        assert result == []
