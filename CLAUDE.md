# Claude Code Guide

@AGENTS.md

## Role

Claude Code is a supported backend for this template and can act as Builder or Manager depending on the active ticket.
Prefer the current code and the canonical docs over memory or stale notes.
Current portable release: `v9.14.1`, dual-mode architecture complete (engine-agnostic, host-first skill precedence).
Treat this repository as standalone when editing public docs or commands; do not assume a parent workspace is available.

## Workflow

For any non-trivial change:
1. Read `PROJECT.md` and `CHANGELOG.md` first.
2. Use plan mode if the change spans multiple layers.
3. Make the smallest useful change.
4. Run the quality gates before closing the task.

If you plan to run the template from terminal, read `QUICKSTART.md` first, then `INTERACTION_MODES.md`, and follow the terminal-driven flow.

For a fresh agent onboarding (new conversation, new backend, post-compaction recovery), use the canonical bootstrap prompt at `prompts/session_bootstrap.md`. Paste it as the first message; it briefs the agent on roles, canonical files, recurring issues and behavior contract without burning context on docs.

## Useful commands

> Ver lista completa en [QUICKSTART.md sección "6. Comandos diarios"](QUICKSTART.md#6-comandos-diarios).

Comandos rápidos:
- `/agent-status` muestra el estado multi-agente actual.
- `/quality-gates` ejecuta `ruff`, `pytest-safe` y `pip-audit`.

## Rule loading

If `.claude/rules/README.md` exists, use it as a map for session-specific context modules.
If a rule conflicts with the codebase, follow the code and record the discrepancy in the project docs.
