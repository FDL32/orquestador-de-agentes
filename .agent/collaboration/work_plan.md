# Work Plan - WOT-2026-017a

## Metadata
- **ID:** WOT-2026-017a
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** PRE_EXISTING_SUITE_RED - Comparacion por identidad de test-id en pre-handoff guard
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Sustituir el bloqueo binario exit_code != 0 del guard assert_canonical_suite_green
por una comparacion por identidad de test-id: el handoff se permite si y solo si el
conjunto de fallos del ultimo run es SUBCONJUNTO del baseline de fallos pre-existentes.
Requiere (a) persistir failed_test_ids en last-run.json dentro de run_pytest_safe.py,
y (b) leer ese campo en pre_handoff_guard.py para la nueva logica de decision.

## Decision Arquitectonica

El diseno elige parseo de lineas FAILED del stream de pytest (stdlib-only) como
metodo de captura de node-ids, en lugar de --json-report (requiere plugin externo).
La logica de decision es subconjunto de sets de string exactos, no conteo: cierra
el vector de mutacion donde un test verde->rojo y otro rojo->verde producen el mismo
conteo pero distinta identidad. Fail-closed en cada caso de baseline irresoluble.

## Fases

### Fase 1 - Ampliar run_pytest_safe: persistir failed_test_ids
- Modificar stream_pytest() en scripts/run_pytest_safe.py para parsear lineas
  FAILED del stream y capturar los node-ids (regex: ^FAILED\s+(\S+)).
- Cambiar firma: stream_pytest retorna tuple[int, list[str]] (returncode, failed_ids).
- En main(), anadir campo ADITIVO failed_test_ids: list[str] al summary cuando
  exit_code != 0; campo ausente cuando exit_code == 0.
- Anadir tests en tests/unit/test_run_pytest_safe.py cubriendo parseo de FAILED,
  campo ausente con exit_code==0, campo presente con exit_code!=0.

### Fase 2 - Actualizar pre_handoff_guard: logica de decision por identidad
- En assert_canonical_suite_green (l.429 pre_handoff_guard.py):
  sustituir if exit_code != 0: (l.502) por logica:
  1. exit_code==0: PERMITIDO.
  2. exit_code!=0 y failed_test_ids AUSENTE: BLOQUEA (fail-closed).
  3. exit_code!=0 y failed_test_ids PRESENTE: comparar set actual vs last-run.json
     base; si irresoluble: BLOQUEA; si subconjunto: PERMITIDO; si hay nuevos: BLOQUEA.
- Preservar los 3 gates existentes sin alteracion: tested_commit_sha==HEAD,
  level=all, args_mode=default_discovery.
- NO anadir ningun flag de override o bypass.

### Fase 3 - Tests de barrera (obligatorios, con repos git reales en tmp_path)
- T1: fallo HEREDADO (en baseline) -> handoff PERMITIDO.
- T2: fallo NUEVO (no en baseline) -> handoff BLOQUEADO.
- T3: baseline ausente o irresoluble -> BLOQUEA (fail-closed).
- T4: MUTATION mismo conteo distinto test-id -> BLOQUEADO.
- T5: regresion del guard: revertir fix minimo, confirmar bug vivo; restaurar,
  confirmar bloqueo correcto.

### Fase 4 - Verificacion final
- Suite completa run_pytest_safe.py --level all. 0 regresiones.

## Criterios de aceptacion

1. scripts/run_pytest_safe.py persiste failed_test_ids: list[str] en last-run.json
   cuando exit_code != 0. Campo ADITIVO; consumidores existentes no se rompen.
2. assert_canonical_suite_green implementa comparacion por IDENTIDAD de test-id
   (subconjunto de sets, no conteo).
3. T1-T5 pasan en la suite del motor.
4. 0 regresiones en la suite completa del motor (level=all, default_discovery).
5. El campo failed existente en run_pytest_safe.py (limpieza de DIRECTORIOS,
   l.275-284) NO se modifica ni renombra.
6. Gates existentes (tested_commit_sha==HEAD, level=all, args_mode=default_discovery)
   PRESERVADOS sin alteracion.
7. Ningun flag de override o bypass anadido.
8. Encoding ASCII/UTF-8 limpio en cada archivo modificado (gate check_encoding_guard).

## Files Likely Touched

- scripts/run_pytest_safe.py
- scripts/pre_handoff_guard.py
- tests/test_pre_handoff_guard.py
- tests/unit/test_run_pytest_safe.py

## Non-goals

- Ningun cambio en repositorios destino (ADU u otros).
- Los 3 gates existentes del guard (SHA, level, args_mode) se PRESERVAN sin alteracion.
- Ningun flag de bypass, override ni --force-suite en ningun script del motor.
- Ningun cambio de comportamiento de run_pytest_safe mas alla de ANADIR failed_test_ids.
- Ningun archivo baseline separado (decision CEM vinculante, rechazada).
- Re-run de la suite base en caliente (~98 min, fragil, rechazado por CEM).
- ADU-004 o cualquier ticket de destino.