# Work Plan - WP-2026-157

## Metadata
- **ID:** WP-2026-157
- **Estado:** COMPLETED
- **deliverable_type:** mixed
- **Titulo:** ECC capability pack - deep-research skill, AP contract and minimal EDD
- **Asignado a:** Builder

## Objetivo
Implantar una skill documental de investigacion previa, formalizar el contrato AP/observations sin cambiar storage y anadir un harness minimo de regresion para los flujos criticos del sistema.

## Contexto
- `skills/repo-compare/` ya existe, pero compara repositorios; no produce contexto estructurado antes de abrir un ticket.
- `skills/_shared/ap-schema.md` y `observations.jsonl` ya sostienen el patron AP en la practica; falta endurecer el contrato y validar entradas de forma automatica.
- No existe una capa EDD minima para detectar regresiones en review bridge, guard paths, scope gate y requeue sin depender de los tests funcionales generales.
- El output de `deep-research` debe ir a `.agent/runtime/research/` y ese path debe permanecer fuera de git.

## Decision Arquitectonica
- `deep-research` sera una skill documental pura, sin logica Python de produccion.
- El contrato AP se formaliza sobre `ap-schema.md` y `observations.jsonl` se mantiene compatible hacia atras.
- El EDD minimo vivira en `tests/evals/` con fixtures aisladas, marker `eval` y sin subprocess real ni bus de produccion.
- `skills/README.md` se actualizara para registrar la nueva skill.
- `pytest.ini` solo se ajustara para registrar el marker `eval`; no se reescribira su configuracion existente.
- `.gitignore` excluira `.agent/runtime/research/` para que los entregables de investigacion no ensucien el arbol.

## Non-goals
- No reimplantar ECC 1:1.
- No introducir LLM-as-judge ni dependencias nuevas.
- No cambiar el formato de `observations.jsonl`.
- No modificar el workflow de Manager/Builder fuera de lo necesario para la nueva capacidad.

## Fases
### Fase 1: deep-research skill
- **Tipo:** TAREA AGENTE
- **Archivos:** `skills/deep-research/SKILL.md`, `skills/deep-research/references/research-template.md`, `skills/README.md`
- **Accion:** Crear y registrar
- **Descripcion:** Skill documental para producir contexto estructurado antes de abrir un WP. Flujo: leer contexto base (`PROJECT.md`, `AUDIT.md`, work plan activo), identificar gaps, buscar fuentes locales o via MCP y producir un resumen con secciones fijas `## Contexto`, `## Gaps`, `## Fuentes`, `## Recomendacion`. El output se persiste en `.agent/runtime/research/<topic>-<YYYY-MM-DD>.md`.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** `python scripts/discover_skills.py --json` detecta la skill sin errores y `skills/README.md` la registra en el catalogo.
- **Si falla:** Reducir la skill a un `SKILL.md` minimal con workflow y referencias, y mover refinamientos a una iteracion posterior.

### Fase 2: AP / observations contract
- **Tipo:** TAREA AGENTE
- **Archivos:** `skills/_shared/ap-schema.md`, `scripts/validate_observations.py`, `tests/unit/test_validate_observations.py`
- **Accion:** Formalizar y validar
- **Descripcion:** Endurecer `ap-schema.md` con campos obligatorios y opcionales, ordenar la secuencia canonica de escritura (`anti-patterns.md` -> `code-rules.md` -> `review-checklist.md` -> `observations.jsonl`) y crear un validador ligero que rechace observaciones invalidas con codigo de salida 1. Campos obligatorios: `timestamp`, `topic`, `signal`, `source`, `applies_to`, `confidence`, `domain`; `anti_pattern_id` es obligatorio cuando la observacion eleva un bug a AP.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** `python scripts/validate_observations.py` pasa sobre el `observations.jsonl` actual y falla de forma controlada ante una entrada invalida.
- **Si falla:** Relajar el validador a warnings solo si el repo ya tiene entradas historicas que no se pueden corregir de inmediato.

### Fase 3: EDD minimo - eval harness de regresion
- **Tipo:** TAREA AGENTE
- **Archivos:** `pytest.ini`, `tests/evals/__init__.py`, `tests/evals/test_eval_review_bridge.py`, `tests/evals/test_eval_guard_paths.py`, `tests/evals/test_eval_scope_gate.py`, `tests/evals/test_eval_requeue.py`
- **Accion:** Crear
- **Descripcion:** Cuatro modulos pytest de regression que cubren los flujos criticos del sistema con fixtures de `tmp_path` y mocks solo en los bordes externos. Los tests se marcan `@pytest.mark.eval` y no llaman a subprocess real ni al bus de produccion. Mapeo explicito: `test_eval_review_bridge.py` -> `bus/review_bridge.py::run_manager_review_cycle`; `test_eval_guard_paths.py` -> `.agent/hooks/guard_paths.py`; `test_eval_scope_gate.py` -> `agent_controller.py::_check_scope_gate`; `test_eval_requeue.py` -> `bus/supervisor.py::requeue_ticket`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `pytest -m eval tests/evals/ -q` pasa los cuatro modulos, cada modulo incluye al menos un test negativo de entrada invalida y la suite safe normal sigue sin depender de ellos.
- **Si falla:** Reducir el harness a `review_bridge` y `scope_gate` y dejar `guard_paths` / `requeue` para un ticket posterior.

## Files Likely Touched
- `skills/deep-research/SKILL.md` (nuevo)
- `skills/deep-research/references/research-template.md` (nuevo)
- `skills/README.md`
- `skills/_shared/ap-schema.md`
- `scripts/validate_observations.py` (nuevo)
- `tests/unit/test_validate_observations.py` (nuevo)
- `pytest.ini`
- `.gitignore`
- `tests/evals/__init__.py` (nuevo)
- `tests/evals/test_eval_review_bridge.py` (nuevo)
- `tests/evals/test_eval_guard_paths.py` (nuevo)
- `tests/evals/test_eval_scope_gate.py` (nuevo)
- `tests/evals/test_eval_requeue.py` (nuevo)

## Calidad
- `python scripts/discover_skills.py --json`
- `python scripts/validate_observations.py`
- `pytest -m eval tests/evals/ -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `deep-research` aparece en el discovery de skills y queda registrado en `skills/README.md`.
- `ap-schema.md` y `validate_observations.py` coinciden en el contrato y bloquean observaciones invalidas.
- El harness `tests/evals/` detecta regresiones criticas sin tocar subprocess real ni bus de produccion.
- La suite safe principal sigue pasando sin depender de los evals.
- La validacion canonica pasa sin errores.
