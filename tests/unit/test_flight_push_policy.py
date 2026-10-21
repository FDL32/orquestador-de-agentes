"""Probe de la politica de publicacion por vuelo (2026-10-19): el push se hace
UNA sola vez al final de TODOS los tickets, nunca por ticket.

Contrato verificado aqui (barrera de FORMA, no de VERDAD: no detecta si un
vuelo real obedece la norma, solo evita que la clausula se pierda sin querer):

  (a) ``AGENTS.md`` fija la regla transversal (push de vuelo, no de ticket) y
      el estado declarado cuando no hay autorizacion registrada.
  (b) ``prompts/orchestrator_autonomous_ticket_batch.md`` la declara para el
      ejecutor que corre muchos tickets (el caso donde la autonomia se rompe).
  (c) ``prompts/orchestrator_pipeline_codeonly.md`` dice "final de TODOS los
      tickets del vuelo", no solo "final de sesion".
  (d) ``prompts/orchestrator_session_bootstrap.md`` mantiene el UN solo push
      al final de la cola/vuelo.
  (e) ``prompts/orchestrator_session_bootstrap_design.md`` exige que el plan
      de vuelo declare la decision de publicacion POR ADELANTADO.

Rigor proporcional (documentation): la barrera es textual; no hay logica de
produccion que ejecutar.
"""

from __future__ import annotations

from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_AGENTS = _MOTOR_ROOT / "AGENTS.md"
_BATCH = _MOTOR_ROOT / "prompts" / "orchestrator_autonomous_ticket_batch.md"
_CODEONLY = _MOTOR_ROOT / "prompts" / "orchestrator_pipeline_codeonly.md"
_BOOTSTRAP = _MOTOR_ROOT / "prompts" / "orchestrator_session_bootstrap.md"
_DESIGN = _MOTOR_ROOT / "prompts" / "orchestrator_session_bootstrap_design.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agents_md_declares_flight_level_push() -> None:
    text = _read(_AGENTS)
    assert "Push por vuelo: UN solo push al final de TODOS los tickets" in text
    assert "La publicacion es una accion del VUELO, no del ticket." in text
    assert "NO se pushea entre tickets" in text
    assert "PUBLICACION_PENDIENTE_AUTORIZACION" in text


def test_agents_md_declares_process_decision_search() -> None:
    """El guard ``check_process_decision_search`` exige BUSQUEDA-PREVIA cuando
    el artefacto se autodeclara DECISION DE PROCESO (AGENTS.md, WOT-2026-104b)."""
    text = _read(_AGENTS)
    assert "DECISION DE PROCESO: la publicacion se difiere al final del vuelo" in text
    assert "BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO:" in text


def test_batch_executor_declares_flight_level_publication() -> None:
    text = _read(_BATCH)
    assert "Publication is FLIGHT-LEVEL: ONE push at the END of ALL tickets" in text
    assert "never pushes between" in text or "never pushes between tickets" in text
    assert "PUBLICACION_PENDIENTE_AUTORIZACION" in text
    assert "nunca por ticket" in text  # PROMPT-SUMMARY (what:)


def test_codeonly_prompt_says_all_tickets_not_session() -> None:
    text = _read(_CODEONLY)
    assert "al final de TODOS los tickets del vuelo" in text
    assert "PUBLICACION_PENDIENTE_AUTORIZACION" in text


def test_bootstrap_keeps_one_push_at_the_end_of_the_queue() -> None:
    text = _read(_BOOTSTRAP)
    assert "UN solo push al" in text
    assert "final de TODOS los tickets de la cola/vuelo" in text


def test_design_prompt_requires_publication_decision_up_front() -> None:
    text = _read(_DESIGN)
    assert "PUBLICACION: autorizada | pendiente" in text
    assert "UNA sola vez al final de TODOS" in text
