# Work Plan - WP-2026-131

## Metadata
- **ID:** WP-2026-131
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Memory index cap for persistent observations
- **Asignado a:** Builder

## Objetivo
Convertir `MEMORY.md` en un indice humano corto y estable, dejando `observations.jsonl` como la fuente historica para busqueda profunda y trazabilidad.

## Decision Arquitectonica
- `MEMORY.md` debe mantenerse acotado y util como indice, no como volcado historico.
- La historia completa y la busqueda profunda pertenecen a `observations.jsonl`.
- `scripts/memory_consolidate.py` es la unica pieza que materializa y recorta el indice.
- `AGENTS.md` debe documentar la regla de memoria acotada de forma breve y operativa.
- `scripts/memory_consolidate.py` debe declarar `MEMORY_MD_LINE_CAP = 80` y truncar el indice con un marcador visible cuando se supere el limite.

## Files Likely Touched
- `scripts/memory_consolidate.py`
- `tests/unit/test_memory_consolidate.py`
- `.agent/runtime/memory/MEMORY.md`
- `AGENTS.md`
- `.agent/collaboration/PLAN_WP-2026-131.md`
- `.agent/collaboration/AUDIT_WP-2026-131.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`

## Fases
1. Definir el cap de lineas en `MEMORY.md` y la politica de recorte en `scripts/memory_consolidate.py`.
2. Ajustar la regeneracion del indice para priorizar resumen util sobre historial largo y truncar con marcador visible cuando sea necesario.
3. Añadir un test explicito que fuerce un output mayor a 80 lineas y verifique que el indice final queda acotado.
4. Actualizar `AGENTS.md` en la seccion `Memoria por proyecto` con la regla de memoria acotada y la ubicacion de la historia completa.
5. Validar que el indice no supera 80 lineas y que la historia sigue disponible en `observations.jsonl`.

## Calidad
- `python scripts/memory_consolidate.py --dry-run`
- `python scripts/run_pytest_safe.py tests/unit/test_memory_consolidate.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `MEMORY.md` no supera 80 lineas.
- `MEMORY.md` sigue siendo un indice humano util.
- La trazabilidad historica queda en `observations.jsonl`.
- `AGENTS.md` documenta la regla sin ambiguedades.
- Los tests de memoria siguen pasando y cubren la regeneracion del indice.

## Nota
Este ticket es intencionalmente pequeno y autocontenido. Si durante la implementacion aparece la necesidad de tocar el bus o el state machine, se considera deriva de alcance y debe escalarse aparte.
