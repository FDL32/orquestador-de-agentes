# Execution Log - WOT-2026-016b

**Ticket:** WOT-2026-016b - Hook pre-commit/pre-push con INSTALL_PYTHON obsoleto: detectar/regenerar ruta de interprete inexistente (repo movido)
**Estado:** IN_PROGRESS
**HEAD al inicio:** 65af880

> execution_log de 018b (COMPLETED) preservado en `execution_log_WOT-2026-018b.md`.

---

## Bootstrap

- Ticket 016b materializado como code (delivery_authority=repo_motor).
- FLT = scripts/check_hook_interpreter.py (nuevo) + tests/test_check_hook_interpreter.py (nuevo)
  + .pre-commit-config.yaml (enganche hook manual).
- Origen: WOT-2026-017a (2026-06-30/07-01) destapo que el hook generado hardcodea INSTALL_PYTHON;
  tras mover el repo fuera de z_scripts\, la ruta quedo obsoleta y el hook caia al fallback roto.

## Fase 0: Diagnostico (VERIFICADO EN VIVO)

- Reproducido el bug en este repo a HEAD 65af880:
  - `.git/hooks/pre-commit` L7 INSTALL_PYTHON = `...\orquestador_de_agentes\.venv\Scripts\python.exe`
    -> EXISTE en disco (ok, regenerado en 017a).
  - `.git/hooks/pre-push` L7 INSTALL_PYTHON = `...\z_scripts\orquestador_de_agentes\.venv\Scripts\python.exe`
    -> NO existe (`ls` confirma No such file). Hook roto vivo.
- grep INSTALL_PYTHON / pre_commit install / hook-type sobre **/*.py -> 0 hits: ningun codigo
  gestiona esto hoy. Superficie NUEVA, no modificacion de seam existente.
- Convencion de scripts/check_*.py confirmada (check_motor_pristine.py, check_ruff_hook_scope.py):
  funciones puras + main(argv)->int, fail-closed, UTF-8/ASCII, tests con repos reales en tmp_path.

## Fase 1: Implementacion (EJECUTADA)

- `scripts/check_hook_interpreter.py`: parse_install_python (regex L7, comilla simple/doble),
  check_hook/check_all sobre HOOK_TYPES=("pre-commit","pre-push"), main con --repo-root/--hooks-dir/--fix.
  Sin --fix: exit 1 + mensaje accionable si algun interprete no existe; exit 0 si todos ok o ausentes.
  Con --fix: regenera via `sys.executable -m pre_commit install --overwrite --hook-type pre-commit
  --hook-type pre-push` y re-verifica. Nunca versiona .git/hooks/*.
- `.pre-commit-config.yaml`: hook local `check-hook-interpreter` en stage `manual` (no automatico:
  un hook automatico seria circular porque el propio hook roto no puede invocarlo con fiabilidad).

## Fase 2: Tests (barrera FAIL-sin/PASS-con, VERDE)

- `tests/test_check_hook_interpreter.py` (8 tests):
  - stale detectado por tipo (parametrizado pre-commit Y pre-push) -> exit 1. [DoD #1, #2]
  - interprete existente -> exit 0; hook ausente -> exit 0 (no falso positivo).
  - BARRERA: mismo texto de hook; solo la EXISTENCIA del interprete flipa PASS<->FAIL (borrar el
    interprete -> exit 1). [DoD #3]
  - mixto (pre-commit ok + pre-push stale) -> exit 1 (no "pasa" por tener uno bueno; forma del bug vivo).

## Evidencia de cierre (gates)

- LIVE run contra los hooks reales: `python scripts/check_hook_interpreter.py` -> exit 1, nombra
  pre-push con la ruta z_scripts inexistente (caza el bug real).
- Focal: `pytest tests/test_check_hook_interpreter.py -q` -> 8 passed.
- ruff check -> All checks passed!; ruff format --check -> already formatted.
- encoding guard sobre archivos tocados -> exit 0.
- Suite canonica run_pytest_safe.py --level all -> pendiente (debe dar exit 0, tested_commit_sha==HEAD).
- validate --json -> pendiente (0/0 tras commit).

## Estado actual

- Implementacion + tests verdes focal. PENDIENTE: commit con ID 016b (PATH saneado) -> re-correr
  suite canonica -> validate 0/0 -> pre-handoff -> mark-ready -> manager-approve.
