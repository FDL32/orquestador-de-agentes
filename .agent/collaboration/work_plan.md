# Work Plan - WP-2026-170

## Metadata
- **ID:** WP-2026-170
- **Estado:** IN_PROGRESS
- **deliverable_type:** code
- **Titulo:** Fix ConcurrentStateError en supervisor/review bridge
- **Asignado a:** Builder

## Objetivo
Eliminar la reconciliacion de estado mutable desde `_tick()` del review bridge para evitar la carrera OCC con `supervisor_state.json`, manteniendo la deteccion de `READY_FOR_REVIEW`.

## Contexto
- `scripts/manager_review_bridge.py` llama a `supervisor.reconcile_state()` dentro del tick del bridge.
- `bus/supervisor.py` tambien escribe `supervisor_state.json`, asi que ambos procesos compiten por la misma superficie de estado.
- El bridge ya obtiene el ticket activo y el estado de trabajo desde el bus, por lo que no necesita reconciliar el supervisor en cada iteracion.
- El fix debe ser quirurgico: solo eliminar la llamada en `_tick()` y conservar las llamadas de bootstrap en `main()`.

## Decision Arquitectonica
- `scripts/manager_review_bridge.py` deja de llamar `supervisor.reconcile_state()` dentro de `_tick()`.
- Las llamadas de inicializacion en `main()` antes de `--watch` y `--once` permanecen intactas.
- No se introduce un helper read-only nuevo: `_ticket_state()` ya obtiene lo necesario del bus.
- No se toca el algoritmo OCC de `write_artifact_atomic()` ni se amplian retries.

## Non-goals
- No cambiar el contrato de estados del bus.
- No modificar el algoritmo de concurrencia de `bus/supervisor.py`.
- No ocultar el problema aumentando retries o timeouts.
- No introducir nuevas dependencias.

## Fases

### Fase 1: fix quirurgico del bridge
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/manager_review_bridge.py`
- **Accion:** Modificar
- **Descripcion:** Eliminar la llamada a `supervisor.reconcile_state()` de `_tick()` y conservar las llamadas de bootstrap en `main()`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `_tick()` no escribe `supervisor_state.json` y el bridge sigue detectando `READY_FOR_REVIEW`.
- **Si falla:** Restaurar la llamada solo en `main()` y dejar el tick sin reconciliacion.

### Fase 2: tests mecanicos de concurrencia
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_manager_review_bridge.py`, `tests/test_supervisor.py`
- **Accion:** Modificar
- **Descripcion:** Cubrir tres casos: `_tick()` no llama `reconcile_state()`, `_tick()` sigue detectando `READY_FOR_REVIEW` y el flujo mockeado no levanta `ConcurrentStateError`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Los tests verifican la ausencia de llamada al reconcile y la preservacion de la deteccion de estado.
- **Si falla:** Mantener el fix y ajustar solo la cobertura de tests.

## Files Likely Touched
- `scripts/manager_review_bridge.py`
- `tests/test_manager_review_bridge.py`
- `tests/test_supervisor.py`

## Calidad
- `python scripts/run_pytest_safe.py tests/test_manager_review_bridge.py tests/test_supervisor.py`
- `uv run ruff check scripts/manager_review_bridge.py tests/test_manager_review_bridge.py tests/test_supervisor.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- El bridge y el supervisor pueden correr simultaneamente sin `ConcurrentStateError`.
- El bridge sigue detectando `READY_FOR_REVIEW`.
- `_tick()` no llama `supervisor.reconcile_state()`.
- Los tests mecanicos cubren la ausencia de reconcile y la deteccion correcta del estado.
