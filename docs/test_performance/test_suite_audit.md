# Auditoria de valor de la suite de tests -- WOT-2026-013e

> Inventario durable y auditable de la suite del motor por familias y riesgo.
> Ticket de tipo `analysis`: este reporte NO borra, relaja, `xfail` ni `skip`
> ningun test, y NO toca `tests/`, runner, CI ni producto. Su salida son
> follow-ups pequenos y verificables para poda segura en tickets posteriores.

## Alcance y anclaje

- **repo_motor HEAD auditado:** `162e506` (arbol limpio al momento de auditar).
- **Metodo:** read-only sobre `tests/` mas relectura de la evidencia previa
  durable (`010j`, `010k`, `010p`, `010l`). Conteos estructurales generados
  frescos contra `162e506`; los tiempos historicos se anclan a su propio SHA.
- **Fronteras cerradas que este ticket NO reabre:** `011e`/`010m`/`011i`
  (frontera xdist local/CI/default) y `013d` (producto: escaneo ante borrados
  concurrentes). Ver "No-goals respetados" al final.

## Nota de reconciliacion (evidencia vs HEAD)

`.agent/runtime/pytest-safe/last-run.json` reporta `exit_code=0`,
`tested_commit_sha=e251bd7`, `level=all`, `args_mode=default_discovery`. El HEAD
actual (`162e506`) esta **3 commits por delante** de `e251bd7`, y entre ambos se
tocaron dos archivos de test (`tests/test_project_paths.py`,
`tests/unit/test_project_scanner.py` en `162e506`). Por tanto:

- Los **tiempos** de `last-run.json` y de las baselines `010j`/`010p` se tratan
  como **evidencia historica anclada a su SHA**, no como medicion fresca del
  HEAD. (STOP condition del contrato: "no depender de output viejo no
  reconciliado con el HEAD actual").
- Los **conteos estructurales** de este reporte (familias, archivos, tests
  recolectados, markers, skips) se regeneraron contra `162e506` con comandos
  reproducibles, listados abajo.

## VERIFICADO: inventario estructural (HEAD 162e506)

Comando autoritativo de recoleccion:

```
python -m pytest tests --collect-only -q -p no:cacheprovider
=> 3111 tests collected
```

### Conteo por directorio (collect-only, autoritativo)

| Directorio | Tests recolectados | Archivos test_*.py | Comando de conteo |
|------------|--------------------|-----------------------|--------------------|
| `tests/` (root) | 1780 | 80 | `pytest $(find tests -maxdepth 1 -name 'test_*.py') --collect-only -q` |
| `tests/unit/` | 1289 | 90 | `pytest tests/unit --collect-only -q` |
| `tests/integration/` | 5 | 2 | `pytest tests/integration --collect-only -q` |
| `tests/evals/` | 37 | 4 | `pytest tests/evals --collect-only -q` |
| `tests/deprecated/` | **0 (no recolectado)** | 2 | excluido por `norecursedirs` |
| `tests/sandbox/` | smoke runtime | 1 | excluido por `norecursedirs` |
| **TOTAL recolectado** | **3111** | -- | `pytest tests --collect-only -q` |

`pytest.ini` excluye explicitamente `tests/sandbox tests/deprecated tests/debug`
de la recoleccion (`norecursedirs`). El crecimiento 2933 (`010p`) -> 3111 (HEAD)
es coherente con la actividad de tickets desde entonces; no hay drop ni
duplicacion anomala.

### VERIFICADO: markers estructurales (collect -m, autoritativo)

| Marker | Tests | Comando |
|--------|-------|---------|
| `slow` | 1 | `pytest tests --collect-only -q -m slow` |
| `integration` | 5 | `pytest tests --collect-only -q -m integration` |
| `eval` | 37 | `pytest tests --collect-only -q -m eval` |

`pytest.ini` declara tres markers: `integration` (filesystem+subprocess real),
`slow` (escaneo de arbol grande) y `eval` (regresion de flujos criticos de
orquestacion, opt-in aislado).

### VERIFICADO: skips estructurales

- **Hard skip (`@pytest.mark.skip`):** 0.
- **`xfail`:** 0.
- **`skipif`:** 10 sitios en 5 archivos. Todos son **gates de entorno
  legitimos**, no skips cosmeticos ni muertos:

| Archivo | Condicion | Naturaleza |
|---------|-----------|------------|
| `tests/unit/test_launcher_powershell_syntax.py` (5) | `_resolve_powershell() is None` / `platform.system() != "Windows"` | Requiere PowerShell / WMI Windows |
| `tests/test_claude_memory_mirror.py` (2) | `sys.platform != "win32"` | Drive-letter solo resuelve en Windows |
| `tests/unit/test_launcher_bootstrap_error_paths.py` (1) | `_resolve_powershell() is None` | Requiere PowerShell |
| `tests/unit/test_run_llm_evals.py` (1) | `not CONFIG_PATH.exists()` | Requiere config local |
| `tests/test_project_map_freshness.py` (1) | `not (graphify-out/graph.json).exists()` | Artefacto local ausente (p.ej. CI) |

Estos `skipif` explican los ~20 `skipped` que reportan las corridas canonicas
(`010j`: 20 skipped; `010p`: 20 skipped). Son condicionales de entorno, no deuda.

## Clasificacion por familia y riesgo

Leyenda de clasificacion:
- **core regression**: protege comportamiento canonico de producto vivo; su
  borrado abriria un agujero de regresion real.
- **structural gate**: barrera de proceso/contrato (handoff, scope, nomenclatura,
  encoding, portabilidad) que falla-cerrado ante drift; protege el sistema, no
  un modulo de producto.
- **legacy candidate**: protege API/flujo retirado o es demo de infraestructura;
  candidato a poda con justificacion.
- **redundant candidate**: solapa cobertura con otro test mas barato/directo;
  candidato a consolidacion, no a borrado ciego.
- **unknown**: requiere medicion/lectura adicional antes de clasificar.

Cada fila marca **[V]** evidencia verificada (lectura directa / conteo
reproducible / fuente durable) o **[I]** inferencia limitada (heuristica por
nombre/agrupacion, no confirmada test-por-test).

### Bus / state-machine / supervisor / locks  -- core regression  [V]
- **Archivos (root):** `test_event_bus.py`, `test_event_bus_hygiene.py`,
  `test_bus_boundary.py`, `test_state_machine.py`, `test_supervisor.py`,
  `test_builder_lock.py`, `test_reconcile_ticket.py`,
  `test_durable_changes_requeue.py`, `test_preflight_reconcile_decision.py`.
  **Unit:** `test_bus_drift_detection.py`, `test_bus_emission_on_mark_ready.py`,
  `test_bus_integrity.py`, `test_bus_utils.py`, `test_motor_bus_isolation_barrier.py`,
  `test_builder_exit_and_breaker.py`.
- **Evidencia [V]:** el bus es "autoridad canonica absoluta" (AGENTS.md,
  bootstrap); las proyecciones derivan de el. `test_supervisor.py` aparece en el
  top de las baselines (`010j`/`010p`) por uso de subprocess real.
- **Riesgo de poda:** ALTO. No tocar.

### Controller / validate / closeout / completion  -- core regression  [V]
- **Archivos:** `test_agent_controller.py`, `test_controller_integration.py`,
  `test_session_closeout.py`, `test_get_closeout_skip.py`,
  `test_authority_report.py`, `test_completion_checker.py`,
  `test_completion_common.py`, `test_completion_integration.py`,
  `test_manager_approve.py`, `test_mark_ready_idempotency.py`,
  `test_session_close_observations.py`, `test_closeout_lessons.py`.
- **Evidencia [V]:** `--validate` es gate obligatorio pre-cierre (bootstrap,
  reglas). El ciclo de cierre canonico depende de estos.
- **Riesgo de poda:** ALTO. No tocar.

### Handoff / scope / deliverable / motor-scope gates  -- structural gate  [V]
- **Archivos (root):** `test_pre_handoff_guard.py`,
  `test_pre_handoff_motor_productive_changes.py`, `test_pre_handoff_multirepo.py`,
  `test_mark_ready_motor_scope.py`, `test_motor_root_gates.py`,
  `test_delivery_hygiene_check.py`, `test_review_packet_evidence_gate.py`.
  **Unit:** `test_scope_gate.py`, `test_scope_gate_deliverable_aware.py`,
  `test_scope_gate_isolation.py`, `test_scope_gate_topology.py`,
  `test_check_deliverables_exist.py`, `test_pre_handoff_checkpoint.py`,
  `test_check_destino_publish_ready.py`.
- **Evidencia [V]:** estos materializan barreras documentadas (`010i`, `010n`,
  `010u`, lecciones de memoria como guard-helper-must-fail-closed). Son las
  barreras canonicas de runner/handoff que el contrato pide listar.
- **Riesgo de poda:** ALTO. Falla-cerrado por diseno; borrarlos reabre clases de
  fallo ya cerradas con barrera.

### Review bridge / decision / requeue  -- core regression  [V]
- **Archivos:** `test_review_bridge.py`, `test_manager_review_bridge.py`,
  `test_review_cycle_e2e.py`, `test_blocker_signature.py`,
  `test_review_bridge_request_changes_logging.py`, `test_request_changes_requeue.py`,
  `test_review_budget_retry.py`, `test_review_strategy_selection.py`,
  `test_review_queue_rotation.py`, `test_decision_artifact.py`,
  `test_decision_parser.py`.
- **Evidencia [V]:** el parser del bridge fue causa raiz de un bug real
  (WP-2026-120, "inspect fantasma"); estos tests lo blindan.
- **Riesgo de poda:** ALTO. No tocar.

### Pausa / reanudacion lifecycle  -- core regression  [V]
- **Archivos:** `test_pause_ticket.py`, `test_resume_ticket.py`,
  `test_state_projection_probe.py`, `test_state_projection_sync.py`,
  `test_ticket_projection_write_path.py`.
- **Evidencia [V]:** `010d` introdujo el lifecycle `PAUSED` fail-closed; el
  contrato exigia tests explicitos de `--abort-paused-ticket` y resume.
- **Riesgo de poda:** ALTO. No tocar.

### Proceso/contrato: nomenclatura, prosa, encoding, portabilidad  -- structural gate  [V]
- **Archivos (root):** `test_check_naming.py`, `test_check_ticket_nomenclature.py`,
  `test_validate_ticket_prose.py`, `test_encoding_integrity.py`,
  `test_encoding_edge_cases.py`, `test_gitattributes_hygiene.py`,
  `test_agent_readme_references.py`, `test_manifest_validator.py`,
  `test_no_inline_ticket_regex.py`, `test_no_history_truncation.py`.
  **Unit:** `test_encoding_post_write_hook.py`, `test_check_backlog_contract.py`,
  `test_check_claude_settings_portability.py`, `test_check_ruff_hook_scope.py`,
  `test_work_plan_schema.py`, `test_validate_contract_formation.py`,
  `test_validate_host_prefix.py`, `test_validate_observations.py`,
  `test_invariant_order.py`, `test_no_legacy_topology_terms.py`,
  `test_ticket_prefix_compat.py`, `test_migrated_ticket_patterns.py`,
  `test_hook_ci_alignment.py`.
- **Evidencia [V]:** materializan gates documentados (encoding guard, ruff scope
  guard WP-2026-093, ticket nomenclature WOT-2026-010a, prose validator).
- **Riesgo de poda:** ALTO. Son las barreras estructurales del proceso.
- **Nota lentitud [V]:** `test_no_inline_ticket_regex.py` (~24s) y
  `test_no_legacy_topology_terms.py` (~62s en 010j, ya optimizado a ~0.2s por
  `010k`) son escaneo de arbol; ver "Familias lentas".

### Skills / discovery / resolver / config  -- core regression  [V]
- **Archivos (root):** `test_discover_skills.py`, `test_check_skill_collisions.py`,
  `test_approval_state_revision_and_skill_access.py`, `test_goose_native_skill.py`,
  `test_registry_catalog.py`.
  **Unit:** `test_skill_discovery.py`, `test_skill_validate.py`,
  `test_skill_resolver_empty_catalog.py`, `test_discover_skills_bom.py`,
  `test_agents_config.py`, `test_configuration_loading.py`.
- **Evidencia [V]:** discovery/resolver son los 6 consumidores que `010s`
  protegio durante la migracion user/model-invoked.
- **Riesgo de poda:** MEDIO-ALTO. `test_goose_native_skill.py` revisar (Goose
  esta DEPRECATED por WT-2026-254a) -> ver legacy candidates.

### Memoria / consolidacion / loaders  -- core regression  [V]
- **Archivos:** `test_memory.py`, `test_memory_consolidate.py`,
  `test_memory_loader_wing.py`, `test_pre_compact_hook.py`,
  `test_claude_memory_mirror.py`, `test_persistence_redaction.py`,
  `test_redact.py`, `test_semantic_logger.py`, `test_security_logging.py`.
- **Evidencia [V]:** memoria L1/L2/L3 via `bus/memory_loader.py` es contrato
  documentado; redaccion protege secretos.
- **Riesgo de poda:** ALTO (redaccion/seguridad). No tocar.

### Install / upgrade / migrate / doctor / rollback  -- core regression  [V]
- **Archivos:** `test_install_agent_system.py`, `test_upgrade.py`,
  `test_migrate_legacy_project.py`, `test_migration_bootstrap.py`,
  `test_doctor_agent_system.py`, `test_rollback.py`, `test_motor_link.py`,
  `test_motor_checkpoint.py`, `test_external_motor_script_bootstrap.py`,
  `test_check_motor_pristine.py`, `test_check_motor_destination_integration.py`,
  `test_cleanup_legacy.py`.
- **Evidencia [V]:** topologia motor/destino e integridad del motor son
  superficie critica de portabilidad.
- **Riesgo de poda:** ALTO. No tocar.

### Runner / gates / quality dispatch / performance harness  -- structural gate  [V]
- **Archivos (unit):** `test_run_pytest_safe.py`, `test_run_gates_dispatch.py`,
  `test_pip_audit_policy.py`, `test_quality_gates_workflow.py`,
  `test_windows_safe_temp_runtime.py`, `test_refactor_kit_performance.py`.
  **Root:** `test_refactor_kit_portable.py`, `test_refactoring_impact.py`.
- **Evidencia [V]:** el runner Windows-safe (`tests/ARCHITECTURE.md`) y el
  dispatch por `deliverable_type` (WP-2026-089/092/093) son barrera de gates.
- **Riesgo de poda:** ALTO. `011e`/`010m`/`011i` cerraron la frontera xdist
  aqui; **fuera de scope de 013e**.

### Launcher / supervisor scripts (PowerShell)  -- structural gate  [V]
- **Archivos:** `test_launch_agent_terminals_script.py`,
  `test_launcher_ps1_syntax.py`, `test_launcher_preflight.py`,
  `test_launcher_state_from_bus.py`, `test_status_bar_indicator.py`,
  `test_ui_state.py`, `test_ui_state_projector_scoping.py`,
  `test_ticket_activity_monitor.py`, `test_stop_hook.py`, `test_guard_paths.py`.
  **Unit:** `test_launcher_powershell_syntax.py`,
  `test_launcher_bootstrap_error_paths.py`, `test_launcher_opencode_invocation.py`,
  `test_launch_session.py`, `test_human_gate_timeout.py`,
  `test_claude_guard_entry.py`.
- **Evidencia [V]:** estos concentran los `skipif` de PowerShell/Windows
  (entorno-condicionales). Protegen el arranque del launcher y el guard de rutas.
- **Riesgo de poda:** ALTO (guard_paths es seguridad). No tocar; respetar skips
  de entorno.

### Publicacion / auditoria / health / classify  -- core regression / structural  [V]
- **Archivos:** `test_classify_publication.py`, `test_audit_rules.py`,
  `test_hermes_build_context_bundle.py`, `test_prepush_check.py`,
  `test_orquestador_scope.py`, `test_council_broker.py`,
  `test_create_checkpoint.py`, `test_relaunch_topology.py`,
  `test_relaunch_evidence_capsule.py`.
  **Unit:** `test_local_audit.py`, `test_local_audit_parsers.py`,
  `test_collect_system_health.py`, `test_compress_canonical.py`,
  `test_graph_context.py`, `test_detect_version.py`, `test_project_scanner.py`,
  `test_project_root_resolution.py`, `test_controller_project_map_cleanup.py`,
  `test_contract_gap_integration.py`, `test_feedback_split.py`,
  `test_manager_feedback_archive.py`, `test_archive_collaboration_artifacts.py`,
  `test_archive_execution_log.py`, `test_review_env.py`.
- **Riesgo de poda:** ALTO. Publicacion Git y health audit son superficie viva.

### Evals (opt-in, regresion de flujos criticos)  -- core regression  [V]
- **Archivos:** `tests/evals/test_eval_guard_paths.py`,
  `test_eval_requeue.py`, `test_eval_review_bridge.py`,
  `test_eval_scope_gate.py` (37 tests, marker `eval`).
  **Unit:** `test_run_llm_evals.py`.
- **Evidencia [V]:** marker `eval` = "regression tests for critical orchestration
  flows (isolated, opt-in)" (pytest.ini).
- **Riesgo de poda:** ALTO. Aislados y opt-in; bajo coste, alto valor.

### Legacy candidates  -- legacy candidate  [V]
| Item | Evidencia [V] | Accion sugerida |
|------|---------------|-----------------|
| `tests/deprecated/test_goose_triggers.py`, `tests/deprecated/test_goose_realworld.py` | Ya excluidos por `norecursedirs`; Goose DEPRECATED (WT-2026-254a). NO se recolectan (0 tests). | Poda diferida: confirmar que no aportan referencia historica util antes de borrar el directorio. |
| `tests/unit/test_ejemplo.py` (2 tests) | Docstring: "Tests unitarios de ejemplo... demuestra como usar la infraestructura". No protege producto. | Candidato a mover a `tests/deprecated/` o documentar como smoke de fixtures; verificar primero que no es el smoke canonico de `tests/ARCHITECTURE.md`. |
| `tests/test_goose_native_skill.py` | Goose DEPRECATED; revisar si valida skill resolver vigente o solo el path Goose retirado. | Inferencia [I]: requiere lectura del archivo antes de clasificar como poda. |

### Redundant candidates  -- redundant candidate  [I]
| Item | Inferencia limitada [I] | Por que NO borrar ciego |
|------|--------------------------|--------------------------|
| `test_scan_current_project` (slow, escaneo real) vs `test_scan_project_deterministic` (fixture sintetica) | `010k` ya elimino la SEGUNDA llamada redundante dentro de `test_scan_current_project`; el test real sigue siendo el unico que valida escaneo del repo real. | NO es redundante: es el unico contrato de escaneo real. Marcado para descartar la sospecha, no para podar. |
| Multiples `test_scope_gate*` (4 archivos) y `test_pre_handoff*` (3 archivos) | Posible solape por nombre. | [I] no confirmado: cada uno cubre un eje distinto (deliverable-aware, isolation, topology, multirepo). Requiere lectura test-por-test antes de consolidar. |

### Unknown  -- unknown  [I]
- `test_detect_version.py::test_upgrade_path_suggestion`: aparece como #2-#3
  outlier (~60-70s) en `010j`/`010p` con cuerpo trivial; el coste no es
  atribuible a logica propia visible (`010j` lo dejo como observacion abierta).
  Clasificacion de **valor**: probablemente core (valida `suggest_upgrade_path`),
  pero su **coste** sigue sin explicar. Unknown en causa de lentitud, no en valor.

## VERIFICADO: tests / familias lentas (anclado a su SHA historico)

De las baselines durables (no medicion fresca del HEAD; ver reconciliacion):

| Test | 010j (479s total) | 010p C1/C2 (334/329s) | Tipo de coste |
|------|-------------------|------------------------|----------------|
| `test_scan_current_project` | 162.29s | 73.96 / 74.48s | Escaneo filesystem real (marker `slow`) |
| `test_upgrade_path_suggestion` | 59.22s | 69.79 / 67.91s | Coste no explicado (unknown) |
| `test_repo_has_no_live_retired_topology_terms` | 61.99s | (optimizado por 010k a ~0.2s) | rglob arbol (ya resuelto) |
| `test_script_runs_cleanly` | 27.34s | 25.80 / 27.12s | subprocess real |
| `test_no_inline_ticket_regex` | 26.34s | 23.61 / 23.51s | Escaneo texto/regex |
| `test_supervisor.py::test_relaunch_*` (x2) | ~40s | ~40s | subprocess real |

Conclusion durable (de `010p`): ~70% del tiempo se concentra en ~6 tests
(0.2% de la suite); coste dominante = **escaneo de filesystem real**, NO
`git/subprocess` difuso (hipotesis refutada por `010j`).

## Barreras canonicas del runner / handoff (recap para el Manager)

- **Runner Windows-safe:** `tests/conftest.py` + `tests/_temp_runtime.py` +
  `scripts/run_pytest_safe.py` (ver `tests/ARCHITECTURE.md`). `pytest.ini`:
  `-p no:cacheprovider`, `tmp_path_retention_policy=none`, `norecursedirs`
  excluye sandbox/deprecated/debug.
- **Handoff gates (structural):** scope gate, pre-handoff guard, deliverables
  exist, motor-scope, review-packet evidence, destino publish-ready.
- **Frontera xdist:** cerrada por `011e` (opt-in local) + `010m` (piloto CI) +
  `011i` (NOT-PURSUED). **Fuera de scope de 013e.**
- **Producto endurecido:** `013d` (escaneo ante borrados concurrentes).
  **Fuera de scope de 013e.**

## Debt detectable (sin tocar codigo)

1. **Ruido en `tests/sandbox/test_runtime/`:** dirs `opencode-review-*`
   acumulados de sesiones previas (permission-denied al enumerar). Es higiene de
   runtime, NO familia de tests; ya caracterizado por `010k`/`013d`. No es deuda
   de la suite en si.
2. **`tests/deprecated/` vivo en disco** pero excluido del runner. Limbo
   ordenado, no urgente.
3. **`test_upgrade_path_suggestion` lento sin causa explicada:** deuda de
   diagnostico, no de valor.

## Follow-ups propuestos (pequenos, acotados, verificables)

Cada uno con superficie de un archivo o un directorio; ninguno mezcla runner +
CI + producto + borrado masivo. Todos son OPCIONALES y requieren su propio
ticket.

| ID sugerido | Scope acotado | Criterio verificable de salida | Riesgo |
|-------------|----------------|--------------------------------|--------|
| FU-013E-1 | Leer `tests/unit/test_ejemplo.py` y `tests/test_goose_native_skill.py`; decidir mover a `tests/deprecated/` o conservar como smoke de fixtures. | Decision documentada + `validate 0/0` + suite verde tras el movimiento. | Bajo |
| FU-013E-2 | Confirmar si `tests/deprecated/test_goose_*.py` tienen valor historico; si no, borrar el directorio. | `git rm` solo de `tests/deprecated/`; collect-only sigue en 3111 (ya estaban excluidos); `validate 0/0`. | Bajo |
| FU-013E-3 | Diagnosticar la causa real del coste de `test_upgrade_path_suggestion` (~60-70s) con `--durations` aislado por test, sin tocar el test. | Reporte que explique el coste y proponga (o descarte) optimizacion local tipo `010k`. | Bajo (analysis) |
| FU-013E-4 | Auditar solape real de `test_scope_gate*` (4) y `test_pre_handoff*` (3) leyendo cada archivo; consolidar SOLO si hay duplicacion exacta de aserciones. | Mapa eje-por-eje; consolidacion con smoke que preserve cada eje, o cierre "sin solape". | Medio |

## No-goals respetados (declaracion explicita)

- **013e NO borra, NO `xfail`, NO `skip` ni relaja ningun test.** Es analysis.
- **013e NO toca** `tests/`, `scripts/run_pytest_safe.py`, `pytest.ini`,
  `pyproject.toml`, `uv.lock`, CI/workflows, `scripts/run_gates_dispatch.py`,
  `scripts/pre_handoff_guard.py` ni producto.
- **013e NO reabre** `011e`, `010m`, `011i` (frontera xdist) ni `013d`
  (producto). Donde aparecio sospecha de redundancia ligada a esas fronteras,
  se marco para descartar la sospecha, no para actuar.
- El unico diff productivo del motor para este ticket es **este reporte**.

## Existencia y verificacion del artefacto

- Generado contra HEAD `162e506`; verificado por lectura directa tras escritura.
- `check_encoding_guard.py` y `validate --json --project-root <repo_destino>`:
  ver `execution_log.md` de `WOT-2026-013e` en `repo_destino` para los exit
  codes literales.
