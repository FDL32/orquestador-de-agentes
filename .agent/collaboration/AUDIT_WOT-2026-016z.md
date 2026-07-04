# AUDIT - WOT-2026-016z

Ticket: WOT-2026-016z - Guard de sesion anti-contaminacion de la identidad git local
del motor (barrera preventiva, no aislamiento de fixture).
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion: anadir
  funciones lectoras/enforcement -> anadir fixture autouse -> crear tests de barrera
  con monkeypatch -> ejercer mutation -> gates -> commit/mark-ready. Ninguna fase pide
  crear y revertir el mismo cambio en el mismo paso; la unica reversion que ocurre es
  la restauracion del guard, que es su funcion normal documentada, no una contradiccion
  de alcance.
- TP-02: verificado - cada criterio de aceptacion del work_plan.md cita un comando
  pytest exacto o un valor exacto esperado (3 passed / 0 failed; los valores literales
  de user.email y user.name antes/despues de la suite; los 4 campos del last-run.json
  con tested_commit_sha == HEAD). El criterio de mutation exige el nombre de los tests
  o la llamada exacta y el resultado, no basta con narrar "se verifico".
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos,
  cada bullet con una unica ruta parseable sin anotacion inline (tests/conftest.py,
  tests/unit/test_motor_git_identity_barrier.py). Los Non-goals delimitan
  explicitamente que NO se toca _isolate_controller_event_bus,
  _restore_motor_bus_if_changed, _enforce_motor_bus_isolation,
  motor_bus_isolation_guard ni test_motor_bus_isolation_barrier.py, ni se anade un hook
  pre-commit/pre-push nuevo, para que el Builder no derive scope.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" u "opcionalmente" en
  el flujo critico del work_plan.md. La seccion de riesgos usa "Bajo/Medio" con
  mitigacion explicita nombrada (documentar el simbolo monkeypatcheado), no delega la
  decision al Builder.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-016z.md y este AUDIT describen la
  misma secuencia (clonar el patron del bus: 3 funciones + fixture autouse per-test,
  3 tests de barrera con monkeypatch, mutation cubierta por esos mismos 3 tests, gates
  de ruff/pytest/suite canonica + verificacion final de identidad sin cambio), los
  mismos 2 archivos de Files Likely Touched y los mismos 8 criterios de cierre. Los
  Blockers de este AUDIT (ver abajo) usan los mismos verbos que las Fases del PLAN
  ("clonar la estructura", "crear los 3 tests con monkeypatch", "verificar que la
  identidad no cambio").
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma canonica
  TP-01..TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo "si existe" /
  "si aplica" en Objetivo, Fases, Criterios ni Decision Arquitectonica del work_plan.md.
  La unica condicional tecnica (sustituir uv por .venv si uv esta roto) esta acotada a
  un gate de tooling ya documentado en WOT-2026-016c, no a la decision de alcance del
  ticket, y ambas ramas quedan definidas (ejecutar el gate real, documentar la
  sustitucion).

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-04), independientemente del diagnostico ya citado en
work_plan.md:
- git config --local user.email y git config --local user.name del motor real, leidos
  directamente: 128408907+FDL32@users.noreply.github.com / FDL32 (limpios, consistentes
  con lo que el work_plan.md declara).
- git status --short del arbol de trabajo: vacio (arbol limpio antes del bootstrap).
- grep de "git config --local user" y "git config user" en tests/: solo 2 archivos
  (tests/conftest.py, que sera el archivo tocado por este ticket, y
  tests/unit/test_motor_bus_isolation_barrier.py, que no toca git config en absoluto --
  solo usa motor_bus_isolation_guard sobre archivos en tmp_path). Ninguna llamada real a
  git config user.email/user.name existe hoy en la suite de tests. Esto confirma que NO
  hay fixture activo que mute la identidad git del motor: el guard de este ticket es
  puramente preventivo, no una correccion de un leak existente.

## Blockers (para el Manager en review)

- Si tests/conftest.py NO contiene una fixture autouse que snapshotea git config
  --local user.email/user.name del motor y falla nombrando el nodeid al detectar
  cambio: BLOCKER, el guard no fue implementado.
- Si el diff toca _isolate_controller_event_bus, _restore_motor_bus_if_changed,
  _enforce_motor_bus_isolation, motor_bus_isolation_guard o
  tests/unit/test_motor_bus_isolation_barrier.py: BLOCKER, fuera de scope (Non-goals).
- Si algun test nuevo invoca git config --local real con cwd apuntando al motor real
  (PROJECT_ROOT) para simular contaminacion, en vez de monkeypatch: BLOCKER, viola el
  requisito explicito de no contaminar el motor real.
- Si tras correr la suite canonica completa, git config --local user.email o user.name
  del motor real difieren de 128408907+FDL32@users.noreply.github.com / FDL32 de forma
  PERSISTENTE (no restaurada por el propio guard antes de terminar la corrida):
  BLOCKER critico, el guard tiene un bug de restauracion o el ticket dejo el motor
  contaminado.
- Si no hay evidencia literal (nombre de test + resultado, o comando + output) para las
  dos ramas de MUTATION (sin-contaminacion no falla / con-contaminacion falla y
  restaura): BLOCKER, el criterio de aceptacion 3 no esta satisfecho.
- Si la suite canonica (run_pytest_safe.py --level all) no tiene tested_commit_sha ==
  HEAD del commit final: BLOCKER, no es cierre canonico.

## Evidencia esperada en execution_log.md

- Cita literal de la fixture nueva _isolate_motor_git_identity y de las 3 funciones que
  clona (antes/despues no aplica porque son funciones nuevas; citar el codigo final).
- Salida literal de: pytest tests/unit/test_motor_git_identity_barrier.py -v (3
  passed).
- Salida literal de: pytest tests/unit/test_motor_bus_isolation_barrier.py -v (3
  passed, no-regresion del hermano).
- Explicacion de cual simbolo interno se monkeypatchea en los tests de barrera y por
  que eso evita tocar subprocess/git real.
- Resultado literal de las dos ramas de mutation (sin-contaminacion no dispara fallo /
  con-contaminacion dispara fallo con nodeid y restaura), citando los nombres exactos
  de los tests usados como evidencia.
- git config --local user.email y user.name del motor, leidos ANTES y DESPUES de la
  suite canonica completa (deben coincidir: 128408907+FDL32@users.noreply.github.com /
  FDL32).
- Salida literal de ruff check y ruff format --check (o su sustituto documentado).
- Salida literal (o referencia a last-run.json) de la suite canonica con los 4 campos
  exactos y tested_commit_sha == HEAD.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-016z en el
  mensaje.
