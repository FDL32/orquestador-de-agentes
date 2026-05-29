# Work Plan - WP-2026-169

## Metadata
- **ID:** WP-2026-169
- **Estado:** APPROVED
- **deliverable_type:** mixed
- **Titulo:** Session close loop bridge - `--session-close` en agent_controller
- **Asignado a:** Builder

## Objetivo
Cerrar el loop de `session-close -> WP-B` exponiendo `--session-close` en `.agent/agent_controller.py` para invocar el orquestador de cierre, sincronizar las proyecciones canonicas post-cierre y dejar el siguiente ciclo listo sin pasos manuales entre el cierre y la creacion del nuevo plan.

## Contexto
- WP-2026-168 ya entrego `scripts/session_closeout.py` como orquestador standalone.
- Hoy el cierre canonico sigue requiriendo lanzar el script aparte y luego alinear proyecciones a mano.
- El nuevo entrypoint debe ser el unico punto de entrada canonico para cierre de sesion desde el controlador.
- El wrapper debe preservar la logica existente del orquestador y no duplicar pasos.
- La integracion debe mantener la semantica de `--dry-run`, `--skip-slow` y la seleccion de tickets.
- El cierre debe dejar el bus y las proyecciones listos para el siguiente ciclo del Manager.

## Decision Arquitectonica
- `.agent/agent_controller.py` anade un flag `--session-close`.
- El handler delega en `scripts/session_closeout.py` y reusa sus flags `--project-root`, `--dry-run`, `--skip-slow`, `--ticket` y `--tickets`.
- Tras un cierre real, el controlador sincroniza la proyeccion de estado en la misma ruta de ejecucion para dejar `STATE.md` y las superficies canonicas listas para el siguiente ciclo.
- La salida del comando debe ser estructurada y no esconder errores del orquestador.
- No se reimplementa la pipeline de cierre dentro del controlador.
- El entrypoint debe permanecer idempotente si el cierre ya fue completado: si `STATE.md` ya refleja un estado terminal (`COMPLETED`) y no se pasa `--force`, el handler imprime aviso y sale con exit 0 sin relanzar el cierre.

## Non-goals
- No rehacer `scripts/session_closeout.py`.
- No cambiar la logica de archivado o memoria ya validada.
- No introducir dependencias nuevas.
- No alterar la cascada de `--manager-approve`.
- No cambiar el modelo de turno de Manager/Builder.
- No forzar un nuevo ticket automatico si el Manager no ha creado uno.

## Fases

### Fase 1: CLI y delegacion canonica
- **Tipo:** TAREA AGENTE
- **Archivos:** `.agent/agent_controller.py`, `tests/test_agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** Anadir `--session-close` al parser y hacer que el handler invoque `scripts/session_closeout.py` con los flags soportados. El comando debe respetar `--dry-run`, `--skip-slow`, `--ticket` y `--tickets`, y devolver el exit code del orquestador sin envolver errores. Cuando no sea `--dry-run`, el handler debe hacer la sincronizacion de estado post-cierre en la misma ruta de ejecucion.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `--session-close` existe, invoca el orquestador correcto, no duplica la logica de cierre y sincroniza el estado real despues del cierre.
- **Si falla:** Mantener el cierre manual y dejar el wrapper para un ticket posterior.

### Fase 2: docs y tests del wrapper
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_agent_controller.py`, `PROJECT.md`, `README.md`, `QUICKSTART.md`, `CHANGELOG.md`
- **Accion:** Modificar
- **Descripcion:** Cubrir el nuevo flag en `tests/test_agent_controller.py` y actualizar la documentacion para que `--session-close` sea visible como ruta canonica. En `README.md`, actualizar la seccion `Common commands` y la ruta de `Typical flow` para mencionar el cierre desde el controlador. En `QUICKSTART.md`, actualizar la seccion `6. Comandos diarios` para incluir `python .agent/agent_controller.py --session-close --project-root .` junto al ciclo diario. En `PROJECT.md`, reflejar el nuevo ciclo activo. En `CHANGELOG.md`, anadir la entrada del puente de cierre.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** La documentacion apunta al nuevo entrypoint, y los tests cubren delegacion, dry-run e idempotencia terminal.
- **Si falla:** Conservar el CLI y posponer solo la actualizacion documental.

## Files Likely Touched
- `.agent/agent_controller.py`
- `tests/test_agent_controller.py`
- `PROJECT.md`
- `README.md`
- `QUICKSTART.md`
- `CHANGELOG.md`

## Calidad
- `python scripts/run_pytest_safe.py tests/test_agent_controller.py`
- `uv run ruff check .agent/agent_controller.py tests/test_agent_controller.py`
- `python .agent/agent_controller.py --session-close --project-root . --dry-run`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `--session-close` existe en `agent_controller.py` y delega en `scripts/session_closeout.py`.
- El handler sincroniza el estado real solo cuando el cierre no es dry-run.
- Si `STATE.md` ya es terminal y no se pasa `--force`, el handler sale con exit 0 sin relanzar el cierre.
- La documentacion apunta al nuevo entrypoint como ruta canonica.
- `tests/test_agent_controller.py` cubre delegacion, dry-run e idempotencia.
