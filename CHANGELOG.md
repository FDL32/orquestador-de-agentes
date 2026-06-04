# 2026-06-04 - CEM v0: sustainable engineering philosophy

### Added
- `AGENTS.md`: CEM v0 (Contract, Evidence, Memory) added as the lightweight engineering philosophy for agent-assisted development.
- `.agent/rules/common/sustainable_engineering.md`: expanded reference for proportional rigor, failure taxonomy, robustness ladder, evidence rules, and relaunch continuity.
- `.agent/runtime/memory/observations.jsonl`: CEM-01..CEM-06 observations promoted so future agents inherit the lessons from the long encoding / suite-stabilization detour.

### Changed
- `README.md`: documents CEM v0 publicly and links it to the next field test, `WT-2026-221a` (verified root/topology plus evidence-linked Builder handoff capsule).

---

# 2026-06-02 - Bus reconstruction: WT-2026-210 / 211 / 212 / 216

Reconstrucción del contrato del bus en cuatro tickets encadenados, derivada de la auditoría
[BUS_ARCHITECTURE_WT-2026-210.md](docs/BUS_ARCHITECTURE_WT-2026-210.md) que documentó 7 invariantes
rotas tras el incidente WT-2026-205.

### Added (WT-2026-210 · commit `29b332e`)
- `scripts/reconcile_ticket.py`: cierre canónico de tickets con runtime huérfano. Emite
  `STATE_CHANGED → COMPLETED` + `SUPERVISOR_CLOSED` si faltan en el bus; limpia
  `builder_lock`, `supervisor_lock` y `requeue_claims`; actualiza `supervisor_state.json`,
  `manager_bridge_state.json` y `bridge_checkpoint.json`. Idempotente. Flags: `--ticket`,
  `--reason`, `--dry-run`, `--json`. No enganchado al preflight automático (pendiente WT-2026-214).
- `tests/test_reconcile_ticket.py`: tests focales del reconciler.
- `docs/BUS_ARCHITECTURE_WT-2026-210.md`: auditoría base con línea temporal verificada del
  incidente (bus seq 540–547), 7 invariantes rotas, tabla de write-paths, y propuesta de
  arquitectura con tres opciones (A: orquestador único, B: supervisor durable, C: proyecciones
  derivadas). Documento congelado — snapshot del estado *antes* de la reconstrucción.

### Changed (WT-2026-211 · commit `0125638`)
- `.agent/agent_controller.py`: `--mark-ready` ya no materializa proyecciones directamente;
  elimina escrituras de `TURN.md`/`execution_log.md` del comando (−122 líneas neto). Solo emite
  eventos al bus.
- `bus/supervisor.py`: añadido como materializador principal de proyecciones operativas
  (`TURN.md`, `STATE.md`, `execution_log.md`) tras transiciones (+133 líneas). El supervisor
  pasa a ser el único writer de proyecciones en el camino normal.
- `tests/test_wt_2026_211_write_path.py`: tests focales del write-path centralizado (nuevo).

**Architecture note — Write-path de proyecciones:**
El controller queda como *emisor de hechos al bus*; el supervisor como *materializador de
proyecciones*. Esto reduce el drift bus↔`TURN.md`/`STATE.md` y hace el orden de transición
determinista. Nota: `state_machine.py` sigue siendo derivador de lectura, no guard de escritura;
cualquier proceso puede emitir `STATE_CHANGED` sin validación. Cerrar esa brecha es WT pendiente.

### Changed (WT-2026-212 · commit `007875e`)
- `bus/review_bridge.py`: añadido `_ensure_durable_changes_consumer()` (línea 238). Garantiza
  que `REVIEW_DECISION=CHANGES` tenga consumidor aunque el supervisor reactivo haya muerto.
  Mecanismo: (1) solo actúa si el lock del supervisor está stale, (2) guard anti-doble-relaunch
  (revisa `BUILDER_RELAUNCH_ATTEMPTED` posterior al trigger antes de actuar), (3) dispara un
  tick real del supervisor: `bootstrap()` + `run_once()` + `_release_supervisor_lock()`.
  El bridge garantiza que exista el consumidor; el consumo real lo ejecuta el supervisor.
- `tests/test_wt_2026_212_durable_changes.py`: tests focales del consumidor durable (nuevo).

### Added (WT-2026-216 · commit `07991cd`)
- `scripts/get_launcher_state.py`: helper Python que derive el estado canónico del launcher
  desde el bus (`StateMachine.derive_state_from_events()`). Devuelve JSON estable
  `{ticket_id, state, role, action, source}`. Requiere `--project-root`.
- `scripts/launch_agent_terminals.ps1`: `Get-ActiveRole` intenta primero `get_launcher_state.py`;
  `TURN.md` queda como fallback explícito. `TURN.md` stale ya no impide el relanzamiento correcto.
- `tests/test_wt_2026_216_launcher_bus_read.py`: tests focales del camino bus vs. fallback TURN stale.

**Architecture note — Autoridad de lectura del launcher:**
La decisión de qué agente lanzar pasa de *proyección documental* (`TURN.md`) a *estado derivado
del bus*. Patrón recomendado hacia adelante: toda decisión semántica nueva → helper Python
testeable; PowerShell queda como borde de integración con Windows.

---

# 2026-06-02 - WT-2026-205 prepush_check regression cleanup

### Fixed
- `scripts/prepush_check.py`: `ruff format --check` deja de recibir `--extend-exclude`, flag no aceptado por ese subcomando. Las exclusiones operativas se mantienen solo en `ruff check` hasta que `WT-2026-210` defina el contrato completo de gates Modelo B.

---

# 2026-06-01 - WT-2026-201 Hardening runtime del launcher tras WT-2026-200

### Added
- `tests/test_supervisor.py::test_relaunch_uses_resume_flag`: endurecido con `trigger_seq=42`
  no nulo y afirmación explícita de los cuatro flags del launcher (`-LaunchBuilder`,
  `-OnlyBuilder`, `-ResumeBuilder`, `-SkipSupervisorWait`).

### Changed
- `tests/test_launch_agent_terminals_script.py::test_launcher_resume_builder_waits_for_supervisor_exit`:
  assert textual `"$LaunchSupervisor = -not $OnlyBuilder" in content` sustituido por
  comprobación semántica vía `re.search(r'\$LaunchSupervisor\s*=\s*-not\s*\$OnlyBuilder', content)`
  resistente a variaciones de espaciado.

### Architecture note — Invariante de precedencia de flags en el launcher
El invariante `-OnlyBuilder > -ResumeBuilder` es una regla dura del launcher:
cuando `-OnlyBuilder` está activo, el supervisor NO se arranca incluso en modo
resume. La asignación `$LaunchSupervisor = -not $OnlyBuilder` (línea 1154 de
`launch_agent_terminals.ps1`) es el punto único donde esta precedencia se
materializa. Cualquier refactorización futura debe preservar esta condición:
`-OnlyBuilder` desactiva `$LaunchSupervisor` independientemente de `-ResumeBuilder`.

---
# 2026-05-30 - WP-2026-177 Fixes: supervisor launcher path + OpenCode workspace permissions

### Fixed
- `bus/supervisor.py`: `_resolve_launcher_path()` — nuevo método que lee `motor_destination_link.json`
  para resolver la ruta del launcher desde el motor en vez del workspace (Model B). Sustituye el bloque
  inline de 13 líneas que causaba C901 y que no se ejecutaba en el supervisor antiguo.
- `scripts/launch_agent_terminals.ps1`: `Set-OpenCodeExternalPermission()` — inyecta en tiempo de
  arranque el permiso `external_directory` para el workspace en `.opencode/opencode.json`, sin rutas
  hardcodeadas en el repositorio. La ruta correcta se lee de `motor_destination_link.json` (campo
  `destination_root`) vía el parámetro `$ProjectRoot`. Si el motor no tiene workspace externo (modo
  standalone), la función no hace nada.

### Architecture note — Model B + OpenCode permissions
El motor (`orquestador_de_agentes/`) es portable: ninguna ruta del destino puede estar commiteada.
`motor_destination_link.json` es el único contrato de vinculación motor↔workspace. El launcher lo
lee para: (1) resolver la ruta del launcher (supervisor requeue), (2) inyectar el permiso
`external_directory` de OpenCode antes de abrir la ventana del builder. Al instalar el motor en un
proyecto nuevo, el instalador actualiza `motor_destination_link.json`; el resto se adapta automáticamente.

---

# 2026-05-29 - WP-2026-175 Canonical session closeout and cycle rollover

### Closed
- Session closed canonically via `--session-close` pipeline.
- Observations generated for WP-2026-175.
- Memory consolidated.
- Collaboration artifacts archived (PLAN/AUDIT WP-2026-174 moved to `_archive/plan_audit/`).
- Event bus terminal tickets archived.
- STATE.md transitioned to COMPLETED.
- PROJECT.md and CHANGELOG.md updated to reflect session close.
- Repository left ready for the next cycle without drift.

---

# 2026-05-29 - WP-2026-169 Session close loop bridge -- `--session-close` en agent_controller

### Added
- `.agent/agent_controller.py`: new `--session-close` flag that delegates to `scripts/session_closeout.py` and syncs post-close state projections.
- `.agent/agent_controller.py`: `_handle_session_close()` handler with idempotency guard (skips if STATE.md already COMPLETED without --force).
- `.agent/agent_controller.py`: `_sync_state_after_session_close()` helper for post-close projection sync.
- `tests/test_agent_controller.py`: TestSessionClose class covering dry-run delegation, idempotency, force override, ticket passing, and script-not-found error.
- `QUICKSTART.md`: section 6 now includes `--session-close` as canonical session close command; section 8 restructured with canonical route first.
- `README.md`: Common commands include `--session-close`; Typical flow step 6 references it.
- `PROJECT.md`: current cycle updated to reflect WP-2026-169 completion.

### Closed
- `WP-2026-169`: implemented and closed canonically as the session close loop bridge.

---

# 2026-05-29 - Builder model migration: Qwen3.5 Plus → DeepSeek V4 Flash

### Changed
- `.opencode/opencode.json`: Builder model changed from `opencode-go/qwen3.5-plus` to `opencode-go/deepseek-v4-flash`.
- `.agent/config/agents.json`: `role_models.BUILDER` updated to `opencode-go/deepseek-v4-flash`.
- `.agent/agents_config.py`: migration default updated to `opencode-go/deepseek-v4-flash`.
- `.opencode/MODELS.md`: catalog updated to reflect DeepSeek V4 Flash as current Builder default.
- `README.md`: Builder backend reference updated.
- `prompts/session_bootstrap.md`: Builder model reference updated.
- `bus/review_bridge.py`: docstring example updated.
- `tests/unit/test_agents_config.py`: all hardcoded model references updated.
- `tests/unit/test_launcher_opencode_invocation.py`: hardcoded model assertion updated.

### Rationale
- Qwen3.5 Plus server errors (`err_a8807a88`, HTTP 500) prompted initial migration to MiMo-V2.5.
- MiMo-V2.5 was an intermediate step; DeepSeek V4 Flash has stronger coding benchmarks and the highest rate limit in the paid catalog (31,650 req/5h).

---
# 2026-05-29 - WP-2026-166 Canonical closeout: manager watchdog for stale READY_FOR_REVIEW

### Added
- `scripts/manager_review_bridge.py`: heartbeat `heartbeat_at` refreshed in watch mode so the supervisor can distinguish a live bridge from a stale one.
- `bus/supervisor.py`: watchdog for stale `READY_FOR_REVIEW` relaunch with `MANAGER_STALE_TIMEOUT = 600`, watermark deduplication, and detached relaunch on Windows and POSIX.
- `tests/test_supervisor.py`: cross-platform detach coverage, stale/fresh/no-op guards, and direct staleness edge cases.

### Closed
- `WP-2026-166`: implemented and closed canonically as the Manager watchdog for stale `READY_FOR_REVIEW` relaunch.

---
# 2026-05-28 - WP-2026-162 Canonical closeout: ticket prose validator automation

### Added
- `scripts/validate_ticket_prose.py`: standalone validator for ticket prose quality with 11
  deterministic detections plus `audit-missing-tp-check`.
- `tests/test_validate_ticket_prose.py`: direct coverage for clean/defect fixtures and the
  structural audit check.
- `tests/test_agent_controller.py`: integration coverage for `warnings.ticket_prose` in
  `--validate`.

### Changed
- `.agent/agent_controller.py`: `_handle_validate()` now exposes ticket prose warnings in the
  canonical JSON output without changing the exit code for warnings only.
- `skills/man-create-work-plan/SKILL.md`: added the mandatory `TP Check` gate for the Manager.
- `skills/man-create-work-plan/references/plan-quality-checklist.md`: added mechanical quality
  checks for ticket plans and explicit prompt-safe examples.
- `skills/_shared/ticket-anti-patterns.md`: added the ticket anti-pattern catalog used by the
  new plan-quality flow.

### Closed
- `WP-2026-162`: implemented the ticket quality loop automation and closed it canonically.

---
# 2026-05-27 - v9.14.1 Session close: hardening, CHANGELOG completeness, audit cleanup

### Changed
- `skills/bui-self-audit/SKILL.md`: Added Paso 4b with three contract rules (reject speculative
  risks, rerun tests+review after any fix, stop on 0 actionable findings). Removed duplicate
  `run_pytest_safe.py` line in Paso 6.

### Added
- `.claude/security-patterns.json`: Per-edit pattern rules for `privada/` access, hardcoded
  credential prefixes (`sk_live_`, `AKIA`, `xoxb-`…), and `pickle.load`. Preparation for
  security-guidance plugin when stable CLI (≥2.1.144) is available.
- `.claude/claude-security-guidance.md`: Project-specific guidance for model-backed security
  reviews.

---
# 2026-05-27 - WP-2026-152 Fix --request-changes requeue deadlock + bridge stderr logging

### Fixed
- `agent_controller.py _handle_request_changes`: Added `pending_requeue` signal derived from
  `events[-1]` to allow `--request-changes` when bus state is IN_PROGRESS due to a direct
  `REVIEW_DECISION=changes` antecedent. Previously the guard rejected IN_PROGRESS
  unconditionally, creating a deadlock: `_state_from_review_decision("changes")` → IN_PROGRESS
  left no valid path for the bridge to re-queue.
- `bus/review_bridge.py`: `subprocess.run(--request-changes)` now checks returncode and logs
  non-zero exit to stderr. Previously captured output was silently discarded, hiding the deadlock.

### Added
- `tests/unit/test_request_changes_requeue.py`: 5 tests covering the `pending_requeue` signal,
  generic IN_PROGRESS rejection, and UNKNOWN-state fallbacks.
- `tests/unit/test_review_bridge_request_changes_logging.py`: 2 tests verifying stderr logging
  and semantic neutrality of the logging change.

---
# 2026-05-27 - WP-2026-151 Retire legacy project_map path

### Fixed
- `agent_controller.py`: Removed runtime reference to `project_map.md` (legacy path). Stale
  comment referencing removed `generate_project_map()` updated to reflect current project
  scanner usage.
- `tests/unit/test_controller_project_map_cleanup.py`: Replaced narrow string-match test with
  generic non-comment-line grep so any future reintroduction of `project_map.md` in code is
  caught automatically.

---
# 2026-05-27 - WP-2026-153 Add grill-with-docs skill

### Added
- `skills/grill-work-plan/SKILL.md`: Pre-plan interrogation skill with triggers `/grill-plan`, `/grill`, `grill-wp`.
  - One-question-at-a-time flow with recommended answer before user response
  - Default context: `PROJECT.md` and `MEMORY.md`; `CONTEXT.md` optional at repo root
  - Codebase-first answers (grep/search before speculation)
  - ADR criteria from mattpocock (hard to revert, surprising without context, real trade-off)
  - Exact completion handshake: `> ✅ Grill completo. Términos resueltos: N. Puedes crear el WP con /plan.`
- `skills/README.md`: Registered new skill in catalog table and index.

### Changed
- `README.md`: Updated skills count (19 → 20), current state, and changelog table.
- `PROJECT.md`: Updated state to WP-2026-153 COMPLETED.

### Summary
- Pre-plan grilling reduces fuzzy scopes and avoidable review loops.
- Skill is documentation-only (no Python runtime, no dependencies).
- Optional integration with `man-create-work-plan` (opt-in, not blocking).

---
# 2026-05-26 - WP-2026-144 Destination ticket prefix onboarding + timeout hotfix

### Added
- `scripts/install_agent_system.py`: `--install --prefix XXX` and `--sync --prefix XXX` write
  `Ticket prefix: XXX` into destination `PROJECT.md` and `ticket_prefix` into `motor_destination_link.json`.
- `agent_controller.py --validate`: warns when `active_profile == host-project` and `PROJECT.md`
  lacks `Ticket prefix:` (new `host_project_prefix` warning category).
- `tests/unit/test_install_agent_system.py`: 4 new cases for `--prefix` plumbing.
- `tests/unit/test_validate_host_prefix.py`: 5 cases covering prefix-present, prefix-missing,
  engine-dev skip, and forced validation.

### Fixed (hotfix)
- `bus/review_bridge.py`: timeout-exhausted retries no longer emit `REVIEW_DECISION: inspect`
  to the bus (which mapped to HUMAN_GATE). Instead the cycle is reclassified as
  `REVIEW_TRANSPORT_FAILED` with `failure_reason: timeout`. Semantic `inspect` is now reserved
  exclusively for explicit Manager requests. Test `test_retry_exhausted_falls_to_inspect`
  renamed and updated to assert `TRANSPORT_FAILED`.

### Updated
- `prompts/session_bootstrap.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md`, `RELEASE_CHECKLIST.md`,
  `CLOSURE_MODEL.md`: destination namespace convention `XXX-YYYY-NNN` with `Ticket prefix: XXX`.

### Summary
- Destination projects are now self-describing for ticket IDs via `--prefix`.
- Validation enforces the prefix declaration on host-project workspaces.
- Timeout failures no longer pollute the bus with spurious `inspect` events.

---
# 2026-05-26 - WP-2026-143 Idempotent --mark-ready via bus-state guard

### Fixed
- `agent_controller.py _handle_mark_ready`: added bus-state guard before the markdown guard.
  Reads `StateMachine.derive_state_from_events()`; returns 0 (no-op) when bus state is already
  READY_FOR_REVIEW, READY_TO_CLOSE or COMPLETED. HUMAN_GATE check also reads bus first.
  Prevents double-emission of STATE_CHANGED→READY_FOR_REVIEW when Builder calls `--mark-ready`
  a second time after the bus has advanced.
- `tests/unit/test_mark_ready_idempotency.py`: 8 tests covering all guard paths.

---
# 2026-05-26 - WP-2026-142 Symmetric scope gate in --mark-ready

### Added
- `agent_controller.py check_scope_gate`: symmetric check — blocks when the intersection of
  changed files and whitelist is empty (`covered_files = ∅`); warns when partial.
  `_scope_gate_allows_close` updated to handle `blocked_reason` and `missing_from_diff`.
- `tests/unit/test_scope_gate.py`: 16 tests covering parse, get_changed_files, gate cases, and
  end-to-end mark-ready blocking.

---
# 2026-05-26 - WP-2026-141 Google eng-practices review standards alignment

### Added
- `skills/man-review-implementation/references/review-checklist.md`: sección `## Aprobacion y Nit`
  con criterio positivo de aprobacion (aprobar cuando mejora la salud del codigo, aunque no sea perfecto),
  convencion `Nit` para comentarios no bloqueantes, y principio de CLs pequeños. URLs directas a
  `standard.html`, `comments.html` y `small-cls.html` de `google.github.io/eng-practices`.
- `AGENTS.md`: punto 4 en "Criterio de cierre" referenciando el principio de aprobacion Google.
- `CREDITS.md`: fila de atribucion para `google/eng-practices` (CC-BY 3.0, adapted).

### Summary
- Adaptacion quirurgica: sin nueva skill ni nueva superficie. Las 3 inserciones son aditivas
  sobre superficies existentes. Trazabilidad completa desde contrato (AGENTS.md) hasta
  ejecucion (review-checklist.md) y atribucion (CREDITS.md).

---
# 2026-05-26 - WP-2026-140 Bus import boundary test + ruff test suite cleanup

### Added
- `tests/test_bus_boundary.py`: firewall AST-based que verifica que `bus/` no importa
  `scripts.*` salvo el seam permitido (`scripts.discover_skills`). Segunda prueba
  grep-based detecta imports dinamicos (`importlib.import_module`, `__import__`).

### Changed
- `pyproject.toml`: `extend-exclude` corregido de `"tests/"` a `"tests/sandbox/"` para
  que ruff cubra los tests reales. `per-file-ignores` ampliado con politica explicita
  para patrones legitimos en tests: `S603`, `S607`, `S108`, `SIM115`, `PERF203`.

### Fixed
- 118 violaciones ruff en 70 archivos de tests: SIM117 (nested-with -> parenthesized),
  PERF401 (for-append -> list comprehension), RUF001/002 (mojibake en docstrings),
  RUF059 (tuplas desempaquetadas sin uso -> `_`), N805/N806 (naming), F841
  (asignaciones sin uso), SIM105 (try/except/pass -> contextlib.suppress), B007,
  E402, ERA001.

### Summary
- 255 tests verdes, ruff limpio. Seam `bus/ -> scripts/` protegido por firewall
  estatico + dinamico. `per-file-ignores` como politica (no noqa por linea) para
  patrones sistematicamente legitimos en el suite de tests.

---
# 2026-05-25 - WP-2026-136 Semantic --candidates input for session_close_observations

### Added
- `scripts/session_close_observations.py`: flag `--candidates <json_file>` para
  inyectar candidatos semanticos externos sin tocar el pipeline de validacion.
  `load_candidates_from_file()` con manejo estricto: FileNotFoundError,
  ValueError (UTF-8 invalido), ValueError (JSON roto), ValueError (non-list).
  Elementos no-dict se saltan con warning.
- `tests/unit/test_session_close_observations.py`: 25 tests (era 16). Nuevos:
  exclusion mutua, JSON valido, archivo ausente, JSON corrupto, top-level invalido,
  elementos no-dict, dispatch correcto, UTF-8 invalido, lista vacia exit 0.

### Changed
- `--ticket` y `--candidates` en `add_mutually_exclusive_group(required=True)`.
- `load_existing_observations()` endurecida con `errors="replace"`.
- `skills/session-close-observations/SKILL.md`: modo --candidates, exclusion mutua,
  workflow con fuente externa documentados.

### Fixed
- `load_candidates_from_file` usaba `errors="replace"` silenciando UTF-8 invalido;
  corregido a `read_bytes().decode("utf-8")` para lanzar ValueError como contratado.
- Lista vacia de candidatos tratada como error (exit 1); corregido a exit 0.

### Summary
- Canal de inyeccion semantica listo para bucle de autoaprendizaje del Manager.
  Fundamento de: audit_findings -> session_close --candidates -> observations.jsonl
  -> review_bridge inyecta contexto dinamico en el prompt del Manager (WP-B).
- 25 tests verdes, ruff limpio, stdlib only.

---
# 2026-05-25 - WP-2026-135 Selective context recovery lite for pre-compact hook

### Added
- `.agent/hooks/pre_compact_hook.py`: hook funcional que carga `observations.jsonl`,
  extrae keywords de `work_plan.md`, rankea por recencia + keyword matching (cap 5) y
  proyecta `additionalContext` con sección `Memoria relevante` antes de compactar.
- `tests/unit/test_pre_compact_hook.py`: 25 tests (TestLoadObservationsSafe,
  TestExtractKeywordsFromWorkPlan, TestScoreObservation, TestRankObservations,
  TestFormatMemorySection, TestMainHook, TestRobustness).

### Changed
- `bus/review_bridge.py`: rubric de `code` y `mixed` ampliad con checklist de
  anti-patrones como BLOCKERs: mock drift, floor assertion, zero-logic wrapper.
- `AGENTS.md`: documentados los tres anti-patrones bajo secciones de testing (§2)
  e implementación (§3) para guiar a Builder y Manager en cada revisión.

### Fixed
- `pre_compact_hook.py` loader: `open(..., errors="replace")` para sobrevivir bytes
  UTF-8 inválidos sin lanzar `UnicodeDecodeError`.
- `score_observation` y `format_memory_section`: normalización `str(x or "")`
  para evitar `AttributeError`/`TypeError` con campos `null`, numéricos o booleanos.

### Summary
- Hook ligero: sin embeddings, sin LLM, sin dependencias externas (stdlib only).
- Rutas derivadas de `Path(__file__).resolve().parent.parent` (no `cwd()`).
- Contrato del hook preservado: `continue=true`, JSON válido siempre.
- 242 + 25 = 267 tests verdes (los 25 del hook no están en el runner pytest-safe
  porque el archivo vive en `.agent/`; se ejecutan con pytest directo).

---
# 2026-05-20 - WP-2026-113 Central motor release consolidation

### Changed
- `PROJECT.md`: Ciclo activo actualizado a WP-2026-113 IN_PROGRESS (consolidacion de release).
- `.agent/collaboration/TURN.md`: Turno actualizado a WP-2026-113, rol BUILDER.
- `.agent/collaboration/STATE.md`: Estado canonico alineado con WP-2026-113.
- `.agent/collaboration/execution_log.md`: Registro de ejecucion inicializado para WP-2026-113.
- `.agent/collaboration/review_queue.md`: Limpieza de reviews historicos de WP-2026-107, WP-2026-111, WP-2026-112.
- `.agent/collaboration/notifications.md`: Handoff vivo para WP-2026-113, residuos historicos mantenidos como referencia.
- `.agent/runtime/events/events.jsonl`: Bus canónico con eventos de WP-2026-113, tickets cerrados permanecen como historial.

### Summary
- Consolidacion post-WP-2026-111 y WP-2026-112: motor central descrito una unica vez.
- Manifiestos (`MANIFEST.distribute`, `MANIFEST.workspace`) expresan la misma arquitectura sin ambiguedad.
- Instalador (`scripts/install_agent_system.py`) actua como bootstrapper sin copiar motor.
- Documentacion canonica (`README.md`, `AGENTS.md`, `PROJECT.md`) cuenta la misma historia.
- Superficies vivas normalizadas: sin mezcla de tickets cerrados con ciclo activo.
- Validacion canonica y tests verdes: 0 errores, 227 tests passing.

---
# 2026-05-20 - WP-2026-111 Central motor and destination workspace contract

### Changed
- `MANIFEST.distribute`: Reescrito como contrato del motor central. El motor NO se copia; este manifiesto delimita la frontera del codigo operativo del repo fuente.
- `MANIFEST.workspace`: Nota operativa actualizada para reflejar arquitectura de motor central. El destino conserva solo estado/memoria/eventos/config; el motor se referencia, no se copia.
- `scripts/install_agent_system.py`: Documentacion actualizada. El instalador prepara (bootstrap) el destino para consumir el motor externo; NO copia el codigo operativo.
- `AGENTS.md`: Seccion "MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)" reescrita. Contrato de version actualizado a "motor central + workspace destino".
- `PROJECT.md`: Estado actualizado a WP-2026-111 COMPLETED. Mision cambiada de "plantilla portable" a "motor central". Seccion de arquitectura reescrita.
- `README.md`: Titulo y descripcion actualizados a "Central motor". Seccion "Central motor architecture (WP-2026-111)" reemplaza "Engine portability". Instrucciones de instalacion actualizadas.
- `CLAUDE.md`: Version de referencia actualizada a v9.14.0.

### Summary
- Cambio arquitectonico completo: de "plantilla portable copiada" a "motor central + workspace destino".
- El motor (codigo operativo) vive una unica vez en `orquestacion_agentes/`.
- Cada proyecto destino conserva solo su `.agent/` de workspace (estado, memoria, eventos, config) y referencia el motor externo.
- El instalador actua como bootstrapper del destino: prepara la estructura de workspace sin copiar el motor.
- Documentacion canonica actualizada para reflejar la nueva arquitectura de forma coherente.
- Cero cambios de comportamiento en el instalador: ya usaba MANIFEST.distribute como allowlist; ahora la narrativa es correcta.

---
# 2026-05-20 - WP-2026-106 Structured manager reviews and human gate escalation

### Added
- `bus/review_bridge.py._validate_changes_structure()`: Validates CHANGES responses have SUMMARY, BLOCKERS, SUGGESTIONS, DECISION: CHANGES sections.
- `bus/review_bridge.py._parse_changes_structure()`: Extracts structured sections from CHANGES stdout.
- `bus/review_bridge.py._persist_review_attempt()`: Persists each review attempt to `.agent/runtime/reviews/<TICKET_ID>/attempt-N.md` idempotently.
- `bus/review_bridge.py._generate_human_review_report()`: Generates `human_review_report.md` from template at 5th consecutive CHANGES.
- `bus/review_bridge.py._emit_review_attempt()`: Emits MANAGER_REVIEW_ATTEMPT with `review_log_path` and `stdout_tail` (lightweight bus).
- `tests/test_manager_review_bridge.py`: TestStructuredChangesValidation (5 tests), TestReviewAttemptPersistence (4 tests), TestHumanGateEscalation (5 tests).
- `tests/unit/test_review_budget_retry.py`: Tests for persistence, validation, and HUMAN_GATE escalation.

### Changed
- `bus/review_bridge.py._load_review_config()`: max_attempts elevated from 2 to 5 (WP-2026-106 threshold).
- `bus/review_bridge.py.run_manager_review_cycle()`: Rewritten to support structured CHANGES validation, per-attempt persistence, and HUMAN_GATE escalation at 5 consecutive CHANGES.
- `.agent/config/agents.json`: `manager_review.max_attempts` updated to 5.

### Summary
- CHANGES decisions now require structured sections (SUMMARY, BLOCKERS, SUGGESTIONS).
- Each review attempt persisted idempotently to `attempt-N.md` for full auditability.
- Bus remains lightweight with only `review_log_path` and `stdout_tail` in events.
- 5 consecutive CHANGES decisions trigger HUMAN_GATE escalation with auto-generated `human_review_report.md`.
- All quality gates pass: ruff clean, 176 tests passing, pip-audit clean.

---
# 2026-05-20 - WP-2026-105 Bus precedence bootstrap hardening

### Added
- `bus/supervisor.py._bus_active_non_terminal_ticket()`: New method that scans all tickets in the event bus and returns the first one in a non-terminal state (READY_FOR_REVIEW, READY_TO_CLOSE, IN_PROGRESS, BLOCKED, HUMAN_GATE).
- `tests/test_supervisor.py`: 6 new tests covering:
  - `test_bus_active_non_terminal_ticket_finds_active_ticket`: Finds tickets in non-terminal states.
  - `test_bus_active_non_terminal_ticket_ignores_completed`: Skips completed tickets.
  - `test_bus_active_non_terminal_ticket_prefers_first_active`: Returns first active ticket.
  - `test_bootstrap_bus_precedence_over_turn_divergence`: Core regression test (bus wins over TURN.md).
  - `test_bootstrap_bus_requeue_repeated_changes`: Verifies repeated requeue works.
  - `test_bootstrap_fallback_to_turn_when_bus_has_no_active`: Fallback to TURN.md when bus has no active.

### Changed
- `bus/supervisor.py.bootstrap()`: Modified to prioritize bus active non-terminal ticket over TURN.md and work_plan.md. Precedence chain: bus (non-terminal) -> TURN.md -> work_plan.md -> state.
- `bus/supervisor.py.bootstrap()` docstring: Updated to reflect bus-first precedence.

### Summary
- Resolves divergence scenario where TURN.md points to old ticket but bus has active non-terminal ticket.
- Bus is now the authoritative source for active ticket during bootstrap.
- TURN.md and work_plan.md remain as fallbacks when bus has no active non-terminal ticket.
- Repeated requeue cycle (REVIEW_DECISION -> changes -> IN_PROGRESS) preserved.
- Zero regressions: 157 tests passing, ruff clean.

---
# 2026-05-19 - WP-2026-101 P0 cleanup: duplicate scripts and orphaned artifacts

### Removed
- `scripts/rollback_agent_system.py`: Exact duplicate of canonical `scripts/rollback.py`
- `.agent/runtime/status_bar_indicator.py`: Exact duplicate of canonical `runtime/status_bar_indicator.py`

### Moved
- `check_wp034.py` → `tests/debug/check_wp034.py`: Debug script for WP-2026-034 event analysis
- `debug_bus_state.py` → `tests/debug/debug_bus_state.py`: Debug script for event bus state inspection
- `scripts/test_refactoring_impact.py` → `tests/test_refactoring_impact.py`: Refactoring impact test suite
- `scripts/test_refactor_kit_performance.py` → `tests/test_refactor_kit_performance.py`: Performance optimization tests
- `scripts/test_refactor_kit_portable.py` → `tests/test_refactor_kit_portable.py`: Portability validation tests
- `scripts/test_goose_native_skill.py` → `tests/test_goose_native_skill.py`: Goose integration tests
- `scripts/sandbox/smoke_test_requeue_flow.py` → `tests/sandbox/smoke_test_requeue_flow.py`: E2E smoke tests for requeue flow

### Changed
- `scripts/upgrade_agent_system.py`: Rollback command now references `scripts/rollback.py` (canonical)
- `scripts/cleanup_legacy.py`: Removed `rollback_agent_system.py` and `upgrade_agent_system.py` from legacy list
- `UPGRADE_CLEANUP_GUIDE.md`: Removed `rollback_agent_system.py` from SAFE_REMOVE list
- `VERIFY_VERSION.sh`: Removed `rollback_agent_system.py` from CRITICAL_FILES list
- `UPGRADE_GUIDE.md`: Removed `rollback_agent_system.py` from legacy aliases
- `DISTRIBUTION_GUIDE.md`: Removed `rollback_agent_system.py` from legacy aliases

### Summary
- Duplicate consolidation: 2 exact duplicates removed, canonical sources preserved
- Orphaned artifacts: 7 debug/test scripts moved out of operational bundle surface
- Zero behavior changes: all quality gates pass (ruff, pytest-safe, agent_controller --validate)
- Tests relocated: 138 unit tests pass, smoke tests pass (3/3)
- Bundle surface reduced: root directory now clean of orphaned Python scripts

---
# 2026-05-19 - WP-2026-100 Portable bundle active-only collaboration archive

### Added
- `scripts/archive_collaboration_artifacts.py`: Stdlib-only helper that moves closed `PLAN_WP-*.md` and `AUDIT_WP-*.md` files from `.agent/collaboration/` to `.agent/collaboration/_archive/plan_audit/`.
  - Reads active WP ID from `work_plan.md` (regex supports both `- **ID:**` and `**ID:**` formats)
  - Idempotent: re-running archives zero files after first pass
  - Dry-run mode (`--dry-run`) reports without modifying disk
  - List active mode (`--list-active`) shows remaining collaboration files
  - Archive directory created on-demand (`parents=True, exist_ok=True`)
- `tests/unit/test_archive_collaboration_artifacts.py`: 9 unit tests covering:
  - `test_parse_wp_number`: WP number extraction from filenames
  - `test_get_active_wp`: Reading active WP from work_plan.md
  - `test_find_closed_plan_audit_files`: Finding closed PLAN/AUDIT files
  - `test_archive_closed_files`: Archiving closed files to archive dir
  - `test_idempotent_second_run_archives_zero`: Second run archives nothing
  - `test_dry_run_does_not_modify_disk`: Dry-run reports without moving
  - `test_no_closed_files_no_op`: No files touched when all active
  - `test_list_active_collaboration_files`: Listing active collaboration files
  - `test_archive_dir_creation`: Archive directory created when needed
- `.agent/collaboration/_archive/plan_audit/`: Internal archive directory for closed PLAN/AUDIT artifacts (77 files archived on first run)

### Changed
- `scripts/archive_collaboration_artifacts.py.get_active_wp()`: Fixed regex to support both `- **ID:** WP-YYYY-NNN` and `**ID:** WP-YYYY-NNN` formats (discovered during implementation)

### Summary
- Keeps portable bundle copyable without dragging old ticket forensics
- Active collaboration surface reduced to ~10 files (work_plan.md, TURN.md, STATE.md, execution_log.md, current PLAN/AUDIT pair)
- 77 closed PLAN/AUDIT files archived to `.agent/collaboration/_archive/plan_audit/`
- Idempotent operation verified: second run archives zero files
- Zero dependencies added (stdlib only: pathlib, shutil, re, argparse)

---
# 2026-05-19 - WP-2026-098 Bridge prompt transport via --file for Windows argv limit

### Added
- `bus/review_bridge.py.ARGV_PROMPT_THRESHOLD = 8000`: Module-level constant for Windows CreateProcess argv limit (~8191 chars) with safety margin.
- Dual transport dispatch in `bus/review_bridge.py._run_opencode_review()`:
  - Short prompts (<8000 chars): passed directly in argv (unchanged behavior)
  - Long prompts (>=8000 chars): written to `tempfile.NamedTemporaryFile(delete=False)` + `--file <path>` flag
- Tempfile cleanup in `finally` block with `os.unlink()` best-effort (catches `OSError` for Windows file-lock transient failures)
- `tests/test_manager_review_bridge.py.TestPromptTransportDispatch`: 4 new tests:
  - `test_short_prompt_uses_argv_path`: verifies argv transport for short prompts
  - `test_long_prompt_uses_file_path`: verifies --file transport for long prompts
  - `test_tempfile_cleaned_up_after_call`: verifies cleanup after successful call
  - `test_tempfile_cleaned_up_on_subprocess_failure`: verifies cleanup on TimeoutExpired

### Changed
- `bus/review_bridge.py._run_opencode_review()`: Refactored with try/finally for tempfile lifecycle management. Removed cmd_string length check (no longer needed with --file path).

### Summary
- Resolves the Windows command-line length bottleneck captured by WP-095 forensic events in WP-097 closeout (stderr: "La línea de comandos es demasiado larga (19268 chars)").
- Self-dogfood: this WP has small diff -> prompt <8000 -> exercises argv path. Tests artificially exercise the --file path.
- Zero dependencies added (stdlib `tempfile` only).
- Backward compatible: short prompts use identical argv path as before.

---
# 2026-05-19 - WP-2026-097 Defense against history truncation + archive integration + bridge V2 smoke

### Added
- `scripts/check_no_history_truncation.py`: Stdlib-only guard script that detects dangerous truncation of `execution_log.md`.
  - Threshold: >50 lines removed without archive compensation
  - Checks for compensating archive files in `.agent/runtime/events/archive/`
  - Provides actionable error message with archive command instructions
  - Exit code 1 on dangerous truncation, 0 otherwise
- `tests/unit/test_no_history_truncation.py`: 15 unit tests covering:
  - Truncation without archive compensation (fail case)
  - Truncation with archive compensation (pass case)
  - Changes below 50-line threshold (pass case)
  - Add-only changes (pass case)
  - Boundary cases (exactly 50 vs 51 lines)
  - Archive file detection (added/renamed)
  - Main function integration tests
- `.pre-commit-config.yaml`: Local hook `check-history-truncation` registered for commit stage.
- `skills/project-finalize/SKILL.md`: Step 9e added suggesting `archive_execution_log.py` when log exceeds ~10 WP entries.

### Changed
- None (stdlib-only implementation, no existing code modified).

### Summary
- Protects `execution_log.md` from accidental/silent truncation without archival.
- Conservative threshold (50 lines) avoids false positives on normal edits.
- Archive integration is manual/suggested only (no auto-invocation).
- Bridge V2 smoke: this ticket's own review validates the manager review cycle.
- Zero dependencies added, fully backward compatible.

---
# 2026-05-19 - WP-2026-096 Caveman-style canonical doc compression helper

### Added
- `scripts/compress_canonical.py`: Stdlib-only helper inspired by JuliusBrussee/caveman (MIT) for compressing canonical markdown files.
  - `--dry-run`: Preview changes without modifying files
  - `--backup`: Create `.original.md` backup before overwriting
  - `--restore`: Restore files from `.original.md` backups
  - Preservation of code fences, inline code, URLs, paths, headers, tables, frontmatter
  - Idempotent: `compress(compress(x)) == compress(x)`
- `tests/unit/test_compress_canonical.py`: 25+ tests covering preservation, compression, idempotency, backup/restore, dry-run, and edge cases.

### Changed
- `CREDITS.md`: Added MIT attribution row for JuliusBrussee/caveman (Inspiration, no code copied).

### Summary
- Implements V1 of caveman-style compression for canonical docs using Python stdlib only.
- Zero dependencies added.
- Conservative compression: only removes clearly redundant filler phrases and excessive whitespace.
- Full technical content preservation via placeholder-based marking/restoration.

---
# 2026-05-19 - WP-2026-095 Manager review V2 (deterministic single-shot, context budget & retries)

### Added
- Pluggable Manager Rubrics: `_rubric_for_type()` outputs custom evaluation prompts based on `deliverable_type` (`code`, `mixed`, or non-code/documentation/research).
- Context Prompt Builder: `_build_review_prompt()` formats the single-shot prompt including core canonical files (`work_plan.md`, `STATE.md`, `TURN.md`), the relevant `execution_log.md` section, optional plan/audit files, and git diff.
- Semantic Truncation & Budget: Enforces a strict 80KB cap. Drops/minimizes less critical context first, falls back to `git diff --stat` if canonical files exceed 60KB.
- Configurable Retry Loop: `"manager_review"` settings in `.agent/config/agents.json` define timeout limits (default 180s), maximum retries (default 2), and backoff multipliers (default 2.0).
- Exponential Technical Backoff: Retries reviews only on technical timeouts (`TimeoutExpired`), applying exponential backoff. Immediately stops and yields `INSPECT` on structural or semantic errors.
- Event Emitter & Forensics: Emits `MANAGER_REVIEW_ATTEMPT` to the event bus containing attempt number, exit code, duration, and output tails for deep inspection.
- Dual Parser: `_parse_opencode_json_decision()` reads JSON event streams when `--format json` is supported, falling back to regex.
- `tests/unit/test_review_budget_retry.py`: 9 new tests covering the retry loop, backoff multipliers, json parsing, budget truncation, and forensic event emission.

### Changed
- `scripts/run_pytest_safe.py`: Registered `tests/test_manager_review_bridge.py` and `tests/unit/test_review_budget_retry.py` inside `DEFAULT_PYTEST_ARGS`.
- `PROJECT.md`: Upgraded system version to `v9.14.0`.
- `.agent/.version_manifest.json`: Upgraded agent core version to `v9.14.0`.
- `pyproject.toml`: Upgraded package version to `9.14.0`.

---
# 2026-05-19 - WP-2026-094 Host setup hook for post-install bootstrap

### Added
- `scripts/install_agent_system._detect_host_setup()`: Detects `.agent/host-setup.{sh,ps1}` in destination project.
- `scripts/install_agent_system._maybe_invoke_host_setup()`: Shows first 20 lines, prompts for confirmation (unless `--yes`), executes hook, propagates exit code.
- `.agent/host-setup.sh.example`: Bash template with documented contract.
- `.agent/host-setup.ps1.example`: PowerShell template with documented contract.
- `--yes` flag to `install_agent_system.py`: Skip interactive confirmation (CI mode).
- `tests/unit/test_install_agent_system.py`: 8 new tests covering detection, user decline, failure propagation, dry-run, and auto_yes.

### Changed
- `scripts/install_agent_system.install_agent_system()`: Invokes host setup hook post-copy (after profile flip).
- `scripts/install_agent_system.sync_agent_system()`: Invokes host setup hook post-copy (after profile flip).
- `AGENTS.md`: Added "Host setup hook (WP-2026-094)" section.
- `CREDITS.md`: Added MIT attribution row for OpenHands pattern.

### Summary
- Adapts OpenHands `.openhands/setup.sh` pattern (MIT) to our layout.
- Interactive confirmation by default (security boundary: no script execution without human OK).
- Exit code propagation (no masking): failed hook aborts install.
- Backward-compatible: absence of hook is valid (silent no-op).
- Templates use `.example` extension: user renames to activate.

---
# 2026-05-19 - Post-audit fixups (session closeout)

### Fixed
- `skills/bui-run-quality-gates/SKILL.md`: Corrected dispatch table description — pip-audit is invoked directly by the dispatcher, not via pre-commit hooks.
- `tests/unit/test_pip_audit_policy.py`: Renamed `test_should_run_pip_audit_with_uv_lock` → `test_should_run_pip_audit_with_requirements_file` (test was covering `requirements-dev.txt`, not `uv.lock`). Added a new, dedicated `test_should_run_pip_audit_with_uv_lock` that correctly tests `uv.lock`.
- `scripts/check_ruff_hook_scope.py`: Added `_normalize_types_val()` helper so the scope guard correctly detects `types:` in multi-line YAML list form (e.g. `types:\n  - python`), not only in inline form.
- `tests/unit/test_check_ruff_hook_scope.py`: Added 2 new tests — `test_valid_config_multiline_types_passes` and `test_multiline_types_with_markdown_fails` — to lock in the multi-line detection.

### Result
- **68/68 tests pass** (`+3` vs WP-093 closeout baseline of 65).
- `ruff check .` → All checks passed.
- `--validate` → 0 errors, 0 warnings.

---
# 2026-05-19 - WP-2026-093 Pre-commit Ruff scope guard for Markdown-safe hooks

### Added
- `scripts/check_ruff_hook_scope.py`: Zero-dependency, stdlib-only scope verification script enforcing that `ruff-check` and `ruff-format` remain strictly Python-only.
- `tests/unit/test_check_ruff_hook_scope.py`: 4 unit tests covering valid configs, missing files, degraded configurations, and markdown/ambiguous configurations.

### Changed
- `scripts/run_pytest_safe.py`: Registered `test_check_ruff_hook_scope.py` in default suite.
- `.pre-commit-config.yaml`: Added protective comments alerting future authors of the scope check.
- `AGENTS.md` and `PROJECT.md`: Documented the new scope guard mechanism to prevent documentation-only tickets from inheriting cosmetic linter checks.

### Summary
- Completely shields non-Python (e.g. Markdown) deliverables from inheriting unnecessary cosmetic linter checks.
- Guarantees automated failure at check-time if the `.pre-commit-config.yaml` is modified to widen ruff scope.

---
# 2026-05-18 - WP-2026-092 Conditional pip-audit by dependency surface

### Added
- `scripts/pip_audit_policy.py`: New policy module deciding whether `pip-audit` should run based on the active work plan's `Files Likely Touched`.
- `tests/unit/test_pip_audit_policy.py`: 5 unit tests validating the dependency surface evaluation and conservative fallback mechanisms.

### Changed
- `scripts/run_gates_dispatch.py`: Integrated `pip-audit` execution into `run_code_gates` natively, along with `ruff check .`, executing it only when `should_run_pip_audit()` confirms dependency manifest modifications.
- `scripts/run_pytest_safe.py`: Registered `test_pip_audit_policy.py` in default suite.
- `AGENTS.md` and `PROJECT.md`: Documented the new dependency-surface policy implementation to resolve WP-087 Gap #4.

### Summary
- Prevents expensive `pip-audit` executions on code tickets when `pyproject.toml`, `requirements.txt`, or locks remain untouched.
- Retains conservative fallback: if missing information, `pip-audit` executes to prioritize security over latency.

---
# 2026-05-18 - WP-2026-091 Pluggable manager review rubric by deliverable_type

### Added
- `tests/unit/test_review_strategy_selection.py`: 3 unit tests verifying deliverable_type-based prompt selection and fallback.

### Changed
- `bus/review_bridge.py`: Updated `ReviewBridge` to read the active plan's `deliverable_type` and construct tailored prompts for OpenCode manager review (code, mixed, and non-code strategies).
- `scripts/run_pytest_safe.py`: Registered the new `test_review_strategy_selection.py` unit tests in `DEFAULT_PYTEST_ARGS`.
- `AGENTS.md`: Documented the new pluggable review rubric contract.
- `PROJECT.md`: Recorded WP-2026-091 completion.

### Summary
- Resolves WP-087 Gap #3 BLOCKER.
- Avoids unified, blind review prompts by dynamically building instructions based on `deliverable_type`:
  - `code` strategy: checks correctness, tests, and styles.
  - `mixed` strategy: combines code checks with thorough structure checks for declared deliverables.
  - `documentation` / `research` / `analysis` strategy: centers strictly on clarity, depth, quality, and structure of requested documents.
- Fallback preserves full backward-compatibility with historical or un-typed tickets.
- Output contract (`APPROVE` / `CHANGES`) remains unchanged for system interoperability.

---
# 2026-05-18 - WP-2026-090 Host-first skill precedence and config profiles

### Added
- `tests/unit/test_skill_discovery.py`: 2 new unit tests verifying host-first precedence override and bundle fallback.
- `tests/unit/test_install_agent_system.py`: 1 new unit test verifying profile flip logic at destination.
- `tests/test_check_skill_collisions.py`: added coverage for collisions across bundle and host skill roots.
- `.agent/config/agents.json`: Added `"active_profile": "engine-dev"` to define the default active profile.

### Changed
- `scripts/discover_skills.py`: Updated `discover_skills()` to discover and merge skills from both host directory (`<destino>/.agent/skills/`) and bundle directory (`skills/`), enforcing host precedence.
- `scripts/check_skill_collisions.py`: Expanded collision scanning to include both bundle and host skill roots.
- `scripts/install_agent_system.py`: Added `flip_profile_in_destination()` to automatically flip `"active_profile"` from `"engine-dev"` to `"host-project"` during `--install` or `--sync`.
- `AGENTS.md`: Documented host-first skill precedence and config profiles.

### Summary
- Allows the engine bundle to be highly reusable and agnostic across multiple host destination projects.
- Host skills override homonymous bundle skills deterministically.
- Installs with automatically flipped configuration profiles (`engine-dev` -> `host-project`).
- Zero dependencies added, fully backward compatible.

---
# 2026-05-18 - WP-2026-089 Pluggable quality gates dispatch by deliverable_type

### Added
- `scripts/run_gates_dispatch.py`: Dispatcher that reads `deliverable_type` and routes quality gates.
- `scripts/check_deliverables_exist.py`: Validates that all declared files in `work_plan.md` actually exist on disk.
- `tests/unit/test_run_gates_dispatch.py`: 4 unit tests for deliverable_type reading and fallback.
- `tests/unit/test_check_deliverables_exist.py`: 3 unit tests for deliverables validation.
- `AGENTS.md` section "Quality gates dispatch by deliverable_type".

### Changed
- `skills/bui-run-quality-gates/SKILL.md`: Re-written as version 2.0.0, wrapping the dispatcher script instead of running hardcoded commands.
- `scripts/run_pytest_safe.py`: Added new unit test files to `DEFAULT_PYTEST_ARGS`.

### Summary
- Resolves WP-087 Gap #2 WORKAROUND.
- Dispatches conditional gates: `code` / fallback runs code gates (ruff, pytest, pip-audit); `documentation` / `research` / `analysis` runs deliverables check; `mixed` runs both.
- Stdlib only, fully backward-compatible.

---
# 2026-05-18 - WP-2026-088 Add deliverable_type field to work_plan schema

### Added
- `.agent/agent_controller.py._check_deliverable_type()`: Validator function that checks for `deliverable_type` field in work_plan.md.
- `.agent/agent_controller.py._check_deliverable_type()` integration in `_handle_validate()`: Emits warnings (not errors) for missing, unknown, or compound values.
- `skills/man-create-work-plan/references/plan-template.md`: Added `deliverable_type` field to template with explanatory notes.
- `skills/man-create-work-plan/SKILL.md`: Added `deliverable_type` to workflow example.
- `tests/unit/test_work_plan_schema.py`: 7 tests covering valid, missing, unknown, compound, case-insensitive, and extra-spaces scenarios.
- `AGENTS.md`: Documentation section "deliverable_type (work_plan schema, V1)".

### Changed
- `.agent/agent_controller.py._handle_validate()`: Now calls `_check_deliverable_type()` and adds warnings to output.

### Summary
- V1 informational: validator emits warning if field missing, unknown value, or compound syntax (e.g., 'code+documentation').
- No dispatch yet (WP-089 will implement conditional gates based on deliverable_type).
- Resolves Gap #1 BLOCKER from WP-2026-087 gap analysis.
- Values: `code | documentation | research | analysis | mixed`.
- Backward compatible: historical work_plans without the field get warning, not error.

---
# 2026-05-18 - WP-2026-085 Config Migration Framework for agents.json

### Added

- `.agent/agents_config.py`: Migration framework idempotente para `agents.json`:
  - `Migration` dataclass: describe transición de schema (id, from_version, to_version, apply).
  - `MigrationReport` dataclass: reporte de ejecución (applied, skipped, backups).
  - `_migrate_1_0_to_1_1()`: handler puro que backfills `role_models` con defaults WP-072.
  - `MIGRATIONS` registry: lista ordenada cronológicamente de migraciones.
  - `migrate_agents_config()`: pipeline 4-paso con backup timestamped + idempotencia.
  - Legacy backfill: config sin `_migrations` con schema actual → poblar retroactivamente sin re-ejecutar.
- CLI `--migrate` / `--dry-run` en `agents_config.py`.
- `tests/unit/test_agents_config.py::TestMigrationFramework`: 7 tests (idempotencia, backup, _migrations update, legacy backfill, dry-run, handler purity, migración 1.0→1.1).

### Changed

- `.agent/config/agents.json`: Añadido `_migrations: ["1.0_to_1.1"]` para reflejar estado real.
- `AGENTS.md`: Añadido comando `Migrar config: python .agent/agents_config.py --migrate [--dry-run]`.

### Summary

- Framework V1 scope acotado: solo `agents.json` + `agents_config.py` + tests.
- Idempotencia obligatoria: segunda `--migrate` consecutiva = no-op (sin backup).
- Backup convention: `agents.json.bak.<ISO-timestamp>` antes de cada migración.
- Stdlib only: sin dependencias nuevas (`semver`, `migrate`, etc. prohibidos).
- **Origen externo**: Oportunidad #1 de `code-yeongyu/oh-my-openagent` - ver `.agent/runtime/compare/code-yeongyu-oh-my-openagent-*.md`.

---
# 2026-05-18 - WP-2026-084 Robust Builder Relaunch (supervisor liveness + launcher resume mode)

### Added
- `bus/supervisor.py._builder_alive()`: Método helper que verifica liveness del Builder via PID + `tasklist` (Windows) con fallback a mtime <15 min.
- `bus/supervisor.py._relaunch_builder()`: Ahora captura stdout/stderr del launcher (Capa 1), verifica liveness antes de relanzar (Capa 2), y usa flag `-ResumeBuilder` (Capa 4).
- `scripts/launch_agent_terminals.ps1 -ResumeBuilder`: Flag aditivo que skip cleanup agresivo (`Stop-ProjectAgentProcesses`, `Remove-StaleRuntimeArtifacts`, `Assert-StartupAlignment`) cuando viene de requeue del supervisor.
- `tests/test_supervisor.py`: 6 tests nuevos (`test_builder_alive_pid_exists`, `test_builder_alive_pid_dead`, `test_builder_alive_no_lock`, `test_builder_alive_fallback_mtime`, `test_relaunch_uses_resume_flag`, `test_supervisor_skips_relaunch_when_builder_alive`).

### Changed
- `bus/supervisor.py._relaunch_builder()`: Ahora devuelve `bool` (True=success/skipped, False=failure). Integrado en `run_once` para relanzamiento condicional.
- `scripts/launch_agent_terminals.ps1`: Cleanup envuelto en `if (-not $ResumeBuilder)` para preservar comportamiento default en primera apertura.

### Summary
- Solución estructural al bug de WP-2026-083: supervisor mataba Builder vivo al relanzar tras CHANGES.
- 4 capas: diagnóstico stdout/stderr + liveness PID-based + flag ResumeBuilder + integración supervisor.
- ADITIVIDAD: launcher sin `-ResumeBuilder` comporta igual que antes (cero regresión).
- NO dependencias nuevas (`psutil` prohibido). Solo `tasklist` nativo Windows + stdlib.
- NO tocar agent_controller / event_bus / state_machine / review_bridge.

---
# 2026-05-18 - WP-2026-083 Memory Consolidate V1 (Dream Cycle, deterministic, no LLM)

### Added
- `scripts/memory_consolidate.py`: CLI determinista para consolidar `observations.jsonl` (dedupe 24h + filter noise + archive >30d + regen MEMORY.md).
- `tests/unit/test_memory_consolidate.py`: 7 tests cubriendo dedupe, drop noise, archive, idempotencia, dry-run.
- `skills/memory-consolidate/SKILL.md`: Skill con triggers `[/consolidate, /memory, /dream-cycle]`.

### Changed
- `skills/project-finalize/SKILL.md`: Añadido Paso 9d (invocación opcional al cierre de sesión).
- `AGENTS.md`: Añadido comando `Memoria consolidada: python scripts/memory_consolidate.py [--apply]`.

### Summary
- V1 determinista (sin LLM, sin cron) de la "dream cycle" de gbrain.
- Default dry-run; `--apply` para escribir con backup `.bak.<timestamp>`.
- Idempotencia obligatoria: segunda ejecución consecutiva = no-op.
- **Origen externo**: Oportunidad #4 de `garrytan/gbrain` - ver `.agent/runtime/compare/garrytan-gbrain-*.md`.

---
# 2026-05-18 - WP-2026-082 Skill repo-compare (GitHub MCP + AUDIT.md as Phase 0)

### Added
- `skills/repo-compare/SKILL.md`: Skill pura (triggers: `/repo-compare`, `/compare`, `/gh-compare`) para comparar proyecto local con repositorios GitHub.
- `skills/repo-compare/PROMPT_TEMPLATE.md`: Prompt completo con 5 fases (preflight AUDIT, validación input, filtro rápido, exploración, output) + cap operativo (12 archivos × 500 líneas).
- `skills/repo-compare/references/output-format.md`: Plantilla de oportunidad con campos `Ya existe` (cita AUDIT.md) + `Fuente verificada`.
- `skills/repo-compare/references/filter-criteria.md`: Scoring 0-5 sobre 5 dimensiones + umbral 3 (BAJO VALOR).

### Changed
- `.gitignore`: Añadido `.agent/runtime/compare/` (output gitignored).
- `AGENTS.md`: Añadido comando `Comparar con repo GitHub: skill /repo-compare`.

### Summary
- Skill pura (sin script Python) que usa GitHub MCP + AUDIT.md como Fase 0.
- Smoke test obligatorio contra `Aider-AI/aider` antes de `--mark-ready`.
- Output persistido a `.agent/runtime/compare/<owner>-<repo>-<sha>-<date>.md`.

---
# 2026-05-18 - WP-2026-081 Implement Local Audit Tool and Skill

### Added
- `scripts/local_audit.py`: Script para recopilar el estado operativo del repositorio y emitir un snapshot estructurado (JSON/Markdown).
- `skills/local-audit/SKILL.md`: Skill (triggers: `/audit`, `/local-audit`, `/snapshot`) que expone el uso del script al entorno agéntico.
- `tests/unit/test_local_audit.py`: Tests unitarios para las funciones extractoras del local audit.

### Changed
- `AGENTS.md`: Añadido el comando `python scripts/local_audit.py` a los Comandos Principales.

### Summary
- Herramienta añadida para facilitar la comprensión de contexto, inspección rápida del sistema y soporte a procesos downstream como la comparación de repositorios.

---

# 2026-05-18 - WP-2026-080 Relaunch Builder on Request Changes & Rejection Counter

### Changed
- `agent_controller.py`: Se implementó el contador de rechazos. Transición a `IN_PROGRESS` (N < 3) o `HUMAN_GATE` (N >= 3).
- `bus/supervisor.py`: Implementado el polling reactivo para detectar `LOOP_DECISION:changes` y relanzar el builder mediante `launch_agent_terminals.ps1`.
- Tests añadidos para validar el ciclo de reintentos automatizados E2E.

---

# 2026-05-18 - WP-2026-079 Relaunch Loop on Request Changes (HUMAN_GATE)

### Changed
- `agent_controller.py`: Implementado el handler `--request-changes` que permitía enviar la transición inicial a `HUMAN_GATE`.

---

# 2026-05-17 - WP-2026-077 Bootstrap dedupe finalization (carry-over from WP-076)

### Changed

- `QUICKSTART.md` §6: Añadido pointer a [AGENTS.md](AGENTS.md#comandos-principales) para comandos de instalación.
- `QUICKSTART.md` §5: Añadido pointer a [INTERACTION_MODES.md](INTERACTION_MODES.md) para modos de interacción.
- `.claude/rules/01-security-architecture.md`: Añadido pointer a [AGENTS.md](../../AGENTS.md#secretos-y-seguridad) para política de seguridad.
- `prompts/session_bootstrap.md`: Añadido pointer a [PROJECT.md](../PROJECT.md#current-architecture) para flujo y arquitectura.
- `PROJECT.md` §"Source of truth": Añadido pointer a [AGENTS.md](AGENTS.md#rutas-importantes) para lista de paths.
- `AGENTS.md` §"Criterio de cierre": Añadido pointer a [QUICKSTART.md](QUICKSTART.md#6-comandos-diarios) para quality gates operacionales.
- `PROJECT.md`: Actualizada referencia "WP-2026-066 is in progress" → "WP-2026-066 completed".

### Summary

- **6 pointers añadidos** para consolidar documentación duplicada (dedupe B-class).
- **1 cleanup histórico** (A12): PROJECT.md refleja estado actual sin referencias "in progress" obsoletas.
- **7 commits** con prefijo `refactor(WP-077):`.
- **Quality gates**: ruff PASS, pytest 19 PASS, validate 0 errors.

---

# 2026-05-17 - WP-2026-076 Refactor bootstrap/onboarding chain (memory loading)

### Changed

- `CLAUDE.md`: Sección "Useful commands" ahora apunta a [QUICKSTART.md](QUICKSTART.md#6-comandos-diarios) en lugar de duplicar lista completa.
- `README.md`: Sección "Common commands" reducida; ahora apunta a [QUICKSTART.md](QUICKSTART.md) como fuente única.
- `.claude/rules/00-startup.md`: Secciones "Flujo de Trabajo" y "Quality Gates" ahora tienen pointers a [PROJECT.md](../PROJECT.md#current-cycle) y [QUICKSTART.md](../QUICKSTART.md#6-comandos-diarios).
- `prompts/session_bootstrap.md`:
  - Eliminada referencia a `~/.claude/projects/*/memory/MEMORY.md` (ruta absoluta externa).
  - Reemplazada por `.agent/runtime/memory/MEMORY.md` y `observations.jsonl` (rutas relativas portables).
  - Actualizada descripción del backend Manager a "modelo configurable en `.agent/config/agents.json`".
  - Sección "Reglas no negociables" ahora apunta a [AGENTS.md](AGENTS.md) como fuente única.

### Fixed

- **Portabilidad**: Cero referencias absolutas a `c:\Users\fdl` o `z_scripts/` en el repo portable (excepto `observations.jsonl` histórico).
- **Drift de versiones**: Todas las menciones de versión ahora coinciden con `pyproject.toml` (v9.9.0) y `.version_manifest.json` (v9.9.0).
- **Duplicidades consolidadas**: Comandos, política de seguridad y flujo Manager→Builder ahora tienen fuente única con pointers explícitos.

### Metrics

| Archivo | Líneas antes | Líneas después | Reducción |
|---------|--------------|----------------|-----------|
| `CLAUDE.md` | 32 | 32 | 0 |
| `README.md` | 63 | 58 | -5 |
| `.claude/rules/00-startup.md` | 22 | 25 | +3 (pointers agregados) |
| `prompts/session_bootstrap.md` | 80 | 80 | 0 |
| **Scope total** | **1828** | **1826** | **-2** |

> Nota: La reducción real es semántica (pointers en lugar de contenido duplicado), no bruta. Los archivos de entrada ahora son más scannables y la onboarding de cada backend (Claude, Codex/OpenCode, Goose) sigue intacta en ≤2 saltos.

### Verified

- `ruff check .` → All checks passed
- `python scripts/run_pytest_safe.py` → 19 passed
- `python .agent/agent_controller.py --validate --json --force` → 0 errors, 0 warnings
- Walk-through mental por backend: Claude (CLAUDE.md), Codex/OpenCode (AGENTS.md), Manager (.opencode/agents/manager.md) — todos siguen siendo onboardables sin saltar fuera del scope inicial.

---

# 2026-05-17 - HOTFIX WP-2026-075 drift correction (post-review manager)

Manager review smoke-test (Test B/D del `scripts/test_manager_smoke.ps1`) detectó drift entre `work_plan.md` y el código entregado en WP-2026-075. Tres correcciones aplicadas en frío, sin abrir nuevo ticket.

### Fixed

- `bus/event_bus.py`: el parámetro `max_duplicates` del constructor estaba declarado y asignado a `self.max_duplicates` pero `emit()`, `_record_blocked_emit()` y el log forense seguían usando `self.max_consecutive_duplicates`. Resuelto: ambos nombres son ahora aliases del mismo umbral; `max_duplicates` gana si se pasan los dos. Tests con `max_consecutive_duplicates=...` siguen funcionando.
- `tests/unit/test_bus_integrity.py`: eliminados imports muertos `os`, `tempfile` y `EventRecord` (señalados por el Manager; no detectados por `ruff check .` porque `tests/` está en `extend-exclude` de `pyproject.toml`).

### Clarified

- Path del log forense: el criterio de aceptación de `work_plan.md` línea 107 decía `.agent/runtime/logs/event_bus_blocks.jsonl`. La implementación real es `.agent/runtime/events/logs/event_bus_blocks.jsonl` (subsystem-scoped). La línea 61 del plan permitía explícitamente esta interpretación. Se mantiene la ruta del código (los tests la verifican y la separación por subsistema es coherente); se actualiza la entrada Added del WP-075 más abajo.

### Verified

- Manager review (`scripts/test_manager_smoke.ps1` Tests B y D) ahora alinea código y plan en los tres puntos detectados.

---

# 2026-05-17 - WP-2026-075 Event Bus Observability (De-duplication Tuning & Suppressed Logging)

### Added

- `bus/event_bus.py`: Observability constants for duplicate blocking:
  - `DUPLICATE_WINDOW_SIZE = 20`: Window size for counting recent duplicates.
  - `MAX_DUPLICATES_IN_WINDOW = 3`: Maximum duplicates allowed in window before blocking.
  - `STDERR_BLOCK_LIMIT = 5`: Maximum stderr warnings per session before suppression.
- `bus/event_bus.py`: Constructor parameters for tuning:
  - `window_size`: Configurable de-duplication window size (default: 20).
  - `max_duplicates`: Configurable maximum duplicates in window (default: 3).
- `bus/event_bus.py`: Session block counter `_session_block_count` for rate-limiting stderr.
- `bus/event_bus.py`: `_block_log_path` property pointing to `<runtime_dir>/logs/event_bus_blocks.jsonl` (i.e. `.agent/runtime/events/logs/event_bus_blocks.jsonl` in production). Path is subsystem-scoped: logs live alongside the events.jsonl they originate from. The work_plan.md line 61 left this open as "o `logs/event_bus_blocks.jsonl` según la estructura" and this resolution was chosen.
- `bus/event_bus.py`: `_record_blocked_emit()` method:
  - Increments session block counter.
  - Writes structured JSONL entry with `timestamp`, `event_type`, `ticket_id`, `actor`, `duplicate_count`, `window_size`, `threshold`, `session_block_number`.
  - Prints to stderr if under `STDERR_BLOCK_LIMIT`.
  - Prints suppression warning when limit exceeded.
- `bus/event_bus.py`: `emit()` now calls `_record_blocked_emit()` when blocking duplicates.
- `tests/unit/test_bus_integrity.py`: `TestBlockedEmitObservability` class with 4 tests:
  - `test_emit_logs_blocked_duplicates_to_file`: Verifies log file creation and entry structure.
  - `test_emit_blocks_multiple_duplicates_all_logged`: Verifies all blocks are logged.
  - `test_stderr_rate_limiting`: Verifies stderr output is rate-limited to 5 warnings + 1 suppression message.
  - `test_block_log_uses_append_mode`: Verifies append mode prevents overwriting.
- `import sys`: Added to `bus/event_bus.py` for stderr output.

### Changed

- `bus/event_bus.py`: `_count_recent_duplicates()` now uses `self.window_size` instead of hardcoded parameter.
- `bus/event_bus.py`: `emit()` returns `None` and logs blocked duplicate instead of silently dropping.
- `PROJECT.md`: Updated version to `v9.9.0` and current cycle to `WP-2026-075`.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: 19 passed (base suite)
- `pytest tests/unit/test_bus_integrity.py -v`: 18 passed (14 existing + 4 new observability tests)
- `python .agent/agent_controller.py --validate --json --force`: PASSED (0 errors, 0 warnings)

### Decision

- Observability resolves the 3 caveats from WP-2026-074 design: arbitrary window tuning, confusing nomenclature, and silent blocking.
- Forensic logging enables empirical tuning of `DUPLICATE_WINDOW_SIZE` and `MAX_DUPLICATES_IN_WINDOW` based on real blocking patterns.
- Stderr rate limiting prevents terminal spam during pathological loops while still providing immediate visibility.
- Append mode ensures concurrent block logging from multiple agents doesn't corrupt the forensic log.
- Default limits (window=20, threshold=3, stderr_limit=5) balance visibility with noise reduction.

---

# 2026-05-17 - WP-2026-074 Bus Integrity (Anti-duplicate emit + Per-ticket archive)

### Added

- `bus/event_bus.py`: Anti-duplicate protection in `EventBus.emit()`:
  - `_serialize_payload()`: Helper for deterministic payload comparison.
  - `_count_consecutive_duplicates()`: Counts consecutive identical events at end of bus.
  - `emit()` now returns `None` if event would exceed `MAX_CONSECUTIVE_DUPLICATES` (default: 3).
  - Configurable via `max_consecutive_duplicates` parameter in `__init__`.
  - Duplicate check compares `(event_type, ticket_id, actor, serialized_payload)`.
  - Different payload, ticket_id, event_type, or actor resets the duplicate counter.
- `bus/event_bus.py`: Per-ticket archive functionality:
  - `archive_ticket_events(ticket_id)`: Moves all events for a closed ticket to `.agent/runtime/events/archive/events.<ticket_id>.jsonl`.
  - Uses atomic write via `tempfile.mkstemp` + `os.replace` to prevent corruption.
  - Returns dict with `archived_count`, `archive_path`, `kept_count`, and `message`.
  - Creates archive directory if it doesn't exist.
  - Returns zero count if no events found for ticket.
- `tests/unit/test_bus_integrity.py`: New test module with 13 tests:
  - `TestAntiDuplicateEmit`: 8 tests covering duplicate detection, counter reset conditions, and configurability.
  - `TestArchiveTicketEvents`: 5 tests covering archive functionality, atomicity, and event order preservation.

### Changed

- `.agent/agent_controller.py`: Fixed order invariant in `_handle_mark_ready()`:
  - `_emit_builder_exit()` now called BEFORE `_sync_mark_ready_targets()`.
  - This ensures `BUILDER_EXIT` sequence number < `STATE_CHANGED READY_FOR_REVIEW` sequence number.
  - Eliminates order invariant warning for new tickets.
- `PROJECT.md`: Updated version to `v9.8.0` and current cycle to `WP-2026-074`.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: 19 passed (base suite)
- `pytest tests/unit/test_bus_integrity.py -v`: 13 passed
- `python .agent/agent_controller.py --validate --json --force`: PASSED (0 errors, 0 warnings)

### Decision

- Anti-duplicate protection prevents pathological bus growth from infinite loops (like the 700+ `MANAGER_REVIEWING` incident in WP-2026-073).
- Default threshold of 3 consecutive duplicates balances protection with flexibility for legitimate repeated events.
- Per-ticket archive enables long-term bus maintainability by moving closed ticket events to historical storage.
- Atomic write ensures bus integrity even if process is interrupted during archive operation.
- Order invariant fix ensures canonical event sequence: `BUILDER_EXIT` (actor: BUILDER) always precedes `STATE_CHANGED READY_FOR_REVIEW` (actor: BUILDER/SUPERVISOR).

---

# 2026-05-16 - WP-2026-073 Launcher bootstrap error-path tests

### Added

- `tests/unit/test_launcher_bootstrap_error_paths.py`: New test module with 6 tests covering bootstrap error paths:
  - `test_bootstrap_exit_code_nonzero`: Verifies exit code != 0 throws with correct message (regression test for WP-2026-069 540694a colon-scope hotfix).
  - `test_bootstrap_json_without_error_property`: Verifies JSON without `.error` property does not crash under StrictMode (regression test for WP-2026-069 a5df2cd hotfix).
  - `test_bootstrap_json_status_skipped`: Verifies JSON with `.status=skipped` throws with clear message including optional properties.
  - `test_bootstrap_non_json_stdout`: Verifies non-JSON stdout throws 'invalid JSON' message.
  - `test_bootstrap_variable_scope_colon_rendering`: Verifies error message renders exit code correctly without variable reference syntax.
  - `test_bootstrap_missing_optional_properties`: Verifies graceful handling of missing optional properties (`.plan_id`, `.reason`).
- Tests use `pytest.mark.skipif` for non-Windows platforms (PowerShell required).
- Tests use temporary mock controller scripts to simulate controlled failure scenarios.

### Verified

- `pytest tests/unit/test_launcher_bootstrap_error_paths.py -v`: 6 passed
- `pytest tests/unit/test_launcher_powershell_syntax.py tests/unit/test_launcher_opencode_invocation.py -v`: 7 passed (no regression)
- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: 19 passed
- `python .agent/agent_controller.py --validate --json --force`: PASSED

### Decision

- Three hotfixes were applied to `scripts/launch_agent_terminals.ps1` on 2026-05-16 (commits 540694a, a5df2cd, dbf4c4a) for bugs that lived in `main` because no test exercised the error path.
- This ticket closes that coverage gap with tests that invoke the bootstrap with controlled failure scenarios.
- Tests reproduce the 3 historical hotfixes (verifiable by reverting and observing failures).
- No changes to launcher were required (test-only ticket); tests pass with current launcher code.
- This is the first end-to-end cycle with the new Manager backend (`openai/gpt-5.4-mini` via OpenCode OAuth) introduced by WP-2026-072.

# 2026-05-16 - WP-2026-072 Manager backend switch to OpenCode (configurable model, DeepSeek V4 Flash default)

### Added

- `.opencode/agents/manager.md`: New Manager agent spec with restrictive permissions:
  - `read: allow`, `edit: deny`, `bash: deny`, `external_directory: deny`
  - Output contract: must end with `DECISION: APPROVE` or `DECISION: CHANGES`
- `role_models` map in `.agent/config/agents.json`:
  - Allows per-role model overrides without code changes
  - `MANAGER: opencode-go/deepseek-v4-flash` (default)
  - `BUILDER: opencode-go/qwen3.5-plus`
- `get_model_for_role(role, config)` function in `.agent/agents_config.py`:
  - Returns model string or None if no override
  - Enables easy model changes via single string edit in agents.json
- Multi-backend dispatch in `bus/review_bridge.py`:
  - `_get_manager_backend()`: Reads MANAGER backend from agents.json
  - `_get_manager_model()`: Reads model override from role_models
  - `_run_opencode_review()`: New route invoking `opencode run --agent manager --model <model> -f <files>`
  - `_run_codex_review()`: Legacy route preserved for backward compatibility
  - `_parse_opencode_decision()`: Parser for `DECISION: APPROVE|CHANGES` pattern
- Tests in `tests/test_manager_review_bridge.py::TestOpencodeReviewRoute`:
  - `test_parse_opencode_decision_approve`
  - `test_parse_opencode_decision_changes`
  - `test_parse_opencode_decision_no_decision_fallback_inspect`
  - `test_parse_opencode_decision_lowercase`
  - `test_get_manager_backend_default_codex`
  - `test_run_manager_review_cycle_dispatches_opencode`
  - `test_run_manager_review_cycle_dispatches_codex`
- Tests in `tests/unit/test_agents_config.py::TestGetModelForRole`:
  - Coverage for get_model_for_role with and without role_models
  - Validation tests for role_models schema

### Changed

- `.agent/config/agents.json`:
  - `schema_version`: 1.0 -> 1.1
  - `role_assignments.MANAGER`: "codex" -> "opencode"
  - Added `role_models` map with BUILDER and MANAGER model assignments
- `PROJECT.md`:
  - Updated Current Cycle section with WP-2026-072 completion
  - Added "Manager Backend Switch to OpenCode (WP-2026-072)" section
  - Documents configuration contract and easy model change procedure

### Preserved (Not Changed)

- Codex backend definition in `agents.json.backends` (not removed)
- Codex route in `bus/review_bridge.py` (legacy path preserved)
- To revert to Codex: set `role_assignments.MANAGER = "codex"` in agents.json

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: All tests passed
- `pytest tests/test_manager_review_bridge.py -v`: All tests passed
- `pytest tests/unit/test_agents_config.py -v`: All tests passed
- `python .agent/agent_controller.py --validate --json --force`: PASSED

### Decision

- Manager backend switched from Codex (OAuth) to OpenCode (static API key) to eliminate structural race condition.
- Cognitive diversity preserved: Builder (Qwen3.5 Plus) + Manager (DeepSeek V4 Flash) are different model families.
- Model change is now trivial: edit single string in `role_models.MANAGER` in agents.json.
- Codex remains available as option for future use.

# 2026-05-16 - WP-2026-071 Terminology refactor (rol manager vs backend codex)

### Changed

- `scripts/codex_review_bridge.py` -> `scripts/manager_review_bridge.py`: Renamed file to reflect role (Manager) rather than backend (Codex).
- `scripts/manager_review_bridge.py`: Updated symbols:
  - `_resolve_codex_executable` -> `_resolve_manager_executable`
  - `run_codex_review_cycle` -> `run_manager_review_cycle`
  - `codex_executable` parameter -> `manager_executable`
  - `codex_path` parameter -> `backend_path`
  - Log prefix `[codex-review-bridge]` -> `[manager-review-bridge]`
  - CLI flag `--codex-path` -> `--backend-path`
- `bus/review_bridge.py`:
  - `_codex_env` -> `_review_env`
  - `run_codex_review_cycle` -> `run_manager_review_cycle`
  - `codex_executable` parameter -> `manager_executable`
  - Backend-specific env (`CODEX_HOME`, `.codex/`) preserved.
- `scripts/launch_agent_terminals.ps1`:
  - `$CodexPath` parameter -> `$ManagerBackendPath`
  - `Resolve-CodexExecutable` -> `Resolve-ManagerExecutable`
  - Filename pattern `codex_manager_prompt_*.md` -> `manager_prompt_*.md`
  - References to `codex_review_bridge.py` -> `manager_review_bridge.py`
  - Backend resolution (`Resolve-BackendExecutable -BackendName 'codex'`) preserved.
- `tests/test_codex_review_bridge.py` -> `tests/test_manager_review_bridge.py`: Renamed file and updated imports.
- `tests/test_manager_review_bridge.py`: Updated function names `test_codex_review_cycle_*` -> `test_manager_review_cycle_*`.
- `tests/test_launch_agent_terminals_script.py`: Updated string assertions for new function/filename.
- `QUICKSTART.md`: Updated references to "Manager review bridge" (role) with backend clarification when needed.
- `INTERACTION_MODES.md`: Updated CLI examples to use `manager_review_bridge.py` and `--backend-path`.
- `PROJECT.md`: Updated role/backend description to "Manager review bridge (backed by Codex backend)".
- `prompts/session_bootstrap.md`: Updated role/backend description.

### Not Changed (Backend Preservation)

- `.agent/config/agents.json`: Backend `codex` definition and `MANAGER: codex` assignment intact (WP-2026-072 scope).
- `templates/startup/manager_codex.md`, `builder_codex.md`: `<rol>_<backend>` pattern preserved.
- `CODEX_HOME` env, `.codex/` excludes: Backend-specific configuration intact.
- `codex review <ticket_id>` command syntax: Codex CLI-specific command preserved.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: 19 passed
- `pytest tests/test_manager_review_bridge.py tests/test_launch_agent_terminals_script.py -v`: 11 passed
- `python scripts/manager_review_bridge.py --help`: Shows `--backend-path` flag correctly
- `python .agent/agent_controller.py --validate --json --force`: PASSED (0 errors; scope warnings expected for renames)

### Decision

- Role (Manager) and backend (Codex) nomenclature now separated.
- Future backend switch (WP-2026-072) can change `agents.json` and `bus/review_bridge.py` command without renaming files.
- Mechanical rename only; no functional change to review behavior.

---

# 2026-05-16 - WP-2026-070 Infrastructure hygiene (monthly exclude-newer + hook-CI alignment test)

### Added

- `.github/workflows/monthly-deps-bump.yml`: New scheduled workflow that runs at 06:00 UTC on the 1st of each month.
  - Updates `exclude-newer` in `uv.toml` to current date.
  - Runs `uv lock --upgrade` and `uv sync --all-groups`.
  - Validates with `pre-commit run --all-files --hook-stage pre-push`.
  - Creates branch and opens PR via `gh pr create`.
  - **No auto-merge**: PR requires human review.
  - Supports manual trigger via `workflow_dispatch`.
- `tests/unit/test_hook_ci_alignment.py`: Structural test validating semantic alignment between `.pre-commit-config.yaml` and `.github/workflows/security-audit.yml`.
  - Uses YAML parsing (yaml.safe_load), not string-match.
  - Verifies CI delegates to `pre-commit run` (not direct `pip-audit`).
  - Verifies pip-audit hook does not use reduced scope (no trailing `.`).
  - Verifies both use `--hook-stage pre-push`.
  - Fails if delegate pattern is broken (regression protection for commit `25153b3`+).
- `PROJECT.md`: Added "Monthly Exclude-Newer Policy (WP-2026-070)" section documenting the workflow and test.

### Changed

- `CHANGELOG.md`: Current cycle reference updated to WP-2026-070.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED
- `pytest tests/unit/test_hook_ci_alignment.py -v`: 5 passed
- `python .agent/agent_controller.py --validate --json --force`: PASSED
- YAML validation: `.github/workflows/monthly-deps-bump.yml` is valid

### Decision

- Monthly workflow prevents CVE invisibility from frozen `exclude-newer`.
- Structural test prevents drift between local hook and CI (like 2026-05-16 incident).
- No auto-merge ensures human review before merging dependency bumps.
- Pre-commit validation before PR creation prevents broken automatic PRs.

---

# 2026-05-16 - WP-2026-069 Controller hardening follow-up (manager-approve validation + order invariant sequence)

### Changed

- `.agent/agent_controller.py`: `_check_builder_exit_order()` now validates complete sequence of events, not just latest. For each `STATE_CHANGED READY_FOR_REVIEW`, checks if there's any prior `BUILDER_EXIT` with lower sequence number.
- `.agent/agent_controller.py`: `_handle_manager_approve()` now checks for `SUPERVISOR_CLOSED` event in bus for per-ticket idempotency, not just global markdown state.
- `.agent/agent_controller.py`: `_sync_markdowns_to_completed()` now also syncs `work_plan.md` to `COMPLETED` during canonical closeout.
- `scripts/launch_agent_terminals.ps1`: bootstrap preflight now fails fast when `--bootstrap-ticket` returns `error`, `skipped`, or a nonzero exit code.
- `tests/unit/test_invariant_order.py`: Updated `test_multiple_events_uses_latest` to `test_multiple_events_detects_any_inversion` and added `test_inversion_with_no_prior_exit` for sequence-based validation.
- `tests/unit/test_manager_approve.py`: Added `test_idempotency_via_bus_supervisor_closed` to verify bus-based idempotency.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED
- `python .agent/agent_controller.py --validate --json --force`: PASSED

### Decision

- Order invariant now detects inversions at any point in the sequence, not just comparing latest events.
- Manager-approve idempotency is per-ticket using bus events (`SUPERVISOR_CLOSED`), preventing wrong-ticket closure if markdown drifts.
- Violations remain warnings (not errors) to avoid invalidating historical tickets.

---

# 2026-05-16 - WP-2026-068 Controller hardening (invariant order + manager-approve)

### Added

- `.agent/agent_controller.py`: New function `_check_builder_exit_order()` to verify BUILDER_EXIT sequence < STATE_CHANGED READY_FOR_REVIEW sequence.
- `.agent/agent_controller.py`: New function `_emit_manager_approve_cascade()` to emit canonical closeout events.
- `.agent/agent_controller.py`: New function `_sync_markdowns_to_completed()` to sync markdown files on manager approve.
- `.agent/agent_controller.py`: New handler `_handle_manager_approve()` for `--manager-approve --ticket WP-XXXX` flag.
- `.agent/agent_controller.py`: `--ticket` argument parser for manager-approve flag.
- `tests/unit/test_invariant_order.py`: 6 tests for order invariant check.
- `tests/unit/test_manager_approve.py`: 6 tests for manager-approve flag (cascade, idempotency, blocking, JSON output, circuit breaker reset).

### Changed

- `.agent/agent_controller.py`: `_check_post_closure_invariants()` now calls `_check_builder_exit_order()` and includes order warnings.
- `.agent/agent_controller.py`: `FLAG_HANDLERS` dict now includes `--manager-approve` entry.
- `.agent/agent_controller.py`: `main()` now parses `--ticket` argument and passes it to manager-approve handler.
- `PROJECT.md`: Added "Manager Approve Flag (WP-2026-068)" section documenting the new flag and order invariant.
- `CHANGELOG.md`: Current cycle reference updated to WP-2026-068.

### Verified

- `ruff check .`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED
- `python .agent/agent_controller.py --validate --json --force`: PASSED

### Decision

- Order invariant violations are warnings (not errors) to avoid invalidating historical tickets.
- Manager-approve flag is idempotent: second invocation on COMPLETED ticket returns `already_completed` without emitting events.
- Flag blocks if ticket is not in READY_FOR_REVIEW state.
- Flag syncs markdowns and resets circuit breaker on success.

---

# 2026-05-15 - WP-2026-067 Launcher OpenCode integration

### Added

- `scripts/launch_agent_terminals.ps1`: New functions `Get-OpenCodeBuilderPrompt` and `Get-CanonicalFilesForOpenCode` for prompt composition and canonical file attachment.
- OpenCode launcher integration: invokes `opencode run "<msg>" --agent builder --model <model> --dir <root> -f <canonicals>` when backend is OpenCode.
- `.opencode/MODELS.md`: Documented launcher recipe and prompt composition.

### Changed

- `scripts/launch_agent_terminals.ps1`: OpenCode branch now uses composed prompt, reads model from `.opencode/opencode.json`, and attaches canonical files via `-f`.
- `QUICKSTART.md`: Removed manual paste instructions; documented automatic prompt composition for OpenCode backend.
- `PROJECT.md`: Added "Launcher OpenCode Integration (WP-2026-067)" section; updated current cycle to WP-2026-067.
- `CHANGELOG.md`: Current cycle reference updated to WP-2026-067.

### Verified

- `ruff check .`: pending
- `python scripts/run_pytest_safe.py`: pending
- `python .agent/agent_controller.py --validate --json --force`: pending

### Decision

- Model is read from config, never hardcoded in PowerShell.
- Kilo, Codex and Claude backends remain unchanged.
- Manual paste step eliminated for OpenCode backend.

---

# 2026-05-15 - WP-2026-066 Baseline Sync and Public Docs Hygiene

### Added

- `tests/integration/RETIRED_TESTS.md`: documentation of retired integration tests with clear justification.
- Integration test alignment: remaining tests (`test_lifecycle_integration.py`, `test_memory_integration.py`) updated to reflect current runtime.

### Changed

- `tests/integration/test_multi_ticket_integration_smoke.py`: RETIRED - depended on removed controller APIs (`mark_ready`, `request_changes`, `perform_document_closeout`, `get_log_status`, `get_rejection_count`, `COUNCIL_BROKER_AVAILABLE`).
- `tests/integration/test_lifecycle_integration.py`: updated version expectation from v9.5 to v9.6.
- `README.md`: current state reflects WP-2026-066 in progress.
- `PROJECT.md`: current cycle and baseline sync sections updated for WP-2026-066.
- `QUICKSTART.md`: current cycle reference updated to WP-2026-066 in implementation.

### Verified

- `python -m pytest tests/integration/ -v`: 7 passed
- `ruff check .`: pending
- `python .agent/agent_controller.py --validate --json --force`: pending

### Decision

- Retired tests documented rather than restored to avoid API debt.
- Multi-ticket security model remains documented in `PROJECT.md` but smoke test removed.
- Core flow validated through unit tests and terminal-driven canonical closeout.

---

# 2026-05-14 - Private GitHub publication of the recovered canonical snapshot

### Added

- `.opencode/`: local OpenCode agent config committed with `builder` and `manager` prompts for reproducible multi-agent runs.
- `PROJECT.md`: documented the recovered baseline and the private GitHub publication of the cleaned snapshot.

### Changed

- The recovered canonical baseline was published on `main` after `WP-2026-061` completed the cleanup of `WP-2026-060` residues.
- The repo now tracks the cleaned operational snapshot rather than the pre-recovery state.

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED
- `uv run pre-commit run --all-files`: PASSED

# 2026-05-14 - Recovery to WP-2026-059 baseline; WP-2026-060 attempt discarded; WP-2026-061 cleanup applied

### Context

After closing `WP-2026-059` (timezone normalization), an attempt at `WP-2026-060` (bridge validation and hardening) suffered massive scope-creep: the Builder modified 40+ files against the planned whitelist of 6, including out-of-scope rewrites of `pyproject.toml`, `uv.lock`, security hooks, Builder/Manager prompt templates, root docs and bus core. Codex (Manager review) flagged two specific regressions in `guard_paths.py` (overly broad regex blocking routine commands) and `bus/review_bridge.py` (removed call to `_record_review` breaking the human-readable review trail). The attempt was discarded.

### Recovered

- Canonical state files (`work_plan.md`, `execution_log.md`, `STATE.md`, `TURN.md`, `SESSION_BRIEF.md`) realigned to `WP-2026-059 COMPLETED`.
- 31 files restored from the prior local backup snapshot (`WP-2026-054 COMPLETED`) for paths that `WP-2026-055..059` did not touch and that `WP-2026-060` had contaminated.
- `bus/time_utils.py` and the timestamp normalization work from `WP-2026-059` are preserved.
- Seed/cursor fix to `scripts/codex_review_bridge.py` and related tests is preserved.

### Removed in WP-2026-061 cleanup

- `scripts/requeue_watcher.py` and `scripts/ticket_requeue_watcher.ps1` (requeue flow was specific to the discarded 060 design).
- `scripts/goose_observer.py` and `tests/test_goose_observer.py` (Goose advisory layer).
- `scripts/run_llm_evals.py` and `tests/unit/test_run_llm_evals.py` (DeepEval lane).
- `scripts/session_closeout.py` and `tests/unit/test_session_closeout.py` (standalone closeout utility).
- `tests/integration/test_manager_builder_loop.py` (depended on `STATE_FILE` constant that does not exist in the recovered controller).
- `tests/unit/test_codex_review_bridge_reseed.py`, `tests/unit/test_agent_controller_reconcile.py`, `tests/unit/test_session_tracker.py`, `tests/unit/test_supervisor_bootstrap_fingerprint.py` (referenced 060-only APIs).

### Known debt deferred

- Integration tests `test_multi_ticket_integration_smoke.py` and several others still reference removed symbols (`STATE_FILE`, `_seed_state_from_supervisor`, `_handle_reconcile_runtime`, `plan_fingerprint`) and need either deletion or restoration of those symbols. Pending decision in a follow-up ticket.

### Verified

- `ruff check .` passes.
- `python scripts/run_pytest_safe.py` passes (19 tests in the safe subset).
- `python -m pytest tests/test_codex_review_bridge.py` passes (6 tests).
- `python .agent/agent_controller.py --validate --json --force` reports no drift.

---

# 2026-05-14 - v9.6.0 closeout and isolated eval lane completed

### Added

- `scripts/run_llm_evals.py`: isolated fail-closed lane for DeepEval / LLM evaluations.
- `.agent/runtime/llm_evals_config.json`: versioned runtime contract for the eval lane.
- `scripts/goose_observer.py`: UTF-8-safe output handling on Windows.

### Changed

- `scripts/session_closeout.py`: confirmed closeout now removes `manager_bridge_state.json` in addition to other residual runtime artifacts.
- `scripts/detect_version.py`, `scripts/upgrade.py`, `scripts/upgrade_agent_system.py`: version contract updated to include v9.6.
- `pyproject.toml`: package version aligned to `v9.6.0`.
- `.agent/project_manifest.toml`, `.agent/.version_manifest.json`: internal version metadata aligned to `v9.6`.

### Verified

- `ruff`, `pytest-safe`, `pip-audit`, and canonical validation passed on the touched surfaces.
- The repository is now in closeout state, ready for the next planning cycle.

---

# 2026-05-13 - WP-2026-044b Runner return-code semantics and builder ticket fallback COMPLETED

### Added

- `scripts/orquestador.py`: comments that document where `return 0` is intentional for dry-run and skill-only modes.
- `scripts/builder_agent.py`: comments that document clean exits and explicit error exits, plus a defensive fallback to the active `plan_id` when `--ticket-id` is missing or stale.
- `.agent/collaboration/execution_log.md`: evidence for the semantics pass and the builder fallback guard.

### Verified

- `python -m py_compile scripts/orquestador.py scripts/builder_agent.py`: PASSED
- `python scripts/orquestador.py --dry-run --engine goose --mode write --query test`: PASSED
- `python scripts/builder_agent.py --help`: PASSED
- `python .agent/agent_controller.py --mark-ready --json --force`: PASSED

### Evidence

- `WP-2026-044b` closed canonically after documenting runner exit-code semantics.
- The builder now self-corrects stale or missing ticket IDs using the active `work_plan.md`.
- No runtime behavior changed beyond the defensive ticket selection guard.

---

# 2026-05-13 - WP-2026-043 Sequence guard for review-constrained closeout COMPLETED

### Added

- `WP-2026-043`: guard de secuencia para impedir closeout o reconciliacion a `COMPLETED` sin `APPROVE` explicito del Manager
- `.agent/collaboration/work_plan.md`, `.agent/collaboration/TURN.md`, `.agent/collaboration/STATE.md`, `.agent/collaboration/execution_log.md` y `.agent/collaboration/notifications.md`: alineados al cierre canonico
- `PROJECT.md`: nueva seccion "Sequence Guard for Review-Constrained Closeout"
- `QUICKSTART.md`: prompts operativos actualizados a `WP-2026-043`

### Changed

- `determine_next_action()` y `perform_document_closeout()` endurecidos con guard de aprobacion explicita
- Tests de `agent_controller.py` ajustados para cubrir la ruta sin APPROVE, con APPROVE y el cierre legitimo

---

# 2026-05-13 - WP-2026-042 Canonical project closure and documentation sync COMPLETED

### Added

- `.agent/archive/execution_log_WP-2026-037-to-041.md`: historical execution logs archived
- `.agent/archive/canonical_state_WP-2026-041.json`: project state snapshot at WP-2026-041 completion
- `.agent/archive/`: created archive directory for operational history preservation
- `PROJECT.md`: updated with canonical closure section and idle clean state documentation
- `QUICKSTART.md`: aligned with post-closure idle state and next cycle startup procedures
- `CHANGELOG.md`: closure entries for WP-2026-041 and WP-2026-042 completion

### Changed

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`: reset for next planning cycle
- Runtime artifacts: cleaned temporary states and residual cursors
- Documentation: synchronized live docs with actual runtime state

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED (canonical alignment confirmed)
- Quality gates: ruff check, pytest-safe passed on all touched files
- Archive integrity: historical data preserved without drift

### Evidence

- Project achieved canonical closure with full archival and documentation sync
- WP-2026-037 through WP-2026-041 operational history preserved in archive
- Runtime left in idle clean state ready for MANAGER / CREATE_PLAN
- All deliverables from WP-2026-042 scope completed successfully

---

# 2026-05-12 - WP-2026-041 Review loop automation COMPLETED

### Added

- Review loop automation with bus-first runtime and Supervisor-directed cycles
- LOOP_INITIALIZED, LOOP_ROUND_START, LOOP_DECISION, LOOP_CONTROL, ESCALATION_INITIATED events
- Scope freeze baseline emission at work start
- Builder requeue mechanism with previous feedback injection
- Supervisor loop control (REQUEUE_BUILDER, READY_TO_CLOSE, HUMAN_GATE)

### Changed

- `supervisor_state.json`: confirmed as cursor/cache only, bus remains authority
- Builder prompts: enhanced with round counter and previous feedback context
- Manager review: integrated with loop flow and convergence tracking

### Verified

- `python -m pytest tests/test_agent_controller.py tests/test_supervisor.py tests/test_codex_review_bridge.py -q`: 67 passed
- `ruff check`: clean on all modified files
- Loop convergence: tested through APPROVE, CHANGES, and timeout scenarios

### Evidence

- Builder->Manager->Builder cycles automated with deterministic flow
- Review retries handled automatically until convergence or escalation
- Bus-first architecture maintained with projection synchronization

---

# 2026-05-13 - WP-2026-042 Canonical project closure and documentation sync preparado

---

# 2026-05-12 - WP-2026-041 Review loop automation preparado

### Added

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md` y `notifications.md`: alineados al nuevo plan activo `WP-2026-041`
- `PROJECT.md`: seccion "Review Loop Automation" con el contrato de eventos y el rol de Supervisor como director del bucle
- `QUICKSTART.md`: prompts operativos actualizados a `WP-2026-041`

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED (alineacion canonica confirmada)

### Evidence

- `WP-2026-041` prepara el bucle Builder -> Manager -> Builder con scope freeze, requeue y human gate
- `supervisor_state.json` queda como cursor/cache, no como fuente de verdad
- El bus de eventos sigue siendo la autoridad de transicion

---

# 2026-05-12 - WP-2026-040 Startup templates por rol/backend implementado

### Added

- `templates/startup/builder_kilo.md`, `builder_codex.md`, `manager_codex.md`, `manager_kilo.md`, `supervisor_default.md`: plantillas de arranque con variables {{ticket_id}}, {{work_plan}}, {{close_command}}, {{role}}, {{backend}}
- `scripts/launch_agent_terminals.ps1`: funciones Get-TemplateContent y Fill-TemplateVariables para cargar y rellenar plantillas automaticamente
- `scripts/launch_agent_terminals.ps1`: limpieza diferida del prompt temporal del bridge tras arrancar Review Bridge
- `scripts/codex_review_bridge.py`: argumento --manager-prompt-file para usar plantilla personalizada en lugar del prompt hardcoded
- `.agent/bus/review_bridge.py`: modificado run_codex_review_cycle para aceptar manager_prompt_file y leer archivo si proporcionado
- `tests/test_launch_agent_terminals_script.py`: test actualizado para verificar uso de plantillas, existencia de variables y funciones en el script
- `PROJECT.md`: seccion "Startup Templates" actualizada con implementacion completa
- `QUICKSTART.md`: seccion 0c actualizada para reflejar plantillas operativas
- `CHANGELOG.md`: entrada documentando la implementacion
- `.agent/collaboration/execution_log.md`: evidencia completa de implementacion y validacion

### Verified

- `python scripts/run_pytest_safe.py tests/test_launch_agent_terminals_script.py -q`: PASSED (5/5 tests)
- `python .agent/agent_controller.py --validate --json --force`: PASSED (alineacion canonica confirmada)
- `python .agent/agent_controller.py --mark-ready --json --force`: PASSED (ticket cerrado canonicamente)

### Evidence

- `WP-2026-039` queda cerrado canonicamente tras el smoke multi-ticket
- `WP-2026-040` abre el flujo de plantillas de arranque por rol/backend
- Se documenta la inyeccion de variables de plantilla para reducir prompt drift

---

# 2026-05-12 - WP-2026-039 Multi-Ticket Integration Smoke implementado

### Added

- `tests/integration/test_multi_ticket_integration_smoke.py`: smoke determinista para tres tickets consecutivos sin drift con tres escenarios (APPROVE limpio, CHANGES/re-APPROVE, cierre directo)
- `PROJECT.md`: seccion "Multi-Ticket Security Model" documentando garantias de aislamiento, alineacion canonica, limpieza automatica y validacion
- `QUICKSTART.md`: seccion 7 sobre el smoke test multi-ticket y comando de ejecucion
- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md` y `notifications.md`: alineados al nuevo plan activo

### Verified

- `python scripts/run_pytest_safe.py tests/integration/test_multi_ticket_integration_smoke.py -q`: PASSED (tres escenarios deterministas sin drift)
- `python .agent/agent_controller.py --validate --json --force`: PASSED (alineacion canonica confirmada)

### Evidence

- `WP-2026-039` valida que tres tickets consecutivos pasan supervisor -> builder -> review -> closeout sin arrastrar estado
- Verificado aislamiento entre tickets (no builder_lock.txt, no cursors obsoletos en manager_bridge_state.json)
- Alineacion canonica antes de cada lanzamiento y limpieza automatica funcional
- Tres escenarios pasan: recorrido feliz, rechazo/re-implementacion, cierre directo sin review

---

# 2026-05-12 - WP-2026-038 preflight estricto y reconciliacion automatica implementado

### Added

- `scripts/launch_agent_terminals.ps1`: Parametro `--StrictLaunch` para validacion estricta (default true), reporte corto por ventana lanzada, limpieza automatica de `manager_bridge_state.json` obsoleto
- `QUICKSTART.md`: Documentacion del modo estricto y reportes de arranque
- `PROJECT.md`: Actualizado para reflejar las capacidades de preflight mejoradas
- `CHANGELOG.md`: Registro de la implementacion del preflight estricto

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED
- Quality gates pasan sobre archivos tocados (scripts/launch_agent_terminals.ps1, QUICKSTART.md, PROJECT.md, CHANGELOG.md)

### Evidence

- Launcher valida alineacion entre `work_plan.md`, `TURN.md` y `STATE.md` antes de abrir ventanas
- Limpieza automatica de `manager_bridge_state.json` si apunta a ticket anterior
- Reporte explicito por cada ventana lanzada para claridad operativa
- Modo estricto aborta en caso de drift, con opcion de deshabilitar via `-StrictLaunch:$false`

---

# 2026-05-12 - WP-2026-037 Arranque de PowerShell para ventanas independientes completado

### Added

- `QUICKSTART.md`: Documentacion mejorada del launcher para ventanas independientes con limpieza de sesiones viejas
- `PROJECT.md`: Marcado como "PowerShell launcher ready" en current readiness
- `execution_log.md`: Evidencia de que el launcher esta funcional y la documentacion actualizada
- `CHANGELOG.md`: Registro de la preparacion del arranque de PowerShell

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED
- Launcher existente funciona correctamente con alineacion de startup y limpieza de estado obsoleto
- Quality gates pasan sobre archivos tocados

### Evidence

- Launcher `scripts/launch_agent_terminals.ps1` preparado para abrir Supervisor, Review Bridge y Builder en ventanas independientes
- Documentacion operativa actualizada para reflejar capacidades del launcher sin ambiguedad
- No se introdujeron cambios de runtime ni dependencias nuevas

### Added

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md` y `notifications.md` actualizados para que `WP-2026-037` sea el ticket activo.
- `PROJECT.md` y `QUICKSTART.md` apuntan ahora a `WP-2026-037` como siguiente ticket para Builder.
- El launcher mantiene el preflight de alineacion y la limpieza de `manager_bridge_state.json` antes de abrir ventanas.

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED

# 2026-05-12 - WP-2026-037 Arranque estricto y limpieza de sesiones viejas

### Added

- `scripts/launch_agent_terminals.ps1`: Nueva función `Is-BuilderRunningInProject()` que usa lock file para verificar sesiones duplicadas scoped al proyecto.
- `scripts/launch_agent_terminals.ps1`: Lógica condicional que permite override manual de Builder con `-BuilderPrompt` independientemente del rol activo.

### Changed

- `scripts/launch_agent_terminals.ps1`: Reemplazado chequeo global de procesos Kilo con scoped lock file para evitar falsos positivos.
- `QUICKSTART.md`: Actualizada documentación del launcher para explicar preflight, limpieza de sesiones viejas y override manual.

### Verified

- `ruff check scripts/launch_agent_terminals.ps1`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED (sin cambios en tests)
- `python .agent/agent_controller.py --validate --json --force`: PASSED sin drift
- Launcher probado manualmente: verifica alineación, limpia bridge state obsoleto, permite override manual y evita duplicados scoped.

### Evidence

- Launcher reforzado para preflight estricto y limpieza de residuos de sesiones anteriores.
- Override manual preservado para testing y escenarios no BUILDER.
- Quality gates pasan sobre archivos tocados.

# 2026-05-12 - WP-2026-036 Launcher auto-start para Builder

### Added

- `scripts/launch_agent_terminals.ps1`: Nueva función `Get-ActiveRole()` que lee `TURN.md` para determinar el rol activo.
- `scripts/launch_agent_terminals.ps1`: Nueva función `Is-BuilderRunning()` que verifica si Kilo ya está ejecutándose para evitar sesiones duplicadas.
- `scripts/launch_agent_terminals.ps1`: Lógica condicional que solo lanza Builder cuando el rol activo es `BUILDER` y no hay una sesión existente.

### Changed

- `QUICKSTART.md`: Actualizada sección del launcher para documentar que es inteligente y solo lanza Builder cuando corresponde.
- `PROJECT.md`: Documentado que el launcher lee `TURN.md` y previene duplicados.

### Verified

- `ruff check scripts/launch_agent_terminals.ps1`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED (sin cambios en tests)
- `python .agent/agent_controller.py --validate --json --force`: PASSED sin drift
- Launcher probado manualmente: solo lanza Builder cuando rol es BUILDER, omite si ya está corriendo.

### Evidence

- Launcher modificado para detectar rol activo en `TURN.md` y evitar duplicados.
- Documentación actualizada para reflejar automatización sin ambiguedad.
- Quality gates pasan sobre archivos tocados.

# 2026-05-12 - WP-2026-034 closeout and WP-2026-036 draft

### Changed

- `WP-2026-034` was closed canonically after the checkpoint-sync fix passed validation.
- `work_plan.md` now records `WP-2026-036` as the next prepared ticket for Builder auto-start automation.
- `PROJECT.md` and `QUICKSTART.md` now point Builder prompts at `WP-2026-036` as the next workstream.

### Verified

- `python .agent/agent_controller.py --validate --json --force` passes after closeout.
- The repo is ready for the next planning cycle with `MANAGER / CREATE_PLAN` active.

# 2026-05-12 - WP-2026-034 smoke test del requeue Manager/Builder

### Changed

- Updated `PROJECT.md` with clear instructions on starting Builder for the active ticket WP-2026-034.
- Updated `QUICKSTART.md` to confirm unambiguous Builder startup for WP-2026-034.
- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md`, `PROJECT.md` y `QUICKSTART.md` reflejan WP-2026-034 sin ambiguedad.

### Evidence of requeue

- Manager performed INSPECT on 2026-05-12 10:19:59, leading to turn back to BUILDER / IMPLEMENT without operational drift.
- TURN.md, STATE.md, execution_log.md, and notifications.md updated correctly via bus-first runtime.
- The ticket passed through Manager rejection (INSPECT) and returned to Builder cleanly, validating the requeue flow.

### Verified

- `python .agent/agent_controller.py --validate --json --force` passes clean.
- `python scripts/run_pytest_safe.py tests/test_agent_controller.py tests/integration/test_manager_builder_loop.py -q` passes.
- No new roles or dependencies introduced.
- Documentation updated for clarity without introducing ambiguity.

# 2026-05-12 - WP-2026-035a closeout and WP-2026-035b kickoff

### Changed

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md`, `PROJECT.md` and `QUICKSTART.md` were updated to close `WP-2026-035a` and activate `WP-2026-035b`.
- `WP-2026-035b` is now the active cycle for bus-first projection sync and active-ticket scoping.

### Verified

- `python .agent/agent_controller.py --validate --json --force` passes without drift after the handoff.


# 2026-05-12 - WP-2026-035a bus-first runtime transition authority

### Added

- `agent_controller.py`: Modificado `determine_next_action()` para derivar estado desde el bus JSONL como fuente primaria, con fallback a archivos.
- `agent_controller.py`: Agregado emisión de eventos `STATE_CHANGED` y `PLAN_STATUS_CHANGED` al actualizar estados en los archivos.

### Changed

- `PROJECT.md`: Actualizada sección `## Current architecture` para documentar el bus JSONL como autoridad canónica de transición, y los archivos Markdown como proyecciones derivadas.
- `QUICKSTART.md`: Actualizado flujo operativo para Builder explicando que el runtime usa el bus como autoridad canónica.

### Verified

- `ruff check .agent/agent_controller.py PROJECT.md QUICKSTART.md CHANGELOG.md`: PASSED
- `python scripts/run_pytest_safe.py`: PASSED
- `python .agent/agent_controller.py --validate --json --force`: PASSED sin drift

# 2026-05-12 - WP-2026-034 smoke test del requeue Manager/Builder

### Added

- `work_plan.md`: Nuevo ticket activo `WP-2026-034` para validar el requeue real con un ciclo pequeno.
- `TURN.md` y `STATE.md`: Turno terminal-driven alineado a `BUILDER / IMPLEMENT` para `WP-2026-034`.
- `execution_log.md`: Registro de arranque del smoke test del requeue Manager/Builder.
- `notifications.md`: Notificacion de `START_WORK` para el nuevo ciclo.

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED

# 2026-05-12 - WP-2026-033 Health dashboard derivado de manifests

### Added

- `agent_controller.py`: Nuevo comando `--health` que expone resumen de salud operativo.
- `PROJECT.md`: Nueva sección `## Health Dashboard` documentando consulta y implementación.
- `QUICKSTART.md`: Agregado `python .agent/agent_controller.py --health` a comandos diarios.

### Changed

- `agent_controller.py`: Implementado `get_health_summary()` y `print_health_summary()` para derivar salud desde manifests, estado y quality gates.
- `PROJECT.md`: Actualizada sección `## Current readiness` para reflejar WP-2026-033 completado.
- `STATE.md`: Actualizado estado a READY_FOR_REVIEW tras implementación.

### Verified

- `ruff check` en archivos tocados: PASSED
- `python scripts/run_pytest_safe.py`: PASSED
- `python .agent/agent_controller.py --health`: Funciona correctamente
- `python .agent/agent_controller.py --validate --json --force`: PASSED sin drift

# 2026-05-12 - WP-2026-032 closeout and WP-2026-033 kickoff

### Changed

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md` and `PROJECT.md` were updated to close `WP-2026-032` and activate `WP-2026-033`.
- `WP-2026-033` is now the active cycle for a health dashboard derived from manifests.

### Verified

- `python .agent/agent_controller.py --validate --json --force` passes without drift after the handoff.


# 2026-05-12 - WP-2026-030 closeout and WP-2026-032 kickoff

### Changed

- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md` and `PROJECT.md` were updated to close `WP-2026-030` and activate `WP-2026-032`.
- `WP-2026-032` is now the active cycle for freshness documentation and release closeout prep.

### Verified

- `python .agent/agent_controller.py --validate --json --force` passes without drift after the handoff.


# 2026-05-11 - WP-2026-028 Matriz mínima de roles y arranque terminal-driven

### Added

- `PROJECT.md`: Nueva sección `## Roles Matrix` que documenta:
  - Builder, Manager y Supervisor como roles canónicos con su frontera de autoridad.
  - Council como mecanismo de `WP-2026-021`, no como rol nuevo.
  - Auditor y Release explícitamente fuera de alcance.
  - Arranque terminal-driven alineado con `QUICKSTART.md`, `INTERACTION_MODES.md`, `TURN.md` y `STATE.md`.

### Changed

- `PROJECT.md`: Actualizada sección `## Current readiness` para reflejar BUILDER / IMPLEMENT como turno activo con WP-2026-028.
- `STATE.md`: Alineado al arranque del ciclo activo.
- `execution_log.md`: Registrada evidencia de implementación del ticket documental.

### Verified

- `ruff` pasó en archivos tocados.
- `pytest` sin regresiones.
- Validación del controller sin drift.
- Consistencia entre `PROJECT.md`, `STATE.md`, `TURN.md` y `work_plan.md`.

# 2026-05-11 - Cleanup infrastructure audit correction

### Changed

- `scripts/cleanup_legacy.py` was hardened to perform real cleanup in `--confirm`, archive `UPGRADE_GUIDE.md`, and skip `.venv`, `.git`, `node_modules` and `tests/sandbox`.
- `tests/conftest.py` now overrides `tmp_path` and `tmp_path_factory` to keep pytest temp activity inside the project runtime on Windows.
- `tests/README.md` now documents `python scripts/run_pytest_safe.py` as the official Windows runner.
- `tests/unit/test_cleanup_legacy.py` and `tests/unit/test_windows_safe_temp_runtime.py` exist and pass, so the previous audit claim about missing tests was inaccurate.
- `UPGRADE_CLEANUP_GUIDE.md` was updated with the corrected audit summary and cleanup policy.

# 2026-05-11 - v9.5 terminal-driven closeout

### Changed

- `README.md`, `PROJECT.md`, `project.md`, `AGENTS.md` and `CLAUDE.md` were aligned to mark the template as copy-ready for the next project.
- `pyproject.toml` and `.agent/.version_manifest.json` were bumped to `v9.5` / `v9.5.0+` to match the terminal-driven closeout.
- Version detection and upgrade helpers were aligned to recognize `v9.5` as the latest portable template release.

# 2026-05-11 - WP-2026-027 closeout

### Changed

- `supervisor.py` now normalizes the execution log status per ticket and closes `WP-2026-027` cleanly.
- `work_plan.md`, `execution_log.md`, `TURN.md`, `STATE.md`, `PROJECT.md` y `notifications.md` were updated to mark `WP-2026-027` as completed and return the turn to planning.
- `WP-2026-026` remains paused until the next planning cycle.

# 2026-05-11 - WP-2026-027 terminal-driven kickoff

### Changed

- `work_plan.md`, `TURN.md`, `execution_log.md`, `notifications.md`, `STATE.md` y `PROJECT.md` se alinearon para arrancar `WP-2026-027` como ticket activo.
- `WP-2026-026` quedo en pausa hasta estabilizar la recuperacion y reconciliacion del supervisor.

## 2026-05-11 - Codex review bridge for terminal-driven mode

### Added

- `scripts/codex_review_bridge.py` to launch Codex CLI reviews automatically when a ticket reaches `READY_FOR_REVIEW`.
- `INTERACTION_MODES.md` now documents the review bridge command for terminal-driven workflows.
- `STATE.md` was aligned to the active sequential flow.

## 2026-05-11 - Interaction Modes guide

### Added

- `INTERACTION_MODES.md` documenting chat-driven and terminal-driven workflows.
- Entry-point references in `AGENTS.md`, `CLAUDE.md`, `PROJECT.md` and `README.md`.

## 2026-05-11 - WP-2026-021 Council Broker MVP closeout

### Added

- Event-driven council broker under `.agent/council/`.
- Deterministic peer review flow with `repair_budget` and `human_gate`.
- JSONL event log and derived council state for machine coordination.

### Changed

- `agent_controller.py` now hands off to the broker only when a ticket is ready.
- Tests for the council scope were cleaned and made reproducible.
- Documentation was harmonized for a copy-ready portable template.

### Verified

- `ruff` passed on the council scope and tests.
- `python scripts/run_pytest_safe.py tests/test_council_broker.py tests/test_audit_rules.py -q` passed.
- `pyproject.toml` parsed cleanly after BOM removal.

## 2026-05-07 - Strict sync and semantic validation

### Changed

- Strict sync became the default for template maintenance.
- Hook configuration validation was tightened.
- Legacy sync naming was documented as compatibility only.

## 2026-05-06 - Memory integration and portable closeout

### Added

- Persistent project memory under `.agent/runtime/memory/`.
- `tools/scripts/memory_manager.py` for append, regenerate and read operations.

### Changed

- The template version contract was documented across the main docs.
- Canonical and legacy command families were separated in the guides.

### Verified

- Memory helpers and memory tests passed.
- `ruff` and `pip-audit` stayed clean on the touched scope.
# 2026-05-12 - WP-2026-037 startup hygiene and clean launch

### Added

- `WP-2026-037` prepared to formalize startup hygiene: preflight alignment check, stale bridge cursor cleanup and clean launch instructions.
- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md` and `notifications.md` updated to move the turn back to Builder for the new ticket.
- `PROJECT.md` and `QUICKSTART.md` updated so Builder prompts and startup instructions point at `WP-2026-037`.

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED

# 2026-05-12 - WP-2026-034 review handoff and launcher alignment

### Added

- `TURN.md`, `STATE.md` and `execution_log.md` now align `WP-2026-034` to `READY_FOR_REVIEW` for Manager review.
- `PROJECT.md` and `QUICKSTART.md` now point Builder prompts back to the canonical `WP-2026-034` smoke test.
- The launcher preflight remains in place: it checks alignment and clears stale bridge cursors before opening windows.

### Verified

- `python .agent/agent_controller.py --validate --json --force`: PASSED

# 2026-05-12 - WP-2026-036 Launcher auto-start para Builder

### Added

- `scripts/launch_agent_terminals.ps1`: Nueva función `Get-ActiveRole()` que lee `TURN.md` para determinar el rol activo.
- `scripts/launch_agent_terminals.ps1`: Nueva función `Is-BuilderRunning()` que verifica si Kilo ya está ejecutándose para evitar sesiones duplicadas.
- `scripts/launch_agent_terminals.ps1`: Lógica condicional que solo lanza Builder cuando el rol activo es `BUILDER` y no hay una sesión existente.
# 2026-05-13 - Version metadata aligned to v9.5.0

### Added

- `.agent/project_manifest.toml`: canonical project manifest materialized for manifest-first detection
- `.agent/.version_manifest.json`: technical version manifest synchronized with `pyproject.toml`

### Changed

- `project.md`, `orquestacion_agentes/PROJECT.md`, `orquestacion_agentes/README.md`, `orquestacion_agentes/AGENTS.md`: version labels updated to `v9.5.0`
- `agent_system/scripts/project_paths.py`: resolver now recognizes manifest-only `.agent/` trees as canonical project roots

### Verified

- `python orquestacion_agentes/scripts/detect_version.py orquestacion_agentes`: PASSED (manifest-first detection)
- `python orquestacion_agentes/scripts/detect_agent_system_version.py orquestacion_agentes`: PASSED (legacy alias)
- `python -m pytest orquestacion_agentes/tests/test_project_paths.py orquestacion_agentes/tests/unit/test_detect_version.py orquestacion_agentes/tests/test_manifest_validator.py -q`: 38 passed
