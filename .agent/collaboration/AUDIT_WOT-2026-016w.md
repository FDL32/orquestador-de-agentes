# AUDIT - WOT-2026-016w

**Ticket:** WOT-2026-016w - check_deliverables_exist.py descarta bullets FLT con anotacion
(bug gemelo de 016s).
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion: confirmar
  sintoma -> aplicar fix minimo -> anadir tests -> verificar no-regresion -> mutation ->
  gates -> commit/mark-ready. Ninguna fase pide crear y revertir el mismo cambio en el mismo
  paso; la unica reversion es la barrera de mutation, documentada como transitoria y
  restaurada de inmediato, no una contradiccion de alcance.
- TP-02: verificado - cada criterio de aceptacion del work_plan.md cita un comando pytest
  exacto con -k y el resultado esperado (N passed), el criterio de ruff cita el comando y
  exit code 0, el de suite canonica cita los 4 campos exactos del last-run.json
  (status=finished, exit_code=0, level=all, args_mode=default_discovery,
  tested_commit_sha == HEAD), y el criterio de mutation exige FAIL-sin-fix / PASS-con-fix
  registrado literalmente, no narrado.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos, cada
  bullet con una unica ruta parseable sin anotacion inline
  (scripts/check_deliverables_exist.py, tests/unit/test_check_deliverables_exist.py). Los
  Non-goals delimitan explicitamente que NO se toca .agent/scope_gate.py,
  _extract_paths_from_generic_sections, _process_backtick_tokens ni
  resolve_with_fallbacks, para que el Builder no derive scope.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" u "opcionalmente" en el
  flujo critico del work_plan.md. La unica clausula condicional aparece en STOP conditions
  ("si uv run ruff format --check no arranca...") y cierra la decision de forma explicita
  (usar el equivalente .venv y documentarlo), no delega alcance al Builder.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-016w.md y este AUDIT describen la misma
  secuencia (fix de primer-token en _resolve_flt_bullet_tokens, 2 tests nuevos, verificacion
  del test anti-narrativa existente, mutation FAIL/PASS, gates de ruff/pytest/suite
  canonica), los mismos 2 archivos de Files Likely Touched y los mismos 8 criterios de
  cierre. Los Blockers de este AUDIT (ver abajo) usan los mismos verbos que las Fases del
  PLAN ("aplicar el fix de primer token", "anadir los 2 tests", "verificar no-regresion",
  "ejercer mutation").
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma canonica
  TP-01..TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo "si existe" / "si
  aplica" en Objetivo, Fases, Criterios ni Decision Arquitectonica del work_plan.md. La
  unica condicional tecnica (sustituir uv por .venv si uv esta roto) esta acotada a un gate
  de tooling, no a la decision de alcance del ticket, y ambas ramas quedan definidas
  (ejecutar el gate real, documentar la sustitucion).

## Matiz de diseno anti-narrativa (verificado en codigo, no inferido)

El docstring de _resolve_flt_bullet_tokens (scripts/check_deliverables_exist.py, lineas
235-243) documenta EXPLICITAMENTE que el filtro de espacio existe para rechazar bullets
narrativos como "Notas: los scripts inspeccionados (`foo.py`, `bar.py`) son read-only".
Ese caso concreto ya tiene cobertura de regresion:
tests/unit/test_check_deliverables_exist.py::test_wot_010j_real_case_narrative_note_not_treated_as_deliverable
(lineas 139-170), que usa el texto narrativo REAL de WOT-2026-010j y exige code == 0. El
fix propuesto (tomar solo el primer token, igual que scope_gate._normalize_flt_line desde
WOT-2026-016s) preserva ese comportamiento: el primer token de una linea narrativa tipica
no pasa looks_like_path (no tiene punto ni slash/backslash como exige la funcion en linea
63-71 del mismo archivo), mientras que el primer token de un bullet anotado con path real
si lo pasa. CONFIRMADO, no refutado: el Manager debe re-ejecutar
test_wot_010j_real_case_narrative_note_not_treated_as_deliverable tras el fix del Builder y
tratar cualquier fallo ahi como bloqueante de cierre (ver STOP conditions del work_plan.md).

## Blockers (para el Manager en review)

- Si _resolve_flt_bullet_tokens sigue usando `" " in normalized: return` sobre la linea
  completa (sin tomar el primer token) tras el commit del Builder: BLOCKER, el fix no fue
  aplicado.
- Si test_wot_010j_real_case_narrative_note_not_treated_as_deliverable falla o fue
  modificado/relajado para forzar verde: BLOCKER, viola la STOP condition explicita del
  work_plan.md.
- Si no hay evidencia literal (comando + output) de FAIL-sin-fix / PASS-con-fix para el
  test de mutation: BLOCKER, el criterio de aceptacion 3 no esta satisfecho.
- Si .agent/scope_gate.py aparece tocado en el diff: BLOCKER, fuera de scope (Non-goals).
- Si la suite canonica (run_pytest_safe.py --level all) no tiene tested_commit_sha == HEAD
  del commit final: BLOCKER, no es cierre canonico.

## Evidencia esperada en execution_log.md

- Cita literal de la funcion _resolve_flt_bullet_tokens antes y despues del cambio (diff o
  snippet).
- Salida literal de: pytest -k wot_016w_flt_bullet_with_trailing_annotation -v (2 passed).
- Salida literal de: pytest -k wot_010j_real_case_narrative_note_not_treated_as_deliverable -v
  (1 passed).
- Salida literal de: pytest tests/unit/test_check_deliverables_exist.py -v (11 passed).
- Salida literal de mutation: FAIL-sin-fix (comando + output) y PASS-con-fix (comando +
  output).
- Salida literal de ruff check y ruff format --check (o su sustituto documentado).
- Salida literal (o referencia a last-run.json) de la suite canonica con los 4 campos
  exactos y tested_commit_sha == HEAD.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-016w en el mensaje.
