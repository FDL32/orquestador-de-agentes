# Work Plan - WP-2026-141

## Metadata
- **ID:** WP-2026-141
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Google eng-practices review standards alignment
- **Asignado a:** Builder

## Objetivo
Adaptar un subconjunto pequeno de `google/eng-practices` al ciclo documental del repositorio para hacer mas objetiva la revision, clarificar `Nit` y dejar trazabilidad en `AGENTS.md` y `CREDITS.md`.

## Decision Arquitectonica
- El criterio de aprobacion debe favorecer la mejora de la salud del codigo, aunque el cambio no sea perfecto.
- `Nit` debe quedar definido como comentario no bloqueante, distinto de un cambio requerido.
- Las referencias externas deben apuntar a secciones concretas de eng-practices, no solo al repo raiz.
- La convencion se integra en las superficies documentales ya existentes, sin crear una skill nueva.
- El alcance se mantiene documental y no toca codigo de produccion ni runtime.

## Files Likely Touched
- `skills/man-review-implementation/references/review-checklist.md`
- `AGENTS.md`
- `CREDITS.md`

## Fases
1. Redactar el criterio de aprobacion y la convencion `Nit` en la checklist de review con enlaces directos a eng-practices.
2. Anadir la linea de trazabilidad en `AGENTS.md`.
3. Registrar la atribucion en `CREDITS.md`.
4. Validar el estado canonico y la consistencia documental.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_work_plan_schema.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `review-checklist.md` contiene el principio de aprobacion y la convencion `Nit`.
- `AGENTS.md` referencia el principio de aprobacion como criterio de cierre.
- `CREDITS.md` incluye la atribucion a `google/eng-practices` con CC-BY 3.0.
- El ticket sigue siendo de tipo documental.
- La validacion canonica pasa sin errores.
