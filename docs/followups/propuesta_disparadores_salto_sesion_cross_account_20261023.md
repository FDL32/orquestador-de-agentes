---
status: resuelta-tras-bucle-5-lentes
resolucion_usuario:
  - trigger_b_semantica: "Compactacion SIEMPRE dispara session_hop ligero (misma cuenta). El cruce de cuenta lo decide SOLO la cuota (Trigger A); el contexto NUNCA cruza por si mismo."
  - unidad_25pct: "25% de CONTEXTO restante de ESTA sesion (no cuota)."
owner: sesion-brabander-cross-account-comms-20261023
related: prompts/session_hop.md, prompts/orchestrator_session_close_chat.md,
  prompts/orchestrator_session_close_full_audit.md,
  prompts/orchestrator_session_close_full_audit_design.md,
  prompts/orchestrator_child_dispatch_multiticket_multibackend_unlimited.md,
  prompts/orchestrator_child_dispatch_cross_claude.md,
  C:\Users\fdl\claude_tooling\accounts\cc-usage-monitor.ps1,
  docs/followups/cross_account_visibility_experiment_20261023.md
decisiones_usuario:
  - automatizacion: autoejecucion_completa
  - ventana_cortesia: 5 min, no bloqueante, via notificacion + ScheduleWakeup
  - senal_contexto: investigar antes de fijar umbral (ver Seccion 2)
---

# Propuesta: disparadores automaticos de salto de sesion (contexto y cuota) con escalado cross-cuenta

## 0. Marco: 5 prompts gobernantes, no 2

El usuario cito 4; hay un 5o que gobierna el mismo dominio y debe coordinarse:

| Prompt | Rol en este diseno |
|---|---|
| `prompts/session_hop.md` | Puente de continuidad LIGERO, misma cuenta, solo lectura, re-mide estado. Candidato para el caso "compactacion con margen". |
| `prompts/orchestrator_session_close_chat.md` | Cierre OPERATIVO (no auditoria). Mas ligero que `close_full_audit`. |
| `prompts/orchestrator_session_close_full_audit.md` | Cierre CANONICO completo (Bloques 1-5, auditoria adversarial). El que el usuario nombra para el caso de cuota agotada. |
| `prompts/orchestrator_session_close_full_audit_design.md` | Version `design`/variante del anterior -- a verificar en la Seccion 4 si diverge o es la fuente de una mejora ya pendiente de fusion. |
| `prompts/orchestrator_child_dispatch_multiticket_multibackend_unlimited.md` | Continuidad MISMA cuenta, multi-backend -- el usuario lo senala como el equivalente "intra-cuenta" al cross-claude. |
| `prompts/orchestrator_child_dispatch_cross_claude.md` | Handoff CROSS-CUENTA (Secciones 1-7 tras el commit `a6c443a1` de la sesion `alvarovans`, ver docs/followups/cross_account_visibility_experiment_20261023.md). |

**Nota de alcance declarada:** `multiticket_multibackend_unlimited.md` orquesta fan-out de VARIOS tickets a VARIOS backends con el padre vivo (ver su propio frontmatter `not:`) -- NO es un sustituto de `session_hop.md` para continuidad de UNA sola Capa 0. Lo incluyo en la tabla porque el usuario lo cito como referencia de "continuidad misma cuenta", pero el diseno de abajo usa `session_hop.md` para ese caso, no ese prompt. Si el usuario quiere que sea ESE prompt el que gobierne el caso "misma cuenta", es una correccion a pedir en el bucle.

## 1. Dos disparadores, con semantica DISTINTA (no un solo umbral)

| | Trigger A: CUOTA (ventana 5h) | Trigger B: CONTEXTO (compactacion) |
|---|---|---|
| Que mide | `cc-usage` (API Anthropic), % usado de la ventana de 5h de la CUENTA activa | Evento `PreCompact` del hook de Claude Code (la sesion ACTUAL se esta quedando sin contexto) |
| Umbral pedido | <15% restante (>=85% usado) | <25% de "la sesion" -- interpretado como contexto restante, no cuota (ver Seccion 2, matiz) |
| Mecanismo de deteccion | Monitor externo (`cc-usage-monitor.ps1`, ya existe, extension de umbral) | Hook `PreCompact` (ya cableado a `.agent/hooks/pre_compact_hook.py`) + heuristica nueva (Seccion 2) |
| Protocolo que dispara | PESADO: `orchestrator_session_close_full_audit.md` (cierre canonico) + `orchestrator_child_dispatch_cross_claude.md` (salto cruzado) -- la CUENTA se va a quedar sin servicio, no solo la sesion | Depende del umbral de contexto (ver abajo): LIGERO (`session_hop.md`, misma cuenta) si hay margen; si <25%, el MISMO salto PESADO que el Trigger A |
| Por que son distintos | Cuota agotada = la cuenta entera deja de responder pronto, sin relacion con cuanto contexto le queda a ESTA sesion | Contexto agotado = ESTA sesion concreta necesita continuar en una sesion nueva; si ademas el margen es bajo repetidamente, es señal de que una simple continuidad intra-cuenta no basta y conviene saltar de cuenta tambien |

**Correccion sobre la lectura literal del usuario:** el mensaje original puede leerse como "compactacion SIEMPRE dispara session_hop, Y SEPARADAMENTE si <25% salta cruzado" -- en la tabla de arriba lo modelo como UN solo disparador (compactacion) con DOS posibles protocolos de salida segun el umbral de contexto, no dos disparadores independientes sobre el mismo evento. Si el usuario quiere que sean dos pasos secuenciales siempre (primero session_hop SIEMPRE, y el salto cruzado es una decision posterior e independiente), es una correccion a confirmar en el bucle -- lo declaro como AMBIGUEDAD RESUELTA POR SUPOSICION, no como hecho.

## 2. El hueco de medicion: no hay señal continua de "% contexto restante"

Investigado en este repo y en el conocimiento del hook `PreCompact` de Claude Code:
- `PreCompact` es un evento PUNTUAL: dispara cuando la compactacion YA va a ocurrir (el harness decidio que hace falta). No entrega un porcentaje progresivo ANTES de llegar a ese punto -- es binario (compactando / no compactando), con un campo `trigger` (`"manual"` vs `"auto"`) pero sin contador de tokens restantes en el payload documentado que he podido confirmar desde este entorno.
- No existe en este repo ningun mecanismo existente que lea o aproxime "% de contexto restante" (`grep` vacio sobre `context_remaining`/`tokens_remaining`/`statusline` en todo el arbol).

**Dos opciones evaluadas, ninguna ejecutada todavia (pendiente de decision en el bucle):**

1. **Heuristica por transcript** (aproximada, NO exacta): un hook `PostToolUse` o un chequeo periodico lee `transcript_path` (lo recibe cualquier hook de Claude Code), cuenta caracteres/4 como aproximacion de tokens, lo compara contra el tamano de ventana del modelo activo (variable por modelo, no hardcodear un numero sin confirmarlo por `orchestrator_capabilities`/`inheritedModel`), y calcula un % aproximado. **Riesgo declarado:** es una aproximacion, no el contador real del harness -- puede desviarse con mensajes densos en herramientas (base64, JSON largo) que no siguen la proporcion chars/4 de texto natural.
2. **Usar `PreCompact` como proxy binario, sin granularidad de %:** cada vez que compacta, evaluar el umbral de CUOTA (Trigger A) en ese mismo instante como proxy de "cuanto margen total queda" -- si la cuota tambien esta baja, se interpreta como "contexto Y cuenta estan al limite a la vez" y se escala a cruzado; si la cuota tiene margen, se trata como session_hop normal. **Esto SUSTITUYE el umbral de "25% de contexto" por una lectura indirecta via cuota**, que es una desviacion real del pedido original del usuario (que quiere 2 señales independientes) -- declarado como tal, no disimulado.

**Recomendacion de esta propuesta (sometida al bucle, no una decision cerrada):** opcion 1 (heuristica por transcript) es la unica que respeta el pedido original (umbral de CONTEXTO independiente de la cuota). Opcion 2 es mas barata pero cambia la semantica pedida. Propongo implementar la opcion 1 con el umbral del 25% como PARAMETRO configurable (no cristalizado), declarando explicitamente que es una APROXIMACION medida por heuristica, nunca "el numero exacto del harness".

## 3. Ventana de cortesia de 5 min (ya acordada con el usuario)

Para AMBOS triggers, antes de ejecutar el protocolo pesado (cierre canonico +
salto cruzado) en modo autoejecucion completa (decision ya tomada por el
usuario): emitir una notificacion NO bloqueante (via mensaje al usuario/bus,
no `AskUserQuestion` que es bloqueante) y `ScheduleWakeup` con
`delaySeconds: 300`. Al despertar: si no hay respuesta/cancelacion
registrada, proceder con el protocolo automatico. La ventana es cortesia de
interrupcion, nunca bloqueo real del vuelo autonomo.

**Nota de alcance:** esto aplica a VUELOS AUTONOMOS (sin humano esperando
turno a turno). En sesion INTERACTIVA, el patron natural es simplemente
preguntar (bloqueante) -- no tiene sentido una ventana de 5 min si el humano
esta ahi mismo. Declarar esta distincion explicitamente en la implementacion
final.

## 4. `orchestrator_session_close_full_audit.md` vs `_design.md` -- RESUELTO

Leido el frontmatter y la tabla de mapeo de `_design.md`: es la VARIANTE
read-only para sesiones de DISEÑO (triage, fichas, planes -- nunca commitea,
nunca muta el motor). `source_of_truth` del propio fichero lo declara:
"deriva de `orchestrator_session_close_full_audit.md`... aquel rige para
desarrollo y este para diseño". Los vuelos autonomos que disparan este
mecanismo (sesiones que tocan codigo, hacen commits, corren suites) son
sesiones de DESARROLLO -- por tanto el prompt que gobierna el protocolo
PESADO de este diseno es `orchestrator_session_close_full_audit.md`, nunca
`_design.md`. Sin ambiguedad real: confirmado por lectura directa, no por
suposicion.

## 5. Errores y puntos de mejora encontrados en esta misma pasada (auto-revision)

1. **Confusion de escala ya declarada en la Seccion 1 (correccion sobre
   lectura literal)** -- ver arriba, pendiente de confirmar con el usuario.
2. **El umbral de "25%" no tiene unidad confirmada.** Puede leerse como "25%
   del contexto de ESTA sesion" (lo que yo asumi) o "25% de la CUOTA de la
   cuenta en este momento, medida AL MOMENTO de compactar" (lectura
   alternativa igual de valida del texto original: "si esta por debajo del
   25% de la sesion" podria referirse al mismo numero que luego se usa para
   cuota, solo que en un punto de evaluacion distinto). Si fuera esto
   ultimo, el diseno se simplifica mucho: un solo monitor de cuota con DOS
   umbrales (25% para contexto/compactacion, 15% para el monitor
   independiente) en vez de dos sistemas de medicion distintos. **Esta es la
   ambigüedad mas cara de las dos -- determina si hace falta construir la
   heuristica de la Seccion 2 o no.**
3. **Falta un criterio de "vuelta atras" (reset)**: si la cuota se
   resetea (ventana de 5h) o el contexto se libera (nueva sesion con 100%
   disponible) DESPUES de haber escalado a cruzado, ¿cuando vuelve el vuelo
   a la cuenta original? El diseno actual de `cc-watch` ya tiene esta
   logica para el caso MANUAL ("vuelve a alvaro tras su reset") -- falta
   decidir si el caso AUTOMATICO hereda la misma regla o necesita una propia
   (p.ej., un vuelo largo que ya salto 2 veces no deberia rebotar cada
   reset).
4. **Riesgo de doble disparo:** si Trigger A (cuota) y Trigger B (contexto)
   se cruzan casi a la vez (compactacion ocurre justo cuando la cuota ya
   esta baja), ambos podrian intentar ejecutar el protocolo pesado por
   separado -- mismo patron de "deduplicacion" que la Seccion 7 del prompt
   cross-claude ya declara para mensajes duplicados, pero aqui aplicado a
   DISPARADORES duplicados, no mensajes. Falta una guarda de idempotencia
   (p.ej. un fichero de estado "handoff en progreso" que el segundo trigger
   consulte antes de lanzar su propio protocolo).
5. **El "autoejecucion completa" elegido por el usuario entra en tension
   declarada con AGENTS.md "Push por vuelo"** (un solo push agrupado, con
   autorizacion humana explicita): el cierre canonico puede implicar un
   push. Si el protocolo automatico llega a ese paso, **debe detenerse en
   el gate de autorizacion existente, no saltarlo** -- la autoejecucion
   cubre el CIERRE y el SALTO de sesion/cuenta, nunca el push en si, que
   sigue las reglas ya vigentes. Declarar esto EXPLICITAMENTE en la
   implementacion, porque "autoejecucion completa" sin esta salvedad
   contradice una regla dura ya existente.

## 6. Propuesta de optimizacion (sintesis, sometida al bucle)

1. Resolver la Seccion 1 (ambiguedad de "a que protocolo dispara cada
   trigger") y la Seccion 5.2 (unidad del 25%) con el usuario ANTES de
   escribir una sola linea de codigo -- ninguna de las dos es una decision
   tecnica, son de PRODUCTO.
2. Leer `orchestrator_session_close_full_audit_design.md` completo antes de
   decidir cual de los dos prompts de cierre gobierna el caso automatico
   (Seccion 4).
3. Implementar el Trigger A (cuota) primero -- es el de menor incertidumbre
   tecnica (extiende `cc-usage-monitor.ps1`, mecanismo ya probado) y puede
   entregar valor sin esperar a resolver la heuristica de contexto.
4. Implementar el Trigger B (contexto) con la heuristica de transcript
   (opcion 1 de la Seccion 2), declarada explicitamente como APROXIMADA, con
   un umbral configurable, nunca un numero cristalizado.
5. Anadir la guarda de idempotencia del punto 4 de la Seccion 5 ANTES de
   activar ambos triggers en produccion -- es la unica barrera de seguridad
   que falta para que "autoejecucion completa" no se convierta en doble
   ejecucion.
6. Declarar explicitamente en el codigo/prompt que el gate de "Push por
   vuelo" sigue vigente sin excepcion (punto 5 de la Seccion 5).
7. Anadir la ventana de cortesia de 5 min (Seccion 3) como capa
   independiente, reusable por ambos triggers -- no duplicar la logica de
   notificacion+`ScheduleWakeup` en cada uno.

## 7. Bucle adversarial corrido (5 lentes con resultado; 4 intentos fallidos por infra/cuota de proveedor, no por contenido)

**Backends:** mistral/mistral-large-latest, codex/gpt-5.6-luna, opencode
nan/gemma4, opencode nan/deepseek-v4-flash -- completados. opencode
nan/qwen3.8-flash -- lanzado, sin resultado al cierre de este documento.
GLM (2 intentos: `nan/glm5.3` sin acceso de API key; `aihubmix/coding-glm-5.3-free`
cuota free agotada) y Google (2 intentos: `google/gemini-3.5-flash` sin
`GOOGLE_GENERATIVE_AI_API_KEY`; `openrouter/google/gemini-3.5-flash` sin
creditos para el `max_tokens` pedido) -- fallidos por infraestructura del
proveedor, NO reintentados mas alla de 2 intentos cada uno (diminishing
returns frente a 4 veredictos ya convergentes).

**Veredicto: 4/4 ADOPTAR CON CAMBIOS.** Las 4 lentes completadas coinciden en
declarar BLOCKER tanto la ambiguedad de la Seccion 1 como la unidad del 25%
de la Seccion 5.2 -- confirmando que NO eran matices menores, sino decisiones
de producto que de verdad bloqueaban la implementacion.

**Hallazgo mas severo (solo DeepSeek, B1):** `PreCompact` dispara cuando el
contexto YA esta casi agotado en la practica (<10%, segun la lente). Medir
"25% restante" EN ESE EVENTO hace que la rama "ligero, hay margen" del diseno
original sea codigo muerto por construccion -- el umbral nunca se cumpliria
"con margen" porque para cuando el evento dispara, el margen ya es minimo.
Esto por si solo invalidaba la Tabla de la Seccion 1 tal como estaba escrita,
independientemente de que el usuario resolviera la ambiguedad de lectura.

**Otros hallazgos convergentes de 2+ lentes (no solo repeticion, cada uno
anadio matiz):**
- Maquina de estados de idempotencia con lock/lease (no solo "un fichero de
  estado") -- codex, gemma4, mistral.
- Guarda anti-oscilacion/ping-pong entre cuentas con `max_hops` + cooldown --
  codex, deepseek.
- La salvedad "nunca saltar el push" es correcta pero incompleta: falta
  cubrir auto-commit del cierre canonico, y que pasa si la sesion vieja no
  muere tras el salto (riesgo de doble-commit/doble-push) -- codex, deepseek.
- El actor que ejecuta el salto no estaba definido -- deepseek (B2): con la
  cuota ya agotada, el propio LLM de la cuenta origen no puede ejecutar su
  propio cierre; el salto debe correrlo un supervisor fuera de banda
  (equivalente a `cc-watch`), no el agente.
- "Cuota agotada a mitad de vuelo" no es "fin del vuelo" -- deepseek (B3): el
  cierre canonico completo (con suite+auditoria) es desproporcionado y
  arriesgado justo cuando la cuota escasea mas. Para el caso de cuota baja A
  MITAD de vuelo, usar un checkpoint ligero (STATE+work_plan+ledger+commit
  WIP), reservando el cierre canonico completo para el caso "cuota agotada Y
  el vuelo ya estaba en su frontera de cierre".

## 8. Resolucion del usuario (post-bucle) -- aplicada a esta propuesta

1. **Trigger B (contexto/compactacion):** la compactacion SIEMPRE dispara
   `session_hop.md` (continuidad ligera, misma cuenta). El cruce de cuenta
   NUNCA lo decide el contexto -- solo lo decide el Trigger A (cuota). Esto
   resuelve de raiz el hallazgo B1 de DeepSeek: ya no hay umbral de contexto
   compitiendo con el momento en que `PreCompact` dispara, porque el
   contexto ya no decide cruces de cuenta.
2. **Unidad del 25%:** CONTEXTO restante de la sesion actual (no cuota),
   confirmado explicitamente por el usuario. Dado el punto 1, este umbral ya
   NO decide una escalada a cruzado -- su uso remanente es decidir CUANDO
   disparar `session_hop` de forma PROACTIVA (antes de que `PreCompact`
   fuerce la compactacion), no solo reactivamente al evento. Para medirlo,
   aplicar la recomendacion de DeepSeek (opcion 3a, superior a la heuristica
   caracteres/4 originalmente propuesta): leer los tokens de `usage` que el
   transcript de Claude Code ya registra por mensaje (`input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`), comparados
   contra la ventana del modelo activo -- no aproximar por longitud de
   caracteres.
3. **Trigger A (cuota) queda como unico camino al protocolo pesado**
   (cierre canonico + salto cruzado), matizado por el hallazgo B3 de
   DeepSeek: si la cuota cae a mitad de vuelo (no en su frontera natural de
   cierre), usar checkpoint ligero + handoff, reservando el cierre canonico
   completo para cuando el vuelo este en su frontera de cierre de todos
   modos.

## 9. Pendiente para la siguiente pasada de diseno (no cerrado en este documento)

**6a lente (qwen3.8-flash) llego tras el cierre del punto 8 -- anadio 2
hallazgos BLOCKER/criticos que NINGUNA de las otras 5 lentes vio, verificados
contra lineas reales del repo y contra el transcript JSONL en vivo de esta
propia sesion (no auto-relato):**

- **RIESGO MAS SEVERO, no cubierto por ninguna guarda propuesta hasta ahora:**
  `PreCompact` NO detiene la sesion que lo dispara -- la sesion vieja sigue
  ejecutando su turno despues del evento. Si se lanza la sesion nueva
  (session_hop o cruzada) sin terminar la vieja, hay DOS escritores sobre el
  mismo ticket (doble commit, doble suite, y en el caso cruzado, consumo de
  cuota en AMBAS cuentas a la vez). Ninguna de las guardas de idempotencia
  propuestas (lock/lease por handoff) cubre esto, porque la sesion vieja
  nunca vuelve a consultarla -- simplemente sigue. Vias de terminacion a
  evaluar (ninguna implementada): (i) bloquear la compactacion desde el
  propio hook con exit code (verificar contra la doc de hooks de Claude Code
  vigente antes de fijarlo); (ii) exigir que la sesion detonante cierre su
  turno (`Stop`) y el hop tome el relevo; (iii) un lease por ticket que la
  sesion vieja compruebe en `PreToolUse` antes de cualquier escritura.
- **`ScheduleWakeup` (la ventana de cortesia de 5 min, Seccion 3) asume una
  primitiva que NO existe como mecanismo del motor:** verificado por grep,
  solo aparece en este mismo documento (3 hits). Es una herramienta
  disponible para un agente Claude Code en turno activo (como yo, ahora
  mismo) -- no hay nada en el motor que despierte a un proceso 5 minutos
  despues sin un turno de LLM corriendo. En un vuelo autonomo sin nadie
  despierto, el portador del timer tiene que ser un proceso externo con
  reloj propio (familia `cc-watch`), no el propio agente. Alternativa
  honesta para v1: notificar y ejecutar inmediatamente, sin ventana de
  reintento.
- Formula mas precisa para leer el contexto real (refina la opcion 3a de
  DeepSeek, Seccion 8.2): `% contexto ~= (input_tokens + cache_read_input_tokens
  + cache_creation_input_tokens del ULTIMO mensaje assistant) / ventana del
  modelo activo` -- `input_tokens` NO es acumulado, los campos de cache SI se
  suman; no hardcodear el tamano de ventana (varia por modelo/beta). Validar
  la formula contra un transcript real y contra `/context` antes de fijar
  cualquier umbral.
- Riesgo adicional: `scripts/check_manager_role_for_suite.py` (WOT-2026-117a,
  cableado en `run_pytest_safe.py --level all`) bloquea la suite si
  `TURN.md` declara un rol no-Manager -- un cierre automatico disparado desde
  una sesion builder/orchestrator puede chocar con esta barrera; declarar el
  rol o el reenvio explicito.
- El hook `PreCompact` actual tiene un contrato TESTEADO y ligero (solo
  proyeccion de memoria, sin LLM, salida solo-ASCII, `tests/unit/test_pre_compact_hook.py:441`)
  -- anadirle logica de despacho del protocolo pesado es un CAMBIO DE
  CONTRATO de un hook ya testeado, no una reutilizacion gratuita. Declarar y
  someter ese cambio a su propio bucle si se decide esa via.
- Definir el actor fuera de banda del salto (hallazgo B2 DeepSeek) -- quien
  ejecuta el cambio de cuenta cuando la sesion origen ya no puede llamar al
  modelo.
- Disenar la maquina de estados de idempotencia (lock/lease, CON dueno/TTL/
  reconciliacion al arrancar -- qwen3.8-flash H9) y la guarda anti-oscilacion
  (`max_hops`+cooldown), con regla de desempate explicita: Trigger A (cuota)
  gana sobre Trigger B (contexto) si colisionan.
- Cerrar el alcance exacto de la excepcion de push (auto-commit vs
  auto-push, y que pasa si la sesion vieja sigue viva).

## 10. Correccion de conteo (Seccion 0, hallazgo H10 qwen3.8-flash)

El titulo de la Seccion 0 decia "5 prompts gobernantes, no 2" pero el cuerpo
listaba 6 filas y el usuario cito 4 (no 2). Conteo correcto: el usuario cito
4 (`orchestrator_session_close_full_audit.md`,
`orchestrator_session_close_full_audit_design.md`,
`orchestrator_child_dispatch_multiticket_multibackend_unlimited.md`,
`orchestrator_child_dispatch_cross_claude.md`); esta propuesta anadio 2 mas
por relevancia directa (`session_hop.md`, `orchestrator_session_close_chat.md`)
-- total 6 prompts gobernantes, no 5.

## 11. Veredicto final del bucle (6 lentes, 5 con resultado)

**5/5 ADOPTAR CON CAMBIOS**, ninguna en RECHAZAR puro. mistral, codex y
gemma4 confirman los 2 BLOCKER originales (Seccion 1, unidad del 25%).
DeepSeek anade los hallazgos B1-B3 que invalidaron el diseno original de
Trigger B (ya resueltos por la decision del usuario en la Seccion 8).
qwen3.8-flash, la ultima en llegar, es la mas rigurosa de las 6 (unica que
verifico contra lineas reales del repo y contra el transcript JSONL en
vivo) y encuentra el riesgo mas severo no cubierto por ninguna otra lente
(vieja-sesion-vs-nueva, punto de arriba) ademas de invalidar la primitiva
`ScheduleWakeup` tal como estaba propuesta. **Este documento queda como BASE
de diseno, NO como spec lista para implementar** -- faltan por resolver, como
minimo: la via de terminacion de la sesion vieja, el portador real del timer
de cortesia, y la maquina de estados de idempotencia con ciclo de vida
completo.
