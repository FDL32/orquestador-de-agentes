# Work Plan - WP-2026-133

## Metadata
- **ID:** WP-2026-133
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Skill references scaffold for validator
- **Asignado a:** Builder

## Objetivo
Crear `references/` con `.gitkeep` en las skills que hoy fallan `skills/validate_all.py`, sin tocar la logica del validador.

## Decision Arquitectonica
- El fix se limita a la estructura de skills: crear `references/` y mantener un `.gitkeep` por carpeta.
- No se toca `skills/validate_all.py` ni ningun otro validador.
- No se introduce logica nueva ni contenido adicional en las skills.
- La solucion debe ser minima y estable para que Git preserve las carpetas vacias.

## Files Likely Touched
- `skills/bui-write-deliverable/references/.gitkeep`
- `skills/graphify/references/.gitkeep`
- `skills/local-audit/references/.gitkeep`
- `skills/memory-consolidate/references/.gitkeep`
- `skills/refactor-manager/references/.gitkeep`
- `skills/systematic-debugging/references/.gitkeep`
- `skills/test-driven-development/references/.gitkeep`

## Fases
1. Crear los 7 directorios `references/` faltantes con `.gitkeep`.
2. Ejecutar `skills/validate_all.py` y confirmar que el validador pasa.
3. Verificar que no se haya modificado el validador ni el contrato de skills.

## Calidad
- `python skills/validate_all.py`
- `ruff check skills/validate_all.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `skills/validate_all.py` reporta 0 skills invalidas.
- Las 7 skills afectadas contienen `references/.gitkeep`.
- No se modifica `skills/validate_all.py`.
- La validacion canonica pasa sin errores.
