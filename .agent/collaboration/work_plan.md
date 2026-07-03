# Work Plan - WOT-2026-015l

## Metadata
- **ID:** WOT-2026-015l
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Gate de cierre: reconciliar backlog vs eventos SUPERVISOR_CLOSED del bus del workspace (bidireccional, anti auto-reporte)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Barrera ejecutable read-only que reconcilie el estado declarado del backlog contra la
fuente de verdad (los eventos `SUPERVISOR_CLOSED` del bus del WORKSPACE de dogfooding, no
del motor). El sintoma se materializo 2x esta semana: 016b `completed` en el bus pero
`pending` en el backlog ~1 dia, y el agujero de 016g en `_archive/backlog_done.md` que el
Manager tuvo que tapar a mano.

Verificacion del objetivo: `python scripts/check_closeout_reconciliation.py
--project-root <workspace>` devuelve exit 0 solo cuando (A) ningun ticket cerrado en el bus
sigue vivo en el backlog y (B) ningun ticket declarado en backlog_done carece de evento de
bus; `pytest tests/unit/test_check_closeout_reconciliation.py` verde con fixtures A/B y
mutation.

## Decision Arquitectonica

- `scripts/check_closeout_reconciliation.py`, NUEVO, offline, read-only y deterministico.
  Patron AP-D04: NO reimplementa la lectura de bus -- reutiliza `preflight_reconcile`
  (`_read_events_for_ticket`, y `bus.state_machine.StateMachine` para semantica de estados)
  y el parseo de tabla viva de `check_backlog_contract` como referencia de formato.
- **Fuentes (rutas relativas al `--project-root` = workspace):**
  1. **Bus (verdad):** `SUPERVISOR_CLOSED` en `.agent/runtime/events/events.jsonl` (vivo)
     MAS `.agent/runtime/events/archive/*.jsonl`. Union de ambos: 016o/016p viven SOLO en
     archive -> mirar solo el vivo da falso negativo. Esquema del evento: `event_type`,
     `ticket_id`, `sequence_number`, `actor`.
  2. **Cola viva:** filas `pending`/`blocked` bajo `## Vista rapida` de
     `.agent/collaboration/backlog.md` (solo tabla; nunca prosa ni comentarios HTML).
  3. **Declarados cerrados (B):** tabla `| Ticket | Estado | Nota |` de
     `.agent/collaboration/_archive/backlog_done.md`, filas con estado terminal
     (`completed`/`done`/`closed`/`superseded`/`absorbed`).
- **Fail-closed:** `--project-root` o `AGENT_PROJECT_ROOT` obligatorio; SIN fallback a
  `__file__` (leer el bus relativo al motor = archivo equivocado; mismo patron y misma
  razon que `check_backlog_contract.py`). Bus/backlog ilegible -> FAIL con diagnostico, no
  silencio.
- **Salida:** JSON a stdout con `--json`
  (`{checks:{drift, orphan_declared}, all_pass, project_root, head}`) + render humano con un
  finding por linea y fix accionable por violacion. No muta estado NUNCA.
- **Exit:** 0 si A y B pasan; 1 si alguna viola; 1 tambien en error de lectura (fail-closed).

## Fases

### Fase 0 - Diagnostico (COMPLETADO)
- Bus fisico del workspace confirmado: `.agent/runtime/events/events.jsonl` (vivo, 11
  SUPERVISOR_CLOSED) + `events/archive/*.jsonl` (181 archivos). Runtime GITIGNORED (estado
  local). Esquema de evento verificado en vivo (015i seq 1298).
- Contrato 012a/012b confirmado: los terminales NO permanecen en la cola viva (desaparecen);
  por eso el drift real es "cerrado-en-bus pero aun-pending", no "declarado sin cerrar".
- Fuente B confirmada: `_archive/backlog_done.md` con tabla `| Ticket | Estado | Nota |`
  (016g ya presente = agujero tapado). 184 IDs.

### Fase 1 - Implementacion
- Funciones puras testables: `read_closed_from_bus(project_root) -> set[str]` (union vivo +
  archive, filtrando `event_type == SUPERVISOR_CLOSED`), `read_live_backlog(project_root) ->
  set[str]` (IDs pending/blocked de `## Vista rapida`), `read_declared_done(project_root) ->
  set[str]` (IDs terminales de backlog_done), `run_gate(project_root) -> report`.
- `run_gate`: check A = `closed_in_bus & live_backlog` (debe ser vacio); check B =
  `declared_done - closed_in_bus` (debe ser vacio). Cada violacion -> finding con ticket_id
  (+ sequence_number del evento cuando aplique).

### Fase 2 - Tests (barrera + mutation)
- `tests/unit/test_check_closeout_reconciliation.py`, con workspace sintetico en `tmp_path`
  (events.jsonl + archive/*.jsonl + backlog.md + _archive/backlog_done.md minimos):
  - happy path: bus y backlog coherentes -> exit 0 / all_pass.
  - **fixture A:** ticket con SUPERVISOR_CLOSED en bus Y fila `pending` en Vista rapida ->
    check drift dispara; MUTATION: revertir el assert A -> deja de disparar (verde espurio).
  - **fixture B:** ticket en backlog_done SIN evento en el bus -> check orphan_declared
    dispara; MUTATION: revertir el assert B -> deja de disparar.
  - archive-only: un SUPERVISOR_CLOSED que vive SOLO en `archive/*.jsonl` cuenta como
    cerrado (barrera contra el falso negativo de mirar solo el vivo).
  - fail-closed: sin project-root -> error/exit != 0; bus ausente -> FAIL, no pass-open.

## Criterios de aceptacion

1. Check A (drift): ningun `SUPERVISOR_CLOSED` del bus (vivo+archive) sigue como fila viva
   `pending`/`blocked` en `## Vista rapida`. Violacion enumerada con ticket_id + seq.
2. Check B (orphan_declared): cada ticket que AFIRMA cierre completo (estado
   `completed`/`done`/`closed`) en `_archive/backlog_done.md` y tuvo actividad en el bus
   tiene su `SUPERVISOR_CLOSED`. Se eximen: historia pre-bus (cero eventos) y cierres
   honestos por otra via (`superseded`/`absorbed`). Violacion enumerada con ticket_id.
3. Union bus vivo + archive verificada por test (archive-only cuenta como cerrado).
4. Fail-closed sin project-root y con bus ilegible (test).
5. MUTATION de las 4 barreras verificadas (drift A, orphan B, archive-glob, superseded-FP):
   cada assert es la barrera de su fixture (sin-fix -> el fixture falla).
6. `--json` emite `{checks:{drift, orphan_declared}, all_pass}`; script no muta estado.
7. ruff + format + encoding verdes; suite canonica `--level all` exit 0 con
   `tested_sha == HEAD`; validate 0/0.

## Files Likely Touched

### repo_motor
- `scripts/check_closeout_reconciliation.py` (nuevo, el gate)
- `tests/unit/test_check_closeout_reconciliation.py` (nuevo, fixtures A/B + mutation)

## Non-goals
- NO auto-reparar el backlog: el gate DETECTA y REPORTA; la correccion es humana/Manager.
- NO tocar el flujo de manager-approve, el bus, ni la state machine.
- NO consultar el bus del repo_motor (agnostico, sin estado operativo -> falso negativo).
- NO derivar estado por prosa del backlog (solo tablas parseables: `## Vista rapida` y la
  tabla de `backlog_done.md`).
- NO llamadas de red.
