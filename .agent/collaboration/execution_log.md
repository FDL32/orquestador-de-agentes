# Execution Log - WP-2026-172

## Metadata
- **ID:** WP-2026-172
- **Estado:** COMPLETED
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Prevent Builder relaunch on HANDOFF_BLOCKED and tolerate PROJECT.md as live surface

## Fases
- Phase 1: superficie viva PROJECT.md.
- Phase 2: relaunch condicional del supervisor.
- Phase 3: cobertura mecanica.

## Registro de Implementacion
- `PROJECT.md` se trata como una superficie viva del ciclo y no debe ensuciar el handoff por si solo.
- `HANDOFF_BLOCKED` indica que el Builder llego al contrato de entrega pero quedo bloqueado por higiene, no que haya caido.
- El supervisor distingue bloqueo de contrato de un crash o timeout real antes de relanzar.

## Evidencia
- Phase 1: `PROJECT.md` añadido a `LIVE_SURFACES_REL` en `scripts/pre_handoff_guard.py`.
- Phase 2: `_has_handoff_blocked_after_sequence()` añadido y usado en `run_once()` / `_bootstrap_requeue_if_needed()` para emitir `RELAUNCH_SUPPRESSED` cuando corresponde.
- Phase 3: tests nuevos en `test_supervisor.py` y `test_pre_handoff_guard.py`.
- Quality gates: ruff OK, pytest 106/106, validation OK.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_pre_handoff_guard.py tests/test_supervisor.py`
- `uv run ruff check scripts/pre_handoff_guard.py bus/supervisor.py tests/test_pre_handoff_guard.py tests/test_supervisor.py`
- `python .agent/agent_controller.py --validate --json --force`
