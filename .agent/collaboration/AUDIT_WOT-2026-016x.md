# AUDIT - WOT-2026-016x

**Ticket:** WOT-2026-016x - run_quality_gates no imprime el WARN de "veredicto no
concluyente" de pytest cuando el stamp es inconclusive.
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion:
  confirmar diagnostico -> anadir el bucle de impresion -> crear test nuevo ->
  mutation -> gates -> commit/mark-ready. La unica reversion es la barrera de
  mutation, documentada como transitoria y restaurada de inmediato, no una
  contradiccion de alcance.
- TP-02: verificado - cada criterio de aceptacion del work_plan.md cita un
  comando o asercion exacta: presencia del WARN en captured.out para el
  criterio 1, result["passed"] is True para el criterio 2, FAIL-sin-fix /
  PASS-con-fix literal para el criterio 3, los 4 campos exactos del
  last-run.json para el criterio 4, comando ruff exacto para el criterio 5,
  comando validate exacto para el criterio 6.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  concretos, cada bullet con una unica ruta parseable. Los Non-goals delimitan
  explicitamente que NO se convierte inconclusive en fail/AUTO-REJECT, NO se
  toca --pre-handoff, NO se modifica _check_quality_gates ni su caller, y NO
  se imprime results["summary"] (solo warnings), para que el Builder no derive
  scope.
- TP-04: verificado - no aparece lenguaje blando tipo si procede u
  opcionalmente en el flujo critico del work_plan.md. El diseno especifica el
  bucle de impresion exacto (for warning in results["warnings"]: print(...))
  y el punto exacto de insercion (antes de la linea del status final).
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-016x.md y este AUDIT
  describen la misma secuencia, los mismos 2 archivos de Files Likely Touched
  y los mismos 6 criterios de cierre. Los Blockers de este AUDIT usan los
  mismos verbos que las Fases del PLAN.
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma
  canonica TP-01..TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional que dejen
  una decision abierta en Objetivo, Fases, Criterios ni Decision Arquitectonica
  del work_plan.md. La decision de que imprimir (solo warnings, no summary) y
  donde (dentro de run_quality_gates, no en _check_quality_gates ni en el
  caller) esta cerrada explicitamente en la seccion Decision Arquitectonica y
  en Non-goals.

## Diagnostico Fase 0 confirmado (no inferido)

El diagnostico de Fase 0 del Orquestador fue verificado directamente en
codigo por el Manager antes de aprobar este plan:

- .agent/agent_controller.py:2089-2154 (run_quality_gates) leido literal:
  confirma que results = {"passed": True, "errors": [], "summary": [],
  "warnings": []} (linea 2092), que el WARN de pytest inconclusive se anade
  solo a results["warnings"] sin tocar results["passed"] (linea 2142-2146), y
  que la unica impresion de la funcion es el header (linea 2091) y el status
  final (linea 2152-2153): ningun item de summary ni de warnings se imprime
  individualmente en ningun punto del cuerpo de la funcion.
- .agent/agent_controller.py:2227-2255 (_check_quality_gates) leido literal:
  confirma que la funcion solo lee gate_result["passed"] (linea 2240) y
  retorna None cuando es True (linea 2255) sin inspeccionar summary ni
  warnings.
- .agent/agent_controller.py:2497 (unico caller de _check_quality_gates,
  dentro de determine_next_action) leido literal: confirma que cuando
  _check_quality_gates retorna None, el flujo continua sin ninguna traza del
  WARN.
- Confirmado con grep sobre tests/test_agent_controller.py que
  test_run_quality_gates_inconclusive_stamp_does_not_fake_pass (linea
  408-429) YA verifica el WARN dentro del dict de retorno
  (result["warnings"]), pero NO usa capsys ni verifica stdout: es
  complementario al test nuevo de este ticket, no redundante ni en conflicto.
- Confirmado con grep que ningun test existente en
  tests/test_agent_controller.py usa capsys junto a run_quality_gates antes de
  este ticket: no hay riesgo de colision con una asercion estricta de
  igualdad sobre stdout.
- Confirmado que TestAutoRejectQualityGates (linea 2344-2409) mockea
  agent_controller.run_quality_gates directamente (no ejecuta el cuerpo real
  de la funcion), por lo que el print anadido dentro de run_quality_gates no
  puede afectar a esos 2 tests.
- Confirmado (STATE.md, execution_log.md) que el ticket previo activo era
  WOT-2026-015m con Estado COMPLETED, y que no hay plan activo (work_plan.md
  vacio de contenido operativo salvo el ticket cerrado) antes de este
  bootstrap: no hay drift de bus pendiente de otro ticket.

La premisa de Fase 0 es CORRECTA: el WARN se acumula en el dict pero nunca se
imprime, y la severidad es redundante-segura (no hay falso-verde de cierre
porque --pre-handoff exige stamp verde por separado), tal como declara el
diagnostico del Orquestador. El gap es cerrable con la impresion propuesta sin
tocar el veredicto passed.

## Blockers (para el Manager en review)

- Si run_quality_gates sigue sin imprimir el contenido de results["warnings"]
  tras el commit del Builder: BLOCKER, el fix no fue aplicado.
- Si el test nuevo no usa capsys ni verifica stdout, sino que solo repite la
  asercion existente sobre result["warnings"] (el dict): BLOCKER, no cubre la
  barrera de visibilidad que pide el ticket (criterio no verificado, TP-02).
- Si el test nuevo o el fix cambian result["passed"] a False, o convierten el
  caso inconclusive en AUTO-REJECT: BLOCKER critico, reintroduce el
  falso-rojo que WOT-2026-016c elimino deliberadamente (Non-goal violado).
- Si test_run_quality_gates_inconclusive_stamp_does_not_fake_pass (linea
  408-429) deja de pasar o fue modificado: BLOCKER, el cambio se filtro fuera
  del alcance aprobado (Non-goal violado).
- Si algun test de TestAutoRejectQualityGates (linea 2344-2409) deja de pasar
  o _check_quality_gates aparece modificado en el diff: BLOCKER, el cambio se
  filtro a la funcion de decision de AUTO-REJECT, fuera de scope.
- Si no hay evidencia literal (comando mas output) de FAIL-sin-fix /
  PASS-con-fix para el test nuevo: BLOCKER, el criterio de aceptacion 3 no
  esta satisfecho.
- Si results["summary"] tambien aparece impreso en el diff (no solo
  results["warnings"]): BLOCKER, ampliacion de alcance no autorizada (Non-goal
  violado).
- Si la suite canonica (run_pytest_safe.py --level all) no tiene
  tested_commit_sha igual a HEAD del commit final: BLOCKER, no es cierre
  canonico.

## Evidencia esperada en execution_log.md

- Cita literal del bucle de impresion anadido en run_quality_gates (diff o
  snippet), y su ubicacion exacta relativa a la linea del status final.
- Salida literal de: pytest tests/test_agent_controller.py -v, con conteo
  explicito de passed incluyendo el test nuevo y los 4+2 tests de
  no-regresion citados en Tests Esperados.
- Salida literal de mutation: FAIL-sin-fix (comando mas output) y
  PASS-con-fix (comando mas output) para
  test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator.
- Salida literal de ruff check sobre los 2 archivos tocados.
- Salida literal (o referencia a last-run.json) de la suite canonica con los
  4 campos exactos y tested_commit_sha igual a HEAD.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-016x en
  el mensaje.
