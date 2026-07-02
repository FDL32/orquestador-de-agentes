# AUDIT - WOT-2026-016b

**Ticket:** WOT-2026-016b - Hook pre-commit/pre-push con INSTALL_PYTHON obsoleto: detectar/regenerar ruta de interprete inexistente (repo movido)
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion; Fase 0
  diagnostica, Fase 1 crea `scripts/check_hook_interpreter.py` + enganche manual, Fase 2
  crea el test. Ninguna fase pide crear y borrar el mismo artefacto ni versionar
  `.git/hooks/*` (declarado non-goal).
- TP-02: verificado - los 7 criterios de aceptacion citan comandos y salidas literales
  (`python scripts/check_hook_interpreter.py` exit 1 nombrando pre-push, `pytest
  tests/test_check_hook_interpreter.py` 8 passed, `ruff check`/`ruff format --check`,
  `check_encoding_guard.py` exit 0, `run_pytest_safe.py --level all` exit 0,
  `validate --json` 0/0), no descripciones subjetivas.
- TP-03: verificado - el Objetivo enumera los dos hooks concretos (pre-commit, pre-push)
  con sus rutas reales verificadas en vivo; Files Likely Touched enumera los 3 archivos
  (2 nuevos + 1 modificado); Non-goals enumera lo excluido (versionar hooks, arreglar solo
  pre-push a mano, gate automatico, remoto/historia, tickets 016c/016e/016g/016m).
- TP-04: verificado - no hay lenguaje blando en Objetivo, Fases ni Criterios; la decision
  de stage `manual` (no automatico, por circularidad) queda registrada como decision cerrada
  con su razon, no como condicion abierta.
- TP-05: verificado - PLAN, AUDIT y execution_log describen la misma superficie (un check +
  su test + enganche manual), el mismo discriminante (existencia en disco del INSTALL_PYTHON)
  y la misma barrera FAIL-sin/PASS-con; el AUDIT no introduce condiciones ausentes del PLAN.

## Blockers

- Ninguno. Implementacion y tests focales verdes; barrera verificada. Pendiente solo el commit
  unico con ID 016b (PATH saneado), re-correr suite canonica sobre HEAD, y handoff canonico.

## Evidencia esperada al cierre

- `python scripts/check_hook_interpreter.py` -> exit 1 nombrando pre-push (bug real cazado);
  con `--fix` regenera y re-verifica.
- `pytest tests/test_check_hook_interpreter.py -q` -> 8 passed (incluye barrera y caso mixto).
- `ruff check` + `ruff format --check` sobre los 2 .py -> limpios.
- `check_encoding_guard.py` exit 0 sobre los archivos tocados.
- `run_pytest_safe.py --level all` -> exit 0, tested_commit_sha == HEAD del commit entregado.
- `validate --json --project-root <motor>` -> 0 errors / 0 warnings.
- Commit unico (2 nuevos + .pre-commit-config.yaml + artefactos de colaboracion) con ID 016b.
