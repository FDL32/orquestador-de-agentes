# Execution Log - WOT-2026-016e

**Ticket:** WOT-2026-016e - scope-override deja de escribir rutas absolutas locales
**Estado:** IN_PROGRESS
**HEAD al inicio del ticket:** 17244fc (tras cierre de 016h)

---

## Fase 0 - Seams confirmados (VERIFICADO EN CODIGO)

- `.agent/scope_gate.py:record_scope_override` (pre-fix) formateaba
  `f"Affected files: {', '.join(sorted(problem_files))}"` con rutas absolutas.
- `problem_files` = `out_of_scope | missing_from_diff`, paths absolutos resueltos
  (`str((root / name).resolve())`).
- DOS call sites en el controller:
  - `agent_controller.py:430` `_record_scope_override` (injected fn en l.443).
  - `agent_controller.py:3179` checkpoint scope.
  Ambos delegan en `scope_gate.record_scope_override` -> fix unico en scope_gate.py
  cubre los dos; el controller solo pasa `repo_root` en el choke point (l.430).
- Test existente: `tests/unit/test_scope_gate.py`.

## Fase 1 - Fix minimo

- `.agent/scope_gate.py`: helper `_relativize_scope_path(path, repo_root)`
  (repo -> `<REPO_ROOT>/rel/path` posix; fuera/no relativizable -> basename).
  `record_scope_override` gana keyword-only `repo_root: Path | str | None = None`;
  relativiza cada problem_file antes de formatear la nota.
- `.agent/agent_controller.py:430`: `_record_scope_override` pasa
  `repo_root=PROJECT_ROOT.resolve()` (choke point unico -> cubre ambas call sites).

## Fase 2 - Regresion + mutation-verify (VERIFICADO EN TEST)

### T-regresion (tests/unit/test_scope_gate.py::TestRecordScopeOverrideNoAbsolutePaths)
4 casos: dentro del repo -> `<REPO_ROOT>/rel`; el username nunca sobrevive; fuera
del repo -> basename; sin repo_root -> basename. Con el fix: 21 passed (exit 0).

### Mutation-verify (par de exit-codes, re-emitido en el replay closeout)
```
mutation-verify:
  sin_fix:  command: pytest tests/unit/test_scope_gate.py::TestRecordScopeOverrideNoAbsolutePaths -q
            exit_code: 1   # 4 failed; la nota generada contiene la ruta absoluta con username
  con_fix:  command: pytest tests/unit/test_scope_gate.py::TestRecordScopeOverrideNoAbsolutePaths -q
            exit_code: 0   # 4 passed
```
Evidencia del bug vivo (sin fix): la asercion falla mostrando
`Affected files: C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\x\y.py`
(ruta absoluta con username presente). Restaurado -> 4 passed.

## Fase 3 - DoD

### DoD(1) rutas relativas en el log: cubierto por T-regresion. PASS.

### DoD(2) classify_publication no marca PUBLISH_WITH_REDACTIONS
Nota generada por el NUEVO `_relativize_scope_path` con paths absolutos de entrada:
```
GENERATED NOTE: Scope override: out of scope reason. Affected files: <REPO_ROOT>/scripts/foo.py, <REPO_ROOT>/tests/bar.py
absolute-path/username leak: False
uses <REPO_ROOT> marker    : True
```
La ruta absoluta con username NO aparece; el marcador `<REPO_ROOT>/...` no matchea
el patron `[A-Za-z]:\Users\...` de classify_publication.py. PASS.

### DoD(3) gates: ver seccion Gates canonicos.

## Gates canonicos [se completa tras el commit + suite]

- Suite canonica run_pytest_safe --level all: [tras commit]
- validate --json: [tras commit]
- ruff check/format: All checks passed / already formatted (exit 0) sobre scope_gate.py,
  agent_controller.py, test_scope_gate.py.
- encoding guard (3 .py + work_plan + PLAN): exit 0.

## Nota de alcance (forward-looking)

El fix 016e relativiza los overrides FUTUROS. Las notas historicas que YA contienen
rutas absolutas (incl. la nota de scope-override de 016h en el commit 17244fc) NO se
reescriben aqui: eso es responsabilidad de 016d/016g (filter-repo). 016e cierra la
FUENTE que las genera.

## Reviews

- Review 1 (Manager): [tras commit]
- Review 2 (fresh-context, gate de scope = alto blast-radius G3): [tras Rev1]
