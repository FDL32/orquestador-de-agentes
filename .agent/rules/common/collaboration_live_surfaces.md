## Superficies vivas vs historicas en `.agent/collaboration/` (WP-2026-107)



No todo lo que parece "viejo" en `collaboration/` es archivable. Distingue:



- **Superficies vivas (NO archivar, las escribe el codigo en cada ciclo):**

  - `archive/`: rotacion de snapshots de `notifications.md`. La escribe

    `agent_controller.py` (`ARCHIVE_DIR`) cada vez que rota la proyeccion.

    NO es legacy; borrarla rompe el controlador.

  - `review_queue.md`: log vivo de reviews del Manager. Le hace append

    `manager_review_bridge.py` (`_record_review`) en cada review.

  - `notifications.md`: proyeccion viva validada por `--validate`. Solo se

    resetea a placeholder, nunca se archiva entera.

- **Superficie historica (`_archive/`):** solo cubre historicos de

  `PLAN_WP-*.md` / `AUDIT_WP-*.md` cerrados (`_archive/plan_audit/`) y

  snapshots legacy no operativos (`_archive/legacy/`). Su contenido puede

  ser un registro unico (p.ej. `_archive/legacy/review_queue.md` conserva

  reviews de WPs que el log vivo ya no tiene): verifica antes de borrar.



Regla: antes de "limpiar" un archivo de `collaboration/`, comprueba si algun

script lo escribe activamente. Si lo hace, es superficie viva.

