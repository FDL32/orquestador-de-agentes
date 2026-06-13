# Destination Preflight

Checklist generico para arrancar `orchestrate-pipeline` sobre cualquier
`repo_destino`.

## Objetivo

Antes de convertir un item del backlog en ticket activo, confirmar que el
destino esta en un estado coherente. El pipeline no debe empezar sobre drift
operativo, archivos de estado zombies o backlog no alineado.

## Checks obligatorios

1. Confirmar root:
   - `cwd` es el `repo_destino`.
   - `.agent/config/motor_destination_link.json` existe.
   - `MOTOR_ROOT` resuelve a un motor existente.

2. Confirmar ticket activo:
   - leer `.agent/collaboration/work_plan.md`;
   - leer `.agent/collaboration/STATE.md`;
   - leer `.agent/collaboration/TURN.md`;
   - si apuntan a tickets distintos, detener y reportar `PIPELINE_BLOCKED`.

3. Confirmar backlog:
   - `.agent/collaboration/backlog.md` existe;
   - cada ticket candidato declara ID, estado, prioridad, dependencia y
     `deliverable_type`;
   - no arrancar tickets dependientes de otro no completado.

4. Confirmar estado runtime:
   - revisar `.agent/runtime/events/events.jsonl` si existe;
   - si el bus contradice `STATE.md` o `TURN.md`, detener y reportar drift;
   - no inventar eventos para cerrar la discrepancia.

5. Confirmar git:
   - `git status --short` del repo que recibira cambios;
   - cambios sucios solo son aceptables si pertenecen al ticket activo o estan
     documentados como preexistentes.

6. Confirmar validate:
   - ejecutar `python <MOTOR_ROOT>/.agent/agent_controller.py --validate --json --project-root .`;
   - no arrancar Builder con errores;
   - warnings requieren decision explicita: blocker, deuda no bloqueante o
     limpieza previa.

## Politica sobre archivos de estado

Archivos como `.session_state.json`, `STATE.md`, `TURN.md` y `backlog.md` no se
limpian a ciegas.

Si estan modificados:

- leer primero el contenido;
- contrastar con el bus y el ticket activo;
- si son residuos de ciclo anterior, mover/copiar evidencia a
  `orchestrator_pipeline/cleanup/<TICKET_ID>/` antes de regenerar;
- registrar la decision en `execution_log.md` y en el closeout report.

## Resultado esperado

El preflight termina con una de estas decisiones:

- `READY`: el pipeline puede arrancar el siguiente ticket.
- `NEEDS_RECONCILE`: hay drift resoluble antes de Builder.
- `PIPELINE_BLOCKED`: falta estado, hay contradiccion de ticket o el destino no
  es seguro para arrancar.
