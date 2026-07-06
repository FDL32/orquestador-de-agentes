# Execution Log - WOT-2026-019j

Ticket: El scope gate no reconoce el heading `## Builder` para tickets
`deliverable_type=mixed`.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-06). Fase 0 (Orquestador)
  diagnostico las 3 superficies ANTES de bootstrapear, verificadas de nuevo
  por el Manager antes de aprobar:
  - `scope_gate.parse_files_likely_touched` (linea 347) y
    `scope_gate.files_likely_touched_tokens` (linea 143): mismo guard
    `_DOC_DELIVERABLE_TYPES` sin `mixed`.
  - Cadena del checkpoint del mark-ready
    (`_handle_mark_ready`, `agent_controller.py:3352`) ->
    `motor_checkpoint.parse_raw_flt_paths` -> `scope_gate.parse_flt_raw_paths`
    -> `parse_flt_raw_buckets` -> `_parse_flt_section`: esta ultima SOLO
    reconoce `## Files Likely Touched`, sin parametro `deliverable_type` ni
    fallback a `## Builder`.
  - Verificacion adicional del Manager: 2 call-sites mas de la misma
    `_parse_raw_flt_paths` dentro de `_handle_pre_handoff`
    (`agent_controller.py:3636` y `:3914`) comparten el mismo mecanismo de
    bug; se corrigen en el mismo ticket.
- Decision de diseno: conjunto compartido `_FLT_BUILDER_FALLBACK_TYPES` para
  las superficies 1 y 2; parametro `deliverable_type` explicito (default
  `"code"`) por toda la cadena de la superficie 3, sin fallback
  incondicional (opcion descartada por blast-radius).
- work_plan.md, STRATEGY_WOT-2026-019j.md y AUDIT_WOT-2026-019j.md creados.
  execution_log.md de WOT-2026-019i archivado a
  execution_log_WOT-2026-019i.md antes de este bootstrap.
  STRATEGY_WOT-2026-019i.md y AUDIT_WOT-2026-019i.md archivados a
  `.agent/collaboration/_archive/plan_audit/` via
  `scripts/archive_collaboration_artifacts.py --project-root .`.
- Turno reseteado a BUILDER (`--reset-turn --force`), ticket a bootstrapear
  en el bus (`--bootstrap-ticket --json`).

## Implementacion (Builder + verificacion/cierre del Orquestador)

- PASO 1 (scope_gate.py sup. 1 y 2): `_FLT_BUILDER_FALLBACK_TYPES =
  _DOC_DELIVERABLE_TYPES | {"mixed"}`; guards de `files_likely_touched_tokens`
  y `parse_files_likely_touched` cambiados a ese conjunto.
- PASO 2 (scope_gate.py cadena raw): `_parse_flt_section`,
  `parse_flt_raw_buckets`, `parse_flt_raw_paths` reciben
  `deliverable_type="code"`; fallback a `## Builder` cuando FLT vacio y tipo en
  el conjunto.
- PASO 3 (motor_checkpoint + agent_controller): `parse_raw_flt_paths` recibe el
  parametro; 3 call-sites de `_parse_raw_flt_paths` en agent_controller pasan el
  deliverable_type correcto (`_dt_mr` mark-ready; `_dt_bom` leido local en el
  guard BOM del pre-handoff; `_dt_ph` en el commit-or-block del pre-handoff).
- PASO 4 (tests): 6 tests nuevos/renombrados en los 3 archivos focales, incl.
  `test_mixed_parses_builder_section_as_whitelist` (invierte el viejo
  `test_mixed_does_not_parse_builder_section`) y
  `test_parse_raw_flt_paths_code_default_ignores_builder` (protege que `code`
  NO cae al fallback).

### Arreglos del Orquestador (el Builder se corto antes de completarlos)
- REGRESION cazada por el Orquestador: `tests/test_agent_controller.py`
  (NO en el FLT original) tenia 3 monkeypatches de `_parse_raw_flt_paths` con
  `lambda content: {...}` -> al anadir el kwarg `deliverable_type` reventaban
  con `TypeError: <lambda>() got an unexpected keyword argument
  'deliverable_type'` (5 tests de `TestExternalMotorCheckpointTopology`).
  Fix: firma de los 3 lambdas a `lambda content, **kwargs: {...}`. Tras el
  arreglo: `TestExternalMotorCheckpointTopology` 10 passed.
- C901: `_parse_flt_section` quedaba en complejidad 16 (>10) con el 2o escaneo
  inline. Extraido a helper `_parse_builder_fallback_entries(lines)` ->
  ruff check `All checks passed!`.

### Verificacion del Orquestador (re-corrida sobre el repo real)
- Tests focales (3 archivos scope_gate/motor_checkpoint): 40 passed.
- `tests/test_agent_controller.py -k "Congruence or CheckpointTopology or
  MarkReady or mark_ready"`: 15 passed (sin regresiones de firma).
- MUTATION-VERIFY (corrido 2x por el Orquestador: pre- y post-refactor C901):
  quitar `mixed` de `_FLT_BUILDER_FALLBACK_TYPES` -> FALLAN 4 tests de mixed
  cubriendo las 3 superficies:
  ```
  FAILED test_scope_gate_deliverable_aware.py::test_mixed_parses_builder_section_as_whitelist
  FAILED test_scope_gate_deliverable_aware.py::test_mixed_gate_no_warning_when_covered
  FAILED test_scope_gate_topology.py::test_raw_paths_mixed_falls_back_to_builder_section
  FAILED test_motor_checkpoint.py::test_parse_raw_flt_paths_mixed_falls_back_to_builder
  4 failed, 1 passed
  ```
  (el 1 passed = `test_mixed_with_flt_uses_flt_not_builder`, correcto: no
  depende del fallback). Restaurar -> 40 passed. Barrera viva, no placebo.
- ruff check + ruff format --check sobre los 7 archivos tocados: limpio.

Nota de scope: el diff toca `tests/test_agent_controller.py` (arreglo de
mocks de firma), que NO estaba en el FLT original -> el mark-ready dara
sobre-captura, se cerrara con --scope-override citando que es consecuencia
directa e inevitable del cambio de firma publica de `_parse_raw_flt_paths`.

## 4a SUPERFICIE (BLOCKER de Review 2 fresh-context, corregido por el Orquestador)

Review 2 fresh-context cazo un BLOCKER real que Fase 0, el Manager y Review 1
NO vieron: el fix cerraba las 3 superficies de la ficha (mark-ready checkpoint,
extension checks, check_scope_gate para repo_destino) pero DEJABA el warning de
`--validate` para tickets `mixed` `repo_motor` con `## Builder` -> el DoD del
ticket ("valida sin warning", work_plan l.16) quedaba a medias, y el caso
DOMINANTE es repo_motor (los tickets del propio motor). Causa:
`_check_scope_for_validate` (agent_controller.py:4344) enruta repo_motor por
`parse_flt_namespaced(plan_content)`, y `scope_gate.parse_flt_namespaced`
(scope_gate.py:281) llamaba `parse_flt_raw_buckets` SIN reenviar
`deliverable_type` -> el fallback a `## Builder` nunca se activaba por esa ruta.
REPRODUCIDO EN VIVO por el Orquestador: parse_flt_namespaced(mixed+Builder,
repo_motor) -> whitelist motor VACIA (pre-fix).

Fix (reenvio de deliverable_type por la cadena, patron identico, default "code"):
- `scope_gate.parse_flt_namespaced`: +param `deliverable_type="code"`, reenviado
  a `parse_flt_raw_buckets`.
- `agent_controller.parse_flt_namespaced` wrapper (l.333): lee `_read_deliverable_type`
  y lo reenvia (el call-site 4344 `parse_flt_namespaced(plan_content)` no cambia:
  el wrapper resuelve el tipo internamente).
- `scripts/pre_handoff_guard.py` (l.330): lee `_read_deliverable_type_from_content`
  y lo reenvia (misma ruta scope-discrepancy, coherencia).
- Tests nuevos en test_scope_gate_topology.py: `test_namespaced_mixed_falls_back_to_builder`
  (mixed+Builder+repo_motor -> whitelist motor no vacia) y
  `test_namespaced_code_default_ignores_builder` (code default -> vacio).

VERIFICADO EN VIVO post-fix: mixed -> {.agent/scope_gate.py, scripts/foo.py};
code -> vacio. MUTATION del Orquestador: quitar el reenvio en parse_flt_namespaced
-> `test_namespaced_mixed_falls_back_to_builder` FALLA (whitelist vacia). Sin
regresion: 42 tests focales, 30 tests agent_controller (checkpoint/validate/scope),
62 tests pre_handoff_guard, todos verde. ruff limpio.


Scope override: Sobre-captura del scope gate + falso positivo del parser (019l). git diff origin/main..HEAD (2 commits 91ad7c8+48d7d65) toca SOLO: scope_gate.py, motor_checkpoint.py, agent_controller.py, pre_handoff_guard.py (4a superficie del blocker de Review 2, fuera del FLT original pero consecuencia directa del fix), test_agent_controller.py (arreglo de 3 mocks lambda por el cambio de firma publica), y los 3 tests focales. 0 hits para todos los archivos AJENOS listados (AUDIT/PLAN 019a/019c/019i, bootstrap, run_gates_dispatch, test_check_publication_gate: artefactos de tickets ya cerrados). Los 'missing:' (motor_checkpoint.parse_raw_flt_paths, parse_flt_raw_paths, scope_gate.parse_flt_raw_paths) son falsos del parser FLT por substring que toma anotaciones de prosa como paths (ficha 019l). Suite 3511 verde tested_sha==HEAD 48d7d65. Verificado auditablemente.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019a.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019a.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019i.md, <REPO_ROOT>/motor_checkpoint.parse_raw_flt_paths, <REPO_ROOT>/parse_flt_raw_paths/parse_flt_raw_buckets, <REPO_ROOT>/prompts/orchestrator_session_bootstrap.md, <REPO_ROOT>/scope_gate.parse_flt_raw_paths), <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/scripts/run_gates_dispatch.py, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_check_publication_gate.py, <REPO_ROOT>/tests/unit/test_run_gates_dispatch.py

Manager approved canonical closeout for WOT-2026-019j