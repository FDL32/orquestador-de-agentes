# Follow-up: `check_context_budget.py` obsoleto (gates absolutos)

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre.
- **deliverable_type:** code (upgrade o retire del script + cableado).
- **delivery_authority:** repo_motor
- **Prioridad:** Media (WARN no-bloqueante: el script mide un invariante % retirado).

## Objetivo

Upgrade `scripts/check_context_budget.py` a los dos gates absolutos del protocolo
`doc_optimization.md` (PASO 1), o bien retirarlo a favor de `check_cuspide_growth_and_drift.py`.

## Antecedentes

El contrato P6 (Seccion 7, deuda 1) declaro que:
- `check_context_budget.py` mide `pct = tokens_proxy/ventana` con tope 5%, un invariante
  retirado el 2026-10-18.
- El invariante actual son los gates absolutos: Codex 32768 B, Claude Code 40000 chars.
- `check_cuspide_growth_and_drift.py` ya mide AMBOS gates en unidad nativa y esta cableado.
- `check_guard_wiring.py` declara: `check_context_budget -> WOT-2026-071a`.

## Contrato del fix (minimo)
- Opcion A: Upgrade `check_context_budget.py` a los dos gates absolutos, midiendo bytes
  (Codex) y chars (Claude Code) de `AGENTS.md` y el cierre `CLAUDE.md`+`@imports`.
- Opcion B: Retirar `check_context_budget.py` y migrar su cableado a
  `check_cuspide_growth_and_drift.py`. Si se elige B, la salida real de hoy es:
  `pct=10.4` (cifra sin significado bajo el protocolo vigente; la medida con sentido
  es 2,48x Codex / 2,08x Claude -- ya actualizada en P6).
- Decision del usuario sobre A o B.

## Recibo de salida real HOY

    python scripts/check_context_budget.py --json -> total_chars=78823, pct=19.7
    (cifra sin significado bajo el protocolo vigente)

## Non-goals
- No cambiar los gates absolutos (decisión de producto).
- No reestructurar AGENTS.md (eso es `agents-md-over-quota-followup.md`).

## Criterio binario de cierre
- [ ] `check_context_budget.py` mide los gates absolutos (A) o fue retirado (B).
- [ ] Cableado actualizado en `.pre-commit-config.yaml`.
- [ ] `ruff` + `pytest` verdes.
