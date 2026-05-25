# Work Plan - WP-2026-139

## Metadata
- **ID:** WP-2026-139
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Cached canonical anti-pattern inventory for review_bridge
- **Asignado a:** Builder

## Objetivo
Hacer que `bus/review_bridge.py` cargue el inventario canónico de anti-patrones desde `skills/_shared/anti-patterns.md` una sola vez y lo reutilice con caché al construir el rubric del Manager.

## Decision Arquitectonica
- `ReviewBridge.__init__()` carga el inventario canónico de AP desde `skills/_shared/anti-patterns.md` y lo deja cacheado.
- `_rubric_for_type()` deja de depender de la copia inline de APs y compone el bloque desde el inventario cacheado.
- La lista canónica de AP sigue viviendo en `skills/_shared/anti-patterns.md`; `code-rules.md` y `review-checklist.md` permanecen como vistas derivadas.
- Si el archivo canónico no estuviera disponible, el review no debe romperse y debe degradar de forma segura.

## Files Likely Touched
- `bus/review_bridge.py`
- `tests/test_manager_review_bridge.py`

## Fases
1. Cargar el inventario canónico AP desde `skills/_shared/anti-patterns.md` con caché en `ReviewBridge.__init__()`.
2. Reemplazar la lista inline de APs en `_rubric_for_type()` por la composición desde el inventario cacheado.
3. Mantener intactos el rubic base, las lecciones dinámicas y el contrato `APPROVE / CHANGES / INSPECT`.
4. Ajustar tests para cubrir carga una sola vez, composición del rubric y degradación segura.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_manager_review_bridge.py -q`
- `ruff check bus/review_bridge.py tests/test_manager_review_bridge.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `bus/review_bridge.py` carga AP canónicos desde archivo una sola vez y los reutiliza con caché.
- El rubric del Manager conserva `AP-01..AP-07` sin la triple copia inline.
- Los tests cubren carga, composición y fallback seguro.
- La validacion canonica pasa sin errores.
