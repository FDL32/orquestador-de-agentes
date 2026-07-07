# Plan de Trabajo: Promover regla CONTRACT_GAP a memoria portable

## Metadata
- **ID:** WOT-2026-020b
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Creado:** 2026-07-07
- **delivery_authority:** repo_motor

## Objetivo

Promover a memoria PORTABLE del motor (UPSTREAM_LEARNINGS.md) la regla
generalizable: un campo REQUERIDO por un gate que NO tiene fuente en el schema
de entrada frozen es un CONTRACT_GAP, NO se resuelve aliasando el campo mas
cercano. Un gate con check presence-only deja pasar el alias -> artefacto
semanticamente corrupto (floor assertion a nivel de artefacto).

## Contexto

Evidencia origen: CTL-2026-010a. GATE_FIELD_MAP aliasaba country<-idioma_origen;
IntakeCompletenessGate (quality_gate.py:381) exige country pero
docs/schemas/intake_request.md v1+v2 no lo provee. Mutation-verify confirma que
retirar el alias rompe 4 tests. OK humano ya dado (2026-07-07).

## Files Likely Touched
- `.agent/runtime/memory/UPSTREAM_LEARNINGS.md`

## Non-goals
- NO modificar observations.jsonl del destino (la regla va en UPSTREAM_LEARNINGS.md del motor, no en observations.jsonl)
- NO crear tests (es documentation; la barrera es el mutation-verify de CTL-2026-010a ya existente)
- NO tocar codigo productivo (quality_gate.py, GATE_FIELD_MAP, schemas)

## Decision Arquitectonica

La regla se promueve a UPSTREAM_LEARNINGS.md (memoria portable del motor) en
vez de observations.jsonl del destino, porque es generalizable entre destinos:
cualquier destino con gates de completitud que exijan campos sin fuente en su
schema frozen se beneficia de la regla. UPSTREAM_LEARNINGS.md es la superficie
canonica para aprendizajes del motor con evidencia y TTL permanente.

## Criterios de aceptacion (DoD)
- [x] la regla escrita en la superficie portable del motor (UPSTREAM_LEARNINGS.md)
- [x] gate de schema-drift de observations.jsonl verde (validate_observations.py --strict exit 0)
- [x] sin duplicar en observations.jsonl del destino

## Review
Single-review (documentation, blast-radius acotado).
