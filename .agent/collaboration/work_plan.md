# Work Plan - WP-2026-136

## Metadata
- **ID:** WP-2026-136
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Semantic --candidates input for session_close_observations
- **Asignado a:** Builder

## Objetivo
Permitir que agentes externos, LLMs o usuarios aporten candidatos de observacion
ya construidos semanticamente a `session_close_observations.py` mediante un flag
`--candidates <json_file>`, desacoplando la generacion de candidatos de su
validacion y filtrado.

## Decision Arquitectonica
- `--candidates` y `--ticket` viven en `add_mutually_exclusive_group(required=True)`.
- `load_candidates_from_file(path)` usa `read_bytes().decode("utf-8")` (estricto):
  bytes invalidos lanzan `ValueError`, no se silencian con `errors="replace"`.
- Lista vacia `[]` es resultado valido: exit 0, no error.
- `load_existing_observations()` endurecido con `errors="replace"` para tolerancia.
- `process_candidates()` y `append_observations()` sin cambios.
- stdlib only; sin dependencias nuevas.

## Files Likely Touched
- `scripts/session_close_observations.py`
- `tests/unit/test_session_close_observations.py`
- `skills/session-close-observations/SKILL.md`
