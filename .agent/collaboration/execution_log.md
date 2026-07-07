# Execution Log - WOT-2026-016k

**Ticket:** WOT-2026-016k
**Estado:** COMPLETED
**Fecha:** 2026-07-07
**delivery_authority:** repo_motor

## PREFLIGHT (Manager, topologia worktree-dev)

- DEV (`orquestador_de_agentes_dev`): main, HEAD == origin/main == c799522, arbol limpio.
- PRINCIPAL (`orquestador_de_agentes`): detached, NO tocar.
- WORKSPACE (`orquestador_de_agentes_workspace`): main 6bd9aa5.

## Fase Manager: Verificacion de premisa

- `scripts/run_pytest_safe.py:461`: `_failed_re = re.compile(r"^FAILED\s+(\S+)")` — solo matchea FAILED.
- `scripts/run_pytest_safe.py:450-510` (`stream_pytest`): retorna `(returncode, failed_ids)`, sin `error_test_ids`.
- `scripts/run_pytest_safe.py:889`: `exit_code, failed_ids = stream_pytest(command)` — unpack de 2 valores.
- `scripts/run_pytest_safe.py:895`: `summary["failed_test_ids"] = failed_ids` — solo campo FAILED en last-run.json.
- `scripts/run_pytest_safe.py:925`: `write_json(LAST_RUN_JSON, summary)` — escribe schema sin error_test_ids.
- `scripts/pre_handoff_guard.py:504-528` (`assert_canonical_suite_green`): cuando `exit_code != 0` y `failed_test_ids` esta vacio, fail-cierra como "state-leak suspected" (opaque failure).
- `backlog.md:29`: WOT-2026-016h confirmo 5 ERRORs de teardown con `failed_test_ids=[]`, exit 1.
- `backlog.md:60-74`: evidencia detallada de 016h: fixture `_isolate_controller_event_bus` en `tests/conftest.py:248-284` usa `pytest.fail(pytrace=False)` en teardown -> ERROR.
- Premisa VERIFICADA: no existe `_error_re` ni `error_test_ids` en `run_pytest_safe.py`.

## Fase Manager: Creacion de work_plan.md

- work_plan.md creado en `.agent/collaboration/work_plan.md` con Estado: APPROVED.
- execution_log.md inicializado con entrada de inicio del ticket.

## Fase Builder: Inicio WOT-2026-016k

- stream_pytest (l.450): firma `-> tuple[int, list[str]]`, retorna 2 valores.
- _failed_re (l.461): solo matchea FAILED.
- failed_ids loop (l.504-510): solo construye failed_ids.
- stream_pytest return (l.510): `return returncode, failed_ids`.
- main() (l.889): `exit_code, failed_ids = stream_pytest(command)` - unpack 2.
- main() (l.895): `summary["failed_test_ids"] = failed_ids`.
- main() (l.925): `write_json(LAST_RUN_JSON, summary)`.
- NO existe _error_re ni error_test_ids.
- Caller de stream_pytest: SOLO l.889 en main().
- tests/unit/test_run_pytest_safe.py: _stub_main (l.447) patchea `lambda cmd: stream_return` donde stream_return es tupla de 2.
- Premisa CONFIRMADA: 100% coincide con work_plan.md.

## Fase 1: Implementacion en run_pytest_safe.py

- Anadido `_error_re = re.compile(r"^ERROR\s+(\S+)")` en stream_pytest (l.463).
- Anadido loop paralelo para `error_ids` despues del loop de `failed_ids`.
- Firma actualizada: `-> tuple[int, list[str], list[str]]`.
- Return actualizado: `return returncode, failed_ids, error_ids`.
- main() unpack: `exit_code, failed_ids, error_ids = stream_pytest(command)`.
- main() summary: `summary["error_test_ids"] = error_ids` anadido despues de `failed_test_ids`.
- Caller verificado: unico caller es main() l.889, actualizado correctamente.
- Segun `git diff`, scripts/run_pytest_safe.py: +24/-9 lineas.

## Fase 2: Tests en tests/unit/test_run_pytest_safe.py

- Actualizados existing _stub_main calls: `(0, [])` -> `(0, [], [])`, `(1, failing_ids)` -> `(1, failing_ids, [])`.
- Actualizado baseline test: `lambda cmd: (0, [])` -> `lambda cmd: (0, [], [])`.
- Nueva funcion `_parse_test_ids_from_lines()` replica del parser REAL (FAILED + ERROR).
- Nueva clase `TestErrorTestIdsParsing`: 7 tests para parsing de ERROR lines.
- Nueva clase `TestErrorTestIdsInSummary`: 3 tests para error_test_ids en last-run.json + 1 test focal directo a stream_pytest con Popen mock.
- _stub_main se duplico para la nueva clase (monkeypatches independientes).
- Segun `git diff`, tests/unit/test_run_pytest_safe.py: +299/-9 lineas.

## Fase 3: Quality gates

### Tests
Comando: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_run_pytest_safe.py -v`
```
44 passed in 0.54s
```

### Ruff check
Comando: `.\.venv\Scripts\python.exe -m ruff check scripts/run_pytest_safe.py tests/unit/test_run_pytest_safe.py`
```
All checks passed!
```

### Ruff format
Comando: `.\.venv\Scripts\python.exe -m ruff format --check scripts/run_pytest_safe.py tests/unit/test_run_pytest_safe.py`
```
2 files already formatted
```

## Fase 4: Mutation-verify (OBLIGATORIO)

### Paso 1: Stash source file (revertir fix, mantener tests)
```
git add scripts/run_pytest_safe.py
git stash push -- scripts/run_pytest_safe.py
```

### Paso 2: Test focal SIN fix -> debe FALLAR
Comando: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_run_pytest_safe.py::TestErrorTestIdsInSummary::test_stream_pytest_real_error_re_with_mocked_subprocess -v`
Resultado: FAILED (exit code 1) — `ValueError: not enough values to unpack (expected 3, got 2)`

### Paso 3: Restore fix
```
git stash pop
```

### Paso 4: Test focal CON fix -> debe PASS
Comando: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_run_pytest_safe.py::TestErrorTestIdsInSummary::test_stream_pytest_real_error_re_with_mocked_subprocess -v`
Resultado: PASSED (exit code 0)

**Exit codes registrados:**
- SIN fix: exit code 1 (falla como esperado)
- CON fix: exit code 0 (pasa como esperado)

## Fase 5: Commit

Comando: `$env:PATH = ".\.venv\Scripts;" + $env:PATH; git add scripts/run_pytest_safe.py tests/unit/test_run_pytest_safe.py; git commit -m "WOT-2026-016k: run_pytest_safe captura ERROR de teardown en error_test_ids (campo separado)"`

Resultado:
```
[main 1a1c000] WOT-2026-016k: run_pytest_safe captura ERROR de teardown en error_test_ids (campo separado)
2 files changed, 314 insertions(+), 9 deletions(-)
```

Hooks pre-commit: todos Passed (yaml, json, toml, merge conflicts, large files, shebangs, ast, EOF, line endings, trailing whitespace, ruff check, ruff format, history guard, encoding, claude).

## Cierre

- Commit SHA: 1a1c000
- Mensaje: `WOT-2026-016k: run_pytest_safe captura ERROR de teardown en error_test_ids (campo separado)`
- Cierre pragmatico: commit code + collab, suite valida, mutation-verify pasa. NO se ejecuto --mark-ready / --pre-handoff / --session-close (bloqueados por fix 020d, intencional).
- Desviaciones: ninguna.

## Mutation-verify preciso (re-corrido por Orquestador)

El Orquestador re-corrio el mutation-verify con mutacion precisa (no stash completo):
1. Edit `_error_re` pattern: `r"^ERROR\s+(\S+)"` -> `r"^DISABLED_MUTATION\s+(\S+)"` (mantiene 3-tuple return, solo rompe el match de ERROR)
2. Test `test_stream_pytest_real_error_re_with_mocked_subprocess` -> FAILED (exit 1): `error_ids` vacio porque `_error_re` no matchea lineas ERROR
3. Revert edit (restaurar `r"^ERROR\s+(\S+)"`)
4. Test -> PASSED (exit 0): `error_ids == ["tests/unit/test_b.py::test_teardown_err"]`

Esto verifica que la captura de ERROR via `_error_re` es la causa real (no solo el cambio de firma de return).
