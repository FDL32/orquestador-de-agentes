# AUDIT - WOT-2026-019j

Ticket: El scope gate no reconoce el heading `## Builder` para tickets
`deliverable_type=mixed`.
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion:
  PASO 1 (guard de `scope_gate.py` para `parse_files_likely_touched` y
  `files_likely_touched_tokens`) -> PASO 2 (parametro `deliverable_type` en la
  cadena `_parse_flt_section`/`parse_flt_raw_buckets`/`parse_flt_raw_paths`)
  -> PASO 3 (`motor_checkpoint.parse_raw_flt_paths` + 3 call-sites de
  `agent_controller.py`) -> PASO 4 (tests de regresion + mutation-check).
  Ningun paso pide anadir y quitar el mismo guard en el mismo punto; el
  mutation check del PASO 4 es explicitamente temporal y documentado, no
  queda en el commit final.
- TP-02: verificado - cada DoD cita un comando o asercion literal: llamadas
  concretas a `scope_gate.parse_files_likely_touched(...,
  deliverable_type="mixed")`, `scope_gate.parse_flt_raw_paths(...,
  deliverable_type="mixed", target="motor")`,
  `motor_checkpoint.parse_raw_flt_paths(plan, deliverable_type="mixed")`,
  nombres exactos de tests nuevos/renombrados, y comandos de pytest/ruff con
  rutas exactas de archivo.
- TP-03: verificado - Files Likely Touched enumera exactamente 6 archivos
  concretos (`.agent/scope_gate.py`, `.agent/motor_checkpoint.py`,
  `.agent/agent_controller.py`, `tests/unit/test_scope_gate_deliverable_aware.py`,
  `tests/unit/test_scope_gate_topology.py`, `tests/unit/test_motor_checkpoint.py`),
  sin comodines. Read/inspect only enumera 2 superficies concretas
  (`_DOC_DELIVERABLE_TYPES_CONGRUENCE`/`_check_deliverable_type_file_congruence`
  en `agent_controller.py`, y la clase `TestDeliverableTypeFileCongruence` en
  `tests/test_agent_controller.py`) explicitamente fuera de alcance de
  edicion.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" en el
  flujo critico. La decision de diseno (opcion (a) quirurgica vs opcion (b)
  fallback incondicional) esta cerrada explicitamente en
  "Decision Arquitectonica" del work_plan.md, con blast-radius razonado, no
  delegada como heuristica libre al Builder.
- TP-05: verificado - work_plan.md, STRATEGY_WOT-2026-019j.md y este AUDIT
  describen la misma secuencia (guard compartido en scope_gate.py + parametro
  deliverable_type por la cadena FLT raw + 3 call-sites de
  agent_controller.py + tests con mutation-check), los mismos 6 archivos de
  Files Likely Touched, y los mismos 8 criterios de aceptacion global. Los
  Blockers de este AUDIT usan los mismos verbos que las STOP conditions del
  PLAN (no tocar `_DOC_DELIVERABLE_TYPES_CONGRUENCE`, no cambiar defaults, no
  reintroducir el guard roto).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01 a TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo "si
  existe" o "si aplica" en Objetivo, Fases o Criterios de Aceptacion Global
  del work_plan.md decidiendo cuando se activa el fix: la decision (siempre
  anadir `mixed` al guard compartido y pasar `deliverable_type` explicito por
  la cadena raw) esta cerrada sin condicionalidad de alcance delegada al
  Builder.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-06) por lectura directa del codigo real
(sin re-derivar, solo confirmando lo ya verificado por el Orquestador):

- `.agent/scope_gate.py:58`: `_DOC_DELIVERABLE_TYPES = frozenset({"analysis",
  "documentation", "research"})`, sin `mixed`.
- `.agent/scope_gate.py:143` (`files_likely_touched_tokens`) y `:347`
  (`parse_files_likely_touched`): ambas usan
  `if not <tokens|files> and deliverable_type in _DOC_DELIVERABLE_TYPES:`
  como guard de fallback a `## Builder`.
- `.agent/scope_gate.py:169-209` (`_parse_flt_section`): la firma es
  `_parse_flt_section(lines: list[str]) -> tuple[...]`, SIN parametro
  `deliverable_type`; solo reconoce
  `"## Files Likely Touched" in stripped and stripped.startswith("## ")`
  (linea 184); no hay ninguna mencion a `## Builder` en toda la funcion.
- Cadena de llamadas confirmada por grep exacto: `agent_controller.py:3352`
  (`_handle_mark_ready`) llama `_parse_raw_flt_paths(plan_content)`;
  `agent_controller.py:3582` define el alias
  `_parse_raw_flt_paths = motor_checkpoint.parse_raw_flt_paths`;
  `motor_checkpoint.py:180-200` (`parse_raw_flt_paths`) llama
  `scope_gate.parse_flt_raw_paths(plan_content, delivery_authority=
  "repo_motor", target="motor")`, SIN pasar `deliverable_type` (la funcion
  no tiene ese parametro hoy); `scope_gate.py:274-301`
  (`parse_flt_raw_paths`) llama `parse_flt_raw_buckets` (linea 288); y
  `scope_gate.py:244-271` (`parse_flt_raw_buckets`) llama
  `_parse_flt_section(lines)` (linea 254) sin ningun parametro adicional.
- `agent_controller.py:3339-3342`: dentro de `_handle_mark_ready`,
  `_non_code_ticket = _dt_mr in {"documentation", "research", "analysis"}`;
  si es `True`, `checkpoint_scope_pass = True` y el checkpoint entero se
  salta. `mixed` no esta en ese set literal.
- `agent_controller.py:3636` y `:3914`: ambos dentro de la misma funcion
  `_handle_pre_handoff` (confirmado con `awk` sobre los limites de funcion:
  la unica `def` entre las lineas 3597 y 4000 es `_handle_pre_handoff` en la
  linea 3597), y ambos llaman `_parse_raw_flt_paths(plan_content)` sin el
  parametro. `_dt_ph = _read_deliverable_type(plan_content)` se define en la
  linea 3726: DESPUES de la linea 3636 (esa linea no tiene ninguna variable
  de deliverable_type disponible en su scope) pero ANTES de la linea 3914
  (que si puede reusar `_dt_ph`).
- `tests/unit/test_scope_gate_deliverable_aware.py:173-174`
  (`test_mixed_does_not_parse_builder_section`) hoy afirma
  `_parse(_MIXED_BUILDER_ONLY, deliverable_type="mixed") == set()`: prueba
  viva de que el comportamiento actual es el contrario al DoD de este
  ticket.
- `tests/unit/test_scope_gate_topology.py:277-279`
  (`test_raw_flt_no_section_returns_empty`) llama
  `motor_checkpoint.parse_raw_flt_paths(_NO_FLT)` SIN el argumento nuevo y
  espera `set()`; `_NO_FLT` (linea 77) no contiene `## Builder`, asi que el
  nuevo parametro con default `"code"` preserva este resultado sin cambios.
- grep de `_DOC_DELIVERABLE_TYPES` sobre `.agent/` y `tests/` confirma
  exactamente 3 usos del conjunto en `scope_gate.py` (definicion + 2 guards)
  y ningun otro caller externo a los descritos en el work_plan.md.
- grep de `_DOC_DELIVERABLE_TYPES_CONGRUENCE` confirma que es un conjunto
  DISTINTO, definido en `agent_controller.py:1238`, usado solo dentro de
  `_check_deliverable_type_file_congruence` (linea 1241-1264), con proposito
  inverso (advertir cuando doc-type declara codigo); no se toca.
- `git status --short`: arbol limpio antes del bootstrap (HEAD ==
  origin/main == 4a8fd22).

## Blockers (para el Manager en review)

- Si `.agent/scope_gate.py` conserva `_DOC_DELIVERABLE_TYPES` (en vez de
  `_FLT_BUILDER_FALLBACK_TYPES`) como guard en `parse_files_likely_touched` o
  `files_likely_touched_tokens`: BLOCKER, el fix no se aplico.
- Si `_parse_flt_section`, `parse_flt_raw_buckets`, `parse_flt_raw_paths` o
  `motor_checkpoint.parse_raw_flt_paths` NO tienen el parametro
  `deliverable_type` con default `"code"`: BLOCKER, la superficie 3 sigue
  ciega.
- Si alguno de los 3 call-sites de `agent_controller.py` (lineas 3352, 3636,
  3914 en el codigo pre-fix) sigue llamando
  `_parse_raw_flt_paths(plan_content)` sin el argumento `deliverable_type`:
  BLOCKER, reproduce exactamente el bug original en ese call-site.
- Si el diff anade `mixed` a `_DOC_DELIVERABLE_TYPES_CONGRUENCE` o modifica
  `_check_deliverable_type_file_congruence`: BLOCKER, fuera de alcance,
  rompe la semantica inversa de ese guard (mixed con codigo es legitimo).
- Si el fallback de `_parse_flt_section` se activa incondicionalmente (sin
  mirar `deliverable_type`) para CUALQUIER tipo cuando falta
  `## Files Likely Touched`: BLOCKER, reproduce la opcion de diseno
  descartada (opcion b), amplia la superficie mas alla de lo aprobado.
- Si `test_mixed_does_not_parse_builder_section` sigue existiendo tal cual
  (afirmando el comportamiento contrario al DoD) en vez de haber sido
  renombrado/invertido: BLOCKER, el test viejo y el fix son contradictorios
  y la suite no puede estar en verde con ambos.
- Si alguno de los tests nuevos NO falla al revertir el fix (mutation check
  ausente o mal ejecutado, documentado con salida literal de pytest):
  BLOCKER, no hay evidencia de que el test verifique el mecanismo real en
  vez de ser un placebo.
- Si algun test existente de los 4 archivos de test tocados, o de
  `TestDeliverableTypeFileCongruence` en `tests/test_agent_controller.py`,
  se rompe con el cambio (deben seguir pasando sin cambios en su codigo):
  BLOCKER.
- Si `ruff check` o `ruff format --check` fallan sobre cualquiera de los 6
  archivos modificados: BLOCKER, gate de calidad no satisfecho.
- Si la suite canonica (`run_pytest_safe.py`) no queda verde con stamp
  fresco sobre HEAD antes de mark-ready: BLOCKER, el gate de pre-handoff no
  confiara en el resultado.
- Si `execution_log.md` no documenta el mutation check (revertir el fix,
  fallo de los tests nuevos, restauracion, exito) con salida literal de
  pytest: BLOCKER, evidencia insuficiente.
- Si el diff cambia la firma publica de cualquier funcion existente de
  `scope_gate.py`/`motor_checkpoint.py` mas alla de anadir el parametro
  `deliverable_type` con default `"code"`: BLOCKER, rompe el contrato que
  usan los callers existentes.

## Evidencia esperada en execution_log.md

- Diff final (o cita literal) de `.agent/scope_gate.py` mostrando
  `_FLT_BUILDER_FALLBACK_TYPES`, el guard actualizado en las 2 funciones de
  PASO 1, y el parametro `deliverable_type` en las 3 funciones de PASO 2.
- Diff final (o cita literal) de `.agent/motor_checkpoint.py` mostrando el
  parametro nuevo en `parse_raw_flt_paths`.
- Diff final (o cita literal) de los 3 call-sites modificados en
  `.agent/agent_controller.py` (lineas 3352, 3636, 3914 en el codigo
  pre-fix), mostrando el argumento `deliverable_type` pasado en cada uno.
- Cita literal de los tests nuevos/renombrados en los 3 archivos de test.
- Salida literal de pytest del mutation check: ANTES de revertir el fix
  (verde, incluyendo los tests nuevos), DESPUES de revertir (los tests
  nuevos FALLAN mostrando el sintoma pre-fix: whitelist vacio, warning
  "No Files Likely Touched", o bloqueo del checkpoint), y tras restaurar el
  fix (verde de nuevo).
- Salida literal de pytest completo sobre los 5 archivos de test de
  scope_gate/motor_checkpoint, confirmando 0 fallos.
- Salida literal (o resumen con conteo exacto de tests) del subconjunto
  filtrado de `tests/test_agent_controller.py` (DeliverableType, ScopeGate,
  MarkReady, PreHandoff), confirmando que `TestDeliverableTypeFileCongruence`
  sigue en verde sin cambios.
- Salida literal del repro manual del DoD binario: un `work_plan.md` de
  prueba mixed + `## Builder` validando 0/0 y pasando `--mark-ready` sin
  `--scope-override`.
- Salida literal de `ruff check`/`ruff format --check` sobre los 6 archivos
  modificados, exit code 0.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  `scripts/run_pytest_safe.py` confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-019j en
  el mensaje.
- Confirmacion explicita (diff vacio o "sin cambios") de que
  `_DOC_DELIVERABLE_TYPES_CONGRUENCE`, `_check_deliverable_type_file_congruence`
  y `TestDeliverableTypeFileCongruence` no aparecen modificados en el diff
  final.
