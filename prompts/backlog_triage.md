# Prompt: Triage del Backlog (analisis pre-pipeline)

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

## Principio rector

Read-only sobre el backlog: este triage NUNCA muta `backlog.md`, codigo ni
estado operativo. Propone; el humano o el Manager decide archivar tickets o
lanzar un pipeline.

---

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

Los tickets `LIKELY_DONE` se proponen para archivar y SALEN del analisis de
pipelines: nunca entran en la Fase 2 (agrupacion).

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

### CROSS-TICKET SURFACE SCAN (obligatorio)

Ademas de dependencias declaradas, la Fase 2 exige un escaneo de
superficie cruzada: dos tickets SIN dependencia declarada entre si pero
con `Files Likely Touched` que SE SOLAPAN deben quedar en el MISMO grupo
o serializarse explicitamente (uno depende del otro en el DAG de grupos).
Un DAG construido solo a partir de dependencias declaradas NO es
suficiente: la colision de superficie es una dependencia OCULTA tan real
como una declarada, y omitirla produce una carrera de escritura si dos
grupos se ejecutan en paralelo.

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

---

## Fase 3: Sintesis y recomendacion

Ordenar los pipelines por valor/riesgo: mas valor con menos riesgo primero.
La higiene de suite o codigo muerto suele ir primero porque despeja el
terreno para el resto.

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
   `HUMAN_GATE` o con infraestructura fuera de git entra jamas en un
   pipeline autonomo.
5. **La skill es puntero, no fuente**: `skills/backlog-triage/SKILL.md` no
   redeclara este metodo. Remite aqui con la clausula "el prompt es la
   fuente de verdad; si algo diverge, prevalece este prompt".

---

## Salida obligatoria

Dos artefactos, en el mismo turno, bajo
`<destino>/orchestrator_pipeline/reports/` (mismo patron de rutas que
`/audit-pipeline`):

- Informe Markdown: `backlog_triage_<YYYYMMDD-HHMM>.md`, con las fases 0
  (reconciliacion), 1 (clasificacion), 2 (agrupacion) y 3 (sintesis)
  desarrolladas.
- JSON portable: `backlog_triage_output.json`, con el esquema:

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
python <MOTOR_ROOT>/scripts/validate_batch_dag.py <destino>/orchestrator_pipeline/reports/backlog_triage_output.json
```

Exigir exit 0. Un DAG que no valida no es una salida completa de esta
fase: corregir el DAG, no el validador.

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
