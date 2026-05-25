# Work Plan - WP-2026-135

## Metadata
- **ID:** WP-2026-135
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Selective context recovery lite for pre-compact hook
- **Asignado a:** Builder

## Objetivo
Hacer que el hook de pre-compactacion recupere contexto util de forma ligera, proyectando una seccion `Memoria relevante` basada en `observations.jsonl` y en el `work_plan` activo, sin fallar si la memoria falta o esta corrupta.

## Decision Arquitectonica
- `pre_compact_hook.py` debe leer `observations.jsonl` de forma segura y devolver una proyeccion util, aunque la memoria no exista o este corrupta.
- La recuperacion de contexto usa dos senales simples: recencia y coincidencia de keywords extraidas del `work_plan` activo.
- La salida relevante se limita a un maximo de 5 observaciones para mantener la compaction ligera.
- El contrato actual del hook se preserva: `continue=true` y JSON estable de entrada/salida.
- La proyeccion compacta se entrega en el campo `additionalContext` del JSON de salida, porque ese es el canal que consume Claude Code antes de compactar.
- La resolucion de rutas debe derivarse desde `Path(__file__).resolve().parent.parent` para obtener `AGENT_DIR` y no depender de `Path.cwd()`.
- No se introducen embeddings, sqlite, LLM ni dependencias pesadas.

## Files Likely Touched
- `.agent/hooks/pre_compact_hook.py`
- `tests/unit/test_pre_compact_hook.py`

## Fases
1. Implementar carga segura de observaciones y extraccion de keywords desde el `work_plan` activo.
2. Derivar `AGENT_DIR` de `Path(__file__).resolve().parent.parent` y localizar `observations.jsonl` y `work_plan.md` sin depender del cwd.
3. Rankear observaciones por recencia y coincidencia de palabras clave, con cap de 5.
4. Formatear la seccion `Memoria relevante` dentro de `additionalContext` para la fase de compactacion.
5. Añadir tests para memoria vacia, archivo ausente, JSONL corrupto, matching por keywords, ranking por recencia y presencia de `additionalContext`.
6. Validar que el hook sigue devolviendo JSON estable sin romper el contrato `continue`.

## Calidad
- `ruff check . && ruff format --check .`
- `python scripts/run_pytest_safe.py tests/unit/test_pre_compact_hook.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- El hook no falla si `observations.jsonl` no existe o esta corrupto.
- La proyeccion incluye una seccion `Memoria relevante` compacta dentro de `additionalContext` cuando hay observaciones utiles.
- La salida relevante no supera 5 observaciones.
- El ranking combina recencia y coincidencia de palabras clave del `work_plan`.
- Los tests cubren memoria vacia, archivo ausente, JSONL corrupto, ranking basico y `additionalContext`.

## Nota
Este ticket es pequeno y autocontenido. Si aparece la necesidad de tocar bus, state machine o consolidacion de memoria, se considera deriva de alcance y debe escalarse aparte.
