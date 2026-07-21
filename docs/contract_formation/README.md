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
   Prompts especializados por artefacto (WOT-2026-007d), que enrutan ese marco:
   [`audit_cf_repo_charter.md`](../../prompts/audit_cf_repo_charter.md),
   [`audit_cf_plan_graph.md`](../../prompts/audit_cf_plan_graph.md),
   [`audit_cf_ticket_contract.md`](../../prompts/audit_cf_ticket_contract.md).

## Plantillas

Rellenar copiando a `DESTINO_ROOT/.agent/planning/` (no editar las plantillas
del motor).

> **Esta es la UNICA via de bootstrap del planning de un destino** (WOT-2026-024h,
> DEC-024H-001). El motor NO versiona ya `.agent/planning/ticket_contracts.md` y un
> `install` fresco NO deposita ningun contrato: hasta 2026-07-21 embarcaba 49881 B
> con 3 contratos REALES de su propio dogfooding (021k/023r/023s), que aterrizaban
> en cada destino nuevo. El destino crea su planning copiando estas plantillas; lo
> que produzca es SUYO y ni `--sync` ni la poda lo tocan (WOT-2026-024d).
> No re-introduzcas un seed ni un placeholder en el motor: el CONTRACT_GAP
> `CG-WOT-2026-024h.md` probo que ninguna forma pasa `validate_contract_formation`.
> Barrera: `scripts/check_distributable_planning_clean.py` (closeout, bloqueante).

| Plantilla | Instancia destino |
|-----------|-------------------|
| [`templates/repo_charter.md`](templates/repo_charter.md) | `.agent/planning/repo_charter.md` |
| [`templates/evidence_catalog.md`](templates/evidence_catalog.md) | `.agent/planning/evidence_catalog.md` |
| [`templates/ticket_contract.md`](templates/ticket_contract.md) | bloque en `.agent/planning/ticket_contracts.md` |
| [`templates/contract_gap.md`](templates/contract_gap.md) | `.agent/planning/contract_gaps/CG-<TICKET_ID>.md` |
| [`templates/plan_graph.md`](templates/plan_graph.md) | `.agent/planning/plan_graph.md` |

`decisions.md` (cola de `DEC-*`) sigue el schema del prompt (seccion 6).
`plan_graph.md` tiene plantilla dedicada (endurecida en `WOT-2026-007e`):
Impact Simulation obligatoria, `paralelizable: yes/no/after` y Merge Regression Audit.

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
