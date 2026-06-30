# AUDIT WOT-2026-017a - PRE_EXISTING_SUITE_RED

**Ticket:** WOT-2026-017a
**Tipo:** code
**delivery_authority:** repo_motor
**Estado:** IN_PLANNING

---

## Criterios de verificacion (tests de barrera obligatorios)

### T1 - Fallo HEREDADO permite handoff

Escenario: suite con un test fallido que estaba en el baseline (failed_test_ids
del last-run.json contiene exactamente el mismo node-id que el fallo actual).

Precondiciones:
- Repo git real en tmp_path con commit ticker + last-run.json con exit_code != 0
  y failed_test_ids = [tests/foo/test_bar.py::TestFoo::test_one].
- El run actual tambien tiene exit_code != 0 y failed_test_ids = [mismo id].

Resultado esperado: assert_canonical_suite_green devuelve (True, diag) con
reason=inherited_failures_subset. El handoff no se bloquea.

Patron: init_git_repo en tmp_path; write_last_run con failed_test_ids; invocar
assert_canonical_suite_green directamente (no CLI) para aislar el seam.

### T2 - Fallo NUEVO bloquea handoff

Escenario: suite con un test fallido que NO estaba en el baseline.

Precondiciones:
- last-run.json con exit_code != 0 y failed_test_ids = [tests/new_test.py::test_nuevo].
- Baseline (si se separa del run actual): failed_test_ids = [] o sin ese id.

Resultado esperado: assert_canonical_suite_green devuelve (False, diag) con
reason que indica regresion nueva. Diag incluye lista de ids nuevos.

### T3 - Baseline ausente/irresoluble bloquea (fail-closed)

Sub-casos:
T3a: last-run.json ausente -> (False, reason=last_run_missing).
T3b: last-run.json no parseable (JSON invalido) -> (False, reason=last_run_unparseable).
T3c: exit_code != 0 pero failed_test_ids AUSENTE en last-run.json ->
     (False, reason=nonzero_exit_but_no_failed_ids (state-leak suspected)).
     NOTA (WOT-2026-017b, reapertura): el reason original de T3c
     (failed_test_ids_missing_with_nonzero_exit, D5c) fue SUBSUMIDO por un
     discriminante unico que tambien cubre el caso failed_test_ids PRESENTE
     pero VACIO ([]), que era un falso-verde real: con D5c solo el campo
     ausente bloqueaba; el campo presente-vacio (suite que crashea sin
     enumerar tests: coleccion rota, OOM/SIGKILL, state-leak) caia en
     a_set=set() -> siempre subconjunto de cualquier baseline -> handoff
     permitido erroneamente con reason=inherited_failures_subset. Ver T6
     en tests/test_pre_handoff_guard.py (T6a: presente-vacio bloquea;
     T6b: ausente sigue bloqueando tras el refactor).
T3d: nivel o args_mode incorrectos en el run base -> (False, reason=not_full_suite).

Resultado esperado en todos los sub-casos: bloqueo, sin degradar a warning.

### T4 - MUTATION: mismo conteo distinto test-id bloquea

Escenario: un test verde->rojo y otro rojo->verde simultaneamente.
Baseline: failed_test_ids = [A] (test A falla, test B pasa).
Run actual: failed_test_ids = [B] (test B falla, test A pasa).
Conteo de fallos: 1 en ambos casos.

Resultado esperado: assert_canonical_suite_green devuelve (False, diag)
con reason=regression_new_failures. El test B es nuevo fallo (B not in baseline).
Prueba que la comparacion es por IDENTIDAD de node-id, no por conteo.

Patron: repo git real; last-run.json con failed_test_ids=[test_A]; run actual
con failed_test_ids=[test_B]; verificar bloqueo.

### T5 - Regresion del guard (mutation-verify)

Escenario: revertir el conjunto MINIMO del fix en pre_handoff_guard.py
(restaurar el bloqueo binario exit_code != 0 sin la logica de subconjunto),
ejecutar T2 y T4 y confirmar que SIN el fix el bug vive (handoff se permite
con nuevo fallo o mutation); luego restaurar el fix y confirmar que CON el fix
bloquea.

Implementacion sugerida: el test parametriza dos variantes del guard usando
monkeypatch en la logica de decision, o copia temporal del script con el
bloqueo binario restaurado. El test usa repos git reales en tmp_path.

Resultado esperado:
- Con bloqueo binario restaurado + suite verde (exit_code=0): T2 no aplicable
  (verde siempre pasa). Con exit_code != 0 + el bloqueo binario: el test
  pasaria... esperar: el bloqueo binario TAMBIEN bloquea exit_code != 0.
  La regresion a verificar es distinta: el bloqueo binario bloquea INCLUSO
  cuando los fallos son heredados (T1 falla). T5 verifica que sin el fix,
  T1 NO funciona (handoff bloqueado aunque fallos sean heredados).
- Con fix aplicado: T1 pasa (heredados permitidos) y T2/T4 bloquean.

Patron: el test T5 tiene dos fases: pre-fix (monkeypatch del guard para
restaurar bloqueo binario) y post-fix (guard real). Confirma que el comportamiento
cambio en la direccion correcta.

---

## Gates de aceptacion (verificacion independiente)

G1 - Encoding: todos los archivos modificados pasan check_encoding_guard.py
     (ASCII/UTF-8 limpio, sin C1 control codepoints, sin BOM oculto).

G2 - Suite verde: run_pytest_safe.py --level all sobre HEAD del motor devuelve
     exit_code=0. No se admiten nuevas regresiones vs baseline (3394 passed,
     20 skipped).

G3 - T1-T5 presentes y verdes: los 5 tests de barrera existen en
     tests/test_pre_handoff_guard.py y pasan en la suite completa.

G4 - failed_test_ids en last-run.json: tests unitarios en
     tests/unit/test_run_pytest_safe.py cubren:
     - parseo correcto de lineas FAILED del stream (sin invocar pytest real).
     - campo ausente cuando exit_code == 0.
     - campo presente con lista correcta cuando exit_code != 0.

G5 - Gates existentes preservados: los tests existentes que verifican
     tested_commit_sha==HEAD, level=all y args_mode=default_discovery
     siguen pasando sin modificacion.

G6 - Campo failed de directorios intacto: grep en run_pytest_safe.py
     confirma que el campo failed existente (l.275-284) no fue modificado
     ni renombrado.

G7 - Sin override: grep en pre_handoff_guard.py confirma ausencia de
     force-suite, ignore-failures, bypass, o flags similares.

G8 - Consumidor preflight_closeout.py: si no fue modificado, los tests
     existentes en tests/unit/test_preflight_closeout.py siguen verdes.
     Si fue modificado, los tests reflejan el cambio y pasan.

---

## Riesgos identificados

R1 - Parseo de FAILED: el formato de salida de pytest puede variar entre
     versiones (modo verbose vs no verbose, con/sin terminal markup). El
     Builder debe verificar que el regex captura correctamente en el modo
     de invocacion canonico del proyecto (sin --verbose por defecto, con
     markup strips si aplica). Mitigacion: tests unitarios de parseo con
     salida real capturada.

R2 - Firma de stream_pytest: si preflight_closeout.py u otros consumidores
     llaman a stream_pytest directamente (no a traves de main()), el cambio
     de firma tuple puede romperlos. El Builder debe hacer grep exhaustivo
     antes de cambiar la firma.

R3 - last-run.json gitignoreado: el archivo es gitignoreado y no versionado.
     Si el run base fue sobreescrito por un run intermedio del ticket, el
     baseline en disco puede no ser el del commit base del ticket. El diseno
     acepta esta limitacion (decision CEM vinculante: no re-run en caliente,
     no archivo baseline separado).
     NOTA DE IMPLEMENTACION (Builder WOT-2026-017a): el campo
     baseline_failed_test_ids se captura como carry-forward del run
     INMEDIATAMENTE ANTERIOR, no del commit base del ticket. Si durante el
     ticket se corre la suite con el arbol sucio o con artefactos de
     colaboracion sin commitear (p.ej. work_plan.md pendiente), ese run puede
     introducir falsos-rojos en el baseline del run siguiente. D5c NO mitiga
     este caso: D5c solo bloquea cuando failed_test_ids esta AUSENTE, no
     cuando contiene ids de estado transitorio. La mitigacion correcta es
     garantizar que el run que precede al handoff se ejecuta con arbol limpio
     y todos los artefactos commiteados, de modo que el baseline refleje el
     conjunto real de fallos pre-existentes.

R4 - Tests flaky del motor: si un test flaky falla en el run post-cambio pero
     no estaba en el last-run.json pre-cambio, el handoff se bloquea por un
     fallo no introducido por este ticket. Mitigacion: D6 (politica de flaky
     explicita; resolucion correcta es xfail/fix/skip, no override).

## TP Check

TP-01: Objetivo verificable. El objetivo sustituir bloqueo binario por subconjunto
verificable ejecutando T1-T5 en la suite. CUMPLE.

TP-02: Criterios con comando o test. Los 8 criterios de aceptacion citan tests
concretos (T1-T5), comandos (run_pytest_safe.py --level all), campos concretos
(failed_test_ids, exit_code) y numeros medibles (0 regresiones). CUMPLE.

TP-03: Files Likely Touched enumerados. 4 archivos obligatorios enumerados en FLT
(scripts/run_pytest_safe.py, scripts/pre_handoff_guard.py, tests/test_pre_handoff_guard.py,
tests/unit/test_run_pytest_safe.py) mas 2 condicionales documentados. CUMPLE.

TP-04: Non-goals presentes y suficientes. La seccion Non-goals tiene 7 items
explicitos con nombres concretos (ADU-004, --force-suite, archivo baseline separado,
re-run en caliente, gates SHA/level/args). CUMPLE.

TP-05: Decision Arquitectonica presente. La seccion Decision Arquitectonica justifica
parseo de stream vs --json-report y la logica de subconjunto de sets. CUMPLE.