# Plan de Trabajo: collect_system_health degrada state-leak-only a WARN (no critical)

## Metadata
- **ID:** WOT-2026-021m
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** BAJA
- **Asignado a:** Builder

## Objetivo
`collect_system_health.py` marca `pytest_safe_last_run_nonzero` como automatic_critical
leyendo el `exit_code` CRUDO de `last-run.json`, sin distinguir un fallo de test REAL
de un exit-1 que viene SOLO del `state_leak` de proyecciones GITIGNORED
(`AUDIT_*`/`STRATEGY_*`). Fix: leer tambien `failed_test_ids`/`error_test_ids`/
`state_leak` y degradar a WARN cuando `exit!=0 AND failed==[] AND error==[] AND
state_leak!=[]`; mantener el critical cuando hay `failed`/`error` ids.

## Contexto
VIVIDO en el cierre de sesion 2026-07-10: last-run.json (run-20260710-011902) tenia
`exit_code:1`, `failed_test_ids:[]`, `error_test_ids:[]`,
`state_leak:[AUDIT_WOT-2026-021d.md, STRATEGY_WOT-2026-021d.md]` -> critical FALSO que
obligo a re-correr la suite (~3min) solo para limpiar el registro. Es el ESPEJO de la
leccion "el wrapper da exit 0 aunque haya 1 failed": aqui da exit 1 sin ningun failed.
El exit code del wrapper NO es un veredicto de suite.

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (verificado in-vivo 2026-07-10)

### CAMBIAR (`scripts/collect_system_health.py`)
- `_read_pytest_last_run` (l.128-141): el dict devuelto incluye tambien
  `failed_test_ids`, `error_test_ids` y `state_leak`, LEIDOS CON `.get(...)` SEGURO
  (correccion plan-audit): `d.get("failed_test_ids", [])`, `d.get("error_test_ids",
  [])`, `d.get("state_leak")` (ausente/None si no hubo leak; el productor
  run_pytest_safe.py:937-939 SOLO escribe state_leak si `leaked` es truthy -> nunca
  es `[]`). Hoy solo devuelve `exit_code`/`finished_at`.
- Logica de critical (l.311-312). **ORDEN EXPLICITO DE RAMAS (correccion plan-audit,
  failed/error GANA a state_leak)** y **TRUTHINESS, NUNCA `!= []`** (BLOCKER plan-audit:
  `None != []` es True -> degradaria el caso inexplicado). Solo cuando exit not in
  (0, None):
  1. `if failed_test_ids or error_test_ids:` -> critical `pytest_safe_last_run_nonzero`
     (fallo real; GANA aunque haya tambien state_leak).
  2. `elif state_leak:` (truthy = lista no vacia) -> WARN
     `automatic_warnings.append("pytest_safe_last_run_stateleak_only")`, NO critical.
  3. `else:` (exit!=0 sin failed/error y sin state_leak) -> critical
     `pytest_safe_last_run_nonzero` (exit NO explicado -> FAIL-SAFE, no se silencia).
- findings.json (l.337-359): anadir `automatic_warnings` (lista) al lado de
  `automatic_criticals`. El exit del script (l.404) sigue siendo
  `1 if criticals else 0` -> los WARN NO cambian el exit code.

### CONSERVAR (no tocar)
- El critical `pytest_safe_last_run_missing` (l.313-314): cannot confirm green.
- El critical `validate_motor_nonzero` (l.315-316).
- El resto de checks, la escritura de raw/, INDEX.md, esqueletos md.
- La convencion de exit 0/1 del script.

## Definition of Done (DoD)
- (a) Fixture A (`exit=1, failed=[], error=[], state_leak=['x']`): collect NO lista
  `pytest_safe_last_run_nonzero` en `automatic_criticals`; lo lista como WARN.
- (b) Fixture B (`exit=1, failed_test_ids=['t']`): SIGUE dando el critical.
- (c) Fixture C (`exit=1, sin failed/error y state_leak AUSENTE`): sigue critical
  (fail-safe). Este es el caso que el `!= []` habria roto (BLOCKER plan-audit).
- (d) Fixture D (`exit=0`): ni critical ni warn (sin cambio).
- (e) Fixture E (`exit=1, failed=['t'], state_leak=['x']` -- fallo real Y leak):
  critical (failed GANA a state_leak; verifica el ORDEN de ramas, CONCERN-2 plan-audit).
- (f) Test unitario nuevo que cubre A/B/C/D/E + mutation-verify (revertir la
  degradacion -> el test de A vuelve a critical y falla).
- (g) py_compile + `ruff check scripts/collect_system_health.py` verdes; ASCII limpio
  (VERIFICADO en scope del encoding-guard via glob scripts/**/*.py; plan-audit OK-4).
- (h) Suite `run_pytest_safe --level all` exit 0, tested_sha==HEAD.

## Riesgos y barreras
- NO silenciar un exit!=0 sin explicacion (sin failed/error Y sin state_leak) ->
  ese caso sigue critical (fail-safe). Barrera: DoD-(c).
- La barrera se define ANTES del codigo con 2 fixtures (mejora del review 2a pasada):
  A -> WARN, B -> critical. Reproduccion minima ya confirmada in-vivo.
- Aislar 021m: NO agrupar 021c en el mismo commit (regla del review). Cierre limpio
  de 021m primero.
