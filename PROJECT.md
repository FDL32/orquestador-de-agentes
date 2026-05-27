# Project: orquestador_de_agentes
**Version:** v9.14.0
**State:** WP-2026-153 COMPLETED (add grill-with-docs skill)

## Current Cycle

- Active ticket: WP-2026-153 COMPLETED (2026-05-27).
- Mode: completed - grill-with-docs skill added.
- Outcome: pre-plan grilling is now a first-class skill with triggers `/grill-plan`, `/grill`, `grill-wp`; `PROJECT.md` and `MEMORY.md` are the default inputs, `CONTEXT.md` remains optional.

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
