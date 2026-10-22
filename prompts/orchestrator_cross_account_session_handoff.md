---
role: orchestrator
cycle_phase: [F7-cierre-sesion]
route_kind: modo
status: experimental
---
# Orchestrator Cross-Account Session Handoff (Capa 0)
<!-- PROMPT-SUMMARY
what: Gobierna el handoff de un vuelo autonomo de la Capa 0 entre DOS CUENTAS Claude distintas (no dos sesiones de la misma cuenta -- eso ya lo cubre la Seccion 10 de `orchestrator_pipeline/reports/metodo_vuelo_autonomo_4capas_20261022.md`): parada activa de la sesion origen, verificacion empirica de visibilidad cross-cuenta por doble primitivo con timeout, canal de handoff por artefacto en disco (no por `ListAgents`/`SendMessage`, no fiables cruzando cuentas), y reconciliacion obligatoria de checkpoint/idempotencia al reanudar.
when: Cuando la Capa 0 de un vuelo (o uno de sus Manager-hijos) va a agotar la cuota de su cuenta Claude activa, o cualquier otro corte de sesion (limite de contexto, cierre forzado) obliga a continuar el vuelo desde OTRA cuenta Claude en la misma maquina (`cc-watch`, `CLAUDE_CONFIG_DIR` distinto).
not: NO sustituye el handoff intra-cuenta (Seccion 10 del metodo de vuelo citado, donde `ListAgents`/`SendMessage` SI funcionan). NO es un mecanismo de fallback automatico de Revisor/Builder (eso es la "Politica de modelo del Revisor" del mismo metodo de vuelo). NO decide POR SI SOLO cuando cambiar de cuenta -- esa decision humana/de monitor (`cc-watch`) es previa a este prompt.
-->

**[EXPERIMENTAL -- status: experimental, ver frontmatter]** -- diseno nacido
2026-10-22/23 en la sesion `FDL32/optimizacion-arranque-frio-cont-20261022`,
a partir de: (a) un bucle de gobierno de 5 lentes independientes sobre
`orchestrator_pipeline/reports/bundle_claude_account_fallback_design_20261022.md`
(opencode/GLM, nan/deepseek, nan/qwen3.8, google/gemini, mistral -- consenso
5/5 PROCEDER CON CAMBIOS); (b) un segundo bucle de 2 lentes sobre el primer
prompt de arranque real (`prompt_arranque_sesion_brabander_cross_account_20261023.md`)
que esta plantilla generaliza; (c) un hallazgo EN VIVO durante ese segundo
bucle: la propia lente `opencode/GLM` tuvo sus lecturas cross-path DENEGADAS
por su allowlist de permisos (`external_directory`), confirmando empiricamente
uno de los riesgos que esta plantilla declara (Seccion 5). Este diseno NO ha
corrido un vuelo real todavia -- su primer uso real es el experimento que lo
origino (sesion `brabander`, pendiente de resultado al escribir esto). NO
promover a `status: stable` sin esa evidencia (ver "Que NO hacer").

contract_id: cid-orchestrator-cross-account-session-handoff-v0
Skill canonica: pendiente -- sin skill wrapper todavia; invocar este prompt
directamente (cita su ruta completa) hasta que exista
`skills/orchestrate-cross-account-session-handoff/SKILL.md`.
source_of_truth: este prompt opera sobre el vuelo citado en `when`; si diverge
de la Seccion 10 de `metodo_vuelo_autonomo_4capas_20261022.md` (handoff
intra-cuenta), ESTE prompt prevalece SOLO para el caso cross-cuenta -- la
Seccion 10 base sigue gobernando el caso intra-cuenta sin cambios.

---

## Paso 0: condicion de entrada -- cuando este prompt aplica de verdad

Antes de usar este prompt, confirma explicitamente AMBAS condiciones (si
falta cualquiera, usa el handoff intra-cuenta de la Seccion 10 del metodo de
vuelo, que es mas barato y ya tiene `ListAgents`/`SendMessage` funcionando):

1. La sesion ORIGEN y la sesion DESTINO corren bajo `CLAUDE_CONFIG_DIR`/
   `providerInstanceId` de CUENTAS CLAUDE DISTINTAS (verificalo: compara el
   nombre de cuenta que `cc-usage` reporta como activa, o el
   `providerInstanceId` que `orchestrator_capabilities` muestra como
   `inheritedProviderInstanceId` en cada sesion -- nunca lo asumas por el
   nombre del worktree o de la sesion).
2. El motivo del corte es agotamiento de cuota, limite de contexto, u otro
   corte de sesion real -- no un simple "quiero paralelizar" (para eso esta
   el dispatch multi-hijo de la misma cuenta, `delegate_task`/fork, que es
   mas barato y mantiene visibilidad via `ListAgents`).

Si ambas se cumplen, sigue con las secciones 1-5 EN ORDEN. No te saltes la
Seccion 1 (parada) pensando que la Seccion 3 (verificacion de canal) viene
primero: la parada es la salvaguarda que existe PRECISAMENTE porque el canal
de verificacion (Seccion 3) puede fallar o tardar.

---

## 1. Parada activa de la sesion ORIGEN (la salvaguarda dura, nunca opcional)

**Regla dura, confirmada por incidente real ya promovido a observacion**
(`resumed-flight-can-run-two-claude-sessions-without-channel`: dos Managers
vivos sobre el mismo vuelo tras un swap de cuenta a mitad de sesion, un
auditor sobre-escribio el informe del otro con un verde vacuo): **la sesion
origen NUNCA queda operando en paralelo con la sesion destino.** No hay
deteccion barata de colision cruzando cuentas (Seccion 3 lo intenta, pero no
esta garantizado que funcione) -- por tanto la UNICA salvaguarda fiable es
que solo una de las dos este activa en cada momento.

Checklist operativo de la sesion ORIGEN, en este orden:
1. Cierra en firme lo que ya aterrizo (commits, verificaciones ya hechas) --
   proporcional, no un cierre canonico completo si el vuelo sigue abierto
   (ver `orchestrator_session_close_full_audit.md`, modo mid-flight).
2. Prepara el prompt de arranque de la sesion destino (contenido minimo en
   la Seccion 2).
3. Lanza o deja listo el comando de arranque de la cuenta destino
   (`cc-brabander`/`vscode-brabander`/`ag-brabander`/etc., ver memoria
   `cc-watch-account-switch.md` -- NUNCA inventes un comando nuevo, usa los
   ya existentes del `$PROFILE`).
4. **DETENTE.** No emitas mas turnos ni tool calls sobre este vuelo hasta que
   la sesion destino confirme por OTRO CANAL (el propio usuario, nunca
   `SendMessage` -- ver Seccion 3) que ha tomado el relevo.

---

## 2. Contenido minimo del prompt de arranque de la sesion DESTINO

El prompt que la sesion origen entrega a la destino DEBE declarar, como
minimo (lista derivada de los hallazgos reales del segundo bucle de 2 lentes
sobre el primer prompt real de este tipo):

- Identidad: de que vuelo/sesion viene, y que ESTO es un handoff cross-cuenta
  deliberado (no una sesion nueva independiente).
- Rutas resueltas (repo_destino, MOTOR_ROOT, destination_root) -- NUNCA
  "adivinadas", siempre con el comando que las resolvio.
- HEAD/rama/estado git EXACTO en el momento de la parada, con el comando que
  lo verifico (no una cifra copiada de memoria).
- **Snapshot de cuota FECHADO explicitamente** (ej. "cuota a las 23:48 del
  2026-10-22, puede haber cambiado -- si necesitas el dato actual, pide al
  usuario que corra `cc-usage` de nuevo"). Nunca presentarlo como estado
  actual sin fecha.
- Que esta PENDIENTE (push, tickets abiertos, bucles sin correr) y que es
  responsabilidad de QUIEN (la sesion origen cuando retome, o la destino si
  el usuario lo decide explicitamente).
- El objetivo CONCRETO de la sesion destino (puede ser continuar el vuelo
  original, o un objetivo nuevo como el experimento de la Seccion 3 de abajo
  -- decidido por el usuario, nunca asumido).
- La regla de la Seccion 1 (la origen se detuvo, no coexiste).
- **Si el prompt pide leer ficheros del worktree de la ORIGEN desde la
  DESTINO** (necesario para que la destino tenga contexto): declara
  explicitamente el riesgo de permisos de la Seccion 5 y su fallback.

---

## 3. Verificacion empirica del canal de comunicacion (doble primitivo, con timeout)

**No asumas que `ListAgents`/`SendMessage` no funcionan cross-cuenta --
TAMPOCO asumas que si funcionan.** Es DESCONOCIDO hasta que se mide (el
usuario reporta experiencia mixta: "a veces se han visto, pero con
dificultad"). La sesion DESTINO, nada mas arrancar, corre este experimento
ANTES de disenar nada:

1. `ListAgents` -- reporta la lista COMPLETA de lo que ves, no un resumen.
   Si ves a la sesion origen (aunque este "detenida", puede figurar `idle`):
   anotalo como SENAL POSITIVA, no concluyas todavia que el canal es fiable
   (una senal positiva puntual no basta; ver "Que NO hacer").
2. `t3_thread_search` con una query que deberia encontrar el vuelo origen
   (ej. el titulo o un ticket ID citable) -- segunda senal INDEPENDIENTE,
   porque puede divergir de `ListAgents` (cruzar cuentas puede fallar para
   uno y no para el otro).
3. **Timeout explicito: si cualquiera de los dos primitivos no responde en
   30 segundos, registra el timeout como resultado (NO lo trates como
   negativo silencioso ni sigas esperando indefinidamente) y continua.**
4. **Persiste el resultado por escrito en un fichero propio citable ANTES de
   seguir** (`orchestrator_pipeline/reports/experimento_visibilidad_cross_account_<fecha>.md`
   o similar) -- no solo en el chat: el escenario que activa este prompt
   (agotamiento de cuota/contexto) puede significar que nadie lea la
   respuesta en el chat hasta mucho despues.

Interpretacion de resultados:
- Si NINGUN primitivo encuentra la sesion origen: confirma la limitacion
  medida. Procede a disenar/usar el canal de artefacto en disco (Seccion 4)
  como UNICO canal fiable.
- Si ALGUN primitivo SI la encuentra: no lo declares "canal fiable" sin mas
  -- es una senal de UN experimento. Documenta exactamente que correlacion
  lo hizo posible (mismo `projectId`? mismo `environmentId` de
  `t3_environment_read`? otra cosa) antes de confiar en el para un vuelo
  real. Usa el canal de artefacto (Seccion 4) como respaldo de todos modos.

---

## 4. Canal de handoff por artefacto en disco (el canal que SI es fiable)

Independientemente del resultado de la Seccion 3, ambas cuentas comparten la
MISMA maquina y el MISMO sistema de ficheros -- ese es el canal que no
depende de ningun primitivo de T3 ni de visibilidad cross-cuenta:

- Fichero de estado compartido, formato propio (ej.
  `<repo_destino>/orchestrator_pipeline/reports/cross_account_handoff_<vuelo>.json`
  o `.md`, segun si hace falta estructura maquina-legible o solo humana).
  Campos minimos: `origen_cuenta`, `destino_cuenta`, `timestamp`,
  `head_sha`, `estado` (`entregado` / `tomado` / `en_progreso` /
  `devuelto`), `siguiente_accion`.
- La sesion DESTINO escribe `estado: tomado` al arrancar -- es la
  confirmacion que la Seccion 1 pide "por otro canal" (puede ser este
  fichero, ademas del propio usuario).
- Ninguna sesion asume que el fichero es verdad absoluta si no coincide con
  el HEAD real de git -- es un PUNTERO para coordinar, no un sustituto de
  `git log`/`git status` (misma disciplina METODO vs ESTADO de
  `session_hop.md`).
- Riesgo declarado, no bloqueante: si AMBAS sesiones escriben el mismo
  fichero a la vez (deberia ser imposible si la Seccion 1 se respeta, pero
  declaralo): usa append-only o un sufijo de timestamp en el nombre, nunca
  sobre-escritura silenciosa.

---

## 5. Riesgo de permisos cross-repo (confirmado en vivo, no hipotetico)

**Medido en esta misma sesion de diseno:** una lente (`opencode/GLM`) con su
propio allowlist de `external_directory` tuvo DENEGADAS lecturas fuera de su
proyecto -- incluso una ruta declarada `allow` cayo por precedencia de una
regla `ask`/`*` anterior. Esto es un riesgo REAL para la sesion DESTINO
leyendo ficheros del worktree de la ORIGEN (Seccion 2), no una
posibilidad remota:

- Si una lectura cross-path es denegada por el propio allowlist de permisos
  de la sesion DESTINO: declaralo explicitamente, NO asumas que el contenido
  no existe. Pide al usuario que pegue el contenido directamente, o que
  amplie el allowlist (`external_directory` en `.opencode/opencode.json` o
  el equivalente del backend/editor activo).
- Nunca sigas adelante fabricando contenido de un fichero que no pudiste
  leer -- es exactamente el patron "premisa falsa que pasa los gates" que
  este mismo repo ya tiene documentado (`verify-premise-before-implementing`).

---

## 6. Reconciliacion obligatoria al reanudar (checkpoint/idempotencia)

**Confirmado por consenso 5/5 del bucle de gobierno original:** un corte a
mitad de una operacion NO idempotente (un `delegate_task` aceptado sin
confirmar, un `git commit`/`push` a medias, una escritura parcial en
`.agent/collaboration/`) deja huerfanos o estado a medio escribir. La sesion
DESTINO NUNCA asume que el ultimo estado conocido (el prompt de arranque, el
fichero de la Seccion 4) es la verdad final:

1. `git status`/`git log` del HEAD REAL del repo_destino -- compara contra
   lo que el prompt de arranque declara. Si diverge, el prompt de arranque
   esta STALE: confia en git, no en la prosa.
2. `task_status`/`ListAgents` de cualquier hijo que pudiera seguir vivo
   (Manager-hijos delegados antes del corte) -- un hijo huerfano lanzado sin
   registro puede causar doble dispatch si no se detecta antes de continuar.
3. Si el corte ocurrio a mitad de una operacion no-idempotente sin checkpoint
   seguro: NO continues esa operacion a ciegas -- decide explicitamente si
   reintentarla desde cero (si es segura de repetir) o declararla
   `PARCIAL_SIN_CIERRE` y escalar al usuario.

---

## Que NO hacer

- No declarar este mecanismo "funciona" tras UN solo experimento positivo de
  la Seccion 3 -- un dato (`n=1`) no es evidencia de fiabilidad, es una
  observacion a confirmar.
- No usar este prompt para paralelizar trabajo dentro de la MISMA cuenta --
  para eso ya existe `delegate_task`/fork con `ListAgents` funcionando
  (Seccion 10 del metodo de vuelo base).
- No asumir que `claudeAgent`/`claudeAgent_alvarovans` (o los nombres
  equivalentes que `orchestrator_capabilities` exponga) mapean a una cuenta
  humana concreta sin verificarlo -- ese mapeo vive en configuracion del
  harness, fuera de cualquier repo (confirmado por el bucle de 5 lentes
  original: ningun fichero versionado lo resuelve).
- No promover este prompt fuera de `status: experimental` sin evidencia de
  VUELO REAL (no solo el experimento de diseno que lo origino) de, como
  minimo:
  1. Una parada real de la Seccion 1 ejecutada de principio a fin (la
     origen SI se detuvo, no coexistio).
  2. El experimento de la Seccion 3 corrido con resultado documentado
     (positivo o negativo, con su fichero citable).
  3. El canal de artefacto de la Seccion 4 usado para una coordinacion real
     (no solo diseñado).
  4. Al menos un caso real de reconciliacion de la Seccion 6 (un corte a
     mitad de operacion, detectado y resuelto sin doble dispatch).
  Hasta entonces: cada vuelo que use este prompt debe tratarlo como
  diseno-en-prueba y documentar sus resultados para la siguiente iteracion
  (criterio del usuario: "despues lo remataremos en la siguiente sesion una
  vez este probado e implantado").
