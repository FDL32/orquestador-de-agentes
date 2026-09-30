# DEC-086K-001: ancla temporal del parser de reset y punto de escritura de cuarentena del canal agent

**Ticket:** WOT-2026-086k (bloqueado por dependencia WOT-2026-086d, ya commiteada)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre el BLOCKER y los MAJOR de
`audit_cf_ticket_contract` para T-086K-001).
**Origen de la auditoria:** `<DESTINO>/.agent/planning/REVISION_decisiones_tickets_086_20260930.md:761-809`
(auditoria sobre HEAD `b541943`; 1 BLOCKER, 6 MAJOR).

---

## DECISION 1 (D2, ancla temporal): ancla = timestamp del EVENTO; hora vencida -> TTL, nunca "+1 dia"

Se RECHAZA la regla original "hora ya pasada hoy -> mañana" por ser una heuristica NO medida (prohibida
por el charter, NG-RAIZ). Se adopta:

- **Ancla = el timestamp del EVENTO de fallo** (cuando ocurrio el fallo real), NO el momento en que se
  ejecuta `quarantine --sync` despues. Motivo: un sync horas mas tarde no debe alargar artificialmente la
  cuarentena.
- Formato **solo-hora** (`%-I:%M %p`, ej. "3:05 PM"): se interpreta como esa hora en la MISMA fecha local
  que el timestamp del evento. Si el resultado es `<= timestamp del evento` (la hora ya paso ese mismo
  dia), el resultado es `None` y se aplica el TTL por defecto -- **nunca se asume "mañana"**.
- Formato **con fecha explicita** (`%b %-d(st|nd|rd|th), %Y %-I:%M %p`, ej. "Jul 28th, 2026 7:56 PM"): se
  parsea como fecha absoluta literal, sin ambiguedad.
- Formato **"try again later"** (sin hora): `None`, TTL por defecto.
- El parser NO distingue mayusculas/minusculas para las tres variantes (el productor real, `codex.exe`,
  emite variaciones de capitalizacion).

## DECISION 2 (D1, punto de escritura): se anade la llamada en `run_loop_round`, rama agent, mismo esquema

Se confirma: en `run_loop_round`, en la rama SIN excepcion donde el canal `agent` devuelve texto con
`failure_mode` que empieza por el prefijo de transporte fallido y la clase es `quota_exhausted` (o
`network_timeout`), se llama a `append_fallback_event` **sin cambiar su tupla de campos existente**
(`fallback_profile`/`fallback_backend`/`fallback_backend_key` = `null` donde no aplique, porque el canal
agent no tiene sustituto automatico hoy). `run_pipeline` (otra ruta que tambien puede fallar en el canal
agent) queda declarado NON-GOAL explicito de este ticket -- no se toca.

`failure_detail` toma los **ultimos 300 caracteres** de la cola de stderr (o la linea que contiene el
marcador de cuota), no los primeros 300 -- corrige el defecto medido donde el eco del prompt (~1140
caracteres) desplaza la hora de reset fuera del corte de cabeza.

---

## Impacto en el contrato formal T-086K-001

Estas 2 decisiones resuelven el BLOCKER de D4 (mutacion no binaria) dandole una fuente reproducible
(fixture con procedencia declarada: el `stderr_real` ya existente en
`tests/unit/test_run_codex_audit.py:398-405` mas una variante solo-hora construida con el formato real de
`codex.exe`), y los MAJOR de ancla temporal, formatos incompletos y punto de escritura. Los MINOR restantes
(Premise Re-check no literal, Objective-Link que promete de mas, integracion con 086h) se resuelven en la
reescritura del contrato con criterios binarios, no requieren decision de producto adicional.

**No se retira** la regla de `ensemble_loop.md` seccion 2 de que `loop-round` sigue llamando al perfil
pedido aunque este en cuarentena -- este ticket solo anade VISIBILIDAD (cuarentena en `quarantine --sync`,
exclusion como sustituto, omision en smoke/preflight), no bloqueo del refuter explicito.
