# Execution Log - WOT-2026-016p

**Ticket:** WOT-2026-016p - Proyecciones regenerables con rutas absolutas: auto-gitignore install/sync + generadores PII-safe (N7 + B-PROJ)
**Estado:** COMPLETED
**HEAD al inicio:** 6af5677

> execution_log de 016b (COMPLETED) preservado en `execution_log_WOT-2026-016b.md`.

---

## Bootstrap

- Origen: N7 mordio en produccion 2026-07-03 (tanda backup 12 repos): el motor regenero
  project-map/link con rutas reales entre filter-repo y un add -A -> PII pusheada (cazada por
  Manager review, corregida con purga+force-push). Sugerencia formal del Manager: auto-gitignore.
- FLT: install_agent_system.py + project_scanner.py + destination_context.py +
  tests/test_projections_pii_safe.py (nuevo).

## Fase 0: Diagnostico (VERIFICADO)

- project_scanner.py:717 `"project_root": str(project_root)` (y schema doc :624 "absolute path").
- destination_context.py:377 `{project_root.resolve()}` y :382 `motor_link.get('motor_root')`.
- install_agent_system.py: 0 hits de gitignore -> funcionalidad nueva; hooks install() L1121
  y sync_agent_system() L1215.
- Consumidores verificados: _build_scanner_context_block lee summary/frameworks/importMap
  (NO project_root); scope_gate excluye el path, no lee contenido; batch_destination_controller
  ESCRIBE su propio "Motor root:" (no parsea el map). Cambio de semantica SEGURO.
- Link: solo-lectura en runtime/motor_link.py; contenido machine-specific por diseno (non-goal).

## Fase 1-2: pendiente de implementar (ver work_plan)

## Fase 1: Implementacion (EJECUTADA)

- install_agent_system.py: PROJECTIONS_GITIGNORE_MARKER + PROJECTIONS_GITIGNORE_ENTRIES (5) +
  ensure_destination_projections_ignored() idempotente (respeta lineas de usuario, dry_run);
  hooks en install (tras mkdir) y sync (tras check de existencia).
- project_scanner.py:717 project_root -> .name (+ schema doc :624). Consumidores no afectados
  (verificado Fase 0).
- destination_context.py:377/382 Destination root y Motor root -> nombres, no rutas.

## Fase 2: Tests (VERDE con barrera)

- tests/test_projections_pii_safe.py: 6 tests (anade-todo, idempotencia sin duplicados,
  respeta entradas de usuario, dry-run no escribe, project-map sin rutas absolutas
  (regex [A-Za-z]:[\/]|/home/), link name-derivation).
- BARRERA FAIL-sin/PASS-con VERIFICADA: git stash del fix de project_scanner ->
  test_project_map_has_no_absolute_paths FAILED; stash pop -> passed.

## Gates

- pytest focal: 6 passed (+ naming 25 total). ruff check: 1 fixed, 0 remaining; format ok.
- encoding guard exit 0. Suite canonica + validate: pendientes tras commit.

## Hallazgo de suite (gestionado)

- Suite --level all a 520b03a: 3 failed en test_destination_context (asertaban el contrato
  VIEJO: ruta absoluta presente). Actualizados al contrato del ticket: nombre presente +
  ruta absoluta AUSENTE (asercion MAS fuerte, no relajacion). 26/26 verdes tras el cambio.


Scope override: test_projections_pii_safe.py esta en el FLT del work_plan (parser no reconoce la subseccion, bug conocido de 016b); test_destination_context.py = actualizacion de 3 asserts al contrato nuevo del ticket, documentada en AUDIT/execution_log y entregada en commit a7d4a87 junto a 520b03a. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016b.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-018a.md, <REPO_ROOT>/.pre-commit-config.yaml, <REPO_ROOT>/prompts/_shared/finding_triage_protocol.md, <REPO_ROOT>/prompts/manager_review.md, <REPO_ROOT>/prompts/orchestrator_launch_builder.md, <REPO_ROOT>/prompts/orchestrator_pipeline.md, <REPO_ROOT>/prompts/orchestrator_session_close_full_audit.md, <REPO_ROOT>/scripts/check_hook_interpreter.py, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_check_hook_interpreter.py, <REPO_ROOT>/tests/test_destination_context.py, <REPO_ROOT>/tests/test_projections_pii_safe.py

Manager approved canonical closeout for WOT-2026-016p