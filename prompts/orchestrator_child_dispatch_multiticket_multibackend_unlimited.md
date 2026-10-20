---
role: orchestrator
cycle_phase: [F4-lanzamiento, F5-implementacion, F6-revision]
route_kind: modo
status: experimental
---
# Orchestrator Child Dispatch Multiticket Multibackend Unlimited (Capa 0)
<!-- PROMPT-SUMMARY
what: Gobierna una sesion "Capa 0" que orquesta un vuelo autonomo MULTI-TICKET SIN LIMITE, despachando UN Manager-hijo por ticket (Capa 1), MULTI-BACKEND (Claude Code, Kilo, OpenCode), con Manager-hijo organizando Builder/Revisor independientes (Capas 2/3); anade sobre el ejecutor existente lock sostenido del SO anti split-brain (nunca lease/heartbeat con renovacion), registro de lanzamiento e identidad Builder!=Revisor verificable por transporte, decision de workspace por ticket y el paso de integracion antes del push agrupado del vuelo.
when: Cuando un vuelo necesita, ADEMAS del DAG de /backlog-triage, dispatch padre/hijo real por ticket sobre MAS DE UN backend de ejecucion, sin un tope fijo de tickets (no solo el pipeline de un unico backend que ya cubre orchestrator_pipeline.md / orchestrator_pipeline_codeonly.md).
not: NO sustituye ni redeclara el PREDICATE de 9 condiciones, las 8 barreras no negociables, el GROUP_STOP_REPORT ni la maquina de estados de orchestrator_autonomous_ticket_batch.md -- gobierna solo la capa ADICIONAL de dispatch padre/hijo multi-ticket multi-backend. Un vuelo que solo usa UN backend y UN Manager no necesita este prompt.
-->

**[EXPERIMENTAL -- status: experimental, ver frontmatter]** -- diseno congelado
en `.agent/planning/PROPUESTA_orquestador_hijos_multibackend_vuelo_sin_limite_20261020.md`
(v7 al momento de escribir este prompt; secciones 2, 2.1-2.6, 3, 4 y 7 son
load-bearing para este prompt -- la Seccion 5 de la PROPUESTA [suite por
ticket] y la Seccion 8 [handoff/compactacion] siguen vigentes sin cambio,
pero este prompt no las reproduce: se ejecutan exactamente como
`orchestrator_autonomous_ticket_batch.md` y la PROPUESTA ya las definen).
Auditado por 4 rondas de bucle adversarial
previas sobre el diseno (registro de dispatches en el historial de cambios de
la PROPUESTA citada) y por un dispatch de diseno dedicado (`challenger_kilo_gemma`,
BA09, informe sin ruta citable desde este prompt -- ver nota de evidencia
abajo) que confirmo el hueco frente al ecosistema existente y recomendo ESTE
prompt + su skill como artefactos nuevos, en modo experimental, nunca
integrados en el ejecutor existente.

**Nota de evidencia (Ronda 1 de bucle sobre ESTE prompt, 2026-10-20):** las
cifras de auditorias previas citadas arriba describen el diseno ORIGEN
(la PROPUESTA), no son verificables desde el texto de ESTE prompt por un
lector sin acceso al historial de esa PROPUESTA. Tratalas como procedencia
declarada, no como hecho demostrado por este documento.

contract_id: cid-orchestrator-child-dispatch-multiticket-multibackend-unlimited-v1
Skill canonica: skills/orchestrate-child-dispatch-multiticket-multibackend-unlimited/SKILL.md
source_of_truth: this prompt operationalizes
`PROPUESTA_orquestador_hijos_multibackend_vuelo_sin_limite_20261020.md`; if
they diverge, the dated sections of the PROPUESTA cited above prevail for
DESIGN rationale, but the EXECUTABLE gates below (registered here first) are
load-bearing the moment this prompt is used in a real flight. The skill is an
operational pointer only.

**No reemplaza ningun prompt existente.** Es un gobierno ADICIONAL que se
APILA sobre el ejecutor ya canonico cuando el vuelo necesita multi-backend
parent/child dispatch real:

```
/backlog-triage                              (READ-ONLY, sin cambios)       -> produce el DAG
/autonomous-ticket-batch                     (sin cambios, mismo PREDICATE) -> consume el DAG, cierra tickets
   `-- ESTE PROMPT se inserta DENTRO de "por ticket: orchestrator_launch_builder.md (Builder)"
       cuando ese ticket requiere un Manager-hijo propio en un backend distinto
       del que ejecuta el ejecutor de batch, en vez del lanzamiento de Builder
       de UN solo backend que ese prompt ya cubre.
```

Si el vuelo entero cabe en UN solo backend con el pipeline canonico existente
(`orchestrator_pipeline.md` / `orchestrator_pipeline_codeonly.md`), **no uses
este prompt**: anade complejidad sin beneficio. Usalo cuando el vuelo necesita
dispatch real a Claude Code, Kilo y/o OpenCode como backends DISTINTOS para
distintos tickets o distintos roles dentro del mismo ticket.

---

## Por que existe (censo verificado, no supuesto)

Verificado por un dispatch de diseno dedicado antes de escribir este prompt
(no asumido): `orchestrator_autonomous_ticket_batch.md` implementa un pipeline
de **2 capas** (Builder -> Review) sobre el backend que ejecuta la propia
sesion de batch. Carece de:

1. Rol **Manager-hijo** (Capa 1) como entidad de coordinacion e informe
   independiente por ticket.
2. **Lock sostenido del SO** (sustituye la idea original de lease/heartbeat de
   Seccion 2.4 de la PROPUESTA) para que nunca existan dos Capa 0 activas sobre
   el mismo backlog.
3. **Registro de identidad verificable** (Seccion 2.5.bis) de que Builder y
   Revisor son backend+modelo DISTINTOS, con consulta real de transporte en el
   cierre, no solo la palabra del hijo.
4. **Fallback-aware launch** (Seccion 3) entre Claude Code, Kilo y OpenCode.
5. **Decision de workspace por ticket** (Seccion 4): motor-solo, destino-solo
   o el par, segun `delivery_authority` real verificado en disco.
6. **Paso de integracion** (Seccion 7) antes del push agrupado del vuelo, para
   que N tickets cerrados por separado convivan en el HEAD integrado.

Este prompt cubre exactamente esos seis puntos. No reimplementa el PREDICATE
de 9 condiciones, las 8 barreras no negociables, el `GROUP_STOP_REPORT`, la
regla de contencion ni la maquina de estados -- todo eso sigue viviendo,
sin cambio, en `orchestrator_autonomous_ticket_batch.md`.

---

## Paso 0: condicion de entrada -- cuando este prompt aplica de verdad

Antes de usar este prompt, confirma explicitamente las DOS condiciones (si
falta cualquiera, usa el ejecutor existente sin esta capa):

1. El vuelo tiene 2+ tickets, O un ticket que por si solo exige Builder y
   Revisor en backend Y modelo DISTINTOS -- las DOS dimensiones, no solo el
   backend (condicion dura de `persona_system.md` Seccion 2 y de la PROPUESTA
   Seccion 2.5; alineada aqui con la comprobacion (c) de la Seccion 3 de este
   prompt tras el hallazgo opencode-glm 3.c: un par backend-distinto pero
   modelo-igual, p.ej. Claude Code/sonnet + Kilo/sonnet, pasaria este Paso 0
   y seria estructuralmente incapaz de certificar ningun cierre).
2. Al menos uno de esos despachos necesita un backend DISTINTO del que corre
   la propia sesion Capa 0 (si todo corriera en el mismo backend que la Capa
   0, el "dispatch multi-backend" es vacuo y el pipeline de un solo backend ya
   basta).

---

## 1. El lock sostenido de la Capa 0 (SUSTITUYE el mecanismo de PROPUESTA Seccion 2.4)

**Precedencia explicita (hueco cerrado en Ronda 6, hallazgo convergente codex/opencode-glm):
esta Seccion 1 PREVALECE sobre PROPUESTA 2.4 para el mecanismo de lock -- "sin reescribirla" de
versiones anteriores de este prompt era incorrecto y contradecia el propio "Mecanismo
REESCRITO" de abajo. PROPUESTA 2.4 describe el diseno ORIGEN (heartbeat-contra-reloj con
deteccion de staleness), que esta Seccion sustituye como mecanismo PRINCIPAL; PROPUESTA 2.4
sigue citandose UNICAMENTE como el algoritmo de deteccion del caso FALLBACK (mas abajo), nunca
como el mecanismo de adquisicion.**

**Mecanismo REESCRITO en Ronda 5 tras tres rondas de parches fallidos sobre
un esquema de fichero+rename (Rondas 3-5, hallazgos codex/cohere-fallback/
gemini/nan_qwen3.8 -- el ultimo, nan_qwen3.8, demostro que NINGUN reordenado
de "escribir + releer" puede cerrar la carrera: es un TOCTOU irreducible,
no un detalle de implementacion. Verificacion de ownership DESPUES de
escribir es tautologica [confirma tu propia escritura]; verificacion ANTES
de escribir sigue dejando una ventana entre la lectura y la escritura donde
otra sesion puede intercalar la suya. Ninguna reordenacion de dos
operaciones de fichero INDEPENDIENTES cierra esa ventana -- se necesita una
primitiva de exclusion mutua real, sostenida, no una secuencia de
escrituras discretas). El diseno correcto exige una primitiva real del
sistema operativo, nunca un patron de fichero+rename+relectura:**

- La Capa 0 adquiere `.agent/collaboration/flight/ORCHESTRATOR.lock` con una
  primitiva de exclusion mutua REAL y la MANTIENE ABIERTA durante TODA la
  vida del vuelo -- nunca la libera y re-adquiere por heartbeat. Ejemplos
  validos: `flock`/`fcntl.flock` en POSIX, un lock exclusivo nativo en
  Windows (`msvcrt.locking` o equivalente), o un lock manager externo con
  transaccion CAS real (p.ej. SQLite `BEGIN IMMEDIATE` sobre una fila unica).
  **Nunca** `open(path, "x")` + rename + relectura (los tres intentos
  anteriores de Rondas 3-5 construian "CAS" a partir de operaciones de
  fichero independientes, que no son componibles en una exclusion real).
- **Primitiva UNICA obligatoria por despliegue (hueco cerrado en Ronda 6,
  hallazgo bloqueante convergente codex+opencode-glm).** El menu de
  ejemplos de arriba NO es intercambiable: `flock` y `fcntl` record locks
  NO interoperan entre si en Linux (un proceso con `flock LOCK_EX` no
  bloquea a otro con `F_SETLK`), y un lock de rango de bytes en Windows
  solo excluye el MISMO rango. Dos sesiones usando primitivas distintas del
  menu obtienen AMBAS exito y creen sostener el lock -- split-brain
  completo, sin firma detectable, en el filesystem exacto donde el prompt
  declara garantia FUERTE. Por eso: todo despliegue de este prompt fija, en
  su propia configuracion (no aqui, que es portable), UNA primitiva
  concreta para TODOS los contendientes -- mismo mecanismo, mismo fichero,
  mismo modo/rango -- y rechaza mezclarlas. `fcntl` ademas se libera si el
  PROCESO cierra CUALQUIER descriptor suyo sobre ese fichero (semantica
  por-proceso, distinta de `flock`); una libreria que haga un `close()`
  incidental sobre el mismo path puede auto-liberar el lock a mitad de
  vuelo -- declararlo al elegir la primitiva de un despliegue concreto.
- **Prohibido borrar, renombrar o recrear el fichero del lock durante el
  vuelo (hueco cerrado en Ronda 6, hallazgo convergente codex+opencode-glm).**
  `flock`/`fcntl` ligan la exclusion al INODE, no a la ruta. Si algo borra o
  regenera `ORCHESTRATOR.lock` mientras una sesion lo sostiene (limpieza de
  arbol, `git clean`, un `--sync` que reaprovisiona el destino), el vuelo
  viejo retiene el lock del inode huerfano mientras un contendiente nuevo
  lockea el inode nuevo -- exclusion dual, split-brain, sin que ninguna de
  las dos sesiones lo note. Ningun proceso ajeno al vuelo (instalador,
  sync, limpieza) puede tocar esta ruta mientras un lock este sostenido.
- Mientras la Capa 0 sostiene el lock del SO, el heartbeat es una simple
  ESCRITURA DE CONTENIDO sobre el fichero ya abierto -- NO una operacion de
  reemplazo/CAS independiente, porque la exclusion ya la garantiza el SO,
  no el patron de escritura. No hay ventana de carrera que cerrar en el
  refresco: mientras el descriptor este abierto con el lock sostenido, NADIE
  MAS puede adquirirlo, por construccion del SO.
- **Caso AUSENTE o titular muerto LIMPIAMENTE (crash, kill, cierre de
  sesion):** el SO libera el lock automaticamente al morir el proceso que
  lo sostenia (`flock` se libera al cerrarse el descriptor o morir el
  proceso duenio). Una sesion nueva que intenta adquirir el lock con la
  MISMA primitiva (obligatorio, ver bullet de arriba) simplemente TIENE
  EXITO -- no necesita heuristica de staleness por timestamp para este
  caso: la propia primitiva del SO ya resuelve la colision de forma
  exclusiva y atomica.
- **Caso titular VIVO y legitimo (vuelo en marcha, incluida una PAUSA de la
  Seccion 6 -- hueco cerrado en Ronda 6, hallazgo opencode-glm G3: una
  PAUSA mantiene el descriptor ABIERTO y el lock SOSTENIDO, nunca lo
  libera; una sesion pausada sigue siendo titular legitimo, no un zombi,
  aunque su heartbeat no avance mientras espera al `fix-de-integracion`):**
  la adquisicion de la primitiva FALLA para cualquier otra sesion. Esa
  sesion NO reintenta en bucle ni asume staleness por el mero fallo: espera
  o reporta la colision al humano -- misma condicion de parada de la
  Seccion 6 ("colision del lock sostenido sin resolver deterministicamente"),
  que cubre exactamente este caso y el fallback de abajo, nunca el caso
  AUSENTE, que el SO ya resuelve solo.
- **Caso fallback -- sin locks nativos disponibles (filesystem que no los
  soporta, p.ej. algunos shares de red) o primitiva indisponible por otro
  motivo:** fallback declarado, NO el camino principal, y su alcance real
  es MAS ESTRECHO de lo que una version anterior de este texto afirmaba
  (hueco cerrado en Ronda 6, hallazgo mas fuerte de opencode-glm, G4). Sin
  soporte de locks nativos, la "adquisicion" tipicamente tiene EXITO para
  TODOS los contendientes (dos pseudo-titulares escriben heartbeat sobre el
  mismo fichero sin que nada los excluya), y la deteccion por
  heartbeat-contra-timestamp -- el UNICO mecanismo de deteccion disponible
  aqui -- **nunca dispara**, porque cada pseudo-titular mantiene su propio
  timestamp fresco. En ese sub-caso NO hay "best-effort con intervencion
  humana": no hay intervencion posible porque nada alerta de la colision.
  Consecuencia operativa, no cosmetica: un despliegue de este prompt debe
  o bien verificar en su propia configuracion que el filesystem del lock
  soporta locks nativos exclusivos ANTES de operar un vuelo multi-sesion
  real, o bien tratar la ausencia de ese soporte como motivo para NO
  promover este mecanismo en ese despliegue -- nunca asumir que el remedio
  humano cubre este sub-caso.
- **Riesgo residual declarado, acotado:** la garantia anti-split-brain es
  FUERTE (real, del SO) solo cuando se cumplen TRES condiciones a la vez:
  (i) el filesystem soporta locks nativos exclusivos, (ii) TODOS los
  contendientes usan la MISMA primitiva sobre el MISMO fichero, y (iii) el
  fichero del lock no se borra/renombra/recrea mientras algun lock esta
  sostenido. Fuera de esas tres condiciones, la garantia NO aplica -- y para
  el sub-caso especifico de ausencia de locks nativos, ni siquiera el
  remedio humano declarado es alcanzable (ver bullet de arriba).

**Liberacion del lock (hueco cerrado en Ronda 1, simplificado en Ronda 5 por
el cambio de mecanismo -- ya NO requiere verificar ownership por separado,
porque sostener el lock del SO abierto YA ES la prueba de ownership).** La
Capa 0 cierra el descriptor del lock (liberando la primitiva del SO) en los
dos unicos puntos de salida de un vuelo: (a) al declarar el vuelo `DONE` tras
el push agrupado (Seccion 7 de la PROPUESTA), y (b) al emitir cualquier
HARD-STOP de la lista de la Seccion 6. Cerrar el descriptor es, por
construccion del SO, instantaneo y sin ventana de carrera: nadie puede
"robar" un lock que todavia esta siendo sostenido, y en cuanto se cierra
cualquier otra sesion puede adquirirlo limpio -- no hace falta un paso
adicional de borrar o marcar el fichero.

---

## 2. Mecanismo de lanzamiento por backend (PROPUESTA Seccion 3, resumen operable)

| Backend | Mecanismo primario | Fallback | Hueco declarado |
|---|---|---|---|
| Claude Code | `delegate_task(isolation:"worktree")` | Agent tool, `subagent_type` fresco (nunca `fork` salvo que el hijo necesite el contexto del padre) | `parent_not_active` persistente, sin ticket de infraestructura todavia (deuda declarada, no de este prompt) |
| Kilo | `task` tool + Agent Manager (worktrees por ticket) | -- | Ninguno: `prompts/kilo_trio_dispatch/` ya lo cubre completo. Este prompt NO lo redeclara. |
| OpenCode | **No existe mecanismo documentado de dispatch de hijos por ticket.** | -- | **Gate `DISPATCH_RESTRICTION` obligatorio, ver Seccion 2.1 de abajo.** |

### 2.1 Gate `DISPATCH_RESTRICTION` (OpenCode) -- nuevo en este prompt, recomendado por challenger_kilo_gemma (BA09)

**Antes de despachar un Manager-hijo a OpenCode**, la Capa 0 verifica que
existe un protocolo de despacho validado para ese backend (hoy no existe
ninguno -- PROPUESTA Seccion 3.3, hueco declarado). Si no existe:

- La Capa 0 **NO despacha** a OpenCode como Manager-hijo de ningun ticket.
- Registra `DISPATCH_RESTRICTION: opencode` en el informe de vuelo, con la
  razon ("sin protocolo de despacho hijo validado") y el ticket afectado.
- El ticket se redespacha a Claude Code o Kilo si su `delivery_authority` lo
  permite; si ninguno puede asumirlo, el ticket queda `pending` con bloqueo
  declarado y AISLADO (mismo criterio de contencion que el ejecutor base:
  solo ESE ticket y su subgrafo de dependientes se congelan).

**Alcance de la parada (hueco cerrado en Ronda 1, hallazgo convergente
codex/gemini/mistral/opencode-glm):** `DISPATCH_RESTRICTION` nunca detiene el
vuelo ENTERO por si solo. El vuelo continua con los tickets que SI tienen
backend viable. Solo escala a la condicion de parada de la Seccion 6 cuando,
tras aplicar la contencion de arriba, **no queda ningun ticket ejecutable**
(mismo criterio que "backlog vacio de tickets ejecutables" del ejecutor
base) -- nunca por el mero hecho de que un ticket aislado quedo bloqueado.

Este gate se levanta UNICAMENTE cuando exista un protocolo de despacho de
hijos para OpenCode escrito y referenciado aqui por su propio documento --
nunca por decision ad-hoc de una sesion concreta.

---

## 3. Registro de lanzamiento e identidad verificable (PROPUESTA Seccion 2.5.bis)

La Capa 0 mantiene `.agent/collaboration/flight/child_launches.jsonl`,
**escrito SIEMPRE por ella, nunca por el hijo** (ver PROPUESTA 2.5.bis(A), tal
como quedo corregida en v7 tras la Ronda 4 del bucle: registro en DOS fases,
`intent` al despachar y `confirmed` cuando la Capa 0 recibe el id real del
reporte del hijo).

**Antes de aceptar el cierre de un Manager-hijo**, la Capa 0 exige, con claves
literales greppables (nunca prosa libre):

```
implementador: <backend>/<modelo>
revisor: <backend>/<modelo>
cita_revision: <task_id|agentId|ref>
```

y resuelve `cita_revision` por consulta REAL de transporte
(`task_status`/`ListAgents` segun backend), cruzandola contra el registro
propio. Comprueba: (a) la invocacion existe de verdad para ESTE ticket, (b) es
posterior al ultimo commit del Builder y anterior a la certificacion, (c)
`backend_implementador != backend_revisor` **Y** `modelo_implementador !=
modelo_revisor` (las dos condiciones, independientes entre si).

**Esquema minimo de cada linea de `child_launches.jsonl`** (hueco cerrado en
Ronda 1, hallazgo gemini/mistral): `{ticket, role: "manager"|"builder"|
"reviewer", backend, modelo, task_id|agentId|null, status: "intent"|
"confirmed", ts}`. Purga: las lineas de un ticket se archivan (nunca se
borran) al cerrar el vuelo que las origino, junto al resto de reportes del
vuelo -- mismo ciclo de vida que `batch_run_<ts>.json` del ejecutor base.

### 3.1 Gate `UNVERIFIED_IDENTITY` -- nuevo en este prompt, recomendado por challenger_kilo_gemma (BA09)

Si cualquiera de las tres comprobaciones de arriba falla -- claves ausentes,
consulta de transporte no resuelve, o alguna de las dos dimensiones de
independencia no se cumple -- la Capa 0 marca el ticket `UNVERIFIED_IDENTITY`
(mismo significado operativo que `NO_VERIFICABLE` de la PROPUESTA Seccion
2.5.bis, nombrado aqui en ingles porque es el token que el informe de vuelo
emite literalmente para que un grep lo encuentre sin depender del idioma del
resto del documento). Un ticket `UNVERIFIED_IDENTITY` **NUNCA** se certifica ni
entra al paso de integracion de la Seccion 5: se remedia (reintentar la
revision independiente sobre el mismo hijo si sigue vivo, o redespachar desde
cero) o escala a `BLOQUEADO_ROJO` tras el tope declarado (`K=2` por defecto,
igual que la PROPUESTA).

**Semantica de `K=2` (hueco cerrado en Ronda 1, hallazgo opencode-glm 3.a):**
el contador es POR TICKET y se RESETEA a cero en cuanto ese ticket alcanza
`UNVERIFIED_IDENTITY` -> remediado -> certificado (exito real, no solo un
reintento). Dos rechazos CONSECUTIVOS sobre el MISMO ticket sin exito
intermedio disparan `K=2`. La rama de "causa raiz ESTRUCTURAL" de la Seccion
6 es un ATAJO sobre la misma cuenta: si los DOS rechazos que agotan `K=2`
citan la misma causa raiz estructural, el ticket escala directo a
`BLOQUEADO_ROJO` en vez de a remediacion -- nunca una tercera rama paralela
con su propio contador.

**Este gate es la mitigacion directa del riesgo residual #1 de la PROPUESTA
("introspeccion de invocaciones nieto no verificada en vivo contra la
plataforma real"): si la introspeccion falla en produccion, el gate lo
convierte en `UNVERIFIED_IDENTITY` declarado en vez de en un cierre silencioso
que asume independencia sin poder probarla.**

---

## 4. Workspace por ticket (PROPUESTA Seccion 4, sin reescribirla)

La Capa 0 PROPONE el workspace (motor-solo / destino-solo / el par con
nomenclatura `AGENTS.md` WOT-2026-104f/104g) en el prompt de despacho, y lo
aprovisiona ANTES de lanzar. El Manager-hijo verifica contra disco en su
primer paso; si no coincide, emite `WORKSPACE_MISMATCH` y termina sin avanzar
-- nunca migra su propio workspace en caliente. Tope `K_ws=2` reintentos antes
de escalar `BLOQUEADO_ROJO` (mismo criterio que la PROPUESTA 2.6).

---

## 5. Integracion antes del push agrupado (PROPUESTA Seccion 7, sin reescribirla)

Antes del push unico del vuelo (regla `AGENTS.md` "Push por vuelo", sin
excepcion), la Capa 0 integra los commits de todos los tickets **por merge,
nunca rebase**, corre la suite canonica completa sobre el HEAD INTEGRADO, y si
hay conflicto de merge o suite roja, **da de alta un ticket
`fix-de-integracion`** que sigue el pipeline de 4 capas completo -- la Capa 0
NUNCA resuelve un conflicto de merge ella misma (violaria su propia regla dura
de no implementar).

---

## 6. Condiciones de parada de este gobierno adicional

Ademas de las causas de parada ya existentes de `orchestrator_autonomous_ticket_batch.md`
(HARD-STOP causes, Seccion correspondiente), este prompt anade estas, citando
cual se cumplio en el informe de vuelo:

- Colision del lock sostenido descubierta por cualquier medio (Seccion 1,
  fallo de adquisicion contra un titular vivo, o reporte humano en un
  despliegue sin locks nativos) sin resolver deterministicamente. En
  fallback sin locks nativos la deteccion runtime NUNCA dispara (Seccion 1);
  el HARD-STOP real en ese caso es de preflight -- filesystem sin soporte de
  locks nativos verificado antes de operar multi-sesion.
- `K=2` rechazos `UNVERIFIED_IDENTITY` consecutivos sobre el mismo ticket, o un
  `BLOQUEADO_ROJO` inmediato si dos rechazos citan la misma causa raiz
  ESTRUCTURAL (catalogo de backends corto, `parent_not_active` persistente).
- `K_ws=2` `WORKSPACE_MISMATCH` consecutivos sobre el mismo ticket.
- Conflicto de merge o suite integrada roja en el paso de integracion (Seccion
  5) -- el vuelo se PAUSA (nunca se cierra como fallo) mientras el ticket
  `fix-de-integracion` sigue su propio pipeline.
- `DISPATCH_RESTRICTION: opencode` dejando, tras aplicar la contencion de la
  Seccion 2.1, CERO tickets ejecutables en el backlog -- nunca por un solo
  ticket aislado que quedo bloqueado mientras otros siguen viables.

Fuera de estas condiciones (y de las ya existentes del ejecutor base), la Capa
0 continua despachando el siguiente ticket sin pausar a narrar un cierre que
no requiere decision humana (converso explicito, PROPUESTA Seccion 2.6).

---

## Que NO hacer

- No despachar a OpenCode como Manager-hijo sin que exista un protocolo de
  despacho validado citado por su propio documento (Seccion 2.1).
- No certificar un ticket `UNVERIFIED_IDENTITY` para destrabar el vuelo.
- No resolver un conflicto de merge de integracion directamente (da de alta un
  `fix-de-integracion`).
- No reescribir, en este prompt, el PREDICATE de 9 condiciones, las 8
  barreras no negociables ni la maquina de estados del ejecutor base -- viven
  en `orchestrator_autonomous_ticket_batch.md`.
- No promover este prompt fuera de `status: experimental` sin evidencia de
  vuelo real (no solo auditada en papel) de los CINCO mecanismos con gate
  propio que declara load-bearing (ampliado en Ronda 1 de 1 a 4; corregido en
  Ronda 2, hallazgo nan_deepseek: la lista de 4 omitia el quinto mecanismo
  gateado -- workspace -- que "Por que existe" ya enumeraba):
  1. El gate `UNVERIFIED_IDENTITY` EJERCITADO (detecto al menos un caso real
     de identidad no verificable y lo remedio o escalo correctamente).
  2. El lock sostenido resistiendo una colision real (2+ sesiones Capa 0 compitiendo
     por el mismo lock, resuelta deterministicamente, sin split-brain).
  3. El gate `WORKSPACE_MISMATCH` (Seccion 4) EJERCITADO en al menos un
     ticket real (un `delivery_authority` que no coincidio con el workspace
     propuesto, resuelto sin que el Manager-hijo migrara su workspace en
     caliente).
  4. El paso de integracion (Seccion 5) ante AL MENOS un conflicto de merge
     real entre tickets de backends distintos, con alta exitosa de un
     `fix-de-integracion` sin que la Capa 0 lo resolviera ella misma.
  5. El gate `DISPATCH_RESTRICTION` EJERCITADO (un ticket real sin backend
     OpenCode viable, contenido sin detener el vuelo entero).
