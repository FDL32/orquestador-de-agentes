# Closure Model

This document defines the two closure contracts used by `orquestador_de_agentes`.

## 1. Definitions

### System Closeout

The process that neutralizes the repository as a reusable template for another project.

Goal:
- Remove ticket-specific wording from public docs.
- Keep traceability in `.agent/`.
- Leave the repository ready to be copied or published as a clean starter.
- Keep the destination ticket namespace rule documented so the next project can declare its own `Ticket prefix: XXX` in `PROJECT.md`.

### Session Closeout

The process that finalizes one operational ticket or runtime cycle inside the current repository.

Goal:
- Remove residual runtime artifacts.
- Preserve canonical traceability in `.agent/collaboration/`.
- Prepare the next runtime cycle without leaving stale cursors behind.

## 2. Responsibility Matrix

| Artifact | Session Closeout | System Closeout |
|----------|------------------|-----------------|
| `work_plan.md` | Keep canonical ticket history | Keep only neutral template wording when exported |
| `TURN.md` | Keep canonical turn history | Neutralize for template reuse |
| `STATE.md` | Keep canonical state history | Neutralize for template reuse |
| `execution_log.md` | Keep canonical execution history | Keep history in `.agent/`, not in public docs |
| `SESSION_BRIEF.md` | Regenerate minimal runtime summary | Keep minimal and neutral |
| `supervisor_state.json` | Remove if confirmed closeout | Remove or omit from exported template |
| `manager_bridge_state.json` | Remove if confirmed closeout | Remove or omit from exported template |
| `builder_lock.txt` | Remove if confirmed closeout | Remove or omit from exported template |
| `README.md` / `PROJECT.md` / `QUICKSTART.md` | Usually unchanged except for active-cycle guidance | Must be neutral and reusable |
| `.agent/` history | Preserve | Preserve |

## 3. Validation Expectations

### Session Closeout

- `python .agent\agent_controller.py --validate --json --force` passes without drift.
- Note: the standalone `scripts/session_closeout.py` utility referenced in earlier revisions was removed in `WP-2026-061` cleanup. Closeout is currently a manual canonical handoff (edit `work_plan.md` and `execution_log.md` to `COMPLETED`, regenerate `TURN.md` with `--reset-turn`, then validate). An integrated replacement is pending design.

### System Closeout

- Public docs contain no ticket-specific history.
- Public docs do not require parent-workspace knowledge.
- The repository root can be copied into another project and used as a neutral template.

## 4. Practical Workflow

### To close a session

1. Run the dry run.
2. Confirm the cleanup.
3. Regenerate the session brief.
4. Validate the canonical state.
5. **Reconcile the next-session startup chain.** Ask: did this session change
   anything the startup system describes? Concretely — canonical paths or
   commands, agent backends/models, the ticket cycle flow, or the root cause of
   a bug that `prompts/session_bootstrap.md` still presents as "expected
   behavior". If yes:
   - Update `prompts/session_bootstrap.md` so it points at the new reality
     (it points, it does not embed).
   - Update or delete affected entries in `.agent/runtime/memory/` — memory
     holds only stable knowledge; volatile state (active ticket, version,
     baseline) must NOT live there.
   - Regenerate `AUDIT.md` (`python scripts/local_audit.py`) so the volatile
     snapshot is fresh.
   If nothing startup-relevant changed, skip — do not rewrite the bootstrap as
   a ritual. Goal: a chained startup — the next session begins with bootstrap,
   memory and `AUDIT.md` all consistent with what actually happened.

### To close the system

1. Finalize the session closeout first.
2. Neutralize public docs and keep history in `.agent/`.
3. Re-run validation from the repository root.
4. Publish or copy the repository as a reusable template.
5. Ensure exported docs describe the destination namespace (`XXX-YYYY-NNN`) and where it is declared, without carrying over the motor's `WP-YYYY-NNN` history.

## 5. Examples

### Example: session closeout

- A Builder ticket finishes.
- The runtime cursor files are removed.
- `SESSION_BRIEF.md` is regenerated.
- The next ticket can start cleanly.

### Example: system closeout

- The repository is ready to be copied into another project.
- Public docs explain the template but do not mention historical tickets.
- All traceability stays inside `.agent/`.
