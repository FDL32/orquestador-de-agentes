# Contract Gap - CG-<TICKET_ID> (PLANTILLA)

> Copia a `DESTINO_ROOT/.agent/planning/contract_gaps/CG-<TICKET_ID>.md`.
> Lo emite el Builder (o el orquestador) cuando un contrato `frozen` resulta
> obsoleto o incompleto EN EJECUCION. Bloquea el ticket y lo devuelve a genesis.
> Es fallo de contrato, NO del Builder. Mantiene al usuario fuera del loop de
> ejecucion (la integracion runtime es `WOT-2026-007f`).

## CG-<TICKET_ID>
- **ticket_id:** <TICKET_ID>
- **detected_by:** BUILDER | ORCHESTRATOR | AUDITOR
- **gap_type:** premise_false | ambiguity | forbidden_surface_needed |
  missing_acceptance | dependency_conflict
- **detected_at:** YYYY-MM-DD
- **evidence:** <comando + salida / diff / ruta que demuestra el gap>
- **description:** <que esperaba el contrato vs que es cierto ahora>
- **blocks:** <que parte del ticket queda bloqueada>
- **requested_resolution:** <que debe decidir/redefinir genesis; si toca
  intencion de producto, proponer `DEC-*`>
- **contract_status_effect:** frozen -> invalidated

## Handoff
- El ticket queda BLOQUEADO; no se improvisa una implementacion alternativa.
- Genesis re-evalua el `ticket_contract`, emite `DEC-*` si hay decision humana,
  y solo re-congela (`status: frozen`) cuando el gap esta resuelto.
