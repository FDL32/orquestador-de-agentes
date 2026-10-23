# Propuesta de optimizacion: split quirurgico de CEM v0 + convencion de claves de referencia

> Documento de DISENO. Read-only sobre codigo: no implementa nada. Entrada para el bucle
> adversarial DESIGN_REVIEW que lo sigue.

contract_id: cid-propuesta-cem-v0-claves-referencia-v1

## ESTADO_FRESCO

    ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022, HEAD=426a2ef52aa1cb4c4bce0e5f3c47bd320ca57139, dirty=0, verificado=2026-10-22T10:53Z

## 1. Nueva pasada sobre toda la informacion reunida: errores encontrados

1. **`docs/registry/README.md:80`** (tabla mantenida a mano, no autogenerada): sigue listando
   `hermes_soul.md` como "Pieza singular (backend externo)". Stale desde WOT-2026-114b (retiro
   Hermes). La regeneracion automatica de `INDEX.md`/`ROUTER.md` en ese ticket NO toco esta
   tabla porque es prosa manual, no derivada por `discover_skills.py`.
2. **`docs/decisions/DEC-router-prompts-001-taxonomia-y-metadatos.md`** (linea ~169, segun cita
   de Fase 0R): tambien menciona `hermes_soul` como ejemplo de prompt "externo". Stale por el
   mismo motivo.
3. **`docs/followups/palanca-a-raiz-agents-md-diseno.md:249`** (**R3** de su propia lista de
   riesgos): "Hermes es el unico consumidor con extraccion por encabezado..." -- esta premisa
   YA NO ES CIERTA desde WOT-2026-114b. El riesgo R3 original (perder cobertura de ese censo si
   no se re-ejecuta) queda resuelto de otra forma: Hermes ya no existe, asi que no hay nada que
   perder por ese lado. Util anotarlo para que un lector no reabra un riesgo ya cerrado por una
   via distinta a la que el diseno previo.
4. **No es un error, es un hallazgo ya documentado y sin resolver (no nuevo en esta pasada):**
   `.agent/rules/common/sustainable_engineering.md` sigue duplicando el bloque CEM v0 de forma
   verbatim/parcial (confirmado: `grep -c "Criterio invariante" .agent/rules/common/
   sustainable_engineering.md` -> 1). Si este ticket mueve parte de CEM v0 a un modulo nuevo,
   esa duplicacion preexistente queda a su vez potencialmente desincronizada con la nueva
   cuspide. Se declara como alcance a verificar en el PASO 4 del propio movimiento (before/after
   de ese fichero tambien, no solo de los consumidores programaticos), no a resolver aqui de
   forma independiente.

Ninguno de estos 4 puntos bloquea nada; son correcciones de higiene documental baratas, ademas
del movimiento principal de la Seccion 2.

## 2. Decision sobre CEM v0 (investigacion ya reportada al usuario)

Confirmado por lectura linea a linea de `AGENTS.md:368-399` (11.328 B): la seccion es una
MEZCLA, no refutacion pura:

- **Grupo A (principios de una linea, ~6 bullets):** ya concentrados, sin beneficio neto de
  moverlos (mismo patron que las "14 pequenas" que Fase 0R ya descarto para el resto del
  fichero).
- **Grupo B (~6 bullets, el grueso de los bytes, ~5.000-6.000 B):** cada uno tiene una frase de
  refutacion corta (PASO 2 fila #1, SIEMPRE se queda, 1-2 lineas) seguida de un caso forense
  extenso (fechas, tickets WOT, cifras -- PASO 2 fila #5, "justificacion forense: MUEVE").

**Decision propuesta:** ejecutar el split quirurgico -- separar cada bullet del Grupo B en (a)
la frase de refutacion, que se queda en `AGENTS.md` con un puntero corto, y (b) el caso forense
completo, que se muda a un modulo de referencia nuevo. Riesgo mas alto que el movimiento de
Vocabulario canonico (WOT-2026-114c): hay que verificar, bullet a bullet, que la frase de
refutacion no pierde fuerza sin su caso adyacente (PASO 3(c) de `doc_optimization.md`).

## 3. Propuesta del usuario: convencion de claves de referencia (`R1`, `U1`, ...)

El usuario propone no repetir una etiqueta generica `<referencia>` en cada puntero, sino un
INDICE con clave corta: letra = fichero, numero = fila/entrada dentro de ese fichero (p.ej.
`R3` = fila 3 del fichero cuyo prefijo es `R`).

### 3.1 Verificacion contra precedente del propio motor (T13 de `CONSTITUTION.md`: "antes de
incorporar algo nuevo, verificar si ya existe algo que ampliar")

- **Precedente que SI aplica -- YA EXISTE la forma, sin formalizar:** `docs/followups/
  palanca-a-raiz-agents-md-diseno.md` ya usa `E1`-`E8` (Equivalencias) y `R1`-`R5` (Riesgos)
  como claves numeradas DENTRO de un mismo fichero. `CONSTITUTION.md` usa `T1`-`T15` (Tenets)
  igual. La propuesta del usuario es la generalizacion natural de un patron que el propio motor
  ya usa, extendido para apuntar ENTRE ficheros (letra selecciona el fichero, no solo la fila).
- **Precedente que NO aplica igual, pero advierte del riesgo real -- `DEC-008B-001-registry-
  model.md`, CORREGIDO tras revision de Codex (ver Seccion 6): mi primera version de este
  documento atribuyo el rechazo a `DEC-router-prompts-001`, pero ese fichero solo ENLAZA a
  `DEC-008B-001` como "decision relacionada" (`DEC-router-prompts-001...md:148-150`). El DEC
  que de verdad evaluo y RECHAZO introducir un `registry.json`/manifest autoritativo SEPARADO
  es `DEC-008B-001`, citado directamente en `docs/registry/README.md:4` ("Decision vinculante")
  y `:7-9` ("introducir una segunda fuente de verdad fue evaluado y rechazado... un registry
  incorrecto es peor que no tener"). El motivo: un indice derivado que NADIE regenera
  automaticamente diverge en silencio de la fuente real.
  **Esto es una advertencia real a incorporar, no un bloqueo:** la forma que el DEC rechazo era
  un catalogo RICO (kind/path/status/owner) mantenido aparte de sus fuentes. La propuesta del
  usuario es mucho mas DELGADA (una leyenda de pocas entradas letra->fichero, mas anclas
  numeradas DENTRO de cada fichero de referencia, que no son "una segunda fuente" sino la
  numeracion natural de una lista ya existente). No es el mismo riesgo, pero SI hereda una
  version mas pequena del mismo riesgo: una clave citada en `AGENTS.md` (`ver R3`) puede
  desincronizarse si el fichero `R` renumera sus filas sin que nadie actualice la cita.

### 3.2 Recomendacion: adoptar la idea, con una barrera mecanica, no solo convencion

1. **Leyenda minima, un solo lugar** (p.ej. nueva tabla en `docs/registry/README.md` o fichero
   dedicado `docs/registry/reference_keys.md`): `letra -> ruta del fichero`. Pocas entradas
   (una por fichero de referencia que use el esquema), bajo riesgo de deriva por su propio
   tamano pequeno.
2. **Las filas NO son una segunda fuente de verdad:** son la numeracion INLINE de una lista que
   de todos modos iba a existir en el fichero de referencia (`**R3.** <texto del caso>`). No se
   mantiene un indice de contenidos separado del propio fichero -- resolver `R3` es "abre el
   fichero mapeado a `R`, busca `R3.` con grep/ctrl-F", cero duplicacion de contenido.
3. **Barrera mecanica (nueva, cablear en el MISMO commit que adopte el esquema, por la regla de
   `AGENTS.md` "el guard que crees se cablea en el mismo commit"):** un script
   (`scripts/check_reference_keys.py`) que censa toda cita `\b[A-Z][0-9]+\b` dentro de un
   contexto de puntero (p.ej. precedida de "ver" o entre backticks) en `AGENTS.md` y los
   ficheros `.agent/rules/common/*.md`, resuelve la letra contra la leyenda, y falla si:
   - la letra no esta en la leyenda;
   - el numero no existe como ancla (`**<clave>.**`) en el fichero mapeado.
   Esto evita exactamente el riesgo que `DEC-router-prompts-001` señalo (indice que diverge en
   silencio): aqui la divergencia SI se detecta, porque el guard la busca activamente.
4. **Alcance de esta primera adopcion: SOLO los punteros nuevos que genere el split de CEM v0**
   (Seccion 2). No retrofitear los `E1`-`E8`/`R1`-`R5`/`T1`-`T15` existentes a este esquema en
   este mismo ticket -- son ad hoc DENTRO de un unico fichero, nunca apuntan desde fuera, y
   retrofitearlos es un cambio de alcance mayor y separado.

### 3.3 Respuesta directa a la pregunta del usuario

La idea es buena y coherente con un patron que el propio motor ya usa de forma informal (E/R/T
numerados). El riesgo real que vale la pena nombrar es el mismo que ya evito el motor con
`DEC-router-prompts-001`: un indice que nadie valida diverge solo. La diferencia que hace esta
version SEGURA es que (a) es mucho mas delgada que lo que ese DEC rechazo, y (b) se cablea con
un guard desde el primer commit, en vez de confiar en que alguien se acuerde de mantenerla (CEM:
"barrera cableada" sobre "norma").

## 4. Propuesta de optimizacion consolidada

1. Fix de higiene documental: corregir los 3 puntos de la Seccion 1 (referencias stale a
   Hermes en `docs/registry/README.md`, `DEC-router-prompts-001...md`, y anotar R3 de
   `palanca-a-raiz-agents-md-diseno.md` como resuelto por otra via).
2. Crear `.agent/rules/common/cem_v0_evidencia_forense.md` con los casos forenses del Grupo B
   de CEM v0, numerados `F1`-`F6` (o el prefijo que se decida), y la leyenda minima en
   `docs/registry/`.
3. Cablear `scripts/check_reference_keys.py` en el MISMO commit que introduce las primeras
   claves `F1`-`F6`.
4. Ejecutar el split quirurgico de CEM v0 en `AGENTS.md`: cada bullet del Grupo B se reduce a
   su frase de refutacion + puntero `(ver F<n>)`.
5. Medir ambos gates antes/despues (igual que en los 3 tickets anteriores) y declarar el estado
   final -- probablemente NO cierra ningun gate por si solo (estimado ~1,30x Codex), pero reduce
   mas el margen. Declarar PASO 5 (deuda) para el resto, con numeros frescos.

## 5. Bucle adversarial (RONDA 1, ya ejecutada)

Roster pedido: `challenger_codex` (agent), `challenger_opencode_glm_5_2` (agent),
`challenger_nan_deepseek_flash` (api), `challenger_nan_qwen_flash` (api),
`challenger_gemini_gemini` (api), `challenger_mistral` (api), `challenger_cohere_command` (api).
`loop_id: EXPLORATORY-cem-v0-claves-referencia-20261022`, fase `DESIGN_REVIEW`, sin
commit/nonce.

**Resultado real (no fabricado):** las 5 lentes `api` fueron bloqueadas por
`privacy_preflight_blocked` (el `ESTADO_FRESCO` del bundle incluye el SHA de `HEAD`, un string
de 40+ caracteres hexadecimales que el detector de entropia confundio con un secreto -- falso
positivo conocido de los scanners basados en entropia sobre hashes de git). Las 2 lentes
`agent` (codex, opencode/glm) SI respondieron:

- **Codex:** `CHANGES` real y util -- encontro el error de atribucion del DEC (ya corregido en
  la Seccion 3.1 arriba) y 4 huecos concretos en la especificacion del guard (Seccion 6).
- **Opencode/glm:** bloqueado de nuevo (2/2 veces ya en este vuelo) por el mismo bug de
  `external_directory` con el orden de reglas invertido -- declaro todo `NO VERIFICABLE` de
  forma honesta en vez de inventar un veredicto. Defecto de infraestructura reproducible,
  ajeno a esta propuesta; se documenta como hallazgo operativo, no se arregla en este ticket.

## 6. Guard refinado tras el feedback real de Codex (RONDA 1)

Los 4 huecos que Codex senalo, resueltos:

1. **Regex puede matchear dentro de bloques de codigo:** el scanner excluye explicitamente
   todo contenido entre lineas ` ``` ` (fenced code blocks) antes de buscar citas o anclas,
   tanto en el fichero que cita como en el fichero de referencia.
2. **"Contexto de puntero" (precedida de 'ver' o backticks) no es un parser preciso:** se
   sustituye por UN SOLO formato literal, sin ambiguedad: la cita es exactamente
   `(ver <LETRA><NUMERO>)`, p.ej. `(ver F3)`. Regex: `\(ver ([A-Z]\d+)\)`. Nada que empiece de
   otra forma cuenta como cita -- elimina el caso borde de "una mencion casual de la clave en
   prosa libre".
3. **Listas anidadas, encabezados, tablas:** la ANCLA (el destino de la cita, dentro del
   fichero de referencia) tiene el mismo tratamiento estricto: debe ser una linea que empiece
   (tras espacio opcional) con `**<LETRA><NUMERO>.**` literal, p.ej. `**F3.** <texto del caso>`.
   Regex: `^\s*\*\*([A-Z])(\d+)\.\*\*`. No se reconoce ninguna otra forma (no cuenta un
   encabezado `### F3`, no cuenta una celda de tabla) -- un formato unico y verificable.
4. **Duplicados/renumeraciones:** el guard falla si (a) una cita `(ver X#)` no tiene ninguna
   ancla `**X#.**` en el fichero mapeado a `X` en la leyenda (cita huerfana), o (b) el fichero
   de referencia tiene MAS DE UNA ancla con la misma clave `X#` (ancla duplicada, ambiguedad de
   destino). NO falla si una ancla existe sin ninguna cita todavia (contenido de referencia
   preparado para citarse despues es legitimo, solo WARN opcional, nunca bloqueante).

**Leyenda minima** (`docs/registry/reference_keys.md`, fichero nuevo, pocas filas):
`| letra | fichero |` -- una fila por fichero de referencia que adopte el esquema. El guard
tambien falla si una letra de la leyenda apunta a un fichero que no existe.

**Alcance de validacion:** el guard escanea citas en `AGENTS.md` + `.agent/rules/common/*.md`
(los ficheros `citado-obligatorio`/`referencia-bajo-demanda` del motor); las anclas se
verifican dentro de cada fichero que la leyenda mapea. Se cablea en el MISMO commit que
introduce las primeras claves `F1`-`F6` (pre-commit, mismo patron que `check_guard_wiring.py`).

### 6.1 Ronda 2 del bucle: 4 puntos adicionales de Codex, resueltos o declarados non-goal

1. **Variantes de fence (` ``` ` vs `~~~`, longitud variable):** el detector de bloques de
   codigo reconoce AMBOS delimitadores (regex de apertura/cierre: `^(\`{3,}|~{3,})`, empareja
   por el mismo caracter y longitud >= la de apertura, igual que el parser de Markdown
   estandar -- no una deteccion ad hoc solo de ` ``` ` literal).
2. **El regex de ancla puede matchear texto en negrita que no es una ancla real** (p.ej.
   `**X3.** importante` usado como enfasis, no como referencia): se acepta como limitacion
   conocida, NON-GOAL -- distinguir intencion semantica de un patron mecanico no es el trabajo
   de un guard de sintaxis. Mitigacion suficiente: el prefijo de letra+numero de este esquema
   (`F`, `R`, `E`...) se reserva por convencion para claves de referencia, nunca para enfasis
   editorial -- se declara en la leyenda como regla de estilo, no se fuerza por codigo.
3. **Deriva semantica (la cita apunta a un ancla que existe pero ya no es el caso correcto
   tras una renumeracion, o la leyenda apunta a un fichero existente pero conceptualmente
   distinto):** NON-GOAL declarado. Un guard mecanico verifica SINTAXIS (?existe la ancla?
   ?es unica?), nunca SEMANTICA (?sigue siendo el caso correcto?) -- eso exige revision humana
   o de Revisor en cada PR que toque un fichero de referencia, igual que cualquier otro cambio
   de contenido. Se documenta como riesgo residual aceptado, no como hueco del guard.
4. **Alcance limitado a `AGENTS.md` + `.agent/rules/common/*.md`:** se mantiene para esta
   PRIMERA adopcion (Seccion 3.2 punto 4, sin cambios) -- extender el escaneo a otras clases
   `citado-obligatorio`/`referencia-bajo-demanda` (p.ej. `CONSTITUTION.md`) es una decision de
   adopcion FUTURA, fuera de alcance de este ticket, que solo introduce las primeras 6 claves.

## 7. Pasada post-WOT-2026-114e: hallazgos y propuesta

WOT-2026-114e (264830ad) acorto la cita de `(ver F1)` a `[F1]` y anadio anclas HTML
navegables (`<a id="f1"></a>`) en `cem_v0_evidencia_forense.md` y un enlace markdown real en
la leyenda. Nueva pasada sobre el estado resultante:

1. **Regex del guard sigue siendo exacto tras el cambio de formato:** `_CITATION_RE = \[([A-Z]\d+)\]`
   censado contra `AGENTS.md` + `.agent/rules/common/*.md` solo matchea las 9 citas reales
   (`[F1]`..`[F7]`, con F1 y F7 repetidos en el resumen de linea 393) -- cero falsos positivos
   de otros patrones `[LETRA+digitos]` en el alcance de citas (verificado por censo literal).
2. **Hallazgo real, ya corregido en este mismo pase:** `.pre-commit-config.yaml:387-393`
   (comentario + `name:` del hook `check-reference-keys`) seguia citando el formato VIEJO
   `(ver X#)`, aunque el guard ya validaba `[X#]` desde 264830ad -- la salida del propio hook en
   consola ("claves (ver X#) resuelven a un ancla") contradecia visualmente el formato real.
   Corregido en el mismo commit que esta seccion: comentario y `name:` ahora dicen `[X#]`, mas
   una linea que fecha el cambio de formato a WOT-2026-114e.
3. **Barrido de `(ver [A-Z]\d+)` fuera de la superficie de citas:** las unicas coincidencias
   restantes son (a) `.agent/runtime/ensemble/bundle_cemv0_api.md` -- artefacto de runtime de la
   RONDA 1, cita textual de la propuesta en el momento en que se envio el bundle, no una fuente
   editable; (b) referencias `(ver I7)`, `(ver D5)`, `(ver R2)`, `(ver D2)` en otros documentos
   (`BUS_PROGRESS_AUDIT_2026-06-02.md`, los dos `DEC-router-*`, `palanca-a-raiz-agents-md-
   diseno.md`) que son numeracion ad hoc DENTRO de un unico fichero, nunca el esquema letra-cruza-
   fichero de este ticket -- confirma la Seccion 3.2 punto 4: no se retrofitean, siguen fuera de
   alcance. (c) El propio `tests/unit/test_check_reference_keys.py:111-120` usa `(ver F9)` a
   proposito como CONTROL NEGATIVO ("formato viejo, ya no es una cita") -- correcto, no stale.
4. **No se encontro ninguna inconsistencia nueva entre lo que la leyenda documenta (Seccion
   "Formato de cita") y lo que el guard aplica** -- ambos coinciden en `[X#]` / `**X#.**` /
   enlace markdown real para la fila de la leyenda.

**Propuesta:** ningun cambio de diseno adicional. El unico defecto real que esta pasada
encontro (el comentario stale de `.pre-commit-config.yaml`) ya esta corregido en este mismo
commit. Se declara el estado como ESTABLE para pasar a la RONDA 3 del bucle adversarial
(Seccion 8) sin cambios pendientes de higiene documental conocidos.

## 8. Bucle adversarial RONDA 3 (post-114e), resultado real

`loop_id: EXPLORATORY-cem-v0-post-114e-20261022`, fase `DESIGN_REVIEW`, `task_type: prose`
(mismo patron que RONDA 1/2 -- `contract-audit` exige nonce+commit-sha, improcedente para una
revision exploratoria sin commit de gobierno), sin nonce ni commit-sha. Dos bundles: uno `api`
(contenido pegado, sin ficheros -- el diff de los 4 cambios de WOT-2026-114e resumido) y uno
`agent` (rutas absolutas del worktree). Roster pedido: `challenger_codex` y
`challenger_opencode_glm_5_2` (agent), `challenger_nan_deepseek_flash` y
`challenger_nan_qwen_flash` (api -- el usuario pidio "con fs" para estos dos, pero el motor
define `nan_api` como canal `api` sin `repo_scope` en `agents.json`: no existe una variante
"nan con filesystem" en este motor, asi que se despacharon como api estandar, con la evidencia
pegada en el bundle en vez de rutas de fichero; se declara aqui en vez de fabricar un modo que
no existe), `challenger_gemini_gemini`, `challenger_mistral`, `challenger_nvidia_kimi`,
`challenger_llm7_minimax`, `challenger_cohere_command` (api).

**Resultado real (no fabricado), 9/9 lentes pedidas respondieron, 0 bloqueadas por
`privacy_preflight_blocked`** (a diferencia de RONDA 1: el bundle de esta ronda no pega ningun
SHA de 40 hex ni token largo, solo fragmentos de regex/codigo y prosa -- evita el disparador de
entropia que bloqueo RONDA 1):

- **7 lentes `api` (deepseek, qwen3.8, gemini, mistral, kimi, minimax, cohere):** las 7
  respondieron de forma sustantiva. Convergencia total en los 3 puntos pedidos: (1) el regex
  `\[([A-Z]\d+)\]` no colisiona con `[^nota]`, `[texto][ref]` ni citas bibliograficas
  multi-letra -- varias lentes (gemini, cohere) senalaron el mismo borde teorico no bloqueante:
  un enlace markdown futuro con la clave como texto visible (`[F1](url)`) matchearia igual,
  mitigado por el censo empirico de 0 falsos positivos; (2) el cambio de la leyenda a enlace
  markdown real es seguro porque solo existe una fila (`F`) y se actualizo atomicamente; (3)
  las 7 lentes confirmaron, releyendo el regex pegado, que `_ANCHOR_RE` no referencia
  `<a id="...">` -- borrar las anclas HTML no afectaria al guard, consistente con la
  declaracion de diseno. **Veredicto expreso:** `nan_qwen_flash` y `cohere` dijeron APPROVE
  explicito; el resto no marco veredicto formal pero no encontro ninguna inconsistencia
  bloqueante. **Dos huecos NO VERIFICABLE senalados** (nan_deepseek, kimi): (a) un censo de
  `[LETRA+digitos]` fuera del alcance declarado, (b) otros consumidores del formato backtick
  viejo de la leyenda. **Verificados por el autor de esta ronda tras el loop** (no por las
  lentes, que no tienen filesystem): `grep -rn '\[[A-Z][0-9]\+\]' --include=*.md --include=*.py
  --include=*.yaml .` fuera de `AGENTS.md`/`.agent/rules/common/*.md` -- cero coincidencias
  reales (el unico match fuera de alcance, `.venv/.../mypy/types.py:3517`, es texto vendored de
  una dependencia, no una cita); `grep -rln "reference_keys.md"` -- los 7 consumidores
  (`cem_v0_evidencia_forense.md`, `bundle_cemv0_api.md` [artefacto de runtime RONDA 1, congelado],
  `.pre-commit-config.yaml`, `AGENTS.md`, este documento, el guard y sus tests) estan todos
  DENTRO del repo y se actualizaron en el mismo commit o son snapshots historicos sin
  pretension de vigencia. Ambos huecos quedan cerrados: cero hallazgo real.
- **`challenger_codex` (agent, destino=worktree del motor):** `APROBAR` ("No se requieren
  cambios"), con lectura real y citas `archivo:linea` -- confirmo las 7 anclas unicas y su
  adyacencia (`cem_v0_evidencia_forense.md:12-13,16-17,19-20,28-29,31-32,34-35,37-38`), ejecuto
  el guard el mismo (`python scripts/check_reference_keys.py` -> `exit 0`), reviso la cobertura
  de tests caso por caso (positivo, cita huerfana, ancla duplicada, control negativo `(ver F9)`,
  fences con backtick y tilde) y confirmo cero restos del formato viejo en el alcance de citas.
- **`challenger_opencode_glm_5_2` (agent):** bloqueada de nuevo (3/3 veces ya en este vuelo
  CEM v0, RONDA 1 + RONDA 2 + RONDA 3) por el mismo bug de permisos `external_directory` --
  declaro **CHANGES dirigido al DESPACHO, no al commit**, registrando explicitamente "nada de
  lo anterior es evidencia en contra del codigo de 264830ad" y proponiendo dos remedios
  (allowlist efectiva o bundle con fragmentos embebidos + log de ejecucion del guard). Esto es
  un defecto de infraestructura reproducible y ya documentado (Seccion 5 de RONDA 1), ajeno a
  esta propuesta; se registra aqui como tercera confirmacion del mismo patron, no se arregla en
  este ticket.

**Conteo de lentes independientes:** 8/9 sustantivas (las 7 api + codex), muy por encima del
minimo de 2 que exige `check_loop_execution.min_distinct_for` para `deliverable_type:
documentation`/`research`. `opencode_glm` cuenta como intento pedido, no como lente
independiente (respuesta no sustantiva por bloqueo de infraestructura, declarada honesta).

**Veredicto consolidado de RONDA 3:** ninguna lente encontro un defecto real en el cambio
264830ad. Los dos huecos NO VERIFICABLE que las lentes `api` senalaron se verificaron
manualmente tras el loop y no revelaron ningun hallazgo. **No hay accion de codigo pendiente.**

**Deuda declarada (no nueva, tercera confirmacion):** el bug de `external_directory` de
`opencode` que impide a esa lente leer el worktree real (WOT-2026-086/el mismo patron citado
en `prompts/ensemble_loop.md`) sigue sin resolverse; no es alcance de este ticket documental,
pero acumula ya 3 rondas consecutivas del mismo vuelo con el mismo sintoma, lo que refuerza el
caso para priorizarlo como ticket de infraestructura propio en una sesion futura.
