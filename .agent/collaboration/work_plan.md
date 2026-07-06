# Work Plan - WOT-2026-019u

## Metadata
- **ID:** WOT-2026-019u
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Eliminar rama muerta de print_motor_checkpoint_guidance tras WOT-2026-019q
- **Creado:** 2026-07-06
- **Prioridad:** Baja
- **Asignado a:** Builder
- **delivery_authority:** repo_motor
- **Depende de:** WOT-2026-019q (cerrado @ d7d15db)

## Objetivo

Eliminar 11 lineas de codigo muerto en
`.agent/motor_checkpoint.py::print_motor_checkpoint_guidance` (lineas
388-398): la rama `if "stale; expected HEAD" in cp_error:` quedo
inalcanzable porque WOT-2026-019q elimino el unico emisor de ese string
(el early-return de Step 3 en `resolve_motor_checkpoint_files`). La rama
`if "refusing empty closeout" in cp_error:` (introducida por 019q) y el
`print` generico final se preservan sin cambios.

## Contexto

Premisa verificada por el Orquestador en Fase 0 y reconfirmada por este
Manager leyendo `.agent/motor_checkpoint.py` lineas 385-408: el grep
repo-wide de `"stale; expected HEAD"` sobre `.agent scripts bus tests` da
exactamente 2 hits -- (1) el consumidor muerto en
`.agent/motor_checkpoint.py:388`, (2) una mencion documental en
`.agent/collaboration/execution_log_WOT-2026-019q.md:42` (registro
historico de una corrida de test, no codigo). Cero emisores del string
como valor de error real: `resolve_motor_checkpoint_files` (la funcion que
antes lo emitia) ya no lo produce desde el commit `d7d15db`.

Grep de `print_motor_checkpoint_guidance` da dos consumidores: el call-site
vivo en `agent_controller.py:3391` (`_print_motor_checkpoint_guidance(plan_id,
cp_error)`, solo invoca la funcion, no depende de la rama muerta) y el alias
en `agent_controller.py:3591`. `tests/unit/test_motor_checkpoint.py` no
contiene ninguna referencia a `print_motor_checkpoint_guidance` ni a
"guidance" (grep vacio) -- no existe ningun test que ejerza la rama muerta,
por lo que el DoD de "adaptar tests que dependan de ella" se satisface por
ausencia: no hay que tocar ningun test.

## Decision Arquitectonica

Borrar el bloque completo de la rama muerta (el `if`, sus dos llamadas a
`print(...)` y su `return`) en una sola edicion atomica, en vez de borrar
solo la condicion `if` y dejar el cuerpo huerfano. Por que: dejar el
cuerpo sin guardia introduciria un `return` incondicional que rompe el
flujo hacia las ramas siguientes (`refusing empty closeout` y el print
generico final quedarian inalcanzables), invirtiendo el bug en vez de
resolverlo. Tampoco se anade un test nuevo que ejerza la rama eliminada:
al no existir hoy ningun test que dependa de ella (grep vacio en
`tests/unit/test_motor_checkpoint.py`), no hay comportamiento que
verificar de una rama que deja de existir; anadir uno seria probar la
ausencia de codigo, no una regla de negocio.

## Non-goals

- No se modifica `resolve_motor_checkpoint_files` ni ninguna otra funcion
  de `.agent/motor_checkpoint.py`: WOT-2026-019q ya fijo esa logica de
  gate y este ticket no la reabre.
- No se reabre ni se renegocia el contrato de cierre de WOT-2026-019q
  (Step 2, Step 4, la caminata de contiguidad y el guard de empty-closeout
  quedan exactamente como estan).
- No se anaden casos nuevos, mensajes nuevos ni ramas nuevas a la
  condicion de refusing empty closeout; se preserva bit-a-bit.
- No se modifica `agent_controller.py`: el call-site en la linea 3391 y el
  alias en la linea 3591 siguen invocando la funcion sin cambios de firma
  ni de comportamiento.
- No se crean tests nuevos para la rama eliminada: al no existir ningun
  test previo que dependa de la rama muerta, no hay comportamiento
  pendiente de cobertura.

## Files Likely Touched

- `.agent/motor_checkpoint.py` (unico archivo modificado; borrado de 11
  lineas, funcion `print_motor_checkpoint_guidance`, lineas 388-398 segun
  el estado actual del archivo).

## Read/inspect only

- `.agent/agent_controller.py` (confirmar que el call-site en la linea 3391
  y el alias en la linea 3591 siguen invocando la funcion sin cambios; no
  se edita).
- `tests/unit/test_motor_checkpoint.py` (confirmar que no existe ningun
  test que referencie `print_motor_checkpoint_guidance` o la rama muerta
  antes y despues del borrado; no se edita salvo que la Fase 2 encuentre
  una referencia que Fase 0 o el Manager no detectaron, ver Fase 2).

## Manager-only

- `.agent/collaboration/work_plan.md` (este archivo).
- `.agent/collaboration/AUDIT_WOT-2026-019u.md`.
- `.agent/collaboration/execution_log.md` y `execution_log_WOT-2026-019u.md`
  (bitacora; el Manager inicializa el estado IN_PROGRESS, el Builder anota
  su ejecucion).

## Plan de Implementacion

### Tipos de Tareas

| Marca | Tipo | Ejecutor |
|-------|------|----------|
| [AGENTE] | TAREA AGENTE | Builder |

### Fase 1: Verificacion previa al borrado [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** `.agent/motor_checkpoint.py`, `tests/unit/test_motor_checkpoint.py`
- **Accion:** Verificar (sin modificar)
- **Descripcion:** Ejecutar `grep -rn "stale; expected HEAD" .agent scripts bus tests`
  y confirmar que el unico emisor de codigo vivo es la linea 388 de
  `.agent/motor_checkpoint.py` (el resto, si aparece, debe ser comentario,
  docstring o `execution_log`). Ejecutar
  `grep -rn "print_motor_checkpoint_guidance" tests/` y confirmar que no
  hay matches. Si cualquiera de los dos greps revela un emisor de codigo
  vivo distinto al ya conocido, o un test que referencie la funcion, el
  Builder detiene la Fase 2 y escala al Manager citando el hit exacto
  archivo:linea antes de tocar codigo.
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** El comando
  `grep -rn "stale; expected HEAD" .agent scripts bus tests` (ejecutado
  desde la raiz del repo) devuelve como maximo 2 lineas: la definicion en
  `.agent/motor_checkpoint.py` y la mencion en
  `.agent/collaboration/execution_log_WOT-2026-019q.md`; y el comando
  `grep -rln "print_motor_checkpoint_guidance" tests/` devuelve 0 archivos.
- **Si falla:** Escalar al Manager con el output literal del grep antes de
  iniciar la Fase 2.

### Fase 2: Borrado de la rama muerta [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** `.agent/motor_checkpoint.py`
- **Accion:** Modificar
- **Descripcion:** En la funcion `print_motor_checkpoint_guidance` (lineas
  385-408 en el estado actual del archivo), eliminar el bloque completo
  que empieza en la linea con `if "stale; expected HEAD" in cp_error:` y
  termina en el `return` de esa rama (11 lineas: el `if`, dos llamadas a
  `print(...)` con su string multi-linea cada una, y el `return`). El
  resultado debe conservar, sin ninguna otra edicion: (a) la linea
  `print(f"[ERROR] No valid motor checkpoint for {plan_id}: {cp_error}")`
  al inicio de la funcion; (b) el bloque completo con la condicion sobre
  `refusing empty closeout` con sus dos `print(...)` y su `return`,
  intacto; (c) la linea final
  `print("Run --pre-handoff first to create checkpoint/review-<ticket> in repo_motor.")`
  como unico fallback. No se toca ninguna otra funcion del archivo
  (`resolve_git_tag_sha`, `resolve_motor_checkpoint_files` u otras quedan
  bit-a-bit identicas).
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** `git diff -- .agent/motor_checkpoint.py`
  muestra unicamente 11 lineas eliminadas (sin lineas anadidas, sin
  cambios en ninguna otra funcion del archivo); la funcion
  `print_motor_checkpoint_guidance` resultante tiene exactamente 2 ramas
  condicionales (la de `refusing empty closeout` seguida del `return`) mas
  el `print` generico final, sin la rama de `stale; expected HEAD`;
  `grep -c "stale; expected HEAD" .agent/motor_checkpoint.py` devuelve 0.
- **Si falla:** Revertir el archivo a HEAD con
  `git checkout -- .agent/motor_checkpoint.py` y escalar al Manager.

### Fase 3: Gates de calidad [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** N/A (comandos de verificacion)
- **Accion:** Ejecutar (no modifica codigo)
- **Descripcion:** Correr, en este orden, desde la raiz del repo con el
  interprete de la worktree-dev:
  1. `./.venv/Scripts/python.exe -m ruff check .agent/motor_checkpoint.py`
  2. `PYTHONDONTWRITEBYTECODE=1 ./.venv/Scripts/python.exe scripts/run_pytest_safe.py --level all`
     (runner canonico del repo; debe correr la suite completa, no un
     subconjunto).
  3. `./.venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .`
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** ruff sale con exit code 0 y 0 findings sobre
  el archivo; la suite completa sale verde (0 failed) y el checkpoint que
  produce reporta `tested_commit_sha` igual al HEAD del commit que
  contiene el borrado de Fase 2; `--validate --json` reporta `errors: 0` y
  `warnings: {}` (objeto vacio).
- **Si falla:** No proceder a handoff ni pre-handoff; escalar al Manager
  con el output literal del gate que fallo.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Borrar solo el `if` y dejar el `return` huerfano | Diff mas chico | Deja codigo inalcanzable residual, no resuelve el objetivo | Descartada |
| Borrar el bloque completo (if, dos prints, return) | Elimina toda la rama muerta; la funcion queda con 2 ramas mas fallback, exactamente el contrato del DoD | Ninguno relevante para un cleanup de 11 lineas | Elegida |
| Anadir un test negativo sobre la rama ya inalcanzable | Documenta el cierre | El DoD no lo exige y no hay nada que probar de una rama que ya no existe | Descartada |

## Guia de Riesgos

| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| [Bajo] | Rutinaria | Intentar 3 veces antes de escalar |

## Criterios de Aceptacion Global

- [ ] `grep -rn "stale; expected HEAD" .agent scripts bus tests` da como
      maximo 2 lineas (definicion mas mencion documental en execution_log
      de 019q), 0 emisores de codigo vivo.
- [ ] La rama condicional sobre `stale; expected HEAD` (11 lineas) esta
      eliminada de `.agent/motor_checkpoint.py`; la rama de
      `refusing empty closeout` y el `print` generico final quedan
      intactos.
- [ ] `ruff check .agent/motor_checkpoint.py` sale con exit code 0.
- [ ] Suite `scripts/run_pytest_safe.py --level all` verde; `tested_commit_sha == HEAD`.
- [ ] `--validate --json --project-root .` da `errors: 0` y
      `warnings: {}`.
- [ ] `git diff -- .agent/motor_checkpoint.py` muestra solo eliminaciones
      (ninguna linea anadida), y ningun otro archivo fuera de
      `.agent/motor_checkpoint.py` aparece modificado.
