# DEC-085A-001: derivacion en memoria sin escritura, y alcance acotado a cuarentena visible

**Ticket:** WOT-2026-085a (ficha VIVA del backlog, distinta de WOT-2026-087a)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre los 2 BLOCKER de
`audit_cf_ticket_contract` para T-085A-001).
**Origen de la auditoria:** `<DESTINO>/.agent/planning/REVISION_decisiones_tickets_086_20260930.md:811-859`
(auditoria sobre HEAD `b541943`; 2 BLOCKER, 3 MAJOR).

---

## DECISION 1 (escritura vs solo-lectura): el recolector deriva en MEMORIA, sin invocar `quarantine --sync`

`scripts/collect_session_state.py` esta declarado explicitamente de solo lectura ("ejecuta comandos
read-only ... No escribe"), y `prompts/session_hop.md` tambien ("Solo lectura ... como mucho lo escribe en
`<DESTINO_ROOT>/orchestrator_pipeline/arranques/`"). El DoD original pedia ejecutar
`ensemble_dispatch.py quarantine --sync`, que SI escribe `backend_quarantine.json` en el runtime del
destino -- contradiccion directa con ambos contratos vigentes.

**Se decide: el recolector reutiliza las funciones existentes (`_quarantine_buckets`, `_quarantine_tables`)
sobre `fallback_events.jsonl` DIRECTAMENTE, calculando el resultado en memoria** (mismo patron que ya usa
`collect_mode` para otras superficies: subprocess `python -c` que importa `ensemble_dispatch` y aplica la
derivacion sin invocar el CLI de escritura). El recolector **NO invoca `quarantine --sync`** y **NO
escribe** `backend_quarantine.json`. `session_hop.md` NO entra en Forbidden Surfaces nuevas: su contrato de
solo lectura se mantiene intacto.

## DECISION 2 (alcance): 085a se limita a la cuarentena visible al arranque; el resto de T4 es de WOT-2026-086h

El prompt canonico (`prompts/ensemble_loop.md:164`, source_of_truth) y la propuesta original
(`PROPUESTA_bucles_revision_integral_20260929.md`, T4) asignaban a `085a` tanto la cuarentena visible como
el "estado unificado de proveedores y descubrimiento `/v1/models`" (`backend_scoreboard.json`). Esa segunda
parte ya se decidio absorber en `WOT-2026-086h` (`DEC-086H-001` Decision 3, esta misma sesion).

**Se decide: `WOT-2026-085a` se queda EXCLUSIVAMENTE con la cuarentena visible al arranque de sesion.** El
`backend_scoreboard.json` y el descubrimiento `/v1/models` quedan como Non-goal EXPLICITO de este ticket
(ya cubiertos por `086h`). `prompts/ensemble_loop.md:164` se actualiza para reflejar la division real:
cuarentena -> `085a`; estado unificado + `/v1/models` -> `086h`.

**Limite declarado (ya medido, no cambia con esta decision):** el fix solo cubre `quota_exhausted` y
`network_timeout` del canal `api` que ya escribieron un evento en `fallback_events.jsonl`. El canal `agent`
(codex/opencode) queda fuera hasta que `WOT-2026-086k` aterrice; un fallo `401`/auth se clasifica `unknown`
y no entra en cuarentena por diseno del clasificador (fuera de alcance de este ticket).

---

## Impacto en el contrato formal T-085A-001

Estas 2 decisiones resuelven los 2 BLOCKER (colision de contrato de escritura; alcance indefinido frente a
086h/T4) que impedian congelar el contrato. Los 3 MAJOR restantes (DoD sin node-ids de test ni mutacion
real; falta de criterio para fuente ausente/corrupta; Non-goals sin declarar el limite de canal) se
resuelven en la reescritura del contrato con criterios binarios, no requieren decision de producto
adicional.
