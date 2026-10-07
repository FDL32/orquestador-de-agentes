# DEC-router-skills-001: taxonomia de fases y contrato de metadatos de las skills

**Ticket:** pendiente de admision (familia "router de skills"; ID no asignado todavia).
**Fecha:** 2026-10-06. **Estado:** APROBADA por el usuario el 2026-10-06 (con la aclaracion de alcance de D-S4 posterior al piloto).
**Revision:** bucle R1 (`EXPLORATORY-skills-router`, DESIGN_REVIEW): 4 lentes API (BA11 nan,
BA150 mistral, BA31 groq, BA24 nvidia) + Codex (BA05, filesystem) + nan glm5.3-flash via Kilo (ad
hoc, fuera del scorecard por diseno), CHANGES/matices en 6/7 decisiones, veredicto completo en
`veredicto_skills_r1.md`. **Hubo DOS R2 de confirmacion solo Codex, sobre objetos distintos**
(corregido tras una ronda adicional pedida por el usuario; ver Parte C de `veredicto_skills_r2.md`
— la version anterior de este parrafo las mezclaba en singular, lo que Codex senalo como
inexactitud real): **R2 sobre `PROPUESTA_skills_v3.md`** (Parte A de `veredicto_skills_r2.md`):
ronda 1 CHANGES (3 hallazgos sobre D-S5 y D-S4), ronda 2 APPROVE tras correccion, sin necesitar la
3a ronda permitida. **R2 sobre esta misma DEC** (Parte B de `veredicto_skills_r2.md`): ronda 1
CHANGES, ronda 2 CHANGES (persistio el hallazgo de procedencia) — **NO convergio** dentro del
limite de 2 rondas que el tramo 2 se fijo. Una ronda 3 adicional (Parte C), pedida explicitamente
por el usuario y con el veredicto completo adjunto como evidencia, resolvio la existencia de la R2
sobre la DEC pero exigio esta misma correccion de cabecera. **Origen:** auditoria
de skills del usuario (2026-10-04, `AUDITORIA_skills_familias_20261004.md`) mas el piloto de
`DEC-router-prompts-001` (prompts, ya aprobada y pusheada a `main`/`origin/main` = `dc0fd6e`).
**Relacion con el prerequisito:** `skills-audit-fixes` (hallazgos A/B/C de la auditoria original)
ya esta fusionada y pusheada a `main`; esta DEC parte de ese estado.

## 1. Contexto

El repo tiene 43 skills en `skills/<nombre>/SKILL.md` con frontmatter YAML validado por
`skills/validate_all.py` (`REQUIRED_FIELDS`: name/version/description/author/tags/role/stage/
writes_memory/quality_gate). 18 de las 43 son skills-puntero: no llevan protocolo propio, solo
remiten a un `prompt` canonico (`prompts/<nombre>.md`) que gobierna el proceso real
(`source_prompt` + `contract_id` en su frontmatter, validado por `--check-contract` SOLO si
`role` esta en `CONTRACT_OPT_IN_ROLES = ("manager", "builder", "auditor")` de
`scripts/discover_skills.py`). Medido en esta sesion (censo con el parser de produccion, no
grep): 0/43 skills son visibles para Claude Code en una sesion normal sin truco; 0/43
descriptions contienen señal de "cuando usar"; el catalogo a mano (`skills/README.md`) documenta
25/43 y cita un numero de anti-patrones obsoleto (14, cuando el inventario real tiene 16).

Esta DEC aplica a las skills el mismo proceso que `DEC-router-prompts-001` ya aplico a los
prompts: metadatos de fase heredables, contrato de `description` como router nativo, visibilidad
nativa sin duplicar la fuente, y un unico punto de entrada generado (`ROUTER.md`).

## 2. Decision

### D-S1. Fases (`cycle_phase`), sin campo nuevo

Las skills-puntero (18/43) pueden declarar el MISMO campo `cycle_phase` que ya define
`DEC-router-prompts-001` D1 (los 9 valores `F0`..`F8`). Si una skill-puntero NO lo declara,
HEREDA el `cycle_phase` de su `source_prompt`. Las 25 skills autocontenidas SIEMPRE declaran su
propio `cycle_phase` (no tienen de donde heredar). Un solo vocabulario para prompts y skills; no
se introduce un nombre de campo alternativo (`override_cycle_phase` se evaluo y se descarto por
decision explicita, para no duplicar semantica con un nombre distinto).

**Evidencia:** `session-close-full-audit` declara `role: auditor`, `stage: review`
(`skills/session-close-full-audit/SKILL.md:7-8`) pero su `source_prompt`
(`prompts/orchestrator_session_close_full_audit.md`, linea 22) es de cierre de sesion F7 — caso
real de divergencia que motiva permitir la declaracion explicita en vez de forzar herencia ciega.

**Enmienda 2026-10-06 (Tramo B, tras adoptar los prompts de las punteras en el router):** la
herencia no siempre tiene de donde leer, porque `DEC-router-prompts-001` D4 deja sin fase dos tipos
de prompt. (a) Una puntero cuyo prompt es `mantenimiento` queda EXENTA de `cycle_phase`: ese
`route_kind` esta "fuera del ciclo" (D2) y su `cycle_phase` es "ausente" (D4), y `ROUTER.md` ya la
lista con su skill en la seccion "Fuera del ciclo (mantenimiento)"; forzarle una fase contradiria la
taxonomia del prompt que la skill solo apunta. La regla general de D-S1 (la fase propia de una
skill siempre gana) no se toca: si alguna vez una de ellas declarase fase, seria un metadato del USO
de la skill, que no mete al prompt en el ciclo ni cambia su `route_kind`; hoy ninguna lo hace. La
exencion se deriva del `route_kind` real del prompt, nunca de una lista a mano. (b) Una puntero
cuyo prompt es `modulo` (prompt con `cycle_phase` PROHIBIDA) declara la suya propia; hoy el unico
caso es `builder-implement-from-plan` -> `[F5-implementacion]`. No choca con D4: la regla de no
escribir a mano la relacion de un modulo con las fases rige para el PROMPT modulo (la deriva el
router de sus citadores); la fase de la skill es la de su propio uso (el Builder implementa). Esa
fase satisface el invariante pero NO anade descubribilidad: no hay seccion del ROUTER que la
muestre (ver la excepcion de D-S6).

### D-S2. Rol `orchestrator`

`orchestrator` se anade a `VALID_ROLES` de `skills/validate_all.py` (hoy: builder, manager,
shared, user, auditor) Y a `CONTRACT_OPT_IN_ROLES` de `scripts/discover_skills.py` (hoy:
manager, builder, auditor). Las 3 skills `orchestrate-autonomous-ticket-batch`,
`orchestrate-destination-batch`, `orchestrate-pipeline` se reclasifican de `role: shared` a
`role: orchestrator`.

**Evidencia:** esas 3 skills tienen `source_prompt`/`contract_id` declarados pero hoy escapan al
gate `--check-contract` porque `shared` no esta en `CONTRACT_OPT_IN_ROLES`
(`scripts/discover_skills.py:287`, verificado). Sin el opt-in, reclasificar seria cosmetico (5/6
lentes de R1 coinciden en esto, incluido Codex con filesystem).

**Nota de nomenclatura (no normativa para esta DEC):** el modulo de prompts ya define un
`CANONICAL_ROLES` propio (`scripts/discover_skills.py:867`, D3 de `DEC-router-prompts-001`) que
incluye `orchestrator` para PROMPTS. Es un conjunto DISTINTO del `VALID_ROLES` de
`skills/validate_all.py` para SKILLS: no se fusionan en esta DEC (riesgo senalado por Codex en R2,
sin exigir cambio porque v3 no los confundia).

### D-S3. `description` como router nativo, sin techo numerico forzado

Formato: `<que hace>. Usar cuando <...>. No usar para <...> (ver <alternativa>)`. Invariante de
trinquete: presencia de las frases guia "Usar cuando" y "No usar para" (solo puede mejorar, nunca
empeorar respecto al estado 0/43 actual). **Sin techo de caracteres forzado por esta DEC**: medido
en el PASO 1a del tramo 2 (ver D-S4) que una description de 1200 caracteres no se trunca en el
listado nativo de Claude Code con 85 entradas totales (version 2.1.289). Esta medicion sustenta
NO fijar un numero extrapolado de la longitud actual (candidatos de R1: 180-400, todos basados en
estadistica de las descriptions HOY, no en el limite de truncado real) — pero es evidencia de UNA
ejecucion, no una propiedad general del producto. Si una version futura o un volumen mayor de
entradas cambia el comportamiento observado, re-medir antes de asumir ausencia de truncado.

En las 18 skills-puntero, el texto de `description` deriva del `when`/`not` de su prompt
(`PROMPT-SUMMARY`, fuente unica), igual que para el `cycle_phase` heredado (D-S1).

### D-S4. Visibilidad nativa via stubs generados, canal Claude Code; `ROUTER.md` para el resto

Se generan stubs `.claude/skills/<nombre>/SKILL.md` (solo `name` + `description` +
una linea que remite a `skills/<nombre>/SKILL.md`) para las skills reales. **Alcance por defecto
(aclarado 2026-10-06, tras el piloto):** el generador cubre por defecto SOLO el scope ya desplegado
(las 4 skills del piloto); `--all-skills` genera las 43. El objetivo final sigue siendo 43/43, pero
se alcanza por el despliegue por lotes, no por la ejecucion por defecto: asi el generador nunca crea
stubs de skills cuyo `description` aun no tiene "Usar cuando"/"No usar para". Con gate de
frescura (misma arquitectura que `ROUTER.md`: si el `SKILL.md` real cambia su `description` y el
stub no se regenera, el gate falla y bloquea `--generate-index`/`--check-index`).

**Excepcion declarada (2026-10-06, Tramo B):** `session-hop` NO recibe stub. Su nombre ya lo
ocupa el comando versionado `.claude/commands/session-hop.md`, que tambien remite a
`prompts/session_hop.md` (desde la decision de abajo, solo como puntero); un stub
con el mismo nombre compite por el mismo `/session-hop` y deja tapada una de las dos entradas.
Se conserva el comando hasta que el usuario decida retirarlo o convertirlo. El generador lo
salta tambien con `--all-skills` (`_stub_names` excluye los nombres de `.claude/commands/`), y
`test_no_deployed_stub_shadows_a_command` falla si un stub desplegado usa el nombre de un comando. Con esto el despliegue cierra en 42/43 por decision, no por olvido.

**Decision del usuario (2026-10-06):** se CONSERVA el comando y se adelgaza a puntero puro. Su
version anterior re-declaraba la regla METODO/ESTADO, el etiquetado `[snapshot <fecha>]` y la
"Restriccion dura" del prompt (tercera copia, contra "skill apunta, prompt gobierna"). Convertirlo
en stub queda APLAZADO: exige reabrir la decision D1+D5 del ticket de `session-hop`, que fija el
comando (`test_las_cuatro_piezas_existen`), y la unica ganancia medida es la description que Claude
Code muestra (hoy la primera linea del comando, en vez del "Usar cuando / No usar para" de la skill).

**Medido (PASO 1a del tramo 2, worktree aislado en `main`@`dc0fd6e`, limpiado tras el probe):** un
generador produjo 44 stubs (43 reales + 1 de prueba `probe-largo` con description de 1200
caracteres marcada cada 100). En el adjunto `skill_listing` real del transcript de una corrida
headless (`claude.exe -p ... --output-format text`, con la herramienta `Skill` habilitada):
44/44 stubs aparecieron, 0 faltantes; las 43 descriptions reales salieron byte-identicas a su
frontmatter de origen (0 mismatches); `probe-largo` aparecio completo (ultima marca presente:
`M1200`, la maxima posible; ninguna marca ausente). El `skill_listing` total midio 26643
caracteres con 85 entradas (44 nuestras + 41 del entorno/anthropic-skills).

**Alcance de canal, declarado explicitamente (pedido en el tramo 2):** los stubs de
`.claude/skills/` sirven EXCLUSIVAMENTE a la extension/app nativa de Claude Code (el mismo binario
usado en todos los probes: `anthropic.claude-code-2.1.289-win32-x64\resources\native-binary\
claude.exe`), incluido el panel de Cursor que corre sobre ese binario. **"Cursor" en esta DEC
significa la extension de Claude Code dentro de Cursor, NO el agente nativo de Cursor** (su propio
sistema, si existe y difiere, no se probo en ninguna sesion de este router). Para Codex, Kilo/nan,
OpenCode (roto en local) y cualquier agente que no lea `.claude/skills/`, el canal de
descubrimiento sigue siendo `ROUTER.md` generado — el mismo artefacto que ya sirve a los prompts.
Stubs y router no son alternativos entre si: son dos puertas (Claude Code nativo vs todo lo demas)
alimentadas por el MISMO frontmatter fuente.

**Riesgo declarado (R1, 5/6 lentes; observado de forma parcial en PASO 1b del tramo 2):** un stub
puede activarse por invocacion de skill cuando su nombre aparece en el texto de una peticion,
reforzando la necesidad de que el generador derive el nombre del stub 1:1 del directorio real
(sin alias ni abreviaturas que coincidan con lenguaje natural frecuente).

### D-S5. `skills:` en `.claude/agents/{manager,builder}.md`: quitar las 6 referencias

Se quitan las 6 referencias (`manager.md`: `manager-create-work-plan`,
`manager-review-implementation`, `manager-resolve-escalation`; `builder.md`:
`builder-implement-from-plan`, `builder-self-audit`, `builder-run-quality-gates`; verificado por
lectura directa del frontmatter de ambos ficheros, 3+3=6).

**Base de la decision (medido, PASO 1b del tramo 2, acotado al caso probado):** para la skill
`manager-review-implementation` con el agente `manager`, con una marca unica escrita al final del
SKILL.md real y SIN stub en `.claude/skills/`, la marca NO aparecio en el `.jsonl` del subagente
(0 ocurrencias de la cadena completa con sufijo aleatorio, verificado contra el transcript, no la
respuesta del orquestador; el subagente no uso ninguna herramienta). Esto demuestra que, para el
caso probado, el campo `skills:` no produjo contenido observable en el mensaje del subagente — no
se extiende esta conclusion a las otras 5 combinaciones sin probes equivalentes.

**La decision de quitar las 6 referencias NO depende de resolver esa pregunta para los 6 casos:**
depende de que D-S4 (stubs) demostro, con las 44 skills reales, ser un mecanismo de
descubribilidad que funciona (ver evidencia arriba), haciendo redundante cualquier efecto que
`skills:` pudiera o no tener. Se recomienda, como accion de seguimiento no bloqueante para esta
DEC, repetir la variante (i) del probe para al menos una combinacion de `builder.md` antes del
despliegue por lotes, como verificacion cruzada.

**Matiz sobre la variante (ii) del mismo probe (con stub presente):** la marca SI aparecio, pero
por invocacion activa de la skill como comando (formato `<command-name>`), no por precarga pasiva;
no se aislo si esa activacion fue espontanea o inducida por la mencion literal del nombre en el
prompt de la sonda. Este matiz es relevante para el riesgo de D-S4 (colision de nombre), no
cambia la base de D-S5.

### D-S6. Un solo punto de entrada (`docs/registry/ROUTER.md`)

`docs/registry/ROUTER.md` (generado por `scripts/discover_skills.py --generate-index` para
prompts; existe hoy en `main`/`origin/main` = `dc0fd6e`, verificado por `git show`; NO existe en
el checkout actual de esta sesion, que esta en la rama `skills-audit-fixes`) gana, como parte del
piloto de esta DEC (seccion 4), una columna `skill` en cada fila de prompt que tenga una
skill-puntero asociada, mas una seccion nueva "skills autocontenidas por fase". Esta extension NO
esta implementada todavia; el piloto debe generarla y validarla. `skills/README.md` (verificado:
137 lineas, 25 filas de tabla, con prosa narrativa fuera de la tabla) sustituye SOLO su tabla
desactualizada por un puntero al router extendido; la prosa narrativa se conserva sin cambios.

**Excepcion declarada (enmienda 2026-10-06):** una puntero cuyo prompt es `modulo` no tiene fila
propia en el ROUTER, porque la tabla de modulos no lleva columna `skill` por diseno
(`DEC-router-prompts-001` D2: un modulo "NO se abre por iniciativa propia; lo ordena u ofrece otro
fichero"). Hoy afecta solo a `builder-implement-from-plan`. Para Claude Code sigue visible por su
stub (D-S4); para el resto de canales llega a traves del prompt que ordena el modulo. Anadir la
columna a esa tabla o listar la skill entre las autocontenidas se descarto: lo primero cambia
codigo y la proyeccion generada, lo segundo rompe la regla de que alli solo van autocontenidas.

### D-S7. Lint de referencias: ticket aparte, con fixtures y helper reutilizable

Se ficha como ticket separado (no entra en el alcance de esta DEC), con dos condiciones: (a) sus
fixtures iniciales son los 3 casos ya conocidos y verificados — `graphify` citando 2 referencias
inexistentes en `references/`, y `skills/README.md` citando "AP-01..AP-14" cuando
`skills/_shared/anti-patterns.md` tiene 16 entradas reales; (b) el router (D-S6) debe exponer su
helper de comparacion "cita vs disco" (analogo a `module_citations` de `DEC-router-prompts-001`
D4) para que el lint lo reutilice en vez de reimplementar el parser.

## 3. Contrato de frontmatter y reglas de validacion (cambios en codigo, NO implementados en esta
## sesion — son el contenido del piloto, paso 4 del proceso)

- `skills/validate_all.py`: `VALID_ROLES` pasa a incluir `orchestrator` (D-S2). `REQUIRED_FIELDS`
  no cambia de nombre (`stage` se MANTIENE como metadato de lifecycle interno de
  `validate_all.py`, sin uso para enrutar — D-S1 del tramo 1, sin cambios).
- `scripts/discover_skills.py`: `CONTRACT_OPT_IN_ROLES` pasa a incluir `orchestrator` (D-S2). El
  descubrimiento de skills gana soporte para `cycle_phase` opcional en frontmatter de skill, con
  herencia de `source_prompt` cuando esta ausente (D-S1). Generador nuevo de stubs
  `.claude/skills/<n>/SKILL.md` con gate de frescura (D-S4), analogo al generador de `ROUTER.md`.
- `docs/registry/ROUTER.md`: generado por `scripts/discover_skills.py --generate-index` para
  prompts (existe hoy en `main`/`origin/main`, NO en el checkout actual que esta en
  `skills-audit-fixes`). Para skills, este artefacto gana columna `skill` y seccion de
  autocontenidas por fase (D-S6) como parte del piloto (seccion 4) — no existe todavia con esa
  extension; el piloto debe generarlo y validarlo.
- `skills/README.md`: la tabla de 25 filas se sustituye por un puntero al router; la prosa
  narrativa (fuera de la tabla) se conserva sin cambios.
- `.claude/agents/manager.md`, `.claude/agents/builder.md`: se quitan las 6 referencias `skills:`
  (D-S5).

## 4. Plan de piloto (paso 4 del proceso, una skill por tipo)

- Puntero con prompt ya piloto: `manager-review-implementation` (su `source_prompt`,
  `prompts/manager_review.md`, ya tiene metadatos de fase de `DEC-router-prompts-001`).
- Autocontenida: `systematic-debugging`.
- Invocada por el usuario: `setup-agent-system`.
- Del orquestador, ya reclasificada por D-S2: `orchestrate-pipeline` (`role: orchestrator` tras
  esta DEC), caso de prueba natural del nuevo opt-in al gate `--check-contract`.

Guard del piloto: `skills/validate_all.py`, `discover_skills.py --check-naming/--check-index/
--check-contract`, tests que nombran las 4 skills del piloto, y la mutacion del gate nuevo (stub
desincronizado del `SKILL.md` real debe fallar el gate de frescura).

## 5. Definicion de cierre (DoD), como INVARIANTES

- Toda skill-puntero sin `cycle_phase` propio resuelve al de su `source_prompt`; toda skill
  autocontenida declara el suyo. Ninguna skill queda sin `cycle_phase` resoluble, SALVO las
  skills-puntero cuyo prompt es `mantenimiento` (enmienda de D-S1, exencion derivada del
  `route_kind` real del prompt). Todo valor resuelto pertenece al vocabulario de fases de D-S1.
- Toda skill con `role` en `CONTRACT_OPT_IN_ROLES` (incluido `orchestrator` tras esta DEC) con
  `source_prompt`/`contract_id` declarado pasa `--check-contract`; ninguna skill con esos campos
  declarados escapa al gate por razon de `role`.
- Toda `description` nueva o modificada contiene las frases guia "Usar cuando" y "No usar para";
  el trinquete de adopcion solo permite mejorar esta cobertura, nunca reducirla.
- Todo stub en `.claude/skills/<n>/SKILL.md` tiene `description` identica a la de
  `skills/<n>/SKILL.md`; un gate de frescura falla si divergen.
- `ROUTER.md` referencia toda skill-puntero por su columna `skill`; ninguna skill-puntero queda
  sin esa columna, SALVO las que apuntan a un prompt `modulo` (excepcion declarada en D-S6). Cada
  prompt tiene como mucho una skill-puntero, tenga o no fila en el ROUTER (donde la tiene, la
  columna solo puede mostrar una).
- Ningun stub desplegado usa el nombre de un comando versionado de `.claude/commands/` (excepcion
  de D-S4: `session-hop` se queda sin stub).
- `.claude/agents/manager.md` y `.claude/agents/builder.md` no declaran `skills:`.
- No es criterio de cierre ninguna cifra de esta sesion (44 stubs, 1200 caracteres, 26643
  caracteres de listing): esas cifras son evidencia fechada de ESTA medicion, no un invariante a
  mantener literal en el futuro.

## 6. Condiciones de refutacion

- Si un probe futuro con mas volumen o una version distinta de Claude Code muestra truncado por
  debajo de 1200 caracteres: D-S3 se revisa y se fija un techo numerico medido (no extrapolado).
- Si un probe equivalente al de D-S5 sobre `builder.md` muestra precarga real de `skills:`: D-S5
  se revisa antes del despliegue por lotes (accion de seguimiento ya declarada en la seccion D-S5).
- Si el agente nativo de Cursor (distinto de la extension de Claude Code) resulta leer
  `.claude/skills/` o un directorio propio: el alcance de canal de D-S4 se amplia con ese dato.

## 7. Non-goals

No se toca el lint de referencias (D-S7, ticket aparte). No se toca `TASK_TYPES`,
`GOVERNMENT_PHASES` ni `review_bridge` (fuera de alcance, igual que en `DEC-router-prompts-001`).
No se fusiona `CANONICAL_ROLES` (prompts) con `VALID_ROLES` (skills) — son conjuntos distintos por
diseno, nota de R2.

## 8. Relacion con otras decisiones

`DEC-router-prompts-001` (ya aprobada y pusheada a `main`/`origin/main` = `dc0fd6e`): define
`cycle_phase`, `PROMPT-SUMMARY` y el generador de `ROUTER.md` que esta DEC extiende a skills.
Auditoria de skills del usuario (2026-10-04): origen del censo de 43 skills y de los hallazgos
A/B/C ya resueltos en `skills-audit-fixes` (fusionada antes de esta DEC).

## Anexo: historial de revision de esta DEC

- R1 (`veredicto_skills_r1.md`): 5 lentes independientes (BA11, BA150, BA31, BA24, BA05) + Kilo
  nan/glm5.3-flash ad hoc; cambios adoptados en D-S1 (override hoy retirado, ver R2), D-S2
  (opt-in obligatorio), D-S5 (sondar antes de quitar, hoy resuelto con cifras), D-S6 (conservar
  prosa narrativa); D-S3/D-S4 quedaron con pendientes de medicion, resueltos en el PASO 1 del
  tramo 2.
- R2 (solo Codex, confirmacion): ronda 1 CHANGES (D-S5 generalizaba el probe mas alla de lo
  medido; D-S4/D-S3 debian formularse estrictamente como experimentales; D-S4 variante (ii)
  afirmaba "auto-invocacion espontanea" sin descartar la lectura alternativa de invocacion
  inducida). Ronda 2 APPROVE tras corregir el lenguaje de v3 en las 3 secciones senaladas, sin
  cambiar ninguna decision de fondo. Matiz no bloqueante: `CANONICAL_ROLES` (prompts) vs
  `VALID_ROLES` (skills) son nombres distintos para conjuntos distintos; no es un defecto de v3.
- R3, 2026-10-06 (`EXPLORATORY-skills-tramo-b`, DESIGN_REVIEW de las enmiendas de D-S1/D-S6 antes
  de desplegar las 16 punteras): Codex (BA05, filesystem) CHANGES por condiciones de procedimiento
  (fijar la base `prompts-adopt-b1a@517fa6c` y re-derivar si se mueve; enmendar DEC, DoD y test a
  la vez; unicidad prompt -> skill); nan glm5.3-flash via Kilo (filesystem) APPROVE, con la
  precision adoptada de que la fase del modulo no anade descubribilidad. Las dos lentes avalan la
  exencion de mantenimiento y la fase propia del modulo con excepcion declarada; las dos
  descartan un check semantico skill<->prompt por no determinista.
- R4, 2026-10-06 (bucle de gobierno `DBL-4` MANAGER_REVIEW sobre `0a024ed`, nonce
  `e0ef560465de5ca9d24fef040adcc9f5`): rama comun BA11, BA13, BA15 (nan) + BA92 (sustituta de BA25,
  tokenharbor), rama dif BA11, BA13, BA15; BA16 y BA10 cayeron a BA01 (no cuentan); lector Claude
  con filesystem; sintesis en dos pasadas Claude; refutacion final Codex (BA05). Lentes
  independientes: 4 + Codex. Hallazgos aceptados y aplicados en el commit siguiente: la description
  de `session-close-full-audit` aflojaba la barrera de 2.5.f/2.5.g; el stub de `session-hop`
  chocaba con su comando (excepcion de D-S4, tambien en el generador); omisiones de tres
  descriptions; redaccion del DoD; enum de fases y unicidad por ruta resuelta en el test.
