---
status: experimental-evidence
owner: sesion-brabander-cross-account-comms-20261023
related: prompts/orchestrator_child_dispatch_cross_claude.md, orchestrator_pipeline/reports/parte_de_parada_cierre_mid_flight_20261023.md (worktree optimizacion-arranque-frio-cont-20261022)
---

# Experimento de visibilidad cross-cuenta Claude (2026-10-23)

Registro del experimento pedido por el usuario: comprobar si `ListAgents` y
`t3_thread_search` ven la sesion origen (`FDL32/optimizacion-arranque-frio-cont-20261022`,
cuenta `alvarovans`) desde esta sesion hermana, lanzada via `t3_thread_launch`
con `modelSelection.instanceId: "claudeAgent"`.

## 1. Identidad de cuenta de esta sesion (circunstancial, NO verificada)

- `orchestrator_capabilities` -> `inheritedProviderInstanceId: "claudeAgent"`,
  `inheritedModel: "claude-sonnet-5"`, `parentThreadId:
  "mcp:f3791ae3-0175-4cf3-afda-6e597bb87d46"`.
- El catalogo `providers` de esa misma llamada lista `claudeAgent` Y
  `claudeAgent_alvarovans` como DOS entradas DISTINTAS.
- Esto coincide exactamente con lo que la sesion origen predijo: su propio
  parte de parada registra un ping real (`delegate_task`) a
  `providerInstanceId: "claudeAgent"` que respondio "OK" -- interpretado ahi
  como "la cuenta hermana esta viva", sin poder confirmar que fuera
  especificamente `brabander`.
- **No se eleva esto a confirmacion.** `prompts/orchestrator_child_dispatch_cross_claude.md`
  (seccion "Que NO hacer") es explicito: el mapeo `providerInstanceId` ->
  cuenta humana concreta vive en configuracion del harness, fuera de
  cualquier repo, y no debe asumirse. El nombre de esta sesion
  (`brabander-cross-account-comms-20261023-f9`, via `ListAgents`) tampoco es
  evidencia independiente: es la rama/worktree que la sesion origen eligio
  nombrar asi ANTES de lanzar, no una senal medida por el harness.
- Pendiente: confirmacion del usuario "por fuera" (que cuenta ve en su
  editor/ventana).

## 2. `ListAgents` -- resultado NEGATIVO para la sesion origen

Salida completa:
- Esta sesion: `brabander-cross-account-comms-20261023-f9 [5e9c82]`.
- Peers (2): `crear-texto-llm-3a [7f9a61]` (busy, 35m), `system32-cb [a9030f]`
  (waiting, 1d).
- La sesion origen (`optimizacion-arranque-frio-cont-20261022`) **no aparece**,
  ni como activa ni como idle/detenida.

**Confusion declarada (no resuelta por este experimento):** la ausencia puede
deberse a (a) que `ListAgents` no cruza cuentas Claude distintas, o (b) a que
la sesion origen recibio la instruccion de DETENERSE (Seccion 1 del prompt
cross-claude) y, si "detenerse" significa terminar el proceso/hilo en vez de
quedar idle, cualquier sesion -- misma cuenta o no -- dejaria de listarse.
Este experimento NO tiene un control que distinga ambas causas (haria falta
comparar contra una sesion de la MISMA cuenta que tambien se detuvo). Queda
como pregunta abierta para el siguiente experimento.

## 3. `t3_thread_search` -- resultado POSITIVO, pero de otra naturaleza (content search, no presence)

Query `"optimizacion-arranque-frio-cont-20261022"` -> 18 matches, todos bajo
el MISMO `projectId` (`386f76d6-846f-4e9f-85b9-6e4673225e46`).

- El primer match (`threadId: mcp:f3791ae3-...`) es, por coincidencia de
  `parentThreadId` con el de esta propia sesion, **mi propio hilo actual**
  (el prompt de arranque que recibi menciona esa ruta literalmente) -- no es
  evidencia de encontrar la sesion origen, hay que descartarlo.
- Los otros ~17 matches SI son hilos distintos y genuinamente pertenecen al
  vuelo origen: hilos `delegated-task` de sus Manager-hijos (rondas de review
  de WOT-2026-116a/117a/118a/119a) y varios `thread:provider:claudeAgent:
  native-thread:...` con contenido narrativo real de los turnos de trabajo de
  la sesion `alvarovans` (branch, HEAD shas, deliverables).
- Interpretacion: `t3_thread_search` busca por CONTENIDO/titulo dentro de un
  `projectId`, no por "quien esta vivo ahora". El hecho de que encuentre
  hilos creados bajo otro `providerInstanceId` indica que el `projectId` NO
  esta particionado por cuenta Claude -- es un indice de contenido compartido
  a nivel de proyecto, mecanismo distinto al roster de `ListAgents`.
- Limite declarado: esto es descubrimiento DE SOLO LECTURA de contenido
  historico, no un canal de comunicacion. No implica que `SendMessage` pueda
  alcanzar esa sesion, ni resuelve si sigue viva.

## 4. Hallazgo nuevo (posterior, en vivo): `t3_thread_send` SI cruza cuenta -- `SendMessage`/`ListAgents` NO

Durante el experimento, la sesion origen (`alvarovans`) envio un mensaje de
seguimiento que llego a este hilo. Verificado en el item crudo via
`t3_thread_read` sobre mi propio `threadId`
(`mcp:f3791ae3-0175-4cf3-afda-6e597bb87d46`): el `itemId` del mensaje entrante
es `...message:mcp:9b8f9753-66aa-4403-8d2b-70a16cf3e13c:thread-send:...` --
`creationSource: "mcp"`, `createdBy: "agent"`. El prefijo `mcp:9b8f9753-...`
coincide EXACTAMENTE con el identificador de comando que aparece en los
`threadId` de las tareas delegadas que la sesion origen lanzo durante su
propio vuelo (`...delegate-task:wot-2026-117a-manager-r1` etc.) -- confirma
que el remitente real es esa sesion, bajo `providerInstanceId:
claudeAgent_alvarovans` (verificado via `t3_thread_list`: su hilo raiz es
`mcp:1994e71a-24ec-44cf-8c6a-7f9ab7d7ccc8`, title "Vuelo R3 arranque en frio
— continuacion (sesion hermana)", `providerInstanceId: claudeAgent_alvarovans`).

**Contraste medido en la misma sesion, mismos targets:**
- `SendMessage` a `t3-0af26b3d-17` -> `{"success":false,"message":"No agent
  named 't3-0af26b3d-17' is reachable."}`.
- `SendMessage` a `optimizacion-arranque-frio-cont-20261022-69` (nombre de la
  sesion origen declarado por ella misma) -> mismo fallo, "not reachable".
- `mcp__t3-code__t3_thread_send` con `threadId:
  "mcp:1994e71a-24ec-44cf-8c6a-7f9ab7d7ccc8"` (el hilo RAIZ real de la sesion
  origen, obtenido de `t3_thread_list`, NO un nombre) -> **exito**:
  `{"status":"queued","delivery":"queued"}`. Mensaje de vuelta entregado.

**Conclusion del hallazgo:** existen (al menos) dos mecanismos de mensajeria
cross-sesion con alcance DISTINTO:
1. `SendMessage`/`ListAgents` (roster de agentes, direccionado por NOMBRE) --
   NO cruza `providerInstanceId`/cuenta en este experimento (n=1, ambos
   sentidos probados, ambos fallaron).
2. `mcp__t3-code__t3_thread_send` (T3 nativo, direccionado por `threadId`
   exacto, descubierto via `t3_thread_list`/`t3_thread_search`) -- SI cruza
   cuenta/`providerInstanceId` (n=1 en cada sentido: origen->yo confirmado por
   la llegada real del mensaje; yo->origen confirmado por el `status:
   queued` de mi propio envio).

Esto cambia el diagnostico del Primer Objetivo: el canal fiable cross-cuenta
NO hace falta disenarlo desde cero (fichero en disco) -- **ya existe y
funciona**, siempre que se conozca el `threadId` exacto del destino (via
`t3_thread_list`/`t3_thread_search`, nunca por nombre de sesion). La limitacion
real no es "no hay canal", es "el canal por NOMBRE (`ListAgents`/
`SendMessage`) no resuelve cross-cuenta, pero el canal por ID si existe y
nadie lo habia probado directamente hasta ahora". Pendiente de una segunda
repeticion independiente antes de promoverlo a mecanismo definitivo (sigue
siendo n=1 por sentido).

## Conclusion provisional (para decidir el diseno, Seccion 3 del prompt cross-claude)

- `ListAgents`/`SendMessage` como canal de PRESENCIA/mensajeria en vivo:
  confirma la limitacion ya sospechada por el usuario -- no ve la sesion
  origen. Tratar como no fiable para coordinacion en vivo cross-cuenta (o,
  como minimo, no fiable cuando la sesion origen se detuvo).
- `t3_thread_search` como indice de CONTENIDO a nivel de proyecto: SI
  encuentra material del vuelo origen (hilos delegados + hilos nativos), con
  el matiz de que no es un canal de mensajeria sino de lectura retrospectiva.
  Esto es util como SEGUNDA via de reconciliacion de solo lectura (Seccion 6
  del prompt cross-claude: "que hizo la sesion origen antes del corte") --
  complementaria al canal de artefacto en disco de la Seccion 4, no un
  sustituto.
- n=1 en ambos primitivos. No promover ninguna conclusion a mecanismo
  definitivo sin mas repeticiones (ver "Que NO hacer" del prompt cross-claude).
