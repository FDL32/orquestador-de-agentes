# Work Plan - WP-2026-138

## Metadata
- **ID:** WP-2026-138
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Manager review memory injection from observations
- **Asignado a:** Builder

## Objetivo
Inyectar las lecciones acumuladas de auditoria en el prompt del Manager leyendo `.agent/runtime/memory/observations.jsonl`, sin tocar el contrato de decision ni el rubric estatico base.

## Decision Arquitectonica
- `bus/review_bridge.py` debe leer `observations.jsonl` y filtrar `topic="manager-review-rubric"`.
- La seccion dinamica se inyecta en `_build_review_prompt()` despues del rubric estatico y antes del bloque de contexto canonico.
- La seccion dinamica se ordena por recencia y se limita a `MAX_RUBRIC_OBSERVATIONS = 5`.
- Cada observacion se trunca a `MAX_OBSERVATION_SIGNAL_CHARS = 200` caracteres si supera el limite.
- Si `observations.jsonl` falta, esta corrupto o no contiene observaciones validas, el prompt sigue sin la seccion dinamica y no falla.
- El rubric estatico sigue siendo la base; la memoria dinamica solo lo amplifica.
- La memoria dinamica se aplica a tickets `code` y `mixed`.
- No se introduce escritura sobre `observations.jsonl` ni se modifica el pipeline de cierre de sesion.
- El contrato `APPROVE / CHANGES / INSPECT` permanece intacto.

## Files Likely Touched
- `bus/review_bridge.py`
- `tests/test_review_bridge.py`
- `tests/test_manager_review_bridge.py`

## Fases
1. Implementar la lectura segura de `observations.jsonl` y el filtrado por topic.
2. Inyectar la seccion de "Lecciones acumuladas" en `_build_review_prompt()` con cap, truncado y soporte para `code`/`mixed`.
3. Mantener el rubric base y el contrato de decision intactos.
4. Anadir tests para archivo ausente, contenido corrupto, filtrado por topic, cap, truncado por entrada y preservacion del rubric base.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_review_bridge.py tests/test_manager_review_bridge.py -q`
- `ruff check bus scripts tests`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- El prompt del Manager incluye una seccion dinamica de observaciones cuando existen entradas con `topic="manager-review-rubric"`.
- La seccion dinamica muestra solo entradas recientes y respeta el cap acordado.
- Cada observacion se trunca a 200 caracteres si excede el limite.
- La seccion dinamica se aplica a tickets `code` y `mixed`.
- Si el fichero falta o es invalido, la construccion del prompt sigue funcionando.
- El rubric base y el contrato `APPROVE / CHANGES / INSPECT` no cambian.
- Los tests cubren archivo ausente, filtrado, cap, truncado por entrada, mixed y formato estable.
- La validacion canonica pasa sin errores.
