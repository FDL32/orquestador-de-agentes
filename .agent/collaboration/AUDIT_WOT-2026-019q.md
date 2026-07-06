# AUDIT_WOT-2026-019q

## Ticket
WOT-2026-019q -- Cierre canonico de un ticket cuyo commit no es HEAD
(batch-close no contiguo), sin aceptar entregas vacias.

## TP Check

- TP-01: verificado - las 3 fases del plan son secuenciales sin contradiccion:
  Fase 1 escribe tests (pre-fix, algunos en rojo por diseno TDD), Fase 2
  implementa el fix, Fase 3 verifica mutation + suite. Ninguna fase pide
  simultaneamente crear y revertir el mismo recurso; la Fase 3.1 revierte
  TEMPORALMENTE solo como parte del propio criterio de aceptacion (mutation-
  verify), y el plan especifica explicitamente restaurar despues.
- TP-02: verificado - cada criterio de aceptacion de cada fase cita un
  comando literal (pytest -k con nombre de clase exacto, ruff check .,
  run_pytest_safe.py) y el exit code esperado. No hay criterios del tipo
  "observable" o "correcto" sin verificador.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  (.agent/motor_checkpoint.py, tests/unit/test_motor_checkpoint.py), sin
  comodines ni "otros archivos si hace falta". Cada bullet FLT es una linea
  de path puro, sin prosa libre en el mismo bullet.
- TP-04: verificado - no aparece lenguaje blando ("si procede", "stale" sin
  definicion) en el flujo critico. El texto usa "stale" solo como cita literal
  del mensaje de error EXISTENTE hoy en el codigo (l.251 de motor_checkpoint.py
  actual), no como criterio de decision del plan nuevo.
- TP-05: verificado - STRATEGY_WOT y work_plan.md describen la misma
  secuencia (Step 1-4 preservados, chequeo nuevo de entrega vacia,
  agent_controller.py fuera de scope) y los mismos archivos FLT. El TP Check
  de este AUDIT usa la forma canonica TP-01..TP-05 y no sustituye la
  verificacion del plan por criterios de diseno del entregable.
- TP-07: verificado - no hay clausulas condicionales de alcance ("si existe",
  "si aplica") decidiendo que se implementa; la Decision Arquitectonica del
  work_plan.md cierra explicitamente Opcion (a) vs (b) sin dejarlo abierto.

## Paridad PLAN/AUDIT (TP-05 explicito)

| Criterio | work_plan.md | STRATEGY_WOT | AUDIT_WOT (aqui) |
|----------|--------------|--------------|-------------------|
| Step 2 ancestor-of-HEAD sin cambios | Fase 2.1 punto 1, Non-goals | Invariantes preservados | Blocker B2 |
| Step 4 subject-contains-ticket-id sin cambios | Fase 2.1 punto 3 | Invariantes preservados | Blocker B3 |
| Step 3 deja de ser retorno temprano bloqueante | Fase 2.1 punto 2 | Decision: Opcion (a) | Blocker B1 |
| Entrega vacia rechazada | Fase 2.1 punto 5, Criterios Globales | Nuevo chequeo (paso 6) | Blocker B4 |
| Caso HEAD==tag sin cambio observable | Fase 2.1 criterio, Criterios Globales | Invariantes preservados | Blocker B5 |
| agent_controller.py fuera de scope | Non-goals, Superficie tocada | Por que el cambio es narrow | Blocker B6 |
| Mutation-verify | Fase 3.1 | (no aplica, STRATEGY no verifica) | Blocker B7 |

## Blockers (deben resolverse antes de aprobar READY_FOR_REVIEW del Builder)

- B1: `resolve_motor_checkpoint_files` para un M3 NO-HEAD (ancestro de HEAD,
  subject con ticket_id, archivos no vacios) debe devolver `ok=True` con el
  set de archivos correcto. Verificar con
  `pytest tests/unit/test_motor_checkpoint.py -k test_buried_ticket_with_real_m3_closes_and_recovers_own_files -v`
  -> exit code 0.
- B2: Un M3 en una rama lateral NO ancestro de HEAD sigue bloqueado con el
  mensaje de Step 2 ("not an ancestor of HEAD"), sin cambios. Verificar con
  `pytest tests/unit/test_motor_checkpoint.py -k test_non_ancestor_still_rejected -v`
  -> exit code 0.
- B3: Un M3 cuyo commit real tiene subject SIN el ticket_id sigue bloqueado
  por Step 4, sin cambios. Verificar con
  `pytest tests/unit/test_motor_checkpoint.py -k test_subject_without_ticket_id_still_rejected -v`
  -> exit code 0.
- B4: Un M3 sobre un commit vacio (`git commit --allow-empty`, cero archivos
  de diff) es RECHAZADO con un mensaje que contiene "refusing empty
  closeout". Verificar con
  `pytest tests/unit/test_motor_checkpoint.py -k test_empty_closeout_commit_is_rejected -v`
  -> exit code 0.
- B5: El caso HEAD==tag (control, ticket topmost) produce el MISMO resultado
  observable que el codigo pre-fix: `ok=True`, `files` == diff exacto del
  commit topmost. Verificar con
  `pytest tests/unit/test_motor_checkpoint.py -k test_topmost_ticket_head_unchanged_behavior -v`
  -> exit code 0.
- B6: `agent_controller.py` NO aparece en el diff del Builder (git diff debe
  mostrar cambios SOLO en `.agent/motor_checkpoint.py` y
  `tests/unit/test_motor_checkpoint.py`). Si el Builder detecta que un call
  site SI requiere cambio, debe escalar antes de tocarlo (discrepancia de
  scope), no modificarlo unilateralmente.
- B7: Mutation-verify manual: revertir el cambio de Fase 2.1 hace que
  `test_buried_ticket_with_real_m3_closes_and_recovers_own_files` y
  `test_empty_closeout_commit_is_rejected` fallen (exit code != 0 en pytest);
  restaurar el cambio los deja en verde (exit code 0). Evidencia
  (comando + output de ambas corridas) debe estar en `execution_log.md`.
- B8: Suite completa `run_pytest_safe.py` termina en exit code 0 con
  `last-run.json.tested_commit_sha == HEAD` tras el commit de handoff.
- B9: `ruff check .` exit code 0 sobre el diff completo.

## Evidencia esperada en execution_log.md

- Comando + output de la corrida pre-fix (Fase 1.1, con 1.1.1/1.1.3 en rojo).
- Comando + output de la corrida post-fix (Fase 2, los 5 tests en verde).
- Comando + output del mutation-verify (Fase 3.1: revertir -> rojo; restaurar
  -> verde).
- Comando + output de `ruff check .` y `run_pytest_safe.py` (Fase 3.2).
- Diff resumen (`git diff --stat`) mostrando SOLO los 2 archivos de FLT
  tocados.

## Riesgos identificados (para la review del Manager)

- Severidad ALTA: `resolve_motor_checkpoint_files` es una gate de cierre NO
  bypasseable (agent_controller.py:1704). Un error en la relajacion de Step 3
  podria abrir un bypass de seguridad del proceso de cierre. Mitigacion:
  Blockers B1-B7 cubren explicitamente los 5 escenarios (no-HEAD legitimo,
  HEAD control, entrega vacia, no-ancestro, subject sin ticket_id) + mutation-
  verify. El Manager debe re-ejecutar personalmente los 5 tests nuevos en la
  review, no confiar solo en el reporte del Builder.
- Severidad MEDIA: si el Builder decide que `agent_controller.py` SI necesita
  tocarse (contradiciendo el analisis de superficie de este plan), eso es una
  discrepancia de scope que debe escalarse ANTES de modificar el archivo (ver
  B6), no decidirse unilateralmente.
- Severidad BAJA: el mensaje de guidance nuevo (Fase 2.2) es solo texto
  informativo; no bloquea el cierre si el Builder omite la rama nueva de
  `print_motor_checkpoint_guidance`, pero SI debe implementarla porque el
  work_plan la marca como Fase 2.2 obligatoria (no opcional) con su propio
  criterio de aceptacion verificable.
