# Artefactos de Sesión y Estado Canónico

## Superficie canónica: `.agent/collaboration/`

El estado operativo de tickets vive en `.agent/collaboration/` del `repo_destino`:

```text
.agent/collaboration/
├── work_plan.md          (aprobado por Manager, ejecutado por Builder)
├── execution_log.md      (bitácora de ejecución actual)
├── TURN.md               (turno actual del agente — protegido por guard_paths)
├── STATE.md              (proyección del ticket activo)
├── backlog.md            (cola de candidatos pendientes/activos)
├── review_queue.md       (cola viva de reviews)
├── notifications.md      (mensajes Manager <-> Builder)
├── archive/              (snapshots operativos, p.ej. review_queue_YYYY-MM-DD.md)
└── _archive/plan_audit/  (histórico canónico de PLAN_/AUDIT_ cerrados)
```

> Nota histórica: versiones antiguas de esta regla describían un patrón
> `.session/` para `work_plan.md` y `execution_log.md`. Ese patrón NO es el
> vigente: el estado canónico vive en `.agent/collaboration/` (ver AGENTS.md).

## Ciclo de vida
- **Durable:** `work_plan.md` y `execution_log.md` persisten entre sesiones y se sobrescriben para la próxima tarea.
- **Archivado:** al cerrar un ticket, sus `PLAN_*/AUDIT_*` van a `_archive/plan_audit/` (lo hace `scripts/archive_collaboration_artifacts.py`).
- **Consolidación:** las decisiones arquitectónicas importantes NUNCA se quedan aquí de forma permanente. Deben consolidarse post-sesión en `PROJECT.md` o `CHANGELOG.md`.

## Relación con TURN.md
- `TURN.md` es el "turno actual del agente", NO un artefacto de sesión temporal.
- Su modificación directa está bloqueada por `guard_paths`; solo el controller/supervisor lo materializa.

## Artefactos de runtime (gitignored)
- `.agent/runtime/reviews/`: raw NDJSON de reviews y `decision_<ticket>.json` (decision artifact del Manager).
- `.agent/runtime/events/events.jsonl`: bus append-only (autoridad canónica).
- `.agent/runtime/audit/AUDIT.md`: auditoría local fresca (<24h) generada por `scripts/local_audit.py`.
