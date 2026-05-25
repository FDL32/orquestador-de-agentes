# State - WP-2026-137

Plan Activo: WP-2026-137
Estado actual: IN_PROGRESS
Rol activo: BUILDER

Resumen:
WP-2026-137 protege el arranque del supervisor con lock de instancia e idempotencia de reconciliacion.

Notas:
- El bus es la fuente canonica del ciclo y debe permanecer monotono.
- `SUPERVISOR_RECONCILED` no debe repetirse para el mismo ticket recuperado.
- Si aparece deriva hacia memoria, rubrica o pipeline de observaciones, el ticket debe escalarse aparte.

