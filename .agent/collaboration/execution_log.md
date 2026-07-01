# Execution Log - WOT-2026-016h

**Ticket:** WOT-2026-016h - aislar tests de --pre-handoff que mutaban el bus real
**Estado:** IN_PROGRESS
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

## Fase 3 - Gates canonicos

- Suite canonica `run_pytest_safe.py --level all`: [se ejecuta tras el commit; ver seccion Gates]
- validate --json: [se ejecuta tras el commit; ver seccion Gates]
- ruff check / ruff format --check: [ver seccion Gates]
- encoding guard: [ver seccion Gates]

## Reviews

- Review 1 (Manager, re-ejecuta gates + mutation par): [tras commit]
- Review 2 (adversarial): [tras Rev1]
