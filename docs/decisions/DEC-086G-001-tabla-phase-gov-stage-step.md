# DEC-086G-001: tabla `phase -> (gov_stage, step)` cerrada, derivacion y filas historicas

**Ticket:** WOT-2026-086g (bloqueado por dependencia WOT-2026-086f; ya aterrizo, pero sin un
vocabulario de `step` propio -- ver nota de bloqueo abajo)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (mismo ciclo de decisiones que `DEC-086H-001`/`DEC-086K-001`).

**Nota de materializacion tardia (2026-10-09):** esta DEC se decidio en la fecha arriba indicada
pero su fichero no se habia escrito como tal -- el texto solo vivia dentro del contrato
`T-086G-001` (`ticket_contracts.md`). Se materializa ahora porque `WOT-2026-088g` (guard de
citas DEC en `ticket_contracts.md`) la encontro citada como `DECIDED` sin fichero real. El
CONTENIDO de las 5 decisiones no cambia respecto a lo ya redactado en el contrato; esto solo
traslada ese texto a su ubicacion canonica.

---

## DECISION 1: tabla `phase -> (gov_stage, step)` CERRADA

Tabla cerrada, cubriendo TODAS las etapas de gobierno medidas (`CONTRACT_AUDIT`,
`MANAGER_REVIEW`, `CLOSE`, `IMPLEMENTATION_REVIEW`, `MEMORY_AUDIT`, `ADJUDICATION`,
`PROPOSAL_AUDIT`, y las demas medidas al activar el ticket).

**Se RECHAZA** la regla "no mapeado -> step": un valor de `phase` que no resuelva en la tabla no
se asume automaticamente como paso de bucle.

## DECISION 2: `challenge-fanout`/`challenge-fanout-lector-fs` son PASOS

Su `gov_stage` se deriva de la etapa de gobierno ACTIVA de esa corrida (no un valor fijo
hardcodeado). `GOVERNMENT_PHASES` sigue exigiendo nonce para ellos -- eso no cambia con esta DEC.

## DECISION 3: valor de `phase` fuera de la tabla cerrada

Un valor de `phase` que no esta en la tabla cerrada produce `(gov_stage=null, step=null)` mas un
aviso visible con su cuenta.

**Se RECHAZA** normalizar variantes de formato (minusculas/guiones) antes de buscar en la tabla:
la tabla se busca con el valor literal, sin normalizacion previa.

## DECISION 4: filas historicas con `phase` de tipo paso

Las filas historicas (1091 medidas en la fecha de esta decision) con `phase` de tipo paso quedan
con `gov_stage=null` PERMANENTE.

**Se RECHAZA** inferir `gov_stage` desde `task_type`: seria una heuristica no medida, prohibida
por el charter del motor (`NG-RAIZ`).

## DECISION 5: origen del vocabulario de `step`

El vocabulario de `step` sale del registro `loop_shapes` de `agents.json` TRAS `WOT-2026-086f`
(no de la propuesta original de diseno ni de una lista cerrada independiente).

**Consecuencia de secuenciacion (bloqueo vigente, no resuelto por esta DEC):** `086g` no puede
redactar su tabla de vocabulario de `step` hasta que `086f` deje ese vocabulario disponible en el
registro. Medido en `WOT-2026-089x`/sesion `closeout-preflight` (2026-10-09): `086f` SI aterrizo
(commit `52a68e0`, 2026-09-30), pero su propio mensaje de commit declara explicitamente
*"registro parametrico de formas... SIN steps propios"* -- las 17 formas propias tienen
`"steps": []` vacio sin excepcion, y los 4 alias legacy no tienen campo `steps` en absoluto. Esto
NO es un hueco accidental: es una decision arquitectonica de `086f` que nunca se propago de vuelta
al contrato `T-086G-001`. El ticket `086g` sigue `status: draft` y BLOQUEADO hasta que un
Contract Formation nuevo decida el vocabulario de `step` (campo separado en `agents.json`, o una
ampliacion de `086f` con un segundo commit) -- ver la fila de `086g` en `backlog.md` y la nota en
`BITACORA.md` de la sesion `closeout-preflight`.

---

## Impacto en el contrato formal `T-086G-001`

Estas 5 decisiones resuelven el DISENO de la tabla; el bloqueo operativo de secuenciacion
(Decision 5) sigue vigente porque `086f` no dejo el vocabulario de `step` disponible. El contrato
permanece `status: draft` hasta que ese bloqueo tenga su propia resolucion.
