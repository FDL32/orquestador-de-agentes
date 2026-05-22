# Execution Log - WP-2026-129

## Metadata
- **ID:** WP-2026-129
**Estado:** COMPLETED
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Review env inheritance fix

## Fases
- Phase 1: eliminar el redirect de `HOME`, `USERPROFILE` y `CODEX_HOME` hacia `.codex` y cambiar el fallback del Manager a `"opencode"`.
- Phase 2: verificar que OpenCode hereda el entorno normal y que el review bridge sigue funcionando.
- Phase 3: validar el cambio con tests y quality gates.

## Registro de Implementacion

### Preparacion Canonica
- `work_plan.md`: ticket aprobado para el nuevo ciclo.
- `STATE.md`: estado inicial del nuevo ticket.
- `TURN.md`: turno del Builder preparado.
- `PLAN_WP-2026-129.md`: alcance y estrategia del ticket.
- `AUDIT_WP-2026-129.md`: criterios de auditoria definidos.

### Calidad Esperada
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

### Implementacion Fase 1: Eliminar redirect de home en review_env() y fallback legacy del Manager
- `bus/review_bridge.py` debe dejar de forzar HOME/USERPROFILE/CODEX_HOME a `.codex`.
- `bus/review_bridge.py` debe dejar de caer en `"codex"` como backend fallback del Manager y usar `"opencode"`.
- `tests/test_manager_review_bridge.py` debe cubrir que el review env hereda el entorno normal.
- `tests/unit/test_review_env.py` puede aislar el helper de entorno si hace falta.

## Criterios de Aceptacion
- [x] `_review_env()` ya no reescribe `HOME`, `USERPROFILE` ni `CODEX_HOME` hacia `.codex`.
- [x] `_get_manager_backend()` ya no usa `"codex"` como fallback y resuelve `"opencode"` para el Manager.
- [x] OpenCode puede ejecutar el review sin heredar un home artificial que rompa su arranque.
- [x] Los tests cubren la herencia del entorno y evitan regresiones.

## Evidencia de Implementacion

### Fase 1 completada
- `bus/review_bridge.py`: `_review_env()` ahora devuelve `os.environ.copy()` sin redirigir variables de home.
- `bus/review_bridge.py`: `_get_manager_backend()` ahora usa `"opencode"` como fallback en lugar de `"codex"`.
- `tests/unit/test_review_env.py`: Nuevo archivo con tests dedicados para la herencia del entorno.
- `tests/test_manager_review_bridge.py`: Actualizado test `test_get_manager_backend_default_opencode` para reflejar el nuevo fallback.
- `tests/test_manager_review_bridge.py`: Test `test_manager_review_cycle_approves` ahora fuerza backend codex explicitamente.

### Quality gates
- `ruff check .`: PASSED
- `pytest`: 239 tests PASSED
- `python .agent/agent_controller.py --validate --json --force`: PASSED (sin errores)


Marked ready by Builder

Manager approved canonical closeout for WP-2026-129