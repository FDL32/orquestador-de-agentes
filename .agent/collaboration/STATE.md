# State - WP-2026-142

Plan Activo: WP-2026-142
Estado actual: IN_PROGRESS
Rol activo: BUILDER

Resumen:
WP-2026-142 endurece `--mark-ready` para evitar fabricacion de scope: bloqueo por cobertura cero, warning por cobertura parcial y preservacion del bloqueo por cambios fuera de la whitelist.

Notas:
- El alcance es code.
- `events.jsonl` y el circuit breaker quedan fuera de alcance.
- El cambio debe respetar los casos base no-git y whitelist vacia.
