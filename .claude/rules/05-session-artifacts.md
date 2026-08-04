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
├── _archive/backlog_done.md  (histórico TERMINAL del backlog — ver nota abajo)
└── _archive/plan_audit/  (histórico canónico de PLAN_/AUDIT_ cerrados)
```

> Nota histórica: versiones antiguas de esta regla describían un patrón
> `.session/` para `work_plan.md` y `execution_log.md`. Ese patrón NO es el
> vigente: el estado canónico vive en `.agent/collaboration/` (ver AGENTS.md).

## Ciclo de vida
- **Durable:** `work_plan.md` y `execution_log.md` persisten entre sesiones y se sobrescriben para la próxima tarea.
- **Archivado:** al cerrar un ticket, sus `PLAN_*/AUDIT_*` van a `_archive/plan_audit/` (lo hace `scripts/archive_collaboration_artifacts.py`).
- **Cerrar un ticket es un TRASPASO entre DOS superficies, no un cambio de etiqueta** (WOT-2026-026t). La FILA del ticket **se mueve** de `backlog.md` a `_archive/backlog_done.md` con un estado terminal (`completed`/`done`/`closed`/`absorbed`/`superseded`/`blocked-final`/`not-pursued`) y su evidencia de aterrizaje (`commit:<sha>`) en la celda `Reactivation`. Ningún script lo hace por ti: `archive_collaboration_artifacts.py` mueve `PLAN_/AUDIT_`, **no filas de backlog**.
  - Escribir un estado terminal en la cola viva es la violación evidente y el gate la bloquea.
  - **El fallo silencioso es el inverso:** una fila archivada que conserva estado VIVO es trabajo pendiente guardado como historia — la cola no lo lista y el archivo lo declara pendiente, así que queda invisible en las dos superficies (medidas 18 filas así el 2026-08-04).
  - Verificación: `python <MOTOR_ROOT>/scripts/check_backlog_contract.py --project-root <repo_destino>` (audita ambas superficies; cableado también en el closeout vía `prepush_check`).
- **Consolidación:** las decisiones arquitectónicas importantes NUNCA se quedan aquí de forma permanente. Deben consolidarse post-sesión en `PROJECT.md` o `CHANGELOG.md`.

## Relación con TURN.md
- `TURN.md` es el "turno actual del agente", NO un artefacto de sesión temporal.
- Su modificación directa está bloqueada por `guard_paths`; solo el controller/supervisor lo materializa.

## Artefactos de runtime (gitignored)
- `.agent/runtime/reviews/`: raw NDJSON de reviews y `decision_<ticket>.json` (decision artifact del Manager).
- `.agent/runtime/events/events.jsonl`: bus append-only (autoridad canónica).
- `.agent/runtime/audit/AUDIT.md`: auditoría local fresca (<24h) generada por `scripts/local_audit.py`.
