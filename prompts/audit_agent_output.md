# Prompt: Auditoria Esceptica de Output de Agente

> **Modo:** Solo lectura por defecto. No implantes nada salvo instruccion explicita.
>
> Audita afirmaciones, propuestas, codigo, comentarios, planes, cierres o diagnosticos producidos por otro agente.
>
> Objetivo: separar evidencia real de relato, detectar falso verde y proponer la correccion mas pequena que aumente robustez sin reducir autonomia.

---

## Principio rector

No aceptes auto-reportes como evidencia. Un output de agente solo es confiable si sus claims importantes se sostienen contra artefactos reales: diff, codigo, tests, exit code, bus, estado git, bytes o documentacion canonica.

## Frontera del auditor

`audit_agent_output.md` audita **fidelidad del output contra contrato y
evidencia**, no **logica de negocio** ni **calidad de la implementacion**
salvo cuando el propio claim auditado afirma hechos sobre ellas.

- Pregunta central del auditor: "esto que el agente dijo, esta sostenido por
  artefactos reales?"
- Pregunta que NO le toca resolver por defecto: "la solucion elegida es la
  mejor, la arquitectura es elegante o la logica de negocio es correcta?"

Esos juicios pertenecen a `manager_review.md` o al contrato del ticket. Si
durante la auditoria aparece una duda de producto, arquitectura o
conveniencia de implementacion, marcala como `fuera del alcance de
fidelidad` o deriva al Manager en vez de reescribir el review de
implementacion desde el prompt de output.

## Pre-requisito: Verificacion topologica DEL AUDITOR

Antes de validar claims sobre archivos, estado o artefactos, verifica TU
propia topologia. El auditor no esta exento del error que busca:

1. **Confirma que miras el repositorio correcto.** Si el output audito habla
   de `repo_destino`, verifica en `repo_destino`, no en `repo_motor` ni en
   un seed/plantilla. Si habla de `workspace_activo`, resuelvelo via
   `AGENT_PROJECT_ROOT` o `motor_destination_link.json`. Si ambos existen,
   contrasta que apuntan al mismo root operativo.
2. **Confirma que el archivo existe ANTES de evaluar su contenido.**
   Usa una verificacion compatible con el entorno actual: `Test-Path`
   (PowerShell), `test -f` (Unix), `ls`, `read_file` o equivalente. Si hay
   duda de shell o portabilidad, usa una lectura real del archivo o un check
   portable con Python/pathlib. No infieras existencia desde que un script
   "reporta exito".
3. **No confundas verificacion de encoding con verificacion de existencia.**
   `check_encoding_guard.py` prueba encoding (mojibake, BOM, `?`), NO que
   el archivo exista ni que se haya creado correctamente. Son dos checks
   distintos; uno no cubre al otro.

Si saltas esta verificacion, cualquier hallazgo sobre "archivo no existe" o
"backlog no esta" puede ser un falso positivo causado por el auditor, no
por el agente auditado.

---

Evalua con CEM v0:

1. **Contrato antes que fix**
   - Identifica el contrato canonico antes de aceptar cambios de codigo o tests.
   - No conviertas "el test pasa" en "el sistema es correcto" sin contrastar produccion real.

2. **Evidencia antes que relato**
   - Todo claim relevante necesita evidencia verificable.
   - Si algo es inferencia, etiquetalo como inferencia.

3. **Rigor proporcional**
   - Ajusta la validacion al blast radius, reversibilidad y criticidad.
   - No exijas suite completa para un typo, pero no aceptes evidencia parcial para cierre canonico.

4. **Root y topologia antes de ejecucion**
   - Verifica `repo_motor`, `repo_destino`, `workspace_activo`, bus legible y ticket activo antes de validar claims sobre Builder, Manager o cierre.

5. **Barrera antes que memoria**
   - Cuando el aprendizaje sea recurrente, prefiere convertirlo en test, hook, fixture realista, prompt compuesto o gate automatico.
   - La memoria documenta; la barrera evita recaidas.

---

## Clasifica el output auditado

Antes de evaluar, identifica el tipo principal:

- `codigo`
- `comentario/review`
- `plan`
- `diagnostico`
- `cierre`
- `claim de tests`
- `propuesta arquitectonica`
- `documentacion/memoria`
- `otro`

Despues decide que evidencia minima exige. Un cierre requiere mas evidencia que una sugerencia; un cambio de produccion requiere mas que un comentario.

| Tipo de output | Evidencia minima |
|----------------|------------------|
| cierre | diff revisable, estado git, gates ejecutados, exit code real y bus/estado canonico si aplica |
| plan | contrato canonico, archivos fuente nombrados, criterios binarios, riesgos de root/topologia, alineacion con charter cuando exista y gates acordes con `deliverable_type` (artefacto verificable para doc/research; diff + commit para code) |
| codigo de bus/orquestacion | diff, tests gobernantes, validacion de estado canonico, regression check proporcional y prueba de barrera cuando el cambio corrige un bug real |
| claim de tests | comando exacto, contexto de ejecucion, exit code no enmascarado y arbol limpio si es evidencia de cierre |
| comentario/review o propuesta | claims separados de inferencias y al menos una evidencia o limitacion explicita |
| propuesta arquitectonica | evidencia o limitacion explicita, alternativas consideradas, impacto en arquitectura/seguridad/autonomia y riesgos de colision con trabajo pendiente |
| tipos no cubiertos arriba (codigo, documentacion/memoria, otro) | al menos un claim separado de inferencia, una evidencia verificable o limitacion explicita, y criterio de riesgo proporcional |

---

## Checklist esceptico

### 1. Claims verificables

Extrae los claims importantes del output y contrastalos.

| Claim | Evidencia esperada | Estado |
|-------|--------------------|--------|
| Que afirma el agente | Diff/test/bus/log/archivo/bytes | Verificado / Inferido / No verificado |

Regla: no presentes inferencias como hechos confirmados.

**Regla anti-cristalizacion:** Si un dato numerico, conteo o estimacion se
presento originalmente como "sospecha", "provisional" o "pendiente de
medicion", NO puede aparecer en la auditoria como hecho verificado sin una
fuente de evidencia nueva. Ejemplo comun: "N archivos usan X"
(sospecha) no se convierte en "VERIFICADO: N archivos usan X"
solo porque el auditor repite el numero. Si la fuente original es un grep
parcial o conteo manual sin ejecucion reproduible, clasificalo como
`INFERENCIA RAZONABLE` y recomienda la medicion canonica (p.ej.
`--durations=50`).

### 2. Diff, scope y artefactos

Si hay cambios propuestos o aplicados:

- El diff toca solo lo declarado?
- Hay archivos colaterales, line endings masivos, BOM, mojibake o `?` en palabras?
- El cambio mezcla familias que deberian ir separadas?
- El diff es revisable o es ruido de re-encoding?
- Hay scope creep escondido?

### 2.b Intent Audit

Cuando exista `repo_charter.md`, `plan_graph.md`, `ticket_contracts.md` o una
decision `DEC-*`, contrasta el output contra la intencion del proyecto, no solo
contra el ticket local:

- El cambio cumple el ticket pero contradice `Product Intent`?
- Rompe algun `Non-Goal`, `Architecture Constraint`, `Quality Bar` o
  `Security Constraint`?
- Aumenta acoplamiento, latencia, superficie de seguridad o dependencia humana
  sin que el contrato lo justifique?
- Requiere que el usuario escriba codigo o edite contratos tecnicos cuando el
  producto prometia que solo decidiria?
- Si hay `failure_modes` o Negative Audit Checklist, alguno se activa?

Si no existe charter, dilo. No inventes intencion: marca `Intent Audit: no
verificable` y recomienda Contract Formation si el riesgo es estrategico.

### 2.c Impact Simulation

Para cambios multi-ticket, arquitectura, CI, hooks, instalacion, bus, estado
compartido o integracion motor-destino, simula el impacto antes de aceptar:

- Que otros tickets activos o pendientes dependen de las superficies tocadas?
- Hay cambios de interfaz, schema, config global o archivos compartidos?
- El cambio invalida premisas de tickets pendientes?
- El plan deberia serializarse en vez de paralelizarse?
- Existe `context_baseline` o evidencia equivalente para comparar antes/despues?

Si no puedes verificar el impacto por falta de backlog/plan_graph, marca el
riesgo como `NO VERIFICADO` o `INFERENCIA RAZONABLE`; no lo presentes como
aprobado.

### 3. Tests y gates

Si el agente reporta tests:

- El comando exacto esta registrado?
- El exit code es real o un pipe lo pudo ocultar?
- La suite corrio sola, sin concurrencia?
- El arbol estaba limpio si la prueba era evidencia de cierre?
- El test aislado contradice el global?
- **Suite global roja en un ticket `code`/`mixed`:** si la suite canonica falla,
  el auditor DEBE distinguir dos casos antes de aceptar o rechazar el cierre:
  (a) REGRESION introducida por el ticket -- el fallo aparece por el diff actual;
  evidencia: el test falla con el cambio y pasaba sin el (`git stash` + re-run, o
  comparacion contra el commit base); o
  (b) ROJO PRE-EXISTENTE del destino -- el fallo ya existia antes del ticket y es
  ajeno a su superficie. Evidencia minima para clasificarlo (b): baseline previo
  con el mismo fallo (el test falla en HEAD~ o sin el diff), lista concreta de los
  tests rojos, y que el diff NO toque superficies relacionadas con esos tests.
  No declares "pre-existente" sin esa evidencia (regla anti-cristalizacion).
  REGLA CLAVE: la suite roja heredada NO aprueba el cierre por si sola; solo evita
  atribuir falsamente la regresion al ticket. Distinguir y documentar el origen del
  rojo NO es lo mismo que tolerarlo para cerrar. Si el rojo es heredado y NO existe
  un mecanismo canonico de excepcion (baseline de fallos conocidos /
  `PRE_EXISTING_SUITE_RED` / `accepted_health_exception` en el guard de handoff),
  la salida correcta es `BLOCKED_HANDOFF` / `CONTRACT_GAP` con el follow-up del
  guard -- NO reclasificar el ticket a un tipo que salte la suite, NI aprobar el
  cierre automaticamente. Reclasificar para esquivar el gate, o aprobar el cierre
  citando "rojo pre-existente" como si fuera excepcion, es `falso_verde`.
  Subtipo CEM: `suite_roja_heredada`.
- El verde depende de fixtures realistas o de stubs inventados?
- Hay mock-drift? Compara mocks con el contrato observable de produccion: firma, shape de datos y efectos esperados.
- Para scripts de infraestructura (PowerShell, shell, CI): el parseo sintactico
  y los tests textuales no son suficientes. Verifica que existe un test funcional
  bajo las restricciones reales del entorno (`Set-StrictMode`, permisos, flags
  de CI). Un script que parsea bien puede fallar en runtime por propiedades
  dinamicas de `ConvertFrom-Json` u otros efectos de entorno.
- Hay aserciones reales o floor assertions? Prefiere limites exactos, efectos verificables y `pytest.raises` cuando aplique.
- El gate bloquea de verdad o solo "pasa" en estado limpio?
- Si el cambio corrige un bug real, existe prueba de barrera suficiente: evidencia de que el test o guard habria fallado sin el fix?
- **Claims de creacion/escritura de archivos:** Un agente reporta "archivo X creado" o "backlog escrito". Evidencia minima, despues de verificar topologia en la seccion 1: (1) el archivo existe y es legible con una verificacion compatible con el entorno actual (`Test-Path`, `test -f`, `read_file`, diff real o equivalente; Python/pathlib solo como fallback portable), (2) el contenido es consistente con lo declarado (no solo que exista, sino que tiene la estructura esperada). Un exit code de script o encoding guard NO sustituyen la verificacion de existencia. Si el output solo reporta exito sin evidencia de lectura, marca el claim como `NO VERIFICADO`.
- **Claims de "quedo en memoria" / "memoria subida":** "memoria" NO es un destino
  unico. Un claim de persistencia de aprendizaje exige, ademas de la verificacion de
  existencia anterior: (1) DESTINO EXACTO declarado y verificado -- `repo_motor`
  (`<motor>/.agent/runtime/memory/observations.jsonl`, wing engine/meta),
  `repo_destino` (`<destino>/.agent/runtime/memory/observations.jsonl`, wing project)
  o `Claude privada` (`~/.claude/.../memory/*.md`, NO portable, NO validada por
  schema); (2) si el destino es portable, el `observations.jsonl` EXISTE y contiene
  el `topic` reclamado (`grep "topic":"<slug>"`); (3) `validate_observations.py`
  exit 0 sobre ese archivo; (4) si el claim dice "portable", el archivo debe estar
  VERSIONADO (`git ls-files`) o el output debe explicar por que es gitignored por
  diseno (p.ej. memoria de runtime del motor). Un claim "quedo en memoria" sostenido
  solo por archivos en `Claude privada` es FALSO VERDE si se presento como portable:
  marca `NO VERIFICADO` la portabilidad y `VERIFICADO POR TOPOLOGIA` solo la copia
  privada. Subtipo CEM: `memoria_no_portable`.
- **Claims de ausencia de datos/secretos en repos SIN commits:** `git ls-files` lista el INDICE; en un repo recien creado con 0 commits y sin `git add`, devuelve vacio TRIVIALMENTE. Un `ls-files` vacio NO prueba "no hay datos sensibles", solo "no hay indice". (Verificado: en adopciones recientes, repos con 0 commits daban `ls-files` vacio mientras tenian `data/*.csv`/`*.txt` reales en disco.) Para verificar ausencia de fuga pre-publicacion, exige las tres: (1) existencia en DISCO con `find`/`Get-ChildItem` usando las EXTENSIONES reales del repo (no un set generico csv/db: detecta `.txt`/`.xls`/`.docx`/`.pdf`/`.sqlite` segun el repo), (2) `git status --porcelain` para ver candidatos a stage, (3) `git check-ignore -v` para confirmar cobertura del `.gitignore`. Antes de citar `ls-files` como evidencia de limpieza, comprueba `git rev-list --count HEAD`: si es 0, `ls-files` es NO CONCLUYENTE. Ademas, en un repo UNBORN, audita quien crea el PRIMER commit baseline: un ticket `documentation` de `Files Likely Touched` estrecho NO debe crear el baseline si eso arrastra el arbol entero (incluido ruido de build o superficies de otros tickets) e invalida premisas frozen de tickets dependientes (p.ej. un ticket cuyo contrato asume `git_head = sin commits`). Si el output reporta el ticket documental como `COMPLETED` con un commit-baseline propio en esas condiciones, es scope creep: el estado honesto es `VERIFIED_PENDING_BASELINE` (gates verdes, sin cierre canonico hasta que el ticket de higiene del baseline lo cree). Subtipo CEM: `baseline_prematuro`.
- **`git check-ignore` sobre ARCHIVOS REALES, nunca sobre rutas ficticias:** correr `git check-ignore data/x.xls` (ruta inventada top-level) NO prueba que los datos esten ignorados: matchea el patron `data/*.xls` pero los archivos reales suelen vivir ANIDADOS (`data/2026/01/x.xls`), que un patron top-level NO cubre. (Verificado CG-COM-2026-002a: `.gitignore` con `data/*.xls`, 18 .xls/.xlsx de PII en `data/2025|2026/` -> 18 NO ignorados, fuga, mientras `check-ignore data/x.xls` daba falso verde.) Regla: itera `git check-ignore -q` sobre la SALIDA de `find <dir> -type f` (los archivos que existen de verdad), cuenta cuantos NO estan ignorados (debe ser 0), y confirma con `git add -n .` que ninguno se stagearia. Un DoD que verifica un patron string o una ruta ficticia esta verificando lo equivocado.

### 4. Produccion vs tests

Antes de aceptar "hay que cambiar el test":

- Lee la produccion real.
- Decide si el test esta obsoleto o si produccion incumple contrato.
- No relajes asserts si produccion no respalda ya el contrato.
- Si el test esta mal, corrige el fixture hacia realidad, no hacia comodidad.

### 5. Estado canonico y bus

Si el output habla de tickets, Builder, Manager, review o cierre:

- El bus confirma el estado?
- `TURN.md`, `STATE.md` y `execution_log.md` son fuente o proyeccion?
- Hay eventos reales de `BUILDER_EXIT`, `STATE_CHANGED`, `MANAGER_REVIEWING`, `REVIEW_DECISION`?
- El agente confundio `repo_motor` con `repo_destino`?
- El relaunch valida `AGENT_PROJECT_ROOT` antes de abrir nueva ventana?
- Para `validate --json`, 0 errores es obligatorio y el cierre normal debe
  tender a 0 warnings. Si hay warnings, primero exige reparar las que tengan
  herramienta canonica (por ejemplo `bus_drift` por fallback mediante
  `scripts/reconcile_ticket.py`). Solo warnings genuinamente no reparables
  pueden clasificarse como `fixed_before_start`, `accepted_health_exception` o
  `blocking`; una warning `blocking` invalida el cierre, y una
  `accepted_health_exception` requiere evidencia, propietario y razon. No
  aceptes fabricacion manual de eventos de bus para borrar warnings.

### 6. Encoding y texto operativo

Para `.md`, `.py`, prompts, skills o documentacion operativa:

- No te fies del render de consola.
- Verifica por bytes o con el guard de encoding.
- Busca mojibake, BOM, `?` en palabra y de-acentuacion lossy.
- Si hay allowlist, distingue deuda real de datos intencionales.
- Si hay hook, prueba que bloquea una corrupcion deliberada, no solo que pasa en limpio.

**Criterio estricto: encoding NO es creacion ni existencia.**
`check_encoding_guard.py` valida integridad de bytes en un archivo que YA
EXISTE. No prueba que el agente haya creado el archivo, que tenga el
contenido correcto, ni que este en la ruta declarada. Para claims de
"archivo creado correctamente", exige evidencia en dos pasos:

1. **Existencia/lectura real:** `Test-Path`, `read_file`, `cat` o diff que
   muestre contenido. Esto confirma que el archivo existe y tiene contenido.
2. **Encoding correcto:** `check_encoding_guard.py` o verificacion por bytes.

Un claim como "encoding guard paso" NO cubre "archivo creado exitosamente".
Si el agente solo reporta encoding, marca `INFERENCIA RAZONABLE` sobre la
creacion y pide evidencia de existencia.

### 7. Autonomia del Builder

La auditoria no debe convertir al Builder en un ejecutor asustado.

Distingue:

- **Barrera obligatoria:** evita dano, falso cierre o corrupcion.
- **Criterio de decision:** ayuda al Builder a elegir sin frenar.
- **Sugerencia no bloqueante:** mejora futura.

Cuando sea posible, convierte aprendizajes en mecanismos automaticos y no en friccion manual.

### 8. Barrera automatica

Para cada fallo relevante:

- Existe ya una barrera que lo habria evitado?
- Si existe, fallo la barrera, no se ejecuto, o estaba fuera de scope?
- Si no se ejecuto: documenta por que y si el hueco es sistemico o circunstancial.
- Si fallo: distingue falso positivo de gap real en la barrera.
- Si no existe, la mejor salida es test, hook, fixture realista, prompt compuesto, manager gate o memoria?
- Si solo propones documentacion/memoria, explica por que una barrera automatica no es proporcional.

---

## Etiquetas de evidencia

Cada hallazgo debe incluir una:

- `VERIFICADO EN DIFF`
- `VERIFICADO EN CODIGO`
- `VERIFICADO EN TEST`
- `VERIFICADO EN BUS`
- `VERIFICADO EN GIT`
- `VERIFICADO POR BYTES`
- `VERIFICADO EN DOCUMENTACION`
- `VERIFICADO POR TOPOLOGIA` (archivo localizado en la ruta canonica correcta tras pre-requisito topologico)
- `INFERENCIA RAZONABLE`
- `NO VERIFICADO`

No mezcles inferencia con hecho confirmado.
`VERIFICADO POR TOPOLOGIA` complementa, no sustituye, a `VERIFICADO EN CODIGO`,
`VERIFICADO EN TEST`, `VERIFICADO EN GIT` o evidencia equivalente.
Aclara que verificaste en el root correcto; no basta por si solo.

---

## Clasificacion CEM

Para cada problema importante, indica:

- **Clase CEM canonica:** A regresion de contrato / B fuga de estado / C deriva de fixture / D entorno-infraestructura. Si no encaja, marca otro y explica.
- **Subtipo observado:** falso verde / root equivocado / fixture irreal / scope creep / encoding / auto-reporte / estado canonico / gate ausente / topologia_del_auditor / root_equivocado / claim_provisional_cristalizado / existencia_vs_encoding / memoria_no_portable / suite_roja_heredada / baseline_prematuro / otro.
- **Impacto de fallo:** codigo / tests / proceso / orquestacion / memoria / documentacion. No es el tipo de output auditado; es donde pega el riesgo.
- **Barrera existente:** test, hook, prompt, bus, manager gate, review u otra.
- **Barrera faltante:** que habria evitado el fallo.
- **Deuda residual:** que queda fuera de esta pasada.

---

## Formato de salida obligatorio

### 1. Veredicto

Uno de:

- `APROBADO`
- `APROBADO CON NITS`
- `CAMBIOS NECESARIOS`
- `NO ACEPTAR TODAVIA`

Incluye una frase con la razon principal.

### 2. Hallazgos

Ordenados por severidad: `CRITICO` / `ALTO` / `MEDIO` / `BAJO`.

Cada hallazgo incluye:

- Claim auditado
- Evidencia
- Riesgo
- Correccion exacta propuesta
- Etiqueta de evidencia
- Clasificacion CEM
- Si bloquea o no bloquea

### 3. Que haria ahora

Solo si el veredicto es CAMBIOS NECESARIOS o NO ACEPTAR TODAVIA: acciones concretas, en orden, con el menor cambio seguro.

### 4. Que NO haria

Solo si el veredicto es CAMBIOS NECESARIOS o NO ACEPTAR TODAVIA: atajos tentadores que introducirian falso verde, scope creep, deuda invisible o perdida de autonomia.

### 5. Aprendizaje reusable

Si aplica:

- aprendizaje candidato a memoria,
- barrera candidata,
- ticket follow-up sugerido.
