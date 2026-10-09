# DEC-088G-001: alcance de "cita DEC", filtro por status, y disposicion de DEC-086G-001

**Ticket:** WOT-2026-088g (bloqueado por `CG-WOT-2026-088g.md` tras el primer intento del
Builder)
**Fecha:** 2026-10-09
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-10-09 (respuestas via `AskUserQuestion` sobre las 3 opciones
abiertas en `CG-WOT-2026-088g.md`).

---

## DECISION 1: alcance de "cita" -- SOLO citas con forma (literal + ruta en el MISMO parentesis)

Una "cita" de DEC en `ticket_contracts.md` es el literal `DEC-<id>` seguido, dentro del MISMO
parentesis, de una ruta `docs/decisions/DEC-<id2>-`. Si `id == id2` y el fichero existe: OK. Si
`id == id2` pero el fichero no existe: ERROR. Si `id != id2` (cita cruzada): ERROR ("sin
resolver").

**Se RECHAZA** tratar TODA mencion de prosa de `DEC-<id>` (sin ruta en la misma linea) como
"cita sin resolver": medido sobre el fichero real, esa lectura marca 55 lineas ERROR + 19 WARN de
menciones legitimas (p.ej. "`DEC-079A-001` materializada en esta sesion..."), dejando el guard
incapaz de ponerse verde sobre el fichero que debe validar. Las menciones de prosa SIN ruta en la
misma linea NO son citas y se ignoran.

## DECISION 2: alcance por status -- SOLO contratos `status: frozen`

El guard inspecciona EXCLUSIVAMENTE los contratos cuya cabecera declara `status: frozen`. Un
contrato `draft` (como `T-086G-001`) queda FUERA del universo que el guard valida.

**Motivo:** coincide con la premisa original del ticket ("un contrato `frozen` que el Builder
ejecuta puede citar una DEC inexistente") -- el riesgo real es que un Builder confie en un
contrato YA CONGELADO. Un contrato `draft` todavia esta en formacion y su propio proceso de
congelacion (`validate_contract_formation.py` u homologo) es la barrera que corresponde a esa
etapa, no este guard.

**Se RECHAZA** inspeccionar todos los contratos sin distinguir status: eso habria dejado el
unico hallazgo real medido (`DEC-086G-001`, citada en un contrato `draft`) como bloqueante de
ESTE guard, cuando la resolucion de ese hallazgo pertenece al bloqueo de secuenciacion propio de
`WOT-2026-086g` (ver `DEC-086G-001`), no a `WOT-2026-088g`.

## DECISION 3: disposicion del hallazgo vivo `DEC-086G-001` -- MATERIALIZAR AHORA

Se materializa `docs/decisions/DEC-086G-001-tabla-phase-gov-stage-step.md` (ver ese fichero) en
el mismo acto que esta DEC, documentando las 5 decisiones que `T-086G-001` ya declaraba como
tomadas en prosa. El bloqueo de SECUENCIACION de `086g` (vocabulario de `step` pendiente de
`086f`) sigue vigente y no lo resuelve esta materializacion -- solo deja de haber una DEC citada
como DECIDED sin fichero real.

**Consecuencia practica:** tras esta DEC y la Decision 2 de arriba, `DEC-086G-001` deja de ser un
hallazgo vivo del guard de `WOT-2026-088g` por DOS vias independientes: (a) el fichero ya existe,
y (b) aunque no existiera, `T-086G-001` es `draft` y queda fuera del universo inspeccionado.

---

## Impacto en el contrato formal `T-088G-001`

Estas 3 decisiones resuelven las 2 ambiguedades que `CG-WOT-2026-088g.md` identifico (alcance de
"cita", filtro por status) y la disposicion del hallazgo vivo. El contrato se re-congela
(`status: frozen`) con el regex y el filtro de Decision 1/2 de esta DEC. El Builder retoma desde
cero (su primer intento no toco ninguna Forbidden Surface ni escribio codigo de produccion).
