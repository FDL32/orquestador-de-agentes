# Execution Log - WP-2026-128

## Metadata
- **ID:** WP-2026-128
**Estado:** COMPLETED
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Skill allowlist contract hardening

## Fases
- Phase 1: externalizar las allowlists por rol en `agents.json` con la key `skill_allowlists`.
- Phase 2: validar allowlists y referencias de skills contra `discover_skills.py`, con error explicito si el catalogo queda vacio.
- Phase 3: verificar que el prompt del Manager y los tests reflejan solo el catalogo filtrado.

## Registro de Implementacion

### Preparacion Canonica
- `work_plan.md`: ticket aprobado para el nuevo ciclo.
- `STATE.md`: estado inicial del nuevo ticket.
- `TURN.md`: turno del Builder preparado.
- `PLAN_WP-2026-128.md`: alcance y estrategia del ticket.
- `AUDIT_WP-2026-128.md`: criterios de auditoria definidos.

### Calidad Esperada
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

### Implementacion Fase 1: Externalizar allowlists en agents.json
- `.agent/config/agents.json` ahora incluye `skill_allowlists` con listas por rol (BUILDER, MANAGER, SUPERVISOR).
- `.agent/agents_config.py` agrega `_validate_skill_allowlists()` para validar roles conocidos y formato de lista.
- Validacion es retrocompatible: si `skill_allowlists` no existe, la config carga sin error.

### Implementacion Fase 2: Validar allowlists contra catalogo de skills
- `bus/exceptions.py` agrega `EmptySkillCatalogError` para error de infraestructura cuando no hay skills.
- `bus/skill_resolver.py`:
  - `_discover_skills()` ahora lanza `EmptySkillCatalogError` si el catalogo queda vacio.
  - Agrega `validate_allowlists_against_catalog()` que cruza allowlists contra skills descubiertas y retorna warnings.
  - `create_resolver()` ahora tiene parametro `validate` (default True) que valida catalogo y emite warnings.
- `bus/review_bridge.py` usa `create_resolver(project_root, validate=False)` para evitar validacion duplicada.

### Implementacion Fase 3: Verificar prompt del Manager con skills filtradas
- `review_bridge.py` ya usa `skill_resolver.filter_skills_for_prompt()` en `_build_review_prompt()`.
- Test agregado `test_build_review_prompt_includes_allowed_skills_for_role` verifica que el prompt incluye seccion `ALLOWED SKILLS FOR ROLE`.

### Tests Agregados
- `tests/unit/test_agents_config.py`: `TestSkillAllowlists` con 5 tests para validacion de allowlists.
- `tests/unit/test_skill_discovery.py`: `TestSkillResolverValidation` y `TestEmptySkillCatalogError` con 5 tests.
- `tests/test_manager_review_bridge.py`: `test_build_review_prompt_includes_allowed_skills_for_role`.

### Quality Gates Ejecutadas
- `ruff check .`: 0 errors
- `pytest`: 239 tests passed (incluye tests nuevos)
- `python .agent/agent_controller.py --validate --json --force`: errors vacios

## Criterios de Aceptacion
- [x] La configuracion puede declarar allowlists por rol sin romper compatibilidad.
- [x] Una allowlist con skills inexistentes falla de forma explicita o queda reportada por validacion.
- [x] Un catalogo de skills vacio se trata como error de infraestructura y no como skill faltante.
- [x] El prompt del Manager solo incluye skills permitidas para su rol.
- [x] El bus y las proyecciones siguen sincronizados bajo el nuevo contrato de skills.


Marked ready by Builder

Manager approved canonical closeout for WP-2026-128