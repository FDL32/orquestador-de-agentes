# Execution Log: WOT-2026-020f

## Ticket
- **ID:** WOT-2026-020f
- **deliverable_type:** code
- **Scope:** motor/pytest-safe-basetemp-isolation

## Fase 0 - Verificacion de premisa (2026-07-07)

**Premisa (1):** `check_canonical_state_leak` solo cubre 4 archivos, no `*_WOT-*.md`.
- VERIFICADO: `snapshot_canonical_state` (run_pytest_safe.py:746) itera
  `("STATE.md", "TURN.md", "work_plan.md", "execution_log.md")` — sin glob.
- Un staged deletion de `AUDIT_WOT-*` no seria detectado por la barrera.

**Premisa (2):** `basetemp` vive dentro del repo motor.
- VERIFICADO: `RUNTIME_DIR = AGENT_DIR / "runtime" / "pytest-safe"` (l.70).
- `make_run_dir()` (l.367) retorna `RUNTIME_DIR / f"run-{stamp}-{pid}"`.
- `select_test_runner` (l.433) pasa `--basetemp={run_dir}` a pytest.
- `resolve_evidence` (bus/evidence.py:107-109) ejecuta `git diff --cached`
  con `cwd=motor_root` -> ve staged changes del motor.
- Un test con `project_root=tmp_path` (dentro del motor via basetemp) ve
  staged changes del motor real -> falsos fallos en `test_*review_bridge*`.

**Premisa CONFIRMADA.**

## Implementacion

**Fix (a):** `snapshot_canonical_state` anade `collab.glob("*_WOT-*.md")` para
capturar artefactos WOT. `check_canonical_state_leak` no cambia (ya compara
todo el snapshot dict).

**Fix (b):** `make_run_dir` usa `Path(tempfile.gettempdir()) / "pytest-safe"`
como base. `import tempfile` anadido. Basetemp fuera del repo motor.

**Archivos modificados:**
- `scripts/run_pytest_safe.py`: +12 lineas (import tempfile, glob WOT, basetemp)
- `tests/unit/test_run_pytest_safe.py`: +65 lineas (5 tests en 2 clases nuevas)

## Gates

- ruff check: All checks passed! (PERF203 suprimido con noqa en glob loop)
- ruff format: 2 files left unchanged
- Tests focales (run_pytest_safe): 50 passed, 0 failed
- validate_agent_config.py: Configuration valid - all checks passed
- Suite canonica --level all: 3537 passed, 47 skipped, 0 failed (544s)
  - 5 tests mas que antes (3532) = los 5 nuevos
  - ~22% mas lento por basetemp en tempfile (tradeoff aceptado)

## Mutation-verify (orquestador sobre repo real)

**Fix (a):** Deshabilitar captura `*_WOT-*.md` (`continue` en el loop)
- `test_wot_file_deletion_detected` -> FAILED (AUDIT_WOT no en snapshot)
- `test_wot_file_content_change_detected` -> FAILED (PLAN_WOT no en leaked)
- `test_no_wot_files_no_leak` -> PASSED (no depende de WOT capture)
- Restaurar -> 3/3 PASSED

**Fix (b):** Revertir `make_run_dir` a `RUNTIME_DIR / run-*`
- `test_make_run_dir_outside_runtime_dir` -> FAILED (basetemp bajo RUNTIME_DIR)
- `test_make_run_dir_in_tempdir` -> FAILED (basetemp no bajo tempfile)
- Restaurar -> 2/2 PASSED

**Veredicto:** mutation-verify confirma ambos fixes.

## Commits

- `WOT-2026-020f: state_leak cubre *_WOT-*.md + basetemp fuera del repo (tempfile)`

## Decision

APROBADO para cierre pragmatico. Ambos fixes son fail-safe (glob no rompe si no
hay WOT files; basetemp en tempfile es estandar). Tradeoff de velocidad aceptado:
correctness > velocidad en gate de cierre.
