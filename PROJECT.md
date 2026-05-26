# Project: orquestador_de_agentes
**Version:** v9.14.0
**State:** WP-2026-146 COMPLETED (human gate timeout and expiry)

## Current Cycle

- Active ticket: WP-2026-146 COMPLETED (2026-05-26).
- Mode: closed - canonical human gate timeout wiring completed.
- Outcome: the existing approval-resolution path now bounds HUMAN_GATE without adding a new terminal state.

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
