# Propuesta: generalizar el eje D a un esquema formal de capsula de decision (eje G) -- 2026-10-23

> Cierra el ultimo punto abierto del informe de investigacion "Contexto siempre cargado para
> agentes LLM bajo presupuestos duros" (adjuntado 2026-10-22 en el thread `Agents,md
> optimizacion`): el eje D (`skill_trigger_governance.md`, WOT-2026-118a) formaliza SOLO
> colision de triggers de skills; el informe pedia un esquema general para CUALQUIER capsula
> de decision transversal (ejemplo citado explicitamente: T4/Gate 2). Esta propuesta NO
> modifica el eje D (alcance declarado de WOT-2026-118a se mantiene intacto) -- anade un eje
> NUEVO, letra `G`, para el caso general.

## Por que una letra nueva, no mas entradas D

`scripts/check_reference_keys.py::parse_legend()` mapea una letra a EXACTAMENTE un fichero
(restriccion ya documentada en `skill_trigger_governance.md`). Anadir el esquema general al
mismo fichero/letra D mezclaria dos alcances distintos (colision de triggers vs capsulas de
decision transversales) bajo una sola clave -- mismo motivo por el que T (WOT-2026-026t) y F
(CEM v0) viven en ficheros separados en vez de compartir letra con D.

## El esquema (5 campos, tomado del informe verbatim)

    REGLA     que esta permitido/prohibido
    CUANDO    condicion observable que la activa
    POR QUE   una sola frase causal que preserve el contexto negativo
    SALIDA    excepcion o camino seguro, si existe
    REF       donde esta la especificacion/evidencia completa

El informe es explicito en que el campo POR QUE es OBLIGATORIO para reglas de prohibicion o
default-deny (preserva el "contexto negativo": por que la regla existe, no solo que ordena).

## Estatus declarado: NORMA, no barrera (rigor proporcional)

`check_reference_keys.py` valida SINTAXIS (`[G#]` resuelve a `**G#.**`), nunca SEMANTICA --
esto ya esta declarado como non-goal explicito del guard. Un verificador mecanico que exija los
5 campos en cada capsula G anadiria una barrera nueva para una coleccion que hoy tiene UNA sola
entrada (T4) y crece raramente (T1-T4 surgieron en 4 meses de flights). Se declara como NORMA
documentada por volumen, con el mismo umbral de escalada que usa `doc_optimization.md` para
otras barreras (2+ casos medidos de deriva antes de construir guard). **Correccion tras bucle
adversarial (codex + deepseek, 2026-10-23):** el borrador original citaba el eje D como
precedente de "norma sin guard" ("D1-D3 tampoco tienen verificador de forma") -- esto es FALSO,
verificado contra `scripts/check_skill_collisions.py::_invalid_trigger_formats()` (D1 SI tiene
verificador mecanico de forma de trigger). D no es un precedente valido para NORMA; la
justificacion correcta es solo el volumen (1 instancia) + el umbral de `doc_optimization.md`,
sin apoyarse en D.

## Contenido propuesto: `.agent/rules/common/decision_capsule_schema.md` (fichero nuevo)

```markdown
# Esquema de capsula de decision transversal (eje G)

> Modulo de referencia (`referencia-bajo-demanda`). Citado desde
> `docs/registry/reference_keys.md` (letra `G`). Generaliza el patron que
> `.agent/rules/common/skill_trigger_governance.md` (eje D) aplica solo a
> colision de triggers de skills, al caso general de cualquier regla
> siempre-cargada que gobierne una decision transversal (no ligada a un
> rol/turno concreto). Origen: informe de investigacion "Contexto siempre
> cargado para agentes LLM bajo presupuestos duros" (2026-10-22), seccion
> "Cómo conservar la razón de una prohibición sin cargar el expediente
> completo".
>
> **ESTATUS DECLARADO: NORMA, no barrera.** `check_reference_keys.py` valida
> solo que `[G#]` resuelva a `**G#.**` (sintaxis), nunca que los 5 campos
> de abajo esten presentes (semantica) -- mismo alcance que ya declaran D1-D3.
> Escalar a guard mecanico esta condicionado a 2+ casos medidos de deriva,
> no se construye preventivamente sin evidencia.

## El esquema

    REGLA     que esta permitido/prohibido
    CUANDO    condicion observable que la activa
    POR QUE   una sola frase causal que preserve el contexto negativo
    SALIDA    excepcion o camino seguro, si existe
    REF       donde esta la especificacion/evidencia completa

El campo POR QUE es OBLIGATORIO para reglas de prohibicion/default-deny: sin el, un agente
frio obedece sin saber que propiedad protege, y no puede razonar ante un caso parecido no
cubierto literalmente.

<a id="g1"></a>
**G1.** Instancia de referencia: Gate 2 (push a rama con trafico concurrente), `AGENTS.md`
seccion "Extension: push a una rama con trafico concurrente de otras sesiones" (cabecera
estable; NO se fija a un SHA concreto -- ver correccion abajo). **Este item NO repite el texto
operativo** (riesgo de divergencia explicitamente senalado por el informe de origen: "cuspide:
decision minima normativa / referencia: desarrollo -- NO cuspide: mini-especificacion /
referencia: otra especificacion casi igual"). Solo mapea donde vive cada campo, sin parafrasear
la regla:
- REGLA + CUANDO + POR QUE + SALIDA: viven en la prosa de esa seccion en `AGENTS.md`, sin
  separacion explicita de campo. Leer ahi, no aqui.
- REF: `.agent/rules/common/flight_push_policy.md` (checklist completa, criterio de merge,
  Alcance, riesgo residual). **Este puntero YA existe en la misma seccion de `AGENTS.md`**
  (aparece dos veces en el working tree de este vuelo); `[G1]` no anade un REF nuevo, anade la
  anotacion de que esa cadena REGLA/CUANDO/POR QUE/SALIDA/REF sigue el esquema formal del eje G.

**Correccion tras bucle adversarial (codex + deepseek, 2026-10-23) -- BLOQUEANTE real,
verificado con `git show HEAD:AGENTS.md` vs working tree:** el borrador original fijaba G1 a
"HEAD `02aba94a803a`" y afirmaba que el parrafo empieza por "Default fail-closed...". Verificado:
en ESE HEAD, la seccion todavia tiene la version larga anterior (bullets "Gate 2 (push con la
rama remota avanzada...)", "Condiciones de rechazo del Gate 2...", "Alcance:", "Riesgo residual
declarado:") -- el parrafo "Default fail-closed..." SOLO existe en el working tree sin
commitear de este mismo vuelo (la compresion T4-redesign). Fijar G1 a ese SHA citaba texto
inexistente en el commit real. **Fix: G1 no fija SHA.** Se aplica en el MISMO commit que la
compresion T4 (de forma que el texto que G1 anota y el `[G1]` que lo cita nacen atomicamente
consistentes); si en el futuro esa seccion cambia de nuevo sin tocar G1, aplica el riesgo
residual declarado abajo (NORMA, no barrera -- no hay guard que fuerce la actualizacion).

**Riesgo residual declarado (NORMA, no barrera):** si `AGENTS.md` cambia el texto de esa
seccion, esta entrada NO se actualiza solo -- nada la cablea. Quien edite esa seccion debe
revisar que esta anotacion sigue siendo correcta en el mismo commit; no hay guard que lo
fuerce (mismo patron de "norma, no barrera" declarado arriba para el esquema completo).

Futuras capsulas transversales (fuera del rol builder/manager/revisor, fuera de colision de
triggers de skills) se anaden aqui como `G2`, `G3`... siguiendo el mismo principio: mapear
campos a su ubicacion real, nunca reescribirlos.
```

## Cambios en `AGENTS.md`

Anadir `[G1]` al final del parrafo de "Extension: push..." (ya termina en un puntero a
`flight_push_policy.md`; el `[G1]` es ADICIONAL, para discoverability del esquema de gobierno,
no sustituye el puntero al checklist -- son dos cosas distintas: REF = evidencia completa,
`[G1]` = anotacion de que esta capsula sigue el esquema formal):

Texto actual (ultima frase): `...equivalente): \`.agent/rules/common/flight_push_policy.md\`.`
Texto nuevo: `...equivalente): \`.agent/rules/common/flight_push_policy.md\` [G1].`

Coste: +5 B (" [G1]"). No se mueve ni resume nada del texto operativo existente.

## Cambios en `docs/registry/reference_keys.md`

Anadir fila (orden alfabetico, tras F, antes de T):

    | G | [`.agent/rules/common/decision_capsule_schema.md`](../../.agent/rules/common/decision_capsule_schema.md) |

## Verificacion

**Orden corregido tras bucle adversarial (deepseek, 2026-10-23):** el borrador original listaba
`check_distribution_boundary.py` (paso 2) antes de anadir la entrada a `MANIFEST.distribute`
(paso 3) -- ese orden hace fallar el guard (fichero nuevo sin entrada de manifiesto resuelve a
0 ficheros trackeados = hueco en la frontera, mismo patron medido con `flight_push_policy.md` y
`wot_010e_line_endings_forense.md` en este mismo vuelo). Orden correcto:

1. Crear `.agent/rules/common/decision_capsule_schema.md` y anadir su entrada a
   `MANIFEST.distribute` (mismo patron que E/T) en el MISMO paso.
2. `git add` del fichero nuevo (`check_distribution_boundary.py` solo cuenta ficheros
   trackeados por git).
3. `check_reference_keys.py` -- debe resolver `[G1]` contra `**G1.**` en el fichero nuevo.
4. `check_distribution_boundary.py` -- ahora con el fichero trackeado y en el manifiesto.
5. `build_llms.py --check` (gate real cableado como `check-llms-full-sync`; "regenerar" no
   basta como paso de verificacion, hay que confirmar que el check pasa tras regenerar).
6. Re-medir gates (coste total: +5 B en AGENTS.md, el fichero nuevo es `referencia-bajo-demanda`
   y no cuenta para ningun gate).
7. Tests focales: `tests/unit/test_flight_push_policy.py` (asserta substrings del `AGENTS.md`
   comprimido, ninguno se rompe por anadir `[G1]` al final del parrafo), mas los focales de los
   guards tocados (`check_reference_keys`, `build_llms`, `check_distribution_boundary`).

## Non-goals de esta propuesta

- NO migra T1/T2/T3 (eje T, forense) al eje G -- son casos forenses HISTORICOS, no capsulas de
  decision VIVAS que un agente consulte para decidir una accion futura. El eje G es para
  reglas que gobiernan una decision, no para evidencia de incidentes pasados.
- NO construye un verificador mecanico de los 5 campos (declarado como NORMA, seccion arriba).
- NO toca el eje D (`skill_trigger_governance.md`) ni su alcance declarado.
- NO identifica ni crea mas instancias G mas alla de T4 -- si en el futuro aparece otra regla
  transversal candidata (ej. ownership de integracion, el ejemplo D7 que citaba el informe),
  se anade como G2 en su propio ticket, no aqui.

## Errores y puntos de mejora encontrados en esta pasada (antes del bucle)

1. **El borrador original de G1 paraFraseaba la regla completa (REGLA/CUANDO/SALIDA como
   frases nuevas)** -- exactamente el patron "dos especificaciones que pueden divergir" que el
   propio informe de origen advierte explicitamente como anti-patron ("cuspide: una
   mini-especificacion / referencia: otra especificacion casi igual"). Corregido: G1 ahora
   solo MAPEA donde vive cada campo (apunta a la prosa real de AGENTS.md), no los reescribe.
   El unico texto nuevo que G1 aporta es el campo REF (que no vive en ningun otro sitio) y la
   declaracion de riesgo residual de desincronizacion.
2. **Riesgo de desincronizacion no declarado en el borrador original:** si alguien edita el
   parrafo de AGENTS.md sin tocar G1, G1 queda potencialmente obsoleto y nadie lo detecta (no
   hay guard). Ahora declarado explicitamente como NORMA con riesgo residual, consistente con
   el resto del documento (nada se construye preventivamente sin evidencia de deriva).
3. **Verificado que letra `G` esta libre:** `docs/registry/reference_keys.md` solo tiene
   D/E/F/T hoy; sin colision.
4. **Verificado el coste real:** la cita `[G1]` anadida (" [G1]") son 5 bytes exactos
   (`len(" [G1]".encode())`), no una estimacion.

## RONDA 1 -- bucle adversarial multi-backend (2026-10-23)

10 lentes despachadas (codex, glm, opencode, deepseek, qwen3.8 x2, google, mistral, cohere,
minimax, kimi). Resultado: 4 fallaron por causas EXTERNAS (creditos/API-key de OpenRouter o
Google agotados, no contenido: glm, google, kimi, minimax), 4 completaron con veredicto
(codex: CHANGES, deepseek: CHANGES, mistral: APPROVE, cohere: APPROVE), 2 (opencode-go/qwen3.8,
nan/qwen3.8) no llegaron a tiempo de esta pasada.

**Hallazgos BLOQUEANTES confirmados (codex + deepseek, coincidentes, verificados por mi
directamente con `git show HEAD:AGENTS.md` vs working tree):** G1 fijaba un SHA (`02aba94a803a`)
cuyo `AGENTS.md` NO contiene el parrafo que G1 citaba ("Default fail-closed..." solo existe en
el working tree sin commitear de la compresion T4 de este mismo vuelo) -- CORREGIDO (G1 ya no
fija SHA, se aplica atomicamente en el mismo commit que la compresion T4).

**Hallazgos MEJORA confirmados:** la justificacion de NORMA citaba el eje D como precedente de
"sin verificador de forma", lo cual es FALSO (D1 si tiene verificador mecanico, verificado contra
`check_skill_collisions.py::_invalid_trigger_formats()`) -- CORREGIDO (justificacion ahora es
solo volumen + umbral de `doc_optimization.md`). El orden de verificacion tenia
`check_distribution_boundary.py` antes de la entrada en `MANIFEST.distribute` -- CORREGIDO
(orden invertido). La afirmacion "REF es el unico texto nuevo que G1 aporta" era imprecisa (REF
ya existe en la misma seccion) -- CORREGIDO (aclarado que `[G1]` anota el esquema, no anade REF).

**Estado: PROPUESTA corregida, lista para aplicar.** Coste total: +5 B en AGENTS.md (deficit
Codex pasa de 4111 a 4116 B, el gate ya estaba en rojo antes de este cambio), 1 fichero nuevo,
1 fila nueva en reference_keys.md y en MANIFEST.distribute. Riesgo: bajo (documentacion +
anotacion, sin logica de ejecucion). Aplicando ahora.
