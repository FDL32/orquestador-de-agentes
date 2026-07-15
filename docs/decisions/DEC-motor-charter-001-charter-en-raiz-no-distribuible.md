# DEC-motor-charter-001: Charter del motor en la raiz, no distribuible

**Ticket:** (prerequisito de WOT-2026-024f-A; habilita el Intent Audit del contract-audit)
**Fecha:** 2026-07-15
**Estado:** DECIDED
**Autor:** Usuario (aprobado en sesion 2026-07-15)

## Contexto

El contract-audit adversarial de `WOT-2026-024f-A` (2a pasada) descubrio que
`.agent/planning/` del motor solo contenia `ticket_contracts.md`: **no existian
`repo_charter.md` ni `plan_graph.md`**. El procedimiento `audit_cf_ticket_contract.md`
los declara entrada obligatoria para el Intent Audit (Non-Goals / Quality Bar /
Security Constraints) -> ese paso era **NO MEDIBLE**, y el prompt manda **escalar, no
parchear** el ticket aislado.

Ironia medida: el motor **exige a sus destinos** un `repo_charter.md` (hay template,
ejemplo completo y prompt de auditoria dedicado; varios destinos lo tienen) y el propio
motor no lo cumplia. Es la familia "predica una norma que no se aplica".

## Decision

1. **El motor tiene su `repo_charter.md` y su `plan_graph.md` en la RAIZ del repo**
   (`<motor>/repo_charter.md`, `<motor>/plan_graph.md`), **no** en `.agent/planning/`,
   porque el motor **no es un `repo_destino`**.
2. **NO son distribuibles.** No figuran en `MANIFEST.distribute` (allowlist literal de 52
   entradas; verificado por pertenencia, no por glob: `repo_charter.md`/`plan_graph.md`
   NO estan en el set). No hace falta editar el MANIFEST; basta documentar y verificar que
   quedan fuera.
3. `prompts/audit_cf_repo_charter.md` resuelve la ruta del charter **primero en la raiz del
   motor, luego en `.agent/planning/` del destino** (editado en esta sesion).
4. El charter define la **portabilidad** y los **Non-Goals** del motor. Su Non-Goal raiz:
   **el motor no decide politica por heuristica** — cuando falta contrato/charter/DEC, falla
   explicito o pide DEC.

## Alcance / Non-goals de esta DEC
- NO reescribe `MANIFEST.distribute` (queda fuera por allowlist; solo se documenta/verifica).
- NO crea un `decisions.md` agregado; las DEC viven en `docs/decisions/` (precedente).
- NO implementa `WOT-2026-024h` (seed neutro): esa es una decision de ejecucion aparte, que
  este charter habilita como NG-1.

## Evidencia
- `command:` `.venv/Scripts/python.exe scripts/validate_contract_formation.py --charter repo_charter.md` -> `exit 0, 0 errors`.
- `command:` `.venv/Scripts/python.exe scripts/validate_contract_formation.py --plan plan_graph.md` -> `exit 0, 0 errors`.
- `path:` `MANIFEST.distribute` (52 entradas; `repo_charter.md`/`plan_graph.md` ausentes).
