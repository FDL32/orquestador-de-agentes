# Execution Log - WOT-2026-019h

**Ticket:** WOT-2026-019h
**Estado:** IN_PROGRESS
**Fecha:** 2026-07-07

## Fase 0: Diagnostico (Orquestador)

- Premisa verificada en codigo real:
  - `_resolve_extra_root` (guard_paths.py l.108-143) solo verifica `.exists()`,
    sin marker de repo
  - `resolve_repo_root` (claude_guard_entry.py l.37-43) SI usa `.claude` marker
  - Tests existentes (TestExtraRootDestination, 6 tests de 019a) ya crean
    `.claude` en `destino_root` pero no en `outside_root`
- Fix: anadir check `(candidate / ".claude").exists() or (candidate / ".git").exists()`
  antes de retornar el candidate en ambas fuentes (env var y link)
