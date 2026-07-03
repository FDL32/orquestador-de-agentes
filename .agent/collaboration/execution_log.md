# Execution Log - WOT-2026-016s

**Ticket:** WOT-2026-016s - mark-ready: el parser de Files Likely Touched descarta el path
cuando el bullet lleva anotacion descriptiva tras la ruta.
**Estado:** READY_FOR_REVIEW
**HEAD al inicio:** 78b5ee0
**delivery_authority:** repo_motor | **deliverable_type:** code

> execution_log de WOT-2026-015l (COMPLETED) preservado en
> `execution_log_WOT-2026-015l.md` antes de este bootstrap.

## Fase 0 - Diagnostico del Manager (EJECUTADA en fase de planificacion)

- Premisa original del backlog ("el parser no reconoce subsecciones repo_motor") verificada
  como IMPRECISA. Causa raiz real confirmada en vivo:
  scope_gate._looks_like_path_token('scripts/x.py (nuevo)') devuelve False porque rechaza
  cualquier token con espacio, y _normalize_flt_line no separa el path de la anotacion
  descriptiva que lo sigue.
- Reproducido end-to-end sobre el work_plan.md real de WOT-2026-015l (subseccion repo_motor
  + bullets anotados tipo "(nuevo, el gate)"): parse_files_likely_touched y
  parse_flt_raw_buckets devuelven whitelist/buckets VACIOS sin el fix.
- Fix propuesto simulado (monkeypatch de _normalize_flt_line con split en el primer espacio)
  y verificado contra el propio work_plan.md de este ticket: resuelve correctamente los 3
  paths del FLT al bucket "motor", bucket "destino" vacio.
- Hallazgo colateral documentado como Non-goal (no corregido en este ticket):
  scripts/check_deliverables_exist.py tiene _resolve_flt_bullet_tokens con el mismo bug
  (su propio docstring dice que espeja el comportamiento de scope_gate).

## Fase 1 - Implementacion (Builder)

- Modificado `.agent/scope_gate.py::_normalize_flt_line`: tras el lstrip/replace/strip
  actual, si el resultado no es vacio se le aplica `cleaned.split(" ", 1)[0]`, quedandose
  solo con el primer token separado por espacio (el path) y descartando cualquier
  anotacion descriptiva posterior. No se toco `_looks_like_path_token`, `_parse_flt_section`
  ni ningun call-site (los 3 consumidores heredan el fix automaticamente al compartir la
  funcion). Diff exacto (verificado con `git diff .agent/scope_gate.py` tras el fix y de
  nuevo tras el mutation-verify, identico byte a byte ambas veces).

## Fase 2 - Tests + mutation-verify (Builder)

- `tests/unit/test_scope_gate.py::TestParseFilesLikelyTouched::test_parse_flt_with_trailing_annotation_after_path`
  (nuevo): bullet `` - `scripts/foo.py` (nuevo, el gate) `` bajo `## Files Likely Touched`
  (ruta plana, sin subseccion) -> `parse_files_likely_touched(content)` (wrapper de
  `agent_controller`, que resuelve contra `PROJECT_ROOT` == `_MOTOR_ROOT` del test) devuelve
  `{str((_MOTOR_ROOT / "scripts/foo.py").resolve())}`. Nota de ajuste respecto al nombre
  literal del work_plan: el wrapper `agent_controller.parse_files_likely_touched` NO acepta
  kwarg `project_root` (firma fija a `PROJECT_ROOT`); como el archivo de test importa ese
  wrapper (no `scope_gate.parse_files_likely_touched` directamente) y `_MOTOR_ROOT` ya es
  `PROJECT_ROOT.resolve()`, se llamo sin `project_root=` replicando el patron de los tests
  preexistentes de la misma clase (`test_parse_simple_files`, etc.).
- `tests/unit/test_scope_gate_topology.py::test_namespaced_motor_annotated_path_resolves`
  (nuevo): fixture `_NAMESPACED_MOTOR_ANNOTATED` con subseccion `### repo_motor` y bullet
  `` - `scripts/bar.py` (nuevo) `` -> `scope_gate.parse_flt_raw_buckets(...)` devuelve
  `bucket["motor"] == {"scripts/bar.py"}` y `bucket["destino"] == set()`.
- Regresion cero confirmada: familia completa de 4 archivos (test_scope_gate.py,
  test_scope_gate_topology.py, test_scope_gate_deliverable_aware.py,
  test_scope_gate_isolation.py) -> 55 passed, 0 failed.

### MUTATION-VERIFY (obligatorio, CEM)

Comando usado en las 4 corridas (mismo comando, fuente mutado/restaurado entre medias):
`.venv/Scripts/python.exe -m pytest tests/unit/test_scope_gate.py -k trailing_annotation
tests/unit/test_scope_gate_topology.py -k "trailing_annotation or annotated" -v`

1. (a) Test SIN fix (revertido manualmente `_normalize_flt_line` a la forma original de
   una sola linea, sin el `.split(" ", 1)[0]`): **2 failed** (ambos tests nuevos), **exit
   code 1**. Evidencia literal:
   `AssertionError: assert set() == {'C:\\Users\\...\\scripts\\foo.py'}` (test 1) y
   `AssertionError: assert set() == {'scripts/bar.py'}` (test 2).
2. (b) Codigo observado: **1**.
3. (c) Test CON fix restaurado (mismo texto exacto reaplicado): **2 passed**, **exit code
   0**.
4. (d) Codigo observado: **0**.

Restauracion verificada: `git diff .agent/scope_gate.py` tras el mutation-verify es
IDENTICO al diff capturado justo despues de aplicar el fix en Fase 1 (mismo patch, sin
diferencias residuales de la mutacion temporal).

## Fase 3 - Verificacion end-to-end (Builder)

- El `work_plan.md` real de WOT-2026-015l ya estaba sobrescrito por el bootstrap de este
  ticket (015l era COMPLETED). El AUDIT_WOT-2026-015l.md no contiene el fragmento FLT
  literal, asi que se reconstruyo via `git show a39cdea:.agent/collaboration/work_plan.md`
  (commit deliverable de 015l citado en el work_plan de este ticket), extrayendo la seccion
  `## Files Likely Touched` completa:
  ```
  ## Files Likely Touched

  ### repo_motor
  - `scripts/check_closeout_reconciliation.py` (nuevo, el gate)
  - `tests/unit/test_check_closeout_reconciliation.py` (nuevo, fixtures A/B + mutation)

  ## Non-goals
  ```
- Script de verificacion ejecutado desde el scratchpad de sesion (no forma parte del
  repo): construye ese CONTENT literal y llama a
  `scope_gate.parse_flt_raw_buckets(CONTENT, delivery_authority="repo_motor")` y
  `scope_gate.parse_files_likely_touched(CONTENT, project_root=<repo_root>,
  deliverable_type="code")`.
- Resultado (exit 0):
  - `buckets["motor"] == {"scripts/check_closeout_reconciliation.py",
    "tests/unit/test_check_closeout_reconciliation.py"}` (NO vacio, 2 paths esperados).
  - `buckets["destino"] == set()`.
  - `parse_files_likely_touched(...)` devuelve el set con ambos paths resueltos contra
    project_root.
  - Confirma el sintoma original resuelto: sobre el FLT real de 015l (subseccion
    repo_motor + bullets anotados), el whitelist deja de estar vacio.

## Hallazgo colateral (Non-goal, ver work_plan) - NO corregido en este ticket

`scripts/check_deliverables_exist.py::_resolve_flt_bullet_tokens` reimplementa el mismo
criterio de rechazo (bullet con espacio tras normalizar -> descartado) y comparte el mismo
bug de raiz (su propio docstring dice que espeja `scope_gate._normalize_flt_line` /
`_looks_like_path_token`). Confirmado NO tocado en este ticket (Non-goal explicito del
work_plan). Se deja anotado para que el Manager decida si abre ticket de seguimiento
(mismo patron AP-D04, mismo fix, otro archivo).

## Notas de handoff

- El Manager (esta sesion) NO ejecuto `--reset-turn` ni `--bootstrap-ticket`: por
  instruccion explicita del orquestador, esos pasos quedan a cargo del Orquestador
  despues de este reporte. TURN.md/STATE.md aun reflejan el ciclo anterior (015l
  COMPLETED / accion CREATE_PLAN) hasta que se ejecuten esos comandos.
- Artefactos de handoff producidos por el Manager en esta sesion: work_plan.md
  (APPROVED), AUDIT_WOT-2026-016s.md, este execution_log.md (IN_PROGRESS). Pendientes
  antes de abrir la ventana del Builder: TURN.md/STATE.md regenerados y evento
  STATE_CHANGED -> IN_PROGRESS emitido al bus.


Scope override: over-captura de archivos de tickets ya cerrados (015l/016m/016o: AUDIT+check_closeout+check_publication) ajenos al diff real de 016s (4c79e8e = scope_gate.py + 2 tests scope_gate + proyecciones); el WARN de FLT ausente ya NO aparece = 016s dogfoodeado OK. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-015l.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016m.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016o.md, <REPO_ROOT>/.agent/runtime/memory/archive/observations.2026-07.jsonl, <REPO_ROOT>/scripts/check_closeout_reconciliation.py, <REPO_ROOT>/scripts/check_publication_gate.py, <REPO_ROOT>/tests/test_check_publication_gate.py, <REPO_ROOT>/tests/unit/test_check_closeout_reconciliation.py