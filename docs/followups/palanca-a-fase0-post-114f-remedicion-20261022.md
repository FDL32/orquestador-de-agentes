# Re-medicion Fase 0 post-WOT-2026-114f -- Palanca A, continuacion 2026-10-22

> Continua `docs/followups/palanca-a-fase0r-medicion-informe.md` (Ronda 2, veredicto
> "SIN CANDIDATO MOVIBLE" al HEAD `279d2705`). Desde entonces se ejecutaron
> WOT-2026-114b (retiro Hermes), 114c (mueve Vocabulario canonico), 114d/114e/114f
> (split quirurgico de CEM v0 + claves de referencia `[X#]`). Esta es la primera
> re-medicion fresca tras esos cuatro movimientos.

## ESTADO_FRESCO

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022, HEAD=d4f730fc7b3b7d75b03b4705ba546c5607998073, dirty=0, verificado=2026-10-22
```

Fuente JSON: `uv run python scripts/measure_agents_md_units.py --json` (ejecutado en fresco a este HEAD).

## Tabla PASO 1 -- Gates (comparativa contra Fase 0R)

| Fichero | Gate | Fase 0R (HEAD 279d2705) | Ahora (HEAD d4f730fc) | Delta |
|---------|------|--------------------------|------------------------|-------|
| AGENTS.md (Codex, bytes) | 32768 B | 61370 B = 1,87x | **42557 B = 1,2987x** | -18813 B |
| CLAUDE.md + @AGENTS.md (Claude, chars) | 40000 chars | 63292 chars = 1,58x | **44486 chars = 1,1121x** | -18806 chars |

Ninguno de los dos gates esta cerrado todavia. Deficit restante: **9789 B** (Codex) /
**4486 chars** (Claude).

Los cuatro movimientos de este vuelo (114b-114f) ya redujeron el ratio de 1,87x/1,58x a
1,30x/1,11x -- mejora real y medida, no estimada.

## Hallazgo metodologico: PASO 3(d) de Fase 0R fue sobre-amplio

Fase 0R concluyo "SIN CANDIDATO MOVIBLE" citando que `scripts/build_llms.py` declara
`AGENTS.md` en `INLINE_IN_FULL` y lee el fichero **completo** para `llms-full.txt`, lo
que hacia fallar PASO 3(d) para **las 24 unidades nivel-2**, sin excepcion.

**Esa conclusion no se sostuvo en la practica.** CEM v0 (unidad #12, 11329 B, que Fase 0R
clasifico como bloqueda por PASO 3(e) Hermes **y** PASO 3(d) build_llms.py) se movio de
todas formas en WOT-2026-114d/e -- y el gate SI mejoro en la cantidad medida (el split
quirurgico redujo CEM v0 de 11329 B a ~5234 B de subtree, ~6000 B de ahorro neto en
AGENTS.md).

**La razon por la que PASO 3(d) no debia ser un veto absoluto:** los dos gates que
`measure_agents_md_units.py` mide (`codex_bytes` sobre `AGENTS.md`, `claude_chars` sobre
`CLAUDE.md + @AGENTS.md`) son estrictamente sobre el CONTENIDO DE ESOS DOS FICHEROS en el
arranque en frio del agente. `llms-full.txt` es una PROYECCION distinta (consumida por
crawlers/documentacion externa via la convencion `llms.txt`, sincronizada por el hook
"check llms.txt/llms-full.txt sync" pre-commit, nunca inyectada en un arranque de sesion
de agente). Que `build_llms.py` lea el AGENTS.md completo para construir esa proyeccion
**no cambia el tamano del AGENTS.md que un agente carga en frio** -- mover un bloque
FUERA de AGENTS.md reduce igual el gate aunque `llms-full.txt` siga reflejando el
fichero (via su propia proyeccion, que se actualiza por separado y no cuenta contra
ningun gate de cuspide).

**Correccion propuesta para futuras rondas de Fase 0:** PASO 3(d) deberia distinguirse
entre "consumidor que carga en el arranque en frio del agente" (veto real, ej. un hook
`SessionStart`) y "consumidor que genera una proyeccion derivada no cargada en frio"
(no es veto, `build_llms.py`/`llms-full.txt` cae en esta segunda categoria). Esto no se
aplica retroactivamente a Fase 0R (queda como esta, fechado); se declara aqui como
correccion metodologica para la proxima ronda.

## Candidato encontrado: `### Orden de trabajo: AGRUPA los commits... (WOT-2026-026t)`

Dentro de `## Convenciones` (el contenedor de 14652 B, ahora probablemente algo menor
tras 114c/d/e -- no re-medido aqui porque Vocabulario canonico y CEM v0 ya salieron de
ahi), la subseccion `### Orden de trabajo... (WOT-2026-026t)` (lineas 161-269) es ahora
el bloque nivel-3 mas grande del fichero:

| Rango | Contenido | Bytes | Patron (igual que CEM v0 Grupo B) |
|-------|-----------|-------|-------------------------------------|
| 161-215 (own de `###`) | Regla + 3 parrafos de caso forense | 3979 | mixto |
| 195-215 | "Asignacion de rol en despacho trio" -- incidente medido 2026-10-18, WOT-2026-104j, cifras + cita de bucle de gobierno UNI-5 | **1874** | refutacion-corta + forense-largo |
| 186-193 | "No uses `-k`..." -- incidente medido WOT-2026-079d, cita de memoria 2026-09-27 | **657** | refutacion-corta + forense-largo |
| 217-224 (`#### Push por vuelo`) | Regla + 3 bullets | 1046 | YA DUPLICADO en `.agent/rules/common/flight_push_policy.md:1-26` (Fase 0R, "Censo de duplicacion", confirmado) |
| 226-269 (`#### Extension: push...`) | Gate 2 completo: criterio, condiciones de rechazo, riesgo residual declarado | 3473 | normativo-largo, NO duplicado todavia en `flight_push_policy.md` (solo header+Gate1, per Fase 0R) |
| &nbsp;&nbsp;248-262 (subset) | "Condiciones de rechazo del Gate 2" | 1205 | normativo-largo |
| &nbsp;&nbsp;264-269 (subset) | "Riesgo residual declarado" | 512 | normativo-largo |

**Verdict: CANDIDATO ENCONTRADO**, bajo el mismo criterio PASO 3(c) que justifico mover
CEM v0 (refutacion corta que se queda + caso forense extenso que se muda), mas una pieza
adicional de duplicacion ya confirmada por Fase 0R (`Push por vuelo`, 1046 B, puede
colapsarse a un puntero porque `flight_push_policy.md` YA tiene el contenido completo).

### Estimacion de ahorro neto (conservadora, mismo metodo que Fase 0R Seccion "Sobre
bytes vs caracteres": E2 conservador, refutacion corta se queda ~150 B por bloque)

| Pieza | Own actual | Puntero propuesto | Ahorro neto |
|-------|-----------|--------------------|-------------|
| "Asignacion de rol en despacho trio" | 1874 | ~150 | **~1724 B** |
| "No uses `-k`..." | 657 | ~150 | **~507 B** |
| "Push por vuelo" (ya duplicado) | 1046 | ~150 (solo el puntero que ya existe, recortar los 3 bullets redundantes) | **~896 B** |
| "Extension: push" (Gate 2 completo) | 3473 | ~200 (regla + puntero a modulo nuevo) | **~3273 B** |
| **Total estimado** | | | **~6400 B** |

Deficit restante tras este movimiento: Codex ~9789-6400 = **~3389 B** (de 1,30x a
~1,10x estimado); Claude ~4486-6400 = **gate CERRADO** (sobra margen, los bloques son
bytes~=chars por ser ASCII-heavy sin no-ASCII significativo, igual que CEM v0).

**Esto NO cierra el gate Codex por si solo**, pero deja un deficit mucho mas pequeno
(~3389 B, candidato a cerrarse con una segunda pasada sobre los 24 bloques "pequenos"
de la Seccion 5 de Fase 0R, ahora reevaluados bajo la correccion metodologica de arriba
en vez del veto absoluto de PASO 3(d)).

## Riesgo declarado (mismo que Fase 0R advirtio para CEM v0)

El split de "Extension: push" requiere escribir contenido NUEVO en
`.agent/rules/common/flight_push_policy.md` (el Gate 2 completo no esta duplicado ahi
todavia, a diferencia de "Push por vuelo" que si lo esta) -- no es un recorte trivial de
duplicado, es una migracion real de contenido normativo. Exige el mismo cuidado que
CEM v0 (PASO 3(c) de `doc_optimization.md`: verificar que la frase de refutacion que se
queda no pierde fuerza sin su desarrollo adyacente) mas verificacion de que ningun guard
cite directamente las lineas movidas por numero (grep de `AGENTS.md:2[2-6][0-9]` antes de
mover).

## Recomendacion

1. Ejecutar el mismo patron de split quirurgico que WOT-2026-114d/e sobre estas 4 piezas
   (trio incident, -k filter incident, Push por vuelo, Extension: push), como un ticket
   nuevo (siguiente sufijo disponible tras 114f).
2. Medir antes/despues con `measure_agents_md_units.py --json` igual que en este informe.
3. Si el deficit Codex restante (~3389 B estimado) no cierra con esto, la siguiente
   candidata es una revision completa de los 24 bloques "pequenos" de Fase 0R Seccion 5
   bajo la correccion metodologica de PASO 3(d) de este documento (ya no todos fallan
   automaticamente por `build_llms.py`).

No se implementa nada en este documento -- es medicion y analisis, para que el usuario
decida si abre el siguiente ticket.

## Pasada de verificacion independiente y propuesta consolidada (2026-10-22)

Re-medicion byte a byte, independiente de la de arriba (no se reusa el numero, se re-deriva):
lineas 186-193 ("No uses `-k`...") = **657 B**, lineas 195-215 (trio) = **1874 B**, lineas
217-224 ("Push por vuelo") = **1046 B**, lineas 226-269 ("Extension: push" completo) = **3473 B**
(subset 248-262 "Condiciones de rechazo" = 1205 B, subset 264-269 "Riesgo residual" = 512 B).
**Los 4 numeros de la tabla de arriba se confirman exactos**, cero discrepancia.

### Correccion 1: "Push por vuelo" no es un duplicado 100% verbatim, pero si sustancialmente redundante

Comparado linea a linea contra `.agent/rules/common/flight_push_policy.md` (30 lineas, 2317 B):
el parrafo "DECISION DE PROCESO... BUSQUEDA-PREVIA..." es **identico caracter a caracter** en
ambos ficheros; la frase "NO se pushea entre tickets" aparece en ambos (literal en AGENTS.md,
parafraseada dentro de una oracion mas larga en `flight_push_policy.md`); el bullet
"Sin autorizacion registrada no hay push..." es **identico**. La unica pieza de AGENTS.md que
NO esta en `flight_push_policy.md` es el propio puntero ("Ver detalles... en
`flight_push_policy.md`"), que ya es el patron correcto. Veredicto: colapsar este bloque a un
puntero mas corto es una operacion de **recorte de duplicado confirmado**, no una migracion de
contenido nuevo -- riesgo bajo, distinto (y menor) del de CEM v0.

### Correccion 2: "Extension: push" (Gate 2) NO es el mismo patron que CEM v0 -- riesgo real a declarar explicito, no solo "mismo cuidado"

El documento de arriba ya marca esta pieza como "normativo-largo" (no "refutacion-corta +
forense-largo") y declara que exige "el mismo cuidado que CEM v0". **Eso subestima la
diferencia.** Los casos forenses de CEM v0 (`cem_v0_evidencia_forense.md`) son contexto
OPCIONAL: explican POR QUE existe una regla de una linea que ya es completa y accionable por si
sola. El contenido de "Extension: push" (criterios de rechazo del Gate 2, riesgo residual
declarado) es **la propia especificacion operativa** -- un agente que necesita decidir SI puede
aplicar el Gate 2 relajado en un push con trafico concurrente necesita leer ESOS criterios EN EL
MOMENTO de la decision, no como trasfondo posterior. Mover este contenido a un modulo de
referencia sin que el puntero que queda en AGENTS.md declare explicitamente la condicion de
disparo ("si vas a aplicar Gate 2 relajado, lee primero [T4]") convierte una regla accionable en
una que un agente puede pasar por alto porque no sabe que necesita consultarla ahora, no
"cuando le interese". **Mitigacion exigida para esta pieza (y no para las otras 3):** el
`refutacion-corta` que se queda en AGENTS.md debe nombrar la condicion de disparo explicitamente
(p.ej. *"Gate 2 (push a rama con trafico concurrente): criterios de rechazo completos y riesgo
residual en [T4] -- leelos ANTES de aplicar la relajacion, no despues."*), no solo un puntero
generico de una linea como los otros 3.

### Hallazgo nuevo 1: cita de linea YA STALE en `manifest_contracts.md` (pre-existente, no introducida por esta propuesta)

`.agent/rules/common/manifest_contracts.md:5` cita `AGENTS.md:214-230` para la seccion
`## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)`. Verificado: esa seccion esta HOY en
la linea **95**, no 214-230 -- la cita quedo stale por un movimiento previo (114c/114d, cuando
Vocabulario canonico y CEM v0 salieron de AGENTS.md y corrieron todas las lineas siguientes hacia
arriba). Es un hallazgo independiente de WOT-2026-026t (mismo defecto de clase que el comentario
stale del hook corregido en 114f), pero se recomienda corregirlo en el mismo ticket porque
mover MAS contenido (WOT-2026-026t) desplazara de nuevo las lineas y agravaria la cita si no se
corrige ahora. Fix: cambiar la cita a numero de linea actual O (mejor, mas robusto a futuros
movimientos) a una referencia por encabezado (`## MANIFEST.distribute y MANIFEST.workspace`) sin
numero de linea.

### Hallazgo nuevo 2: el "fix" de `MANUAL_PUBLICATION_CHECKLIST.md` propuesto por el fork anterior es insuficiente -- la premisa completa del documento es obsoleta, no solo la version de ejemplo

El fork anterior reporto una version de ejemplo stale (`v9.6.0` en un mensaje de commit de
muestra, linea 15). Verificado y confirmado -- pero es la parte MENOR del problema. La primera
linea del documento declara: *"este checklist documenta los pasos manuales... ya que el agente
no ejecuta comandos de git"*. **Esa premisa es falsa hoy**: esta misma sesion ha ejecutado
decenas de `git commit`/`git add`/`git status` directamente via herramienta Bash a lo largo de
WOT-2026-114b a 114g. El documento entero (fechado `WP-2026-058`, una era anterior del motor) es
candidato a marcarse como **legacy/historico** -- no solo corregir el numero de version de un
ejemplo ilustrativo. Recomendacion: anadir una nota de cabecera ("Documento historico de
WP-2026-058, pre-fecha el flujo actual donde el agente SI ejecuta git directamente; ver
`AGENTS.md` seccion 'Orden de trabajo' para el flujo vigente") en vez de reescribirlo entero
(fuera de alcance de este ticket).

### Hallazgo nuevo 3: `.loop_bundle_optimizacion.md` no es debris generico -- es una RECURRENCIA del mismo anti-patron ya documentado (WOT-2026-104n)

Verificado con `git log --all -- .loop_bundle_optimizacion.md`: el fichero esta trackeado desde
el commit `8756e927` ("WOT-2026-104l: clear stale events and add execution_log evidence (ronda
2)", 2026-10-19) -- **el mensaje de ese commit no menciona bundles de bucle en absoluto**, lo que
confirma que entro por un `git add -A` que arrastro contenido fuera de alcance (exactamente el
patron que advierte `AGENTS.md` seccion "Orden de trabajo" sobre volumen desproporcionado).
Ademas, `prompts/orchestrator_launch_builder.md:303-310` ya documenta **este mismo nombre de
fichero** como precedente citado de WOT-2026-104n (2026-10-19, mismo dia): *"un `git add -A`
final capturo solo `.loop_bundle_optimizacion.md` como volumen sospechoso"*. Es decir: el
fichero que hoy sigue en la raiz no es un caso nuevo de debris -- es el MISMO incidente ya
analizado en WOT-2026-104n, que nunca se limpio. Seguro de borrar (ninguna otra referencia viva
lo consume; el unico grep positivo es la cita historica en el prompt, que sigue siendo correcta
como anecdota aunque el fichero se borre).

### Propuesta consolidada (4 cambios concretos, ninguno implementado todavia)

1. **Split WOT-2026-026t** (nuevo ticket, siguiente sufijo tras 114g): mover las 4 piezas
   (657 + 1874 + 1046 + 3473 B = 7050 B de origen) a un modulo nuevo
   `.agent/rules/common/wot_026t_orden_trabajo_forense.md`, mismo patron de anclas que
   `cem_v0_evidencia_forense.md` (`<a id="t1"></a>`...`<a id="t4"></a>`, marcadores `**T1.**`-
   `**T4.**`), nueva fila `T` en `docs/registry/reference_keys.md`. La pieza T4 (Extension: push
   Gate 2) lleva el refutacion-corta reforzado descrito arriba (condicion de disparo explicita),
   las otras 3 (T1-T3) siguen el patron CEM v0 estandar. Ahorro neto estimado sin cambios:
   ~6400 B (cierra el gate Claude, deja Codex en ~1,10x) -- cifra ya validada, no se re-deriva.
2. **Fix `manifest_contracts.md:5`**: cita por encabezado en vez de rango de lineas (evita
   recurrencia del mismo defecto en el proximo movimiento).
3. **Fix `CLOSURE_MODEL.md:46`**: corregir la afirmacion falsa sobre `session_closeout.py`
   (existe, esta vivo, `agent_controller.py:7092-7134` delega `--session-close` a el).
4. **`MANUAL_PUBLICATION_CHECKLIST.md`**: nota de cabecera de documento historico (no reescritura
   completa) + `.loop_bundle_optimizacion.md`: `git rm` (confirmado debris recurrente, cero
   consumidores vivos).

No se implementa nada todavia -- esta propuesta es el objeto de revision del bucle adversarial
de la seccion siguiente, ANTES de que cualquier cambio aterrice (mismo orden que CEM v0 RONDA 1:
diseno -> bucle -> solo entonces implementacion).

## Bucle adversarial RONDA 4 (`EXPLORATORY-wot-026t-split-y-fixes-20261022`, DESIGN_REVIEW, resultado real)

Roster pedido (9, mismo que RONDA 3): `challenger_codex`, `challenger_opencode_glm_5_2`,
`challenger_nan_deepseek_flash`, `challenger_nan_qwen_flash`, `challenger_gemini_gemini`,
`challenger_mistral`, `challenger_nvidia_kimi`, `challenger_llm7_minimax`,
`challenger_cohere_command`. `task_type: prose`, sin commit-sha/nonce (exploratorio, mismo
precedente que RONDA 1/3). `project_root` del destino (`orquestador_de_agentes_workspace`).

**9/9 respondieron con contenido sustantivo.** De esas 9, **3 cayeron en sustitucion automatica
por `proposer_claude` (BA01)** tras agotar su cadena de fallback (`gemini_gemini` -> BA01,
`nvidia_kimi` -> BA01, `nan_qwen_flash` -> `groq_qwen` -> BA01): por definicion del contrato
(Seccion 4 de `ensemble_loop.md`, "no es sustitucion por BA01"), esas 3 NO cuentan como lentes
independientes, aunque su contenido se cita abajo como senal adicional (converge con el resto).
`nan_deepseek_flash` tambien cayo en fallback dos veces pero aterrizo en un backend_key DISTINTO
(`BA07`, kilo_deepseek_flash) -- SI cuenta, por definicion del contrato. **6 lentes
independientes contadas**: `codex` (BA05), `opencode_glm_5_2` (BA06, nota: perfil legacy,
sustituido por `challenger_opencode_glm_flash` en seleccion automatica, pero invocable por
nombre -- y esta vez SI respondio, rompiendo la racha de 3 fallos consecutivos del bug
`external_directory` de rondas anteriores), `kilo_deepseek_flash` (BA07, via fallback),
`mistral` (BA150), `llm7_minimax` (BA172, degenerado en bucle de repeticion tras su analisis
inicial -- ver nota abajo), `cohere_command` (BA130). Bien por encima del minimo de 2-3
(`documentation`/`analysis`) que exige `check_loop_execution.min_distinct_for`.

### Veredicto por punto (consolidado de las 6 lentes independientes + 3 senales BA01)

**1. T1/T2 -- criterio CEM v0 bien aplicado, con una condicion que NINGUNA lente omitio:**
unanimidad (9/9, incluidas las 3 BA01) en que el patron esta bien aplicado, PERO casi todas
(codex, opencode/glm, gemini[BA01], kimi[BA01], deepseek-via-BA07) senalaron **independientemente**
que la frase corta que queda en AGENTS.md debe conservar explicitamente una clausula que el
diseno original trataba como "contexto": para T1, la clausula de MECANISMO ("`-k` selecciona por
nombre de clase/fichero, no por grafo de call-sites" -- sin ella la regla es un imperativo sin
razon verificable, deepseek-BA07); para T2, la clausula de ALCANCE NEGATIVO ("NO toca
`run_gates_dispatch.py` ni `builder-run-quality-gates`" -- sin ella el riesgo es sobregeneralizar
la regla fuera del protocolo trio, exactamente el incidente WOT-2026-104j que T2 documenta).
**Hallazgo nuevo no estaba en la propuesta:** `check_reference_keys.py` valida que `[T1]`/`[T2]`
resuelven a un ancla, NUNCA que la frase RETENIDA sea semanticamente suficiente -- el guard da una
falsa garantia de "split correcto" que no cubre esto (deepseek-BA07). No hay guard mecanico
posible para eso: la revision humana de las 4 frases retenidas queda como criterio de aceptacion
explicito del ticket, no delegable al guard.

**2. T4 (Gate 2) -- MAYORIA FUERTE contra mover el 100% al modulo, con matices distintos cada
lente, NO un copy-paste de la misma objecion:**

| Lente | Veredicto T4 |
|---|---|
| codex (independiente) | NO mover integro; dejar especificacion minima fail-closed en AGENTS.md, migrar solo desarrollo |
| opencode/glm (independiente) | NO mover; T4 es "norma disparada por evento", el puntero no cubre el modo de fallo ("nunca forma la intencion de abrir el modulo") |
| kilo_deepseek_flash/BA07 (independiente) | Mover ES posible, pero SOLO con (a) default-deny explicito en la linea siempre cargada y (b) checklist comprimida de las 5 condiciones en AGENTS.md, no solo puntero -- y (c) el destino correcto NO es el modulo forense nuevo, es `flight_push_policy.md` (Gate 2 es la continuacion natural de Gate 1, que ya vive ahi) |
| mistral (independiente) | NO mover; mantener T4 integro en AGENTS.md "aunque supere el limite de bytes" |
| minimax (independiente, degenerado tras el analisis) | Antes de degenerar: NO mover, mismo argumento de "el puntero no es la regla" |
| cohere (independiente) | UNICO EN DESACUERDO: mitigacion SUFICIENTE, el puntero + guard de existencia del modulo basta |
| gemini (BA01, no cuenta) | NO mover integro; separar las 5 condiciones de rechazo (quedan) del riesgo residual (migra) |
| kimi (BA01, no cuenta) | NO mover integro; mismo argumento, "tabla de decision, no una norma" |
| nan_qwen->BA01 (no cuenta) | NO mover integro si el ahorro de T4 es indispensable, al menos el criterio de rechazo se queda inline |

**Disenso real y declarado, no suavizado:** `cohere_command` es la UNICA lente (de 6
independientes) que aprueba el puntero reforzado tal cual. Su razonamiento ("no hay evidencia en
el repo de que un agente haya ignorado un puntero en un momento de decision") es circular -- la
ausencia de un incidente documentado de ESTE puntero especifico (que no existe todavia) no es
evidencia de que sea seguro. Las otras 5 lentes independientes citan el incidente WOT-2026-104j
(documentado en el propio bloque T2 del bundle) como prueba de que SI ocurre exactamente ese modo
de fallo (agente que actua sin consultar la asignacion explicita) cuando la informacion no esta
en la linea siempre cargada.

**La propuesta tecnica mas accionable y la unica que ofrece un camino intermedio verificable** es
la de `kilo_deepseek_flash`/BA07: default-deny explicito + checklist comprimida de 5 condiciones
(~400-500 B, no 3473 B) en AGENTS.md + destino real = `flight_push_policy.md` (no el modulo
forense nuevo, para no crear una SEGUNDA sede de la politica de push junto a Gate 1). Esta misma
lente senalo ademas un error de categoria en el diseno original: mezclar T1/T2 (evidencia
historica) con T3/T4 (politica operativa viva) en el MISMO fichero `*_evidencia_forense.md` es
inconsistente con el proposito declarado de ese patron de modulo (igual que CEM v0, que es
puramente forense). T3 y T4 pertenecen a `flight_push_policy.md`, no a un modulo forense nuevo.

**3. Riesgos no nombrados en fixes 5-8 (hallazgos nuevos, no repetidos de la propuesta):**
- Fix 5: una cita por encabezado deja de ser machine-checkable (una cita por rango de linea SI lo
  era); alternativa superior citada por 2 lentes independientes: conservar el rango de linea
  ADEMAS del heading esperado, y que `check_reference_keys.py` valide que el rango contiene ese
  heading (deepseek-BA07). Tambien: no esta claro si el guard sabe validar citas por encabezado o
  solo por rango (nan_qwen->BA01, aunque esta no cuenta como independiente, el punto es valido y
  verificable por su cuenta).
- Fix 6: ambiguedad motor-vs-destino en la cita de evidencia (`_MOTOR_ROOT`) -- "el fichero
  existe" prueba el motor, no necesariamente lo que `CLOSURE_MODEL.md` describe si ese documento
  habla del destino (deepseek-BA07, NO VERIFICABLE declarado explicitamente). Ademas: borrar la
  frase falsa sin sustituirla por la verdad deja un hueco documental nuevo (varias lentes).
- Fix 7: marcar "historico" sin nombrar el sucesor (`flight_push_policy.md`) ni tocar los
  "inbound links" deja vivo el riesgo que se queria matar -- un agente que llega por enlace sigue
  leyendo la premisa falsa (codex, deepseek-BA07, kimi-BA01, converge independientemente).
- Fix 8: el riesgo real no es el borrado, es que NO ES DURABLE -- el patron que creo el fichero
  (bucle que hace `git add -A`) sigue vivo; sin `.gitignore` o un check en pre-commit
  (`delivery_hygiene_check.py` es el sitio natural), el fichero puede reaparecer (deepseek-BA07,
  hallazgo no estaba en la propuesta original).
- **Riesgo transversal nuevo, no nombrado en la propuesta:** si el modulo de referencia nuevo
  vive bajo cualquier cadena always-loaded (`@import`, un glob de `rules/`), el "ahorro" es cero
  -- precondicion dura no verificada todavia (deepseek-BA07).
- **Riesgo de secuenciacion nuevo:** los 8 cambios deben aterrizar en UN solo commit antes de la
  suite canonica (la regla "la suite es el ultimo paso" de este MISMO ticket invalida cualquier
  commit posterior) -- partirlos en commits incrementales paga ~7 min de re-corrida por cada uno
  (deepseek-BA07).

**4. Calculo de ahorro neto -- la correccion mas importante de toda la ronda:** multiples lentes
independientes (codex, mistral, deepseek-BA07) calculan, con las mismas 4 piezas pegadas en el
bundle, que **incluso con el ahorro OPTIMISTA de ~6400 B completo (moviendo T4 integro), el gate
Codex queda en ROJO: 36157 B vs limite 32768 B = deficit 3389 B, ratio 1,10x.** El informe previo
de esta misma seccion presentaba "~1,10x" como si fuera un cierre o casi-cierre; es un gate que
SIGUE FALLANDO. Y si se aplica el veredicto mayoritario del punto 2 (T4 NO se mueve integro, solo
una fraccion pequena), el ahorro real cae por debajo de los 6400 B estimados y el deficit Codex
es MAYOR que 3389 B. **Conclusion: ni siquiera en el escenario mas favorable (mover T4 entero,
que la mayoria de lentes desaconseja) este ticket cierra el gate Codex por si solo.**

### Recomendacion final (no implementado en esta ronda)

1. **T1/T2: proceder con el split, con las clausulas de mecanismo/alcance retenidas
   explicitamente** en la frase corta (no delegadas al modulo) -- cambio de bajo riesgo,
   consenso fuerte, correccion barata (~100-150 B extra por pieza, no afecta el veredicto).
2. **T3: proceder** (recorte de duplicado confirmado, sin disenso).
3. **T4: NO proceder con el split integro tal como esta propuesto.** Si se quiere perseguir el
   ahorro de bytes de todas formas, la ruta que sobrevive la revision es la de `kilo_deepseek_flash`:
   default-deny explicito + checklist comprimida de las 5 condiciones (no el texto completo) +
   destino `flight_push_policy.md` (no un modulo forense nuevo) -- pero esto es un diseno NUEVO,
   no el que se reviso en esta ronda, y necesitaria su propia ronda de revision antes de
   implementarse.
4. **Fixes 5-8: proceder, con las correcciones senaladas** (cita por heading+rango en vez de solo
   heading; afirmar la verdad en CLOSURE_MODEL.md en vez de solo borrar la frase falsa y declarar
   explicitamente motor-vs-destino; nombrar el sucesor en MANUAL_PUBLICATION_CHECKLIST.md;
   `.gitignore`/pre-commit check para que el fix 8 sea durable).
5. **El gate Codex NO se cierra con este ticket**, ni en el escenario optimista. Declarar
   explicitamente ese resultado (no presentarlo como cierre parcial silencioso) y abrir una
   SEGUNDA medicion Fase 0 sobre el resto de AGENTS.md para identificar la siguiente candidata,
   una vez este ticket aterrice.

No se implementa nada en este documento -- queda para que el usuario decida si abre el ticket
con el alcance reducido (T1+T2+T3+fixes, sin T4 integro) y si persigue el diseno alternativo de
T4 en una ronda de revision separada.
