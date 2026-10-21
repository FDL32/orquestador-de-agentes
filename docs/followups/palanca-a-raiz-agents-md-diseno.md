# Diseno (WP de DISENO, read-only sobre codigo): bajar el AGENTS.md raiz bajo el gate Codex

> Documento de DISENO (`sesion_diseno`): NO implementa nada ni toca prompts. Es el contrato
> de entrada para una sesion de desarrollo posterior, previa revision del usuario.
> Deuda que atiende: `docs/followups/agents-md-over-quota-followup.md` (sigue ABIERTA).
> Precedentes que lee y NO redeclara (X-09): contrato de pasada 2 (E1-E6, abajo "Equivalencia"),
> `prompts/doc_optimization.md` (PASO 1-5), propuestas de Palanca A de 2026-10-18/19.

contract_id: cid-palanca-a-raiz-agents-md-diseno-v1

## 0. Decisiones del usuario (2026-10-21) que gobiernan este diseno

1. Objetivo: bajar `AGENTS.md` raiz POR DEBAJO del gate Codex (32768 B).
2. Alcance de la primera pasada: SOLO la raiz, sin `AGENTS.md` anidados (recomendacion
   aceptada: Codex trunca en silencio y root-first, codex-rs/core/src/agents_md.rs).
3. `flight_manifest.json`: deuda declarada con dueno, NO WP propio (ver seccion 8).

## 1. ESTADO_FRESCO y mediciones (snapshot 2026-10-21; si el comando da otro valor, manda el comando)

    ESTADO_FRESCO: raiz=<worktree FDL32-agents-md-sessionstart-palanca-a-20261021>, HEAD=99737636, dirty=1 (este mismo documento, sin trackear), verificado=2026-10-21
    Nota: origin/main avanzo a 6bc3d2de tras esta medicion (otra sesion); no toca AGENTS.md ni CLAUDE.md. Re-medir tras fusionar.

| Dato | Valor | Comando que lo re-mide |
|---|---|---|
| AGENTS.md (Codex, bytes) | 61047 B = 1,86x | `python -c "import sys; sys.path.insert(0,'scripts'); import check_cuspide_growth_and_drift as c; m=c.measure_snapshot('HEAD'); print(m.agents_bytes, m.claude_chars)"` |
| Cierre CLAUDE.md+@AGENTS.md (chars) | 62970 = 1,57x | mismo comando (segundo valor) |
| Deficit minimo hasta el gate Codex | 28279 B | 61047 - 32768 |
| Secciones que extrae Hermes (ids) | vocabulario_canonico 13149 B, cem_v0 11329 B, secretos_y_seguridad 1555 B | `grep -n AGENTS_SECTIONS_REGISTRY scripts/hermes_build_context_bundle.py` |

Censo por seccion `##` (re-mide agrupando por encabezado y sumando bytes): Convenciones 14652,
Vocabulario 13149 (Tipos de SESION 1097, Modos de EJECUCION 6093, Glosario de ticket 4399,
Distincion collaboration 628), CEM v0 11329, Comandos 4159, Backends y roles 3032,
Docstrings/testing 2316; el resto, menos de 1,6 KB cada una. Dentro de Convenciones: Orden de
trabajo 8500 (incluye Push por vuelo, ya movido en parte, y la Extension push concurrente
3474), encoding 3059 (de ellos "No MEZCLES vias" 2239), proceso 1875, perfiles 787, lectura 414.

## 2. Resultado central: el TOPE de directivas es 4228 B; que la piramide llegue depende de una retencion SIN medir

**Que es firme y que es hipotesis (corregido tras el bucle DESIGN_REVIEW de ronda 1):** la
aritmetica de abajo es exacta y re-medible. La CONCLUSION ("la piramide sola no llega") solo
se sigue si la retencion real de directivas supera ese presupuesto, y esa retencion es hoy una
estimacion. La Fase 0 la mide; hasta entonces esto es una hipotesis con numeros, no un teorema.

Lo que la pasada 2 dejo DIFERIDO ("ola 2": Extension push concurrente 3474 + No MEZCLES vias
2239 + Docstrings/testing 2316 = 8029 B, re-medido hoy; el contrato de pasada 2 decia 3656 para
la Extension) mas las dos secciones grandes que extrae Hermes (Vocabulario 13149 + CEM v0
11329) suman **32507 B brutos**. Si se movieran ENTERAS, la raiz quedaria en
61047 - 32507 = **28540 B**. Pero cada seccion movida deja una directiva (E2: encabezado +
frases normativas literales + puntero). Para llegar al gate:

    tope total de directivas que pueden quedarse        = 32507 - 28279 = 4228 B    (0% de margen)
    con 10% de margen (objetivo 29491 B)                = 32507 - 31556 =  951 B

Son tres grupos de bloques con decenas de NUNCA/SIEMPRE y marcadores fijados por tests: 4,2 KB
(o 0,95 KB) para todas sus directivas es inalcanzable sin violar E3 ("nada se pierde"). **Estimacion, a
medir en la Fase 0** (no es un hecho): directivas realistas de unos 10-14 KB entre las tres
=> raiz de ~38,5-42,5 KB (1,18-1,30x). SI la Fase 0 confirma esa retencion, el resto del
deficit exige OTRA palanca, no mas movimientos del mismo tipo (coincide con la conclusion de
pasada 2); SI mide <= 4228 B, la piramide sola llega. El suelo de 28540 B (todo lo que no es
uno de los 5 grupos movibles: Comandos 4159, Backends 3032, Convenciones residual, 18 secciones
de menos de 1,6 KB...) tampoco esta clasificado por PASO 2 todavia: la Fase 0 lo hace.

**Aclaracion (hallazgo mal leido por dos lentes):** Codex suma SOLO los `AGENTS.md` de la
jerarquia root-to-leaf (E6 del bundle), no los modulos bajo `.agent/rules/common/`. Que el
modulo contenga la seccion entera y la cuspide una seleccion literal NO suma al gate: el ahorro
es el de la cuspide, igual que midio la pasada 2 (77372 -> 61047 B). La duplicacion directiva /
modulo es deliberada (E2) y se vigila con el guard E8.

**Riesgo R4 (no verificable aqui):** el contador `remaining` de Codex es compartido entre
entornos; si el usuario abre varios repos a la vez, el presupuesto efectivo de ESTA raiz podria
ser menor que 32768 B. Es otra razon para exigir margen y no apuntar al limite exacto.

Gate Claude Code (40000 chars sobre el cierre): CLAUDE.md mide 2006 chars, asi que el cierre
cabe si la raiz queda por debajo de ~38000 chars. La piramide se acerca a ese borde pero no lo
garantiza. El gate Codex es el que exige mas.

## 3. Palancas candidatas para el resto del deficit (decision del usuario, ver seccion 9)

| Palanca | Que cierra | Coste / riesgo | Veredicto de este diseno |
|---|---|---|---|
| P-pir. Piramide (olas 1-3) | ~20-24 KB netos (a medir) | Medio; equivalencia E1-E6 | HACER primero |
| C. Condensar prosa de filas #1-#3 | hasta unos KB | Cambia una REGLA de `doc_optimization.md` (hoy: "SIEMPRE se queda ENTERO"); riesgo forense | Exige contrato propio y bucle; NO se asume |
| A-anidada (scripts/, prompts/, skills/) | Solo contenido por dominio; el total root-to-leaf desde ese cwd NO baja | Truncado silencioso si la raiz no tiene margen | Fuera de la 1a pasada (decision 2) |
| B. Desacoplar `@AGENTS.md` de CLAUDE.md | Solo gate Claude | No toca Codex; menos reglas en cada sesion Claude | No resuelve el objetivo |
| Mover filas #1-#3 enteras a modulo | El resto | Contradice PASO 2 sin contrato nuevo | Mismo contrato que C |

## 4. Diseno de la Fase 1 (Hermes primero, sin mover contenido)

Problema (TRAMPA-3 de `doc_optimization.md`): `build_motor_context` extrae las 3 secciones por
encabezado desde `AGENTS.md` (`_extract_registered_section(agents, id)`). Si el cuerpo pasa a un
modulo y el encabezado se queda con un puntero, Hermes recibe 95% menos y NO lanza error.

**D1. El modulo contiene la seccion ENTERA verbatim (con su encabezado) y el registro apunta a el.**
`AGENTS_SECTIONS_REGISTRY` gana un tercer campo `source` (ruta relativa al motor) por id; la
extraccion lee ese fichero. Mientras no se mueva nada, `source = AGENTS.md` y la salida es
identica. Al mover la seccion, `source` pasa a `.agent/rules/common/<modulo>.md` y la salida de
Hermes es BYTE-IDENTICA a la anterior (el modulo ES el texto original; la cuspide conserva una
seleccion literal, E2). Esto cumple PASO 4 sin "diferencia justificada bloque a bloque".

**D1-bis. Procedencia del manifiesto (hallazgo BLOCKER de la ronda 2, verificado en el codigo).**
`build_bundle` hashea como `source_files` solo `prompts/hermes_soul.md`, `AGENTS.md`, el bootstrap
y el closeout (`scripts/hermes_build_context_bundle.py:265-295`). Si el texto de una seccion sale
de un modulo, `bundle_manifest.json` seguiria certificando el sha256 de un `AGENTS.md` que ya no
lo contiene: procedencia falsa aunque los bytes cuadren. En el MISMO commit que mueve la primera
seccion, cada `source` distinta de `AGENTS.md` entra en `source_paths` (comprobacion de existencia
+ hash en `source_files`), con un test que fija que toda `source` del registro figura en el
manifiesto. Efectos colaterales de la tupla de 3 campos que ese commit tambien adapta:
`_REGISTRY_BY_ID = dict(AGENTS_SECTIONS_REGISTRY)` (`:85`) y los desempaquetados `for sid, _ in`
de los tests (`:113`, `:171`) fallan con 3 campos. El modulo tambien debe estar en
`MANIFEST.distribute` (un guard existente verifica que cada entrada resuelve a un fichero
trackeado), de modo que un destino no pueda recibir un Hermes que apunta a un fichero ausente.

**D2. Guard de no-degradacion ejecutable, antes de mover nada.** Se captura el baseline de las 3
SECCIONES que devuelve la extraccion (sha256 y longitud de cada una) en el commit 0 y un test
fija esos valores contra la salida REAL (no el conteo de lineas). Una seccion que encoja hace
caer el test. Se compara por seccion y NO por bundle completo: el bundle lleva el sha del commit
y la hora de generacion, asi que nunca es identico entre commits. Los tests actuales no lo hacen:
`tests/test_hermes_build_context_bundle.py:171` solo exige `.strip()` no vacio, y `:122` fija
`source.count("_extract_registered_section(agents,") == 3` (forma del codigo). Se adaptan en el
mismo commit: `:122` pasa a fijar el invariante nuevo, "los 3 ids se resuelven cada uno desde
la `source` declarada en el registro y ningun id carece de `source`".

**D2-bis. Consumidores restantes (before/after por consumidor, PASO 4).** Solo Hermes extrae por
encabezado; los demas leen el fichero entero, por ruta o por manifiesto. Cada uno tiene accion y
verificacion propia, ejecutada ANTES y DESPUES de cada commit que mueva contenido:

| Consumidor | Que hace con AGENTS.md | Accion | Verificacion |
|---|---|---|---|
| `hermes_build_context_bundle.py` | extrae 3 secciones por encabezado | D1 (registro con `source`) | sha256 de las 3 secciones = baseline |
| `build_llms.py` | lo incrusta entero en `llms-full.txt` | anadir cada modulo a `INLINE_IN_FULL` | `build_llms.py --check` rc 0; el fichero generado crece (cuspide + modulo): es una proyeccion, no cuenta para ningun gate |
| `discover_skills.py` (`module_citations`) | busca citas literales de prompts | ya busca en `.agent/rules/common/*.md` (pasada 2) | T9 sin modulos huerfanos |
| `destination_context.py` | preview de las 30 primeras lineas | no tocar las lineas 1-30 | `head -30` identico |
| `census_dogfooding_narrative.py`, `check_distribution_agnostic.py` | leen bytes via `MANIFEST.distribute` | anadir cada modulo a `MANIFEST.distribute` | ambos guards verdes |
| `upgrade_agent_system.py` | `CRITICAL_PATHS` incluye `AGENTS.md` | verificacion, sin edicion | los modulos bajo `.agent/` propagan por directorio |

**D3. Orden bisect-safe.** (1) commit 0: baseline + test; (2) commit 1: `source` en el registro
con `AGENTS.md` por defecto (delta 0 B en cuspide); (3) un commit por seccion movida, cada uno con
delta de cuspide <= 0, modulo en `MANIFEST.distribute` y en `INLINE_IN_FULL` de `build_llms.py`
(+ `build_llms.py --check` rc 0), `discover_skills.module_citations()` ya extendido en pasada 2.
`upgrade_agent_system.CRITICAL_PATHS`: verificacion, no edicion (los modulos bajo `.agent/`
propagan solos, evidencia en el contrato de pasada 2).

## 5. Fases y presupuesto (cifras = TECHO de lo movible, no prediccion)

| Fase | Contenido | Techo movible | Riesgo | Precondicion |
|---|---|---|---|---|
| 0 | Medir (definicion abajo) sobre TODO AGENTS.md, incluido el suelo de 28540 B; censar tambien contenido ya duplicado entre AGENTS.md y modulos/prompts (palanca barata: se mide, no se asume) | - | Bajo | ninguna. **Es la puerta de decision:** sus numeros fijan si hacen falta las fases 3-5 |
| 1 | Registro de Hermes re-apuntable + baseline (seccion 4) | 0 B | Medio (consumidor runtime) | Fase 0 |
| 2 | Vocabulario: Modos EJECUCION, Glosario ticket, Tipos SESION, Distincion | 12217 B | Medio | Fase 1 |
| 3 | Ola 2 diferida (3474+2239+2316), UN bloque por commit y solo los que la Fase 0 clasifique como separables | 8029 B | ALTO (refutacion densa, marcadores fijados por tests) | Fase 2 medida |
| 4 | CEM v0 (nucleo epistemologico), LA ULTIMA | hasta 8-9 KB | ALTO (filas #1-#3) | Fases 1-3 medidas + bucle propio |
| 5 | Palanca restante (C u otra), solo si el usuario la elige | el resto | segun palanca | seccion 9 |

Secretos y seguridad (1555 B) NO se mueve: son prohibiciones duras (fila #2) y cuesta mas de lo
que ahorra.

**Definicion operativa de la Fase 0 (corrige "dos cubos", hallazgo de la ronda 2).** Por cada
bloque (encabezado `##`/`###`/`####`) de AGENTS.md: (1) la FILA de PASO 2 (1-7; ante match
multiple gana la fila superior), con las 5 condiciones de PASO 3 y la letra que falla; (2) la
SELECCION E2 que quedaria en la cuspide (encabezado + frases normativas literales + puntero),
en bytes, y el resto movible; (3) para el suelo, si algun bloque admite mover o fusionar sin
perder norma. Salida: DOS numeros, no uno: la retencion total de los 5 grupos y el ahorro
adicional posible del suelo, mas la lista de bloques con su fila. Cifras como "10-14 KB" son
una estimacion mia sin fuente; la Fase 0 las sustituye. Si hay ambiguedad entre dos filas se
toma la mas conservadora (no mover). Los 932 B de Vocabulario no atribuidos a subsecciones
(13149 - 12217: encabezado, introduccion y tabla de 4 terminos) se clasifican tambien ahi.

**El 4228 B es un TECHO, no un objetivo:** es lo MAXIMO que podrian pesar todas las
directivas juntas si se movieran los 5 grupos enteros. Cualquier bloque de filas #1-#3 que PASO 3
impida mover reduce ese techo.

## 6. Equivalencia (referencia, no redeclaracion)

Se reutilizan E1-E6 del contrato de pasada 2 sin cambios: E1 modulo byte-a-byte; E2 cuspide =
encabezado + frases normativas LITERALES + puntero; E3 nada se pierde; E4 marcadores fijados por
barreras (tests, hooks) viajan verbatim; E5 fechas/ids con el bloque; E6 la cuspide nunca crece
y los 3 ids de Hermes conservan longitud exacta. Se anaden dos:

- **E7:** cada una de las 3 secciones que extrae Hermes es BYTE-IDENTICA (sha256) antes y despues
  de cada commit de la Fase 2+. Se mide por seccion, no por bundle (ver D2); y la salida de
  Hermes es identica SOLO en esas 3 secciones (el manifiesto cambia a proposito, D1-bis).
- **E8 (guard de deriva cuspide/modulo, mecanico):** cada LINEA no vacia del cuerpo de una
  seccion movida en la cuspide, salvo la linea de puntero (la que lleva el marcador
  `-> modulo:`), es SUBCADENA EXACTA del modulo. Asi las "frases normativas" no se adivinan
  parseando prosa: son las lineas que la cuspide conserva, y el marcador de puntero las separa.
  Un test lo comprueba. Detecta que la cuspide cite algo que el modulo ya no dice (deriva en esa
  direccion). NO exige lo inverso: una regla anadida solo al modulo es legitima, porque el
  modulo es el texto completo y la cuspide una seleccion (E3 pide que cada norma este en la
  directiva O en el modulo). El gate de deriva existente solo avisa de que se toco uno sin el
  otro, no de que el texto diverja.

## 7. Verificacion por fase (cada una con su propia mutacion que debe caer)

- Ambos gates en su unidad nativa, sin convertir: `wc -c` Codex y chars del cierre Claude.
- Hermes: sha256 de las 3 secciones iguales al baseline (E7); mutacion: truncar un modulo -> cae.
- Deriva (E8): mutacion = editar una frase literal solo en el modulo -> el test cae.
- **Comportamiento, no solo bytes (R1):** el disparador es el VOLUMEN movido, no la etiqueta de
  riesgo: tras cada fase que mueva mas de 4000 B (la Fase 2 mueve 12217 B, asi que entra) se
  repite la prueba de arranque en frio de la propuesta de continuidad (mismo fixture, al menos
  Claude, un Kilo fuerte y un backend debil tipo gemma4) sobre una regla cuyo detalle haya pasado
  a un modulo. El umbral de 4000 B es un knob SIN medir, declarado como tal. Criterio de bloqueo,
  POR BACKEND: un backend con 3 fallos independientes de seguir el puntero (casos distintos, no
  repeticiones del mismo fixture) bloquea el siguiente movimiento a modulo hasta decision del
  usuario; con menos, se REGISTRA como riesgo medido. Estado hoy: gemma4 lleva 2 (la prueba de
  esta propuesta mas un caso independiente de 2026-10-08); Claude y qwen3.8-flash, 0. Sin esta
  medicion, E3 solo garantiza bytes, no adherencia.
- `build_llms.py --check` rc 0; `discover_skills` T9 sin huerfanos; `check_cuspide_growth_and_drift`
  pre-commit con delta NEGATIVO; `check_guard_wiring` verde.
- Mojibake: ningun `c3 83`, `c3 82`, `c3 a2 e2 82 ac`, `ef bf bd`; `AGENTS.md` conserva `c3 b1`
  y `e2 80 94`. E1 se verifica con BYTES contra `git show <base>:AGENTS.md`, nunca con prosa.
- Suite canonica UNA vez al final (`--level all`, clon de ruta corta), tras TODOS los commits.
- Un Builder real (nan/qwen) NO se acepta por su recibo: se re-ejecuta el verificador (leccion
  de la pasada 2: recibo APLICADO con 3 checks fallando, `amend` prohibido, blancos duplicados).

## 8. Deuda declarada: `flight_manifest.json`

Decision del usuario: deuda con dueno, no WP. Dueno: decision de usuario para abrir WP. Pieza
nueva (manifiesto machine-readable de que se carga siempre / por ticket / por hijo), no una
migracion de contenido. Criterio de salida: un manifiesto validado por un guard cableado.
No bloquea nada de este diseno. Se ficha en `docs/followups/` al cerrar esta sesion.

## 9. Decisiones que quedan para el usuario

1. SI la Fase 0 confirma que la retencion supera el tope de la seccion 2, que hacer con el
   deficit restante: Palanca C (condensar prosa, requiere cambiar la regla del PASO 2),
   anidados limitados, o aceptar la piramide sola y dejar la deuda abierta con numeros nuevos.
   Este diseno NO lo decide, y la cuantia del deficit restante es hipotesis hasta la Fase 0.
2. Si la Fase 4 (CEM v0) se hace en esta tanda o se deja tras medir las Fases 1-3 (recomendado:
   tras medir; ya es la ultima).
3. **Aceptar o no el riesgo R1**: mover detalle a modulos cambia carga garantizada por
   carga-por-puntero, con una regresion funcional medida en un backend debil (gemma4, n=2). El
   diseno la mide (seccion 7) pero no decide si es aceptable. Es una decision de producto.
4. Si el 10% de margen es REQUISITO (recomendado por R4, no verificable) o basta quedar bajo el
   gate exacto.

## 10. Fuera de alcance

- Arranque en frio (hook UTF-8, memoria por cwd, par de worktrees, guard de topologia): `docs/followups/arranque-agentes-frios-propuesta-optimizacion.md`. Relacion: la verificacion conductual de este diseno (seccion 7) se hace en un arranque en frio y se beneficia de D1a/D1b; no es precondicion de ninguna fase de reduccion.

Anidados (decision 2), Palanca B, `scripts/filter_lens_output.py`, esquema de
`observations.jsonl`, P4 (`--apply` automatico), WOT-2026-058b y 105a.

## 11. Riesgos y limitaciones declaradas

- R1: un agente frio que no sigue el puntero opera solo con la directiva (mecanismo de carga
  "puntero-por-prosa", sin autocarga; riesgo permanente declarado en pasada 2). Medido: gemma4
  via Kilo fallo 2 de 2 pruebas de seguir el puntero; Claude y qwen3.8-flash lo siguieron.
- R2: las cifras de la seccion 2 usan retenciones ESTIMADAS; la Fase 0 las sustituye por medidas.
- R3: Hermes es el unico consumidor con extraccion por encabezado segun el censo de pasada 1
  (no re-ejecutado en esta sesion: la Fase 0 lo repite con `git grep` sin filtrar por extension,
  PASO 3(d)). Los otros 5 consumidores de contenido tienen accion y verificacion en D2-bis.
- R4: el presupuesto efectivo de Codex puede ser menor que 32768 B si otros entornos comparten
  el contador (no verificable con la lectura de codigo hecha). Justifica exigir margen.
- R5: unidades. El cierre de Claude se mide en caracteres y el de Codex en bytes; AGENTS.md
  tiene unos 83 bytes multibyte mas que caracteres. No se convierte de una unidad a otra.
