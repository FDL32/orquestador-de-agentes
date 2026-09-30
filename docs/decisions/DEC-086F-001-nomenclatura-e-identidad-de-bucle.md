# DEC-086F-001: Nomenclatura de formas (UNI/DBL/ROL/CHA-N) e identidad de ejecucion

**Ticket:** WOT-2026-086f (draft, bloqueado por decisiones pendientes)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre
`PROPUESTA_D1_D2_D3_D5_P10_ratificacion_20260930.md`, workspace).
**Autores de la investigacion:** 2 agentes independientes de solo lectura (D-2 y D-3), mas verificacion
del orquestador.
**Antecedente:** WOT-2026-037b ("Schema de `loop_id`/`backend_key`", 2026-07-19). Ver correccion en el
Anexo: una cita anterior de este trabajo le atribuyo una frase que WOT-2026-037b nunca dijo.

---

## DECISION 1 (D-2): se adopta el vocabulario UNI/DBL/ROL/CHA-N

Se ratifica adoptar `UNI/DBL/ROL/CHA-N` como nombres de forma, sustituyendo el esquema de nombres de
`loop_shapes` que fijo WOT-2026-037b (los 4 `L###` con nombre legible `BUC-01/02/03/CHA-01`).

**Con las siguientes 4 condiciones, ya resueltas por esta DEC y por DEC-086I-001:**

1. **La regla unica de que cuenta como N** es la de DEC-086I-001 Decision 2: fan-out de lentes
   distintas, sin el emisor (BA01); el refuter (codex) **SI cuenta** en N (alineado con la barrera real).
   Consecuencia: `L720` (BA05 refuter + 4 nan) se alias-mapea a **`DBL-5`**, no `DBL-4`.
2. **El registro es parametrico por gramatica** (forma+N: `UNI-2`, `UNI-3`, `UNI-4`, `UNI-5`, `DBL-2`...
   `DBL-6`, `ROL-2`...`ROL-4`, `CHA-4`, `CHA-5`), no una lista cerrada de combinaciones ad-hoc.
3. **El modo secuencial/paralelo (P/S) va como CAMPO APARTE**, no como sufijo del nombre. Motivo: un
   sufijo (`UNI-3/S`) duplicaria informacion que ya vive en la ejecucion (el orden de las llamadas) y
   complicaria el parseo de un nombre que WOT-2026-086i necesita reconocer por texto plano en chat.
4. **Los alias recalculados de L700/L710/L720/L800 son de SOLO LECTURA sobre el historico** (no
   inyectivos: varias corridas historicas con distinto backend real pueden mapear al mismo alias
   `DBL-N`). Nunca se usan para escribir filas nuevas -- las filas nuevas llevan el nombre de forma
   directamente.

### Alias historicos (solo lectura, no exhaustivos hasta que WOT-2026-086f los complete)

| `loop_id` antiguo | `name` en `loop_shapes` | Alias `UNI/DBL/ROL/CHA-N` (con refuter contando en N) |
|---|---|---|
| `L700` | BUC-01 (deprecated) | `DBL-4` (medido: 4 nan sin refuter en su forma original) |
| `L710` | BUC-02 (deprecated) | `DBL-6` (medido: 4 nan + codex + BA06) |
| `L720` | BUC-03 (active) | `DBL-5` (BA05 refuter + 4 nan) |
| `L800` | CHA-01 (active) | `CHA-4` a `CHA-5` segun si incluyo refuter en esa corrida (varia por ejecucion) |

WOT-2026-086f debe cerrar la tabla completa con evidencia (censo real del scorecard), no dar estos
valores por definitivos: son la primera aproximacion de este DEC, calculados sobre la descripcion de
`loop_shapes.steps` en `agents.json`, no sobre un recuento fila a fila.

---

## DECISION 2 (D-3): la identidad de ejecucion es el `challenge_nonce`, no un campo nuevo

**Se RECHAZA** la propuesta original de D-3 ("`run_id` va en el campo `loop_id` existente; `shape_id`
es campo nuevo"). **Se adopta la opcion C**: el `challenge_nonce` es el id de ejecucion; `loop_id` sigue
siendo la FORMA (donde se fusiona con la Decision 1 de arriba). **No se anade ningun campo nuevo de
identidad.**

**Se adopta ademas la opcion C-a**: `emit-nonce` acepta un modo sin commit (`commit_sha: null`) para
las etapas que no son de gobierno (`DESIGN_REVIEW`, `EXPLORATORY`), que hoy quedan sin nonce.
`check_loop_execution` nunca acreditaria esas emisiones, porque su barrera exige que el sha coincida.

### Premisa refutada, medida antes de decidir

La propuesta original asumia que hacia falta un campo nuevo porque `loop_id` ya se usaba mayormente como
id de ejecucion. FALSO: de 953 nonces emitidos, solo 512 (53,7%) usan una de las 4 formas registradas; y
la identidad de ejecucion UNICA **ya existe**: los 953 nonces son 953 distintos, ninguno repetido, cada
uno con un solo `loop_id` y un solo sha. Esto ya estaba escrito en `docs/decisions/DEC-bucle-doc-001-
ancla-de-bucle-sobre-documento.md` (capa "Instancia" = `challenge_nonce`, "ya es unico por emision") y en
la leccion de memoria `obs-count-by-the-unit-that-identifies-the-run-not-by-the-anchor`. Anadir `run_id`/
`shape_id` habria duplicado una identidad que ya existia.

### Correccion obligatoria dentro de WOT-2026-086f (no opcional)

El ruido FABRICADO de `fabricated_nonce_rounds` en `check_loop_execution.py`: filtra el ledger de
emisiones por `loop_id` pero NO filtra las filas del scorecard por lo mismo, asi que con `--loop-id X`
explicito, rondas legitimas de OTRO bucle sobre el mismo sha salen marcadas como FABRICADO. Afecta a 203
shas con mas de un nonce (medido). Debe corregirse antes de congelar el contrato de 086f, con su propia
mutation.

### Impacto en WOT-2026-074j

La premisa de WOT-2026-074j ("los joins de `check_loop_execution` agrupan por `loop_id`") esta
desfasada: la barrera agrupa por nonce (opcion C', ya implementada), no por `loop_id`. Su DoD de
"unicidad de `loop_id` por ejecucion" ya no aplica bajo esta decision (el `loop_id` sigue siendo forma,
se repite por diseno). Lo que SI sigue vigente de 074j es el sintoma de `fabricated_nonce_rounds` de
arriba. WOT-2026-074j debe reescribirse (o absorberse en WOT-2026-086f) para reflejar esto antes de
tocarlo.

---

## Anexo: correccion de una atribucion imprecisa (2026-09-30)

Durante la investigacion de D-3, una cita interna del investigador atribuyo a "WOT-2026-037b (2026-07-
19)" la frase "ID citable que NO codifica estructura". Verificado por el orquestador: esa frase **no
existe en ningun documento del repo** (buscado en `docs/decisions/`, `git log --grep`, memoria y
backlog). Lo unico real de WOT-2026-037b es que fijo el "Schema de `loop_id`/`backend_key`" (citado en
`<destino>/.agent/runtime/compare/loop_id-semantica-tipo-vs-instancia.md:268`). La Decision 1 de este
DEC sustituye ESE esquema de nombres, no una propiedad que nadie escribio. El hecho de fondo que la cita
imprecisa intentaba describir (`loop_id`=tipo, `challenge_nonce`=instancia) es correcto y esta
fundamentado de forma independiente en `DEC-bucle-doc-001`, asi que la Decision 2 de este DEC no se ve
afectada por el error de atribucion.
