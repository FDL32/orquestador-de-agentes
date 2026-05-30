# Project: orquestador_de_agentes
**Version:** v9.14.1
**State:** SESSION CLOSED (2026-05-29)

## Current Cycle

- Last session closed: WP-2026-175 COMPLETED (2026-05-29). Canonical session closeout and cycle rollover.
- Last ticket: WP-2026-174 COMPLETED (2026-05-29). Persist manager review bridge checkpoint across supervisor restarts.
- Last ticket: WP-2026-173 COMPLETED (2026-05-29). Add pre-handoff helper to stage commit and checkpoint before mark-ready.
- Last ticket: WP-2026-170 COMPLETED (2026-05-29). Fix ConcurrentStateError in supervisor/review bridge.
- Last ticket: WP-2026-169 COMPLETED (2026-05-29). Session close loop bridge - `--session-close` en agent_controller.
- Last ticket: WP-2026-168 COMPLETED (2026-05-29). Session closeout orchestrator - audit, memory, archive.
- Previous ticket: WP-2026-167 COMPLETED (2026-05-29). Builder handoff safety - guard, checkpoints y recovery protocol.
- Delivery hygiene loop already in place: `delivery_hygiene_check.py` preflight + `prepush_check.py`.
- The session was closed canonically via `--session-close`, with observations, memory consolidation, and artifact archiving completed.
- `validate_ticket_prose.py` TP-06 / TP-07 detection remains active; the canonical TP Check format is still enforced.

## Current readiness

- The repository session has been closed canonically. Ready for the next cycle startup.

## Repomix Context Integration (WT-2026-182)

The system integrates `repomix` as a compressed context layer for agent bootstrapping:

- **Bootstrapping:** On session start, `launch_agent_terminals.ps1` runs `npx repomix --compress`
  to generate `.agent/context/repomix.xml`, which is injected as an explicit context file for
  the Builder agent (via `-f` flag). Gives agents instant "X-ray vision" of the workspace.
- **Config:** A `repomix.config.json` template is provisioned to the workspace root by
  `install_agent_system.py` (from `agent_system/templates/repomix.config.json`).
- **Repo-Compare:** The `skills/repo-compare/` skill uses repomix locally (`.session/repomix_local.xml`)
  and optionally for remote repos (`.session/repomix_remote.xml`) to accelerate comparisons.
- **Failure tolerance:** If `npx repomix` fails or times out (>15s), the session continues
  without the compressed context — no blocking.

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
