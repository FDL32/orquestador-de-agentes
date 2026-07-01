# Execution Log - WOT-2026-016h

**Ticket:** WOT-2026-016h - aislar tests de --pre-handoff que mutaban el bus real
**Estado:** COMPLETED
**HEAD al inicio:** f3db5e9eed4c3b05b35c739f529f52f88742ad37

---

## Fase 0 - Seams confirmados (VERIFICADO EN CODIGO)

- El event bus se resuelve desde `get_agent_dir()` = motor-root derivado de
  `__file__` en `agent_controller.py`; NO redirigible por `--project-root`. La
  unica forma de aislarlo es apuntar el motor-root a un repo temporal.
- `scripts/run_pytest_safe.py` captura fallos con `^FAILED\s+(\S+)`; NO matchea
  lineas `ERROR ...` de teardown. 5 ERRORS + 0 FAILED -> exit 1 con
  `failed_test_ids` vacio -> `pre_handoff_guard.assert_canonical_suite_green`
  fail-cierra (discriminante conjunto-vacio + senal-de-fallo).
- Guard de aislamiento: `_isolate_controller_event_bus` (`tests/conftest.py`) falla
  en teardown cuando un test muta el `events.jsonl` real.
- Patron canonico de aislamiento: `tests/test_pre_handoff_multirepo.py`.

## Fase 1 - Reescritura in-process

- Fixture `temp_motor` (`_TempMotor`): repo git real en `tmp_path`, seed de
  `.opencode/opencode.json` con los bytes reales de HEAD, work_plan+exec_log
  committeados en el dest, monkeypatch de `_MOTOR_ROOT`/`PROJECT_ROOT`/
  `WORK_PLAN`/`EXEC_LOG`.
- Los 5 tests que ejercian `--pre-handoff` por SUBPROCESO contra el motor real ->
  reescritos a `_pre_handoff_inprocess` (llama `agent_controller._handle_pre_handoff`
  con el singleton `event_bus` reseteado, gobernado por el `_MOTOR_ROOT` temporal).
- El 6o test (`TestLauncherNoBomDrift`) no ejerce `--pre-handoff` -> no se toca.

## Fase 2 - Verificacion + mutation-verify

### Fichero en aislamiento (con el fix)
```
.venv/Scripts/python.exe -m pytest tests/test_opencode_config_stability.py -q
6 passed in 3.52s
```
Exit code: 0. `events.jsonl` real SIN cambios (git status del path vacio).

### Mutation-verify (par de exit-codes, re-emitido en el replay closeout)
```
mutation-verify:
  sin_fix:  command: .venv/Scripts/python.exe -m pytest tests/test_opencode_config_stability.py -q
            exit_code: 1     # 6 passed, 5 errors de teardown (bus real mutado)
  con_fix:  command: .venv/Scripts/python.exe -m pytest tests/test_opencode_config_stability.py -q
            exit_code: 0     # 6 passed, 0 errors
```
Secuencia: revertir la reescritura (`git stash push -- tests/test_opencode_config_stability.py`)
-> pre-fix con `_MOTOR_ROOT` real -> `6 passed, 5 errors`, exit 1 (vuelven los 5
ERRORS de teardown con el mensaje "Test mutated the real motor event bus and was
isolated"). Restaurar (`git stash pop`) -> `6 passed, 0 errors`, exit 0.
Conclusion: la reescritura in-process elimina realmente los 5 ERRORS de teardown.

## Fase 3 - Gates canonicos (VERIFICADO)

- Commit: 467fcdf ("WOT-2026-016h: aislar tests de --pre-handoff...").
- Suite canonica `run_pytest_safe.py --level all` @ tested_commit_sha=467fcdf (==HEAD):
  status=finished, exit_code=0, level=all, args_mode=default_discovery,
  failed_test_ids=[]. Los 8 baseline_failed_test_ids (TestPreHandoff +
  TestBuilderBriefExclusion) que estaban rojos por work_plan sucio AHORA pasan
  (confirma la hipotesis 016i: commitear el work_plan los limpia). Los 5 ERRORS de
  teardown de test_opencode_config_stability.py desaparecieron.
- validate --json --project-root .: 0 errors / 0 warnings (exit 0).
- ruff check tests/test_opencode_config_stability.py: All checks passed (exit 0).
- ruff format --check: 1 file already formatted (exit 0).
- encoding guard (test + STATE + work_plan + execution_log): exit 0.

## Reviews (VERIFICADO)

- Review 1 (Manager, verificacion mecanica independiente): commit con ticket id OK;
  git show --name-only 467fcdf = 4 archivos (test file + STATE/execution_log/work_plan
  live surfaces); UNICO .py tocado = tests/test_opencode_config_stability.py (== FLT);
  sin scope creep. APROBADO.
- Review 2 (adversarial, >=2 senales nuevas frente a Rev1):
  1) inspeccion de diff: `--pre-handoff` remanente solo en docstrings/comentarios y el
     helper in-process; `_MOTOR_ROOT` a nivel modulo es SOLO semilla (git show
     HEAD:.opencode) + monkeypatch (l.146) al motor temporal; sin subproceso al motor real.
  2) bus/events: events.jsonl real SIN mutar tras el `--level all` completo (git status
     del path vacio); ultimo evento pre-handoff = seq 25 (bootstrap 016h), sin eventos
     inyectados por tests.
  3) git-history: `git show --name-only 467fcdf` NO toca produccion (scope_gate/
     agent_controller/motor_checkpoint/scripts intactos); diff = test-isolation puro.
  Sin counterexample. 016h NO es alto blast-radius (solo internals de test, sin codigo
  de produccion/gate/bus) -> fresh-context Rev2 no exigido por G3. APROBADO.
- decision artifact: .agent/runtime/reviews/decision_WOT-2026-016h.json = APROBADO.

## Handoff (G7) - VERIFICADO EN BUS

- --pre-handoff --project-root . --json --force: status=success (M3 recreado a HEAD).
- --mark-ready: scope-override aplicado (arbol limpio -> heuristica de commits recientes
  sobre-captura .gitignore [f3db5e9 chore] + pre_handoff_guard.py/test_pre_handoff_guard.py
  [d8dd16c 017a COMPLETED], ajenos a 016h). Eventos reales: BUILDER_EXIT (seq 26) +
  STATE_CHANGED IN_PROGRESS->READY_FOR_REVIEW (seq 27 BUILDER, seq 28 SUPERVISOR).
  Estado derivado: READY_FOR_REVIEW.


Scope override: 016h delivery is commit 467fcdf touching only tests/test_opencode_config_stability.py (the FLT). Clean-tree recent-commit heuristic over-captured .gitignore (f3db5e9 chore, closed) and scripts/pre_handoff_guard.py + tests/test_pre_handoff_guard.py (d8dd16c WOT-2026-017a, COMPLETED). No 016h change touches those.. Affected files: C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\.gitignore, C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\scripts\pre_handoff_guard.py, C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\tests\test_pre_handoff_guard.py

Manager approved canonical closeout for WOT-2026-016h