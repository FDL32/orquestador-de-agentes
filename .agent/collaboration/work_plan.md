# Work Plan - WP-2026-130

## Metadata
- **ID:** WP-2026-130
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Manager legacy naming cleanup

## Objetivo
Eliminar la mezcla semantica entre rol y backend en el Manager review path, renombrando referencias legacy de `codex` a `manager` donde realmente describen la ruta del Manager y no el backend real.

## Decision Arquitectonica
- `_run_codex_review()` es un nombre legacy que mezcla el rol Manager con el backend historico; debe pasar a un nombre semantico de ruta legacy del Manager.
- `parse_method = "legacy_codex"` debe pasar a una etiqueta de trazabilidad que describa la ruta legacy del Manager.
- Las referencias de tests y templates que siguen hablando de `codex` como si fuera el Manager deben renombrarse para no mezclar rol con backend.
- El backend real `codex` puede seguir existiendo en `agents.json`; lo que se limpia es el naming del path del Manager.

## Files Likely Touched
- `bus/review_bridge.py`
- `tests/test_manager_review_bridge.py`
- `tests/test_launch_agent_terminals_script.py`
- `templates/startup/manager_legacy.md`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WP-2026-130.md`
- `.agent/collaboration/AUDIT_WP-2026-130.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `PROJECT.md`

## Fases
1. Renombrar la ruta legacy del Manager en `bus/review_bridge.py` para que deje de hablar de `codex` cuando en realidad describe un flujo de Manager.
2. Renombrar los fixtures, tests y templates que siguen usando `codex` como etiqueta de la ruta del Manager.
3. Verificar que el rename no toca la compatibilidad real del backend `codex` en `agents.json` ni rompe el arranque OpenCode.

## Calidad
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- Ninguna ruta del Manager usa `codex` como nombre de rol o ruta legacy.
- Los tests y templates del Manager hablan de la semantica correcta.
- El backend `codex` real sigue existiendo como opcion configurada, sin confusion de nombres.
- Los tests cubren el rename y evitan regresiones de nomenclatura.

## Nota
WP-2026-129 queda como closeout historico del entorno de review. Este ticket corrige la nomenclatura legacy del Manager para no mezclar rol con backend.
