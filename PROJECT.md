# Project: orquestador_de_agentes
**Version:** v9.14.0
**State:** WP-2026-143 COMPLETED (bus-backed mark-ready idempotency)

## Current Cycle

- Active ticket: WP-2026-143 COMPLETED (2026-05-26).
- Mode: idle — listo para siguiente ticket.
- Outcome: `--mark-ready` now uses bus-backed idempotency and avoids duplicate
  review cycles after drift.

## Current readiness

- The repository remains ready for terminal-driven execution.

## Source of truth

> See `[AGENTS.md](AGENTS.md)` for the canonical runtime paths and operational contract.

- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/STATE.md`
- `.agent/runtime/memory/`
- `.agent/council/`
- `.agent/agent_controller.py`
- `scripts/run_pytest_safe.py`
