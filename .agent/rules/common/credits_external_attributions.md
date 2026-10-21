## Atribuciones externas (CREDITS.md)



Cuando un WP incorpora una idea/patrÃ³n de un repositorio externo:



1. **`repo-compare`** emite al final de su reporte un bloque candidato listo para pegar en `CREDITS.md`.

2. El humano decide cuÃ¡ndo adoptar la idea y pega la fila correspondiente en `CREDITS.md` (raÃ­z del repo).

3. El WP que implementa la idea incluye `Origen externo:` o `Inspired by:` en `work_plan.md`.

4. **`project-finalize` Paso 8d** verifica que la fila CREDITS exista antes de cerrar el WP. Si falta, bloquea el cierre.



Formato: tabla compacta `| WP | Source | Pattern | License | Adapted vs Ported |`. Detalle en `CREDITS.md`.



**LimitaciÃ³n conocida:** `CREDITS.md` vive en raÃ­z; `scripts/install_agent_system.py` actualmente solo copia `.agent/`. Por tanto, esta convenciÃ³n **no se propaga automÃ¡ticamente** a proyectos derivados. Si forks/derivados quieren la convenciÃ³n, deben replicar `CREDITS.md` + skills `repo-compare` y `project-finalize` manualmente.

