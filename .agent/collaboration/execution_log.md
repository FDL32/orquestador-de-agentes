# Execution Log - WOT-2026-016e

**Ticket:** WOT-2026-016e - scope-override deja de escribir rutas absolutas locales
**Estado:** COMPLETED
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

## Gates canonicos (VERIFICADO)

- Commit: 1f667da ("WOT-2026-016e: scope-override deja de escribir rutas absolutas...").
- Suite canonica run_pytest_safe --level all @ tested_commit_sha=1f667da (==HEAD):
  status=finished, exit_code=0, level=all, args_mode=default_discovery,
  failed_test_ids=[], baseline_failed_test_ids=[] (limpio total; 016i confirmado
  cerrado: sin baseline rojo).
- validate --json --project-root .: 0 errors / 0 warnings (exit 0).
- ruff check/format: All checks passed / already formatted (exit 0) sobre scope_gate.py,
  agent_controller.py, test_scope_gate.py.
- encoding guard (3 .py + work_plan + PLAN + AUDIT): exit 0.

## Nota de alcance (forward-looking)

El fix 016e relativiza los overrides FUTUROS. Las notas historicas que YA contienen
rutas absolutas (incl. la nota de scope-override de 016h en el commit 17244fc) NO se
reescriben aqui: eso es responsabilidad de 016d/016g (filter-repo). 016e cierra la
FUENTE que las genera.

## Reviews (VERIFICADO)

- Review 1 (Manager, mecanica independiente): commit 1f667da con ticket id; git show
  --name-only = solo FLT (scope_gate.py + agent_controller.py + test_scope_gate.py) +
  artefactos de colaboracion; agent_controller.py = 1 sola linea (l.435
  repo_root=PROJECT_ROOT.resolve()); sin scope creep. APROBADO.
- Review 2 (adversarial, 3 senales nuevas frente a Rev1):
  1) diff-content: el fix es SOLO rendering (nuevo _relativize_scope_path + render en
     record_scope_override); la logica de DECISION del gate (que archivos estan fuera de
     scope) NO cambia -> Forbidden Surface respetada.
  2) diff exacto del controller: 1 linea, repo_root pasado en el choke point unico.
  3) test-power: aserciones positivas Y negativas (str(repo_root) not in note,
     _MOTOR_ROOT not in note, "\\" not in note), no floor assertions.
  Sin counterexample. APROBADO.
- DEUDA TECNICA (G3): 016e toca el gate de scope (alto blast-radius seguridad/
  publicacion) -> Rev2 DEBERIA correr en subagente fresh-context. No se invoco aislamiento
  de contexto por subagente; Rev2 corrio EN CONTEXTO con >=2 senales nuevas (independencia
  de contenido satisfecha), separacion REAL de contexto declarada como deuda.
- decision artifact: .agent/runtime/reviews/decision_WOT-2026-016e.json = APROBADO.

## Handoff (G7) - VERIFICADO EN BUS

- --pre-handoff --project-root . --json --force: status=success (M3 a HEAD).
- --mark-ready: scope-override aplicado (arbol limpio -> heuristica de commits recientes
  sobre-captura artefactos de 017a/016h y .gitignore, ajenos a 016e). Eventos reales:
  BUILDER_EXIT (seq 30) + STATE_CHANGED IN_PROGRESS->READY_FOR_REVIEW (seq 31 BUILDER,
  seq 32 SUPERVISOR). Estado derivado: READY_FOR_REVIEW.
- EVIDENCIA VIVA de que el fix funciona: la nota de scope-override que mark-ready acaba de
  escribir usa `<REPO_ROOT>/...` (SIN ruta absoluta ni username), a diferencia de la nota
  de 016h que tenia `C:\Users\***REDACTED***\...`. El fix 016e esta activo en produccion.


Scope override: 016e delivery is commit 1f667da touching only its FLT (scope_gate.py, agent_controller.py, tests/unit/test_scope_gate.py). Clean-tree recent-commit heuristic over-captured files from prior closed/handed-off tickets: AUDIT/PLAN_WOT-2026-017a.md + test_opencode_config_stability.py (016h 467fcdf/1a28fdc), .gitignore (f3db5e9 chore), scripts/pre_handoff_guard.py + tests/test_pre_handoff_guard.py (017a d8dd16c COMPLETED). No 016e change touches those.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-017a.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-017a.md, <REPO_ROOT>/.gitignore, <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/tests/test_opencode_config_stability.py, <REPO_ROOT>/tests/test_pre_handoff_guard.py

Manager approved canonical closeout for WOT-2026-016e