# Work Plan - WP-2026-128

## Metadata
- **ID:** WP-2026-128
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Skill allowlist contract hardening

## Objetivo
Endurecer el contrato de filtrado de skills por rol para que la configuracion sea valida, trazable y reproducible, evitando que roles vean skills no permitidas o que allowlists rotas entren silenciosamente al prompt.

## Decision Arquitectonica
- `agents.json` pasa a ser la fuente de verdad operativa de allowlists por rol usando la key exacta `skill_allowlists`.
- `bus/skill_resolver.py` sigue siendo la capa de resolucion, filtrado y validacion de skills.
- `bus/review_bridge.py` solo consume la lista filtrada; no debe decidir permisos ni duplicar reglas de acceso.
- La validacion temprana debe fallar de forma clara cuando una allowlist referencia skills inexistentes o un rol desconocido.
- El prompt del Manager debe reflejar solo las skills realmente accesibles por su rol.

## Files Likely Touched
- `.agent/agents_config.py`
- `.agent/config/agents.json`
- `bus/skill_resolver.py`
- `bus/review_bridge.py`
- `bus/exceptions.py`
- `tests/unit/test_agents_config.py`
- `tests/unit/test_skill_discovery.py`
- `tests/test_manager_review_bridge.py`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WP-2026-128.md`
- `.agent/collaboration/AUDIT_WP-2026-128.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `PROJECT.md`

## Fases
1. Externalizar y versionar las allowlists de skills por rol en `agents.json` con la key `skill_allowlists` y compatibilidad hacia atras.
2. Validar allowlists y referencias de skills de forma temprana, cruzandolas contra el catalogo real de `discover_skills.py` y fallando si el catalogo queda vacio.
3. Verificar que el prompt del Manager y los tests consumen solo el catalogo filtrado y que las quality gates siguen limpias.

## Calidad
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- La configuracion puede declarar allowlists por rol sin romper compatibilidad.
- Una allowlist con skills inexistentes falla de forma explicita o queda reportada por validacion.
- Un catalogo de skills vacio se trata como error de infraestructura, no como skills huérfanas.
- El prompt del Manager solo incluye skills permitidas para su rol.
- El bus y las proyecciones siguen sincronizados bajo el nuevo contrato de skills.

## Nota
WP-2026-127 quedo como referencia historica del endurecimiento del bus y la revision. Este ticket convierte el filtrado de skills en un contrato configurado y verificable, en vez de una regla solo implicita.
