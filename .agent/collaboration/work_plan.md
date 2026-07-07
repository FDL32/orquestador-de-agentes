# Plan de Trabajo: Heading exact match edge cases

## Metadata
- **ID:** WOT-2026-020c
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-07
- **delivery_authority:** repo_motor

## Objetivo

Testear y documentar el comportamiento del scope gate ante headings con formatos
alternativos: trailing content (`## Files Likely Touched (motor)`) y
double-space (`##  Files Likely Touched`). WOT-2026-019l cambio la deteccion de
substring a match exacto (`stripped == "## {heading}"`); este ticket verifica
que el match exacto NO detecta estos formatos (fail-closed) y documenta la
decision.

## Decision

**Mantener match exacto (fail-closed).** Razon: el match exacto previene que
menciones en prosa del literal del heading abran la seccion y lean tokens
basura (WOT-2026-019l, L-GATE-HARDENING-001 regla 1). Relajar a `startswith`
reintroduciria el riesgo de falso positivo. Los edge cases (trailing content,
double-space) no ocurren en ningun work_plan existente. Si el formato evoluciona,
el fail-closed es seguro: la seccion no se detecta (fallo visible) en vez de
matchear contenido equivocado (fallo silencioso).

## Files Likely Touched
- `tests/unit/test_scope_gate.py`

## Read/inspect only
- `.agent/scope_gate.py` (no se modifica; el match exacto se mantiene)

## Non-goals
- NO cambiar la deteccion de headings sin trailing content (comportamiento actual preservado)
- NO relajar el match a startswith (decision: mantener exacto)
- NO tocar scope_gate.py (es test-only; el codigo no cambia)

## Criterios de aceptacion (DoD)
- [x] test que un heading con trailing content NO abre la seccion (comportamiento actual preservado)
- [x] test que un heading con double-space NO abre la seccion
- [x] decision documentada: mantener exacto (fail-closed)
- [x] MUTATION: relajar a startswith -> el comportamiento cambia (trailing content abre la seccion)

## Mutation-verify
1. Edit scope_gate.py: cambiar `stripped == "## Files Likely Touched"` a `stripped.startswith("## Files Likely Touched")`
2. Correr test de trailing content -> debe FALLAR (la seccion se abre)
3. Revertir edit
4. Correr test -> debe PASS (la seccion no se abre)
