# Work Plan - WOT-2026-019q

## Metadata
- **ID:** WOT-2026-019q
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Permitir el cierre canonico de un ticket cuyo commit no es HEAD
  (batch-close no contiguo) sin aceptar entregas vacias.
- **Creado:** 2026-07-06
- **Prioridad:** Alta
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Modificar resolve_motor_checkpoint_files en .agent/motor_checkpoint.py para
que un ticket cuyo commit checkpoint (M3, checkpoint/review-<ticket>) NO es
HEAD pueda cerrar canonicamente (--mark-ready -> --manager-approve) cuando
su commit es ancestro real de HEAD, su commit message contiene el ticket_id,
y la caminata de contiguidad desde ESE commit recupera un conjunto de archivos
NO VACIO. El caso comun (sha == head_sha, ticket topmost) NO cambia de
comportamiento. Un M3 que apunte a un commit vacio (<ticket>: closeout sin
diff real) debe seguir siendo RECHAZADO explicitamente.

## Contexto

Fase 0 del Orquestador (script reproducible, re-ejecutado de forma
independiente por este Manager con el venv de la worktree-dev) demostro con
un fixture git real y el modulo motor_checkpoint real (no mocks):

1. resolve_motor_checkpoint_files Step 3 (l.247-252 de
   .agent/motor_checkpoint.py) exige sha == head_sha; si no, devuelve
   ok=False con "Tag ...@<sha> is stale; expected HEAD <head_sha>". Este es
   el UNICO paso que bloquea el cierre de un ticket enterrado bajo otro commit
   posterior.
2. Step 2 (is_git_ancestor_of_head, l.235) YA garantiza que el commit del
   checkpoint sea ancestro de HEAD antes de llegar a Step 3 -- es decir, el
   diff del ticket SI esta realmente entregado en la historia de HEAD cuando
   se llega a evaluar Step 3.
3. contiguous_ticket_commits(motor_root, sha_ticket, ticket_id) invocado
   DESDE el commit real del ticket enterrado (no desde HEAD) devuelve
   EXACTAMENTE el commit propio del ticket, y files_from_commits sobre ese
   resultado recupera SOLO el diff de ese ticket. La maquinaria de contiguidad
   ya funciona correctamente para el caso no-HEAD; Step 3 es el bloqueador
   aislado.
4. Un commit vacio de cierre (<ticket>: closeout, git commit --allow-empty)
   pasa Step 3 (si se tagea a si mismo, es HEAD) y Step 4 (subject contiene el
   ticket_id), pero files_from_commits sobre el devuelve set() (cero
   archivos). Este es el anti-patron que la ficha prohibe explicitamente: la
   solucion debe rechazar una entrega de cero archivos.

Caso real que motiva el ticket: CTL-2026-009k, 009g, 009i (implementados,
revisados y pusheados a origin/main en el destino Crear_Texto_LLM) quedaron
completed-partial porque sus commits quedaron enterrados bajo 009j (ya
cerrado), y la gate de cierre no es bypassable via --force ni
--scope-override (agent_controller.py:1704).

## Decision Arquitectonica

Opcion elegida: (a) cierre no-HEAD.

La ficha ofrece dos opciones: (a) relajar Step 3 para aceptar un M3 no-HEAD
verificando contiguidad+entrega no vacia desde el commit real del ticket; o
(b) prohibir el batch-close con diagnostico accionable. Se elige (a).

Justificacion (evidencia de Fase 0, punto 3 arriba): la maquinaria de
contiguidad y recoleccion de archivos YA funciona correctamente para el commit
real del ticket enterrado; el unico cambio necesario es narrow (Step 3). La
opcion (b) NO desbloquea los 3 tickets reales que motivan la ficha (009k/009g/
009i ya estan commiteados y enterrados; prohibir el batch-close no ayuda a
el problema ya ocurrido (los commits ya enterrados de 009k/009g/009i), solo evita que vuelva a pasar en el futuro). (a) resuelve
tanto el caso ya ocurrido como previene la recurrencia (con las barreras de
abajo), por lo que aporta mas valor con un cambio de superficie menor.

Riesgo evaluado y mitigado: relajar sha != head_sha podria, en teoria, abrir
un bypass donde cualquier commit historico con subject conteniendo el
ticket_id certifique una entrega no relacionada con el cierre real. Se mitiga
asi:
- Step 2 (ancestor-of-HEAD) se preserva sin cambios: el commit debe estar
  realmente en la historia de HEAD.
- Step 4 (subject contiene ticket_id) se preserva sin cambios, aplicado sobre
  el commit real (sha), no sobre HEAD.
- Contiguidad hacia atras del propio ticket (contiguous_ticket_commits) se
  preserva sin cambios de firma ni de logica interna.
- Entrega NO vacia: se anade una verificacion nueva explicita despues de
  files_from_commits: si el conjunto de archivos resultante esta vacio, el
  checkpoint se RECHAZA con un mensaje diagnostico nuevo y distinto
  ("Checkpoint ... delivers no files; refusing empty closeout"), en vez de
  aceptarlo silenciosamente. Esto cierra explicitamente el anti-patron del
  commit vacio de cierre (punto 4 de Contexto), que de otro modo pasaria a
  certificar cero archivos bajo la logica relajada.
- El caso comun HEAD==tag (ticket topmost) sigue el mismo camino de codigo
  hasta Step 2; Step 3 pasa a ser informativo (ya no bloqueante por si solo)
  pero el resultado observable para ese caso (files recuperados == diff del
  topmost) es IDENTICO al comportamiento actual, verificado por el test de
  control ya existente en Fase 0 (Escenario B) y por el test de no-regresion
  nuevo de este ticket.
- Distincion "M3 legitimo al commit real" vs "M3 stale por olvido de
  --pre-handoff": bajo el nuevo contrato, un M3 es aceptado si (1) es
  ancestro de HEAD, (2) su subject contiene el ticket_id, y (3) la caminata de
  contiguidad desde el produce un conjunto de archivos no vacio. El caso de
  "olvido de --pre-handoff" (working tree modificado DESPUES de crear el M3,
  sin volver a taguearlo) no lo detecta este mecanismo -- lo sigue detectando
  el chequeo de arbol sucio (pre_handoff_guard.py / dirty-tree check) que se
  ejecuta ANTES de invocar resolve_motor_checkpoint_files en los 3 call
  sites de agent_controller.py (l.2849, 2927, 3350) y que este ticket NO
  modifica. Es decir: "stale por arbol sucio" y "stale por Step 3 == HEAD" son
  chequeos ortogonales; este ticket solo relaja el segundo, preservando el
  primero intacto.

## Superficie tocada (topologia verificada)

_resolve_motor_checkpoint_files en agent_controller.py (l.3587) es un
alias de motor_checkpoint.resolve_motor_checkpoint_files y se invoca en 3
sitios (l.2849, 2927, 3350). Los 3 call sites consumen unicamente la tupla de
retorno (valid: bool, files: set[str], error: str) de forma generica (no
inspeccionan el string interno de Step 3 para tomar decisiones de control mas
alla de imprimir cp_error o pasarlo a _print_motor_checkpoint_guidance).
Por lo tanto el cambio queda LOCALIZADO en .agent/motor_checkpoint.py;
agent_controller.py NO requiere modificacion de logica. La UNICA funcion
adicional que se toca dentro de motor_checkpoint.py (no en
agent_controller.py) es print_motor_checkpoint_guidance, para anadir
guidance del nuevo mensaje de "empty closeout" (ver Fase 2.2).

## Plan de Implementacion

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| BOT | TAREA AGENTE | Builder |

### Fase 1: Tests primero (TDD) - escenarios no-HEAD y anti-patron vacio

#### 1.1: BOT Anadir tests de escenario no-HEAD y de entrega vacia
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/unit/test_motor_checkpoint.py
- **Accion:** Modificar (anadir clase de test nueva, no tocar las existentes)
- **Descripcion:** Anadir una clase TestResolveMotorCheckpointFilesNonHead
  con, como minimo, estos casos (fixture git real via subprocess, igual
  patron que _init_git_repo/_add_committed_work_plan ya presentes en el
  archivo; NO usar mocks de git):
  1. test_buried_ticket_with_real_m3_closes_and_recovers_own_files: construye
     un repo con commit base, commit del ticket A (file_a.py, subject
     f"{ticket_a}: implement A"), tag M3 checkpoint/review-<ticket_a>
     apuntando al commit de A, y luego un commit de ticket B ENCIMA (HEAD).
     Llama a resolve_motor_checkpoint_files(repo, ticket_a) y asegura
     ok is True y files == {"file_a.py"}.
  2. test_topmost_ticket_head_unchanged_behavior (control/no-regresion):
     mismo fixture, tag M3 de ticket B apuntando a HEAD (el propio commit de
     B). Asegura ok is True y files == {"file_b.py"} -- exactamente el
     comportamiento actual, sin cambios observables.
  3. test_empty_closeout_commit_is_rejected: construye un repo con el commit
     del ticket A real (file_a.py) y luego un commit VACIO
     (git commit --allow-empty -m "<ticket_a>: closeout") como HEAD, con el M3
     apuntando a ese commit vacio. Asegura ok is False y que el mensaje de
     error contenga el texto literal "refusing empty closeout" fijado en
     Fase 2.1 (el test usa ESE texto exacto, no una subcadena generica).
  4. test_non_ancestor_still_rejected (no-regresion de Step 2): M3 tageado
     en una rama lateral no fusionada a HEAD; asegura ok is False y el
     mensaje sigue siendo el de "not an ancestor of HEAD" (Step 2 no cambia).
  5. test_subject_without_ticket_id_still_rejected (no-regresion de Step 4):
     M3 apuntando a un commit real cuyo subject NO contiene el ticket_id;
     asegura ok is False con el mensaje de Step 4 sin cambios.
- **Riesgo:** MEDIO (fixtures git nuevas, pero patron ya establecido en el
  mismo archivo)
- **Criterio de Aceptacion:** Los 5 tests se ejecutan con el comando
  ".venv\Scripts\python.exe -m pytest tests/unit/test_motor_checkpoint.py -k TestResolveMotorCheckpointFilesNonHead -v"
  y en este punto (ANTES del fix de Fase 2) los tests 1.1.1 y 1.1.3 FALLAN
  (reproducen el bug/anti-patron), y 1.1.2/1.1.4/1.1.5 PASAN (comportamiento ya
  correcto hoy). Esto documenta el estado pre-fix como evidencia TDD.

### Fase 2: Implementar la relajacion de Step 3 + rechazo de entrega vacia

#### 2.1: BOT Modificar resolve_motor_checkpoint_files
- **Tipo:** TAREA AGENTE
- **Archivo:** .agent/motor_checkpoint.py
- **Accion:** Modificar
- **Descripcion:** En resolve_motor_checkpoint_files (l.212-283 actual):
  1. Mantener Step 1 (resolver tag SHA) y Step 2 (ancestor-of-HEAD) sin
     cambios.
  2. Cambiar Step 3: en vez de retornar (False, set(), "...is stale...")
     inmediatamente cuando sha != head_sha, continuar la evaluacion (no
     bloquear aqui). El chequeo de "stale" deja de ser una condicion de
     retorno temprano; se convierte en informacion que solo importa para el
     mensaje de error si los pasos posteriores tambien fallan. Concretamente:
     eliminar el return temprano de Step 3; conservar el calculo de
     head_sha (se sigue necesitando para Step 2 y para logs/diagnostico) y
     seguir el flujo hacia Step 4.
  3. Mantener Step 4 (subject contiene ticket_id) sin cambios de logica,
     aplicado sobre sha (el commit real del checkpoint, como ya hace hoy).
  4. Mantener la llamada a contiguous_ticket_commits(motor_root, sha,
     ticket_id) sin cambios de firma ni de logica interna.
  5. Anadir DESPUES de files_from_commits: si files es un set vacio,
     retornar (False, set(), f"Checkpoint {tag_name}@{sha[:8]} delivers no
     files; refusing empty closeout") en vez de (True, files, ""). Este
     chequeo aplica tanto al caso HEAD==tag como al caso no-HEAD (simetrico,
     no depende de la rama Step 3).
  6. El mensaje de error de "is stale; expected HEAD" de Step 3 (texto
     original) se ELIMINA como retorno temprano bloqueante; NO debe aparecer
     mas como causa de fallo del camino feliz no-HEAD. Si se desea preservar
     el string en algun log informativo no bloqueante, debe quedar claramente
     fuera del valor de retorno de error (no concatenado al err
     devuelto cuando ok=True).
- **Riesgo:** ALTO (cambia el contrato de una gate de cierre no
  bypasseable; blast radius = cualquier cierre de ticket del motor)
- **Criterio de Aceptacion:**
  - resolve_motor_checkpoint_files para un M3 no-HEAD con subject valido,
    ancestro de HEAD, y archivos no vacios devuelve ok=True con el set de
    archivos correcto (verificado por el test 1.1.1 de Fase 1, ahora en
    verde).
  - El caso HEAD==tag (control) sigue devolviendo exactamente el mismo
    resultado que antes del cambio (verificado por el test 1.1.2, en verde
    antes y despues del fix -- no debe haber ninguna diferencia observable).
  - Un M3 sobre commit vacio es rechazado (test 1.1.3 en verde).
  - Step 2 y Step 4 siguen bloqueando sus casos (tests 1.1.4 y 1.1.5 en
    verde, sin cambio de comportamiento).

#### 2.2: BOT Actualizar guidance de error (obligatoria)
- **Tipo:** TAREA AGENTE
- **Archivo:** .agent/motor_checkpoint.py
- **Accion:** Modificar
- **Descripcion:** En print_motor_checkpoint_guidance (l.358-373), anadir
  una rama elif "refusing empty closeout" in cp_error: que emita guidance
  accionable especifica: "El checkpoint M3 apunta a un commit sin diff real.
  Re-ejecuta --pre-handoff apuntando al commit que SI contiene el trabajo del
  ticket; no uses un commit de cierre vacio." Esta tarea NO modifica el
  contrato de retorno de Fase 2.1, solo mejora el mensaje impreso al Builder
  cuando el nuevo caso de rechazo ocurre.
- **Riesgo:** BAJO (solo texto de guidance, no logica de gate)
- **Criterio de Aceptacion:** Ejecutar un script Python de una linea que
  importe motor_checkpoint (con .agent en sys.path) y llame a
  print_motor_checkpoint_guidance("T-1", "Checkpoint checkpoint/review-T-1
  delivers no files; refusing empty closeout") debe imprimir una linea que
  contenga "empty closeout" o "commit vacio" en la guidance mostrada (no el
  texto generico de "Run --pre-handoff first..."), exit code 0.

### Fase 3: Mutation-verify y suite completa

#### 3.1: BOT Mutation-verify manual del fix
- **Tipo:** TAREA AGENTE
- **Archivo:** (ninguno nuevo; verificacion sobre .agent/motor_checkpoint.py
  y tests/unit/test_motor_checkpoint.py)
- **Accion:** Verificar (no crea archivo)
- **Descripcion:** Revertir temporalmente el cambio de Fase 2.1 (con git
  stash o comentando el return temprano restaurado) y ejecutar
  ".venv\Scripts\python.exe -m pytest tests/unit/test_motor_checkpoint.py -k TestResolveMotorCheckpointFilesNonHead -v".
  Confirmar que los tests 1.1.1 y 1.1.3 (los que dependen directamente del fix)
  FALLAN sin el, y que al restaurar el fix (git stash pop o descomentar)
  vuelven a PASAR. Documentar el resultado (comando + output relevante) en
  execution_log.md.
- **Riesgo:** MEDIO (paso de verificacion, no debe dejar el repo en estado
  revertido)
- **Criterio de Aceptacion:** Evidencia textual en execution_log.md de:
  (a) comando + output con tests 1.1.1/1.1.3 en rojo tras revertir, exit code
  1; (b) comando + output con los 5 tests en verde tras restaurar, exit
  code 0.

#### 3.2: BOT Correr gates de calidad completos
- **Tipo:** TAREA AGENTE
- **Archivo:** N/A (comandos)
- **Accion:** Verificar
- **Descripcion:** Ejecutar, en este orden, desde
  C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev:
  1. ruff check .
  2. .venv\Scripts\python.exe scripts\run_pytest_safe.py
  Ambos deben terminar en exit code 0. Si run_pytest_safe.py reporta fallos
  pre-existentes documentados en memoria (ninguno conocido para este modulo),
  el Builder debe distinguir explicitamente fallos nuevos introducidos por
  este ticket de fallos heredados, citando el archivo/test exacto.
- **Riesgo:** MEDIO
- **Criterio de Aceptacion:** ruff check . exit code 0. run_pytest_safe.py
  exit code 0 y last-run.json con tested_commit_sha == HEAD (verificado
  tras el commit de handoff, no antes).

## Non-goals

- No reescribir historia de ramas del usuario.
- No relajar la exigencia de suite fresh-green ni de subject con ticket_id.
- No permitir cerrar un ticket cuyo diff NO este en la historia de HEAD (Step
  2 ancestor-of-HEAD se preserva intacto).
- No tocar la superficie de cross_root ni de scope_gate.py mas alla de lo
  necesario (este ticket no las toca en absoluto).
- No modificar agent_controller.py: los 3 call sites consumen la tupla de
  retorno de forma generica y no requieren cambios (verificado en el analisis
  de superficie arriba).
- No implementar la Opcion (b) (prohibir batch-close): se descarta
  explicitamente por la justificacion de la Decision Arquitectonica.
- No cerrar el bus de CTL-2026-009k/009g/009i: esa es la deuda de destino
  ligada, fuera de scope de este ticket de motor (la ejecuta el destino
  Crear_Texto_LLM una vez este ticket cierre).

## Files Likely Touched

- .agent/motor_checkpoint.py
- tests/unit/test_motor_checkpoint.py
- tests/test_mark_ready_motor_scope.py (2 tests del contrato viejo tag==HEAD,
  derogado por este ticket, actualizados al contrato nuevo; scope-expansion
  justificada CEM: el cambio de contrato invalida sus aserciones)
- tests/test_setup_dev_worktree_script.py (hotfix de entorno: asercion
  path-fragil de un test de 019m que falla SOLO al correr la suite desde la
  worktree-dev por colision de substring con la ruta del sandbox; bloquea el
  gate de cierre-desde-dev de cualquier ticket; fix 1-linea aprobado por el
  humano, analogo a los hotfixes CI de 019m)

## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| (a) Relajar Step 3, verificar contiguidad+entrega no vacia desde el commit real | Desbloquea los 3 tickets reales ya entregados; maquinaria de contiguidad ya funciona (Fase 0); cambio narrow y localizado en un modulo | Toca una gate de cierre no-bypasseable (blast radius alto); requiere mutation-verify riguroso | Elegida |
| (b) Prohibir batch-close con diagnostico | Cambio mas simple; evita la clase de problema hacia el futuro | NO desbloquea 009k/009g/009i (ya commiteados y enterrados); solo previene, no resuelve el caso ya ocurrido | Descartada |
| Commit vacio de cierre como atajo | Ninguno real (ceremonial) | Certifica cero archivos; anti-patron explicitamente prohibido por la ficha | Descartada (rechazada activamente por Fase 2.1) |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Calidad

- ruff check . -> exit code 0 (Fase 3.2).
- .venv\Scripts\python.exe scripts\run_pytest_safe.py -> exit code 0,
  last-run.json.tested_commit_sha == HEAD (Fase 3.2).
- .venv\Scripts\python.exe -m pytest tests/unit/test_motor_checkpoint.py -k TestResolveMotorCheckpointFilesNonHead -v
  -> exit code 0 con los 5 tests nuevos en verde tras el fix (Fase 1 + Fase 2).
- Mutation-verify: revertir Fase 2.1 -> tests 1.1.1 y 1.1.3 en rojo (exit code
  1); restaurar -> los 5 en verde (exit code 0) (Fase 3.1).
- Script Python de una linea que ejerza print_motor_checkpoint_guidance con
  el mensaje "refusing empty closeout" -> exit code 0, guidance nueva
  presente (Fase 2.2).

## Criterios de Aceptacion Global

- [ ] Un ticket cuyo commit NO es HEAD, con M3 apuntando a su commit real y
      diff real en la historia de HEAD, cierra canonico (test
      test_buried_ticket_with_real_m3_closes_and_recovers_own_files en
      verde: ok=True, files == su propio diff, no el del topmost).
- [ ] La solucion NO acepta un commit vacio como entrega (test
      test_empty_closeout_commit_is_rejected en verde: ok=False).
- [ ] Mutation-verify: revertir el fix hace que
      test_buried_ticket_with_real_m3_closes_and_recovers_own_files y
      test_empty_closeout_commit_is_rejected FALLEN; restaurar los deja en
      verde (Fase 3.1, evidencia en execution_log.md).
- [ ] Suite canonica run_pytest_safe.py verde; exit code 0.
- [ ] El caso comun HEAD==tag no cambia de comportamiento observable (test
      test_topmost_ticket_head_unchanged_behavior en verde, identico
      antes/despues del fix).
- [ ] ruff check . exit code 0.

## Handoff

### 2026-07-06 Handoff: Manager -> Builder
**Plan:** WOT-2026-019q
**Accion requerida:** Implementar segun work_plan.md (Fases 1 a 3, en orden TDD).
**Estado:** PENDING
