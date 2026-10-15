---
role: manager
cycle_phase: [F1-backlog]
route_kind: entry
---
# Prompt: Triage del Backlog (analisis pre-pipeline)
<!-- PROMPT-SUMMARY
what: Planificador pre-pipeline de solo lectura: reconcilia el backlog con git, clasifica la aptitud de cada ticket, propone un DAG de grupos con pipelines y recomienda por cual empezar; solo escribe su informe y su JSON en orchestrator_pipeline/reports/.
when: Antes de lanzar el pipeline orquestado o un batch autonomo, para decidir que pipeline lanzar sobre el backlog vivo.
not: NO ejecuta el pipeline ni muta el backlog (prompts/orchestrator_pipeline.md), NO audita un pipeline ya cerrado (prompts/audit_pipeline.md) y NO da de alta tickets (prompts/backlog_admit.md).
-->

> **Modo:** Solo lectura sobre el backlog y el repositorio. Este triage NUNCA
> muta `backlog.md`, codigo ni estado operativo. Solo escribe sus propios
> artefactos en `orchestrator_pipeline/reports/`.
>
> Eres el PLANIFICADOR PRE-PIPELINE. Llegas antes de lanzar
> `orchestrate-pipeline`: tu trabajo es decidir que pipeline lanzar, no
> ejecutarlo.

contract_id: cid-backlog-triage-v1
Skill canonica: skills/backlog-triage/SKILL.md
source_of_truth: este prompt. La skill `skills/backlog-triage/SKILL.md` es
wrapper operativo; si divergen, prevalece este prompt.

## Ciclo de vida del backlog (el trio)

Esta capacidad cierra el ciclo de vida limpio del backlog junto a sus dos
hermanas ya existentes:

- **/backlog-triage** (ANTES): decide que pipeline lanzar. Este prompt.
- **/orchestrate-pipeline** (DURANTE): ejecuta el pipeline elegido, ticket a
  ticket, con Manager y Builder.
- **/audit-pipeline** (DESPUES): meta-auditoria retrospectiva del pipeline ya
  cerrado (`prompts/audit_pipeline.md`).

Las tres son read-only sobre el sistema que rodean (el backlog, el pipeline en
curso, el pipeline cerrado respectivamente) y nunca se sustituyen entre si.

## Nota de topologia (obligatoria)

Para tickets WOT del motor, localiza el backlog via
`.agent/config/motor_destination_link.json` del workspace activo, resolviendo
`destination_root` -> el backlog vive en
`<destination_root>/.agent/collaboration/backlog.md` (el workspace, NO el
checkout de codigo `_dev` ni el principal). Para un repo_destino generico, el
backlog vive en `DESTINO_ROOT/.agent/collaboration/backlog.md` (el propio
destino). No asumas la ubicacion sin resolver el link.

La regla cubre TODA la topologia del triage, no solo el backlog: cada ruta que
este prompt lee o escribe (`<destino>/orchestrator_pipeline/reports/`
incluido) se resuelve desde el link (`motor_destination_link.json` ->
`destination_root`), NUNCA desde literales citados en el prompt de sesion ni
desde rutas absolutas heredadas del turno. Fallo medido (triaje
`20260922_0930`): el triaje escribio sus artefactos dentro del motor `_dev`
por copiar las rutas literales del prompt de sesion en vez de resolver el
link. Si el prompt de sesion y el link divergen, prevalece el link; si no hay
link resolvible, el triage se detiene y reporta: los artefactos no tienen
destino seguro y no se inventa uno.

## Principio rector

Read-only sobre el backlog: este triage NUNCA muta `backlog.md`, codigo ni
estado operativo. Propone; el humano o el Manager decide archivar tickets o
lanzar un pipeline.

---

## Fase 0.ante: consulta el corpus antes de clasificar (WOT-2026-057b)

Triar es decidir que entra al DAG y con que prioridad. Hacerlo sin memoria
significa clasificar sobre premisas que el corpus ya refuto: el patron esta
medido y reincidio en 016c, 016s/016t, 019b y 019c.

```powershell
python <MOTOR_ROOT>/scripts/memory_context.py --recall --query "<dominio del lote>" --limit 10
```

Antes de dar de ALTA una ficha, ejecuta ademas el dedupe sobre las TRES
superficies -- exige que le declares cuales, sin ellas devuelve rc=2 y no
escanea nada:

```powershell
python <MOTOR_ROOT>/scripts/find_similar_signals.py --text "<texto de la ficha>" `
  --archive <MOTOR_ROOT>/.agent/runtime/memory/archive/observations.*.jsonl `
  --backlog <DESTINO>/.agent/collaboration/backlog.md `
  --backlog <DESTINO>/.agent/collaboration/_archive/backlog_done.md
```

Un `[DEDUPE: SIN VECINOS]` estampado sobre un barrido que no corrio es peor que
no deduplicar: da por nueva una ficha que ya existe.

### Dedupe/fusion sobre tickets YA EXISTENTES, no solo altas nuevas (medido 2026-10-15)

El dedupe de arriba cubre el ALTA de una ficha nueva. Pero el backlog
vivo puede acumular, DENTRO de tickets ya existentes, candidatos a fusion
que nadie detecto porque nunca pasaron por este flujo de alta (p.ej. dos
fichas antiguas que describen el mismo defecto con palabras distintas).
Cada fila declara `[LINEA: <nombre>]` -- agrupa mentalmente las filas por
esa etiqueta ANTES de clasificar cada una por separado en la Fase 0/1: si
dentro de una misma linea ves 2+ filas que describen el mismo sintoma, o
una fila que depende implicitamente de otra sin usar la celda "Depende
de", **este prompt NO fusiona ni edita `backlog.md` por si mismo** --
reporta la senal en el informe de salida (Fase 3) como un hallazgo de
dedupe, con los dos IDs y el motivo de sospecha, y la deja fuera del DAG
hasta que se resuelva. `backlog_admit.md` cubre UNICAMENTE el alta de
fichas NUEVAS (su propio alcance declarado); la fusion de DOS fichas YA
EXISTENTES no tiene hoy un flujo mecanico propio -- es el humano o el
Manager, al leer el informe, quien decide fusionar (edicion manual de
`backlog.md` con su propio recibo/evidencia) o declarar la dependencia en
la celda "Depende de" de la fila correspondiente. Este prompt se limita a
SENALAR, nunca a ejecutar ninguna de las dos acciones.

**Pasada barata inter-lineas, obligatoria ademas de la intra-linea**
(medido 2026-10-15, lentes Codex/nan: restringir el censo a una sola
`LINEA` pierde precedentes reales de fusion que cruzaron linea --
`WOT-2026-062g`/`062h` y `WOT-2026-049c`/`049g` no compartian `LINEA`).
Antes de cerrar la Fase 0, agrupa TAMBIEN por el token de `scope`
declarado en cada fila (`motor/<slug>` o `<repo>/<slug>`, el campo que
sigue al `deliverable_type` en el formato de fila) -- esta pasada es
deliberadamente BARATA (agrupar por el token literal de `scope`, sin
comparar texto): cruza la barrera de `LINEA` porque el scope describe la
superficie tecnica, no la categoria narrativa, y evita el barrido GLOBAL
por similitud semantica (costoso, y fuera del alcance de esta pasada). Si
dos o mas filas comparten el MISMO `scope` exacto y estan ambas vivas
(`pending`/`deferred`/`completed-partial`/`blocked`), trata eso como
senal de fusion/dependencia a resolver, igual que el caso intra-linea de
arriba.

**Fallback opcional, solo si la pasada barata no basta**: no existe hoy
una herramienta que filtre `find_similar_signals.py` por `LINEA` o por
`scope`. Si necesitas comparar dos fichas concretas ya sospechadas de
duplicado (no como censo general), puedes usar esa herramienta con
`--text` sobre el contenido de la ficha mas antigua, sabiendo que su
barrido es GLOBAL y es trabajo de similitud semantica mas costoso que la
pasada por `scope` de arriba -- usala como verificacion puntual de un par
ya senalado, no como mecanismo primario de censo.

## Fase 0.pre: Gate de formato (obligatorio, antes de analizar)

Ejecutar:

```powershell
python <MOTOR_ROOT>/scripts/check_backlog_contract.py --project-root <destino>
```

Exigir `exit 0` ANTES de analizar nada. Si el exit code no es 0, detener y
reportar el backlog como no analizable. Este gate no compite con el
validador sintactico WOT-2026-012b: es complementario. `check_backlog_contract.py`
verifica la forma; este triage es el planificador semantico que viene despues.

---

## Fase 0: Reconciliacion (recolector mas juicio, NO determinista)

Leer `backlog.md` completo. Para cada ticket `pending`/`deferred`/
`completed-partial`, RECOLECTAR senales de git y JUZGAR con esas senales:

- `git log --grep <ID>` (commits que mencionan el ticket).
- `git ls-files <archivos-del-scope>` (si los archivos declarados existen).
- greps de terminos del DoD del ticket sobre el codigo/docs actuales.
- `last-run.json` u otro artefacto de ejecucion si existe.

No existe un check determinista generico: cada DoD requiere una verificacion
distinta. Por eso esta fase es **recolector mas juicio**, nunca automatica.

### Verificar el DoD VIGENTE, no solo el DoD en la fecha del commit (medido 2026-10-15)

Un commit puede cerrar PARTE de un DoD y la fila seguir viva porque (a) el
commit solo implementa un subconjunto declarado desde el principio, (b) o
una sesion posterior AMPLIO el DoD con nuevos sub-puntos sobre la MISMA
fila. Estas dos causas se confunden facilmente y exigen el mismo remedio:
**lee el DoD COMPLETO de la fila tal como esta HOY, enumera CADA sub-punto,
y verifica cada uno por separado con su propio comando** -- nunca aceptes
"encontre un commit cuyo subject empieza con el ID" como evidencia de
cierre total.

Senales de que el DoD pudo crecer DESPUES del commit candidato (disparan
escrutinio EXTRA, no son la condicion de entrada de esta regla): marcadores
en el cuerpo de la fila como `== AMPLIACION`, `== AMPLIADA`, `== HALLAZGO
NUEVO`, `== SEGUNDA MEDICION`, `== REINCIDENCIA`, o cualquier fecha
POSTERIOR a la del commit candidato dentro del texto. Si existe un
marcador asi, NO asumas que el commit mas antiguo cierra los sub-puntos
anadidos despues -- verificalos uno a uno igual que los originales. La
ausencia de marcador NO exime de leer el DoD completo: una fila puede
tener sub-puntos (a)(b)(c) sin cerrar desde el principio, sin ninguna
ampliacion posterior, y un commit que solo cierra (a) no cierra la fila.

**Excepcion declarada, no contradiccion**: si la fila separa
explicitamente "DoD de mecanismo" de "DoD de medicion" (ver
`backlog_admit.md`, seccion de alta), "DoD VIGENTE" para efectos de
clasificar `LIKELY_DONE` en ESTA fase significa el DoD de MECANISMO
unicamente. El DoD de medicion (ventana temporal, tasa sobre N sesiones)
NUNCA bloquea que el mecanismo se proponga como cerrado -- se reporta
por separado como deuda `deferred` con su `Reactivation:` explicita, sin
impedir que la parte de mecanismo salga de la Fase 0 como `LIKELY_DONE`.
Si la fila NO declara esa separacion, el DoD vigente es el texto completo
tal cual esta escrito, sin esta excepcion.

### El código de producción puede existir y la cobertura de tests no (medido 2026-10-15, WOT-2026-068l/068m)

Un commit de cierre puede ser ancestro real de `HEAD` y cumplir el DoD en
el momento de commitear, pero sus TESTS de regresion especificos pueden
haber sido BORRADOS por commits POSTERIORES del mismo eje tecnico sin que
nadie lo note -- no es ampliacion de fila, no es rama lateral, no es
error topologico, no es ventana de medicion: el codigo persiste, la
cobertura desaparece. Antes de marcar `LIKELY_DONE`, verifica que los
tests citados por el commit de cierre SIGUEN EXISTIENDO en HEAD
(`git log --oneline HEAD -- <ruta-del-test>` o `grep -n "def test_<patron>"
<fichero-de-test>`), no solo que el commit de produccion es ancestro.

### Universo cerrado por serie (obligatorio, antes de clasificar)

Los estados validos de la cola viva son EXACTAMENTE
`IN {pending, deferred, completed-partial, blocked}`. Antes de clasificar
nada, verifica que cada fila del backlog porte uno de esos cuatro estados.
Una fila con cualquier otro valor (typo, estado legacy, vacio) es una
ANOMALIA: se reporta en el informe con su fila e id, NO se clasifica y NO
entra en ningun pipeline hasta resolverse. El universo queda cerrado por
serie: ninguna fase de este triage puede tratar un estado fuera del conjunto
como si fuera uno de los cuatro, ni silenciar la fila que lo incumple.

### Paso 0.0 -- excluir del lote lo que no es verificable por commit (medido 2026-10-15)

Antes de construir cualquier lote para el patron Builder-real+Revisor-real (ver "Nota de
escala" mas abajo), excluye los tickets que contengan, EN SU SECCION DE DECISION/DoD ACTUAL
(no en una nota historica ya resuelta dentro del mismo texto), cualquiera de estos
marcadores de no-autonomia: `DISENO_PRIMERO`, `DECISION PENDIENTE`, `REQUIERE_HUMANO`,
`HUMAN_GATE`, `APLAZADO POR DEC`. El campo `commits_found` del recolector mide MENCIONES del
ID en subjects de commit, no cierres -- un ticket con `commits_found` alto puede tener como
unico hit una fila de gobernanza del propio backlog (alta, fusion, ampliacion), nunca una
implementacion. Medido: un lote preseleccionado solo por `commits_found>0 AND
paths_absent==0` tuvo que descartarse ENTERO (4/4 candidatos) tras leer sus DoD completos.
No excluyas por `deliverable_type` (un `analysis`/`research` puede tener DoD binario
verificable igual que un `code`); excluye por los marcadores explicitos de arriba.

### Paso 0.1 -- EJECUTAR el recolector (obligatorio)

`scripts/backlog_reconcile.py` YA EXISTE (WOT-2026-021i) y recolecta las senales
de arriba de forma determinista. Ejecutalo ANTES de juzgar nada:

```bash
python scripts/backlog_reconcile.py \
  --motor-root <repo_motor> \
  --project-root <repo_destino>
```

Emite un directorio con las senales crudas por ticket (commits que citan el ID,
existencia de los ficheros del scope, HEAD contra el que se midio). Usa `--out`
para fijar el directorio de salida; si lo omites, lo deriva del destino.

**Trata cada senal emitida como HIPOTESIS A VERIFICAR, nunca como hecho
confirmado** -- el propio recolector lo declara (`This script NEVER
classifies`, ver Paso 0.2): un commit listado es candidato a evidencia,
no evidencia aceptada, hasta pasar las dos verificaciones de abajo
(ancestro real + commit-puente).

**Verificacion adicional obligatoria sobre cada commit candidato (medido
2026-10-15):** que `grep --all` encuentre un commit NO significa que sea
ancestro de `main`/`origin/main` -- puede vivir solo en una rama lateral
(`flight/*`, `vuelo/*`) que nunca se fusiono. Confirma con
`git merge-base --is-ancestor <sha> main` (o `origin/main` si existe)
ANTES de aceptar el commit como evidencia; si el commit vive solo en una
rama lateral, la fila NO es `LIKELY_DONE`, es como mucho
`NEEDS_HUMAN_VERIFY` con esa evidencia declarada. Ademas, si el CUERPO del
commit candidato cita otro SHA como "la implementacion real" o "el
cableado lo entrega" (patron de commit-puente que solo documenta, no
implementa), verifica TAMBIEN ese SHA citado -- no basta con que el
commit madre exista y sea ancestro.

### Paso 0.2 -- CONTRATO DE AUTORIDAD (no negociable)

**El script RECOLECTA; el AGENTE juzga.** Su propio docstring lo fija:
`This script NEVER classifies` (`scripts/backlog_reconcile.py:7`). Emite senales
etiquetadas `[RELATO]`, no veredictos.

Por tanto:

- **PROHIBIDO** derivar `LIKELY_DONE` / `LIKELY_PENDING` / `NEEDS_HUMAN_VERIFY`
  de un campo del JSON. Esas tres etiquetas las emite el agente LEYENDO la
  evidencia, nunca el recolector.
- Un `exit 0` del recolector significa "recolecte", **no** "el backlog esta
  reconciliado". Verifica el ARTEFACTO (el directorio de salida y su contenido),
  no solo el codigo de salida.
- Si el recolector falla o no cubre un ticket, esta fase se hace **a mano** con
  los comandos de arriba para ese ticket. La ausencia de senal no es senal.

### Paso 0.3 -- LEER el bloque `divergences`

`findings.json` trae un bloque `divergences`: contradicciones entre DOS fuentes que
ninguna senal por-ticket puede ver por separado. Hoy emite dos clases:

- `dec_accepted_but_ticket_live`: un DEC marca el ticket como aceptado y su fila
  sigue viva. Lectura inocente posible: el DEC acepto un DISENO, no la implementacion.
- `blocked_with_offqueue_blocker`: una fila `blocked` cuyo bloqueante no esta en la
  cola viva. Lecturas OPUESTAS: el bloqueante se archivo (la fila esta desbloqueada
  y nadie lo vio) **o** es un typo. Resolver antes de proponer nada.

Cada divergencia lleva su evidencia y una `note` que enuncia las lecturas opuestas.
**Son SENAL, no veredicto:** ninguna autoriza por si sola a desbloquear, archivar ni
reclasificar. Se investigan como cualquier otra senal de esta fase.

**Alcance declarado (no inferir cobertura que no hay):** el cruce de bloqueantes
mira SOLO las filas `blocked`, porque son las que nunca entran en reconciliacion.
Una fila `pending` con un bloqueante archivado NO se reporta hoy. Y un bloqueante
escrito en forma corta (`028a` en vez de `WOT-2026-028a`) **no se detecta**: la
celda parece sin bloqueante. Si la celda "Depende de" no esta vacia pero no produjo
senal, verificala a mano.

Emitir por ticket una de estas tres clasificaciones de reconciliacion:

- **LIKELY_DONE**: evidencia de commit/archivo que ya satisface el DoD.
  Etiqueta `VERIFICADO` con `commit:`/`path:` concreto.
- **LIKELY_PENDING**: sin evidencia de que se haya hecho.
- **NEEDS_HUMAN_VERIFY**: senales contradictorias o insuficientes para
  decidir con confianza.
- **PREMISA_NO_REPRODUCIBLE** (medido 2026-10-15, WOT-2026-043e): el objeto concreto que
  motivo la ficha (un dato, una celda, un conteo) ya no se reproduce en el arbol vivo HOY.
  Accion: declarar el PRIMER PASO exigido por el propio ticket si lo tiene (p.ej. "emitir
  `CG-<id>.md` y cerrar sin implementar"); si no lo tiene, anotar el hallazgo sin archivar --
  el objeto puede haberse resuelto por OTRO commit, verificarlo antes.
- **PREMISA_NO_VERIFICABLE** (medido 2026-10-15, WOT-2026-059r): la FUENTE que la ficha cita
  como evidencia de su propia premisa (un documento, un paquete, un buzon) ya no existe ni
  se puede recuperar. Accion: declarar el limite explicitamente; si es razonable, proponer
  candidatos por convergencia de senales independientes (nunca como identidad probada).

**Precedencia entre clasificaciones:** `PREMISA_NO_REPRODUCIBLE` y `PREMISA_NO_VERIFICABLE`
aplican cuando falta el OBJETO o la FUENTE de la premisa (nada que verificar).
`NEEDS_HUMAN_VERIFY` aplica cuando el objeto y la fuente SI existen pero la evidencia
encontrada es CONTRADICTORIA o insuficiente para decidir con confianza. Usa el subtipo mas
especifico que aplique.

Los tickets `LIKELY_DONE` se proponen para archivar y SALEN del analisis de
pipelines: nunca entran en la Fase 2 (agrupacion).

### Paso 0.4 -- PASO MECANICO de localizacion antes de declarar "no existe" (medido 2026-10-15)

Un verificador (humano o agente) puede concluir erroneamente "este script/
funcion no existe" porque busco solo en el `repo_destino` cuando la fuente
CANONICA de un ticket con `delivery_authority: repo_motor` o `scope
motor/...` vive en `repo_motor`. **Una advertencia textual sola NO basta**
-- medido 3 veces consecutivas con el mismo modelo pese a una advertencia
explicita en el prompt de arranque. Antes de escribir "no existe" o
`NO_CIERRA` por ausencia de fichero/funcion:

```bash
test -f <repo_motor>/scripts/<nombre_fichero> && echo "EXISTE EN MOTOR"
test -f <repo_destino>/scripts/<nombre_fichero> && echo "EXISTE EN DESTINO"
```

Si el PRIMER comando (motor) da "EXISTE EN MOTOR", el fichero SI EXISTE;
declarar "no existe" sin haber corrido este par de comandos ambos y pegado
su salida literal es evidencia insuficiente. **Precision de alcance**: la
regla no es que `scripts/*.py` vivan EXCLUSIVAMENTE en el motor -- un
`repo_destino` puede tener copias instaladas de utilidades del motor para
ese destino concreto (ver `AGENTS.md` del workspace). La regla real es:
**la fuente CANONICA de cualquier script/test es siempre el motor**;
busca ahi primero, y si encuentras una copia en el destino que diverge,
la version del motor es la que manda para decidir si el DoD esta cerrado.

---

## Fase 1: Clasificacion de aptitud

Por cada ticket PENDING (todo lo que no quedo `LIKELY_DONE` en la Fase 0),
clasificar en una de tres categorias:

- **APTO_AUTONOMO**: DoD binario, `deliverable_type: code` (o `mixed` con
  gates claros), mutation-verify aplicable, riesgo bajo, cero politica y
  cero `HUMAN_GATE`.
- **REQUIERE_HUMANO**: politica, cambio destructivo, infraestructura local,
  bloqueado por un factor externo.
- **DISENO_PRIMERO**: ficha grande con sub-decisiones de arquitectura
  todavia sin cerrar.

**Superficie en vuelo por otra sesion (fallo medido WOT-2026-016r):** si la
superficie de un ticket (su `Files Likely Touched`/scope) esta siendo
modificada por OTRA sesion activa -- worktree hermano con ticket en vuelo,
cambios sin commitear en el mismo arbol compartido, o ticket `in_flight` con
scope solapado -- su clasificacion es `REQUIERE_HUMANO`, NUNCA
`APTO_AUTONOMO`, con el motivo declarado en `requires_human`. Esta regla es
previa a cualquier otra consideracion de la Fase 1: ningun razonamiento
posterior puede devolver a `APTO_AUTONOMO` un ticket con superficie en vuelo.

Cada clasificacion lleva etiqueta de evidencia `VERIFICADO` / `INFERIDO` /
`REQUIERE_HUMANO`, heredada del contrato de `prompts/audit_agent_output.md`
(mismo contrato que usa `/audit-pipeline`).

---

## Fase 2: Agrupacion en pipelines

Agrupar los tickets `APTO_AUTONOMO` por:

- afinidad tecnica (mismo subsistema o mismo gate -> permite una
  verificacion final comun);
- dependencias declaradas y ocultas;
- blast radius (tickets de alto impacto no se mezclan con higiene de bajo
  riesgo en el mismo pipeline salvo que compartan gate).

Cada pipeline resultante declara:

- nombre;
- tickets en el orden de ejecucion;
- rationale (por que van juntos);
- gate de verificacion comun;
- tamano `S` / `M` / `L`.

### CROSS-TICKET SURFACE SCAN (obligatorio cuando el FLT es resoluble; cobertura declarada SIEMPRE)

Ademas de dependencias declaradas, la Fase 2 exige un escaneo de
superficie cruzada: dos tickets SIN dependencia declarada entre si pero
con `Files Likely Touched` que SE SOLAPAN deben quedar en el MISMO grupo
o serializarse explicitamente (uno depende del otro en el DAG de grupos).
Un DAG construido solo a partir de dependencias declaradas NO es
suficiente: la colision de superficie es una dependencia OCULTA tan real
como una declarada, y omitirla produce una carrera de escritura si dos
grupos se ejecutan en paralelo.

El escaneo es OBLIGATORIO cuando el FLT es resoluble: el triage puede
leer `Files Likely Touched` de los tickets y compararlos para decidir
serializacion. Cuando NO es resoluble -- el gate de WOT-2026-013j
PROHIBE el campo en el backlog a proposito; el FLT canonico vive en
`ticket_contracts.md`, indexado por `T-XXXX-NNN` mientras el DAG razona
en `WOT-YYYY-NNNx`, y la resolucion por prosa se midio al 46% de
ambiguedad -- el grupo NO omite el dato: declara `surface_scan` con
`{"executed": false, "coverage": "0/N", "method": "<por que no se
resolvio>"}`. La cobertura se declara SIEMPRE, resuelto o no: lo que se
bloquea es el SILENCIO, no la ausencia de dato.

### DEPENDENCIA REAL vs PREFERENCIA DE ORDEN (WOT-2026-023u)

`depends_on_groups` (y su reciproco `blocks_groups`) modela SOLO dependencia
REAL: el grupo B **consume un artefacto o estado que produce A**, hay un
bloqueo explicito, o **comparten una superficie serializada** (surface scan
de arriba). La preferencia de orden SIN consumo ni superficie compartida
-- "prefiero correr A antes que B" -- **NO DEBE** entrar en
`depends_on_groups`/`blocks_groups`: dos grupos asi son INDEPENDIENTES. El
orden preferido se expresa con `recommended_start`, el orden de la lista de
grupos o el `rationale`, nunca con una arista del DAG.

Por que importa (incidente inaugural 2026-07-13): el triage encadeno
G1(022v)->G2(023q)->G3(023s) como `depends_on` cuando solo era preferencia
("instrumentos antes que produccion"); G1 paro en el contract-audit y la
regla de contencion habria CONGELADO G2 y G3, que no dependian de 022v para
nada. Una arista falsa en el DAG convierte una parada local en una cascada
global. Ante la duda: si B corriera ANTES que A y no consumiera nada suyo ni
tocara su superficie, ¿seguiria siendo correcto? Si la respuesta es si, son
independientes -- no hay arista.

### Autoridad de la clasificacion

`class` (S/M/L) y `autonomy_mode` (p.ej. `autonomous`,
`hard-stop-with-recovery`) los asigna el TRIAGE, no el ejecutor. El
ejecutor (`/orchestrate-pipeline` u otro consumidor del DAG) NUNCA
reclasifica un grupo para evitar un gate: reclasificar para esquivar un
`common_gate` o un `autonomy_mode` mas estricto es, por definicion,
`falso_verde` bajo el contrato de `prompts/audit_agent_output.md`.

### El triage sigue siendo solo lectura

Esta fase produce el DAG de grupos (que ordenar, que serializar, que
paralelizar); NO lo ejecuta. La ejecucion sigue siendo responsabilidad
exclusiva de `/orchestrate-pipeline`. El triage no gana logica de
ejecucion por tener ahora un DAG en vez de una lista plana: sigue siendo
un planificador, nunca un ejecutor.

**Decision de diseno confirmada (bucle adversarial 2026-10-15, 7 lentes
independientes, 6/7 CAMBIOS_NECESARIOS sobre la propuesta original):**
se evaluo y se DESCARTO dar a este prompt autoridad de escritura directa
sobre `backlog.md`. Ya existe una decision de diseno previa que lo
prohibe explicitamente
(`.agent/planning/design_autonomous_ticket_batch.md:373`: "NO meter la
ejecucion dentro de `backlog_triage.md` (debe seguir read-only)"), y el
bucle encontro un riesgo real que la justifica: un falso `pending` es
benigno (se re-tria), pero un falso `completed` archivado directamente
es destructivo y de baja visibilidad -- la misma sesion que motivo esta
nota demostro que el juicio de un agente sin segundo verificador falla
(Revisor refutando al Builder 3 veces en el primer lote de una sesion de
higiene real). El read-only de este prompt sigue siendo la barrera
correcta: la ejecucion del archivado (patron Builder-real + Revisor-real,
ver "Nota de escala" mas abajo) es responsabilidad de quien EJECUTA el
informe de este triage, nunca de este prompt.

---

## Fase 3: Sintesis y recomendacion

Ordenar los pipelines por valor/riesgo: mas valor con menos riesgo primero.
La higiene de suite o codigo muerto suele ir primero porque despeja el
terreno para el resto.

### TDS como senal de desempate

Para desempatar dentro de un mismo grupo de pipelines o priorizar los de
valor comparable, se puede recalcular el TDS (Technical Debt Score):

```powershell
python <MOTOR_ROOT>/scripts/backlog_priority_score.py --project-root <DESTINO_ROOT> --ticket <ID-DEL-TICKET> --format json
```

O para una corrida global sobre todo el backlog:

```powershell
python <MOTOR_ROOT>/scripts/backlog_priority_score.py --project-root <DESTINO_ROOT> --format json
```

El TDS aporta una senal numerica complementaria (severidad, reincidencia,
desbloqueo, coste y antiguedad), pero NO participa en la clasificacion
de aptitud (Fase 1): esa sigue siendo APTO_AUTONOMO/REQUIERE_HUMANO/
DISENO_PRIMERO segun DoD, riesgo y politica. El TDS se usa como
desempate dentro de los grupos de valor comparable.

**Terminologia:** "recalcular TDS" designa la operacion puntual de un
ticket; "re-triaje" se reserva para el proceso completo de
`backlog_triage.md` (Fase 0 reconciliacion, Fase 1 clasificacion,
Fase 2 agrupacion, Fase 3 sintesis).

Salida obligatoria de esta fase:

- Listar EXPLICITAMENTE los tickets `REQUIERE_HUMANO`, con motivo, separados
  de los pipelines autonomos.
- Senalar los tickets cuya premisa hay que reverificar: candidatos a
  ya-hechos que la Fase 0 no pudo confirmar con certeza suficiente
  (`NEEDS_HUMAN_VERIFY`).
- Recomendar explicitamente por cual pipeline empezar.

---

## Nota de escala (tecnica opt-in, no obligacion)

El analisis multi-lente (fan-out de varios agentes trabajando el mismo
backlog desde angulos distintos) es RECOMENDADO para backlogs grandes (mas de
6 tickets `pending` aproximadamente, o mezcla de scopes/autoridades
distintas dentro del mismo backlog). Es OPCIONAL para backlogs pequenos: un
solo agente en una pasada basta.

### Patron Builder-real + Revisor-real para la Fase 0 a escala (medido 2026-10-15, 151 candidatos en 15 lotes)

Cuando la Fase 0 tiene que verificar muchos candidatos `LIKELY_DONE` (el
caso de un censo grande del recolector), el analisis multi-lente de arriba
puede sustituirse por un patron mas fuerte: un **Builder real** (CLI
directo, canal `agent`, filesystem propio -- ver
`prompts/builder_invocation_contract.md`, NUNCA `ensemble_dispatch.py`
para esto) investiga un lote pequeno (3-5 tickets) y clasifica
`LIKELY_DONE_COMPLETO | PARCIAL | NO_CIERRA` con evidencia en disco; un
**Revisor real** (modelo distinto, mismo mecanismo) re-verifica de forma
independiente CUALQUIER veredicto `LIKELY_DONE_COMPLETO` antes de que se
proponga para archivar -- nunca se fia de las citas del Builder, repite
sus propios comandos. Quien EJECUTA el informe de este triage (no este
prompt) aplica el resultado final.

**Condicion dura de esta tecnica**: quien aplica el veredicto final (el
Manager o quien ejecuta el informe) **debe** haber ejecutado su propia
verificacion en disco -- nunca acepta como evidencia un auto-reporte solo
citado por el Builder o solo citado por el Revisor, haya o no discrepancia
entre ambos. La pareja Builder+Revisor reduce cuanto hay que re-verificar
(cuando coinciden, la re-verificacion puede ser mas ligera), pero no la
sustituye: el riesgo de que dos modelos distintos compartan el mismo sesgo
sistemico (ver el error topologico motor-vs-destino repetido 3 veces en
esta misma sesion, PASO 0 mecanico de arriba) no desaparece por acuerdo
entre ambos. Esta condicion no crea un rol nuevo: formaliza que la pareja
Builder+Revisor (dos modelos distintos, sin visibilidad cruzada de la
respuesta del otro) es el segundo punto de verificacion independiente que
sustituye al "humano decide" cuando el volumen hace inviable una revision
manual total.

**Concurrencia maxima del canal `agent` compartido (medido 2026-10-15;
corregido tras bucle DESIGN_REVIEW de 3 lentes -- Codex + 2 nan/agent -- que
detecto una inversion factual en la version original de este parrafo):** al
lanzar varios Builders o Revisores reales (Kilo/Codex/OpenCode con
filesystem) sobre el MISMO backend compartido (p.ej. varios perfiles `nan`),
lanza de A LO SUMO DOS a la vez, nunca en bloque mayor. Medido: 4
lanzamientos simultaneos de `nan/qwen3.6` dejaron a los DOS PRIMEROS
lanzados encolados varios minutos sin avanzar un solo paso (`step_start`
ausente en su log), mientras los DOS ULTIMOS lanzados progresaban con
normalidad desde el primer minuto -- la contencion del pool compartido no
es hipotetica, es observable en el propio log. **Declaracion de alcance:**
el umbral "DOS" es la cautela adoptada de una sugerencia en vivo del
usuario, NO un maximo medido -- el dato solo mide que 4 simultaneos saturan;
no hay evidencia propia de que 3 sea seguro o de que 2 sea el techo optimo.
Tratar "DOS" como punto de partida conservador, ajustable con mas
mediciones, no como constante demostrada.

**Criterio de "pareja atascada":** antes de lanzar la siguiente pareja,
verifica que la pareja anterior ya escribio su artefacto de entrega, O que
su log muestra al menos un `step_start`/`tool_use` reciente (progreso real,
no solo "el proceso sigue vivo"). Si una pareja lleva mas de ~3 minutos sin
ningun `step_start` nuevo, trata eso como señal de atasco: no lances la
siguiente pareja encima (agravaria la contencion); espera a que la atascada
progrese o termine, o escala al usuario si el atasco persiste. Sin este
criterio, la regla de "dos en dos" puede bloquear el lote entero si una
pareja se cuelga, exactamente el fallo que pretende evitar.

**Espera por marca inequivoca, no por temporizador (medido 2026-10-15):**
tras lanzar un Builder/Revisor real en background, la condicion de
finalizacion VERIFICABLE es la APARICION de su artefacto de entrega
declarado (el fichero que la tarea le exige escribir) -- el `exit code` del
wrapper de lanzamiento es evidencia NECESARIA pero no SUFICIENTE (CEM v0:
"un `exit 0` puede significar no hice nada"), nunca la unica señal. **La
aparicion del fichero tampoco basta por si sola:** verifica ademas que su
contenido no esta vacio o truncado (un artefacto de 0 bytes o cortado a
mitad de frase es la misma trampa que un exit 0 sin trabajo real). Cuando
el harness de la sesion ofrezca un mecanismo de vigilancia por evento
(polling de una condicion de fichero/log hasta que se cumple, con
notificacion automatica), prefierelo sobre una espera de tiempo fijo: una
espera fija o sobra tiempo o se queda corta. Para N artefactos pendientes,
una sola vigilancia que notifique por cada uno segun aparece es mas
eficiente que N rondas de "espera X minutos y comprueba". **Cota maxima
obligatoria:** toda vigilancia por evento declara un timeout maximo (no
queda esperando indefinidamente si el artefacto nunca aparece); al expirar
sin señal, trata el lanzamiento como sospechoso de atasco (ver criterio de
arriba) en vez de seguir esperando en silencio.

**Contrato duro de lectura entera (medido 2026-10-15, WOT-2026-042g y
WOT-2026-044j):** antes de que el Builder o el Revisor declaren que un
guard/check/funcion NO existe o NO cubre una propiedad, deben leer el
fichero candidato ENTERO -- un `grep` de una palabra NO basta. Dos lotes
reales midieron que el Builder declaro ausente un check que SI existia,
bajo otro nombre de funcion dentro del MISMO fichero, y solo la lectura
entera del Revisor lo detecto; en ambos casos el veredicto FINAL no
cambio, pero la justificacion del Builder era falsa y tuvo que corregirse.
Un `grep` que no encuentra un termino es evidencia de que ESE TERMINO no
aparece, nunca de que la FUNCION esta ausente.

**Contrato duro de cita literal de estructuras de datos (medido 2026-10-15, campana Grupo A):**
cuando el Builder o el Revisor citan el CONTENIDO de una coleccion de codigo (lista, frozenset,
enum, diccionario) como evidencia de un DoD, deben pegar la salida LITERAL de un comando de
lectura (`sed -n <rango>`, o equivalente) de esa seccion exacta del fichero -- nunca
reescribirla de memoria/parafraseada. Medido: un Builder cito un `frozenset` de 7 estados
omitiendo uno (`superseded`) por reconstruirlo de memoria en vez de releerlo, lo que invalido su
analisis de divergencia (aunque el veredicto final no cambio porque el Revisor si releyo el
fichero). Es el mismo fallo de fondo que el "Contrato duro de lectura entera" de arriba
(evidencia no verificada presentada como verificada), pero manifestado al CITAR un dato ya
leido antes, no al declarar ausencia de una funcion. Excepcion de seguridad heredada de
`prompts/audit_agent_output.md`: "salida literal" nunca exige volcar secretos, tokens o
credenciales -- si la seccion citada los contiene, se redacta (`***REDACTED***`) y se declara
el redactado, nunca se omite la cita entera por eso.

**Contrato duro de no fabricar salida de comandos silenciosos (medido 2026-10-15, experimento
de calibracion de modelos economicos; validado OK por bucle DESIGN_REVIEW de 3 lentes):** antes
de citar la "salida literal" de un comando de verificacion (ancestria, diff, `--quiet`), el
Builder o el Revisor confirma PRIMERO si ese comando concreto imprime algo en caso de exito.
Varios comandos habituales de este contrato (`git merge-base --is-ancestor`, la mayoria de
`git <subcomando> --quiet`) NO IMPRIMEN NADA en exito -- solo devuelven un exit code. Medido dos
veces en la misma sesion: un Builder (qwen3.6) y un Revisor (gemma4, antes de esta correccion)
citaron `Salida: YES_ANCESTOR` para `git merge-base --is-ancestor`, un texto que ese comando
nunca produce -- el HECHO subyacente resulto ser cierto en ambos casos, pero la "salida literal"
pegada era una invencion, exactamente el anti-patron que el contrato de cita literal de arriba
existe para prevenir, aplicado aqui a un comando silencioso en vez de a una coleccion de codigo.
**Regla operativa: si el comando no imprime nada, reporta el EXIT CODE real (`echo "exit=$?"`
inmediatamente despues, nunca `$?` tras un pipe -- ver regla de AGENTS.md sobre
autoengano-por-pipe), nunca un texto de salida inventado.** Para saber de antemano si un comando
imprime algo en exito, revisa su `--help`/manual o haz una corrida de prueba en un repo/commit de
control conocido antes de citarlo como evidencia. Tras anadir esta clausula EXPLICITA al prompt
de tarea del Revisor, el mismo modelo que antes fabrico "YES_ANCESTOR" dejo de hacerlo y ademas
detecto un defecto de rigor fino del Builder en la misma corrida -- la correccion tuvo efecto
medible EN ESTA SESION (2/2 casos tras aplicarla, 0/2 antes), declarado como observacion de
sesion, no como tasa general garantizada para cualquier modelo o dominio.

**Checklist estructurado por regla dura (medido 2026-10-15, campana Grupo A), reemplaza el
grep de frases de auto-admision:** el informe final del Builder enumera PRIMERO, en una lista
explicita, las reglas duras del prompt de tarea que lo invoco (nunca a criterio del Builder
decidir cuales cuentan como "duras": son las que el prompt de tarea marca como tal), y despues
incluye una fila por cada una: `regla | comando ejecutado (o root/topologia usado, ver Paso 0.4,
si la regla no produce stdout) | salida literal o referencia reproducible y localizable a ella |
resultado`. Un Builder omitio la verificacion de ancestria (`git merge-base --is-ancestor`) en
su primer uso de un modelo nuevo en la sesion, y lo admitio en prosa libre dentro de una seccion
de "dudas" al final del informe -- una deteccion automatica por grep de frases ("no se pudo
verificar", "no ejecute") habria sido fragil ante sinonimos ("no lo revise porque parecia obvio"
no coincide con ningun patron fijo). El checklist estructurado hace la omision visible por
AUSENCIA DE FILA, no por coincidencia de texto libre, y el Revisor la contrasta linea por linea
contra su propia ejecucion. Este checklist es ADITIVO: complementa el informe Builder existente
(evidencia en disco, veredicto por ticket), nunca lo sustituye.

**Refuerzo de primer uso de un modelo nuevo como Builder (medido 2026-10-15, campana Grupo A):**
el primer lote de la sesion con cualquier modelo NUEVO en el rol Builder recibe, en su prompt
de tarea, el bloque completo de reglas duras marcado como NO OPCIONAL de forma explicita (el
texto que hoy solo se anade de forma REACTIVA tras detectar un fallo) -- no se espera a que el
modelo falle una vez para reforzar el prompt. Medido: el mismo modelo (`qwen3.6`) omitio una
regla dura en su primer uso de la sesion y la cumplio correctamente en el segundo, tras que el
Manager anadiera manualmente ese refuerzo citando el fallo anterior. El coste de anadirlo desde
el primer uso es una linea de prompt; el coste de no hacerlo fue un veredicto intermedio
apoyado en una verificacion nunca ejecutada, atrapado solo porque el Revisor y el Manager lo
notaron por lectura atenta, sin ningun mecanismo que lo garantizara.

**Las tareas de Builder/Revisor del triaje NO se redactan libremente: se instancian desde
plantilla, y la plantilla declara de que contrato canonico existente toma cada pieza (medido
2026-10-15, validado por bucle DESIGN_REVIEW de 3 lentes):** antes de escribir a mano el fichero
de tarea de un Builder o Revisor, busca si ya existe un contrato de revision/invocacion
aplicable en `prompts/` (candidatos conocidos: `prompts/manager_review.md` para el formato de
revision -- sanity-check previo (Paso 1c), tabla de claims-vs-evidencia con veredicto
`confirmado/impreciso/falso`, formato fijo de informe de salida -- y
`prompts/builder_invocation_contract.md` para el MECANISMO exacto de invocacion via CLI, que ya
define el comando canonico `kilo run --auto -m nan/<modelo> --dir <repo> --format json
--print-logs -f <tarea> -- <mensaje>`). Si existe, la tarea nueva lo cita explicitamente y
declara que partes toma prestadas y cuales omite a proposito (p.ej. el mutation-verify de codigo
de `manager_review.md` no aplica a revision documental de triaje). Si la busqueda NO encuentra
ningun contrato aplicable, declara explicitamente "busque en X, Y, Z; no encontre protocolo
aplicable" antes de redactar libremente (misma norma ya existente en `AGENTS.md`, "Decision de
proceso sin instruccion exacta => BUSCA protocolo documentado antes de suponer uno"), y la tarea
ad-hoc resultante queda marcada como candidata a convertirse en plantilla reutilizable si el
mismo patron se repite en una sesion futura. Esto evita reinventar, sesion tras sesion, un
formato de revision que ya existe y ya esta calibrado por otros tickets. Dos plantillas de
ejemplo, derivadas de estos dos contratos para el caso de revision documental de backlog:
`REVISOR_TASK_TEMPLATE_experimento_calibracion.md` y `BUILDER_TASK_TEMPLATE_experimento_calibracion.md`
(ambas en `.agent/planning/` del repo_destino de origen; no son parte de este repo_motor, son el
ejemplo vivo de la tecnica).

**Rol del Revisor mas alla de confirmar o refutar (medido 2026-10-15,
WOT-2026-059r):** si una premisa resulta irresoluble por falta de un dato
(p.ej. el nombre de un guard citado por una fuente ya drenada), el Revisor
puede proponer un candidato por CONVERGENCIA de senales independientes
(fecha, superficie, estado del guard, contexto de la sesion que lo
origino), declarando SIEMPRE y explicitamente que es una hipotesis
razonada y no una identidad probada. Esto reduce el coste de que una
sesion futura repita la misma busqueda infructuosa, sin fingir una
certeza que no existe.

**Extraccion de filas por texto (medido 2026-10-15, propio del Manager):**
cualquier extraccion automatizada de una fila de `backlog.md` por texto
(Python, grep, etc.) debe anclar la celda EXACTA del ID
(`r'\|\s*\w+\s*\|\s*' + re.escape(id) + r'\s*\|'` sobre la PRIMERA linea
del bloque -- el `\w+` cubre la celda de Prioridad que precede al ID,
nunca el ID en si, asi que los guiones de un ID como `WOT-2026-040o` no
son un problema para este patron), nunca un substring-anywhere: un ID
corto puede aparecer como substring de otro ID mas largo o en cualquier
posicion de un bloque de texto largo, devolviendo la fila equivocada. La
extraccion debe ademas exigir EXACTAMENTE una coincidencia y fallar
explicito ante cero o varias.

### Presupuesto de fan-out multiagente

Antes de lanzar un fan-out multiagente, pide autorizacion explicita y declara
el presupuesto de contexto:

- numero de agentes previstos;
- fase y objetivo de cada grupo de agentes;
- coste esperado (`bajo` / `medio` / `alto`);
- riesgo de agotar la sesion antes de la sintesis final;
- recomendacion de modelo: si el coste es `medio` o `alto`, recomienda bajar
  el nivel para fases repetitivas o exploratorias (por ejemplo, `Opus` ->
  `Sonnet`, `GPT-5.5` -> `GPT-5.4`) y reservar el modelo mas fuerte para
  sintesis final o ataques criticos.

Reglas operativas:

- Por defecto, usa 3-5 agentes como maximo. Mas de 5 agentes requiere
  justificacion explicita en el prompt de autorizacion.
- No entregues el historial completo a todos los agentes. Usa fases:
  `recon compacto -> resumen normalizado -> ataque focal -> sintesis`.
- Los agentes de recon/ataque deben devolver salidas compactas en tabla
  (`claim/vector/evidencia/veredicto/bloquea`), no transcripts narrativos
  largos salvo que sean evidencia imprescindible.
- Reserva un agente final de sintesis que reciba solo los hallazgos
  normalizados, no todos los transcripts completos. Quedarse sin cuota antes
  de la sintesis invalida el valor del fan-out.

---

## Los 5 riesgos codificados

1. **No hinchar `orchestrator_pipeline.md`**: el metodo completo vive en este
   prompt. El cableado en `orchestrator_pipeline.md` es solo referencia mas
   consumo del JSON de salida, nunca una copia de estas fases.
2. **El triage puede fabricar certezas**: toda clasificacion (Fase 0 y Fase 1)
   lleva etiqueta de evidencia (`VERIFICADO` / `INFERIDO` / `REQUIERE_HUMANO`),
   heredada de `prompts/audit_agent_output.md`. Ninguna clasificacion se
   presenta como hecho sin artefacto.
3. **Backlog stale (reconciliacion primero)**: la Fase 0 es SIEMPRE el primer
   paso de analisis, antes de cualquier clasificacion o agrupacion. Un
   ticket `LIKELY_DONE` nunca entra en un pipeline.
4. **Autonomia falsa**: la Fase 1 separa `APTO_AUTONOMO` de `REQUIERE_HUMANO`
   y de `DISENO_PRIMERO`. Ningun ticket destructivo, de politica, con
   `HUMAN_GATE`, con infraestructura fuera de git o con superficie en vuelo
   por otra sesion entra jamas en un pipeline autonomo (WOT-2026-016r).
5. **La skill es puntero, no fuente**: `skills/backlog-triage/SKILL.md` no
   redeclara este metodo. Remite aqui con la clausula "el prompt es la
   fuente de verdad; si algo diverge, prevalece este prompt".

---

## Salida obligatoria

Dos artefactos, en el mismo turno, bajo
`<destino>/orchestrator_pipeline/reports/` (mismo patron de rutas que
`/audit-pipeline`). `<destino>` aqui es SIEMPRE el `destination_root`
resuelto del `motor_destination_link.json` (ver Nota de topologia): jamas una
ruta literal del prompt de sesion, jamas una ruta del motor (`repo_motor`,
worktree `_dev` o checkout principal).

- Informe Markdown: `backlog_triage_<YYYYMMDD-HHMMSS>.md`, con las fases 0
  (reconciliacion), 1 (clasificacion), 2 (agrupacion) y 3 (sintesis)
  desarrolladas. Ademas, el informe incluye:

  - **Snapshot con hora:** al INICIO y al FINAL del triaje: hora (ISO-8601
    UTC), HEAD del motor, HEAD del workspace y `dirty` de ambos,
    correlacionados con los campos `generated_at` / `state_at_triage` del
    JSON (el esquema JSON no cambia).
  - **Checklist binario de cierre:** lista de items SI/NO (`[x]` / `[ ]`,
    sin grises): gate de formato exit 0, recolector ejecutado y verificado
    por artefacto, universo de estados verificado (sin anomalias sin
    reportar), snapshot inicial y final identicos, `validate_batch_dag.py`
    exit 0, encoding guard exit 0 sobre la lista explicita de ficheros
    escritos. Un item fallido no se maquilla: se declara como tal y aplica
    la regla de su fase (los gates detienen).
  - **Protocolo `EXTERNAL_WRITE_DETECTED`:** si entre el snapshot inicial y
    el final el estado cambio (HEAD movido, `dirty` flip, `backlog.md`
    modificado) -- otra sesion escribio mientras el triaje corria -- el
    informe lo declara LITERALMENTE `EXTERNAL_WRITE_DETECTED`, identifica
    las fases afectadas y las re-analiza sobre un snapshot fresco. Nunca se
    construyen conclusiones mezclando snapshots.

- JSON portable: `backlog_triage_<YYYYMMDD-HHMMSS>.json`, con el esquema:

**BARRERA (cableada en codigo, WOT-2026-049c):** el DAG NO se escribe con la
herramienta de escritura nativa del agente. Se materializa con
`scripts/backlog_triage_writer.py`, UNICO dueno de la escritura, que aplica
la copia-puntero: antes de escribir el fichero nuevo copia el DAG previo con
`shutil.copy2` a `backlog_triage_<ts>_previo.json` (nunca lo sobrescribe sin
copia), y escribe el nuevo con write-tmp-then-rename (atomico). Comando
exacto (el DAG construido se pasa por stdin, o con `--from-file`):

```powershell
python <MOTOR_ROOT>/scripts/backlog_triage_writer.py write `
  --project-root <destino>
```

`--out-dir <dir>` sobreescribe el destino derivado
(`<project-root>/orchestrator_pipeline/reports/`). El escritor NO valida el
esquema: sigue siendo `validate_batch_dag.py` quien lo valida despues.

```json
{
  "pipelines": [
    {
      "name": "string",
      "tickets": ["WOT-2026-XXXa"],
      "rationale": "string",
      "common_gate": "string",
      "size": "S|M|L"
    }
  ],
  "tickets": [
    {
      "id": "WOT-2026-XXXa",
      "classification": "APTO_AUTONOMO|REQUIERE_HUMANO|DISENO_PRIMERO",
      "reconciliation": "LIKELY_DONE|LIKELY_PENDING|NEEDS_HUMAN_VERIFY",
      "evidence_label": "VERIFICADO|INFERIDO|REQUIERE_HUMANO",
      "artifact": "commit:<sha>|path:<ruta>|null"
    }
  ],
  "recommended_start": "string (nombre de pipeline)",
  "requires_human": [
    {"id": "WOT-2026-XXXa", "reason": "string"}
  ],
  "premise_verify": [
    {"id": "WOT-2026-XXXa", "reason": "string"}
  ],
  "schema": "autonomous-batch-dag/v1",
  "generated_at": "string (ISO-8601)",
  "state_at_triage": {
    "motor": "string (sha)",
    "workspace": "string (sha)",
    "dirty": "0|1"
  },
  "groups": [
    {
      "id": "G-EJEMPLO",
      "tickets": ["WOT-2026-XXXa"],
      "depends_on_groups": [],
      "blocks_groups": ["G-OTRO"],
      "shared_surfaces": ["ruta/relativa/archivo.py"],
      "surface_scan": {
        "executed": true,
        "coverage": "11/23",
        "method": "FLT de ticket_contracts.md"
      },
      "class": "S|M|L",
      "autonomy_mode": "autonomous|hard-stop-with-recovery",
      "common_gate": "string (comando exacto)",
      "recovery_owner_stage": "BUILDER|MANAGER",
      "max_recovery_attempts": "int"
    }
  ],
  "stop_policy": {
    "hard_stop_causes": ["string"],
    "recoverable_causes": ["string"],
    "max_unclassified_stops": "int"
  },
  "budget": {
    "max_tickets_closed": "int",
    "max_group_recoveries": "int"
  }
}
```

Las claves `pipelines`, `tickets`, `recommended_start`, `requires_human` y
`premise_verify` son el esquema historico (lista plana de pipelines) y se
MANTIENEN sin cambios: es un cambio ADITIVO. Las claves nuevas
(`schema`, `generated_at`, `state_at_triage`, `groups`, `stop_policy`,
`budget`) anaden el DAG de grupos: cada `group` es una unidad de
serializacion/paralelizacion derivada de los `pipelines` de la Fase 2 mas
el cross-ticket surface scan. `depends_on_groups` / `blocks_groups` deben
ser reciprocas (si G1 bloquea G2, G2 depende de G1). Antes de entregar
el JSON, validarlo con:

```powershell
python <MOTOR_ROOT>/scripts/validate_batch_dag.py <destino>/orchestrator_pipeline/reports/backlog_triage_<YYYYMMDD-HHMMSS>.json
```

Exigir exit 0. Un DAG que no valida no es una salida completa de esta
fase: corregir el DAG, no el validador.

El binding es EXCLUSIVO: `validate_batch_dag.py` valida el DAG JSON que este
prompt produce (`backlog_triage_<YYYYMMDD-HHMMSS>.json`), NUNCA el
`findings.json` del recolector de la Fase 0 -- son artefactos distintos, con
esquemas distintos, y validar el segundo es validar OTRA cosa (fallo medido
en los triajes 20260922).

Cierre de artefactos (obligatorio, antes de declarar el triage completo):
pasa el encoding guard sobre la LISTA EXPLICITA de ficheros que este triaje
escribio -- sus dos artefactos de salida, ni uno mas, ni un barrido
generico:

```powershell
python <MOTOR_ROOT>/scripts/check_encoding_guard.py `
  <destino>/orchestrator_pipeline/reports/backlog_triage_<YYYYMMDD-HHMMSS>.md `
  <destino>/orchestrator_pipeline/reports/backlog_triage_<YYYYMMDD-HHMMSS>.json
```

Exigir exit 0 con el denominador publicado (2 auditados, 0 saltados). Un
guard verde sobre un universo distinto al declarado no cuenta como cierre.

El informe NO escribe `backlog.md`: propone. El humano o el Manager decide
archivar los `LIKELY_DONE` o lanzar el pipeline recomendado.

---

## Restriccion dura

- NO reabre tickets ni modifica `backlog.md`.
- NO escribe codigo ni estado operativo.
- NO ejecuta el pipeline (eso es `/orchestrate-pipeline`).
- NO audita un pipeline ya cerrado (eso es `/audit-pipeline`).
- El DAG de grupos (`groups`, `stop_policy`, `budget`) es una PROPUESTA de
  orden y agrupacion, no una ejecucion: producir el DAG nunca es
  ejecutarlo. La logica de `autonomy_mode`, `recovery_owner_stage` y
  `max_recovery_attempts` la INTERPRETA el ejecutor; el triage no la
  aplica.
- Solo escribe sus dos artefactos de salida y propone.
