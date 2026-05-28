# Project: orquestador_de_agentes
**Version:** v9.14.1
**State:** SESSION CLOSED (2026-05-28)

## Current Cycle

- Active ticket: WP-2026-162 COMPLETED (2026-05-28). Canonical closeout published.
- Ticket quality loop automation added: `ticket-anti-patterns.md`, `plan-quality-checklist.md`,
  `validate_ticket_prose.py`, and `warnings.ticket_prose` in `--validate`.
- CHANGELOG updated with the WP-2026-162 closeout entry.
- Hardening: `.claude/security-patterns.json` + `.claude/claude-security-guidance.md` added as
  preparation for security-guidance plugin.
- `bui-self-audit` updated with Paso 4b contract rules and deduplication cleanup.

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
