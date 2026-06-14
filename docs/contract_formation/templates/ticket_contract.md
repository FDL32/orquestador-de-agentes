# Ticket Contract - <TICKET_ID> (PLANTILLA)

> Un bloque por ticket real dentro de `DESTINO_ROOT/.agent/planning/ticket_contracts.md`.
> Solo un contrato `status: frozen` puede convertirse en `work_plan.md`.
> Todo campo del `work_plan` debe provenir de aqui: el Builder no inventa.

## <TICKET_ID> - <titulo>
- **ticket_id:** WOT-2026-NNNx | WP-2026-NNNx
- **status:** draft | review | frozen | invalidated
- **deliverable_type:** code | documentation | research | analysis | mixed
- **delivery_authority:** repo_motor | repo_destino
- **Objective-Link:** OBJ-00x
- **Plan-Link:** PLAN-00x
- **Premise:** <premisa verificable del ticket: que estado del mundo asume>
- **Premise Re-check (read-only):**
  `<comando read-only que reproduce y confirma la premisa antes de implementar>`
- **Context Baseline Evidence:** `git_head`, `git_status`, `validate_result`,
  `local_audit_result` (si hay comando), `generated_at`.
- **Files Likely Touched:**
  - Builder: <rutas que el ticket crea/modifica>
  - Read/inspect only: <fuentes que se leen pero no son entregables>
- **Forbidden Surfaces:** <superficies prohibidas derivadas del plan y sus
  dependencias; las protege el scope-gate>
- **DoD (criterios binarios de cierre):**
  - [ ] <criterio 1>
  - [ ] <criterio 2>
- **Integracion cross-ticket:** <que tickets tocan superficies compartidas y
  como se serializa/coordina>
- **CONTRACT_GAP behavior:** si la premisa es falsa, hay ambiguedad, se necesita
  una `Forbidden Surface`, falta criterio de aceptacion o hay conflicto de
  dependencias -> emitir `CG-<TICKET_ID>.md`, bloquear, devolver a genesis.
- **Builder clarification budget:** 0 (objetivo). Si el Builder necesita
  preguntar intencion de producto, es fallo de contrato, no del Builder.
- **STOP conditions:** <cuando parar y escalar/abrir follow-up>
- **Depende de:** <TICKET_ID(s)> | -

> Trazabilidad: `OBJ-00x -> PLAN-00x -> <TICKET_ID> -> commit -> aceptacion`.
