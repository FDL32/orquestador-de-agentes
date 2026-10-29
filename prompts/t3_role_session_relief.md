# Prompt: T3 Role Session Relief (relevo de sesion-rol hermana)

<!-- PROMPT-SUMMARY
what: Protocolo operativo de relevo de sesion-rol hermana (implantacion/triaje/orquestadora)
en un vuelo T3 multi-sesion. Define clases de fallo (A/B), arbol de decision por ranura,
progreso observable, checkpoint continuo, preflight de relanzo, plantilla del sucesor,
verificacion solo alcanzable, y self-hop del orquestador.
when: Cuando una sesion-rol hermana pierde fiabilidad (Clase A) o servicio parcial (Clase B)
dentro de un vuelo T3 multi-sesion, y la orquestadora o una sesion vecina detecta la senal.
not: NO define integridad de lente (Clase C, remite a 129w/129v). NO cubre nonce/blowout.
NO es una generalizacion arbitraria: vive aqui por C1 de PROPUESTA v3 (ROL-3), 129f depende
de 129a (aparcado). NON-GOAL: integridad de lentes (129v/129w), nonce/blowout de ensemble_loop.
-->

> **Modo:** Este modulo es el hogar operativo del relevo de sesion-rol. `session_hop.md`
> sigue solo-lectura y solo recibe un puntero (D2 de work_plan 129u). El roster se escribe
> por separado (OR-1 es el unico escritor).

contract_id: cid-t3-role-session-relief-v1
source_ticket: WOT-2026-129u
source_proposal: C:/tmp/vuelo-20261026b-orq/PROPUESTA_v3_relevo_sesion_rol.md (ROL-3, v3)

---

## 1. Alcance y relacion

Este es el protocolo **OPERATIVO** de relevo de sesion-rol hermana (implantacion/triaje/orquestadora)
en un vuelo T3 multi-sesion. El modulo vive AQUI (D1 del work_plan).

**Fuentes del diseno:**
- Fila 129u del backlog (work_plan.md).
- PROPUESTA v3 (ROL-3, rund 2, veredictos ROL-3 6/6 en el defecto de dependencia de 129a):
  C1-C14, citados en las secciones correspondientes.
- Fuentes que cita la propuesta: `incidencias.md` (rutas del vuelo), WOT-2026-129q (codigo de
  instancia de relanzo), WOT-2026-129d (cupo/latido).
- Roster: campo declarado por este modulo, escrito por OR-1.

**NON-GOAL:** Integridad de lente (Clase C) remite a WOT-2026-129w/129v. Nunca dependencia operativa
de 129a (aparcado, C1) ni de 129f (solo glosario/puntero).

---

## 2. Clases de fallo

### Clase A: sesion no fiable

La sesion-rol hermana **NO es fiable** por cualquiera de estas causas:
- **Overflow:** desborde de contexto o limite del backend que impide procesar el turno actual.
- **Cuelgue:** ausencia de progreso observable en la ranura asignada durante un plazo configurado.
- **Failed:** fallo categorizado de la sesion (crash, timeout no recuperable, respuesta no valida).

**Remedio:** `t3_thread_send mode=restart` (reiniciar el run de la ranura). El mensaje estrecho
solamente aplica para fallo de proveedor con hilo vivo (C2 de PROPUESTA v3).

### Clase B: turno cae pero la sesion sirve

La sesion-rol hermana **sirve** pero su turno se pierde. Se subdivide en:

- **B1 - Filtro de contenido:** el turno llega corrupto o alterado por un filtro intermedio.
  Se cambia la forma del turno (reencaminar con otro encoding o estructura).
- **B2 - Fallo de transporte repetido:** `empty_content_despite_sentinel` o 5xx del transporte.
  Este ultimo **NO es Clase A** ni justifica rotar un backend sano (C3 de PROPUESTA v3).
  Se reencamina por el dispatcher o se difiere.

**Regla:** un fallo de transporte repetido (B2) NO es Clase A. No rotar backend si esta sano.

### Clase C: integridad de lente (FUERA DE ALCANCE)

La integridad de lente es **Clase C** y esta FUERA del alcance de este modulo. Remite a
WOT-2026-129w/129v. Se deduplica contra la prescripcion de `incidencias.md` (C11 de PROPUESTA v3).

---

## 2.5. Tercer discriminador: cupo/cuenta agotada (129d)

Antes de que cualquier senal se clasifique como **Clase A** (sesion no fiable),
la orquestadora verifica un tercer discriminador: si la causa del fallo es
**cupo/cuenta agotada** (limite de tokens, cupo de latido, cuota del backend),
la senal se remite a **WOT-2026-129d** (cupo/latido) y **NO se escala a Clase A**.

**Regla dura:** nunca escalar a Clase A sin descartar primero que la causa
no es "cupo/cuenta agotada". Si el cupo esta agotado, el remedio es
solicitar mas cupo (129d), no reiniciar la sesion (Clase A).

Referencia: C4 de PROPUESTA v3.

---

## 3. Arbol A/B por ranura con umbral configurable

### Declaracion del campo en el roster

Este modulo declara un campo en el roster con la forma:

```
rules.session_relief.<ranura>.plazo_sin_progreso
```

donde `<ranura>` es la ranura T3 identificadora (ej. `implantacion`, `triaje`, `orquestadora`).
Campo adicional:

```
rules.session_relief.<ranura>.sensible_a_causa
```

que toma valor `determinista` o `no_determinista`.

Defaults del diseno (C5, C12 de PROPUESTA v3):
- `plazo_sin_progreso`: configurable, definido en el roster.
- `sensible_a_causa`: `determinista` por defecto (C12).

### Regla causa determinista

Una muerte **determinista** (desborde de contexto, limite del backend, fallo de codificacion
estructurado) se releva al **PRIMER fallo** (C12 de PROPUESTA v3). Esperar un segundo fallo
solo quema cupo de la orquestadora sin beneficio.

**Ejemplos:** overflow de tokens, limite de contexto, timeout por longitud maxima.

### Regla causa no determinista

Para causas **no deterministas** (fallos esporadicos, 5xx intermitentes, errores de transporte
no replicables), se aplica el umbral de **2+ fallos**.

- Asimetrico por capacidad de la ranura (C5 de PROPUESTA v3):
  - **Lectura (triaje):** umbral propio configurado en el roster. El triaje puede tener
    mayor tolerancia a fallos esporadicos.
  - **Escritura (implantacion):** umbral propio configurado en el roster. La escritura es
    mas critica; default de diseno = 2 fallos.
- El **2 es default de diseno, NO una lectura calibrada de evidencia** (C5): no hubo 2 fallos
  de sesion consecutivos en ninguna ranura documentada. Es una conservacion por defecto.

### Reset del contador

El contador de fallos por ranura se **resetea SOLO por progreso verificado** (C5, C12):
- Cualquier reset exige **>= 2 senales verificables del conjunto de la seccion 4**
  (commits, ficheros, journal con estado avanzado, logs, PIDs).
- La senal de `t3_thread_send mode=restart` completada con EXIT puede contar como
  **maximo UNA** de esas >= 2 senales: es recuperacion, no progreso de trabajo;
  no basta sola, no relaja la seccion 4 a 1 senal.

El reset **NO se hace** por cerrar un ticket sin progreso medible (C12: la regla
"sin cierre de ticket intermedio" se rompe en ranuras con cierres rapidos).

### Precedente medido

El precedente de sustitucion de backend por inestabilidad es BA110 (4 caidas, cuarentena
temporal, C10 de PROPUESTA v3). No es el revisor interino.

---

## 4. Progreso observable (mecanismo PROPIO, nunca updatedAt solo)

### Senales de progreso

El progreso observable se mide con **>= 2 senales** del siguiente conjunto (BA15 de CONTRACT_AUDIT):

1. **updatedAt:** marca de tiempo de la ultima actividad registrada.
2. **commits nuevos:** commits en el worktree de la ranura desde la ultima medicion.
3. **ficheros modificados:** archivos creados, editados o renombrados en el worktree.
4. **logs de procesos:** entrada reciente en el journal o log de la sesion.
5. **PIDs vivos:** proceso activo identificado por `t3_thread_list` o `t3_worktree_list`.

**Nunca solo updatedAt:** una unica senal de updatedAt NO es suficiente (BA15). Se requieren
>= 2 senales para considerar progreso verificado.

### Mecanismo propio

Este modulo define y exige el mecanismo de deteccion de progreso observable. No depende de
ningun otro ticket. Es un mecanismo PROPIO del modulo (R2 de trabajo: el progreso observable
= mecanismo PROPIO).

### Remedios segun senal

- **Cuelgue detectado** (0 senales por plazo configurado): `t3_thread_send mode=restart`.
- **Fallo de proveedor con hilo vivo:** mensaje estrecho (solo este caso, C2).

### Vecino opcional: WOT-2026-129v

WOT-2026-129v (detector de cuelgue del latido) se cita SOLO como posible **emisor OPCIONAL**
de la senal de progreso. Este modulo NO exige ni implementa 129v: 129v decide si la emite.
129v y 129w quedan como exclusiones, nunca como fuente operativa obligatoria (NON-GOAL).

---

## 5. Checkpoint continuo

### Ubicacion

El checkpoint continuo vive **FUERA del worktree de la sesion** (C7 de PROPUESTA v3).
Ubicacion propuesta: carpeta del vuelo (`C:/tmp/vuelo-<vuelo-id>/` o ruta equivalente).

**Razon:** los artefactos del scorecard y checkpoint son por worktree (C7); si vivieran
dentro del worktree, cada sesion sobre-escribiria el de las otras.

### Via de escritura

Via declarada: **Bash/python append LF** (C13 de PROPUESTA v3).

**Razon:** la carpeta del vuelo esta fuera del repo y `guard_paths` bloquea Write/Edit
nativos ahi (incidencias.md:3, medido). La via de escritura debe ser compatible con
guard_paths: Bash `>>` append o Python `open(path, 'a', encoding='utf-8')` con LF explicito.

**Nunca Write/Edit nativo del agente:** `guard_paths` rechazaria la escritura a la carpeta
del vuelo (C13).

### Cadencia

- **Al cambio de estado de ticket:** cada transicion de estado (IN_PROGRESS -> COMPLETED, etc.)
  escribe una entrada de checkpoint.
- **Al ceder la ranura:** cuando una sesion termina o cede su ranura, escribe un checkpoint
  final antes de cerrar.

### Contenido minimo

Cada entrada de checkpoint incluye:
- Ranura y threadId.
- Ticket activo y su estado.
- Senales de progreso verificadas (timestamps, SHAs, PIDs).
- Fecha y hora del checkpoint.
- DECISIONES (decision con su fuente -- `id` del mensaje T3 -- y las premisas
  que la motivaron, nunca copiada sin fuente; cada decision marcada
  `PENDIENTE` o `TOMADA`).
- LATIDOS (cada tarea/job en background con el `threadId` al que queda atado).
- OBREROS (cada sesion-rol obrera viva con `threadId`, ruta de sus informes,
  su `max_silencio` configurado para la ranura y a quien reporta, `reporta_a`).
- CADENA_CONSULTA (la cadena de consulta ordenada, padre inmediato primero,
  cada eslabon con su `threadId` y la fuente que lo fija -- p.ej.
  `flight_roster.json` o el mensaje de arranque que lo declaro).
- AUTORIDAD (que decision esta delegada en esta sesion-rol frente a lo que
  queda reservado a SUPERVISOR-2, con su fuente).
- PROXIMO_PASO (la siguiente accion concreta, con el comando exacto que la
  ejecuta o verifica).

### Prueba de lectura por el sucesor

El sucesor **verifica que puede leer** el checkpoint al arrancar. Si no puede leerlo,
declara `checkpoint_no_accessible` y reconstruye desde las fuentes que alcanza (git, backlog,
journal).

---

## 6. Preflight del relanzo

### Codigo de instancia de WOT-2026-129q

Antes de lanzar un sucesor, se verifica el codigo de instancia de WOT-2026-129q
(precedente medido en el vuelo).

### Regula dos-hilos-mismo-nombre

NO lanzar el sucesor hasta confirmar **SETTLED/ABANDONADA** del hilo viejo (C7 de PROPUESTA v3,
precedente 129q). Esto cierra la ventana de "dos hilos con el mismo nombre de ranura, uno
vivo sin asentar" (C14 de PROPUESTA v3).

### Secuencia de preflight

1. Consultar estado del hilo viejo (129q).
2. Si no es `SETTLED` ni `ABANDONADA`: esperar.
3. Solo tras confirmacion, lanzar el sucesor.
4. Nunca lanzar el sucesor si el viejo sigue `PENDING` o `RUNNING`, salvo la excepcion declarada en "Excepcion: relevo planificado o self-hop" (mas abajo en esta misma seccion).

### Excepcion: relevo planificado o self-hop

La regla dos-hilos-mismo-nombre no aplica a un relevo PLANIFICADO. El campo
`active_roles.<rol>.estado` (valores `ACTIVO`, `PENDIENTE_ACK`,
`SALIENTE_MUERTO`), escrito por el script escritor del roster
(WOT-2026-136b, nunca a mano -- este modulo DECLARA el campo, no lo escribe,
mismo patron que `rules.session_relief.*` de la seccion 3), registra el
estado de la sesion saliente y permite las tres transiciones siguientes:

- `ACTIVO -> PENDIENTE_ACK`: el saliente congela su actividad mientras el
  entrante se autentica.
- `PENDIENTE_ACK -> ACTIVO(entrante)` con ACK via el primer mensaje con
  HEAD/hilos/latidos re-medidos de la seccion 7.
- `PENDIENTE_ACK -> SALIENTE_MUERTO` sin ACK en 15 minutos -- umbral NUEVO
  de este modulo -- o sin `>= 2` senales de progreso VERIFICADAS de la
  seccion 4 dentro de ese mismo plazo (misma vara que la seccion 4 exige
  para progreso verificado, nunca "senales ausentes" como criterio
  independiente: en `PENDIENTE_ACK` el saliente esta congelado por diseno y
  sus senales de actividad se vuelven ausentes de forma esperada, asi que un
  criterio de ausencia por si solo disparase `SALIENTE_MUERTO` casi de
  inmediato y se saltaria los 15 minutos).

El congelamiento del saliente dura mientras `estado = PENDIENTE_ACK`. La
decision de completar desde el checkpoint de un `SALIENTE_MUERTO` la toma
SUPERVISOR-2 (nunca el entrante), exigiendo al menos 2 senales de progreso
(Seccion 4) verificadas. "SUPERVISOR-2" designa siempre al relay del usuario,
nunca a una orquestadora degradada a supervisora (vision del usuario,
PROPUESTA v7 Sec. 1 -- este modulo no redefine esa vision, solo nombra al
actor con precision).

---

## 7. Plantilla del sucesor

El sucesor **recibe** una plantilla de arranque. Esta plantilla es copiable desde el modulo
y se construye con los siguientes requisitos (DoD 3, C6-C9 de PROPUESTA v3):

### Sub-requisito 1: estado heredado CITADO con fuente (nunca copiado)

El estado que hereda el sucesor se **cita con su fuente**, nunca se copia textualmente:
- "El ticket X estaba en IN_PROGRESS segun backlog.md a las HH:MM."
- "El worktree Y tenia los siguientes cambios pendientes: <lista con comando de re-medicion>."

**NUNCA copiar texto de la propuesta sin atribucion** (R3 del trabajo, DoD 3): todo dato
heredado lleva `segun <fuente>, <fecha>` o `verificado con <comando>, <rc>`.

### Sub-requisito 2: hilo abandonado id + NO_REABRIR

Todo hilo que queda abandonado por el relevo se marca con:
- **Id del hilo:** `thread_id=<id>`
- **Estado:** `NO_REABRIR` (por id, no por run).

El sucesor NO reabre el hilo marcado como NO_REABRIR.

### Sub-requisito 3: METODO separado de ESTADO

El METODO (procedimiento, reglas de trabajo) vive versionado en este prompt.
El ESTADO (datos concretos, cifras, SHAs) se re-mide al arrancar.

No cristalizar estado en ningun fichero versionado (como dicta session_hop.md).

### Sub-requisito 4: veredictos de revisores como AFIRMACIONES no hechos

Los veredictos de revisores se transportan como **afirmaciones con fuente**:
- "El revisor X declaro: 'APROBADO' (segun bus event <id>, <fecha>)."

NUNCA como hechos consumados. El sucesor re-verifica los veredictos si son criticos.

### Sub-requisito 5: medicion sin redireccion de PowerShell (UTF-16)

Las mediciones de tamano se hacen con Python, nunca con redireccion de PowerShell:

```python
# CORRECTO: bytes con Python (evita UTF-16 de PowerShell)
tamano = len(open(ruta, 'rb').read())

# INCORRECTO: redireccion de PowerShell (escribe UTF-16, C9b de PROPUESTA v3)
# $size = (Get-Item ruta).Length
```

**Precedente medido:** dos fallos sin dueno el dia del diseno, uno de ellos la medicion con
redireccion de PowerShell que escribe UTF-16 (C9b de PROPUESTA v3).

### PIDs propios del sucesor

El sucesor reporta sus propios PIDs en el arranque, no hereda los del hilo anterior:
- PID del proceso de la sesion.
- PID de los hilos T3 asociados.
- Referencia a `t3_thread_list` para verificacion.

---

## 8. Verificacion de la orquestadora (solo alcanzable / NO VISIBLE)

### Lo que la orquestadora alcanza por si misma

La orquestadora verifica **solo lo alcanzable** por ella misma (DoD 4, C8 de PROPUESTA v3):
- **Git:** `git status`, `git log`, `git diff`, `git merge-base --is-ancestor`.
- **Backlog:** lectura de `backlog.md` en el repositorio del worktree.
- **Journal:** lectura del journal de eventos del ticket activo.
- **Estado del bus:** lectura de `events.jsonl` del ticket (si existe).

### Lo que se declara "NO VISIBLE"

Cualquier dato sobre un worktree ajeno al que la orquestadora **no tiene acceso directo**
se declara explicitamente como **"NO VISIBLE"** (C8, nunca se omite en silencio):

- Scorecard de worktree ajeno: la orquestadora no lo lee; lo reporta el sucesor.
- PIDs de sesion hermana: la orquestadora no los ve directamente; los reporta la sesion hermana.
- Estado interno de una sesion (memoria, contexto): la orquestadora no lo accede; lo reporta
  la sesion.

### Scorecard de worktree ajeno

Regla (C8): si la orquestadora necesita verificar algo sobre un worktree al que no accede,
declara: `[no visible: worktree <nombre>, orquestadora no tiene acceso directo]`.

El sucesor **reporta sus propios PIDs** y estados medidos por sus propias herramientas.

---

## 9. Self-hop del orquestador (C14)

### Cuando aplica

Antes de que la sesion orquestadora se apague (por compactacion u otra razon de cierre),
aplica las senales de Clase A/B a:
1. Cada sesion hermana (implantacion, triaje).
2. Si misma (la orquestadora).

### Que hace

1. **Evalua cada hermana:** aplica las senales de Clase A/B de la Seccion 2 a cada hermana.
2. **Evalua si misma:** aplica las mismas senales a su propio estado.
3. **Relanza SOLO las necesitadas:** nunca "relanzar las tres por defecto" (C14).
   Solo se relanza la sesion que cumple la condicion de relevo.
4. **Sanas por referencia:** las sesiones sanas se entregan por REFERENCIA (su `threadId`)
   en el arranque del sucesor, para que el nuevo orquestador siga hablandoles sin tocarlas.
5. **Bundle de continuidad:** lo escribe el orquestador viejo (C14), porque tiene el contexto
   vivo de por que fallo la sesion: que revisor se retiro y por que, que ticket quedo aparcado,
   que decision de roster se aplico. Un sucesor tendria que reconstruir eso desde
   backlog.md/journal.jsonl antes de poder decidir.

### Razon medida

Triaje-1 cayo por desborde de contexto mientras implantacion-1 y la orquestadora seguian
sanos (C14). Relanzar a implantacion-1 sin necesidad habria repetido el fallo de
WOT-2026-129q (dos hilos con el mismo nombre de ranura, uno vivo sin asentar).

### Criterio de relevo

Solo se relanza una sesion si cumple una condicion de Clase A o B que requiera accion.
Las sesiones sanas se entregan por referencia, no se relanza.

### Releer tras compactar

Mecanismo: `t3_thread_read` paginado sobre el propio hilo desde `afterPosition`
igual a la ultima posicion leida antes de compactar (o los ultimos 20 items si
se desconoce) mas el checkpoint mas reciente. Desempate: gana el hilo salvo
que el checkpoint se declare expresamente autoritativo para ese campo.

---

## 10. Cadena de ancestros (consulta escalonada)

Tricotomia:
- **VIVO:** `t3_thread_read` normal.
- **SETTLED pero legible:** `t3_thread_read` paginado.
- **DESBORDADO:** no se relee, se marca "NO VERIFICABLE" y se salta al
  siguiente nivel.

Plazo de 10 minutos (umbral NUEVO de este modulo) antes de saltar de nivel.

Registro `ancestor_unavailable` en `roster_changes.jsonl` -- declarado SOLO
como PROTOCOLO (el nombre del evento), sin prescribir el formato exacto de
esa linea ni implicar que este ticket escriba ese fichero: el esquema y el
escritor de `roster_changes.jsonl` son de WOT-2026-136b. (sin reintento en
caliente)

Escalada a SUPERVISOR-2 y despues al usuario si cada nivel de la cadena queda
"no_disponible"/"NO VERIFICABLE" (caso de agotamiento total).

DIFERIDO en esta seccion: desafio con nonce, cuaderno de consultas con
metrica, contador de saltos.

## Referencias cruzadas

- `prompts/session_hop.md`: puente entre sesiones (solo lectura); este modulo apunta aqui
  como el hogar del relevo operativo. Puntero en Paso 5-bis.
- WOT-2026-129q: codigo de instancia de relanzo (preflight, Seccion 6).
- WOT-2026-129d: latido de cupo (tercer discriminador, Seccion 10).
- WOT-2026-129v: detector de cuelgue del latido (emisor opcional, Seccion 4).
- WOT-2026-129w: integridad de lente (Clase C, NON-GOAL, Seccion 2).
- WOT-2026-129f: glosario y punteros (NON-GOAL operativo; 129f recibe solo glosario/puntero).
- `AGENTS.md`: vocabulario canonico (T3, ranura, vuelo, worktree).
- `prompts/ensemble_loop.md`: NON-GOAL (nonce/blowout no cubiertos).
- `C:/tmp/vuelo-20261026b-orq/PROPUESTA_v3_relevo_sesion_rol.md`: insumo de diseno (C1-C14).

---

## NON-GOAL declarados

Los siguientes temas estan explicitamente fuera del alcance de este modulo.
Cualquier trabajo sobre ellos pertenece a otros tickets:

- **Integridad de lente (Clase C):** WOT-2026-129w/129v. Deduplicar contra `incidencias.md`
  (C11 de PROPUESTA v3).
- **Nonce/blowout de ensemble_loop:** fuera del alcance de 129u.
- **VUELO-NNN:** fuera del alcance de 129u.
- **Dependencia de 129a:** 129a esta aparcado (C1). Este modulo NO depende de 129a.
- **Escritura del roster:** el campo `rules.session_relief.*` se escribe por OR-1 en el roster.
  Este modulo lo declara, no lo escribe.
