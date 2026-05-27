# Project: orquestador_de_agentes
**Version:** v9.14.0
**State:** WP-2026-150 COMPLETED (project scanner with import map)

## Current Cycle

- Active ticket: none (WP-2026-150 completed on 2026-05-27).
- Mode: idle - waiting for the next approved work plan.
- Outcome: destination projects now have a token-efficient scanner path with real importMap extraction.

## Current readiness

- The repository remains ready for terminal-driven execution.

## Source of truth

> See `[AGENTS.md](AGENTS.md)` for the canonical runtime paths and operational contract.

- Destination projects declare `Ticket prefix: XXX` in their local `PROJECT.md` (or via `--install --prefix XXX`) and use `XXX-YYYY-NNN`; this motor keeps `WP-YYYY-NNN`.

- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/STATE.md`
- `.agent/runtime/memory/`
- `.agent/council/`
- `.agent/agent_controller.py`
- `scripts/run_pytest_safe.py`
