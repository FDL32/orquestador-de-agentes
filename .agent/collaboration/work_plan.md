# Plan de Trabajo: WP-2026-124 - Drift canonico del bus

## Metadata
- **ID:** WP-2026-124
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-05-21
- **Prioridad:** HIGH
- **Asignado a:** Builder
- **Backend:** OpenCode
- **Tipo:** IMPLEMENTATION

---

## Objetivo

Eliminar el drift entre el bus canonico y las proyecciones de colaboracion.
Un `REVIEW_DECISION` nunca debe poder existir sin su `STATE_CHANGED`
correspondiente, y los guards deben leer el estado derivado del bus como
autoridad, no `execution_log.md`.

## Contexto

WP-2026-123 quedo atascado en `inspect` (HUMAN_GATE derivado) sin cerrarse
canonicamente: el bus salto de su `REVIEW_DECISION inspect` directo a otro
ticket, sin `STATE_CHANGED`. Ese es exactamente el agujero a cerrar: `inspect`
queda hoy como derivacion del bus y deja `STATE.md` / `execution_log.md`
desalineados.

Regla unica de este WP (sin auto-healing silencioso):

- el bus manda;
- las proyecciones se materializan desde el bus;
- si bus y proyeccion divergen, se aborta o se pide intervencion humana.

## Decision arquitectonica (opcion B)

La materializacion compartida NO se mueve a un modulo nuevo y NO se importa
entre paquetes (evita el import circular: `bus/review_bridge.py` no puede
importar `agent_controller.py`, que a su vez importa `bus/*`).

En su lugar:

- La materializacion canonica (emitir `STATE_CHANGED` + sincronizar
  `STATE.md` / `TURN.md` / `execution_log.md`) vive en `agent_controller.py`,
  donde ya estan `update_log_status` y `update_turn_file` y la ruta de
  `changes` (`_handle_request_changes`).
- `scripts/manager_review_bridge.py` la **dispara por CLI**, invocando
  `agent_controller.py` como subproceso — exactamente igual que `changes` ya
  hace hoy. Cero import entre paquetes, cero modulo nuevo.
- Se anade un flag `--escalate-human-gate --ticket WP-XXXX` a
  `agent_controller.py` para la ruta `inspect`: emite `STATE_CHANGED ->
  HUMAN_GATE` (actor `SUPERVISOR`) y sincroniza las 3 proyecciones. NO toca
  el contador de rejections (`inspect` no es un rechazo del Manager).

## Contracto de alcance

Cubre el bloque drift/bus canonico:

- materializacion canonica de transiciones para `approve` / `changes` /
  `inspect` por la misma ruta CLI;
- sincronizacion de `STATE.md` / `TURN.md` / `execution_log.md` desde el bus;
- guards (`--mark-ready`, `--request-changes`) que leen el estado derivado
  del bus;
- asercion post-ciclo bus == proyeccion;
- test e2e de regresion del ciclo review -> transition -> projection;
- fix del test roto pre-existente `test_emit_fail_safe_on_review_decision`.

Queda **fuera** de este WP la higiene de transporte de `inspect` (filtrado de
basura del backend en `review_queue.md`) y el health check pre-ciclo. Eso es
un WP posterior.

## Files Likely Touched

### Codigo

- `.agent/agent_controller.py`
- `scripts/manager_review_bridge.py`
- `bus/review_bridge.py`

### Documentacion / Estado

- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WP-2026-124.md`
- `.agent/collaboration/AUDIT_WP-2026-124.md`
- `PROJECT.md`

### Tests

- `tests/test_review_bridge.py`
- `tests/test_manager_review_bridge.py`
- `tests/unit/test_bus_drift_detection.py`
- `tests/unit/test_bus_emission_on_mark_ready.py`
- `tests/test_review_cycle_e2e.py`

## Plan

### Fase 1: Materializacion canonica via CLI

- Extraer la materializacion de estado de `_handle_request_changes` a una
  funcion interna reutilizable de `agent_controller.py` (sin moverla de
  modulo).
- Anadir el flag `--escalate-human-gate --ticket WP-XXXX`: emite
  `STATE_CHANGED -> HUMAN_GATE` (actor `SUPERVISOR`) + sincroniza las 3
  proyecciones. Sin tocar el contador de rejections.
- Hacer que `scripts/manager_review_bridge.py`, al recibir `inspect`, dispare
  `agent_controller.py --escalate-human-gate` por subproceso (misma mecanica
  que `changes`). Garantiza que todo `REVIEW_DECISION` deje su `STATE_CHANGED`.

### Fase 2: Guards leen el bus

- `--mark-ready` y `--request-changes` consultan el estado derivado del bus
  (`StateMachine.derive_state_from_events`), no `execution_log.md`.
- Las proyecciones quedan como conveniencia humana, no como autoridad.

### Fase 3: Asercion post-ciclo

- Tras cada ciclo de review, verificar que el estado derivado del bus coincide
  con el de las proyecciones. Si divergen, fallar ruidoso (no auto-corregir).

### Fase 4: Validacion

- Anadir `tests/test_review_cycle_e2e.py`: ciclo review -> decision -> bus ->
  proyecciones, para `approve`, `changes` e `inspect`.
- Arreglar `test_emit_fail_safe_on_review_decision` (roto pre-existente en
  `tests/test_review_bridge.py`).
- `ruff check .`, `pytest` del slice, `agent_controller.py --validate`.

## Criterios de Aceptacion

- [ ] `inspect` emite `STATE_CHANGED -> HUMAN_GATE` via CLI; no queda como
      decision fantasma.
- [ ] `approve`, `changes` e `inspect` materializan por la misma ruta.
- [ ] `STATE.md`, `TURN.md`, `execution_log.md` se materializan desde el bus.
- [ ] `--mark-ready` y `--request-changes` leen el estado derivado del bus.
- [ ] No queda drift persistente entre bus y proyecciones.
- [ ] No hay import circular: `bus/review_bridge.py` no importa
      `agent_controller.py`.
- [ ] `test_emit_fail_safe_on_review_decision` pasa.
- [ ] El test e2e de regresion pasa.
- [ ] `ruff check .` y `agent_controller.py --validate` pasan limpios.

## Riesgos

- El cambio toca la autoridad canonica de estado; verificar que las rutas
  legacy de `changes` / `approve` no se rompen.
- No introducir auto-healing silencioso: si bus y proyeccion divergen, el
  sistema debe fallar visiblemente.
- La cobertura de tests debe ejercitar el ciclo completo, no solo la ruta
  feliz; incluir explicitamente `inspect`.
