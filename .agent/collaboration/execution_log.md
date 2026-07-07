# Execution Log - WOT-2026-019h

**Ticket:** WOT-2026-019h
**Estado:** COMPLETED
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

## Fase 1: Implementacion

- Anadido `_has_repo_marker(candidate)` en guard_paths.py (verifica .claude o .git)
- Modificadas ambas fuentes en `_resolve_extra_root`: env var (l.140) y link (l.156)
- 3 tests nuevos en TestExtraRootDestination:
  - test_extra_root_without_marker_rejected (dir sin marker -> bloqueado)
  - test_extra_root_with_git_marker_accepted (dir con .git -> aceptado)
  - test_link_destination_without_marker_rejected (link sin marker -> bloqueado)

## Mutation-verify (Orquestador)

- CON fix: 9 passed (6 existentes + 3 nuevos), exit 0
- SIN fix (revertido): 2 FAILED (dir sin marker aceptado, link sin marker aceptado),
  1 PASSED (test positivo .git), exit 1
- Barrera confirmada real (no placebo)

## Gates

- Tests: pytest tests/test_guard_paths.py::TestExtraRootDestination -> 9 passed
- Ruff: ruff check .agent/hooks/guard_paths.py tests/test_guard_paths.py -> 4 E501 pre-existentes (ninguno en lineas tocadas)
- Suite canonica: run_pytest_safe.py --level all -> 3507 passed, 47 skipped, exit 0, tested_commit_sha=02b5dbd
- Validate: 0 errors / 0 warnings


Scope override: origin/main..HEAD = 4 commits (b651ea8 019l code + 162ed55 019l collab + 237879f 019h code + 02b5dbd+c4c9f22 019h collab). git show --name-only 237879f = guard_paths.py, test_guard_paths.py (FLT match). git status --porcelain = empty.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019k.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019p.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019r.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019s.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019u.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019r.md, <REPO_ROOT>/.agent/motor_checkpoint.py, <REPO_ROOT>/.agent/scope_gate.py, <REPO_ROOT>/bus/supervisor.py, <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/scripts/setup_dev_worktree.ps1, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_approval_state_revision_and_skill_access.py, <REPO_ROOT>/tests/test_setup_dev_worktree_script.py, <REPO_ROOT>/tests/unit/test_run_gates_dispatch.py, <REPO_ROOT>/tests/unit/test_scope_gate.py

Manager approved canonical closeout for WOT-2026-019h