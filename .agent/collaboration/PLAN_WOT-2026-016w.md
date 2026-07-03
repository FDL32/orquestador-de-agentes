# PLAN - WOT-2026-016w

**Ticket:** WOT-2026-016w - check_deliverables_exist.py descarta bullets FLT con anotacion
(bug gemelo de 016s).
**Estado:** APPROVED
**delivery_authority:** repo_motor | **deliverable_type:** code

Este documento es la estrategia tecnica breve del ticket; el contrato completo (diagnostico
detallado, criterios, gates, STOP conditions) vive en work_plan.md. Si algo difiere entre
ambos, work_plan.md manda.

## Resumen del problema

scripts/check_deliverables_exist.py, funcion _resolve_flt_bullet_tokens (linea 244-252),
descarta CUALQUIER bullet de Files Likely Touched que, tras limpiar backticks/comillas,
contenga un espacio en la linea completa. Esto incluye bullets legitimos con anotacion
descriptiva tras el path, por ejemplo "- `scripts/x.py` (nuevo, el gate)": la funcion nunca
llega a comprobar si scripts/x.py existe en disco. Es el mismo bug que WOT-2026-016s
corrigio en .agent/scope_gate.py::_normalize_flt_line (commit 4c79e8e), pero
check_deliverables_exist.py quedo sin tocar.

## Estrategia (cambio minimo)

1. Confirmar en codigo (ya hecho en Fase 0 del Orquestador/Manager) que el sintoma existe y
   que el matiz anti-narrativa del docstring (lineas 235-243) sigue siendo valido.
2. Aplicar en _resolve_flt_bullet_tokens el mismo patron que _normalize_flt_line de
   scope_gate.py: tras la limpieza de backticks/comillas/bullet-prefix, quedarse solo con el
   primer token separado por espacio, y aplicar el resto de las validaciones existentes
   (placeholders <>{}}, YYYY, NNN, trailing slash, looks_like_path) sobre ese primer token.
3. Anadir dos tests nuevos en tests/unit/test_check_deliverables_exist.py que prueben: (a)
   un bullet anotado cuyo deliverable falta en disco da code == 1 y menciona el archivo; (b)
   el mismo bullet cuando el deliverable SI existe da code == 0.
4. Confirmar que el test de no-regresion existente
   (test_wot_010j_real_case_narrative_note_not_treated_as_deliverable) sigue en verde tras el
   cambio.
5. Ejercer mutation: revertir el fix, confirmar que el test nuevo (a) falla; restaurar,
   confirmar que pasa. Registrar ambos resultados literales en execution_log.md.
6. Correr gates: pytest focal del archivo, ruff check, ruff format --check (o su
   equivalente .venv si uv esta roto en este entorno), suite canonica
   run_pytest_safe.py --level all.
7. Commitear en repo_motor con WOT-2026-016w en el mensaje, mark-ready, esperar review del
   Manager (validate es Manager gate).

## Archivos tocados

- scripts/check_deliverables_exist.py (funcion _resolve_flt_bullet_tokens unicamente)
- tests/unit/test_check_deliverables_exist.py (2 tests nuevos)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion (binarios)" items 1-8. No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de los comandos
exactos.
