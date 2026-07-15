# Prompt: Auditoria Adversarial de Cierre de Sesion

contract_id: cid-session-close-full-audit-v0
Skill canonica: skills/session-close-full-audit/SKILL.md

## Que es y que NO es

Pasada de auditoria adversarial que precede al cierre canonico de una sesion.
Encadena las tres auditorias estructurales de salud del sistema, anade una
pasada adversarial sobre el CODIGO GENERADO en la sesion (el paso que el flujo
de cierre anterior omitia), y solo entonces deja proceder al cierre operativo y
a la promocion de memoria.

NO reimplementa la logica de las skills que orquesta. Es un wrapper contextual:
- la salud del sistema la posee `skills/system-health-audit/SKILL.md`;
- el cierre operativo lo posee `skills/manager-session-closeout/SKILL.md` +
  `prompts/orchestrator_session_close_chat.md` (comando canonico
  `agent_controller.py --session-close`);
- la promocion de memoria la gobierna `prompts/memory_upload.md`.

El contrato del auditor lo gobierna integramente `prompts/audit_agent_output.md`
(CEM v0, evidencia antes que relato, doble pasada, frontera del auditor); este
prompt NO lo reproduce, solo lo aplica al cierre de sesion. MODO read-only por
defecto: audita y propone el cambio minimo; no parchea salvo instruccion explicita.

Distincion con skills hermanas:
- `system-health-audit` = salud de las 3 capas (es el Bloque 1 de esta pasada).
- `audit-pipeline` = meta-auditoria post-pipeline TRANSVERSAL del backlog completo (TODOS los tickets cerrados, no uno solo).
- `audit_agent_output` = auditoria esceptica generica de output (es la
  herramienta del Bloque 2; aqui se aplica a los diffs de la sesion).
- esta pasada = orquesta las anteriores + cierre + memoria en un cierre de sesion.

---

## Prompt

```text
Auditas el cierre de esta sesion como AUDITOR adversarial, no como narrador.

CONTRATO: rige `prompts/audit_agent_output.md` (CEM v0) en su totalidad; no se reproduce aqui. En una frase operativa: evidencia antes que relato (ningun auto-reporte cuenta; solo diff/exit-code/test/bus/SHA/bytes/git), etiqueta cada hallazgo VERIFICADO/INFERIDO/NO VERIFICADO, y responde con conclusiones + evidencia citada, no con volcados de archivos. Para los detalles del contrato (frontera del auditor, verificacion topologica, checklist esceptico, clasificacion CEM) lee el prompt fuente; no los repitas en tu reporte.

REGLA DE PARADA (especifica de esta pasada de cierre): si cualquier gate sale en rojo, o si un hallazgo contradice una afirmacion previa del Builder/Manager, DETENTE. No avances a la promocion de memoria. Surfacea la contradiccion explicitamente (claim original vs evidencia real) en vez de taparla. La memoria solo se promociona sobre una sesion verde y reconciliada.

Ejecuta en este orden y reporta por bloque:

== BLOQUE 1: AUDITORIA DE SALUD DEL SISTEMA (3 auditorias estructurales) ==
1. `prompts/audit_post_change_system_health.md` (contract_id cid-system-health-audit-v0). Recolector determinista primero: `python scripts/collect_system_health.py --motor-root <repo_motor> --project-root <repo_destino> --mode auto`. El script RECOLECTA (testigo read-only); TU AUDITAS (aplicas juicio). Su Fase 8 (pasada adversarial) invoca `prompts/audit_agent_output.md` sobre la salida del recolector: hazla explicita, no implicita.
2. `prompts/audit_complete_motor_destination.md`. Analisis estrategico read-only de arquitectura/portabilidad/loop Builder-Manager. NO muta el arbol; produce blueprint de tickets para DESPUES, no acciones ahora.
3. `prompts/audit_portability_legacy_surface.md`. Inventario read-only de stubs legacy y candidatos a extraer/retirar; propone follow-ups pequenos.

3.ter CABLEADO DE LOS HOOKS (barrera, no norma). Los hooks son el fallo mas repetido de este repo: se rompen a menudo y en silencio. Un guard que nadie invoca es una NORMA, no una barrera (WOT-2026-024u). Ejecuta y AUDITA la salida, no el relato:
   - `python scripts/check_guard_wiring.py` -> exit 0 obligatorio. Reporta `wired/unwired/UNDECLARED/stale`. Un guard UNDECLARED o una declaracion STALE BLOQUEAN el cierre.
   - `python scripts/check_hook_interpreter.py` (stage manual DELIBERADO: un hook automatico seria circular -- el hook roto no puede invocar al check que detecta que esta roto). Por eso en el cierre se corre A MANO: es su unico call-site real.
   - Comprueba que los hooks del `.git/hooks` del repo REAL existen (`pre-commit`, `pre-push`). OJO topologia: en un worktree los hooks viven en el `<common-git-dir>/hooks` del checkout PRINCIPAL, no en el del `_dev`.
   - **LIMITE CONOCIDO (leer antes de fiarse del veredicto):** `check_guard_wiring` es fiable en la ruta CONFIG (pre-commit `entry:`, workflow `run:`, settings `command`: parseo estructural). Su ruta PYTHON-SINK puede SOBRE-DECLARAR (falso-WIRED): ver el docstring del modulo y los casos `should_wire_override` del corpus, todos con ticket `WOT-2026-025c`. Si un guard sale WIRED y no ves su call-site, VERIFICALO A MANO. No conviertas su verde en un veredicto que no da.

3.quater PORTABILIDAD DEL MOTOR (el motor debe ser AGNOSTICO del destino). Regla escrita que el propio motor ha incumplido en lo que distribuye (WOT-2026-024z): una norma no es un mecanismo. Verifica con probes, no leyendo:
   - Ningun fichero de `MANIFEST.distribute` puede hardcodear el nombre/ruta de un workspace o destino concreto. Probe: por cada entrada de `MANIFEST.distribute` que sea un fichero, grep del nombre del workspace; **0 hits obligatorio**. Dentro de los prompts, la ruta se cita SIEMPRE como `<workspace_activo>` / `<repo_motor>`, resueltos por `AGENT_PROJECT_ROOT` o `motor_destination_link.json` (`runtime/motor_link.py`).
   - OJO TOPOLOGIA (verificado 2026-07-15, no lo supongas al reves): `motor_destination_link.json` vive en el `.agent/config/` del **WORKSPACE/destino**, apuntando al motor (`motor_root`) -- NO en el motor. El motor no sabe quienes son sus destinos: por eso es agnostico. Un probe que lo busque en `repo_motor/.agent/config/` falla con FileNotFoundError.
   - El motor no versiona artefactos de sesion ni output de auditorias (WOT-2026-024y): un `destinos/<algo>/` trackeado con el informe de una sesion es basura de runtime en el repo publico.
   - Topologia de los 3 worktrees: `_dev` en `main` (aqui se commitea), `principal` DETACHED (solo consumo; un commit ahi cuelga de ningun branch), workspace en `main`. El `principal` STALE frente a `origin/main` es NORMAL: se sincroniza con `sync_principal.py`, que es su primera barrera. NO lo "arregles" poniendolo en una rama.
   - Reporta cada punto como VERIFICADO (con el comando) o NO VERIFICADO. Un hardcode en un fichero que VIAJA es bloqueante: contamina a todos los destinos.

3.quinquies OPTIMIZACION DE SUITE (opcional, solo si la evidencia lo pide). NO es parte del cierre obligatorio: es una capacidad que el cierre PUEDE disparar cuando la telemetria justifica el gasto.
   - Disparador (no lo lances "por si acaso"): la suite canonica de esta sesion supera el presupuesto de tiempo acordado, O `run_history.jsonl` muestra una tendencia al alza sostenida, O el mismo test aparece repetidamente en el top-slowest de `--durations=25`.
   - Si dispara: `prompts/suite_optimization.md` (contract_id cid-suite-optimization-v1). Es RECOLECTOR -> JUEZ: lee `.agent/runtime/pytest-safe/run_history.jsonl` + la tabla de durations; NUNCA optimices desde la intuicion ni desde la atribucion de pytest (TRAMPA-1 del prompt: la atribucion MIENTE con teardown session-scoped).
   - Non-goals que el cierre debe hacer respetar: NUNCA mock-drift, NUNCA relajar asserts, NUNCA tocar barreras git reales. Un piloto exige before/after medido y guard; sin las DOS condiciones duras del PASO 2, no se aplica.
   - Si NO dispara: dilo explicitamente (`suite dentro de presupuesto: <N>s, sin tendencia`), no lo omitas en silencio.

3.bis REGISTRO DE FOLLOW-UPS DEL MOTOR (cierra el agujero: los follow-ups que proponen 1-3 NO pueden quedarse en el chat ni en la memoria de sesion; se persisten como tickets candidatos en el backlog del WORKSPACE de desarrollo del motor para que puedan desarrollarse despues). El motor (`repo_motor`) debe permanecer agnostico/portable: NUNCA se escribe un follow-up en `repo_motor` (ver `prompts/audit_portability_legacy_surface.md`). El destino del registro es el repo_destino del motor = su workspace de dogfooding.
   - **Gate de evidencia (mismo umbral que el Bloque 4 para memoria):** un follow-up SOLO se registra si tiene evidencia verificable (SHA/diff/exit-code/cita de prompt/evento de bus). Sin evidencia -> se descarta o se degrada a observacion; no se infla el backlog con "seria bueno revisar X" especulativo.
   - **Resolucion del workspace (portable, no hardcodear ruta):** leer `repo_motor/.agent/config/motor_destination_link.json` -> campo `destination_root`. Ese es el workspace de desarrollo del motor (su repo_destino de dogfooding). NO asumir una ruta literal.
   - **Gate de presencia (barrera, no friccion):** verificar `Test-Path <destination_root>` (o `test -f` del `backlog.md`) ANTES de escribir.
     - Si el workspace ESTA en el espacio de trabajo: escribir cada follow-up con evidencia en `<destination_root>/.agent/collaboration/backlog.md` -> (a) una fila en la tabla `Vista rapida` y (b) una ficha detallada. Campos minimos: `Ticket` (prefijo `WOT-`, siguiente id libre), `Estado: pending`, `delivery_authority: repo_motor`, `Origen: session-<fecha>-<slug>`, `Reactivation: -`, y el criterio binario de aceptacion + la evidencia que lo origino. Respetar el contrato de cola viva del propio `backlog.md` (estados permitidos, columna Reactivation).
     - Si el workspace NO esta montado: DETENERSE y SOLICITAR al usuario que abra/monte el repo de desarrollo del motor (`destination_root`). NO escribir el follow-up en `repo_motor`, NI en el repo_destino de ESTA sesion, NI dejarlo solo en memoria. Emitir la ficha pegable como fallback explicito y marcar el registro como PENDIENTE.
   - Regla unica de no-bloqueo del cierre (X-01/E4): durante el Bloque 1 NO escribas el follow-up
     en disco. PREPARA cada ficha en borrador. La escritura real a
     `<destination_root>/.agent/collaboration/backlog.md` ocurre en el Bloque 5 (post-cierre), DESPUES
     de que `--session-close` termine en verde. Motivo verificado en vivo (E4): el Bloque 3 corre
     `prepush_check --closeout-mode` -> `check_git_tree_clean`, cuya allowlist
     `EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS` (4 entradas, NO incluye `backlog.md`, match por substring)
     deja el arbol sucio y BLOQUEA el cierre (exit 1). NO se arregla ampliando la allowlist; se
     arregla por ORDEN.
   - **Escribe en Bloque 5, NO commitees:** cuando el cierre ya paso, escribe el backlog. Lo commitea
     el humano/Manager (contrato cola viva). El cierre NO crea commits en el `.git` del workspace.
   - Reporta: por cada follow-up, `[REGISTRADO en <ruta>:<ticket>]` o `[PENDIENTE - workspace no montado]`, con la evidencia citada.

== BLOQUE 2: PASADA ADVERSARIAL SOBRE EL CODIGO GENERADO ESTA SESION (el paso que faltaba) ==
Esta es la barrera critica que el flujo anterior omitia: la salida del Builder nunca se validaba con escepticismo antes de cristalizar aprendizajes.

4. Aplica `prompts/audit_agent_output.md` (su checklist esceptico y clasificacion CEM completos) SOBRE LOS DIFFS DE ESTA SESION, no sobre codigo generico. MODO: solo lectura e inspeccion, NO implementacion. Encuadre especifico para el cierre (el resto lo da el prompt fuente):
   - Encuadre: los "diffs" son los commits productivos de ESTA sesion. Enumeralos con `git log` / `git diff --stat` (cwd=repo_motor). Cita SHAs y rutas reales.
   - Mira especialmente: false-green, root equivocado, fixture drift, scope creep, mock drift, floor assertion (todos definidos en el prompt fuente).
   - Barrera mutation-verified: para cada guard/test nuevo que afirme bloquear un fallo, demuestra que FALLA sin el fix. Un guard que no se demuestra que bloquea no cuenta como barrera.
5. Herramientas de EVIDENCIA de esta pasada (no son las 3 auditorias estructurales). El auditor PROPONE hallazgos; estas skills son consumidoras que IMPLEMENTAN solo si procede y con tu OK:
   - `skills/builder-self-audit/SKILL.md`: las 3 barreras secuenciales del Builder (sintaxis por tipo via py_compile/yaml.safe_load/json.load, completitud multi-archivo, frescura documental PROJECT.md/QUICKSTART.md/TURN.md/STATE.md) deben tener evidencia de salida real, no exit code de un pipe.
   - `skills/builder-run-quality-gates/SKILL.md`: confirma que los gates corrieron via `scripts/run_gates_dispatch.py` (dispatch por deliverable_type), NO invocando ruff/pytest directo (eso evade el audit trail).
   - `skills/code-audit/SKILL.md`: si procede, vulture/deadcode/ruff son generadores de senal, no veredictos; toda categoria DEAD/ABANDONED/LEGACY/SMELL exige triangulacion manual contra git history.
   - `skills/systematic-debugging/SKILL.md`: si la sesion agoto intentos de debug, revisa `execution_log.md` por marcadores de escalado (tope de 3 intentos); un cierre sobre premisa no resuelta es bandera.
   - `prompts/manager_review.md`: confirma que la verificacion mecanica del Manager dispatcho por deliverable_type (ruff/pytest si code|mixed; validate+encoding si docs|research|analysis). Aplicar el gate equivocado invalida la review.

5.bis Triage obligatorio de hallazgos nuevos antes de memoria/backlog. Aplica
   `prompts/_shared/finding_triage_protocol.md` a cada hallazgo del Bloque 2 antes
   de convertirlo en accion:
   - mismo ticket solo si bloquea el criterio de aceptacion o es regresion del
     diff actual;
   - hotfix autonomo solo para bug preexistente que bloquea gate obligatorio,
     1-3 lineas, bajo riesgo, test aislado y sin cambio de contrato;
   - backlog/follow-up si es deuda real con evidencia pero no bloquea el
     deliverable;
   - Contract Formation/ticket nuevo si requiere cambiar contrato, FLT,
     arquitectura o superficie;
   - checkpoint humano si es seguridad/PII/remoto, irreversible o alto
     blast-radius.
   Reporta la clasificacion elegida y la evidencia. No promociones memoria ni
   registres backlog sobre hallazgos sin triage.

PUNTO DE CONTROL antes del Bloque 3: la sesion debe estar VERDE y RECONCILIADA. Si el Bloque 2 destapa un false-green o una contradiccion, vuelve al Builder; NO continues.

== BLOQUE 3: CIERRE CANONICO ==
Invariante de arbol de cierre (v3 P1 delta): antes de correr `prepush_check`/`--session-close`, NINGUN write-surface no incluido en `EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS` puede haber sido modificado por este flujo (en particular `backlog.md`). Si lo fue, es un error de ORDEN del propio flujo: difiere esa escritura al post-cierre (Bloque 5). El gate no se relaja; el flujo se reordena.

6. `prompts/orchestrator_session_close_chat.md` es el WRAPPER orquestador. NO reimplementes sus pasos en este prompt: las skills son la fuente canonica. Invoca el comando canonico unico, que ya orquesta todo el pipeline automaticamente:
   - `python .agent/agent_controller.py --session-close --dry-run --project-root <repo_destino>` (previsualiza, no muta), revisa el reporte.
   - `python .agent/agent_controller.py --session-close --project-root <repo_destino>` (ejecuta). Si `STATE.md` ya esta COMPLETED, anade `--force`.
   - El pipeline orquesta en orden: prepush_check (bloqueante), local_audit, validacion de prosa, observaciones por ticket (`session-close-observations`), consolidacion de memoria (`memory-consolidate`), limpieza de sesion, archivado de collaboration/bus/execution_log, manifest check, git clean. NO repitas estos pasos a mano; los scripts sueltos (`local_audit.py`, `session_close_observations.py`, `memory_consolidate.py --dry-run`) son solo para diagnostico puntual.
   - Learnings y changelog (decisiones humanas, fuera del pipeline automatico): `manager-session-closeout` (`skills/manager-session-closeout/SKILL.md`) clasifica learnings local/generalizable/dudoso y escribe `closeout_lessons.md`; `version-changelog` (`skills/version-changelog/SKILL.md`) propone bump SemVer (tags solo con tu OK explicito).
   - VALIDACION post-cierre obligatoria: `python .agent/agent_controller.py --validate --json --project-root <repo_destino>` debe dar `0 errors / 0 warnings`. Si aparece `bus_drift` post-archive, reconcilia con `scripts/reconcile_ticket.py --ticket <ID> --reason "post-session-close bus drift"` y revalida. NO fabriques eventos de bus a mano.
   - NO asumas un warning "esperado" de `work_plan.md` ausente tras el cierre. Re-valida siempre contra la fuente viva: si `validate --json` da `0/0`, documenta `0/0`; si aparece una warning nueva, tratala como senal real del estado presente, no como folklore del cierre anterior.
   - `TURN.md` puede quedar en `ROL=MANAGER`, `ACCION=CREATE_PLAN`, `Plan ID: N/A` inmediatamente despues del cierre. Eso NO bloquea el cierre si `validate --json` sigue en `0/0`. El siguiente bootstrap/arranque de ticket debe regenerarlo; no lo eleves a hallazgo si no rompe validacion.

== BLOQUE 4: PROMOCION DE MEMORIA (decision, no escritura ciega) ==
7. `prompts/memory_upload.md` es GATE de pre-escritura (propose-before-write), NO un volcado al final. Para CADA aprendizaje:
   - Declara el destino ANTES de escribir: Claude privada / portable motor (repo_motor) / portable destino (repo_destino) / varios.
   - Distingue OBSERVACION (hecho objetivo, lo posee session-close-observations) de LEARNING (regla generalizable con evidencia, lo posee manager-session-closeout). No los mezcles en el mismo tier.
   - Sin evidencia verificable (diff/commit/test/exit-code/evento-bus) no hay entrada portable: degrada a dudoso o descarta.
   - Gate de schema-drift: si `observations.jsonl` esta en drift, NO se admiten entradas portables nuevas. Valida contra `skills/_shared/ap-schema.md` y el consumidor real `bus/memory_loader.py`.
   - Promocion a repo_motor (engine/meta) exige confirmacion humana explicita. Las alas portables no se escriben sin aprobacion.
   - Si el Manager detecto un false-positive o fixture drift en el Bloque 2, ese "aprendizaje" NO se cristaliza como hecho: el loop de feedback lo bloquea.

PROPIEDAD DE ARTEFACTOS (quien escribe que, para evitar triple-write ciego):
- `observations.jsonl`: lo posee session-close-observations (observaciones) + manager-session-closeout (learnings locales). memory-consolidate solo dedupe/archiva; nunca lo reescribe a mano.
- `UPSTREAM_LEARNINGS.md`: lo posee manager-session-closeout (generalizables/dudosos con TTL).
- `closeout_lessons.md`: puente para el siguiente manager-create-work-plan; lo posee manager-session-closeout.
- `CHANGELOG.md` + ficheros de version: los posee version-changelog.
- `MEMORY.md`: lo regenera memory-consolidate; no se edita a mano.
- `backlog.md` del workspace del motor (`<destination_root>/.agent/collaboration/backlog.md`): lo prepara el Bloque 1.3.bis y lo escribe el Bloque 5 (post-cierre verde) (follow-ups del motor con evidencia). Un follow-up-ticket NO es una entrada de memoria: registralo SOLO en el backlog, no lo dupliques en `observations.jsonl`/`UPSTREAM_LEARNINGS.md`. La memoria documenta el aprendizaje; el backlog agenda el trabajo. El cierre del destino escribe el archivo pero NO commitea el `.git` del workspace.

== BLOQUE 5: REGISTRO DIFERIDO DE FOLLOW-UPS (post-cierre verde) ==
8. Con `--session-close` en verde y el arbol limpio, materializa los follow-ups PREPARADOS en 1.3bis: escribe fila Vista rapida + ficha en `backlog.md`, corre `check_backlog_contract.py`, reporta `[REGISTRADO en <ruta>:<ticket>]`. NO commitees. Registrar follow-ups nunca debe poder bloquear el cierre que los origino.

VALIDACION FINAL: `python .agent/agent_controller.py --validate --json --project-root <repo_destino>` -> exige `0 errors / 0 warnings`. Reporta exit code real.

Recordatorio: responde con conclusiones etiquetadas (VERIFICADO/INFERIDO/NO VERIFICADO) y evidencia citada (SHA, ruta, exit code), no con volcados de archivos. Si algo sale en rojo, DETENTE en el punto de control correspondiente y surfacea la contradiccion antes de tocar memoria.
```

---

## Cuando usarlo

- Al cerrar una sesion que toco codigo del motor o del destino, ANTES del cierre
  canonico, para auditar adversarialmente los diffs de la sesion.
- Como fase previa recomendada de `orchestrator_session_close_chat.md`.

## Cuando NO usarlo

- Durante un ticket aun en `IN_PROGRESS` (usa el cierre normal del ticket).
- Para arrancar una sesion nueva (usa `orchestrator_session_bootstrap.md`).
- Como sustituto del cierre operativo: esta pasada audita y precede; el cierre
  real lo ejecuta `agent_controller.py --session-close`.
