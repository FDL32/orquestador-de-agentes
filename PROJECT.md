# Project: orquestador_de_agentes
**Version:** v9.14.1
**State:** SESSION ACTIVE (2026-05-29)

## Current Cycle

- Active ticket: none.
- Last ticket: WP-2026-166 COMPLETED (2026-05-29). Manager watchdog for stale READY_FOR_REVIEW relaunch.
- Delivery hygiene loop already in place: `delivery_hygiene_check.py` preflight + `prepush_check.py`.
- WP-2026-167 COMPLETED (2026-05-29). Builder handoff safety - guard, checkpoints y recovery protocol.
- Current cycle is closed and the repository is ready for the next planning cycle.
- `validate_ticket_prose.py` TP-06 / TP-07 detection remains active; the canonical TP Check format is still enforced.

## Current readiness

- The repository is idle and ready for the next planning cycle.

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
