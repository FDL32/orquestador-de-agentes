"""Probe de WOT-2026-104n: un Builder/subagente NUNCA parchea un guard bloqueante
ni borra la evidencia de sus propios bloqueos.

Contrato DoD de la ficha (cuatro clausulas verificadas aqui):
  (a) `builder_invocation_contract.md` prohibe textualmente parchear/monkeypatchear
      el mecanismo de un guard al toparse con un bloqueo, y cita el incidente real.
  (b) prohibe textualmente borrar/truncar `.agent/runtime/events/events.jsonl`.
  (c) `dispatch_builder.template.md` apunta por REFERENCIA a esa seccion (X-09),
      sin redeclarar las prohibiciones completas.
  (d) `orchestrator_launch_builder.md` (M2) cita el incidente como ejemplo de que
      un `git add -A` puede parecer inocuo cuando el trabajo real vive en rutas
      gitignoradas.

Rigor proporcional (ticket deliverable_type: documentation): no hay logica de
produccion que ejecutar, asi que la barrera es textual -- regresion si alguien
borra estas clausulas sin querer. No es una barrera de VERACIDAD (no detecta si
un Builder real obedece la norma), es barrera de FORMA sobre el contrato.
"""

from __future__ import annotations

from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = _MOTOR_ROOT / "prompts" / "builder_invocation_contract.md"
_DISPATCH_TEMPLATE = (
    _MOTOR_ROOT / "prompts" / "kilo_trio_dispatch" / "dispatch_builder.template.md"
)
_LAUNCH_BUILDER = _MOTOR_ROOT / "prompts" / "orchestrator_launch_builder.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_contract_prohibits_patching_a_blocking_guard() -> None:
    text = _read(_CONTRACT)
    assert "WOT-2026-104n" in text
    assert (
        "Nunca parchear, monkeypatchear ni modificar el mecanismo de un guard" in text
    )
    assert "DETENTE y reporta" in text


def test_contract_prohibits_deleting_events_bus_log() -> None:
    text = _read(_CONTRACT)
    assert "Nunca borrar, truncar ni reescribir" in text
    assert ".agent/runtime/events/events.jsonl" in text
    assert "salvo instruccion EXPLICITA del orquestador" in text


def test_contract_prohibits_scope_creep_past_the_scoped_mandate() -> None:
    text = _read(_CONTRACT)
    assert "Un mandato ACOTADO acota el alcance, no solo la tarea" in text


def test_dispatch_template_points_by_reference_without_redeclaring() -> None:
    text = _read(_DISPATCH_TEMPLATE)
    assert "cid-builder-invocation-v1" in text
    assert "Sección 3" in text
    assert "WOT-2026-104n" in text
    # X-09: el template REMITE, no copia las tres prohibiciones completas.
    assert (
        "Nunca parchear, monkeypatchear ni modificar el mecanismo de un guard"
        not in text
    )


def test_m2_reinforced_with_gitignored_evidence_incident() -> None:
    text = _read(_LAUNCH_BUILDER)
    assert "WOT-2026-104n" in text
    assert "GITIGNORADAS" in text
    assert "git status --short --ignored" in text
