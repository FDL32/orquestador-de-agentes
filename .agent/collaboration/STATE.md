# State - WP-2026-139

Plan Activo: WP-2026-139
Estado actual: IN_PROGRESS
Rol activo: BUILDER

Resumen:
WP-2026-139 carga el inventario canonico de anti-patrones desde archivo con caché en review_bridge para evitar drift entre Manager, Builder y memoria.

Notas:
- El bus es la fuente canonica del ciclo y debe permanecer monotono.
- `skills/_shared/anti-patterns.md` es la fuente canonica de AP-01..AP-07.
- `code-rules.md` y `review-checklist.md` siguen siendo vistas derivadas.
- Si aparece deriva hacia escritura de memoria o el pipeline de cierre, el ticket debe escalarse aparte.
