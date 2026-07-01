# Work Plan - WOT-2026-016h

## Metadata
- **ID:** WOT-2026-016h
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Aislar los tests de --pre-handoff que mutaban el bus real del motor
- **Asignado a:** Builder
- **delivery_authority:** repo_motor
- **blocks:** WOT-2026-016e

## Objetivo

`tests/test_opencode_config_stability.py` lanzaba `--pre-handoff` como SUBPROCESO
contra el motor REAL (`_MOTOR_ROOT` derivado de `__file__`), lo que escribia en el
`events.jsonl` real del motor y disparaba el guard de aislamiento
(`_isolate_controller_event_bus`, `tests/conftest.py`) en TEARDOWN -> 5 ERRORS de
teardown en la suite `--level all`. Como `run_pytest_safe.py` captura fallos con
`^FAILED` y NO lineas `ERROR`, esos 5 ERRORS producen `exit_code=1` con
`failed_test_ids` VACIO -> `pre_handoff_guard.assert_canonical_suite_green`
fail-cierra (discriminante conjunto-vacio + senal-de-fallo). Esto bloquea el cierre
canonico de CUALQUIER ticket code del motor, incluido WOT-2026-016e.

## Decision Arquitectonica

Reescribir los 5 tests que ejercian `--pre-handoff` por subproceso para que corran
IN-PROCESS (`agent_controller._handle_pre_handoff`) contra un MOTOR TEMPORAL en
`tmp_path`, con `_MOTOR_ROOT`/`PROJECT_ROOT`/`WORK_PLAN`/`EXEC_LOG` monkeypatcheados.
El bus se resuelve desde `get_agent_dir()` (motor-root derivado de `__file__`), NO
redirigible por `--project-root`; la unica forma de aislarlo es apuntar el
motor-root a un repo temporal. Patron canonico ya probado en
`tests/test_pre_handoff_multirepo.py`. El 6o test (`TestLauncherNoBomDrift`) no
ejerce `--pre-handoff` -> no se toca.

## Fases

### Fase 0 - Confirmar seams (VERIFICADO EN CODIGO)
- El bus se resuelve desde `get_agent_dir()` = motor-root derivado de `__file__`
  (`agent_controller.py`), NO redirigible por `--project-root`.
- `run_pytest_safe.py` captura solo `^FAILED\s+(\S+)`, no `ERROR ...` (teardown).
- `_isolate_controller_event_bus` (`tests/conftest.py`) falla en teardown cuando un
  test muta el `events.jsonl` real.

### Fase 1 - Reescritura in-process
- Fixture `temp_motor` (`_TempMotor`): repo git real en `tmp_path`, seed de
  `.opencode/opencode.json` con bytes reales de HEAD, work_plan+exec_log committeados
  en el dest, monkeypatch de los 4 roots.
- Los 5 tests que ejercian `--pre-handoff` por subproceso -> `_pre_handoff_inprocess`
  (llama `agent_controller._handle_pre_handoff` con el bus singleton reseteado).

### Fase 2 - Verificacion (mutation-verify)
- Fichero en aislamiento con el fix: 6 passed, 0 errors.
- Mutation: revertir a `_MOTOR_ROOT` real -> vuelven los 5 errors (6 passed, 5
  errors); restaurar -> 6 passed, 0 errors.
- `events.jsonl` real SIN cambios tras la corrida (git status del path vacio).

## Criterios de aceptacion (DoD binario)

1. `tests/test_opencode_config_stability.py` en aislamiento: 6 passed, 0 errors
   (antes 6 passed, 5 errors).
2. La corrida NO muta el `events.jsonl` real del motor (git status del path vacio).
3. Suite canonica `run_pytest_safe.py --level all` sin esos 5 ERRORS de teardown +
   validate 0/0 + ruff check/format + encoding limpios.

## Files Likely Touched

- tests/test_opencode_config_stability.py

## Non-goals

- NO tocar `run_pytest_safe.py` (que capture ERROR ademas de FAILED es otro ticket).
- NO tocar `agent_controller.py` ni el guard de aislamiento del conftest.
- NO tocar el 6o test (`TestLauncherNoBomDrift`), que no ejerce `--pre-handoff`.
- NO mezclar con 016e (scope-override) ni con 016i (aislamiento de work_plan).
