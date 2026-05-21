# Project state

- Project: `orquestacion_agentes`
- Version: `v9.14.0`
- State: WP-2026-123 COMPLETED (Workspace minimo del destino - enlace motor-destino).
- Last review: 2026-05-20
- Mission: keep the central motor clean, versioned once, and externally referenced
  - The repo is the unique source of operational code (motor central).
  - Destination projects keep only their `.agent/` workspace (state, memory, events, config).
  - The installer prepares the destination to consume the external motor.

## Current Cycle

- Active ticket: WP-2026-123 COMPLETED (Workspace minimo del destino).
- Mode: implementation / Builder turn completed.
- Builder backend: OpenCode (model: opencode-go/qwen3.5-plus).
- Manager backend: OpenCode (model: configurable via agents.json).
- Target model: Qwen3.5 Plus [NO VERIFICADO como provider/model].
- Outcome: workspace minimo implantado con archivo de enlace motor-destino.
- Manifiestos, documentacion e instalador alineados con el contrato del enlace.

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

- Central motor: operational code lives once in `orquestacion_agentes/`.
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

Objetivo: mantener `orquestacion_agentes/` como motor central unico y abrir el proyecto de destino como workspace separado, con su propio `.agent/` minimo.

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
- Mantener el motor en `orquestacion_agentes/` y el proyecto destino limpio.
- La operacion debe seguir funcionando con el mismo contrato canonico de bus y colaboracion.

### Regla de secuencia
- Consolidar/publicar primero la base estable actual.
- Despues ejecutar WP-A.
- Luego WP-B.
- Finalmente WP-C.
