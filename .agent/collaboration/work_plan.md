# Plan de Trabajo: capacidad /backlog-triage (analisis pre-pipeline del backlog)

## Metadata
- **ID:** WOT-2026-021h
- **Estado:** COMPLETED
- **deliverable_type:** mixed
- **Creado:** 2026-07-09
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
Crear la capacidad /backlog-triage: el espejo PRE-PIPELINE de /audit-pipeline.
Tres piezas nuevas/modificadas, en este orden: (1) prompts/backlog_triage.md
(metodo, fuente de verdad), (2) skills/backlog-triage/SKILL.md (puntero, molde
exacto de skills/audit-pipeline/SKILL.md), (3) cableado CONDICIONAL minimo en
prompts/orchestrator_pipeline.md (paso 5 del bootstrap, l.44-45) que consuma la
salida del triage sin incrustar su metodo.

## Contexto
El 2026-07-09, antes de organizar el backlog tras cerrar WOT-2026-021g, el
orquestador ejecuto AD-HOC un analisis en 3 fases (reconciliacion contra git,
agrupacion multi-lente, sintesis en pipelines ordenados) que evito planificar 4
tickets ya hechos (020m/020s/021e/020u) y produjo pipelines ejecutables. El
usuario pidio cristalizar el proceso como capacidad reutilizable, formando el
ciclo de vida limpio del backlog: /backlog-triage (antes) / /orchestrate-pipeline
(durante) / /audit-pipeline (despues).

Contrato fuente completo (2 pasadas adversariales ya incorporadas):
orquestador_de_agentes_workspace/orchestrator_pipeline/cleanup/next_session_dev/CONTRATO_WOT-2026-021h_backlog_triage.md
Este work_plan es su materializacion ejecutable; en caso de discrepancia de
detalle, el contrato es la fuente de las decisiones de alcance y este plan la
fuente de la secuencia Builder.

## Configuracion Privada Requerida
Ninguna. No se necesitan credenciales ni archivos en privada/.

## Decision de arquitectura (fijada por el usuario 2026-07-09, vinculante)
TRES piezas, metodo primero, automatizacion despues:
1. prompts/backlog_triage.md (source_of_truth): el metodo del analisis
   pre-pipeline. 4 fases (0.pre gate, 0 reconciliacion, 1 clasificacion, 2
   agrupacion, 3 sintesis) mas los 5 riesgos codificados.
2. skills/backlog-triage/SKILL.md (wrapper PUNTERO, NO fuente normativa):
   molde EXACTO = skills/audit-pipeline/SKILL.md (misma estructura de
   secciones y frontmatter, stage: plan).
3. Cableado MINIMO en prompts/orchestrator_pipeline.md: el paso 5 actual del
   bootstrap ("Lee BACKLOG_PATH y ordena tickets", l.44-45 verificado en vivo)
   pasa a ser CONDICIONAL. NO se suma como paso aparte (si se sumara, el propio
   paso 5 reordenaria y pisaria la salida del triage).
NO se construye en este ticket el script de reconciliacion determinista
(scripts/backlog_reconcile.py, diferido a follow-up WOT-2026-021i): la Fase 0
del metodo se hace "a mano" (comandos git) hasta que exista ese recolector.

## Rutas exactas verificadas (evitar busqueda a ciegas)
- Molde de la skill: skills/audit-pipeline/SKILL.md (14 lineas de frontmatter:
  name/version/description/triggers/author/role/stage/writes_memory/quality_gate/
  tags/source_prompt/contract_id; secciones "Cuando usarla" / "No usar" /
  "Prompt canonico" / "Topologia obligatoria" / "Flujo" / "Herramientas por fase"
  / "Contrato de evidencia" / "Salidas" / "Restriccion dura"). VERIFICADO
  leyendo el archivo completo.
- Molde/hermano del prompt: prompts/audit_pipeline.md (cabecera con
  contract_id: cid-audit-pipeline-v1, Skill canonica: skills/audit-pipeline/SKILL.md,
  source_of_truth: este prompt; estructura de fases con encabezados "## Fase N").
  VERIFICADO existe y su cabecera literal.
- Punto de cableado: prompts/orchestrator_pipeline.md, seccion "0. Bootstrap
  del destino", paso 5 (l.44-45 en la version actual): "Lee BACKLOG_PATH y
  ordena tickets por dependencias, prioridad y orden de aparicion." VERIFICADO
  por lectura completa del archivo (1343 lineas); NO confundir con la seccion
  numerada "## 5. Manager: revisar implementacion" (l.652), que es un heading
  H2 distinto y NO se toca.
- Enum de stage: skills/validate_all.py::VALID_STAGES (l.37-47) incluye
  plan (junto a setup/implement/review/quality/close/memory/meta/support).
  VERIFICADO por lectura del archivo; plan YA lo usan
  skills/manager-create-work-plan/SKILL.md y skills/grill-work-plan/SKILL.md
  (2 skills). NO crear un stage planning nuevo.
- Descubrimiento de skills: scripts/discover_skills.py::_scan_skills_dir
  escanea CADA subdirectorio de skills/ buscando SKILL.md y parsea su
  frontmatter; NO requiere registro manual en agents.json ni en ningun otro
  archivo. Basta con crear skills/backlog-triage/SKILL.md con frontmatter
  valido para que aparezca en discover_skills()/--catalog. VERIFICADO
  leyendo discover_skills.py completo (no hay paso de registro adicional).
  Contrato bidireccional prompt-skill: como role: manager (heredado del
  molde) esta en CONTRACT_OPT_IN_ROLES, declarar source_prompt/contract_id
  activa la validacion estricta de --check-contract: el prompt debe contener
  literalmente "Skill canonica: skills/backlog-triage/SKILL.md" y
  "contract_id: cid-backlog-triage-v1" (mismo patron que audit_pipeline.md).
- Gate de formato del backlog: scripts/check_backlog_contract.py (CLI:
  --project-root PROJECT_ROOT, sin fallback a cwd; usa AGENT_PROJECT_ROOT
  si no se pasa el flag). VERIFICADO con --help.
- Topologia del backlog del motor: para tickets WOT, el backlog vive en
  orquestador_de_agentes_workspace/.agent/collaboration/backlog.md, NO en el
  checkout de codigo (_dev ni el principal). Se localiza via
  motor_destination_link.json (destination_root -> workspace). Esto es
  DISTINTO de la topologia de un repo_destino generico, donde el backlog vive
  en DESTINO_ROOT/.agent/collaboration/backlog.md (el propio destino).

## Files Likely Touched
- prompts/backlog_triage.md (nuevo)
- skills/backlog-triage/SKILL.md (nuevo)
- prompts/orchestrator_pipeline.md (modificar SOLO el paso 5 del bootstrap,
  l.44-45 en la version actual)

## Read/inspect only
- skills/audit-pipeline/SKILL.md (molde; NO se modifica)
- prompts/audit_pipeline.md (hermano/referencia; NO se modifica)
- prompts/audit_agent_output.md (contrato de evidencia heredado; NO se
  modifica)
- skills/validate_all.py (solo para confirmar el enum de stage; NO se
  modifica)
- scripts/check_backlog_contract.py (solo se invoca/referencia; NO se
  modifica)

## Forbidden Surfaces
- NO tocar prompts/audit_pipeline.md ni skills/audit-pipeline/SKILL.md:
  son espejos de referencia, no superficie de este ticket.
- NO tocar prompts/orchestrate_destination_batch.md, skills/orchestrate-pipeline/
  ni ningun otro prompt/skill de ejecucion del pipeline.
- NO crear scripts/backlog_reconcile.py (diferido a WOT-2026-021i).
- NO anadir un paso 5.bis aparte en prompts/orchestrator_pipeline.md: el
  cableado reemplaza el contenido del paso 5 existente, no se suma.
- NO crear un stage nuevo (planning u otro) en skills/validate_all.py.

## Non-goals
- NO construir el recolector determinista de senales de reconciliacion
  (scripts/backlog_reconcile.py): follow-up WOT-2026-021i explicito.
- NO incrustar el metodo del triage en orchestrator_pipeline.md: solo
  referencia al prompt mas consumo del JSON.
- NO que la skill redeclare reglas del metodo (puntero, no fuente).
- NO forzar el analisis multi-lente (fan-out de agentes) en cada ejecucion: es
  tecnica opt-in por tamano de backlog, declarada como tal en el prompt.
- NO tocar audit_pipeline.md ni orchestrate-pipeline (solo se referencian
  como espejos del ciclo de vida).

## Decision Arquitectonica

### 1. prompts/backlog_triage.md -- contenido canonico
Cabecera identica en forma a prompts/audit_pipeline.md (tres lineas):
contract_id: cid-backlog-triage-v1
Skill canonica: skills/backlog-triage/SKILL.md
source_of_truth: este prompt. La skill skills/backlog-triage/SKILL.md es
wrapper operativo; si divergen, prevalece este prompt.

Declarar el espejo de ciclo de vida explicitamente en la introduccion:
/backlog-triage (ANTES: que pipeline lanzar) / /orchestrate-pipeline
(DURANTE: ejecuta 1 pipeline) / /audit-pipeline (DESPUES: meta-auditoria del
backlog cerrado). Este parrafo satisface el criterio "coherencia del espejo"
del DoD (ya existe un ancla parcial en orchestrator_pipeline.md l.1128-1136,
seccion "11. Meta-auditoria final", que menciona /audit-pipeline; el prompt
nuevo debe citar el trio completo, no solo el hermano post-pipeline).

Nota de topologia (obligatoria, literal en el prompt): "Para tickets WOT del
motor, localiza el backlog via .agent/config/motor_destination_link.json del
workspace activo, resolviendo destination_root -> el backlog vive en
<destination_root>/.agent/collaboration/backlog.md (el workspace, NO el
checkout de codigo _dev ni el principal). Para un repo_destino generico, el
backlog vive en DESTINO_ROOT/.agent/collaboration/backlog.md (el propio
destino). No asumas la ubicacion sin resolver el link."

Fases (read-only sobre el backlog; NUNCA muta backlog, codigo ni estado):

- Fase 0.pre - Gate de formato: ejecutar
  python MOTOR_ROOT/scripts/check_backlog_contract.py --project-root <destino>
  y exigir exit 0 ANTES de analizar. Si el exit code no es 0, detener y
  reportar el backlog como no analizable (no es competidor del validador
  sintactico WOT-012b, es complementario: este triage es el planner semantico).
- Fase 0 - Reconciliacion (recolector mas juicio, explicitamente NO
  determinista): leer backlog.md completo; para cada ticket
  pending/deferred/completed-partial, RECOLECTAR senales de git
  (git log --grep ID, git ls-files archivos-del-scope, greps de
  terminos del DoD, last-run.json si existe) y JUZGAR con esas senales. El
  prompt declara explicitamente: "no existe un check determinista generico;
  cada DoD requiere una verificacion distinta". Emitir por ticket:
  LIKELY_DONE (con evidencia commit/archivo, etiqueta VERIFICADO) /
  LIKELY_PENDING / NEEDS_HUMAN_VERIFY. Los LIKELY_DONE se proponen para
  archivar y SALEN del analisis de pipelines (nunca entran en agrupacion).
- Fase 1 - Clasificacion de aptitud: por cada ticket PENDING (no
  LIKELY_DONE), clasificar APTO_AUTONOMO (DoD binario, deliverable code,
  mutation-verify, bajo riesgo, cero politica/HUMAN_GATE) /
  REQUIERE_HUMANO (politica/destructivo/infra-local/blocked-externo) /
  DISENO_PRIMERO (ficha grande con sub-decisiones pendientes). Cada
  clasificacion lleva etiqueta VERIFICADO/INFERIDO/REQUIERE_HUMANO
  (contrato de evidencia heredado de prompts/audit_agent_output.md, mismo
  que audit-pipeline).
- Fase 2 - Agrupacion en pipelines: agrupar los APTO_AUTONOMO por
  afinidad tecnica (mismo subsistema/gate -> una verificacion final comun) mas
  dependencias declaradas y ocultas mas blast radius. Cada pipeline: nombre,
  tickets en orden, rationale, gate de verificacion comun, tamano S/M/L.
- Fase 3 - Sintesis y recomendacion: ordenar pipelines por valor/riesgo
  (mas valor con menos riesgo primero; higiene de suite/codigo-muerto suele ir
  primero). Listar EXPLICITAMENTE los REQUIERE_HUMANO con motivo, separados
  de los pipelines autonomos. Senalar los tickets cuya premisa hay que
  reverificar (potencialmente ya-hechos, no capturados por la Fase 0 con
  certeza suficiente). Recomendar por cual pipeline empezar.
- Salida (obligatoria): informe Markdown mas backlog_triage_output.json
  bajo orchestrator_pipeline/reports/ del destino (mismo patron de rutas que
  audit-pipeline). Esquema del JSON: pipelines[] (nombre, tickets-en-orden,
  gate-comun, tamano), tickets[] (id, clasificacion APTO_AUTONOMO/
  REQUIERE_HUMANO/DISENO_PRIMERO, reconciliacion LIKELY_DONE/LIKELY_PENDING/
  NEEDS_HUMAN_VERIFY, etiqueta-evidencia, artefacto), recommended_start,
  requires_human[], premise_verify[]. El informe NO escribe backlog.md:
  propone; el humano/Manager decide archivar/lanzar.

Nota de escala (declarada como tecnica, no obligacion): el analisis
multi-lente (fan-out de agentes) es RECOMENDADO para backlogs grandes (mas de
6 tickets pending aproximadamente, o mezcla de scopes/autoridades), OPCIONAL
para pequenos.

Los 5 riesgos codificados EXPLICITAMENTE (con encabezado propio o bloque
identificable, no disueltos en prosa general):
1. No hinchar orchestrator_pipeline.md: el metodo vive aqui, el cableado es
   solo referencia mas consumo de JSON.
2. El triage puede fabricar certezas: toda clasificacion lleva etiqueta de
   evidencia (VERIFICADO/INFERIDO/REQUIERE_HUMANO), heredada de
   prompts/audit_agent_output.md.
3. Backlog stale: la Fase 0 (reconciliacion) es SIEMPRE el primer paso, antes
   de cualquier planificacion; un ticket LIKELY_DONE nunca entra en
   pipeline.
4. Autonomia falsa: Fase 1 separa APTO_AUTONOMO de REQUIERE_HUMANO de
   DISENO_PRIMERO; destructivo/politica/HUMAN_GATE/infra-fuera-de-git NUNCA
   van en pipeline autonomo.
5. Skill es puntero, no fuente: skills/backlog-triage/SKILL.md no redeclara
   el metodo; remite con la clausula "prevalece el prompt".

### 2. skills/backlog-triage/SKILL.md -- molde exacto
Copiar la ESTRUCTURA de skills/audit-pipeline/SKILL.md seccion por seccion
(Cuando usarla / No usar / Prompt canonico / Topologia obligatoria / Flujo /
Herramientas por fase / Contrato de evidencia / Salidas / Restriccion dura),
adaptando el CONTENIDO al triage (read-only sobre backlog, no sobre pipeline
cerrado) SIN copiar el metodo del prompt: cada seccion remite o resume en 1-2
lineas, nunca reproduce las 4 fases completas.

Frontmatter exacto (12 campos):
name: backlog-triage
version: 1.0.0
description: Analisis pre-pipeline del backlog: reconciliacion contra git,
  clasificacion de aptitud y agrupacion en pipelines ordenados por valor/riesgo
triggers: [/backlog-triage, backlog-triage]
author: agent
role: manager
stage: plan
writes_memory: false
quality_gate: false
tags: [core, system, backlog]
source_prompt: prompts/backlog_triage.md
contract_id: cid-backlog-triage-v1

role: manager (no auditor): el triage es meta-planificacion (decide que
pipeline lanzar), analogo a manager-create-work-plan, no una auditoria
retrospectiva. stage: plan segun el DoD del contrato (ya en el enum,
semanticamente correcto para "antes del pipeline"). La clausula "el prompt es
la fuente de verdad; si algo diverge, prevalece el prompt" debe aparecer
literal (mismo texto que skills/audit-pipeline/SKILL.md l.51-53, adaptado al
nombre del prompt nuevo).

### 3. Cableado en prompts/orchestrator_pipeline.md
Reemplazar el paso 5 actual del bootstrap (l.44-45: "Lee BACKLOG_PATH y
ordena tickets por dependencias, prioridad y orden de aparicion.") por un
paso 5 CONDICIONAL que preserva el fallback exacto cuando no aplica:

"5. Si /backlog-triage ya se ejecuto (existe
orchestrator_pipeline/reports/backlog_triage_output.json reciente en
PIPELINE_REPORTS_DIR) O el backlog en BACKLOG_PATH tiene mas de N tickets
pending o mezcla scopes/autoridades distintas, ejecuta /backlog-triage
(MOTOR_ROOT/prompts/backlog_triage.md) si aun no corrio, y usa SU SALIDA
(backlog_triage_output.json) como orden de la cola: los tickets LIKELY_DONE
NO entran, los REQUIERE_HUMANO no entran en pipeline autonomo. Si no aplica
ninguna condicion (backlog pequeno/homogeneo y sin salida de triage previa),
lee BACKLOG_PATH y ordena tickets por dependencias, prioridad y orden de
aparicion, como hasta ahora." El umbral N sugerido es 6 (no critico, el
Builder documenta su eleccion en el diff/commit si difiere).

Es un condicional DENTRO del paso 5 existente (mismo numero, mismo lugar), NO
un paso 5.bis nuevo que se sume: si se sumara, la version vieja del paso 5
seguiria corriendo siempre y pisaria el orden que produjo el triage.
orchestrator_pipeline.md NO incrusta el metodo del triage: solo la
referencia al prompt y el consumo del JSON descrito arriba.

## Barrera / verificacion (deliverable mixed, docs-heavy, no bugfix)
Este ticket es prompt/skill/cableado (documentation-heavy), no un bugfix de
codigo: no aplica mutation-verify de codigo. La barrera proporcional, criterio
BINARIO declarado explicitamente en AUDIT_WOT-2026-021h.md:
- Barrera anti-riesgo-5 (skill es puntero, no fuente): grep -c de los
  terminos clave del metodo ("LIKELY_DONE", "APTO_AUTONOMO",
  "REQUIERE_HUMANO", "DISENO_PRIMERO", "Fase 0.pre", "Fase 3") sobre
  skills/backlog-triage/SKILL.md debe dar 0 apariciones DE LA REGLA
  (definicion/criterio), salvo menciones puramente referenciales de una linea
  (p.ej. "Fase 0 - Reconciliacion" como nombre de fase en la tabla de
  herramientas, sin redefinir su contenido). Las reglas completas (que es
  LIKELY_DONE, como se calcula, que hace que un ticket sea APTO_AUTONOMO)
  deben existir SOLO en prompts/backlog_triage.md.
- Barrera anti-riesgo-1 (orchestrator_pipeline.md no absorbe el metodo):
  git diff prompts/orchestrator_pipeline.md debe mostrar cambios SOLO dentro
  del paso 5 del bootstrap (rango de lineas acotado, no un bloque nuevo de
  varias fases); el diff no debe contener las palabras "Fase 0.pre", "Fase 1 -
  Clasificacion", "Fase 2 - Agrupacion" ni "Fase 3 - Sintesis" (esas son
  fases del METODO, exclusivas del prompt nuevo).

## Plan de Implementacion

### Fase 1: Crear prompts/backlog_triage.md
- **Tipo:** TAREA AGENTE (Builder)
- **Archivo:** prompts/backlog_triage.md
- **Accion:** Crear
- **Descripcion:** Redactar el prompt completo segun la Decision Arquitectonica
  seccion 1: cabecera con contract_id: cid-backlog-triage-v1,
  Skill canonica: skills/backlog-triage/SKILL.md, source_of_truth; parrafo
  del trio de ciclo de vida; nota de topologia obligatoria (motor -> workspace
  via motor_destination_link.json, destino generico -> su propio
  .agent/collaboration/backlog.md); las 5 fases (0.pre, 0, 1, 2, 3) con el
  contenido exacto descrito arriba; los 5 riesgos codificados en un bloque
  identificable; el esquema del JSON de salida
  (backlog_triage_output.json) con los campos declarados
  (pipelines[]/tickets[]/recommended_start/requires_human[]/
  premise_verify[]); la nota de escala del analisis multi-lente
  como tecnica opt-in.
- **Riesgo:** Medio (documento nuevo, pero fija un contrato que consumira el
  cableado de Fase 3 y sera puntero-fuente de la skill de Fase 2; un error de
  alcance aqui se propaga a las otras 2 fases).
- **Criterio de Aceptacion:**
  - El archivo existe y contiene, en encabezados identificables, las 4 fases
    (0/1/2/3, mas la 0.pre) en ese orden.
  - Contiene los 5 riesgos codificados como bloque explicito (verificable por
    grep de las 5 frases clave: "no hinchar", "fabricar certezas",
    "backlog stale" o "reconciliacion", "autonomia falsa", "puntero").
  - Contiene la nota de topologia con la frase literal sobre
    motor_destination_link.json.
  - Contiene el esquema JSON con los 5 campos obligatorios nombrados
    (pipelines, tickets, recommended_start, requires_human,
    premise_verify).
  - Cabecera contiene literal "contract_id: cid-backlog-triage-v1" y
    "Skill canonica: skills/backlog-triage/SKILL.md" (verificable por grep;
    necesario para que discover_skills.py --check-contract pase en Fase 5).
- **Si falla:** Revisar contra el contrato fuente
  (CONTRATO_WOT-2026-021h_backlog_triage.md en el workspace) y corregir la
  fase o riesgo faltante antes de continuar a Fase 2.

### Fase 2: Crear skills/backlog-triage/SKILL.md
- **Tipo:** TAREA AGENTE (Builder)
- **Archivo:** skills/backlog-triage/SKILL.md
- **Accion:** Crear
- **Descripcion:** Copiar la ESTRUCTURA de secciones de
  skills/audit-pipeline/SKILL.md (Cuando usarla / No usar / Prompt canonico
  / Topologia obligatoria / Flujo / Herramientas por fase / Contrato de
  evidencia / Salidas / Restriccion dura), con el frontmatter exacto de la
  Decision Arquitectonica seccion 2 (name, version, description,
  triggers: [/backlog-triage, backlog-triage], author: agent,
  role: manager, stage: plan, writes_memory: false,
  quality_gate: false, tags, source_prompt: prompts/backlog_triage.md,
  contract_id: cid-backlog-triage-v1). Cada seccion resume o remite al
  prompt en 1-2 lineas; el "Flujo" lista los NOMBRES de las 5 fases (0.pre, 0,
  1, 2, 3) sin reproducir sus reglas internas. Incluir la clausula literal "el
  prompt es la fuente de verdad; si algo diverge, prevalece
  prompts/backlog_triage.md" (mismo patron de
  skills/audit-pipeline/SKILL.md l.51-53).
- **Riesgo:** Bajo (archivo nuevo, molde ya verificado y estable).
- **Criterio de Aceptacion:**
  - El archivo existe con las 9 secciones del molde (mismos titulos de
    seccion que audit-pipeline/SKILL.md, adaptados al triage).
  - Frontmatter completo con los 12 campos exactos de la Decision
    Arquitectonica seccion 2, incluido stage: plan (no planning).
  - Contiene la clausula "el prompt es la fuente de verdad".
  - Barrera anti-riesgo-5 (ver seccion "Barrera / verificacion" de este plan):
    0 redeclaraciones del metodo, verificado por el Builder antes de marcar
    la fase completa.
- **Si falla:** Si el grep de la barrera anti-riesgo-5 encuentra
  redeclaraciones, recortar la seccion a una referencia y repetir el grep
  antes de continuar.

### Fase 3: Cablear paso 5 condicional en prompts/orchestrator_pipeline.md
- **Tipo:** TAREA AGENTE (Builder)
- **Archivo:** prompts/orchestrator_pipeline.md
- **Accion:** Modificar
- **Descripcion:** Localizar el paso 5 actual dentro de la seccion "0.
  Bootstrap del destino" (verificado en l.44-45 de la version leida por el
  Manager: "5. Lee BACKLOG_PATH y ordena tickets por dependencias,
  prioridad y orden de aparicion."). Reemplazar SOLO ese punto por el texto
  condicional completo de la Decision Arquitectonica seccion 3 (misma
  numeracion "5.", mismo lugar en la lista). No anadir un punto "5.bis" ni
  mover el resto de la numeracion del bootstrap. Si el numero de linea real
  difiere de l.44-45 en el momento de editar (el archivo pudo cambiar entre
  la Fase 0 del Manager y la implementacion), el Builder localiza el paso 5
  por su TEXTO literal actual ("Lee BACKLOG_PATH y ordena tickets"), no por
  el numero de linea.
- **Riesgo:** Medio (el archivo es el prompt canonico del pipeline completo,
  1343 lineas; un error de alcance aqui puede desalinear la numeracion o
  incrustar el metodo por accidente).
- **Criterio de Aceptacion:**
  - git diff prompts/orchestrator_pipeline.md muestra cambios
    EXCLUSIVAMENTE dentro del punto 5 de la seccion "0. Bootstrap del
    destino" (no en ninguna otra seccion del archivo, incluida la "## 5.
    Manager: revisar implementacion" mas abajo, que NO se toca).
  - El diff no contiene ninguna de las frases "Fase 0.pre", "Fase 1 -
    Clasificacion", "Fase 2 - Agrupacion", "Fase 3 - Sintesis" (barrera
    anti-riesgo-1, ver seccion "Barrera / verificacion").
  - El texto nuevo referencia MOTOR_ROOT/prompts/backlog_triage.md y
    backlog_triage_output.json, y preserva literalmente el fallback "ordena
    tickets por dependencias, prioridad y orden de aparicion" para el caso
    sin-triage.
- **Si falla:** Revertir el cambio de prosa (git diff muestra un bloque
  contenido y reversible) y corregir el alcance antes de reintentar.

### Fase 4: Coherencia de espejo (trio antes/durante/despues)
- **Tipo:** TAREA AGENTE (Builder)
- **Archivo:** prompts/backlog_triage.md (ya cubierto en Fase 1) y
  verificacion cruzada sobre prompts/orchestrator_pipeline.md
- **Accion:** Verificar (no crea archivo nuevo; confirma que el requisito ya
  quedo satisfecho por las Fases 1 y 3)
- **Descripcion:** Confirmar que al menos uno de los prompts documenta
  explicitamente el trio /backlog-triage (antes) / /orchestrate-pipeline
  (durante) / /audit-pipeline (despues) con referencia cruzada. El parrafo
  de introduccion de prompts/backlog_triage.md (Fase 1) ya lo cubre; esta
  fase es la verificacion explicita de que quedo, no una redaccion nueva.
- **Riesgo:** Bajo (verificacion, no escritura).
- **Criterio de Aceptacion:** grep de las 3 cadenas "/backlog-triage",
  "orchestrate-pipeline", "/audit-pipeline" en el mismo archivo
  (prompts/backlog_triage.md) da las 3 presentes.
- **Si falla:** Completar el parrafo faltante en prompts/backlog_triage.md
  antes de continuar a Fase 5.

### Fase 5: Calidad, encoding y descubrimiento
- **Tipo:** TAREA AGENTE (Builder)
- **Archivo:** todos los tocados/creados; suite de discovery/validate
- **Accion:** Verificar
- **Descripcion:** Ejecutar, en este orden, y registrar comando mas salida
  literal en execution_log.md:
  1. Encoding guard sobre los 2 archivos nuevos y el prompt editado:
     python scripts/check_encoding_guard.py prompts/backlog_triage.md skills/backlog-triage/SKILL.md prompts/orchestrator_pipeline.md
     (o el comando equivalente documentado en
     prompts/orchestrator_launch_builder.md, seccion "Check de encoding").
     Exit 0, sin mojibake ni em-dash/comillas curvas (usar guion/comillas
     ASCII) en los 2 archivos NUEVOS. El prompt editado puede conservar
     em-dash preexistentes fuera del rango tocado (no se re-redacta contenido
     ajeno al diff), pero el TEXTO NUEVO anadido por Fase 3 debe ser ASCII
     limpio.
  2. Descubrimiento de la skill:
     python scripts/discover_skills.py --json y confirmar que
     backlog-triage aparece en skills[] con triggers incluyendo
     /backlog-triage.
  3. Contrato bidireccional prompt-skill:
     python scripts/discover_skills.py --check-contract con exit 0 (valida
     que source_prompt/contract_id de la skill nueva resuelven
     correctamente contra prompts/backlog_triage.md, dado que
     role: manager esta en CONTRACT_OPT_IN_ROLES).
  4. Naming convention:
     python scripts/discover_skills.py --check-naming con exit 0
     (backlog_triage es snake_case valido para el prompt,
     backlog-triage es kebab-case valido para la skill; ninguno combina
     actor y accion en orden invertido, no aplica la regla actor-first).
  5. python .agent/agent_controller.py --validate --json --force con 0
     errores (los warnings de bus/code-only-mode esperados no bloquean).
- **Riesgo:** Bajo (solo verificacion; ningun comando muta produccion).
- **Criterio de Aceptacion:** los 5 comandos anteriores terminan con el
  resultado indicado; las 2 barreras binarias de la seccion "Barrera /
  verificacion" (anti-riesgo-5 grep sobre la skill, anti-riesgo-1 grep sobre
  el diff del prompt) quedan registradas en execution_log.md con el
  resultado exacto del grep (0 matches de regla completa en cada caso).
- **Si falla:** Si --check-contract o --check-naming fallan, corregir el
  frontmatter o el nombre de archivo (nunca renombrar backlog-triage a otra
  forma sin volver a Fase 1/2) y repetir el comando que fallo.


## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| 3 piezas (prompt + skill puntero + cableado condicional minimo) | Separa metodo de mecanica; reusa el molde ya probado de audit-pipeline; blast radius acotado en orchestrator_pipeline.md | Mas archivos que una unica pieza monolitica | Elegida (decision del usuario, vinculante) |
| Incrustar el metodo directamente en orchestrator_pipeline.md | Un solo archivo, sin indireccion | Hincha el prompt del pipeline, mezcla decidir-que-lanzar con ejecutar; contradice el DoD explicito | Descartada |
| Construir tambien scripts/backlog_reconcile.py en este ticket | Cierra la Fase 0 con recolector automatico ya | Amplia el alcance del ticket mas alla del metodo; el usuario fijo metodo-primero-automatizacion-despues | Descartada, diferida a WOT-2026-021i |
| stage nuevo planning para la skill | Nombre mas especifico | plan ya existe en el enum y es semanticamente correcto; crear uno nuevo rompe la convencion sin necesidad | Descartada |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|---------------------|
| Bajo | Rutinaria (archivos nuevos siguiendo un molde verificado, verificaciones) | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion (contenido normativo nuevo, edicion acotada de un prompt de 1343 lineas) | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Calidad
- Encoding guard sobre prompts/backlog_triage.md, skills/backlog-triage/SKILL.md,
  prompts/orchestrator_pipeline.md (Fase 5.1): exit 0, ASCII limpio en el
  contenido nuevo.
- python scripts/discover_skills.py --json confirma backlog-triage
  descubierta con trigger /backlog-triage (Fase 5.2).
- python scripts/discover_skills.py --check-contract exit 0 (Fase 5.3).
- python scripts/discover_skills.py --check-naming exit 0 (Fase 5.4).
- python .agent/agent_controller.py --validate --json --force con 0
  errores (Fase 5.5).
- Barrera anti-riesgo-5 (grep sobre la skill, 0 redeclaraciones de regla) y
  anti-riesgo-1 (grep sobre el diff del prompt, 0 fases del metodo
  incrustadas) registradas en execution_log.md (Fase 2 y Fase 3).
- No aplica ruff/pytest (no hay codigo Python nuevo en este ticket).

## Criterios de Aceptacion Global
- [x] prompts/backlog_triage.md existe con las 4 fases (reconciliacion ->
      clasificacion -> agrupacion -> sintesis) mas la 0.pre, y los 5 riesgos
      codificados explicitamente.
- [x] skills/backlog-triage/SKILL.md existe, frontmatter completo
      (source_prompt: prompts/backlog_triage.md,
      contract_id: cid-backlog-triage-v1,
      triggers: [/backlog-triage, backlog-triage], stage: plan,
      writes_memory: false), clausula "el prompt es la fuente de verdad".
      Verificado por grep que NO redeclara el metodo.
- [x] El prompt incluye la Fase 0.pre (check_backlog_contract.py exit 0
      antes de analizar) y la nota de topologia (backlog del motor vive en el
      workspace via motor_destination_link.json).
- [x] El prompt produce el JSON portable backlog_triage_output.json con el
      esquema declarado (pipelines/tickets/recommended_start/
      requires_human/premise_verify).
- [x] prompts/orchestrator_pipeline.md paso 5 del bootstrap es CONDICIONAL
      (usa salida de triage si existe, si no ordena como antes) sin incrustar
      el metodo; git diff muestra solo esa modificacion, no un paso nuevo
      aparte.
- [x] /backlog-triage descubierta por discover_skills.py
      (--json/--catalog); --check-contract y --check-naming en exit 0.
- [x] Encoding guard limpio (ASCII, sin em-dash/comillas curvas) sobre los 2
      archivos nuevos y el contenido nuevo del prompt editado.
- [x] --validate --json --force 0 errores.
- [x] Coherencia de espejo: el trio /backlog-triage / /orchestrate-pipeline /
      /audit-pipeline documentado en prompts/backlog_triage.md.
- [x] Barreras anti-riesgo-5 y anti-riesgo-1 (grep) registradas con resultado
      exacto en execution_log.md.

## Handoff: Manager -> Builder
**Plan:** WOT-2026-021h
**Accion requerida:** Implementar segun work_plan.md
**Estado:** PENDING
