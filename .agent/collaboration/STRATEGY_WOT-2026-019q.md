# STRATEGY_WOT-2026-019q

## Ticket
WOT-2026-019q -- Cierre canonico de un ticket cuyo commit no es HEAD
(batch-close no contiguo), sin aceptar entregas vacias.

## Problema tecnico

resolve_motor_checkpoint_files (en .agent/motor_checkpoint.py) certifica el
cierre de un ticket via el tag checkpoint/review-<ticket_id>. Step 3 exige
sha == head_sha (el tag debe apuntar exactamente a HEAD). Cuando se apilan
commits de varios tickets y se cierran en lote, solo el topmost (== HEAD)
pasa Step 3; los tickets enterrados fallan con "is stale; expected HEAD"
aunque su diff SI este en la historia de HEAD (Step 2, ancestor-of-HEAD, ya
lo garantiza antes de llegar a Step 3).

## Decision: Opcion (a)

Relajar Step 3 para que no sea un retorno temprano bloqueante. El commit del
checkpoint puede ser HEAD o no; lo que determina si el checkpoint es valido
es:
1. Step 1: el tag resuelve a un SHA real.
2. Step 2 (sin cambios): ese SHA es ancestro de HEAD.
3. Step 4 (sin cambios, aplicado sobre el SHA real del tag, no sobre HEAD): el
   subject del commit contiene el ticket_id.
4. contiguous_ticket_commits (sin cambios de firma/logica) camina hacia atras
   desde el SHA del tag acumulando commits contiguos del mismo ticket.
5. files_from_commits (sin cambios de firma/logica) recolecta el diff de esos
   commits.
6. NUEVO: si el set de archivos resultante esta vacio, el checkpoint se
   rechaza explicitamente con un mensaje distinto de los anteriores
   ("Checkpoint <tag>@<sha> delivers no files; refusing empty closeout").
   Este chequeo nuevo aplica siempre (HEAD==tag o no), cerrando el anti-patron
   del commit vacio de cierre.

## Por que el cambio es narrow (localizado en motor_checkpoint.py)

Los 3 call sites en agent_controller.py (l.2849, 2927, 3350) invocan
_resolve_motor_checkpoint_files (alias de motor_checkpoint.
resolve_motor_checkpoint_files, fijado en l.3587) y solo consumen la tupla
(valid, files, error) de forma generica: usan valid para bifurcar y error
para mensajes de log/guidance. Ninguno inspecciona el contenido literal del
mensaje de Step 3 para tomar una decision de control adicional (mas alla de
imprimirlo). Por tanto agent_controller.py no requiere cambios de logica; el
contrato de entrada/salida de la funcion permanece identico
((bool, set[str], str)), solo cambia CUANDO se retorna True/False.

## Invariantes preservados (no tocar)

- Step 2 ancestor-of-HEAD: sin cambios. Un ticket cuyo commit NO este en la
  historia de HEAD sigue bloqueado con "not an ancestor of HEAD".
- Step 4 subject-contains-ticket-id: sin cambios de logica, se sigue aplicando
  sobre el SHA real del tag.
- contiguous_ticket_commits: sin cambios de firma ni de logica interna (ya
  demostrado feasible en Fase 0 para el caso no-HEAD).
- El caso comun HEAD==tag (ticket topmost, el 99% de los cierres) produce
  exactamente el mismo resultado observable que antes del cambio: unico
  cambio de comportamiento es que Step 3 deja de ser un gate bloqueante
  aislado, pero el resultado final para ese caso no varia porque Step 2 y
  Step 4 siguen pasando igual y files_from_commits sigue recolectando el
  mismo set no vacio.
- --pre-handoff / dirty-tree check (fuera de este modulo): no se modifica.
  Sigue siendo el mecanismo que detecta "M3 desactualizado por olvido de
  volver a correr --pre-handoff tras cambios posteriores en el arbol".

## Distincion M3 legitimo vs M3 stale por olvido

Bajo el contrato nuevo, "M3 legitimo" = ancestro de HEAD + subject con
ticket_id + contiguidad no vacia. Esto es exactamente lo que certifica un M3
creado correctamente por --pre-handoff en el momento en que el commit del
ticket era HEAD, sin importar que despues se apilen commits de otros
tickets encima. "M3 stale por olvido de --pre-handoff" es un escenario
DISTINTO: el working tree cambia DESPUES de crear el M3 sin volver a
taguearlo -- ese escenario lo sigue detectando el dirty-tree check ANTES de
que se llegue a invocar resolve_motor_checkpoint_files, no depende de Step 3.
Los dos mecanismos son ortogonales y este ticket solo toca el segundo.

## Contrato de retorno (sin cambios de firma)

resolve_motor_checkpoint_files(motor_root: Path, ticket_id: str) -> tuple[bool, set[str], str]

Cambia UNICAMENTE la logica interna: cuando se retorna True/False y con que
mensaje, no la firma ni el tipo de los valores.

## Alcance de archivos

- .agent/motor_checkpoint.py: logica de resolve_motor_checkpoint_files +
  guidance en print_motor_checkpoint_guidance.
- tests/unit/test_motor_checkpoint.py: 5 tests nuevos (clase
  TestResolveMotorCheckpointFilesNonHead), sin tocar los tests existentes.

agent_controller.py NO se toca (verificado: los 3 call sites son agnosticos
al mensaje interno de Step 3).
