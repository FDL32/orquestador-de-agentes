## Atribuciones externas (CREDITS.md)

Cuando un WP incorpora una idea/patrón de un repositorio externo:

1. **`repo-compare`** emite al final de su reporte un bloque candidato listo para pegar en `CREDITS.md`.
2. El humano decide cuándo adoptar la idea y pega la fila correspondiente en `CREDITS.md` (raíz del repo).
3. El WP que implementa la idea incluye `Origen externo:` o `Inspired by:` en `work_plan.md`.
4. **`project-finalize` Paso 8d** verifica que la fila CREDITS exista antes de cerrar el WP. Si falta, bloquea el cierre.

Formato: tabla compacta `| WP | Source | Pattern | License | Adapted vs Ported |`. Detalle en `CREDITS.md`.

**Limitación conocida:** `CREDITS.md` vive en raíz; `scripts/install_agent_system.py` actualmente solo copia `.agent/`. Por tanto, esta convención **no se propaga automáticamente** a proyectos derivados. Si forks/derivados quieren la convención, deben replicar `CREDITS.md` + skills `repo-compare` y `project-finalize` manualmente.
