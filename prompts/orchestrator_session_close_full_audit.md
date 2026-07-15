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

3.ter CABLEADO DE LOS HOOKS (barrera, no norma). Los hooks son el fallo mas repetido de este repo: se rompen a menudo y en silencio. Un guard que nadie invoca es una NORMA, no una barrera (WOT-2026-024u). Ejecuta y AUDITA la salida, no el relato.
   **DESDE DONDE (obligatorio, medido 2026-07-15):** corre estos guards desde `_dev`, el checkout donde se COMMITEA. `check_guard_wiring` resuelve su motor desde `__file__`, asi que la copia del `principal` audita el CODIGO DEL PRINCIPAL: si el principal esta stale -- que es su estado NORMAL entre syncs -- devuelve `rc=0` sobre codigo viejo, un verde que NO aplica a HEAD. Mismo patron que el link stale de 3.quater: no falla, acierta con datos caducados. Verifica antes: `git -C <_dev> rev-parse HEAD` == el HEAD que estas cerrando.
   Todos los comandos de 3.ter/3.quater se corren con cwd=`<repo_motor>` (`_dev`) y con `<repo_motor>\.venv\Scripts\python.exe`; nunca con el `python` del PATH (conviven 3 interpretes: PATH 3.12, venv 3.10, y `uv run python` que es lo que declara el pre-commit).
   - `<repo_motor>\.venv\Scripts\python.exe scripts/check_guard_wiring.py` -> exit 0 obligatorio. Reporta `wired/unwired/UNDECLARED/stale`. Un guard UNDECLARED o una declaracion STALE BLOQUEAN el cierre (mecanizado: `return 1` en el propio script -- esta norma SI tiene barrera).
   - `<repo_motor>\.venv\Scripts\python.exe scripts/check_hook_interpreter.py --hooks-dir "$(git rev-parse --path-format=absolute --git-common-dir)/hooks"` (stage manual DELIBERADO: un hook automatico seria circular -- el hook roto no puede invocar al check que detecta que esta roto). Por eso en el cierre se corre A MANO: es su unico call-site real.
     **`--hooks-dir` NO es opcional (medido 2026-07-15).** El script resuelve `ROOT` por `__file__` y hace un join LITERAL `repo_root/.git/hooks` (`check_hook_interpreter.py:28,111-113`). En un WORKTREE (`_dev`) `.git` es un FICHERO gitlink: `_dev/.git/hooks` NO existe, los dos hooks salen `present=False`, y el script **imprime PASS y sale 0 sin haber mirado nada**. Es FAIL-OPEN sobre el conjunto vacio (mismo patron que `guard-subconjunto-conjunto-vacio`).
     **CRITERIO DE ACEPTACION (exit 0 NO basta):** la salida debe terminar en `(pre-commit, pre-push)`. Si dice `(none present)`, el check NO verifico nada -> trata el cierre como ROJO y corrige el `--hooks-dir`. Los dos casos dan exit 0; el UNICO discriminante es ese parentesis: LEELO Y CITALO en el reporte.
     Follow-up estructural (no lo arregles aqui): que `_default_hooks_dir` use `git rev-parse --git-path hooks`, y que `none present` sea exit 1 en un repo con `.pre-commit-config.yaml`. Registralo en el Bloque 5.
   - Comprueba que los hooks del repo REAL existen (`pre-commit`, `pre-push`). OJO topologia: en un worktree los hooks viven en el `<common-git-dir>/hooks` del checkout PRINCIPAL, no en el del `_dev` (verificado: `git rev-parse --git-path hooks` -> `<principal>/.git/hooks`; `core.hooksPath` sin definir).
   - **LIMITE CONOCIDO (leer antes de fiarse del veredicto):** `check_guard_wiring` es fiable en la ruta CONFIG (pre-commit `entry:`, workflow `run:`, settings `command`: parseo estructural). Su ruta PYTHON-SINK puede SOBRE-DECLARAR (falso-WIRED): ver el docstring del modulo y los **6** casos `should_wire_override` del corpus (`tests/fixtures/guard_wiring_corpus.yaml`). **CUATRO** son los agujeros ABIERTOS que cierra `WOT-2026-025c` y desapareceran con el rediseno. **Los otros dos NO:** `isolated_pathtoken_in_echo` es un RESIDUAL DECLARADO que SOBREVIVE a 025c (cerrarlo exigiria la lista negra que la auditoria hermana prohibio); `dash_m_as_separate_list_element` es `override: false` (limite fail-closed, no sobre-declaracion). Si un guard sale WIRED y no ves su call-site, VERIFICALO A MANO. No conviertas su verde en un veredicto que no da.

3.quater PORTABILIDAD DEL MOTOR (el motor debe ser AGNOSTICO del destino). Regla escrita que el propio motor ha incumplido en lo que distribuye (WOT-2026-024z): una norma no es un mecanismo. Verifica con probes, no leyendo:
   - Ningun fichero de `MANIFEST.distribute` puede hardcodear el nombre/ruta de un workspace, de un destino, NI del propio checkout del motor. Dentro de los prompts la ruta se cita SIEMPRE como `<workspace_activo>` / `<repo_motor>`, resueltos por `AGENT_PROJECT_ROOT` o `motor_destination_link.json` (`runtime/motor_link.py`).
   - Probe (denominador CERRADO y agujas COMPLETAS -- las dos cosas, o no mide la regla):
     - DENOMINADOR: expande cada entrada de `MANIFEST.distribute`; las entradas de DIRECTORIO (hoy `skills/`, +96 ficheros) NO se saltan, se recorren. Filtra por `git ls-files` (solo lo VERSIONADO viaja). Emite el conteo: `N entradas -> M ficheros versionados auditados`. **Un probe que no publica su denominador no cuenta** (es el defecto de 024c: saltar en silencio y decir ERROR=0).
     - AGUJAS (todas, no solo la 1a): nombre del workspace activo, nombre del checkout `_dev`, nombre del `principal`, `C:\Users`/`C:/Users`, y el username del operador. **0 hits obligatorio en TODAS.**
     - DEFECTO CONOCIDO ABIERTO (medido 2026-07-15, no lo redescubras): `prompts/orchestrator_session_bootstrap.md` (`MANIFEST.distribute:53`) hardcodea `orquestador_de_agentes_dev` en las lineas 51, 55 y 102. La version anterior de este probe (aguja UNICA = nombre del workspace) daba **0 hits y VERDE sobre esta violacion viva**: asi se cerro 024z con un verde que no gano. Si sigue ahi, reportalo y registra follow-up; no lo arregles en el cierre.
   - OJO TOPOLOGIA (medido 2026-07-15; la version anterior de esta linea era FALSA y se corrigio en la misma sesion): `motor_destination_link.json` es un fichero **UNTRACKED, machine-specific, de runtime** -- no es un artefacto versionado del motor. Estado real medido en esta maquina:
     - `_dev` (donde se COMMITEA): **no existe**.
     - `principal` (que TAMBIEN es un checkout del motor): **existe**, pero STALE (`motor_version v9.14.1`, creado 2026-05-30, con `motor_root` apuntando al PROPIO principal).
     - `workspace`: existe y es el fresco (`v9.17.1`, `motor_root` -> `_dev`).
     Consecuencia OPERATIVA (no cosmetica): "leer el link desde `repo_motor`" NO falla de forma ruidosa -- desde el `principal` **acierta con datos de hace seis semanas**. Una respuesta silenciosamente equivocada es peor que un FileNotFoundError. Resuelve SIEMPRE por `AGENT_PROJECT_ROOT` primero; si usas el link, usa el del **workspace activo** y COMPRUEBA su frescura (`motor_root` debe apuntar al checkout donde de verdad se commitea).
   - El motor no versiona artefactos de sesion ni output de auditorias (WOT-2026-024y). Probe (no es opinion): `git ls-files destinos/ .agent/runtime/reviews/ .agent/runtime/audit/` -> **0 lineas obligatorio**. Trackeado == publicado.
     DEFECTO CONOCIDO ABIERTO (medido 2026-07-15): `destinos/pii-path-audit/INVENTARIO_PII_RUTAS.md` sigue trackeado (commit `a8d2f77`, WOT-2026-020u). Este probe sale ROJO hoy: reportalo como VIOLACION VIVA con su ticket, NO lo arregles en el cierre y NO lo declares VERIFICADO.
   - Topologia real (medido 2026-07-15 con `git worktree list` + `git remote get-url origin`): **DOS worktrees de UN repo, mas UN repo SEPARADO**. No son "3 worktrees" -- la version anterior de esta linea era FALSA.
     - `_dev` -> worktree en `main`, aqui se commitea. Su `.git` es un FICHERO gitlink.
     - `principal` -> worktree DETACHED (solo consumo; un commit ahi cuelga de ningun branch). Es el checkout que POSEE el `<common-git-dir>`: los hooks de AMBOS worktrees viven en `<principal>/.git/hooks`.
     - `workspace` -> **repositorio INDEPENDIENTE** (origin `orquestador-de-agentes-workspace.git`, distinto del motor), con su propio `.git`, su propio `main` y su propio HEAD. NO comparte common-git-dir: sus hooks son suyos (medido: vacios). `sync_principal.py` NO lo gobierna.
     El `principal` STALE frente a `origin/main` es NORMAL entre syncs: se sincroniza con `sync_principal.py`, su primera barrera. NO lo "arregles" poniendolo en una rama. Pero OJO: un guard corrido DESDE el principal stale audita codigo viejo (ver 3.ter).
   - Reporta cada punto como VERIFICADO (con el comando) o NO VERIFICADO. Un hardcode en un fichero que VIAJA es bloqueante: contamina a todos los destinos.

3.quinquies OPTIMIZACION DE SUITE (opcional, solo si la evidencia lo pide). NO es parte del cierre obligatorio: es una capacidad que el cierre PUEDE disparar cuando la telemetria justifica el gasto.
   - Disparador (MEDIBLE, no "por si acaso"). Umbral CANONICO -- si lo cambias, cambialo AQUI: **duracion de `--level all` > 300 s**. Fuente: `<repo_motor>/.agent/runtime/pytest-safe/run_history.jsonl`, campo `duration_s` de la ultima linea con `"level": "all"` y `"status": "finished"`. Dispara si se cumple CUALQUIERA:
     (a) `duration_s` de esta sesion > 300 s;
     (b) tendencia: la mediana de `duration_s` de las 5 corridas `level=all` mas recientes supera en >20% la de las 5 anteriores;
     (c) el mismo `nodeid` aparece en `top_slowest` en >=3 de las 5 ultimas corridas.
     Los tres se computan del MISMO fichero; CITA el numero que obtuviste. (La version anterior decia "supera el presupuesto de tiempo acordado" -- un umbral que NO existe en ningun sitio del repo: era una norma sin mecanismo que obligaba a emitir un verde infalsable.)
   - OJO ROOT (medido 2026-07-15): `run_history.jsonl` existe en `<repo_motor>` (`_dev`) pero **NO** en el workspace (solo `last-run.json`/`.log`). Si el repo cuya suite auditas no tiene `run_history.jsonl`, el disparador es **NO VERIFICABLE**: dilo asi, no lo declares "dentro de presupuesto".
   - Si dispara: `prompts/suite_optimization.md` (contract_id cid-suite-optimization-v1). Es RECOLECTOR -> JUEZ: lee `run_history.jsonl` + la tabla de durations; NUNCA optimices desde la intuicion ni desde la atribucion de pytest (TRAMPA-1 del prompt: la atribucion MIENTE con teardown session-scoped).
   - Non-goals que el cierre debe hacer respetar: NUNCA mock-drift, NUNCA relajar asserts, NUNCA tocar barreras git reales. Un piloto exige before/after medido y guard; sin las DOS condiciones duras del PASO 2, no se aplica.
   - Si NO dispara: dilo con los NUMEROS reales (`suite <N>s < 300s; tendencia <+X%>; sin nodeid recurrente`), no con la formula vacia. Si no puedes computarlos: `disparador NO VERIFICABLE: <razon>`.

3.sexies REGISTRO DE FOLLOW-UPS DEL MOTOR -- SE EJECUTA AL FINAL DEL BLOQUE 1 (recoge los follow-ups que generan 3.ter/3.quater/3.quinquies; por eso va la ultima, pese a que antes se llamaba `3.bis` -- el ordinal mentia sobre su posicion). (cierra el agujero: los follow-ups que proponen 1-3 NO pueden quedarse en el chat ni en la memoria de sesion; se persisten como tickets candidatos en el backlog del WORKSPACE de desarrollo del motor para que puedan desarrollarse despues). El motor (`repo_motor`) debe permanecer agnostico/portable: NUNCA se escribe un follow-up en `repo_motor` (ver `prompts/audit_portability_legacy_surface.md`). El destino del registro es el repo_destino del motor = su workspace de dogfooding.
   - **Gate de evidencia (mismo umbral que el Bloque 4 para memoria):** un follow-up SOLO se registra si tiene evidencia verificable (SHA/diff/exit-code/cita de prompt/evento de bus). Sin evidencia -> se descarta o se degrada a observacion; no se infla el backlog con "seria bueno revisar X" especulativo.
   - **Resolucion del workspace (portable, CON MECANISMO -- no basta con prohibir el atajo):** resolver `<destination_root>` en este orden, y CITAR cual gano:
     (1) `AGENT_PROJECT_ROOT` si esta definido y `Test-Path` da true. Medido 2026-07-15: en esta maquina esta VACIO por defecto -- no cuentes con el.
     (2) El `--project-root` con el que YA se invoca `agent_controller.py --session-close` en el Bloque 3: es el mismo `<repo_destino>`. Reutilizalo -- es la fuente que el cierre ya usa y que el operador ya tuvo que dar.
     (3) El `motor_destination_link.json` del workspace de (2), campo `destination_root`, SOLO para verificar coherencia (debe coincidir con (2)).
     (4) Si (1) y (2) fallan: DETENERSE y pedir el workspace. NO adivinar una ruta literal.
     (La version anterior decia "(2) el link del workspace activo" -- CIRCULAR: `<workspace>` es justo la incognita que se resuelve. Sin (2)-el-flag, todo cierre caia al DETENERSE, o el agente hardcodeaba en silencio.)
     - **NO leas el link desde `repo_motor`** (regla corregida 2026-07-15, medida): el link es UNTRACKED y machine-specific. En `_dev` no existe; en el `principal` existe pero STALE (v9.14.1, de hace seis semanas, con `motor_root` apuntando al propio principal). Leerlo desde `repo_motor` NO falla de forma ruidosa: **acierta con datos caducados**. Detalle de la topologia real en 3.quater.
     - Tras resolver, VERIFICA la frescura: `motor_root` del link debe apuntar al checkout donde de verdad se commitea (`_dev`), no al principal. Si apunta a otro sitio, el link esta stale: no lo uses, reporta.
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
- `backlog.md` del workspace del motor (`<destination_root>/.agent/collaboration/backlog.md`): lo prepara el Bloque 1.3.sexies y lo escribe el Bloque 5 (post-cierre verde) (follow-ups del motor con evidencia). Un follow-up-ticket NO es una entrada de memoria: registralo SOLO en el backlog, no lo dupliques en `observations.jsonl`/`UPSTREAM_LEARNINGS.md`. La memoria documenta el aprendizaje; el backlog agenda el trabajo. El cierre del destino escribe el archivo pero NO commitea el `.git` del workspace.

== BLOQUE 5: REGISTRO DIFERIDO DE FOLLOW-UPS (post-cierre verde) ==
8. Con `--session-close` en verde y el arbol limpio, materializa los follow-ups PREPARADOS en 1.3.sexies: escribe fila Vista rapida + ficha en `backlog.md`, corre `check_backlog_contract.py`, reporta `[REGISTRADO en <ruta>:<ticket>]`. NO commitees. Registrar follow-ups nunca debe poder bloquear el cierre que los origino.

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
