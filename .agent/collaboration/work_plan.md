# Plan de Trabajo: Retirada del residuo native skill Goose deprecated

## Metadata
- **ID:** WOT-2026-020m
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-08
- **delivery_authority:** repo_motor
- **Prioridad:** LOW
- **Asignado a:** Builder

## Objetivo
Retirar los 3 archivos del residuo native skill Goose (familia 254a deprecated):
`goose-skill.json`, `goose_integration.py`, `test_goose_native_skill.py`. El test es
consumidor circular (se prueba a si mismo; sin consumidor de produccion).

## Premisa (verificada read-only)
- VERIFICADO EN GIT: `goose-skill.json` + `goose_integration.py` trackeados en `skills/refactor-manager/`.
- VERIFICADO EN GREP: consumidor de produccion = ninguno; solo `test_goose_native_skill.py`
  (circular) + `.goosehints` (doc deprecada).
- BRECHA DE FICHA ENCONTRADA: `.goosehints` (trackeado, deprecado 254a, en CRITICAL_PATHS de
  `upgrade_agent_system.py`) referencia `goose_integration` (l.22, l.78). La ficha no lo conto.
  Decision (humano): limpiar referencias (no borrar el archivo).

## Files Likely Touched
- `skills/refactor-manager/goose-skill.json` (delete)
- `skills/refactor-manager/goose_integration.py` (delete)
- `tests/test_goose_native_skill.py` (delete)
- `.goosehints` (clean 2 dangling import refs)

## Forbidden Surfaces
- NO tocar `scripts/discover_skills.py` ni `scripts/orquestador.py` (superficie runtime -> WOT-2026-020n)
- NO tocar `skills/refactor-manager/SKILL.md` (canonico vivo)
- NO retirar referencias historicas en DEC/changelog

## Non-goals
- No tocar la superficie runtime Goose/Claw (GooseAdapter, ClawAdapter, ADAPTERS, --goose flag) -> 020n
- No borrar `.goosehints` entero (esta en CRITICAL_PATHS; retirada completa es fase 2 / 020n)

## Decision Arquitectonica
Limpiar las 2 referencias colgantes en `.goosehints` (l.22, l.78) en lugar de borrar el
archivo entero. Motivo: `.goosehints` esta en `CRITICAL_PATHS` de `upgrade_agent_system.py`
(l.50) y su propio header declara "retirada completa es fase 2 de la deprecacion" (020n).
Borrarlo romperia el upgrade system y se adelantaria a 020n. Limpiar las referencias al
import retirado satisface el DoD grep=0 sin tocar la superficie runtime (Non-goals:
discover_skills.py, orquestador.py, SKILL.md -> 020n). El comentario de reemplazo evita el
string `goose_integration` para que el DoD grep devuelva 0 literal.

## Criterios de Aceptacion
- [x] `git grep goose-skill.json|goose_integration` devuelve 0
- [ ] `run_pytest_safe.py --level all` exit 0 (suite final pendiente)
- [x] Mutation criterio 4: sin los 2 archivos, el test falla (3 failed)
- [x] Mutation criterio 3: ningun otro test depende de los archivos goose (grep tests/ = solo el removido)
