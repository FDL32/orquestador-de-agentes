# Work Plan - WP-2026-129

## Metadata
- **ID:** WP-2026-129
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Review env inheritance fix

## Objetivo
Eliminar el redirect legacy de `HOME`, `USERPROFILE` y `CODEX_HOME` hacia `.codex` en el entorno de review para que OpenCode herede el entorno normal del proceso y no falle por una home aislada.

## Decision Arquitectonica
- `_review_env()` debe preservar el entorno heredado en vez de reescribir las variables de home hacia `.codex`.
- `_get_manager_backend()` debe dejar de caer en `"codex"` y usar `"opencode"` como fallback del Manager.
- El fix debe ser compatible con OpenCode y no introducir un caso especial que rompa otros backends.
- La review env debe quedar reproducible sin esconder el home real del proceso.

## Files Likely Touched
- `bus/review_bridge.py`
- `tests/test_manager_review_bridge.py`
- `tests/unit/test_review_env.py`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WP-2026-129.md`
- `.agent/collaboration/AUDIT_WP-2026-129.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `PROJECT.md`

## Fases
1. Eliminar el redirect de `HOME`, `USERPROFILE` y `CODEX_HOME` hacia `.codex` en `_review_env()` y cambiar el fallback del Manager de `"codex"` a `"opencode"`.
2. Asegurar que OpenCode hereda el entorno normal y que el review bridge sigue funcionando sin aislar la home.
3. Verificar el cambio con tests del review bridge y quality gates.

## Calidad
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `_review_env()` ya no reescribe `HOME`, `USERPROFILE` ni `CODEX_HOME` hacia `.codex`.
- `_get_manager_backend()` ya no usa `"codex"` como fallback y resuelve `"opencode"` para el Manager.
- OpenCode puede ejecutar el review sin heredar un home artificial que rompa su arranque.
- Los tests cubren la herencia del entorno y evitan regresiones.

## Nota
WP-2026-128 queda como closeout historico del filtrado de skills. Este ticket corrige el entorno de review para no romper OpenCode con una home redirigida.
