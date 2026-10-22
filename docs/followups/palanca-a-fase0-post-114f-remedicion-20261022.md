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
