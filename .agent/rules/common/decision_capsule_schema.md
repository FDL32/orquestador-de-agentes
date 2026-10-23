# Esquema de capsula de decision transversal (eje G)

> Modulo de referencia (`referencia-bajo-demanda`). Citado desde
> `docs/registry/reference_keys.md` (letra `G`). Generaliza el patron que
> `.agent/rules/common/skill_trigger_governance.md` (eje D) aplica solo a
> colision de triggers de skills, al caso general de cualquier regla
> siempre-cargada que gobierne una decision transversal (no ligada a un
> rol/turno concreto). Origen: informe de investigacion "Contexto siempre
> cargado para agentes LLM bajo presupuestos duros" (2026-10-22), seccion
> "Como conservar la razon de una prohibicion sin cargar el expediente
> completo".
>
> **ESTATUS DECLARADO: NORMA, no barrera.** `check_reference_keys.py` valida
> solo que `[G#]` resuelva a `**G#.**` (sintaxis), nunca que los 5 campos
> de abajo esten presentes (semantica). Justificacion por VOLUMEN (1 sola
> instancia hoy, G1) y por el criterio de escalada canonico [F8] -- no por
> el eje D como precedente: D1 SI tiene verificador mecanico de forma
> (`scripts/check_skill_collisions.py::_invalid_trigger_formats()`), asi
> que D no demuestra que "norma sin guard" sea el patron establecido.

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
estable; no se fija a un SHA concreto -- esta anotacion se aplica atomicamente en el mismo
commit que fija el texto vigente de esa seccion). **Este item NO repite el texto operativo**
(riesgo de divergencia explicitamente senalado por el informe de origen: "cuspide: decision
minima normativa / referencia: desarrollo -- NO cuspide: mini-especificacion / referencia:
otra especificacion casi igual"). Solo mapea donde vive cada campo, sin parafrasear la regla:
- REGLA + CUANDO + POR QUE + SALIDA: viven en la prosa de esa seccion en `AGENTS.md`, sin
  separacion explicita de campo. Leer ahi, no aqui.
- REF: `.agent/rules/common/flight_push_policy.md` (checklist completa, criterio de merge,
  Alcance, riesgo residual). Ese puntero ya existe en la misma seccion de `AGENTS.md`; `[G1]`
  no anade un REF nuevo, anota que esa cadena REGLA/CUANDO/POR QUE/SALIDA/REF sigue el esquema
  formal del eje G.

**Riesgo residual declarado (NORMA, no barrera):** si `AGENTS.md` cambia el texto de esa
seccion, esta entrada NO se actualiza sola -- nada la cablea. Quien edite esa seccion debe
revisar que esta anotacion sigue siendo correcta en el mismo commit; no hay guard que lo
fuerce (mismo criterio [F8] declarado arriba para el esquema completo).

Futuras capsulas transversales (fuera del rol builder/manager/revisor, fuera de colision de
triggers de skills) se anaden aqui como `G2`, `G3`... siguiendo el mismo principio: mapear
campos a su ubicacion real, nunca reescribirlos.
