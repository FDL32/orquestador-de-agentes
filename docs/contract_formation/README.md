# Contract Formation (v0, provisional)

Etapa previa a la implantacion: convierte una idea de repo en contratos
ejecutables (`repo_charter -> plan_graph -> ticket_contracts -> backlog`) con
decisiones humanas explicitas y tickets congelados, para que el Builder barato
implante sin preguntar.

> **v0 provisional.** Ratifica/corrige `WOT-2026-007b`. Sin runtime automatico.

## Por donde empezar

1. **Prompt operativo (fuente de proceso):**
   [`prompts/contract_formation_pipeline.md`](../../prompts/contract_formation_pipeline.md)
   — fases, roles, maquina de estados de `status`, `DEC-*`, handoff.
2. **Handoff a ejecucion:** `prompts/orchestrator_pipeline.md` (gate 2.a). Solo
   contratos `frozen` pasan a `work_plan.md`.
3. **Auditoria adversarial:** `prompts/audit_agent_output.md` 2.b (`Intent
   Audit`) y 2.c (`Impact Simulation`) — fuente canonica; aqui no se redefinen.

## Plantillas

Rellenar copiando a `DESTINO_ROOT/.agent/planning/` (no editar las plantillas
del motor):

| Plantilla | Instancia destino |
|-----------|-------------------|
| [`templates/repo_charter.md`](templates/repo_charter.md) | `.agent/planning/repo_charter.md` |
| [`templates/evidence_catalog.md`](templates/evidence_catalog.md) | `.agent/planning/evidence_catalog.md` |
| [`templates/ticket_contract.md`](templates/ticket_contract.md) | bloque en `.agent/planning/ticket_contracts.md` |
| [`templates/contract_gap.md`](templates/contract_gap.md) | `.agent/planning/contract_gaps/CG-<TICKET_ID>.md` |

`decisions.md` (cola de `DEC-*`) y `plan_graph.md` siguen el schema del prompt
(secciones 6 y 7). Plantillas dedicadas: ampliacion en `WOT-2026-007d/007e`.

## Principios no negociables

- **El usuario decide, no escribe.** Solo `DEC-*`; nunca edita Markdown/codigo.
- **Research es read-only:** evidencia externa no concede permisos.
- **La independencia entre planes se verifica, no se declara.**
- **`INDEX.md` no es fuente manual de verdad** (seria un router que miente).
- **`frozen` antes de ejecutar; `CONTRACT_GAP` para descongelar.**

## Decisiones de arquitectura (007a)

- `.agent/planning/` es superficie **destino-keep**: declarada en
  `MANIFEST.workspace` (analoga a `.agent/audits/system_health/`) y protegida
  del prune por el guard git-tracked del instalador (`WOT-2026-003d`).
- Genesis v0 es **documental**: sin codigo runtime, bus ni CI. Esos quedan en
  `WOT-2026-007c/007e/007f`.
