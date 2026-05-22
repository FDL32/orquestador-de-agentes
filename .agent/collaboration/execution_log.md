# Execution Log - WP-2026-130

## Metadata
- **ID:** WP-2026-130
**Estado:** IN_PROGRESS
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Manager legacy naming cleanup

## Fases
- Phase 1: renombrar la ruta legacy del Manager para que deje de describirse como `codex`.
- Phase 2: actualizar los fixtures, templates y tests que siguen usando la nomenclatura legacy.
- Phase 3: validar el rename con tests y quality gates sin tocar la compatibilidad real del backend `codex`.

## Registro de Implementacion

### Preparacion Canonica
- `work_plan.md`: ticket aprobado para el nuevo ciclo.
- `STATE.md`: estado inicial del nuevo ticket.
- `TURN.md`: turno del Builder preparado.
- `PLAN_WP-2026-130.md`: alcance y estrategia del ticket.
- `AUDIT_WP-2026-130.md`: criterios de auditoria definidos.

### Calidad Esperada
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

### Implementacion Fase 1: Renombrar la ruta legacy del Manager
- `bus/review_bridge.py` debe dejar de usar nombres `codex` para la ruta legacy del Manager.
- `bus/review_bridge.py` debe cambiar la trazabilidad `legacy_codex` a una etiqueta semantica de Manager.
- `tests/test_manager_review_bridge.py` debe cubrir el nuevo nombre sin cambiar la semantica del backend real.
- `tests/test_launch_agent_terminals_script.py` debe reflejar el nuevo nombre del template legacy.

## Criterios de Aceptacion
- [ ] La ruta legacy del Manager ya no se describe como `codex`.
- [ ] Los tests y templates reflejan la nomenclatura correcta.
- [ ] El backend `codex` real sigue disponible como configuracion, sin romper compatibilidad.
- [ ] Los tests cubren el rename y evitan regresiones.

## Evidencia de Implementacion

### Fase 1 pendiente
- `bus/review_bridge.py`: renombrar la ruta legacy del Manager.
- `tests/test_manager_review_bridge.py`: ajustar fixtures y nombres de pruebas.
- `tests/test_launch_agent_terminals_script.py`: cambiar la referencia del template legacy.

### Quality gates esperados
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`
