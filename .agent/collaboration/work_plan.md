# Work Plan - WP-2026-143

## Metadata
- **ID:** WP-2026-143
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Bus-backed mark-ready idempotency
- **Asignado a:** Builder

## Objetivo
Hacer `--mark-ready` idempotente usando el estado del bus como autoridad. Si el bus ya indica `READY_FOR_REVIEW`, `READY_TO_CLOSE` o `COMPLETED`, el comando debe salir limpio sin emitir `BUILDER_EXIT` ni `STATE_CHANGED` duplicados. Si el bus no esta disponible, se conserva el fallback actual sobre markdown.

## Decision Arquitectonica
- `--mark-ready` consultara primero el estado derivado del bus para el ticket activo.
- `READY_FOR_REVIEW` seguira siendo el camino idempotente de "ya listo".
- `READY_TO_CLOSE` y `COMPLETED` seran no-op limpios para evitar ciclos de review duplicados.
- Si el bus no esta disponible o no puede derivarse un estado, se mantiene el fallback actual sobre markdown.
- El scope gate y el circuit breaker conservan su comportamiento actual.

## Files Likely Touched
- `.agent/agent_controller.py`
- `tests/unit/test_bus_emission_on_mark_ready.py`
- `tests/unit/test_mark_ready_idempotency.py`

## Fases
1. Introducir un guard de estado del bus en `--mark-ready` y separar los caminos `READY_FOR_REVIEW`, `READY_TO_CLOSE` y `COMPLETED`.
2. Anadir tests para el no-op idempotente y para el fallback cuando el bus no esta disponible.
3. Verificar que no se emiten eventos duplicados y que el flujo existente sigue funcionando.
4. Validar con los gates locales del repositorio.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_bus_emission_on_mark_ready.py -q`
- `python scripts/run_pytest_safe.py tests/unit/test_mark_ready_idempotency.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `--mark-ready` no emite eventos duplicados cuando el bus ya esta en `READY_FOR_REVIEW`, `READY_TO_CLOSE` o `COMPLETED`.
- El guard lee el estado del bus y no depende del drift de markdown para evitar un segundo ciclo de review.
- El fallback actual se conserva cuando el bus no esta disponible.
- La validacion canonica pasa sin errores.
