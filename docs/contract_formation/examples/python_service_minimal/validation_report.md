# validation_report.md -- WOT-2026-007b

> Evidencia de la validacion vertical del Contract Formation Pipeline v0.
> Generado durante la sesion 2026-06-15.

---

## 1. Context Baseline

| Campo | Valor |
|-------|-------|
| repo_motor git_head | 7bf57f8 (Contract Formation Pipeline v0) |
| repo_destino validate_result | OK, 0 errors, 0 warnings |
| generated_at | 2026-06-15 |

No hay warnings de validate al arrancar: pipeline puede iniciarse directamente.

---

## 2. Builder Clarification Rate

| Metrica | Valor |
|---------|-------|
| Tickets en el ejemplo | 1 (T-HEALTH-001) |
| Preguntas que el Builder necesitaria hacer | 0 |
| Motivo | El ticket_contract incluye Premise, Premise Re-check, Files Likely Touched, Forbidden Surfaces, DoD, STOP y CONTRACT_GAP behavior. Sin ambiguedad. |
| **Resultado** | **clarification_rate = 0 de 1 = 0** |

El objetivo del ticket (rate = 0) se cumple para este arquetipo.

---

## 3. Premise Re-check (demo read-only)

Antes de activar T-HEALTH-001, el Manager ejecuta checks de entorno (python version,
uv dry-run, existencia de service.py). Si alguno falla: CONTRACT_GAP. Sin improvisacion.

---

## 4. Impact Simulation -- hallazgo

La Impact Simulation de PLAN-001 detecto colision latente:
- Si existiera PLAN-002 modificando pyproject.toml (dependencias de BD),
  el lock-file seria shared_dependency con riesgo de conflicto.
- Decision: serializar cualquier PLAN-002 despues de PLAN-001.

---

## 5. Prueba Destructiva -- violacion de Non-Goal

Escenario: propuesta de anadir tabla SQLite para registrar uptime.

Cadena de bloqueo:
1. Negative Audit Checklist del charter: Introduzca BD state persistente (viola Non-Goal).
2. Auditor aplica Intent Audit y detecta contradiccion con Non-Goals del charter.
3. Ticket T-HEALTH-001 lista .db y migrations en Forbidden Surfaces.
4. Si el Builder recibe la peticion por error: STOP condition, emite CG-T-HEALTH-001.md.

Conclusion: la propuesta destructiva queda bloqueada en genesis antes de llegar al Builder.

---

## 6. Intent Audit (demo)

Auditor revisa T-HEALTH-001 contra el charter:
- Product Intent: smoke-test minimo -- cumple (un endpoint, nada mas).
- Non-Goals: no persistencia, no auth -- Forbidden Surfaces garantizan que no se tocan.
- Quality Bar: ruff + test de humo -- el DoD los incluye.
- Security Constraints: no credenciales -- el DoD no pide BD ni env vars.

Resultado: Intent Audit PASS. Ticket avanza a status: frozen.

---

## 7. Pending-contract recheck (demo)

Si despues de cerrar T-HEALTH-001 se abriera T-HEALTH-002 modificando pyproject.toml:
- Si muta el lock-file, la premisa de contratos que asuman el lock-file estable queda invalida.
- El orquestador marca esos contratos CONTRACT_INVALID y los devuelve a genesis.

---

## 8. Gates

| Gate | Resultado |
|------|-----------|
| encoding check archivos md del ejemplo | exit 0 (verificado al cerrar) |
| validate destino | 0 errors, 0 warnings |

---

## 9. Conclusion

El Contract Formation Pipeline v0 produce contratos suficientes para clarification_rate = 0.
Los mecanismos de defensa (Negative Audit, Intent Audit, Forbidden Surfaces, STOP,
CONTRACT_GAP) funcionan en capas: genesis bloquea primero, Builder como red de seguridad.

**007a queda ratificado para arquetipos de complejidad similar.**

Limitaciones que los tickets siguientes deben cubrir:
- 007c: validador documental que automatice la verificacion de campos del contrato.
- 007d: prompts de auditoria fino como skills invocables.
- 007e: endurecimiento mecanico de reglas de paralelismo en plan_graph.
