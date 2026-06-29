# Prompt: Auditoria del Ticket Contract (Contract Formation)

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
> Auditoria adversarial de un `ticket_contract` ANTES de congelarlo (`status: frozen`)
> y convertirlo en `work_plan.md`. El objetivo es que el Builder barato implante sin
> preguntar: `Builder clarification rate = 0`.
>
> **No dupliques `audit_agent_output.md`.** El `Intent Audit` (2.b) y la
> `Impact Simulation` (2.c) son la fuente canonica. Aqui los **enrutas y especializas**
> para un ticket concreto; no redefinas el procedimiento.

---

## Entradas obligatorias

Lee antes de evaluar:

- `.agent/planning/ticket_contracts.md` (el bloque del ticket auditado).
- `.agent/planning/repo_charter.md` (`Non-Goals`, `Quality Bar`, `Security Constraints`).
- `.agent/planning/plan_graph.md` (el `PLAN-*` y las `Forbidden Surfaces` derivadas).
- `prompts/contract_formation_pipeline.md` (campos obligatorios y maquina de estados).
- `prompts/audit_agent_output.md` secciones 2.b y 2.c (marco general).
- Para validacion mecanica de campos: `scripts/validate_contract_formation.py`
  (WOT-2026-007c). La auditoria humana/adversarial NO sustituye al validador ni
  viceversa: el script cubre estructura; este prompt cubre intencion y suficiencia.

## Checklist especifica del ticket contract

1. **Campos completos:** `status`, `Objective-Link`, `Plan-Link`, `Premise`,
   `Premise Re-check`, `Files Likely Touched`, `Forbidden Surfaces`, DoD, STOP,
   `CONTRACT_GAP behavior`, `Builder clarification budget`. Un campo ausente bloquea.
2. **Premise verificable read-only:** el `Premise Re-check` es un comando read-only
   reproducible, no una afirmacion de fe. Si no se puede reproducir, no es premisa.
3. **DoD binario:** cada criterio de cierre es un comando con exit code o un test
   pass/fail, no "verificar que funcione".
4. **Forbidden Surfaces coherentes con el plan:** las superficies prohibidas derivan del
   `PLAN-*` y de sus `shared_dependencies`; protegen el anti-scope real del ticket.
5. **Suficiencia para clarification = 0:** simula ser el Builder. Hay alguna decision de
   intencion de producto que tendrias que preguntar? Si si, es fallo de contrato, no del
   Builder: marca el hueco para que vuelva a genesis, no para que el Builder improvise.
6. **deliverable_type honesto:** un ticket que dice `documentation` pero cuyo DoD exige
   ejecutar Builder/codigo/tests debe ser `mixed` o abrir ticket separado.
7. **CONTRACT_GAP como unica valvula:** el contrato deja claro que ante premisa falsa,
   ambiguedad, superficie prohibida necesaria o criterio incompleto, el Builder emite
   `CG-<TICKET_ID>.md` y bloquea; no muta el contrato en silencio.
8. **Intent Audit (rutado a 2.b):** contrasta el ticket contra `Non-Goals`,
   `Quality Bar` y `Security Constraints` del charter. Un ticket que cumple su DoD pero
   contradice un Non-Goal debe marcarse riesgo, no aprobarse.
9. **Evidencia minima para frozen:** cada claim central del contrato necesita
   artefacto concreto (`path:`, `command:` + `exit_code:`, `commit:` cuando
   aplique). Una etiqueta sin artefacto es relato y no habilita `frozen`.

## Severidad de hallazgos

- **BLOCKER:** campo obligatorio ausente; DoD no binario; `Premise Re-check` no
  reproducible; el ticket exige una decision de producto no resuelta; contradice un
  `Non-Goal`/`Security Constraint`.
- **MAJOR:** `Forbidden Surfaces` no derivadas del plan; `deliverable_type` mal
  clasificado; `CONTRACT_GAP behavior` ausente o vago; evidencia central sin
  artefacto concreto.
- **MINOR:** redaccion que no bloquea implantacion.
- **NIT:** estilo u orden.

## STOP conditions

- Si el ticket solo es elegible para `frozen` cuando el Builder "asuma" algo: no esta
  listo; devuelvelo a `draft`.
- Si el ticket exige que el usuario escriba codigo o edite contratos: redisenalo como
  `DEC-*`; no apruebes.
- Si auditando descubres que el `plan_graph` o el charter estan mal: escala hacia
  arriba (audit_cf_plan_graph / audit_cf_repo_charter), no parchees el ticket aislado.

## Salida (apta para bucle de mejora)

Entrega:
- `DECISION: APPROVE (frozen-ready) | CHANGES`.
- Hallazgos por severidad, cada uno con el campo del contrato afectado y la correccion.
- Estimacion explicita del `Builder clarification rate` esperado y por que.
- Tabla minima `Claim | Evidencia | Estado` para los claims centrales del contrato.
- Si `CHANGES`, la lista de campos que el Manager debe completar antes de `frozen`.
