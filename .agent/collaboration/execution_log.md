# Execution Log - WOT-2026-015l

**Ticket:** WOT-2026-015l - Gate de cierre: reconciliar backlog vs eventos SUPERVISOR_CLOSED del bus (bidireccional, anti auto-reporte)
**Estado:** COMPLETED
**HEAD al inicio:** 6058fd0
**delivery_authority:** repo_motor | **deliverable_type:** code

> execution_log de 016m (COMPLETED) preservado en `execution_log_WOT-2026-016m.md`
> (el bootstrap de 015l no lo archivo; separado a mano).

## Fase 0 - Diagnostico (EJECUTADA)
- Bus fisico del workspace confirmado: `.agent/runtime/events/events.jsonl` (vivo) +
  `events/archive/*.jsonl` (181 archivos). Runtime GITIGNORED (estado local).
- Esquema de evento verificado en vivo: SUPERVISOR_CLOSED con `event_type`, `ticket_id`,
  `sequence_number`, `actor` (ej. 015i seq 1298).
- Contrato 012a/012b: los terminales NO permanecen en la cola viva -> el drift real es
  "cerrado-en-bus pero aun-pending", no "declarado sin cerrar".
- Fuente B: `_archive/backlog_done.md`, tabla `| Ticket | Estado | Nota |`.

## Fase 1 - Implementacion (EJECUTADA)
- `scripts/check_closeout_reconciliation.py` (nuevo, read-only). Funciones puras:
  `read_bus` (union vivo+archive: {closed:id->seq}, {present}), `read_live_backlog`
  (IDs vivos de `## Vista rapida`), `read_declared_done` (IDs que AFIRMAN cierre),
  `run_gate`.
- Check A (drift) = `closed_bus & live_backlog` (excluye `completed-partial`).
- Check B (orphan) = `(declared_done & present_in_bus) - closed_bus`. Exime pre-bus
  (cero eventos) Y estados no-afirmativos (`superseded`/`absorbed`).
- Fail-closed: `--project-root`/`AGENT_PROJECT_ROOT` sin fallback a `__file__`; bus/backlog
  ilegible -> ReconcileError -> exit 1. `--json`. No muta estado.
- Patron AP-D04: reutiliza el enfoque de lectura de bus de preflight_reconcile y el parseo
  de tabla de check_backlog_contract.

## Fase 2 - Tests + verificacion en vivo
- Focal: `pytest tests/unit/test_check_closeout_reconciliation.py` = **12 passed** (0.13s).
- Verificacion EN VIVO contra el workspace real:
  - 1a corrida cazo drift real y orphans -> triage (ver abajo).
  - Tras el fix de check B: `[PASS]` exit 0 (drift=0, orphan=0, prebus_exempt=3).

## mutation-verify (barreras vivas: sin-fix -> test FALLA; con-fix -> verde)
```
M1  check A (drift) neutralizado             -> test_drift_closed_in_bus...      FALLA (exit 1)
M2  check B (orphan) neutralizado            -> test_orphan_declared_done...     FALLA (exit 1)
M3  archive glob eliminado                   -> test_archive_only_close...       FALLA (exit 1)
M4  check B re-incluye superseded (FP)       -> test_superseded_..._exempt       FALLA (exit 1)
CON-FIX (fuente restaurado): 12 passed
```

## Triage del hallazgo real del gate: WT-2026-239a
- La 1a corrida del gate contra el workspace marco `orphan_declared = WT-2026-239a`
  (declarado terminal sin SUPERVISOR_CLOSED).
- Triage: 239a esta marcado **`superseded`** (NO `completed`) en backlog_done, cerrado por
  Ruta B honesta 2026-06-22. El Manager emitio CHANGES (bug critico de seguridad); el scope
  migro a los hijos 240a/241a que SI entregaron el fix. Se dejo el bus SIN cerrar A PROPOSITO
  "para no falsear historia". 4 tipos de evento en bus, ningun SUPERVISOR_CLOSED.
- Conclusion: NO es auto-reporte -- es lo contrario, un cierre escrupulosamente honesto.
  El gate tenia un falso positivo: no distinguia `superseded`-honesto de `completed`-fantasma.
- FIX aplicado: check B solo exige bus a estados que AFIRMAN cierre completo
  (`_CLOSURE_CLAIMING_STATES = {completed, done, closed}`); `superseded`/`absorbed` se eximen.
  Barrera M4 lo blinda. Gate ahora PASA contra el workspace real.

## Gates
- ruff check + format: limpio. encoding guard: 0. focal: 12 passed.
- validate: config valid, single authority. validate_ticket_prose: ver nota de cierre.
- suite canonica `--level all` sobre HEAD final: exit 0, sin state-leak (ver nota).

Marked ready by Builder

Manager approved canonical closeout for WOT-2026-015l (SUPERVISOR_CLOSED bus seq 14)

## Nota de cierre
- El Manager review post-cierre (pre-push) cazo 6 findings legitimos: execution_log de 016m
  no separado, tested_sha desfasado por el churn, warning validate, mutation-verify no formal,
  triage 239a pendiente, AUDIT ausente. Todos corregidos ANTES del push (este log, el fix de
  check B, AUDIT_WOT-2026-015l.md, re-run de suite y validate). Push solo tras re-review.
