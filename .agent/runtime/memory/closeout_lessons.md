# Closeout Lessons

Lecciones curadas del ciclo de desarrollo del motor.
Leídas por el Manager en Paso 0b de `man-create-work-plan` antes de planificar.
Fuente: observaciones promovidas desde `observations.jsonl`.

---

## builder-contract

### CL-01 — Estado enum del controller (ticket-state-enum-contract)
`IDLE` es un sentinel de workspace sin ticket activo, no un estado válido del controller.
Al cerrar un ticket, `work_plan.md`, `execution_log.md` y `STATE.md` deben usar el enum
del controller: `APPROVED`, `IN_PROGRESS`, `READY_FOR_REVIEW`, `COMPLETED`.
Escribir `IDLE` en el motor activa errores de validación y bloquea `--manager-approve`.
**Regla:** usar `IDLE` solo en workspaces destino sin ticket activo, nunca en el motor durante cierre.

### CL-02 — Consistencia de superficies al cierre (state-surface-separation)
`STATE.md`, `execution_log.md`, `work_plan.md` y `TURN.md` deben reflejar el mismo
estado antes de `--manager-approve`. Si difieren, el controller lo detecta como drift
y puede bloquear el cierre o producir un falso APPROVE sobre estado inconsistente.
**Regla:** verificar que las cuatro superficies coinciden antes de cualquier operación de cierre.

## delivery-hygiene

### CL-03 — review_queue.md es trazabilidad viva (review-queue-traceability)
`review_queue.md` es escrita por `manager_review_bridge.py` en cada review.
Editarla manualmente durante el cierre rompe la trazabilidad del ciclo y puede
causar que el bridge duplique o pierda entradas en la siguiente review.
**Regla:** no editar `review_queue.md` manualmente. Esta permitida la rotacion
automatica offline gestionada por el motor en `session_closeout.py` durante
`--session-close`, que preserva cabecera, ticket activo y 10 entradas recientes.
El podado manual queda terminantemente prohibido (ver WT-2026-190).
