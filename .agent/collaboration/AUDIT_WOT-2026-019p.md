# Audit - WOT-2026-019p

## Metadata
- **ID:** WOT-2026-019p
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Fecha:** 2026-07-07

## TP Check

- TP-01: verificado - las 3 fases son secuenciales sin instrucciones
  incompatibles sobre el mismo recurso. Fase 1 anade las 2 funciones de
  modulo _replace_once_or_none y _atomic_replace_with_retry mas su
  call-site en write_artifact_atomic dentro de bus/supervisor.py; Fase 2
  solo anade tests nuevos en
  tests/test_approval_state_revision_and_skill_access.py sin tocar
  produccion; Fase 3 solo ejecuta comandos de verificacion. Ninguna fase
  pide crear y revertir el mismo cambio en el mismo paso.
- TP-02: verificado - cada fase tiene un verificador literal: git diff
  acotado (confirma las 2 funciones de modulo y el call-site de 1 linea)
  y ruff check sin C901 ni PERF203 (Fase 1), comando pytest -k con el
  nombre de test exacto y descripcion FAIL-sin-fix/PASS-con-fix (Fase
  2.1), comando pytest -k del test negativo (Fase 2.2), y ruff check mas
  suite completa mas --validate --json (Fase 3). No aparece "observable"
  o "correcto" sin una prueba literal que lo verifique.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  (bus/supervisor.py, tests/test_approval_state_revision_and_skill_access.py)
  sin comodines ni "otros archivos si hace falta".
- TP-04: verificado - no aparecen expresiones "si procede",
  "opcionalmente" ni "preferiblemente"; el plan especifica valores
  concretos (3 intentos, backoff 0.01 segundos por intento,
  PermissionError con codigo 5) en vez de terminos blandos.
- TP-05: verificado - este AUDIT usa los mismos archivos, comandos y
  criterios que las Fases 1-3 del work_plan tras sus 2 actualizaciones
  (diseno con helper de 1 funcion para C901, luego 2 funciones sin
  try/except-en-loop para PERF203): mismos nombres de funcion
  _replace_once_or_none y _atomic_replace_with_retry, mismas firmas,
  mismos 2 nombres de test, mismos comandos ruff/pytest/validate; no
  introduce ninguna condicion adicional no presente en el plan.

## Blockers Verificados Pre-Aprobacion

- Lectura completa de bus/supervisor.py, metodo write_artifact_atomic
  (lineas 160-267): confirma que el bloque try de las lineas 234-249
  contiene la unica invocacion de os.replace del metodo, y que el bucle
  externo for attempt in range(max_retries) (linea 195) solo captura
  FileExistsError del lock (linea 199), no PermissionError del rename.
- Hallazgo post-implementacion (confirmado por el Orquestador): el bucle
  de retry inline elevo write_artifact_atomic de complejidad McCabe <=10
  a 13, incumpliendo C90=10 (pyproject.toml:58, extend-select con C90);
  sin el bucle, ruff check daba "All checks passed!". Decision: extraer
  el bucle a una funcion de modulo _atomic_replace_with_retry(temp_path,
  artifact_path, attempts=3) definida antes de class
  SequentialTicketSupervisor, sin usar `# noqa: C901`. La funcion no
  requiere self (solo usa sus 2-3 parametros), por lo que una funcion de
  modulo es mas simple que un metodo nuevo.
- Segundo hallazgo post-implementacion (confirmado por el Orquestador):
  con el helper de una sola funcion _atomic_replace_with_retry ya
  extraido (resolviendo C901), ruff reporto PERF203 (`try`-`except`
  dentro de un `for` incurre en overhead) sobre el except PermissionError
  anidado en el for del helper. El Manager reprodujo el hallazgo de forma
  aislada (archivo de prueba con el extend-select real del proyecto: E,
  F, B, S, RUF, N, W, I, PERF, UP, C90, ERA, SIM) y confirmo que: (a) la
  version con try/except dentro del for SI dispara PERF203 (reproducido);
  (b) separando el intento individual en una funcion propia
  (_replace_once_or_none, try/except sin loop) del bucle de reintento
  (_atomic_replace_with_retry, for sin try/except propio) el mismo
  archivo pasa "All checks passed!" (sin C901, sin PERF203, sin B904).
  Decision: reestructurar en 2 funciones en vez de usar
  `# noqa: PERF203` o un per-file-ignore; el unico precedente de ignore
  de PERF203 en el repo (tests/test_pre_commit_hooks.py) es sobre
  codigo de test, no de produccion.
- Grep de write_artifact_atomic sobre tests/: confirma que los tests
  existentes de esta funcion viven en
  tests/test_approval_state_revision_and_skill_access.py (funciones
  test_supervisor_write_artifact_atomic,
  test_supervisor_write_artifact_atomic_with_expected_revision,
  test_supervisor_write_artifact_atomic_concurrent_conflict) y en
  tests/evals/test_eval_requeue.py; el archivo elegido para los tests
  nuevos es el primero, por continuidad de patron con los tests
  existentes de la misma funcion.
- Confirmado en el interprete del proyecto que bus.supervisor.os.replace
  es un atributo accesible y monkeypatcheable (bus/supervisor.py importa
  el modulo os completo en la linea 4, no una funcion individual).
- Confirmado que el flaky documentado (log de 019m, 2026-07-06) fue un
  PermissionError [WinError 5] Acceso denegado durante el rename atomico
  en test_bootstrap_bus_precedence_over_turn_divergence, aislado 3/3 en
  verde y con una re-corrida completa de la suite en exit 0 sobre el
  mismo HEAD: confirma transitoriedad, no regresion determinista de
  logica.

## Criterios que el Manager verificara en el Review

1. git diff -- bus/supervisor.py entre el commit base y el commit de
   entrega muestra: (a) dos funciones de modulo nuevas,
   _replace_once_or_none (try/except sin loop) y
   _atomic_replace_with_retry (for sin try/except propio), definidas
   antes de class SequentialTicketSupervisor; (b) dentro del bloque try
   de las lineas 234-249, la linea os.replace directa reemplazada por
   una unica linea de llamada a _atomic_replace_with_retry; el resto del
   metodo write_artifact_atomic (lock, OCC, lectura de revision)
   permanece identico a la version pre-019p.
2. El retry OCC externo (bucle for attempt in range(max_retries), lineas
   195-216) y su logica de stale lock recovery no aparecen modificados en
   el diff.
3. tests/test_approval_state_revision_and_skill_access.py incluye
   exactamente 2 funciones de test nuevas:
   test_supervisor_write_artifact_atomic_retries_transient_permission_error
   (positivo) y
   test_supervisor_write_artifact_atomic_reraises_after_exhausting_replace_retries
   (negativo), ambas con monkeypatch de bus.supervisor.os.replace, sin
   depender de sys.platform ni de sys.platform == "win32", ni de leer el
   atributo winerror del PermissionError.
4. El test positivo, ejecutado con pytest -k apuntando a su nombre
   exacto sobre el archivo de test, pasa en exit 0 sobre el commit de
   entrega. El Builder documenta en el execution_log el comando y
   resultado FAIL (revirtiendo temporalmente el call-site al os.replace
   directo sin retry, o haciendo que _atomic_replace_with_retry retorne
   tras la primera llamada a _replace_once_or_none sin reintentar)
   seguido del comando y resultado PASS (con ambas funciones completas y
   en uso), demostrando que la barrera es real y no un test que pasaria
   de cualquier forma.
5. El test negativo, ejecutado con pytest -k apuntando a su nombre exacto,
   pasa en exit 0 y confirma con pytest.raises(PermissionError) que
   write_artifact_atomic re-lanza la excepcion original tras agotar los
   reintentos, mas la ausencia de archivos temporales huerfanos con
   prefijo .tmp_ en el directorio de colaboracion de la fixture tras la
   excepcion.
6. ruff check sobre bus/supervisor.py y
   tests/test_approval_state_revision_and_skill_access.py sale con exit
   code 0, sin la regla C901 (write_artifact_atomic recupera complejidad
   <=10 tras perder el bucle inline) NI la regla PERF203 (ninguna de las
   2 funciones nuevas tiene try/except dentro de un for); el Builder no
   anadio `# noqa: C901` ni `# noqa: PERF203` ni un per-file-ignore en
   pyproject.toml para resolver ninguno de los 2 hallazgos.
7. La suite completa reportada por el Builder (run_pytest_safe --level
   all o equivalente) esta verde y su tested_commit_sha coincide con el
   HEAD del commit de entrega.
8. python .agent/agent_controller.py --validate --json --project-root .
   reportado por el Builder da errors: 0. El ticket ya fue bootstrapeado
   a WOT-2026-019p / IN_PROGRESS antes de la implementacion (confirmado
   por el Orquestador), por lo que no deberia reaparecer el drift
   APPROVED-vs-COMPLETED del ciclo anterior; si reapareciera por otra
   causa, el Manager lo distingue explicitamente en el review antes de
   bloquear el cierre por ese motivo.
9. Ningun otro archivo del repo aparece modificado en el diff de entrega
   salvo bus/supervisor.py,
   tests/test_approval_state_revision_and_skill_access.py y los
   artefactos de colaboracion que el propio Builder actualice
   (execution_log_WOT-2026-019p.md).

## Evidencia esperada en execution_log_WOT-2026-019p.md

- Diff literal (git diff -- bus/supervisor.py) o su resumen de lineas
  anadidas/eliminadas: las 2 funciones _replace_once_or_none y
  _atomic_replace_with_retry completas mas el call-site de 1 linea
  dentro de write_artifact_atomic.
- Comando y salida literal del test positivo en modo FAIL (sin retry o
  con _atomic_replace_with_retry sin reintentar) y en modo PASS (con
  ambas funciones completas).
- Comando y salida literal del test negativo (fail-closed).
- Output de ruff check sobre los 2 archivos tocados, confirmando ausencia
  de C901, ausencia de PERF203, y ausencia de `# noqa: C901` /
  `# noqa: PERF203` en el archivo.
- Checkpoint de la suite completa con su tested_commit_sha.
- Output de --validate --json.
