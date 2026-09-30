# DEC-086H-001: taxonomia de smoke, precedencia de timeout y alcance (absorbe /v1/models)

**Ticket:** WOT-2026-086h (bloqueado por dependencia WOT-2026-086c, ya commiteada)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre los 2 BLOCKER y 4 MAJOR de
`audit_cf_ticket_contract` para T-086H-001).
**Origen de la auditoria:** `<DESTINO>/.agent/planning/REVISION_decisiones_tickets_086_20260930.md:677-750`
(auditoria sobre HEAD `b541943`; 2 BLOCKER, 5 MAJOR).

---

## DECISION 1 (D2): taxonomia de 8 clases de la propuesta P7; `ok_razonador` CUENTA como disponible

Se adopta la taxonomia completa de `PROPUESTA_bucles_revision_integral_20260929.md` P7 (8 clases), no
las 4 clases actuales de `_classify_transport_failure` (que solo cubre casos de transporte fallido, no
"disponible pero lento"):

`ok`, `ok_razonador` (200 sin `content` pero con deltas `reasoning_content`: el modelo SI responde,
solo tarda pensando -- **CUENTA como disponible**), `quota_exhausted`, `sin_acceso` (401/403),
`model_unavailable`, `lento` (timeout del smoke; **NO se excluye** del pool, solo se marca lento),
`proveedor_caido` (502/503/504/524), `respuesta_sin_token` (fallo de validacion del nonce).

**Se RECHAZA** el estado actual (el razonador que agota tokens pensando queda marcado como no-vivo/
`unknown`): es un falso negativo medido -- el modelo esta disponible, solo es lento.

`_classify_transport_failure` (usada por `loop-round` y otras rutas) solo admite ADICION de estas clases
nuevas; sus 4 clases actuales NO se retiran ni cambian de significado (no-regresion para el resto del
sistema).

## DECISION 2 (D1): `--timeout` del smoke es el TECHO EFECTIVO, gana a `timeout_s` del backend

En la ruta `smoke` especificamente, el valor de `--timeout` pasado por el operador SIEMPRE prevalece
sobre `backends.<b>.timeout_s` declarado en `agents.json` (hoy `send_to_profile:1590` hace lo contrario:
dar precedencia a `timeout_s`, lo que deja a un `--timeout` corto como no-op en 4 de 5 proveedores API).

**Se RECHAZA** dejar que `timeout_s` del backend siga ganando en la ruta smoke.

**Alcance de la correccion:** SOLO afecta a la ruta `smoke`. `loop-round` (fuera del smoke) sigue
respetando `timeout_s` del backend sin cambios -- esta decision no toca el comportamiento de gobierno.

## DECISION 3 (D3): 086h ABSORBE el descubrimiento `/v1/models`; `deliverable_type` pasa a `mixed`

Existia una colision de responsabilidad: el contrato canonico ya commiteado (`prompts/ensemble_loop.md`
seccion 8) y la ficha original asignaban "estado unificado de proveedores y descubrimiento `/v1/models`"
a `WOT-2026-085a` (renumerada esta misma sesion a `WOT-2026-087a` por colision de ID con una `085a`
distinta ya viva en el backlog -- ver `<DESTINO>/.agent/collaboration/backlog_inbox/
FP-20260930-motor-recuperado-estado-proveedores.tickets.md`), pero `T-086H-001` tambien la reclamaba
(D3, titulo, trazabilidad P11).

**Se decide: 086h absorbe `/v1/models` por completo.** Motivo: ambas funcionalidades tocan el mismo
momento de arranque (verificar disponibilidad de proveedores antes de gastar completions) y comparten el
mismo Forbidden Surface (`send_to_profile` como unico camino de salida de red declarado). Separarlas en
dos tickets distintos duplicaria el trabajo de descubrimiento de estado por proveedor.

**Consecuencias:**
- `deliverable_type` de `T-086H-001` pasa de `code` a `mixed` (codigo + diseno de politica de
  concurrencia, que ya tenia, mas el diseno de descubrimiento `/v1/models`).
- `prompts/ensemble_loop.md` seccion 8 retira TANTO la entrada de "smoke rapido y paralelo" COMO
  "estado unificado de proveedores y descubrimiento /v1/models" -- ambas se resuelven en este ticket.
- La ficha `WOT-2026-087a` (ex `085a` del motor huerfano) se marca `superseded-by:WOT-2026-086h` en
  `backlog_inbox/`, sin dar de alta como ticket independiente.

## DECISION 4 (D1/D6): defaults confirmados; medicion de tokens declarada NO VERIFICABLE cuando falte `usage`

Se confirman los valores por defecto de la propuesta P7: `--timeout 15` (segundos), `--max-tokens 64`,
tope de 4 concurrentes por proveedor (alineado con `prompts/ensemble_loop.md` seccion 3.5, medido
2026-09-29 que 8 concurrentes da 429 en nan).

Para D6 (medicion de tiempo y tokens antes/despues): el modulo `ensemble_dispatch.py` no tiene ningun
instrumento de conteo de tokens hoy (verificado: 0 coincidencias de `usage`/`prompt_tokens`/
`completion_tokens`). Se declara explicitamente: la medicion de TIEMPO DE PARED es obligatoria y
verificable (wall-clock real, antes/despues); la medicion de TOKENS se publica solo si el proveedor
devuelve el campo `usage` en su respuesta, y se declara literalmente `tokens: NO VERIFICABLE` cuando no
lo devuelva -- nunca se inventa un contador nuevo para este ticket.

---

## Impacto en el contrato formal T-086H-001

Estas 4 decisiones resuelven los 2 BLOCKER (D2 contradecia su propia fuente de diseno P7; D1 no era
alcanzable/binario) y los MAJOR de alcance (Forbidden Surfaces incompletas sobre el radio de impacto real
de `smoke_profile` como `check_alive` por defecto de la sustitucion automatica; dueno de `/v1/models`).
Los MAJOR restantes (denominador del probe, `--profile <agente>` explicito) se resuelven en la
reescritura del contrato con criterios binarios, no requieren decision de producto adicional.
