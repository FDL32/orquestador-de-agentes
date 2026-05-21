# Plan de Trabajo: WP-2026-122 - Desacople de `project_root` en runtime

## Metadata
- **ID:** WP-2026-122
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-05-21
- **Prioridad:** HIGH
- **Asignado a:** Builder
- **Backend:** OpenCode
- **Tipo:** IMPLEMENTATION

---

## Objetivo

Implementar el contrato de inyeccion de `project_root` definido por la
auditoria de WP-2026-121 para que el motor pueda operar sobre un destino
externo sin copiarse dentro de el. El comportamiento por defecto debe seguir
siendo el mismo cuando no se pase un root externo.

## Contexto

La auditoria previa ya cerro las decisiones clave:

- `bus/event_bus.py`, `bus/supervisor.py` y `bus/review_bridge.py` no
  necesitan cambios internos.
- `agent_system/scripts/project_paths.py` se mantiene como helper de
  instalacion y diagnostico; no enruta el runtime de WP-A.
- El contrato de inyeccion es: `--project-root` en entry points, variable de
  entorno `AGENT_PROJECT_ROOT` para hooks y una funcion central
  `resolve_project_root()`.

La revision del plan detecto un punto arquitectonico que hay que fijar antes
de implementar:

- No se admiten constantes globales `PROJECT_ROOT` fijadas en import para los
  modulos de categoria [A] si su valor puede depender del root externo.
- La logica comun vivira en un unico modulo hogar: `runtime/project_root.py`.
- Los consumidores de [A] usaran resolucion diferida en funciones/factories;
  el import time no puede ser la fuente de verdad.
- Los entry points pueden aceptar `--project-root`, pero la correccion real es
  que los modulos importados no dependan de haber parseado CLI antes de cargar.

La base estable ya esta publicada. Este WP ejecuta el paso siguiente de la
secuencia de portabilidad: WP-A.

## Files Likely Touched

### Codigo

- `runtime/project_root.py`
- `.agent/agent_controller.py`
- `.agent/agents_config.py`
- `.agent/completion_checker.py`
- `.agent/completion_common.py`
- `.agent/session_tracker.py`
- `.agent/hooks/stop_hook.py`
- `.agent/runtime/memory/memory_helpers.py`
- `runtime/ui_state_projector.py`
- `scripts/manager_review_bridge.py`
- `scripts/local_audit.py`
- `scripts/ticket_supervisor.py`
- `scripts/ticket_activity_monitor.py`
- `scripts/run_gates_dispatch.py`
- `scripts/builder_agent.py`
- `scripts/archive_event_bus.py`
- `scripts/check_deliverables_exist.py`
- `scripts/memory_consolidate.py`
- `scripts/update_project_map.py`
- `scripts/validate_authority.py`
- `scripts/run_pytest_safe.py`
- `scripts/launch_agent_terminals.ps1`
- `bus/review_bridge.py`
- `.agent/runtime/events/events.jsonl`

### Tests

- `tests/test_agent_controller.py`
- `tests/unit/test_agents_config.py`
- `tests/test_completion_checker.py`
- `tests/test_completion_common.py`
- `tests/test_stop_hook.py`
- `tests/integration/test_memory_integration.py`
- `tests/test_ui_state_projector_scoping.py`
- `tests/test_manager_review_bridge.py`
- `tests/unit/test_local_audit.py`
- `tests/test_validate_authority.py`
- `tests/unit/test_run_gates_dispatch.py`
- `tests/unit/test_check_deliverables_exist.py`
- `tests/unit/test_archive_collaboration_artifacts.py`
- `tests/unit/test_memory_consolidate.py`
- `tests/test_project_map_freshness.py`
- `tests/test_builder_lock.py`
- `tests/unit/test_project_root_resolution.py`
- `tests/test_manager_review_bridge.py`

### Documentos de handoff del ticket

- `.agent/collaboration/PLAN_WP-2026-122.md`
- `.agent/collaboration/AUDIT_WP-2026-122.md`
- `PROJECT.md`
- `.agent/collaboration/review_queue.md`

## Plan

### Fase 1: Contracto central

- Implementar `runtime/project_root.py` como modulo hogar unico de la
  resolucion.
- Implementar `resolve_project_root()` con precedencia:
  `--project-root` > `AGENT_PROJECT_ROOT` > derivacion actual.
- **Canal CLI -> resolver:** el entry point que parsea `--project-root`
  exporta el valor a `AGENT_PROJECT_ROOT` en el entorno justo despues de
  parsear. Asi la precedencia efectiva colapsa a `env > derivado` y el
  resolver diferido no necesita acceso al `argv`. No se introduce un segundo
  canal en paralelo.
- **Importabilidad:** garantizar que `runtime/project_root.py` es importable
  desde los 20 modulos [A] (que viven en `.agent/`, `bus/`, `scripts/`,
  `runtime/`). Asegurar el repo-root en `sys.path` o usar un import robusto
  en cada importador que hoy no lo tenga.
- Reemplazar la dependencia de constantes globales en los modulos [A] por
  acceso diferido en funciones/factories.
- Mantener la ruta por defecto sin cambios cuando no se inyecte root externo.
- Anadir tests unitarios nuevos para la precedencia, los fallbacks y el
  comportamiento import-safe.

### Fase 2: Entry points y scripts runtime

- Parametrizar los entry points de categoria [A] para aceptar `--project-root`.
- Migrar los call-sites runtime a la funcion central compartida sin depender de
  que la CLI haya sido parseada antes de importar.
- Mantener `project_paths.py` fuera del runtime de WP-A.

### Fase 3: Hooks y launcher

- Hacer que los hooks lean `AGENT_PROJECT_ROOT` cuando no haya CLI propia.
- Ajustar `launch_agent_terminals.ps1` para propagar el root del workspace de
  destino al runtime.

### Fase 4: Validacion

- Ejecutar los tests afectados y la validacion canonica sobre el proyecto
  destino de prueba.
- Verificar que el comportamiento legacy sin root externo no cambia.

## Criterios de Aceptacion

- [ ] `resolve_project_root()` existe y se usa en los puntos de alcance.
- [ ] `runtime/project_root.py` es el modulo hogar unico de la resolucion.
- [ ] Los modulos [A] dejan de depender de `PROJECT_ROOT` globales fijados en
      import para la logica sensible al root.
- [ ] `--project-root` funciona en los entry points definidos.
- [ ] `AGENT_PROJECT_ROOT` funciona en hooks y procesos sin CLI propia.
- [ ] El comportamiento por defecto sigue apuntando al repo del motor.
- [ ] Los tests afectados pasan.
- [ ] `bus/event_bus.py`, `bus/supervisor.py` y `bus/review_bridge.py` siguen
      sin cambios internos.
- [ ] `.agent/runtime/events/events.jsonl` figura en el alcance declarado para
      el cambio del bus.

## Riesgos

- La parte mas sensible es la propagacion del root al launcher, a los hooks y
  la eliminacion de constantes de import en los modulos [A].
- Los tests de integracion pueden necesitar fixtures con un destino separado.
- No se debe introducir un segundo mecanismo de resolucion en paralelo a
  `resolve_project_root()`.
