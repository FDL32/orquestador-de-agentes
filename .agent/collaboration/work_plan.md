# Plan de Trabajo: collect_system_health lee last-run del destino cuando dest_ok

## Metadata
- **ID:** WOT-2026-021c
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** BAJA
- **Asignado a:** Builder

## Objetivo
`collect_system_health._read_pytest_last_run` (l.128) se invoca SIEMPRE con
`motor_root` (l.299), aun cuando se audita un `repo_destino` (`dest_ok`). Cuando el
last-run del MOTOR esta stale (exit 1 de un run viejo) y el del DESTINO esta verde
(exit 0), el colector reporta un FALSE-RED de pytest-safe del destino. Fix: leer el
last-run del `dest_root` cuando `dest_ok`, del `motor_root` en modo motor-only.

## Contexto
Hermano de WOT-2026-021m (mismo fichero, misma superficie pytest_safe_last_run).
020g (5e8365d) arreglo encoding + ok-por-exit_code pero NO la raiz (el root
equivocado). En un cierre code-only del MOTOR (sin destino) el comportamiento actual
es correcto (lee el motor); el bug SOLO se manifiesta cuando `dest_ok` (auditoria de
un repo_destino real con su propia suite). La clasificacion por causa de 021m
(state-leak vs failed/error) sigue aplicando al last-run resultante, sea de quien sea.

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (verificado in-vivo 2026-07-10 por reproduccion de 2 fixtures)

### CAMBIAR (`scripts/collect_system_health.py`)
- l.299: `pytest_last = _read_pytest_last_run(motor_root)` ->
  `pytest_last = _read_pytest_last_run(dest_root if dest_ok else motor_root)`.
  `dest_root`/`dest_ok` ya estan en scope (l.223-224). En modo motor-only (dest_ok
  False) sigue leyendo el motor (sin regresion).
- Transparencia del recolector (testigo): anadir el campo `source` = "destino" |
  "motor" al `pytest_last` EN EL CALLER (l.299), NO dentro de `_read_pytest_last_run`
  (que recibe un root y no sabe su tipo -> ahi seria incalculable). Ej.:
  `pytest_last = _read_pytest_last_run(root); pytest_last["source"] = "destino" if
  dest_ok else "motor"`. NO cambia el veredicto, solo lo audita.

### CONSERVAR (no tocar)
- La clasificacion por causa de 021m (failed/error -> critical; state_leak -> warn;
  else -> critical fail-safe): opera sobre el last-run resultante, sea motor o destino.
- El critical `pytest_safe_last_run_missing` (si el last-run del root elegido falta).
- El resto de checks del destino (ruff_destino, validate_destino), inventarios, etc.

## Definition of Done (DoD)
- (a) Fixture 1 (motor last-run exit=1 stale, destino exit=0, dest_ok): collect NO
  marca `pytest_safe_last_run_nonzero` (lee el destino verde). `source`=="destino".
- (b) Fixture 2 (destino exit=1 con failed_test_ids, dest_ok): SIGUE critical (fallo
  real del destino).
- (c) Fixture 3 (modo motor-only, motor exit=1): sigue leyendo el motor (sin regresion;
  `source`=="motor"). El test existente motor-only sigue verde.
- (c2) Fixture 4 (dest_ok pero destino SIN last-run.json): critical
  `pytest_safe_last_run_missing` (NO fallback silencioso al motor -> NO false-green).
- (d) Test unitario que cubre Fixture 1/2/3/4 + mutation-verify (revertir a motor_root ->
  Fixture 1 falla).
- (e) py_compile + ruff + ASCII limpios (encoding-guard scope).
- (f) Suite `run_pytest_safe --level all` exit 0, tested_sha==HEAD.

## Riesgos y barreras
- NO romper el modo motor-only (dest_ok False sigue leyendo el motor). Barrera: DoD-c.
- La clasificacion de 021m NO se toca; solo cambia DE QUE root se lee el last-run.
- Aislar 021c: NO mezclar con 021k (sandbox hermeticity, otra familia) ni 021i
  (recolector backlog). Cierre limpio de 021c solo (regla del review 2a pasada).
