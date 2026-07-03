# AUDIT - WOT-2026-016t

**Ticket:** WOT-2026-016t - manager-approve: el mensaje del WARN por commit invalido no es
accionable (no muestra el commit encontrado ni distingue el camino limpio de --force).
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las 3 fases son secuenciales sin contradiccion: Fase 1 re-verifica el
  diagnostico contra el codigo real (obligatoria antes de tocar nada, dado que la premisa
  original del backlog era imprecisa), Fase 2 aplica el fix del texto del mensaje, Fase 3
  anade el test de barrera con mutation. Ninguna fase pide crear y borrar el mismo
  artefacto ni contradice a otra.
- TP-02: verificado - cada criterio de aceptacion tiene comando o assert literal: el pytest
  -k warn_message con el resultado esperado (subcadenas especificas en stderr), el diff
  acotado a 0 lineas en las funciones que no se tocan, la mutation con resultado esperado
  rojo/verde, el comando de regresion completo del archivo de test, ruff check + format
  --check, el runner de suite canonica y el validate final con exit code y contadores 0/0.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos sin
  comodines (.agent/agent_controller.py, tests/unit/test_manager_approve.py), con
  anotacion de que dentro del primero el cambio es SOLO el bloque ~4520-4529. El
  Diagnostico y la Decision Arquitectonica delimitan explicitamente que NO se toca
  (_validate_closeout_commit_message, _check_last_commit, _CHECKPOINT_KEYWORDS, la
  condicion que dispara el WARN) para que el Builder no derive scope hacia la logica de
  validacion.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" u "opcionalmente" en el
  flujo critico; las decisiones (que se modifica, que no, por que se obtiene el commit con
  una llamada propia en vez de cambiar la firma de _check_last_commit) estan cerradas con
  razon explicita en el propio plan.
- TP-05: verificado - plan y audit describen la misma secuencia (re-verificar diagnostico,
  fix del mensaje, test con mutation), los mismos 2 archivos de Files Likely Touched y los
  mismos criterios de cierre (regresion cero en el archivo de test, diff acotado en las
  funciones protegidas, ruff, suite canonica, validate). Los Blockers de este AUDIT usan
  los mismos verbos que las Fases del PLAN (re-verificar, fijar el fix del mensaje, anadir
  el test con mutation).
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma canonica TP-01..
  TP-05, no criterios de diseno del entregable).
- TP-07: verificado - no hay clausulas condicionales de alcance ("si existe", "si aplica")
  decidiendo que se entrega; la clausula condicional del punto 5 de Fase 3 (fixture de git
  real opcional) exige explicitamente documentar la decision en execution_log.md si se
  omite, en vez de dejarla como salida silenciosa sin registro.

## Blockers

- Ninguno identificado en fase de planificacion. El Manager debe verificar en review que:
  1. El diff de .agent/agent_controller.py toca unicamente el bloque de construccion del
     mensaje dentro de "if not commit_valid:" (obtencion best-effort del commit +
     warn_parts/warn_msg). NO debe tocar _validate_closeout_commit_message,
     _check_last_commit, _CHECKPOINT_KEYWORDS, ni la condicion de la linea 4517/llamada de
     la linea 4519 que deciden CUANDO se dispara el WARN.
  2. La obtencion del commit para mostrar en el mensaje es best-effort (try/except
     silencioso): un fallo de git en esa consulta adicional NO debe romper el flujo ni
     cambiar el return 1 ya decidido por el gate.
  3. El test nuevo en tests/unit/test_manager_approve.py existe con el nombre declarado en
     el plan (o equivalente documentado si el Builder ajusta el nombre exacto) y verifica
     exactamente lo que dicen los criterios de aceptacion 3 y 4: las 3 subcadenas
     (commit encontrado, camino limpio, --force) y el comportamiento MUTATION.
  4. La evidencia de mutation (rojo sin fix / verde con fix) aparece en execution_log.md
     con el comando literal usado, no solo una afirmacion en prosa.
  5. La suite completa de tests/unit/test_manager_approve.py (incluidos los tests
     preexistentes que mockean el camino feliz return_value=(True, "")) sigue en 100%
     passed tras el fix -- en particular que el test de topologia motor/destino
     (test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology) no
     se vio afectado por el cambio.
  6. Si el Builder decide, en el punto 5 de Fase 3, omitir el test de integracion con git
     real (fixture mas cara), debe existir la justificacion explicita en execution_log.md;
     si no aparece, es un blocker de review (la clausula condicional del plan exige
     registro, no silencio).

## Evidencia esperada al cierre

- pytest tests/unit/test_manager_approve.py -k warn_message -> passed, con las 3
  aserciones exactas (commit encontrado, camino limpio, --force como alternativa).
- pytest tests/unit/test_manager_approve.py -> 100% passed (archivo completo, incluidos
  los tests preexistentes de camino feliz y el de topologia motor/destino).
- Evidencia mutation: comando de reversion manual del texto del mensaje + resultado FAIL
  en el/los test(s) nuevos, seguido de reaplicacion del fix + resultado PASS, documentado
  en execution_log.md.
- git diff acotado mostrando 0 lineas modificadas en _validate_closeout_commit_message,
  _check_last_commit y _CHECKPOINT_KEYWORDS.
- ruff check y ruff format --check sobre los 2 archivos del ticket -> 0 errores.
- scripts/run_pytest_safe.py --level all -> exit 0, sin state-leak sobre
  .agent/collaboration/.
- .agent/agent_controller.py --validate --json --project-root . -> exit 0, 0 errors, 0
  warnings.
- Commit(s) del ticket con ID WOT-2026-016t y autor noreply (convencion vigente de la
  sesion), sin PII en el mensaje ni en el diff.
