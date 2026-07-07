# Plan de Trabajo: Fix falso-verde del recolector de salud (encoding + parse)

## Metadata
- **ID:** WOT-2026-020g
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-08
- **delivery_authority:** repo_motor
- **Prioridad:** LOW
- **Asignado a:** Builder

## Objetivo
`collect_system_health.py` produce dos falsos verdes: (1) pierde/corrompe el stdout de
subprocesos (ruff) porque `subprocess.run(text=True)` usa cp1252 en Windows en vez de UTF-8;
(2) marca `ok=True` sin mirar el `exit_code`. El recolector debe reflejar el exit real.

## Premisa (verificada read-only)
- VERIFICADO EN CODIGO (`collect_system_health.py:43-49`): subprocess.run text=True SIN encoding utf-8.
- VERIFICADO EN CODIGO (`collect_system_health.py:50-56`): `_run` devuelve "ok": True fijo.

## Files Likely Touched
- `scripts/collect_system_health.py`
- `tests/` (test nuevo/extendido del recolector; ruta exacta la fija el Builder segun layout)

## Read/inspect only
- `.agent/audits/system_health/general_audit_20260707_1630/findings.json`
- `.agent/runtime/pytest-safe/last-run.json`

## Forbidden Surfaces
- NO tocar el AUDITOR ni la logica de veredicto (solo la fidelidad del RECOLECTOR).
- NO tocar run_pytest_safe.py ni scripts fuera del recolector.

## Non-goals
- No cambiar la logica de los checks del recolector (que comandos corre, ni el orden).
- No tocar el AUDITOR ni la Pasada B (veredicto del agente).
- No modificar `_read_pytest_last_run` (ya usa json.load desde el origen; el
  exit_code=null del audit fue sintoma del crash de encoding, no bug de parseo).
- No alterar el flujo de degradacion auto/motor-only/full ni la salida de exit codes
  del recolector (0/1/2/3).
- No ampliar scope al parseo "regex/parcial" del backlog (premise stale, ya satisfecha).

## Decision Arquitectonica
Forzar `encoding="utf-8", errors="replace"` en `subprocess.run` en lugar de depender de
la codepage del sistema. Motivo: el root cause del crash es que `text=True` sin
`encoding=` usa cp1252+strict en Windows, y `UnicodeDecodeError` (ValueError) escapa
del try/except de `_run` (que solo captura OSError). UTF-8+replace es fail-safe: nunca
crashea y captura stdout UTF-8 (lo que ruff emite) sin perdida. Derivar `ok` de
`returncode == 0` en lugar de hardcodear True: el recolector es Pasada A determinista;
su fidelidad depende de reflejar el exit real, no de asumir verde. Ambos cambios son
salida del recolector (no logica de control), por lo que no alteran el flujo.

## Fase 1: Fix de fidelidad del recolector
### 1.1 Forzar encoding UTF-8 en captura de subprocesos
- Archivo: `scripts/collect_system_health.py` (`_run`, l.43). Anadir `encoding="utf-8", errors="replace"`.
- Riesgo: BAJO. AC: stdout no-ASCII capturado sin None ni `?` lossy (test).
### 1.2 Derivar `ok` del exit_code real
- Archivo: `scripts/collect_system_health.py` (dict retorno, l.50-56). `ok = proc.returncode == 0`.
- Riesgo: MEDIO. AC: exit_code=1 -> ok=False; exit_code=0 -> ok=True. Verificar consumidores del ok fijo.
### 1.3 Barrera de regresion (mutation-verify)
- Archivo: `tests/`. Test que cubra ambos fallos. Revertir cada fix -> test FALLA; restaurar -> PASA.
- Riesgo: BAJO. AC: 4 exit codes en execution_log.

## Calidad (gates)
- `ruff check scripts/collect_system_health.py` -> 0
- `python scripts/run_pytest_safe.py --level unit --xdist-workers auto` -> 0
- test focal del recolector -> pasa; mutation-verify de ambos fixes
- `python scripts/check_encoding_guard.py scripts/collect_system_health.py` -> 0

## Criterios de Aceptacion Global
- [x] `_run` fuerza encoding utf-8, captura stdout no-ASCII sin perdida
- [x] `ok` deriva de exit_code == 0
- [x] findings.json: ruff exit 1 -> ok=false; last-run exit 0 -> exit_code=0
- [x] Test regresion + mutation-verify (4 exit codes en execution_log)
- [ ] ruff 0, suite verde, validate 0 errors  (suite final sobre arbol limpio pendiente)
