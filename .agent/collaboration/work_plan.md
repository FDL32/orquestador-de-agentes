# Work Plan - WP-2026-140

## Metadata
- **ID:** WP-2026-140
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Bus import boundary test for scripts dependency firewall
- **Asignado a:** Builder

## Objetivo
Blindar la capa `bus/` para que no cree nuevas dependencias sobre `scripts/`, preservando solo la excepcion explicitamente permitida para `scripts.discover_skills`.

## Decision Arquitectonica
- El boundary test analiza el arbol `bus/` y extrae las importaciones `scripts.*` de forma estaticamente segura.
- La unica importacion permitida desde `bus/` hacia `scripts/` es `scripts.discover_skills`, porque esa es la seam existente de discovery de skills.
- Si aparece cualquier otro `scripts.*` dentro de `bus/`, el test debe fallar con el modulo exacto y la importacion observada.
- El ticket no cambia el codigo de produccion salvo que el boundary revele una excepcion adicional que deba formalizarse.

## Files Likely Touched
- `tests/test_bus_boundary.py`

## Fases
1. Implementar un test AST-based que recorra `bus/` y coleccione imports `scripts.*`.
2. Declarar explicitamente el allowlist minimo: `scripts.discover_skills`.
3. Hacer que el failure message identifique el modulo de `bus` y la importacion prohibida.
4. Validar con el subset de tests, `ruff` y la validacion canonica.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_bus_boundary.py -q`
- `ruff check tests/test_bus_boundary.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `bus/` solo mantiene la importacion permitida `scripts.discover_skills`.
- Cualquier nuevo `scripts.*` importado desde `bus/` hace fallar el test con una traza clara.
- El boundary no produce falsos positivos sobre imports que no pertenecen a `bus/`.
- La validacion canonica pasa sin errores.
