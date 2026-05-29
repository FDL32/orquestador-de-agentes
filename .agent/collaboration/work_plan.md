# Work Plan - WP-2026-172

## Metadata
- **ID:** WP-2026-172
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Prevent Builder relaunch on HANDOFF_BLOCKED and tolerate PROJECT.md as live surface
- **Asignado a:** Builder

## Objetivo
Evitar el relanzado automatico del Builder cuando el trigger de requeue ya fue seguido por un `HANDOFF_BLOCKED`, y tratar `PROJECT.md` como superficie viva tolerada por el pre-handoff guard para que el cierre del ciclo no genere falsos positivos de arbol sucio.

## Contexto
- `scripts/pre_handoff_guard.py` considera superficies vivas del runtime, pero `PROJECT.md` aun puede ensuciar el handoff cuando el Builder lo actualiza como parte del cierre del ciclo.
- `bus/supervisor.py` relanza Builder de forma automatica cuando detecta requeue, pero no distingue con suficiente precision entre un bloqueo de contrato (`HANDOFF_BLOCKED`) y un crash o timeout real.
- El trigger de requeue puede aparecer antes del `HANDOFF_BLOCKED`; la supresion debe mirar eventos posteriores al trigger, no solo el ultimo evento visible.

## Decision Arquitectonica
- `scripts/pre_handoff_guard.py` añade `PROJECT.md` a `LIVE_SURFACES_REL` para que el guard no lo considere dirty_tree durante `--mark-ready`.
- `bus/supervisor.py` debe comprobar, antes de confirmar el relanzado, si existe algun `HANDOFF_BLOCKED` con `sequence_number > requeue_trigger_sequence`; si existe, suprime el relanzado en ambas rutas de requeue (`run_once()` y `_bootstrap_requeue_if_needed()`).
- El supervisor sigue relanzando ante timeout, lock stale o ausencia de evidencia de cierre, pero no cuando el Builder ya emitio `HANDOFF_BLOCKED` posterior al trigger.
- No se modifica el contrato de `--mark-ready`; solo se ajusta la tolerancia de superficie viva y la politica de relanzado.
- No se introducen nuevos estados de ticket ni nuevas dependencias.

## Non-goals
- No cambiar el contrato de `--mark-ready` ni su secuencia de eventos.
- No tocar la logica de OCC de `write_artifact_atomic()`.
- No relajar la deteccion de dirty_tree mas alla de `PROJECT.md` como superficie viva.
- No introducir reintentos extra ni timeouts mayores.

## Fases

### Fase 1: superficie viva PROJECT.md
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/pre_handoff_guard.py`
- **Accion:** Modificar
- **Descripcion:** Añadir `PROJECT.md` a `LIVE_SURFACES_REL` para que el guard lo tolere como superficie viva durante el handoff. El archivo sigue actualizandose como parte del ciclo, pero no debe bloquear `--mark-ready` por dirty_tree cuando sea la unica diferencia relevante.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** Un cambio aislado en `PROJECT.md` no dispara `dirty_tree` en el pre-handoff guard si el resto del arbol esta limpio.
- **Si falla:** Revertir la tolerancia de `PROJECT.md` y mantener el comportamiento actual.

### Fase 2: relaunch condicional del supervisor
- **Tipo:** TAREA AGENTE
- **Archivos:** `bus/supervisor.py`
- **Accion:** Modificar
- **Descripcion:** Ajustar la logica de requeue en `run_once()` y en `_bootstrap_requeue_if_needed()` para que el supervisor no dispare `BUILDER_RELAUNCH_ATTEMPTED` cuando exista algun `HANDOFF_BLOCKED` con `sequence_number > requeue_trigger_sequence`. El relanzado debe quedar reservado para crash, timeout o ausencia de evidencia de cierre, no para bloqueo de contrato. Si se suprime el relanzado, emitir un evento diagnostico que deje trazabilidad del bloqueo posterior al trigger.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un ticket que termina en `HANDOFF_BLOCKED` posterior al trigger de requeue no genera relanzado automatico; un timeout o ausencia de actividad relevante sigue pudiendo relanzar Builder.
- **Si falla:** Mantener el comportamiento actual de relanzado y diferir la discriminacion de `HANDOFF_BLOCKED` a un ticket posterior.

### Fase 3: cobertura mecanica
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_pre_handoff_guard.py`, `tests/test_supervisor.py`
- **Accion:** Modificar
- **Descripcion:** Cubrir dos escenarios: (1) `PROJECT.md` cambia pero el guard no debe bloquear; (2) un `HANDOFF_BLOCKED` posterior al trigger no debe disparar relanzado automatico, mientras que un caso de timeout/crash sigue relanzando. Los tests deben verificar tambien que el flujo valido sigue intacto.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Los tests reproducen la tolerancia de `PROJECT.md` y la exclusion de relanzado tras `HANDOFF_BLOCKED`.
- **Si falla:** Conservar el fix principal y limitar la cobertura a uno de los dos comportamientos.

## Files Likely Touched
- `scripts/pre_handoff_guard.py`
- `bus/supervisor.py`
- `tests/test_pre_handoff_guard.py`
- `tests/test_supervisor.py`

## Calidad
- `python scripts/run_pytest_safe.py tests/test_pre_handoff_guard.py tests/test_supervisor.py`
- `uv run ruff check scripts/pre_handoff_guard.py bus/supervisor.py tests/test_pre_handoff_guard.py tests/test_supervisor.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `PROJECT.md` se trata como superficie viva tolerada por el pre-handoff guard.
- `HANDOFF_BLOCKED` posterior al trigger de requeue no provoca relanzado automatico del Builder.
- `BUILDER_RELAUNCH_ATTEMPTED` sigue ocurriendo solo ante escenarios de crash/timeout o falta de evidencia de cierre.
- Los tests cubren la superficie viva y la exclusion de relanzado.
