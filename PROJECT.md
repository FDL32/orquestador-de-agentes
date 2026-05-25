# Project state

- Project: `orquestador_de_agentes`
- Version: `v9.14.0`
- State: WP-2026-137 COMPLETED (supervisor startup lock and reconciliation dedupe).
- Last review: 2026-05-25
- Mission: keep the central motor clean, versioned once, and externally referenced
  - The repo is the unique source of operational code (motor central).
  - Destination projects keep only their `.agent/` workspace (state, memory, events, config).
  - The installer prepares the destination to consume the external motor.

## Current Cycle

- Active ticket: WP-2026-137 COMPLETED (supervisor startup lock and reconciliation dedupe).
- Mode: closed.
- Outcome: supervisor lock atomico e idempotencia de reconciliacion completados;
  bus y markdowns sincronizados al cierre.

## Source of truth

> See `[AGENTS.md](AGENTS.md)` for the canonical runtime paths and operational contract.

- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/STATE.md`
- `.agent/runtime/memory/`
- `.agent/council/`
- `.agent/agent_controller.py`
- `scripts/run_pytest_safe.py`

## Current architecture

- Central motor: operational code lives once in `orquestador_de_agentes/`.
- Destination workspace: each project keeps only `.agent/` with state, memory, events, config.
- External reference: destination projects reference the motor externally (not copied).
- Markdown projections remain human-readable snapshots derived from the bus.
- The event bus (`events.jsonl`) is the canonical transition authority.
- `TURN.md`, `STATE.md` and `execution_log.md` stay synchronized together.
- Builder and Manager are role contracts and may run on OpenCode or other approved backends.
- `inspect` remains a human-gate projection of the Manager review path.

## Current readiness

- WP-2026-101 is COMPLETED: duplicate scripts removed, orphaned test/debug artifacts moved to `tests/`.
- The repository remains ready for terminal-driven execution.

## Roadmap de Desacople Motor / Destino

Objetivo: mantener `orquestador_de_agentes/` como motor central unico y abrir el proyecto de destino como workspace separado, con su propio `.agent/` minimo.

### WP-A - Desacople de `project_root` en el motor
- Auditar todas las rutas derivadas de `Path(__file__)` en el motor.
- Parametrizar `project_root` de forma explicita en `agent_controller.py`, `bus/event_bus.py`, `bus/supervisor.py`, `bus/review_bridge.py`, `scripts/manager_review_bridge.py` y `scripts/local_audit.py` como minimo.
- Mantener el comportamiento por defecto sin cambios cuando no se pase un root externo.
- Resultado esperado: el motor puede operar sobre un destino externo sin copiarse dentro.

### WP-B - Workspace minimo en el destino
- Hacer que el instalador cree solo el `.agent/` necesario en el proyecto destino.
- No copiar el motor; solo estado, memoria y config del destino.
- Definir y documentar el archivo de enlace motor-destino antes de este paso.

### WP-C - Launcher multi-root
- Abrir motor y destino como workspace separados en VS Code.
- Mantener el motor en `orquestador_de_agentes/` y el proyecto destino limpio.
- La operacion debe seguir funcionando con el mismo contrato canonico de bus y colaboracion.

### WP-2026-124 - Drift canonico del bus
- Unificar la materializacion de transiciones de estado.
- Hacer que los guards lean el bus derivado.
- Sincronizar las proyecciones desde la autoridad canonica.
- Validar con tests end-to-end que bus y proyecciones no vuelven a divergir.

### WP-2026-126 - Bus end-to-end review validation
- Validar que el Manager recibe un review real mediante review packet.
- Confirmar que el bus y las proyecciones cierran con una decision canonica.

### WP-2026-127 - State revision, approval timeout and skill filtering
- Introducir revision explicita por artefacto con escrituras atomicas y OCC.
- Filtrar skills por rol con validacion temprana.
- Implementar aprobacion con timeout configurable y resolucion canonica.

### Regla de secuencia
- Consolidar/publicar primero la base estable actual.
- Despues ejecutar WP-A.
- Luego WP-B.
- Finalmente WP-C.
# WP-C launcher notes

WP-C closes the motor/destination decoupling in the launcher.

- The launcher must resolve the target workspace before starting Supervisor, Bridge, or Builder.
- Precedence: `--project-root` > `AGENT_PROJECT_ROOT` > `motor_destination_link.json` > local fallback.
- `motor_destination_link.json` is a persisted contract artifact, not a source of truth for engine code.
- `WP-mini` hygiene stays deferred by design and is not part of WP-C scope.
- The retroactive review of `WP-2026-123` is optional and non-blocking.
