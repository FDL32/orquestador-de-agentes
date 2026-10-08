---
role: manager
cycle_phase: [F1-backlog, F2-contrato, F3-auditoria-contrato, F4-lanzamiento, F6-revision]
route_kind: modo
---
# Prompt: Bucle Manager-Builder ligero sobre el backlog (filtro -> ticket -> Builder -> revision)
<!-- PROMPT-SUMMARY
what: Bucle Manager->Builder ticket a ticket sobre una SERIE filtrada del backlog (por tema, [LINEA: ...] o grep libre), con reglas de parada explicitas y metricas de mejora continua por iteracion, antes del push.
when: Cuando hay que cerrar una familia de tickets relacionados (misma LINEA, mismo subsistema) sin la ceremonia de un batch autonomo con DAG formal.
not: NO es orchestrator_autonomous_ticket_batch.md (ese exige DAG fresco de /backlog-triage y gate start_context_isolation resuelto por tercero); NO sustituye backlog_triage.md para decidir que pipeline lanzar sobre el backlog COMPLETO; NO es manager_orchestrator_loop.md (ver seccion 0 de relacion con ese nucleo).
-->

contract_id: cid-manager-orchestrator-loop-backlog-v1
source_of_truth: prompts/manager_orchestrator_loop.md (nucleo) para las reglas de
validez 1/2/4/6 (seccion 4) y el esquema de metricas M3 (seccion 6 de este prompt,
que REUSA el `SCHEMA: adjudicacion` del nucleo). Este prompt es `source_of_truth`
SOLO para lo que le es propio: el vocabulario de serie/ticket (seccion 1), la
ausencia de votacion por lentes (seccion 2), los 6 pasos del bucle ligero
(seccion 5), y las EXCEPCIONES explicitamente declaradas que NO se remiten: la
regla de validez 3 (contador GLOBAL de reintentos por ticket, corregida por bucle
de gobierno real) y la regla de validez 5 (hueco N8 declarado, propio de este
bucle). **Las secciones donde el objeto del hijo difiere del nucleo (regla 3,
regla 5) se mantienen INTEGRAS en este prompt y NO se remiten al nucleo** bajo
ninguna circunstancia; cualquier redaccion futura que elimine esta excepcion
reintroduce el riesgo de perder esas correcciones (adoptado tras bucle de
gobierno con 5 lentes independientes, 2026-10-08).
nucleo_referenciado: prompts/manager_orchestrator_loop.md (contract_id
cid-manager-orchestrator-loop-v1) -- ESTE prompt REMITE a su ESTRUCTURA y REUSA su
vocabulario/schemas donde el objeto coincide (ver seccion 0); donde el objeto
difiere (tickets del backlog, no planes/estrategias) o donde existe una
correccion local (regla 3, regla 5), este prompt declara la seccion como
ESPECIALIZACION explicita y la mantiene completa, sin redefinir en paralelo lo
que ya remite.

Origen: sesion 2026-10-08, verificado con bucle de gobierno real (Codex BA05 +
2 lentes `nan` con filesystem real via Kilo headless), 3/3 veredictos `ADOPTAR CON
CAMBIOS` convergentes en que faltaban reglas de parada explicitas; reestructurado
despues para copiar el esqueleto del nucleo en vez de una adaptacion ligera.
**Revision posterior (sesion 2026-10-08, bucle de gobierno DESIGN_REVIEW con 5
lentes independientes -- nan/qwen y nan/gemma con filesystem real via Kilo,
groq/qwen, nvidia/nemotron y cohere/command sin filesystem -- 5/5 ADOPTAR CON
CAMBIOS): este prompt REDECLARABA integramente las reglas de validez 1/2/4/6 y el
schema de metricas del nucleo en vez de REMITIR, violando el principio "skill
apunta, prompt gobierna" (AGENTS.md, X-09) un nivel arriba del caso que esa norma
cubria. Corregido aqui: las secciones compartidas REMITEN; las EXCEPCIONES (regla
3, regla 5) permanecen explicitas.

## 0.pre Como arrancar (anti-exploracion; adoptado tras bucle de gobierno 2026-10-08)

Esta seccion existe porque el adaptador del nucleo
(`manager_orchestrator_loop_adapter_motor.md`, seccion 0) ya resolvio el mismo
sintoma para su propio prompt -- una sesion gasto ~350k tokens explorando el
repo antes de lanzar nada -- y esa correccion no se habia propagado aqui. Si te
pegaron este prompt sin un objetivo adjunto, el documento no te dice que hacer:
te dice COMO ejecutar un bucle una vez que ya sabes QUE serie de tickets vas a
limpiar.

1. **Declara la serie con esta forma ANTES de cualquier otra cosa** (el humano
   la rellena, o la pides con estas tres lineas exactas si faltan):

       OBJETIVO: <una frase: que serie de tickets vas a filtrar y cerrar>
       ALCANCE: <el criterio exacto: [LINEA: <nombre>] o el grep libre sobre el backlog>
       ENTREGABLE: <cada ticket de la serie termina en APPROVE o BLOCKED, con su entrada M3>

   Sin estas tres lineas, el paso 1 de la seccion 5 (Filtrar) no se puede
   ejecutar: necesita saber QUE criterio aplicar sobre el backlog. **No
   explores el backlog entero ni el repo** (leer todas las fichas, censar
   subsistemas) mientras falte cualquiera de las tres -- pidelas primero.
2. **Si el humano NO tiene un criterio concreto** ("limpia lo que haga falta",
   "mira que hay pendiente"): no te quedes parado pidiendo mas detalle
   indefinidamente. Cae a **sesion generica**: usa `skills/backlog-triage/SKILL.md`
   (modo lectura, propone candidatos y agrupa por LINEA). Su resultado rellena
   el ALCANCE de arriba antes de congelar la serie -- la sesion generica
   PRODUCE el criterio, no lo sustituye.
3. **Con la serie ya declarada:** NO releas `builder_invocation_contract.md`,
   `orchestrator_pipeline_codeonly.md` ni `manager_review.md` enteros para
   recordar un comando -- ya estan resueltos en la seccion 3 (contrato de
   capacidades) de este prompt. Si dudas si tu ticket necesita revision
   adversarial de lentes (no la tiene este bucle por defecto), la tabla de
   `builder_invocation_contract.md` seccion 0 resuelve esa duda puntual; no
   inventes un mecanismo nuevo.
4. **Si el objetivo es ambiguo** ("mejora estos tickets", "revisalos todos"):
   no lo tomes por concreto al azar ni lo descartes como vacio. Pide
   aclaracion con UNA pregunta especifica. Si tras dos intentos sigue sin
   concretarse, cae al fallback del punto 2.
5. **No releas rutas que ya estan declaradas** en la seccion 3 (contrato de
   capacidades) o la seccion 4 (reglas de validez). Explorar de mas cuesta el
   contexto que el bucle necesita para las iteraciones reales.

> **Nota de M4 (declarada tras bucle de gobierno, 4/5 lentes la pidieron):**
> esta seccion y la tabla de capacidades (seccion 3) son senal de ENRUTADO
> rapido, no exencion de lectura. M4 (`AGENTS.md`, "Prompt/contrato citado =>
> LEELO ENTERO") sigue aplicando intacto cuando vayas a REDACTAR contra un
> contrato citado (p.ej. `orchestrator_pipeline_codeonly.md` antes de lanzar un
> Builder) o a adjudicar sobre el. Si queda cualquier duda tras el enrutado,
> abre el contrato completo antes de proceder.

## 0. Que es y relacion con `manager_orchestrator_loop.md`

**Si buscas el nucleo portable de bucles de revision ADVERSARIAL (estrategia ->
planes -> prompt del ejecutor, con lentes que votan), es
`prompts/manager_orchestrator_loop.md`, NO este fichero.** Comparten estructura y
vocabulario a proposito -- este prompt es una ESPECIALIZACION del mismo patron
para un objeto distinto:

| | `manager_orchestrator_loop.md` (el nucleo) | Este prompt |
|---|---|---|
| Objeto del bucle | una ESTRATEGIA, sus PLANES, el PROMPT del ejecutor -- bucle de revision ADVERSARIAL con lentes que votan | una SERIE DE TICKETS del backlog -- bucle OPERATIVO Manager->Builder, sin votacion adversarial |
| Unidad de iteracion | un plan / una propuesta | un ticket |
| Cuando se usa | diseñar o auditar un proceso/propuesta ANTES de que exista como tickets | limpiar una familia de tickets YA EXISTENTE en el backlog |
| Roles que votan | LENTE cuenta como voto, identidad distinta del autor exigida | no hay votacion: MANAGER_REVIEW es la unica revision, un solo rol |
| Fases | 11 fases (OBJETIVO...ESCALADO) | 6 pasos (filtrar...siguiente), ver seccion 5 |

Si tienes dudas sobre cual aplica: si el objeto a revisar es un PROMPT o una
ESTRATEGIA todavia sin ejecutar, usa el nucleo. Si el objeto es un TICKET del
backlog que ya existe, usa este prompt.

Tres formas de uso (igual que el nucleo, seccion 0): (1) pegar este prompt como
arranque del Manager y rellenar el perfil a mano; (2) cargarlo desde una skill que
lo apunta con su hash; (3) una herramienta del sistema que hace el preflight y
registra. Hoy este repo usa la forma (1): invocacion directa por chat.

## 1. Vocabulario

| Termino | Que es |
|---|---|
| serie | el conjunto de tickets del backlog seleccionados por el filtro del paso 1 de la seccion 5, CONGELADO como snapshot al momento del filtrado |
| ticket | la unidad de iteracion de este bucle (equivalente al "plan" del nucleo) |
| MANAGER | orquesta la serie, filtra, reconcilia, adjudica el cierre de cada ticket. Nunca implementa directamente salvo modo implementador=manager (seccion 8) |
| EJECUTOR (Builder) | implementa el ticket. Su informe no es evidencia; lo son el diff y el artefacto (igual que el nucleo, seccion 2) |
| MANAGER_REVIEW | la unica revision de cada ticket -- NO hay votacion de lentes de identidad distinta, a diferencia del nucleo |
| BLOCKED | estado terminal de un ticket que agoto sus reintentos sin cerrar; permanece en el backlog con la evidencia del motivo |
| NO_CANDIDATES | resultado legitimo del paso 2 (reconciliacion) cuando ningun ticket de la serie sigue siendo valido |
| evidencia | comando+exit-code, cita `ruta:linea`, o artefacto -- NUNCA una impresion sin verificar (mismo gate CEM v0 que el resto del repo) |

### 1.1 Niveles de evidencia (heredados del nucleo, seccion 1.2)

- **(a)**: observada en dos o mas casos/iteraciones independientes.
- **(b)**: observada en un unico caso.
- **(c)**: hipotesis, pendiente de confirmar.

Toda regla de este prompt que cite un nivel lo conserva al citarse en otro sitio
(mismo contrato que el nucleo).

## 2. Roles

- **MANAGER**: orquesta la serie (filtra, reconcilia, decide BLOCKED/reintento),
  lanza al Builder, adjudica MANAGER_REVIEW. Es el humano-en-el-loop de cada
  iteracion -- a diferencia del nucleo, no requiere gate de aislamiento de tercero
  porque el Manager YA es la supervision.
- **EJECUTOR (Builder)**: implementa un ticket. Su informe de salida no es
  evidencia por si solo; lo son el diff, el commit y el log (igual que el nucleo).
- **USUARIO**: decide si aplicar las propuestas del informe de automejora
  (seccion 7), si autorizar el push, y resuelve el escalado si una serie queda
  `ESTANCADA` (seccion 7.4).

**Diferencia deliberada con el nucleo (seccion 2 de alli):** no existe el rol
LENTE aqui. MANAGER_REVIEW es la unica revision -- un solo rol decide, sin
votacion de identidades distintas. Si una revision por lentes adversariales fuera
necesaria para un ticket concreto (p.ej. un cambio de alto riesgo), eso se
resuelve invocando el nucleo (`manager_orchestrator_loop.md`) para ESE ticket
puntual, no generalizando la votacion a toda la serie.

## 3. Contrato de capacidades

Capacidades que este bucle necesita, en los terminos del repo (no el lenguaje
generico del nucleo, porque este prompt ya es especifico de `orquestador_de_agentes`):

| Capacidad | Como se cubre en este repo | Si falta |
|---|---|---|
| FILTRO_BACKLOG | `grep`/lectura de `<destino>/.agent/collaboration/backlog.md` + `_archive/backlog_done.md` por `[LINEA: ...]` o texto libre | sin filtro declarado, la serie no esta definida -- STOP |
| RECONCILIACION | Paso 0 de `backlog_triage.md` aplicado al subconjunto filtrado | sin reconciliar, un ticket ya-hecho entra al bucle por error |
| CONTRACT_FORMATION | `orchestrator_prepare_and_launch_ticket.md` + `audit_cf_ticket_contract.md` + `scripts/validate_contract_formation.py` | el ticket no puede prepararse sin contrato valido |
| LANZAMIENTO | `orchestrator_pipeline.md` (modo destino) o `orchestrator_pipeline_codeonly.md` (modo motor), segun `is_motor_code_only()` CON `AGENT_PROJECT_ROOT` exportada | modo equivocado produce commits en el repo que no corresponde |
| REVISION | `manager_review.md`, fase MANAGER_REVIEW | sin revision, un ticket con `CHANGES` real se cerraria igual |
| REGISTRO_METRICAS | entradas M3 (seccion 6) escritas en memoria de la sesion, compiladas al cierre en `.agent/planning/INFORME_automejora_<serie>_<fecha>.md` | sin registro, la seccion 7 (automejora) queda vacia y sin evidencia |
| EVIDENCIA_CIERRE | commit por ticket, `git diff --stat`, exit codes de los gates | sin VCS no hay cierre verificable |

## 4. Reglas de validez del bucle

Las reglas 1, 2, 4 y 6 de esta seccion REMITEN al nucleo (`manager_orchestrator_loop.md`
seccion 4, reglas de validez 1-7) -- aplican IGUAL, sin redeclaracion de texto: la
regla de congelar la serie al filtrar, la de reconciliar antes de procesar, la de
que un estado terminal escribe su entrada de metrica antes de avanzar, y la
condicion de terminacion por lista completa recorrida. **Las reglas 3 y 5 son
EXCEPCIONES propias de este bucle, NO remitidas, porque el objeto (tickets con
reintentos de Contract Formation/Review) no tiene contraparte en el nucleo
(que opera sobre planes/estrategias, no sobre contadores de reintento de
ticket):**

3. **Reintentos tienen tope, y el tope es un CONTADOR GLOBAL POR TICKET, no por
   fase.** 2 **intentos totales** (el primero + 1 reintento, nunca "1 + 2") en la
   SUMA de Contract Formation + MANAGER_REVIEW para ese ticket antes de
   `BLOCKED`. Builder: 1 reintento antes de `BLOCKED`, contador propio. (b)
   **Correccion tras bucle de gobierno (nvidia/glm-flash BA21, 2026-10-08,
   hallazgo A): la version anterior contaba "2 intentos por fase" (Contract Y
   Review, cada uno con su propio contador de 2), lo que permite que un ticket
   oscile Contract(falla)->Review(falla, reset re-preparo)->Contract(falla
   otra vez)... indefinidamente sin agotar NUNCA ningun contador individual.**
   El re-preparo de un ticket tras un `CHANGES` de Review consume el MISMO
   contador que ya gasto Contract Formation, no uno nuevo. Sin esto, "tope"
   es cosmetico: el ticket nunca muere. **Esta regla NO se remite al nucleo
   bajo ninguna circunstancia** (verificado por bucle de gobierno de 5 lentes
   independientes, 2026-10-08: el nucleo no tiene logica de reintentos de
   ticket, asi que remitir esta regla la perderia).
5. **N8 del nucleo aplica por TICKET, no por serie:** los hallazgos adoptados de
   un ticket se aplican en UN commit, y ese commit es el ancla de su propia
   verificacion (gates + suite). No se abre un commit por hallazgo dentro de un
   mismo ticket. (b)
   - **HUECO DECLARADO, no resuelto (hallazgo de bucle de gobierno, Gemini
     BA110, 2026-10-08):** N8 en el nucleo describe bucles que CIERRAN con
     hallazgos adoptados; no dice que hacer con los commits de intentos
     fallidos de un ticket que termina `BLOCKED` tras agotar sus reintentos
     (regla 3). Si un intento parcial dejo un commit en el historial antes de
     marcar `BLOCKED`, ese commit NO tiene un bucle de verificacion que lo
     ancle -- posible violacion de N8 por un caso que N8 no contemplaba. **No
     resuelto en esta version**: antes de usar este bucle en un ticket donde
     un reintento fallido pueda generar un commit intermedio, decide
     explicitamente si (a) el reintento NUNCA commitea hasta el intento que
     cierra con `APPROVE` (revert entre intentos), o (b) se acepta un commit
     por intento con su propio ancla de verificacion parcial. Declarar la
     decision tomada antes de empezar la serie, no durante.

## 5. El bucle (6 pasos + reglas de parada por paso)

1. **Filtrar.** Ir al backlog y seleccionar una SERIE de tickets por un criterio
   textual explicito: el campo `[LINEA: <nombre>]` (preferido si existe, mas
   preciso que un grep libre) o un `grep` libre sobre un tema. **Declara el
   criterio exacto usado** (no lo dejes implicito) y la serie resultante.
   - Regla de validez 1 (seccion 4): la serie se congela aqui.

2. **Reconciliar.** Para cada ticket de la serie congelada, aplicar el Paso 0 de
   `backlog_triage.md`. Si un ticket ya no es valido, EXCLUIRLO y continuar.
   - **Si tras reconciliar TODA la serie no queda ningun ticket valido:**
     terminar el bucle y reportar `NO_CANDIDATES` (0 tickets procesados). Es un
     resultado legitimo, no un fallo -- declararlo, no silenciarlo.

3. **Preparar el ticket.** `orchestrator_prepare_and_launch_ticket.md` (Contract
   Formation si no tiene `ticket_contract`, o directo a `work_plan.md` si ya esta
   `frozen`).
   - **Si el contrato no supera su auditoria** (`audit_cf_ticket_contract.md` da
     `CHANGES`, o `scripts/validate_contract_formation.py --tickets <ruta>` da
     `rc != 0`): reintentar con el feedback, tope 2 intentos (regla de validez 3).
     Si se agota: `BLOCKED` en el backlog con evidencia, continuar con el
     siguiente.

4. **Lanzar al Builder.** `orchestrator_pipeline.md` (destino) o
   `orchestrator_pipeline_codeonly.md` (motor code-only) segun
   `is_motor_code_only()` con `AGENT_PROJECT_ROOT` exportada.
   - **Si el Builder falla a mitad:** no avanzar sin resolver. Registrar,
     reintentar una vez (regla de validez 3), si persiste `BLOCKED` y continuar.

5. **Revisar la entrega.** `manager_review.md`, fase MANAGER_REVIEW.
   - **Si el veredicto es `CHANGES`:** reintentar con el feedback, tope 2
     intentos. Si se agota, `BLOCKED` y continuar.
   - **Antes de cerrar ESTE ticket (obligatorio):** registra la entrada de
     metrica de la seccion 6 sobre la iteracion que acaba de terminar.

6. **Siguiente ticket.** Volver al paso 3 con el siguiente ticket de la serie
   congelada, hasta agotarla (regla de validez 6).

## 6. Esquema ejecutable: entrada de metrica por iteracion

**REMITE al `SCHEMA: adjudicacion` del nucleo** (`manager_orchestrator_loop.md`
seccion 7) -- mismos campos `required`, mismos `enum`, misma regla de que una
entrada sin `evidencia` verificable se descarta. **Diferencia DECLARADA, no
redeclaracion:** este bucle no vota con lentes de identidad distinta (seccion 2),
asi que sustituye los 3 campos especificos de esa votacion
(`lente_pedida`/`lente_que_respondio`/`identidad`) por 2 campos propios que
identifican la iteracion sin votacion (`ticket_id`/`rol_que_actuo`); el resto de
campos del schema del nucleo (`hallazgo`, `tipo`, `verificacion`, `efecto`,
`correcto`, `util`, `adoptado`, `motivo`) se mantienen IDENTICOS, y se anaden
`prompt_senalado`/`evidencia` (ya presentes en el espiritu del nucleo, seccion
1.2) para que el informe de cierre (seccion 7.2) pueda calcular una tasa de
adopcion real.

```json
{
  "type": "object",
  "required": ["ticket_id", "rol_que_actuo", "hallazgo", "tipo", "verificacion", "efecto", "correcto", "util", "adoptado", "motivo", "prompt_senalado", "evidencia"],
  "properties": {
    "ticket_id": {"type": "string", "minLength": 1},
    "rol_que_actuo": {"type": "string", "enum": ["MANAGER", "EJECUTOR"]},
    "hallazgo": {"type": "string", "minLength": 1},
    "tipo": {"type": "string", "enum": ["hecho", "preferencia", "diseno"]},
    "verificacion": {"type": "string", "enum": ["comando", "cita", "no_verificable"]},
    "efecto": {"type": "string", "enum": ["cambia-objeto", "cambia-decision", "historico", "descartado"]},
    "correcto": {"type": "boolean"},
    "util": {"type": "boolean"},
    "adoptado": {"type": "boolean"},
    "motivo": {"type": "string"},
    "prompt_senalado": {"type": "string", "minLength": 1},
    "evidencia": {"type": "string", "minLength": 1}
  }
}
```

**EJEMPLO BUENO:**

```json
{
  "ticket_id": "WOT-2026-070v",
  "rol_que_actuo": "EJECUTOR",
  "hallazgo": "el paso 3 (Contract Formation) no decia donde buscar el ticket_contract si ya existia pero en status draft, no frozen",
  "tipo": "diseno",
  "verificacion": "cita",
  "efecto": "cambia-objeto",
  "correcto": true,
  "util": true,
  "adoptado": true,
  "motivo": "el hueco se reprodujo citando la linea exacta",
  "prompt_senalado": "prompts/orchestrator_prepare_and_launch_ticket.md",
  "evidencia": "ticket_contracts.md:142, status: draft sin indicacion de proximo paso"
}
```

**EJEMPLO MALO -- sin evidencia verificable (se descarta, no cuenta):**

```json
{
  "ticket_id": "WOT-2026-070v",
  "rol_que_actuo": "MANAGER",
  "hallazgo": "me parecio que el Builder tardo mas de lo normal",
  "tipo": "preferencia",
  "verificacion": "no_verificable",
  "efecto": "descartado",
  "correcto": false,
  "util": false,
  "adoptado": false,
  "motivo": "sin evidencia, no se adopta",
  "prompt_senalado": "",
  "evidencia": ""
}
```

Igual que el nucleo (seccion 1.2): una entrada sin `evidencia` verificable es una
opinion, no una observacion -- se descarta, nunca entra al informe compilado.

## 7. Automejora por iteracion e informe antes del push

**Principio: propone, nunca implanta.** Mismo patron que
`orchestrator_session_close_full_audit.md` Bloque 2.5.j ("PROCESS IMPROVEMENT
PROPOSAL... SOLO PROPONE") y que la fase MEJORA del nucleo (seccion 5 de alli, y
su seccion 8 de metricas), aplicado aqui a nivel de UNA iteracion en vez de a un
ciclo completo de planes.

### 7.1 Recoleccion continua (barata, por iteracion)

Tras el MANAGER_REVIEW de cada ticket (paso 5 de la seccion 5), antes de pasar al
paso 6, registra UNA entrada del schema de la seccion 6 si en ESA iteracion
aparecio alguna de estas senales:

- **Friccion de ejecucion:** un paso del bucle (seccion 5) resulto ambiguo, o el
  Builder/Manager tuvo que improvisar algo que el prompt no cubria.
- **Interrelacion entre agentes:** un handoff entre Manager y Builder (o entre
  este bucle y otro prompt que invoca: `orchestrator_prepare_and_launch_ticket.md`,
  `orchestrator_pipeline.md`, `manager_review.md`) fallo, fue lento, o exigio
  contexto que no viajaba en el artefacto.
- **Ruptura de vuelo:** la iteracion se detuvo por algo que el bucle NO
  anticipaba (no cubierto por las reglas de validez de la seccion 4).
- **Punto de mejora:** algo que funciono pero de forma subobtima.

Estas 4 clases se mapean al campo `hallazgo` libre del schema; el campo `tipo`
(`hecho`/`preferencia`/`diseno`) ya las clasifica, no necesitan su propio enum.

### 7.2 Compilacion del informe (al cerrar la serie, antes del push)

Cuando la serie congelada se agota (seccion 5, condicion de terminacion),
compila TODAS las entradas de metrica en:

```
<destino>/.agent/planning/INFORME_automejora_<serie>_<fecha>.md
```

Estructura:

```markdown
# Informe de automejora -- serie "<criterio de filtro>" (<fecha>)

## Resumen de la serie (equivalente a "metricas por ciclo" del nucleo, seccion 8)
- Tickets en la serie congelada: <N>
- Cerrados (APPROVE): <N>
- BLOCKED (reintentos agotados): <N>
- Excluidos en reconciliacion (ya hechos/duplicados): <N>
- Reintentos usados por ticket (min / mediana / max)
- Incidentes de agente (Builder mudo, sin entregable, fallo de transporte): <N>

## Entradas de metrica recogidas (schema seccion 6, una fila por entrada de 7.1)

| Ticket | rol_que_actuo | hallazgo | tipo | verificacion | prompt_senalado |
|---|---|---|---|---|---|

## Propuestas de mejora (agrupadas por prompt_senalado)

### <prompt/template X>
- **Clase:** `prompt_refactor` | `skill_refactor` | `script_guard` |
  `handoff_prompt_defect` (vocabulario de
  `orchestrator_session_close_full_audit.md` Bloque 2.5.j -- no redefinir aqui).
- **Cambio propuesto:** <texto exacto o diff sugerido, no solo la idea>
- **Evidencia que lo sostiene:** <las filas de la tabla de arriba que lo motivan>
- **Umbral de aplicacion:** si la MISMA friccion aparecio en >=3 iteraciones de
  series DISTINTAS, candidato fuerte (mismo umbral que `prompt_override` de
  `orchestrator_session_close_full_audit.md` 2.5.d). Una friccion de UNA sola
  iteracion se declara igual, con menor prioridad.

## Veredicto
Esta serie NO aplica ningun cambio por si misma. Las propuestas quedan para que
el usuario decida (a) aplicarlas en un ticket aparte, (b) fichar via
`backlog-admit`, o (c) descartar.
```

**Este informe se presenta al usuario ANTES de cualquier `git push` de los
commits que el bucle genero.** No bloquea el push del trabajo ya revisado; es
informacion para decidir si incorporar alguna mejora ahora o en un ciclo aparte.

### 7.3 Que NO hace esta seccion

- NO edita ningun prompt/template durante el bucle.
- NO ficha automaticamente en el backlog.
- NO sustituye la auditoria de `orchestrator_session_close_full_audit.md` si la
  sesion tambien cierra formalmente -- es complementaria, a nivel de serie.
- NO bloquea el cierre de ningun ticket individual: se recolecta DESPUES de que
  el ticket cerro (paso 5), nunca antes.
- NO vota con LENTES de identidad distinta (exclusivo del nucleo, seccion 2 de
  alli): aqui MANAGER_REVIEW es la unica revision.

### 7.4 Propiedad de mejora continua (nivel (c), pendiente de confirmar)

Igual que el nucleo (seccion 8, "propiedad de mejora continua medible"): si esta
serie es la N-esima pasada sobre la MISMA `[LINEA: ...]`, compara contra el
informe de automejora de la pasada anterior sobre esa linea (si existe) -- los
incidentes repetidos deberian BAJAR y las lecciones preventivas aplicadas
deberian SUBIR. Si no baja, la serie se declara `ESTANCADA` y se escala al
usuario en vez de repetir la misma friccion una tercera vez sin intervencion.

## 8. Modo implementador=manager

Igual que el nucleo (seccion 9): cuando no hay EJECUTOR distinto y el propio
Manager implementa el ticket, se mantienen TODOS los pasos del bucle (seccion 5);
cambia el actor. El paso 5 (MANAGER_REVIEW) lo hace el Manager sobre su PROPIO
diff -- "aplicate tu propia vara": el Manager no adjudica sus propios hallazgos
de la seccion 6 sin evidencia verificable, mismo gate que cualquier otro rol.

## 9. Que NO hacer

- **NO** uses este prompt para series sin acotar (todo el backlog de una vez):
  para eso esta `backlog_triage.md` + `orchestrator_autonomous_ticket_batch.md`.
- **NO** apliques ninguna propuesta del informe de automejora (seccion 7) sin
  que el usuario la apruebe explicitamente.
- **NO** publiques (push) sin que el usuario haya visto el informe de
  automejora, si la serie produjo alguna observacion.
- **NO** proceses tickets `REQUIERE_HUMANO` o `DISENO_PRIMERO` en este bucle
  (mismo limite que el batch autonomo).
- **NO** reimplementes la votacion de lentes del nucleo dentro de este bucle: si
  un ticket concreto necesita revision adversarial, invoca
  `manager_orchestrator_loop.md` para ESE ticket, no generalices al resto de la
  serie.

## 10. Versionado

`contract_id: cid-manager-orchestrator-loop-backlog-v1`. Primera version
publicada. Cambios a los pasos del bucle, las reglas de validez o el schema de
metricas exigen bump de version y nota de migracion una vez publicado (mismo
contrato que el nucleo, seccion 10).
