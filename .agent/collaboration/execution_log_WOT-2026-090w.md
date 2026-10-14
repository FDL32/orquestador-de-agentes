# WOT-2026-090w — Receipt del Paso 0

## Fase 0: Reproducir el bug (rc rojo previo)

**Nodo de test:** `test_backlog_only_commit_is_not_delivery`
**Comando:** `python scripts/run_pytest_safe.py -- tests/unit/test_session_closeout_loop_targets.py::test_backlog_only_commit_is_not_delivery`

### RC ROJO PREVIO (mutacion: helper -> `return False`)

El test `test_backlog_only_commit_is_not_delivery` contiene la prueba de mutacion interna:
cuando `_delivers_only_backlog_surfaces` se neutraliza a `return False`, el commit solo-backlog
(rev `d6842551...`) REAPARECE en `loop_execution_targets.txt`.

Veredicto: **Paso 0 completado** — el test demuestra que SIN el filtro, el bug existe
(commit solo-backlog entra como ENTREGA); con el filtro activo, el commit se excluye.

### RC VERDE POST-FIX (sin mutacion)

Mismo nodo con filtro activo: 1 passed, exit 0. El sha no entra en targets.txt.

---
Generated: 2026-10-14
BUI-090w-r2 (builder@qwen3.6)