# Plan de Trabajo: Barrera state_leak + basetemp fuera del repo

## Metadata
- **ID:** WOT-2026-020f
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-07
- **delivery_authority:** repo_motor

## Objetivo

Dos hallazgos de la sesion 020d+020f:
1. `check_canonical_state_leak` solo cubria STATE/TURN/work_plan/execution_log,
   NO `*_WOT-*.md` -> un staged deletion de AUDIT_WOT-* no era detectado.
2. `basetemp` de `run_pytest_safe` vivia en `.agent/runtime/pytest-safe/run-*`
   (DENTRO del repo motor) -> `tmp_path` dentro del motor -> staged changes
   visibles para `resolve_evidence` (bus/evidence.py) -> falsos fallos.

## Files Likely Touched
- `scripts/run_pytest_safe.py`
- `tests/unit/test_run_pytest_safe.py`

## Criterios binarios (DoD)
- [x] Un staged deletion de `*_WOT-*.md` durante la suite es detectado por state-leak
- [x] Staged changes del motor NO son visibles para `resolve_evidence` en tests
      con `project_root=tmp_path` (basetemp fuera del repo)
- [x] MUTATION: revertir -> vuelve el falso fallo / el deletion no detectado

## Implementacion

**Fix (a):** `snapshot_canonical_state` ahora tambien captura `*_WOT-*.md` via
`collab.glob("*_WOT-*.md")`. `check_canonical_state_leak` no cambia (ya compara
todo el snapshot).

**Fix (b):** `make_run_dir` ahora usa `Path(tempfile.gettempdir()) / "pytest-safe"`
como base en lugar de `RUNTIME_DIR`. Basetemp fuera del repo motor -> `tmp_path`
fuera del motor -> staged changes del motor no visibles para `resolve_evidence`.

## Mutation-verify
- (a) Deshabilitar captura `*_WOT-*.md` (`continue`) -> 2 tests FAIL
- (b) Revertir `make_run_dir` a `RUNTIME_DIR / run-*` -> 2 tests FAIL
- Restaurar ambos -> 50/50 pasan

## Tradeoff
Basetemp en `tempfile.gettempdir()` mide 9:04 vs 7:24 en `RUNTIME_DIR` (wall-clock
de `run_pytest_safe --level all`, 3537 tests). Delta: +100s (~22.5%) por IO/antivirus.
Es aceptable: correctness (staged changes no visibles) > velocidad en gate de cierre.

## Non-goals
- No cambiar la logica de `resolve_evidence` (bus/evidence.py) ni de `check_canonical_state_leak`
- No mover `RUNTIME_DIR` entero (solo basetemp); los reportes de last-run siguen en `.agent/runtime/`
- No optimizar la velocidad del basetemp en tempfile (el tradeoff es aceptado)

## Decision Arquitectonica
Basetemp fuera del repo motor via `tempfile.gettempdir()` en lugar de un subdirectorio
del repo. Motivo: el problema raiz es que `tmp_path` (basetemp de pytest) vive dentro
del repo motor, haciendo que `git diff --cached` con `cwd=tmp_path` vea staged changes
del motor real. Mover solo basetemp (no RUNTIME_DIR) resuelve el problema sin romper
la localizacion de last-run.json/run logs que siguen en `.agent/runtime/pytest-safe/`.
