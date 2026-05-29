# Project: orquestador_de_agentes
**Version:** v9.14.1
**State:** SESSION ACTIVE (2026-05-29)

## Current Cycle

- Active ticket: WP-2026-171 IN_PROGRESS (2026-05-29). Builder handoff checkpoint association enforcement.
- Last ticket: WP-2026-170 COMPLETED (2026-05-29). Fix ConcurrentStateError in supervisor/review bridge.
- Last ticket: WP-2026-169 COMPLETED (2026-05-29). Session close loop bridge - `--session-close` en agent_controller.
- Last ticket: WP-2026-168 COMPLETED (2026-05-29). Session closeout orchestrator - audit, memory, archive.
- Previous ticket: WP-2026-167 COMPLETED (2026-05-29). Builder handoff safety - guard, checkpoints y recovery protocol.
- Delivery hygiene loop already in place: `delivery_hygiene_check.py` preflight + `prepush_check.py`.
- New cycle focuses on making `--mark-ready` fail closed unless the checkpoint M3 is associated with the delivered commit.
- `validate_ticket_prose.py` TP-06 / TP-07 detection remains active; the canonical TP Check format is still enforced.

## Current readiness

- The repository is in the WP-2026-171 implementation cycle.

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
