# Work Plan - WP-2026-167

## Metadata
- **ID:** WP-2026-167
- **Estado:** APPROVED
- **deliverable_type:** mixed
- **Titulo:** Builder handoff safety - guard, checkpoints y recovery protocol
- **Asignado a:** Builder

## Objetivo
Cerrar el gap contractual que causo WP-2026-165: el sistema no verifica programaticamente que el arbol este limpio antes de emitir `READY_FOR_REVIEW`, no tiene anclas de recuperacion, y no tiene un protocolo formal para cuando Builder se pierde.

## Contexto
- WP-2026-165 perdio trabajo porque el Builder interpreto archivos no commiteados como scope externo y los borro con `git checkout`.
- `delivery_hygiene_check.py` y `prepush_check.py` ya verifican higiene de entrega antes del push remoto, pero el gap esta en el handoff interno Builder -> Manager.
- Superficies vivas del sistema (`TURN.md`, `STATE.md`, `execution_log.md`, `events.jsonl`, `store.json`, `project-map.json`, `notifications.md`, `review_queue.md`) son escritas por el propio runtime y deben ignorarse de forma explicita para evitar falsos positivos.
- El protocolo de recuperacion debe usar `git status` y `git reflog` como anclas, no limpieza destructiva.
- `worktree` por ticket queda fuera de alcance en este ticket.

## Decision Arquitectonica
- `scripts/pre_handoff_guard.py` se invoca desde `.agent/agent_controller.py` en `_handle_mark_ready()` antes de `_sync_mark_ready_targets()` y antes de emitir `STATE_CHANGED -> READY_FOR_REVIEW`.
- El guard ejecuta `git status --porcelain` y excluye las superficies vivas y los archivos ya ignorados por `.gitignore`.
- Si el arbol esta sucio, el guard devuelve exit 1 + JSON diagnostico; `.agent/agent_controller.py` emite `HANDOFF_BLOCKED` con ese JSON.
- Si hay archivos fuera de `Files Likely Touched`, el guard los reporta como `scope_discrepancy` en el payload, pero nunca los borra ni los revierte.
- El checkpoint M3 (`checkpoint/review-<ticket>`) debe existir antes de `--mark-ready`; no se auto-crea desde el handoff.
- `scripts/create_checkpoint.py` crea checkpoints semanticos M0-M4 y emite `BUILDER_MILESTONE` con `{milestone, sha, tag, ticket_id}`.
- Si la tag de checkpoint ya existe, el script hace skip con aviso y no falla.
- La base del diff de scope es `git diff --name-only $(git rev-parse checkpoint/base-<ticket> 2>/dev/null || git merge-base HEAD main)`.
- El protocolo de recuperacion vive en `.agent/rules/builder/recovery.md` y usa `git status`, `git reflog` y `git checkout <tag-o-hash>` como ruta primaria para volver al ultimo ancla conocido bueno. Si `git checkout` no esta disponible, usar `git switch --detach <tag-o-hash>`.
- No se implementa `worktree` en este ticket.

## Non-goals
- No correr `pytest` ni `ruff` dentro del guard; eso ya lo cubre el preflight de entrega.
- No auto-crear el checkpoint M3 desde `--mark-ready`.
- No tocar `scripts/launch_agent_terminals.ps1`.
- No cambiar la logica del Manager ni del bus de review.
- No introducir `worktree` por ticket en este WP.
- No cambiar el cierre canonico de tickets.

## Fases

### Fase 1: guard de handoff
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/pre_handoff_guard.py`, `.agent/agent_controller.py`, `tests/test_pre_handoff_guard.py`
- **Accion:** Modificar
- **Descripcion:** Crear un guard programatico de handoff que se ejecute antes de emitir `READY_FOR_REVIEW`. La insercion va en `_handle_mark_ready()` antes de `_sync_mark_ready_targets()`. El guard debe validar el arbol limpio, ignorar superficies vivas, detectar discrepancias de scope sin destruccion y bloquear el handoff si falta el checkpoint M3 o si el arbol esta sucio. `scripts/pre_handoff_guard.py` solo devuelve exit 1 + JSON; la emision de `HANDOFF_BLOCKED` la hace `.agent/agent_controller.py`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `--mark-ready` con arbol sucio bloquea con exit 1 y emite `HANDOFF_BLOCKED`; `--mark-ready` con arbol limpio y M3 existente conserva el comportamiento actual; `scope_discrepancy` se reporta como observacion no bloqueante; las superficies vivas no producen falsos positivos.
- **Si falla:** Mantener el comportamiento actual de `--mark-ready` y dejar el guard para un ticket posterior.

### Fase 2: checkpoints semanticos
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/create_checkpoint.py`, `tests/test_create_checkpoint.py`, `skills/bui-implement-from-plan/references/code-rules.md`
- **Accion:** Modificar
- **Descripcion:** Crear una utilidad de checkpoint que produzca commits/tags anotadas M0-M4. Builder debe crear M3 explicitamente antes de `--mark-ready`; si M3 falta, el guard bloquea. El comando debe emitir `BUILDER_MILESTONE` con milestone, tag y SHA verificable.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `scripts/create_checkpoint.py` crea checkpoints anotados, imprime SHA y deja trazabilidad en el bus; el plan y `code-rules.md` exigen M3 antes del handoff; si la tag ya existe, el script hace skip con aviso y no falla.
- **Si falla:** Dejar el checkpoint como paso manual documentado, sin forzar auto-creacion desde `--mark-ready`.

### Fase 3: protocolo de recuperacion
- **Tipo:** TAREA AGENTE
- **Archivos:** `.agent/rules/builder/recovery.md`, `skills/_shared/ticket-anti-patterns.md`, `skills/man-review-implementation/references/review-checklist.md`
- **Accion:** Crear + Modificar
- **Descripcion:** Crear el directorio `.agent/rules/builder/` si no existe y documentar un protocolo de recuperacion literal con comandos: parar, `git status`, `git reflog`, volver al ultimo ancla estable con `git checkout <tag-o-hash>` y reanudar desde el ultimo checkpoint. Si `git checkout` no esta disponible en la version de Git instalada, usar `git switch --detach <tag-o-hash>` como alternativa equivalente. Anadir AP-D03 al catalogo y una comprobacion explicita de handoff limpio en la review checklist.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** `recovery.md` existe y describe los pasos con comandos literales; AP-D03 esta en el catalogo; la checklist del Manager pregunta por `HANDOFF_BLOCKED` y handoff limpio.
- **Si falla:** Mantener la documentacion de recuperacion como regla externa y no introducir logica nueva.

## Files Likely Touched
- `scripts/pre_handoff_guard.py`
- `scripts/create_checkpoint.py`
- `tests/test_pre_handoff_guard.py`
- `tests/test_create_checkpoint.py`
- `.agent/agent_controller.py`
- `.agent/rules/builder/recovery.md`
- `skills/_shared/ticket-anti-patterns.md`
- `skills/bui-implement-from-plan/references/code-rules.md`
- `skills/man-review-implementation/references/review-checklist.md`

## Calidad
- `python scripts/pre_handoff_guard.py --project-root . --ticket-id WP-2026-167`
- `python scripts/run_pytest_safe.py tests/test_pre_handoff_guard.py tests/test_create_checkpoint.py`
- `uv run ruff check .agent/agent_controller.py scripts/pre_handoff_guard.py scripts/create_checkpoint.py tests/test_pre_handoff_guard.py tests/test_create_checkpoint.py`
- `python scripts/validate_ticket_prose.py --json`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `--mark-ready` bloquea cuando el arbol esta sucio o cuando falta el checkpoint M3.
- Las superficies vivas del runtime no generan falsos positivos en el guard.
- `scope_discrepancy` se reporta sin limpieza destructiva si aparecen archivos fuera de scope.
- `BUILDER_MILESTONE` queda registrado con milestone, tag y SHA.
- El protocolo de recuperacion y la review checklist referencian el mismo contrato de handoff limpio.
