# Work Plan - WP-2026-175

## Metadata
- **ID:** WP-2026-175
- **Estado:** APPROVED
- **deliverable_type:** documentation
- **Titulo:** Canonical session closeout and cycle rollover
- **Asignado a:** Builder

## Objetivo
Cerrar canónicamente la sesión actual tras WP-2026-174, consolidar el reporte de cierre, archivar los artefactos transitorios y dejar el repositorio listo para arrancar el siguiente ciclo sin drift.

## Contexto
- El repo ya dispone de la ruta canónica de cierre de sesión a través de `python .agent/agent_controller.py --session-close --project-root .`.
- `scripts/session_closeout.py` ya implementa el orquestador de cierre; este ticket reutiliza esa entrada canónica en vez de recrear lógica.
- En sesiones anteriores el problema no fue la ausencia del cierre, sino dejar proyecciones y artefactos residuales sin consolidar.
- El cierre debe dejar explícitamente `PROJECT.md`, `STATE.md`, `TURN.md` y el reporte de cierre alineados con la realidad del bus.

## Decision Arquitectonica
- El ticket reutiliza el flujo canónico existente de cierre de sesión y no introduce un segundo orquestador.
- El cierre debe ser idempotente: si la sesión ya está cerrada, el flujo sale con éxito sin reescribir de más.
- `--session-close` genera el reporte de cierre y deja las proyecciones de runtime listas para el siguiente ciclo.
- `PROJECT.md` y `CHANGELOG.md` se actualizan explícitamente en un paso posterior del ticket para reflejar el cierre canónico.
- No se introduce código nuevo en este ticket.

## Non-goals
- No cambiar la lógica de `scripts/session_closeout.py`.
- No tocar `bus/supervisor.py`.
- No introducir nuevas dependencias.
- No abrir un nuevo ticket técnico en esta fase.

## Fases

### Fase 1: ejecutar y validar el cierre canónico
- **Tipo:** TAREA AGENTE
- **Archivos:** `STATE.md`, `.agent/collaboration/TURN.md`, `.agent/collaboration/execution_log.md`, `.agent/runtime/memory/session_close_report.md`
- **Accion:** Modificar
- **Descripcion:** Ejecutar la ruta canónica de cierre de sesión con `python .agent/agent_controller.py --session-close --project-root .` y confirmar que el reporte de cierre se genera. Usar `python .agent/agent_controller.py --session-close --project-root . --dry-run` solo como comprobación previa, no como sustituto del cierre. El flujo real debe ser idempotente y no reintroducir drift entre bus, reporte y estado canónico. Verificar explícitamente que ejecutar el cierre real dos veces seguidas devuelve exit 0 en ambas ejecuciones y que la segunda no introduce cambios canónicos adicionales.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El cierre deja las proyecciones runtime coherentes, el reporte de cierre queda emitido y una segunda ejecución del cierre devuelve exit 0 sin modificar el estado canónico.
- **Si falla:** Conservar el cierre actual pero exigir validación manual antes de cambiar el estado canónico.

### Fase 2: consolidar cierre y preparar el siguiente ciclo
- **Tipo:** TAREA AGENTE
- **Archivos:** `PROJECT.md`, `CHANGELOG.md`, `.agent/collaboration/work_plan.md`, `.agent/collaboration/execution_log.md`
- **Accion:** Modificar
- **Descripcion:** Actualizar manualmente `PROJECT.md` y `CHANGELOG.md` con la entrada de cierre de la sesión. Ejecutar `python scripts/archive_collaboration_artifacts.py` para mover los artefactos cerrados a `_archive/plan_audit/` y dejar preparado el siguiente ciclo sin residuos operativos del ticket anterior.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** `PROJECT.md` refleja el cierre canónico, `CHANGELOG.md` deja trazado el cierre de sesión y el ticket cerrado no permanece como ciclo activo.
- **Si falla:** Mantener el cierre canónico y posponer el archivo del histórico a una pasada posterior.

## Files Likely Touched
- `PROJECT.md`
- `CHANGELOG.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/runtime/memory/session_close_report.md`

## Calidad
- `python .agent/agent_controller.py --session-close --project-root . --dry-run`
- `python .agent/agent_controller.py --session-close --project-root .` (cierre real)
- `python .agent/agent_controller.py --session-close --project-root .` (segunda ejecucion — debe devolver exit 0 sin cambios canonicos)
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- La sesión actual queda cerrada canónicamente y el reporte de cierre se emite.
- `PROJECT.md`, `STATE.md` y `TURN.md` reflejan el estado terminal coherente.
- `CHANGELOG.md` deja trazado el cierre de sesión.
- El flujo de cierre es idempotente y no reabre drift si se repite.
