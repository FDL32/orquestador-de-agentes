# Informe de medicion Fase 0R -- WOT-2026-112c (RONDA 2 corregida)

Medicion corregida tras revision del Revisor (Codex, backend distinto) y el Manager.
Ronda 1: 3 candidatos movibles. Ronda 2: corregido PASO 2, re-identificado `build_llms.py`
como consumidor programatico que lee AGENTS.md entero (afecta a TODAS las unidades),
corregidas duplicaciones, unidades y clasificaciones.

Fuente JSON: `measure_agents_md_units.py` (Ronda 2, `--json`).

---

## ESTADO_FRESCO

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\palanca-a-continuacion-20261021, HEAD=279d27052890317cb620c94e2b8973b3ca9b6e4a, dirty=0, verificado=2026-10-21T22:23Z
```

Reproducible: `git rev-parse HEAD` -> `279d27052890317cb620c94e2b8973b3ca9b6e4a`, `git status --porcelain -- AGENTS.md CLAUDE.md` -> (vacío).

---

## Tabla PASO 1 -- Gates

| Fichero | Gate | Medida | Limite | Exceso |
|---------|------|--------|--------|--------|
| AGENTS.md (Codex, bytes) | 32768 B | 61370 B = **1,87x** | 32768 B | 28602 B |
| CLAUDE.md + @AGENTS.md (Claude, chars) | 40000 chars | 63292 chars = **1,58x** | 40000 chars | 23292 chars |

Fuente JSON: `units` (medidor), `gates` (cifras de cierre). No estimaciones a mano.

Solo hay un `@import` en CLAUDE.md: `@AGENTS.md` (linea 3). No hay otros import transitivo.

---

## Tabla completa de unidades nivel-2 -- PASO 2

Fila PASO 2: ante match multiple, gana la fila superior.

| # | Linea | Encabezado | Subtree B | Fila PASO 2 | Hermes |
|---|-------|-----------|-----------|-------------|--------|
| 1 | 3 | ## Backends y roles | 3032 | #2 Prohibicion dura | - |
| 2 | 48 | ## Resumen del entorno | 211 | #4 Flags condicionales | - |
| 3 | 55 | ## Rutas importantes | 1023 | #4 Flags condicionales | - |
| 4 | 69 | ## Vocabulario canonico | 13472 | #4 Flags condicionales / #7 Condición | vocabulario_canonico=OK |
| 5 | 249 | ## Contrato de version y portabilidad | 1052 | #4 Flags condicionales | - |
| 6 | 260 | ## MANIFEST.distribute y MANIFEST.workspace | 366 | #4 Flags condicionales | - |
| 7 | 264 | ## Comandos principales | 4159 | #3 Comando operativo | - |
| 8 | 306 | ## Convenciones | 14652 | #4 Flags condicionales (contenedor, 17 B own) | - |
| 9 | 498 | ## Archivado de colaboracion | 416 | #4 Flags condicionales | - |
| 10 | 505 | ## Superficies vivas vs historicas | 197 | #4 Flags condicionales | - |
| 11 | 509 | ## Convenciones de docstrings y testing | 2316 | #3 Comando operativo | - |
| 12 | 534 | ## CEM v0 - Contrato, Evidencia y Memoria | 11329 | #1 Refutacion | cem_v0=OK |
| 13 | 567 | ## Hacer ahora vs aplazar (criterio de decision) | 340 | #1 Refutacion | - |
| 14 | 571 | ## Skills Formales de Proceso | 1519 | #4 Flags condicionales / #7 Condición | - |
| 15 | 589 | ## Atribuciones externas (CREDITS.md) | 191 | #4 Flags condicionales | - |
| 16 | 593 | ## Memoria por proyecto | 1344 | #1 Refutacion | - |
| 17 | 619 | ## deliverable_type (work_plan schema, V2) | 834 | #4 Flags condicionales | - |
| 18 | 636 | ## Quality gates dispatch by deliverable_type | 878 | #4 Flags condicionales | - |
| 19 | 648 | ## Host-first skill precedence & Config Profiles | 479 | #4 Flags condicionales | - |
| 20 | 656 | ## Host setup hook | 435 | #4 Flags condicionales | - |
| 21 | 664 | ## Pluggable manager review rubric by deliverable_type | 455 | #4 Flags condicionales | - |
| 22 | 671 | ## Secretos y seguridad | 1555 | #2 Prohibicion dura | secretos_y_seguridad=OK |
| 23 | 696 | ## Robust Builder Relaunch | 434 | #4 Flags condicionales | - |
| 24 | 704 | ## Criterio de cierre | 638 | #3 Comando operativo | - |

**Correcciones PASO 2 respecto a Ronda 1:**

- **#1 (Backends y roles):** Antes `#4/#7`, ahora `#2 Prohibicion dura`. Contiene prohibiciones duras: `AGENTS.md:16` ("NUNCA el mismo backend/modelo") y `AGENTS.md:43` ("No confundir Builder real con lente de ensemble"). No es #4 puro.
- **#12 (CEM v0):** Antes `#3 Comando operativo`, ahora `#1 Refutacion`. Contiene refutaciones explicitas: "El exit code tras una tuberia MIENTE" (linea 544), "El conflicto entre probes ES el hallazgo" (linea 552). Gana #1 (refutacion) sobre #3 (comando) por regla PASO 2 ("ante match multiple, gana la fila superior").
- **#13 (Hacer ahora vs aplazar):** Antes `#7 Condición`, ahora `#1 Refutacion`. Contiene la frase "El coste de APLAZAR **no es cero**" (linea 569), que es la refutacion misma del criterio. No es #7.
- **#16 (Memoria por proyecto):** Antes `#4/#7`, ahora `#1 Refutacion`. Contiene "--bootstrap entrega un INDICE, no el corpus" (linea 597), refutacion de una creencia erronea. Ademas tiene #3 (comandos canonicos `:601-604`), pero gana #1.

**Nota sobre contenedores vacíos:** `## Convenciones` tiene 17 B own (solo el encabezado); su subtree 14652 B incluye hijas (`###` y `####`). No se evalua como unidad de traslado: sus hijas se evaluan individualmente.

**Nota sobre `## Vocabulario canonico`:** Es contenedor de 4 hijas nivel-3 (Tipos SESION, Modos EJECUCION, Glosario, Distincion). Para PASO 3, se evalua el bloque padre entero porque es la unidad que Hermes extrae. Hijas y nietas de `## Vocabulario canonico` NO se evaluan individualmente.

---

## PASO 3: veredicto para cada unidad nivel-2

### (e) Fallo por registry de extraccion (Hermes) -- 3 unidades

Unidad | #Fila | Condicion | Registros (registry JSON)
-------|-------|-----------|------------------------
## Vocabulario canonico | #4 | FAIL (e) | vocabulario_canonico: 1 match, subtree=13472 B
## CEM v0 | #1 | FAIL (e) | cem_v0: 1 match, subtree=11329 B
## Secretos y seguridad | #2 | FAIL (e) | secretos_y_seguridad: 1 match, subtree=1555 B

**Nota:** No se mueven por (e), independientemente de la fila PASO 2. La unidad #22 es prohibicion dura: se queda por PASO 2 y por (e) tambien falla. La unidad #12 es refutacion: se queda por PASO 3(c) y por (e) ademas.

### (d) Fallo por consumidor programatico -- build_llms.py lee AGENTS.md entero

**`scripts/build_llms.py:123-124`** declara `INLINE_IN_FULL = ["AGENTS.md", ...]` y
**`build_full_block()` (lineas ~198-215)** hace `path.read_text(...)` del fichero
**COMPLETO** de AGENTS.md y lo embebe verbatim en `llms-full.txt`.

Por PASO 3(d) ("Falla si alguno consume el bloque... **o lee el fichero entero**"),
`build_llms.py` hace fallar (d) para **TODAS** las unidades nivel-2 de AGENTS.md,
no solo para bloques especificamente nombrados.

Esto re-evalua la conclusion de la Ronda 1: las 3 unidades que se declaraban
"candidatas movibles" en Ronda 1 (Backends y roles, Memoria por proyecto, Hacer
ahora vs aplazar) tambien fallan PASO 3(d) por este consumidor explicitamente
citado. Verificacion:
```
grep -n "INLINE_IN_FULL" scripts/build_llms.py  -> linea 123: INLINE_IN_FULL = ["AGENTS.md", ...]
sed -n '198,215p' scripts/build_llms.py         -> build_full_block() lee el fichero entero con path.read_text()
```

**Adicionalmente, `.agent/rules/common/sustainable_engineering.md` contiene copias
VERBATIM del bloque CEM v0:** lineas 76-87 (7 reglas copiadas "palabra por palabra"
desde AGENTS.md seccion CEM v0, incluyendo "Criterio invariante, evidencia fechada"
en linea 87 = copia literal desde AGENTS.md:559).

---

## Clasificacion exhaustiva de las 24 unidades nivel-2

Cada unidad en EXACTAMENTE UNA categoria (excluyente, sin solapamiento). Se usa el
motivo de bloqueo PRIMARIO (mas restrictivo): PASO 2 > PASO 3(e) > PASO 3(c) > PASO 3(d).

### 1. Bloqueos PASO 2 (SIEMPRE se quedan) -- 4 unidades

| # | Linea | Encabezado | Fila PASO 2 | Motivo |
|---|-------|-----------|-------------|--------|
| 1 | 3 | ## Backends y roles | #2 Prohibicion dura | "NUNCA el mismo backend/modelo" (:16), "No confundir Builder real con lente de ensemble" (:43) |
| 22 | 671 | ## Secretos y seguridad | #2 Prohibicion dura | Prohibicion dura (se queda SIEMPRE) |
| 11 | 509 | ## Conv. docstrings y testing | #3 Comando operativo | Comando operativo (se queda SIEMPRE) |
| 24 | 704 | ## Criterio de cierre | #3 Comando operativo | Comando operativo (se queda SIEMPRE) |

### 2. Bloqueos PASO 3(e) (Hermes registry) -- 2 unidades

| # | Linea | Encabezado | Motivo |
|---|-------|-----------|--------|
| 4 | 69 | ## Vocabulario canonico | Extraido por Hermes (`vocabulario_canonico` registry) |
| 12 | 534 | ## CEM v0 - Contrato, Evidencia y Memoria | Extraido por Hermes (`cem_v0` registry) + duplicacion en `sustainable_engineering.md` |

### 3. Bloqueos PASO 3(c) (contienen refutacion) -- 2 unidades

| # | Linea | Encabezado | Refutacion contenida |
|---|-------|-----------|---------------------|
| 13 | 567 | ## Hacer ahora vs aplazar | "El coste de APLAZAR **no es cero**" (:569) -- es la refutacion misma del criterio. Gana PASO 2 fila #1. |
| 16 | 593 | ## Memoria por proyecto | "--bootstrap entrega un INDICE, no el corpus" (:597) -- refutacion de creencia erronea. Gana PASO 2 fila #1. |

### 4. Bloqueos PASO 3(d) (consumidor programatico) -- 1 unidad

| # | Linea | Encabezado | Tamaño | Consumidor |
|---|-------|-----------|--------|------------|
| 7 | 264 | ## Comandos principales | 4159 B | `build_llms.py` lee AGENTS.md entero (todos fallan 3d, este es el unico >=1600 B que no cae en categorias anteriores) |

**Nota:** `build_llms.py` falla PASO 3(d) para TODAS las unidades. Esta categoria
muestra solo las que no caen en categorias previas. El efecto de `build_llms.py`
es universal: ninguna unidad pasa 3(d) por si sola.

### 5. Pequeñas (own_bytes < 1600, overhead > beneficio) -- 14 unidades

Todas fallan PASO 3(d) por `build_llms.py` y ademas, aun si no fuera por (d), el
overhead de crear un puntero de referencia (nota, enlace, mantenimiento) supera
el beneficio neto de extraccion.

| # | Linea | Encabezado | own_bytes | Fila PASO 2 |
|---|-------|-----------|-----------|-------------|
| 2 | 48 | ## Resumen del entorno | 211 | #4 |
| 3 | 55 | ## Rutas importantes | 1023 | #4 |
| 5 | 249 | ## Contrato de version y portabilidad | 1052 | #4 |
| 6 | 260 | ## MANIFEST.distribute y MANIFEST.workspace | 366 | #4 |
| 9 | 498 | ## Archivado de colaboracion | 416 | #4 |
| 10 | 505 | ## Superficies vivas vs historicas | 197 | #4 |
| 14 | 571 | ## Skills Formales de Proceso | 871 | #4/#7 |
| 15 | 589 | ## Atribuciones externas (CREDITS.md) | 191 | #4 |
| 17 | 619 | ## deliverable_type (work_plan schema, V2) | 536 | #4 |
| 18 | 636 | ## Quality gates dispatch by deliverable_type | 878 | #4 |
| 19 | 648 | ## Host-first skill precedence & Config Profiles | 479 | #4 |
| 20 | 656 | ## Host setup hook | 435 | #4 |
| 21 | 664 | ## Pluggable manager review rubric by deliverable_type | 455 | #4 |
| 23 | 696 | ## Robust Builder Relaunch | 434 | #4 |

**Suma own_bytes de las 14 pequenas: 7544 B** (corregido; una version previa decia 6731 B).

### 6. Contenedor vacio -- 1 unidad

| # | Linea | Encabezado | own_bytes | subtree |
|---|-------|-----------|-----------|---------|
| 8 | 306 | ## Convenciones | 17 | 14652 (hijas evaluadas individualmente) |

---

## Resumen de veredicto

### Veredicto final: SIN CANDIDATO MOVIBLE

No hay ninguna unidad nivel-2 que pase PASO 3 completo. La causa raiz es que
`build_llms.py` (línea 123-124) declara `AGENTS.md` en `INLINE_IN_FULL` y lee
el fichero entero en `build_full_block()` (línea 198-215), lo que hace fallar
PASO 3(d) para TODAS las unidades.

Adicionalmente, las 3 unidades que la Ronda 1 declaraba "movibles" fallan por
razones adicionales:

| Unidad | Falla 3(d) | Falla 3(c) | Falla PASO 2 | Motivo principal |
|--------|-----------|-----------|-------------|-----------------|
| ## Backends y roles | SI (build_llms.py) | - | SI (#2 Prohibicion) | PASO 2 prohibicion dura |
| ## Memoria por proyecto | SI (build_llms.py) | SI (refutacion :597) | SI (#1 Refutacion) | PASO 2 refutacion |
| ## Hacer ahora vs aplazar | SI (build_llms.py) | SI (refutacion :569) | SI (#1 Refutacion) | PASO 2 refutacion |

### Censo de duplicacion por contenido

**CEM v0 -- DUPLICACION CONFIRMADA**

`.agent/rules/common/sustainable_engineering.md` (lineas 76-87): 7 reglas copiadas
verbatim desde AGENTS.md CEM v0, incluyendo linea 87 = copia literal de AGENTS.md:559
("Criterio invariante, evidencia fechada").

**Push por vuelo -- DUPLICACION CONFIRMADA; Extension: push -- PARCIAL (corregido)**

`.agent/rules/common/flight_push_policy.md` (30 lineas):
- Lineas 1-26: "Push por vuelo" duplicado completamente (942 chars de coincidencia).
- Linea 27-30: Solo el encabezado "Extension: push" + 2 lineas de Gate 1 (95 chars de
  coincidencia). **NO se reproduce el desarrollo completo de Gate 2** (AGENTS.md:394-435).
  Correccion respecto a Ronda 1: solo "Push por vuelo" esta completamente duplicado;
  "Extension: push" tiene coincidencia solo en encabezado y Gate 1.

**Backends y roles -- sin duplicacion en rules**

No se encontro copia verbatim del bloque completo en `.agent/rules/common/`.
Solo se citan terminos individuales (`repo_motor`, `repo_destino`).

**Memoria por proyecto -- DUPLICACION CONFIRMADA**

`.agent/rules/common/memory_hierarchy.md` contiene copia casi-verbatim de parte de
"Memoria por proyecto": coincidencia contigua de 264 chars (longest match `difflib`),
mas otras 8+ coincidencias menores (74 chars sobre `--recall` EXPANSION, 82 chars
sobre `memory_context.py --recall`, 116 chars sobre `fail-closed`).

**Hacer ahora vs aplazar -- DUPLICACION CONFIRMADA**

`.agent/rules/common/do_now_vs_defer.md` contiene LITERALMENTE las 3 frases normativas
principales del bloque:
1. "El coste de APLAZAR **no es cero**" (presente)
2. "Cada gate se responde con un ARTEFACTO, no con un juicio." (presente)
3. "Ante duda no resuelta POR EVIDENCIA, **aplazar gana**." (presente)

Verificado con busqueda literal de substring: las 3 presentes en ambos ficheros
(ajustando por formataje markdown).

---

## Sobre unidades y aritmetica

### Unidades y tamanos (fuente JSON `measure_agents_md_units.py`)

Total unidades nivel-2: **24**

| Categoria | Cantidad | Suma own_bytes |
|-----------|----------|----------------|
| Bloqueos PASO 2 (SIEMPRE) | 4 | 5335 B (3032+1555+110+638) |
| Bloqueos PASO 3(e) (Hermes) | 2 | 12261 B (932+11329) |
| Bloqueos PASO 3(c) (refutacion) | 2 | 1684 B (340+1344) |
| Bloqueos PASO 3(d) (grande) | 1 | 4159 B |
| Pequeñas (<1600) | 14 | 7544 B |
| Contenedor vacio | 1 | 17 B |
| **Total L2** | **24** | **31000 B** (suma own_bytes) |

**Correccion (verificacion Manager, re-sumado con Python sobre el JSON real):** las
cifras de esta tabla en una version previa de este informe contenian 3 errores
aritmeticos (6915/14404/6731/28635 en vez de 5335/12261/7544/31000). Los
sumandos por unidad no cambiaron; solo la suma estaba mal calculada.

Nota: la suma de own_bytes de las 24 unidades nivel-2 es:
3032+211+1023+932+1052+366+4159+17+416+197+110+11329+340+871+191+1344+536+878+479+435+455+1555+434+638 = **31000 B**

Suma de subtree_bytes L2: 61327 B (61370 - 43 del encabezado #1).

### Sobre bytes vs caracteres

Las cifras de ahorro en Ronda 1 ("3236 caracteres") confundian bytes con chars.
Correccion:

- Los 3 bloques candidatos (Backends, Memoria, Hacer) tienen bytes==chars (sin
  no-ASCII significativo). own_bytes = own_chars para estos bloques concretos.
- El ahorro NETO en bytes (E2 conservador): (3032-1200) + (1344-200) + (340-80) = 3236 B
- El ahorro NETO en chars: (3032-1200) + (1344-200) + (338-80) = 3234 chars
  (la diferencia de 2 chars viene de `own_chars=338` vs `own_bytes=340` en
  "Hacer ahora vs aplazar" por 2 caracteres con encoding UTF-8 de 2 bytes).

No se reutiliza la cifra de bytes para reportar ahorro en chars. Son unidades
distintas.

---

## Observacion critica

La medicion corregida (Ronda 2) concluye **SIN CANDIDATO MOVIBLE**. Ninguna de las
24 unidades nivel-2 pasa PASO 3 completo porque `build_llms.py` falla PASO 3(d) para
todas.

Esto **NO** cierra los deficits:
- Codex: deficit 28602 B -> incluso en el escenario mas favorable (mover TODAS las
  14 unidades "pequenas" + "Comandos principales", ignorando que todas fallan
  PASO 3(d) por `build_llms.py`), el maximo teorico es 7544 + 4159 = 11703 B,
  muy por debajo del deficit real.
- Claude: la misma limitacion aplica en caracteres (own_chars ~ own_bytes para
  estos bloques, sin no-ASCII significativo).

La opcion recomendada por el diseño es deuda declarada con owner humano, no mover
bloques que generen overhead.

---

## Bloqueos detectados

1. **CEM v0 duplicado en `sustainable_engineering.md`:** `sustainable_engineering.md:87`
   es copia literal de AGENTS.md:559 ("Criterio invariante, evidencia fechada").

2. **flight_push_policy.md duplica "Push por vuelo" completamente; "Extension: push" parcialmente:**
   lineas 1-26 del fichero reproducen "Push por vuelo" (942 chars); la seccion
   "Extension: push" solo tiene encabezado + 2 lineas de Gate 1 (95 chars), NO el
   desarrollo de Gate 2.

3. **Resultados pueden ser "SIN CANDIDATO MOVIBLE":** Ninguno de los candidatos
   publicados (ni los 3 de Ronda 1 ni otros) supera las condiciones PASO 3 actuales.
   El hallazgo #1 (build_llms.py lee AGENTS.md entero) aplica a TODO el fichero.
   Esta seccion declara explicitamente que NINGUN candidato supera las condiciones
   actuales; no se extrapola a que no exista ningun subbloque posible en el futuro.

4. **No se pudo ejecutar PASO 4 (before/after de consumidores):** Se requieren cambios
   en el arbol para medir el impacto real en los consumidores. Esto se posterga hasta
   decidir si se propone un traslado.

---

## Aritmetica de la tabla

Suma propia de unidades nivel-2 (verificacion del inventario):

3032 + 211 + 1023 + 932 + 1052 + 366 + 4159 + 17 + 416 + 197 + 110 + 11329 + 340 + 871 + 191 + 1344 + 536 + 878 + 479 + 435 + 455 + 1555 + 434 + 638 = **31000 B** (suma de own_bytes nivel-2)

Suma de subtree_bytes nivel-2 (para referencia, incluyendo hijas):
61327 B (61370 - 43 B del encabezado nivel-1)

---

## Informes de cierre

- Contrato builder: `prompts/builder_invocation_contract.md` (referenciado)
- Veredicto final: SIN CANDIDATO MOVIBLE -- build_llms.py lee AGENTS.md entero,
  fallan PASO 3(d) todas las unidades nivel-2.
