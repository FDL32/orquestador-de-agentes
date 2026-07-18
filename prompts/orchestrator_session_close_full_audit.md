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

### Dos modos: cierre FINAL vs mid-flight (WOT-2026-029c)

Este prompt esta escrito para el cierre FINAL de una sesion. Antes de correrlo,
DECIDE en cual de los dos modos estas -- porque el Bloque 3 (cierre canonico) es
DESTRUCTIVO del estado de continuacion y no debe ejecutarse a mitad de vuelo:

- **Cierre FINAL** (modo por defecto de este prompt): la sesion TERMINO, no queda
  ningun ticket `IN_PROGRESS` ni vuelo abierto. Flujo COMPLETO: Bloques 1->2->2.5,
  y luego el Bloque 3 corre `agent_controller.py --session-close` (archiva la
  colaboracion, resetea STATE a IDLE, rota proyecciones) + Bloque 4 (memoria) +
  Bloque 5 (backlog). El humano revisa y pushea. Es el unico modo que ejecuta el
  Bloque 3.

- **Mid-flight** (parada a mitad de vuelo, NO cierre): quieres auditar y dejar un
  handoff en un checkpoint mientras el vuelo/lote SIGUE abierto (hay tickets por
  delante o un ticket `IN_PROGRESS`). Flujo RECORTADO y read-only:
  - Corre los Bloques 1 y 2 (salud + auditoria adversarial de los diffs hasta aqui)
    y 2.5 (proceso), TODO informativo.
  - **NO corras el Bloque 3.** `--session-close` archivaria la colaboracion y
    resetearia STATE -> BORRARIA el estado de continuacion que el vuelo necesita
    para retomarse. Es el error que este modo existe para prevenir.
  - Handoff **SHA-free** (no incrustes el HEAD como estado; ver
    `scripts/check_handoff_state_sha.py` / WOT-2026-024t): el estado se VERIFICA
    contra git al retomar, no se escribe en prosa que caduca.
  - **NO push.** El humano decide cuando publicar; una parada mid-flight es local.
  - Memoria/backlog: difiere la promocion (Bloques 4/5) al cierre FINAL; en mid-flight
    solo se dejan DRAFTs con evidencia (no se materializan tickets ni memoria todavia).
  - Emite un parte de parada (que quedo hecho, que sigue pendiente, punto exacto de
    retomada) en `orchestrator_pipeline/reports/`, NO un cierre.

  Regla dura: si hay un ticket `IN_PROGRESS` o un lote abierto, estas en mid-flight
  por definicion -> Bloques 1/2/2.5 SI, Bloque 3 NO. La seccion "Cuando NO usarlo"
  de abajo (ticket `IN_PROGRESS`) se refiere al Bloque 3, no a la auditoria.

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

3.4 CABLEADO DE LOS HOOKS. Los hooks son el fallo mas repetido de este repo: se rompen a menudo y en silencio. Un guard que nadie invoca es una NORMA, no una barrera (WOT-2026-024u).
   REGLA: todos los comandos de 3.4/3.5 se corren con cwd=`<repo_motor>` (el checkout donde se COMMITEA) y con `<repo_motor>\.venv\Scripts\python.exe`. Nunca desde el `principal` (audita codigo stale: da rc=0 sobre codigo viejo) ni con el `python` del PATH. Antes de empezar: `git -C <repo_motor> rev-parse HEAD` == el HEAD que cierras.
   - `<repo_motor>\.venv\Scripts\python.exe scripts/check_guard_wiring.py` -> **exit 0 obligatorio**. UNDECLARED o stale BLOQUEAN el cierre (mecanizado: el script devuelve 1).
   - `<repo_motor>\.venv\Scripts\python.exe scripts/check_hook_interpreter.py --hooks-dir "$(git rev-parse --path-format=absolute --git-common-dir)/hooks"`
     **`--hooks-dir` NO es opcional, y `exit 0` NO basta: la salida DEBE terminar en `(pre-commit, pre-push)`.** Si dice `(none present)`, el check no miro nada y salio verde igual -> cierre ROJO, corrige el `--hooks-dir`. LEE Y CITA ese parentesis en el reporte; es el unico discriminante.
     Por que (defecto de produccion, NO lo arregles aqui): **WOT-2026-025d**. Stage manual deliberado: un hook automatico seria circular.
   - Los hooks reales viven en `<common-git-dir>/hooks` (el checkout PRINCIPAL), no en el `.git` del worktree.
   - **LIMITE del veredicto (leelo antes de fiarte):** `check_guard_wiring` es fiable en la ruta CONFIG (parseo estructural de `entry:`/`run:`/`command`). Su ruta PYTHON-SINK puede SOBRE-DECLARAR (falso-WIRED). Si un guard sale WIRED y no ves su call-site, VERIFICALO A MANO. Detalle y alcance: docstring del modulo + los casos `should_wire_override` del corpus -> **WOT-2026-025c** (ojo: no todos desaparecen con 025c; el corpus dice cual sobrevive).

3.5 PORTABILIDAD DEL MOTOR (el motor debe ser AGNOSTICO del destino). Regla escrita que el propio motor ha incumplido en lo que distribuye (WOT-2026-024z): una norma no es un mecanismo. Verifica con probes, no leyendo:
   - Ningun fichero de `MANIFEST.distribute` puede hardcodear el nombre/ruta de un workspace, de un destino, NI del propio checkout del motor. Dentro de los prompts la ruta se cita SIEMPRE como `<workspace_activo>` / `<repo_motor>`, resueltos por `AGENT_PROJECT_ROOT` o `motor_destination_link.json` (`runtime/motor_link.py`).
   - Probe (denominador CERRADO y agujas COMPLETAS -- las dos cosas, o no mide la regla):
     - DENOMINADOR: expande cada entrada de `MANIFEST.distribute`; las entradas de DIRECTORIO (hoy `skills/`, +96 ficheros) NO se saltan, se recorren. Filtra por `git ls-files` (solo lo VERSIONADO viaja). Emite el conteo: `N entradas -> M ficheros versionados auditados`. **Un probe que no publica su denominador no cuenta** (es el defecto de 024c: saltar en silencio y decir ERROR=0).
     - AGUJAS (todas, no solo la 1a): nombre del workspace activo, nombre del checkout `_dev`, nombre del `principal`, `C:\Users`/`C:/Users`, y el username del operador. **0 hits obligatorio en TODAS.**
     - **MECANISMO (WOT-2026-024z DoD(d) / 025e, cerrado 2026-07-15):** este probe ya NO se hace a mano. `scripts/check_distribution_agnostic.py` lo implementa (denominador cerrado publicado, agujas workspace/`_dev`/`C:\Users`/username con la allowlist de meta-menciones) y esta CABLEADO en `.pre-commit-config.yaml` (`id: check-distribution-agnostic`). La aguja del checkout `principal` NO se incluye: `orquestador_de_agentes` a secas es el NOMBRE CANONICO del repo (47 usos legitimos medidos), no una fuga. El hardcode que este advisory citaba (`orquestador_de_agentes_dev` en `orchestrator_session_bootstrap.md`) quedo des-hardcodeado por 025e.
   - `motor_destination_link.json` es UNTRACKED, machine-specific y de runtime -- no es un artefacto versionado. **NO lo leas desde `repo_motor`**: puede no existir (worktree de trabajo) o existir STALE (el principal lo tiene de otra epoca, apuntando a si mismo). Leerlo del sitio equivocado no falla: acierta con datos caducados. Resuelve SIEMPRE por `AGENT_PROJECT_ROOT` o por el `--project-root` del cierre; si usas el link, usa el del **workspace activo** y comprueba que su `motor_root` apunta al checkout donde de verdad se commitea.
   - El motor no versiona artefactos de sesion ni output de auditorias (**WOT-2026-024o**, que ABSORBIO a 024y el 2026-07-15: eran el mismo trabajo sobre la misma superficie). Probe: `git ls-files destinos/ .agent/runtime/reviews/ .agent/runtime/audit/` -> **0 lineas**. Trackeado == publicado.
     (WOT-2026-024o cerrado 2026-07-15, commit 2480116: `destinos/pii-path-audit/INVENTARIO_PII_RUTAS.md` -- el unico fichero bajo `destinos/` -- se movio integro al `_archive` del workspace y el directorio se retiro. Este probe ya sale VERDE.)
   - Topologia: **DOS worktrees de UN repo + UN repo SEPARADO** (no "3 worktrees"). Verificalo, no lo asumas: `git worktree list` + `git remote get-url origin`.
     - `<repo_motor>` (worktree de trabajo) -> en `main`, aqui se commitea. Su `.git` es un FICHERO gitlink.
     - `<principal>` -> worktree DETACHED (solo consumo; un commit ahi cuelga de ningun branch). Es el checkout que POSEE el `<common-git-dir>`: los hooks de AMBOS worktrees viven ahi.
     - `<workspace_activo>` -> **repositorio INDEPENDIENTE** (su propio origin, distinto del motor; su propio `.git`, `main` y HEAD). NO comparte common-git-dir: sus hooks son suyos. `sync_principal.py` NO lo gobierna.
     El `<principal>` STALE frente a `origin/main` es NORMAL entre syncs: lo sincroniza `sync_principal.py`, su primera barrera. NO lo "arregles" poniendolo en una rama. Pero OJO: un guard corrido DESDE el principal stale audita codigo viejo (ver 3.4).
   - Reporta cada punto como VERIFICADO (con el comando) o NO VERIFICADO. Un hardcode en un fichero que VIAJA es bloqueante: contamina a todos los destinos.

3.6 OPTIMIZACION DE SUITE (opcional, solo si la evidencia lo pide). NO es parte del cierre obligatorio: es una capacidad que el cierre PUEDE disparar cuando la telemetria justifica el gasto.
   - Disparador (MEDIBLE, no "por si acaso"). Umbral CANONICO -- si lo cambias, cambialo AQUI: **duracion de `--level all` > 300 s**. Fuente: `<repo_motor>/.agent/runtime/pytest-safe/run_history.jsonl`, campo `duration_s` de la ultima linea con `"level": "all"` y `"status": "finished"`. Dispara si se cumple CUALQUIERA:
     (a) `duration_s` de esta sesion > 300 s;
     (b) tendencia: la mediana de `duration_s` de las 5 corridas `level=all` mas recientes supera en >20% la de las 5 anteriores;
     (c) el mismo `nodeid` aparece en `top_slowest` en >=3 de las 5 ultimas corridas.
     Los tres se computan del MISMO fichero; CITA el numero que obtuviste.
   - OJO ROOT: `run_history.jsonl` vive en `<repo_motor>`; un destino puede no tenerlo (solo `last-run.json`). Si el repo cuya suite auditas no lo tiene, el disparador es **NO VERIFICABLE**: dilo asi, no lo declares "dentro de presupuesto".
   - Si dispara: `prompts/suite_optimization.md` (contract_id cid-suite-optimization-v1). Es RECOLECTOR -> JUEZ: lee `run_history.jsonl` + la tabla de durations; NUNCA optimices desde la intuicion ni desde la atribucion de pytest (TRAMPA-1 del prompt: la atribucion MIENTE con teardown session-scoped).
   - Non-goals que el cierre debe hacer respetar: NUNCA mock-drift, NUNCA relajar asserts, NUNCA tocar barreras git reales. Un piloto exige before/after medido y guard; sin las DOS condiciones duras del PASO 2, no se aplica.
   - Si NO dispara: dilo con los NUMEROS reales (`suite <N>s < 300s; tendencia <+X%>; sin nodeid recurrente`), no con la formula vacia. Si no puedes computarlos: `disparador NO VERIFICABLE: <razon>`.

3.7 REGISTRO DE FOLLOW-UPS DEL MOTOR -- va la ULTIMA del Bloque 1 a proposito: recoge los follow-ups que generan 3.4/3.5/3.6. (cierra el agujero: los follow-ups que proponen 1-3 NO pueden quedarse en el chat ni en la memoria de sesion; se persisten como tickets candidatos en el backlog del WORKSPACE de desarrollo del motor para que puedan desarrollarse despues). El motor (`repo_motor`) debe permanecer agnostico/portable: NUNCA se escribe un follow-up en `repo_motor` (ver `prompts/audit_portability_legacy_surface.md`). El destino del registro es el repo_destino del motor = su workspace de dogfooding.
   - **Gate de evidencia (mismo umbral que el Bloque 4 para memoria):** un follow-up SOLO se registra si tiene evidencia verificable (SHA/diff/exit-code/cita de prompt/evento de bus). Sin evidencia -> se descarta o se degrada a observacion; no se infla el backlog con "seria bueno revisar X" especulativo.
   - **Resolucion del workspace (portable, CON MECANISMO -- no basta con prohibir el atajo):** resolver `<destination_root>` en este orden, y CITAR cual gano:
     (1) `AGENT_PROJECT_ROOT` si esta definido y `Test-Path` da true. Medido 2026-07-15: en esta maquina esta VACIO por defecto -- no cuentes con el.
     (2) El `--project-root` con el que YA se invoca `agent_controller.py --session-close` en el Bloque 3: es el mismo `<repo_destino>`. Reutilizalo -- es la fuente que el cierre ya usa y que el operador ya tuvo que dar.
     (3) El `motor_destination_link.json` del workspace de (2), campo `destination_root`, SOLO para verificar coherencia (debe coincidir con (2)).
     (4) Si (1) y (2) fallan: DETENERSE y pedir el workspace. NO adivinar una ruta literal.
     - **NO leas el link desde `repo_motor`** (regla corregida 2026-07-15, medida): el link es UNTRACKED y machine-specific. En `_dev` no existe; en el `principal` existe pero STALE (v9.14.1, de hace seis semanas, con `motor_root` apuntando al propio principal). Leerlo desde `repo_motor` NO falla de forma ruidosa: **acierta con datos caducados**. Detalle de la topologia real en 3.5.
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

== BLOQUE 2.5: AUDITORIA DE ARTEFACTOS Y PROCESO DE SESION (WOT-2026-022e, ampliado 026d) ==
Audita los artefactos que los prompts generaron durante la sesion Y el PROCESO que la sesion siguio (prompts disenados, herramientas usadas, rondas de ensemble, decisiones de triage), registrados en el manifest.jsonl de la infra session-scratch (`scripts/init_session_scratch.py`, WOT-2026-022c) y cruzados con el scorecard de ensembles (2.5.i). Es INFORMATIVO: NO bloquea el cierre, con UNA sola excepcion binaria (ver 2.5.f). Su salida alimenta el Bloque 4 (memoria) y el Bloque 5 (backlog), NUNCA un tercer destino persistente. El sub-bloque 2.5.j (PROCESS IMPROVEMENT PROPOSAL) SOLO PROPONE mejoras de proceso; la escritura va por los canales existentes (Bloques 4/5).

2.5.a SKIP si vacio: si `<repo_destino>/.agent/runtime/session/` no tiene sesiones, SALTA este bloque entero (no gastes tokens en carpeta vacia) y dilo: "Bloque 2.5: sin sesiones, SKIP".

2.5.b Fuente UNICA = el manifest, no los logs. Lee cada sesion con la CLI, jamas escrapeando `execution_log` (no tiene schema para reintentos):
   - `python scripts/init_session_scratch.py --project-root <repo_destino> list`
   - `python scripts/init_session_scratch.py --project-root <repo_destino> audit --session-id <sid>` (exit 1 si el manifest es invalido; usa `--report-only` para inventario sin fallar).

2.5.c Metrica de friccion operacional por `prompt_version`. Para cada generator del manifest, agrega: num. de reintentos + `error_count` + `corrected_after_use`. Una friccion alta y concentrada en un `prompt_version` concreto es la senal; el MAYOR ROI es la friccion con los prompts CANONICOS (evidencia: el maiden voyage de 021z cazo 3 defectos de usabilidad de `audit_pipeline_codeonly.md` en su 1er uso real).

2.5.d Regla `prompt_override` (la desviacion recurrente ES el bug): si >=3 sesiones usan la MISMA override (identidad = prompt_name + override_hash) sobre un prompt CANONICO, abre un ticket de refactor de ese prompt canonico. Una override puntual no; la MISMA repetida >=3 veces si.

2.5.e Triage obligatorio de hallazgos: pasa cada hallazgo de 2.5.c / 2.5.d por `prompts/_shared/finding_triage_protocol.md` ANTES de convertirlo en accion. El destino es el Bloque 4 (memoria, si es aprendizaje con evidencia) o el Bloque 5 (backlog, si es follow-up con evidencia), NUNCA un tercer sitio persistente. Sin evidencia verificable -> se descarta.

2.5.f Decision por artefacto (append-only ESTRICTO). Para cada artefacto de sesion decide `kept` / `promoted` / `discarded` y REGISTRALA como EVENTO NUEVO `artifact_decision` en el manifest, CON su `artifact_path`:
   - `python scripts/init_session_scratch.py --project-root <repo_destino> add --session-id <sid> --event artifact_decision --generator <g> --artifact-path <path> --decision <kept|promoted|discarded>`
   JAMAS edites la entrada original: el manifest es append-only. UNICA EXCEPCION BINARIA que SI bloquea: si un artefacto marcado `kept` o `promoted` contiene PII/secret, BLOQUEA ESA promocion (solo esa, no el cierre entero) y trata el hallazgo como incidente de seguridad segun el triage de 2.5.e.

2.5.g Cierre del ciclo de sesion (fail-safe). Archiva la sesion SOLO tras auditoria COMPLETA -- si el cierre falla, conservala intacta para debug: `... archive --session-id <sid>` REHUSA (`status:stop`, `session_intact:True`) si algun `artifact_added` no tiene su `artifact_decision` (invariante de completitud, match por `artifact_path`). Despues, purga las archivadas conservando K=10: `... gc`. FAIL-SAFE: una sesion con un artefacto sin decision NO se archiva, y como `gc` solo toca sesiones ARCHIVADAS, ese artefacto nunca se pierde silenciosamente.

2.5.h Role Fit Review -- dimension ROL (WOT-2026-022k, EXTIENDE la regla prompt_override de 2.5.d). Ademas de detectar friccion por PROMPT, detecta cuando la friccion recurrente pertenece a un ROL y no a un prompt concreto.
   - Atribucion de rol POR JUICIO: el manifest NO tiene campo de rol de agente (`repo_role` es {motor,no_motor,unknown}, otra cosa). Mapea cada generator con friccion a su rol canonico de AGENTS.md (orchestrator / manager / builder / auditor / user) y REGISTRA la atribucion en una tabla `generator -> prompt_version -> rol_atribuido -> motivo -> friccion`. Un generator ambiguo (no atribuible a un solo rol) se queda a nivel de prompt: NO se agrega por rol.
   - Precedencia y NO doble-conteo: la regla `prompt_override` de 2.5.d GANA para el prompt concreto. Si la friccion se concentra en UN prompt (>=3 misma override) -> es refactor de ESE prompt (2.5.d) y esos hits se EXCLUYEN de la agregacion por rol. Ningun hallazgo alimenta a la vez `prompt_override` y Role Fit Review.
   - Disparo de ROLE_FOLLOWUP: SOLO sobre la friccion RESIDUAL (la que queda tras excluir los hits de `prompt_override`) cuando se DISPERSA por >=2 prompts del MISMO rol y recurre en >=3 sesiones. Ese patron dice que el problema es el ROL (su encaje/definicion), no un prompt.
   - Verdictos (distingue "sin datos" de "sin problema"):
     - `SKIP_NO_TELEMETRY`: <2-3 sesiones de telemetria acumulada. Es ausencia de EVIDENCIA, no de problema: un Role Fit Review sin datos es auto-reporte y CEM lo prohibe. SALTA con este verdicto explicito; NO lo llames NO_ROLE_CHANGE.
     - `NO_ROLE_CHANGE`: hay datos suficientes y la friccion no se concentra por rol.
     - `ROLE_FOLLOWUP`: friccion residual por rol -> ficha de ajuste de rol, registrada en el Bloque 5 (backlog) via el triage de 2.5.e.
     - `MEMORY_ONLY`: senal de rol con evidencia pero sin accion de ticket -> Bloque 4 (memoria) via 2.5.e.
   - NUNCA ROLE_HOTFIX: el cierre solo REGISTRA la senal; cambiar un rol (definicion, backend, allowlist) exige ticket propio, jamas edicion de rol en caliente durante el cierre.

2.5.i Cruce con el scorecard de ensembles (WOT-2026-026d, dep WOT-2026-025y). El Bloque 2.5 hasta aqui audita SOLO la friccion de prompts (manifest). Amplia el ambito a lo que la sesion HIZO -- prompts disenados, herramientas usadas, rondas de ensemble, decisiones de triage -- cruzando el manifest con el scorecard:
   - **Eventos de REFERENCIA del manifest** (el mismo `manifest.jsonl`, nuevos eventos de 026d): `prompt_designed`, `tool_used`, `ensemble_ref`, `backlog_triage_decision`. Cada uno lleva un campo `reference` (hash/ruta/id), NUNCA una copia del payload. El scorecard es DUENO del veredicto por ronda; el manifest solo apunta a el (`ensemble_ref.reference` = fila/id del scorecard). Un dato, un escritor: no dupliques el veredicto del scorecard en el manifest.
   - **Cruce**: para cada `ensemble_ref` del manifest, resuelve su `reference` contra el scorecard de la sesion (`session_id` comun, aportado por 025y) y agrega: que backend propuso/adjudico, latencia, evidencia. Para cada `tool_used`/`prompt_designed`, agrega su recurrencia y si coincide con friccion de 2.5.c/2.5.h.
   - **INFORMATIVO** (misma regla que el resto del bloque): NO bloquea el cierre. Si NO hay scorecard de la sesion (o `session_id` no cruza), dilo explicito ("2.5.i: sin scorecard cruzable para esta sesion, SKIP del cruce") y sigue con lo que el manifest si tenga -- ausencia de scorecard no es fallo.

2.5.j PROCESS IMPROVEMENT PROPOSAL (WOT-2026-026d; pieza SEPARADA de `memory_upload.md`, decision usuario 2026-07-16). Con la telemetria de 2.5.c/2.5.h/2.5.i ya agregada, emite propuestas de mejora de PROCESO. Entrada = ledger de sesion + scorecard + prompts usados + herramientas usadas + errores/retries. Salida = propuestas CLASIFICADAS, SOLO PROPONE (no escribe aqui):
   - Clases: `prompt_refactor` / `skill_refactor` / `script_guard` / `memory_candidate` / `backlog_ticket`. Cada propuesta lleva su EVIDENCIA verificable (SHA/diff/exit-code/cita de prompt/fila de scorecard); sin evidencia -> se descarta (mismo umbral que 2.5.e / Bloque 4).
   - **La escritura va por los canales EXISTENTES, no por un tercer destino**: `memory_candidate` -> Bloque 4 (memoria, con confirmacion humana); `prompt_refactor`/`skill_refactor`/`script_guard`/`backlog_ticket` -> Bloque 5 (backlog persistente del workspace del motor) via el triage de 2.5.e.
   - **CLAUSULA DE PERSISTENCIA (nit revisor 2026-07-16)**: toda propuesta `script_guard`/`backlog_ticket` que SOBREVIVA el triage DEBE materializarse via el Bloque 5 en el backlog persistente. El ledger de sesion es gitignored y se purga (gc, KEEP_LAST_K=10): una propuesta que solo viva ahi es EFIMERA y se pierde. No la dejes en el ledger creyendo que quedo registrada.
   - Promocion de lo aprendido SOLO por Bloques 4/5 post-cierre (verde). Este sub-bloque PROPONE; NUNCA escribe backlog ni memoria durante el Bloque 2.5 (respeta el invariante de arbol de cierre de mas abajo: nada se escribe en `backlog.md` antes de `--session-close`).

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
- `backlog.md` del workspace del motor (`<destination_root>/.agent/collaboration/backlog.md`): lo prepara el Bloque 1.3.7 y lo escribe el Bloque 5 (post-cierre verde) (follow-ups del motor con evidencia). Un follow-up-ticket NO es una entrada de memoria: registralo SOLO en el backlog, no lo dupliques en `observations.jsonl`/`UPSTREAM_LEARNINGS.md`. La memoria documenta el aprendizaje; el backlog agenda el trabajo. El cierre del destino escribe el archivo pero NO commitea el `.git` del workspace.

== BLOQUE 5: REGISTRO DIFERIDO DE FOLLOW-UPS (post-cierre verde) ==
8. Con `--session-close` en verde y el arbol limpio, materializa los follow-ups PREPARADOS en 1.3.7: escribe fila Vista rapida + ficha en `backlog.md`, corre `check_backlog_contract.py`, reporta `[REGISTRADO en <ruta>:<ticket>]`. NO commitees. Registrar follow-ups nunca debe poder bloquear el cierre que los origino.

VALIDACION FINAL: `python .agent/agent_controller.py --validate --json --project-root <repo_destino>` -> exige `0 errors / 0 warnings`. Reporta exit code real.

Recordatorio: responde con conclusiones etiquetadas (VERIFICADO/INFERIDO/NO VERIFICADO) y evidencia citada (SHA, ruta, exit code), no con volcados de archivos. Si algo sale en rojo, DETENTE en el punto de control correspondiente y surfacea la contradiccion antes de tocar memoria.
```

---

## Cuando usarlo

- Al cerrar una sesion que toco codigo del motor o del destino, ANTES del cierre
  canonico, para auditar adversarialmente los diffs de la sesion.
- Como fase previa recomendada de `orchestrator_session_close_chat.md`.

## Cuando NO usarlo

- Para el **Bloque 3 (cierre canonico) con un ticket aun en `IN_PROGRESS` o un
  vuelo abierto**: NO corras `--session-close` (borraria el estado de
  continuacion). Los Bloques 1/2/2.5 SI se pueden correr como auditoria
  mid-flight read-only (ver "Dos modos" arriba, WOT-2026-029c); lo prohibido a
  mitad de vuelo es el Bloque 3, no la auditoria.
- Para arrancar una sesion nueva (usa `orchestrator_session_bootstrap.md`).
- Como sustituto del cierre operativo: esta pasada audita y precede; el cierre
  real lo ejecuta `agent_controller.py --session-close`.
