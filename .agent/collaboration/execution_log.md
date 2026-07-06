# Execution Log - WOT-2026-019q

Ticket: Cierre canonico de un ticket cuyo commit no es HEAD (batch-close no
contiguo), sin aceptar entregas vacias.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-06). Fase 0 (Orquestador)
  verifico en codigo, con un fixture git real y el modulo motor_checkpoint
  real (no mocks), que Step 3 de resolve_motor_checkpoint_files es el UNICO
  bloqueador del cierre de un ticket enterrado, que Step 2
  (ancestor-of-HEAD) ya garantiza que el diff este en la historia de HEAD, y
  que contiguous_ticket_commits/files_from_commits ya recuperan
  correctamente el diff del ticket enterrado desde su propio commit. El
  Manager re-ejecuto el script de repro de forma independiente antes de
  aprobar el plan (mismo resultado).
- work_plan.md, STRATEGY_WOT-2026-019q.md y AUDIT_WOT-2026-019q.md creados.
  Decision Arquitectonica: Opcion (a) (relajar Step 3, verificar
  contiguidad+entrega no vacia desde el commit real del ticket), justificada
  porque desbloquea los 3 tickets reales (CTL-2026-009k/009g/009i) que
  motivan la ficha, mientras que la Opcion (b) (prohibir batch-close) no lo
  hace.
- Artefactos de WOT-2026-019m (COMPLETED) archivados: execution_log.md ->
  execution_log_WOT-2026-019m.md; AUDIT_WOT-2026-019m.md y
  STRATEGY_WOT-2026-019m.md -> .agent/collaboration/_archive/plan_audit/.

## Builder: implementacion (2026-07-06)

### Fase 1: tests nuevos (TDD, escritos ANTES del fix)

Se anadio la clase `TestResolveMotorCheckpointFilesNonHead` a
`tests/unit/test_motor_checkpoint.py` con los 5 tests del plan (fixtures git
reales via subprocess, mismo patron que `_init_git_repo`/`_add_committed_work_plan`
ya presentes en el archivo; sin mocks de git).

Comando pre-fix:
```
.venv\Scripts\python.exe -m pytest tests/unit/test_motor_checkpoint.py -k TestResolveMotorCheckpointFilesNonHead -v
```
Resultado pre-fix (exit code 1): `test_buried_ticket_with_real_m3_closes_and_recovers_own_files`
FAILED (`... is stale; expected HEAD ...`), `test_topmost_ticket_head_unchanged_behavior` PASSED,
`test_empty_closeout_commit_is_rejected` FAILED (`assert True is False`),
`test_non_ancestor_still_rejected` PASSED, `test_subject_without_ticket_id_still_rejected` PASSED.
`2 failed, 3 passed, 11 deselected` — exactamente el estado esperado por el
criterio de aceptacion de Fase 1 (1.1.1 y 1.1.3 en rojo, resto en verde).

Nota de fixture: el primer intento de `test_empty_closeout_commit_is_rejected`
(commit real de A seguido directamente por un commit vacio de cierre, sin
commit intermedio) NO reproducia el anti-patron: `contiguous_ticket_commits`
camina hacia atras desde el commit vacio y, como el subject de A tambien
contiene el ticket_id, lo incluye en la contigueidad, recuperando
`file_a.py` (no vacio) — resultado correcto para ESE fixture, pero no el
anti-patron que el plan pide reproducir. Se ajusto el fixture para incluir un
commit de ticket B intermedio (subject SIN el ticket_id de A) entre el commit
real de A y el commit vacio, replicando exactamente la secuencia del repro de
Fase 0 (`base -> A -> B -> A:closeout`): asi la contigueidad se corta en B
antes de alcanzar el commit real de A, y el commit vacio queda aislado
(archivos == `set()`).

### Fase 2: fix aplicado

`.agent/motor_checkpoint.py::resolve_motor_checkpoint_files`:
- Step 3 ya NO retorna temprano cuando `sha != head_sha`; se preserva el
  calculo de `head_sha` (usado solo como nota diagnostica opcional en el
  mensaje de error de entrega vacia, nunca como bloqueo).
- Step 2 y Step 4 sin cambios de logica.
- Nuevo chequeo simetrico DESPUES de `files_from_commits`: si `files` es
  `set()`, retorna `(False, set(), f"Checkpoint {tag}@{sha[:8]} delivers no
  files; refusing empty closeout...")` en vez de `(True, files, "")`.
- `print_motor_checkpoint_guidance`: nueva rama `elif "refusing empty
  closeout" in cp_error` con guidance ASCII accionable.

Comando post-fix (mismos 5 tests):
```
.venv\Scripts\python.exe -m pytest tests/unit/test_motor_checkpoint.py -k TestResolveMotorCheckpointFilesNonHead -v
```
Resultado: `5 passed, 11 deselected` — exit code 0.

Verificacion Fase 2.2 (guidance):
```
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.agent'); import motor_checkpoint; motor_checkpoint.print_motor_checkpoint_guidance('T-1', 'Checkpoint checkpoint/review-T-1 delivers no files; refusing empty closeout')"
```
Salida: imprime `[ERROR] No valid motor checkpoint for T-1: ...` seguido de
`"El checkpoint M3 apunta a un commit sin diff real. Re-ejecuta --pre-handoff
sobre el commit que SI contiene el trabajo del ticket; no uses un commit de
cierre vacio."` — exit code 0.

### Regresion detectada y resuelta: 2 tests de contrato viejo en test_mark_ready_motor_scope.py

Al correr `run_pytest_safe.py` con el fix aplicado, se detectaron 11 fallos.
Se investigo cada uno por separado (stash selectivo de `.agent/motor_checkpoint.py`
para comparar con/sin el fix, dejando los tests nuevos intactos):

- 8 fallos en `tests/test_agent_controller.py` (`TestPreHandoff::*`,
  `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`)
  y 1 fallo en `tests/test_setup_dev_worktree_script.py::test_remove_cleans_worktree_and_reattaches_main`:
  confirmados HEREDADOS (fallan identico con motor_checkpoint.py revertido al
  original). Los 8 primeros dependen del estado real del working tree de la
  worktree-dev (work_plan.md real modificado sin commit durante el ticket);
  el ultimo no tiene relacion alguna con motor_checkpoint.py. No relacionados
  con este ticket.
- 2 fallos en `tests/test_mark_ready_motor_scope.py`
  (`TestMotorNoEvidence::test_stale_ancestor_checkpoint_blocks`,
  `TestResolveMotorCheckpointFiles::test_ancestor_but_not_head_returns_invalid`):
  confirmados como PASAN sin el fix y FALLAN con el fix — es decir, estos 2
  tests codificaban explicitamente el contrato VIEJO ("handoff requires tag
  == HEAD") que WOT-2026-019q deroga a proposito (Opcion (a), elegida en la
  Decision Arquitectonica). Por indicacion expresa del Manager (CEM:
  scope-expansion justificada porque el cambio de contrato invalida sus
  aserciones), se actualizaron ambos tests para reflejar el contrato NUEVO
  en vez de dejarlos en rojo:
  - `test_stale_ancestor_checkpoint_blocks` -> renombrado
    `test_ancestor_checkpoint_with_real_delivery_passes`; assert cambiado de
    `result == 1` a `result == 0` (el checkpoint ancestro con entrega real
    ahora pasa mark-ready).
  - `test_ancestor_but_not_head_returns_invalid` -> renombrado
    `test_ancestor_not_head_with_real_delivery_is_valid`; assert cambiado de
    `not valid` / `"stale" in error` a `valid` / `files == {"src/base.py"}`
    (verificado ejecutando el escenario real antes de fijar el assert: la
    caminata de contiguidad desde el commit del propio tag no alcanza
    `src/newer.py`, aunque ese commit posterior tambien contenga el
    ticket_id en su subject, porque la caminata nunca llega a verlo — parte
    del commit del tag hacia atras, no desde HEAD).
  - Ningun otro test de `tests/test_mark_ready_motor_scope.py` fue tocado
    (los 12 restantes siguen exactamente igual).

Archivo `tests/test_mark_ready_motor_scope.py` anadido a los archivos
tocados de este ticket (fuera de las FLT originales del plan), con
justificacion CEM: el cambio de contrato de Step 3 invalida directamente las
aserciones de esos 2 tests especificos; dejarlos en rojo romperia CI sin
razon (no es un fallo real del fix, es un test que verifica el
comportamiento derogado a proposito por este mismo ticket).

Correccion adicional de encoding: se detecto un caracter no-ASCII (em-dash,
introducido por error en un docstring nuevo) en
`tests/test_mark_ready_motor_scope.py` y se corrigio a texto ASCII plano
antes de la verificacion final (el resto de bytes no-ASCII detectados en
`.agent/motor_checkpoint.py` y `tests/unit/test_motor_checkpoint.py` se
confirmaron preexistentes en HEAD, ajenos al diff de este ticket — verificado
con `git diff -- <archivos> | python -c "...decode('ascii')..."`, que
confirma el diff completo es ASCII puro).

### Fase 3.1: mutation-verify (re-corrido completo tras el ajuste de scope)

Paso 1 — stash SOLO de `.agent/motor_checkpoint.py` (`git stash push -m
"019q-mutation-verify-v2" -- .agent/motor_checkpoint.py`), dejando los 3
archivos de test (incl. los 2 actualizados de test_mark_ready_motor_scope.py)
intactos en el working tree.

Paso 2 — comando:
```
.venv\Scripts\python.exe -m pytest tests/test_mark_ready_motor_scope.py tests/unit/test_motor_checkpoint.py -v
```
Resultado SIN el fix (exit code 1): `4 failed, 26 passed`. Los 4 fallos son
exactamente los que dependen del fix:
`TestMotorNoEvidence::test_ancestor_checkpoint_with_real_delivery_passes`,
`TestResolveMotorCheckpointFiles::test_ancestor_not_head_with_real_delivery_is_valid`,
`TestResolveMotorCheckpointFilesNonHead::test_buried_ticket_with_real_m3_closes_and_recovers_own_files`,
`TestResolveMotorCheckpointFilesNonHead::test_empty_closeout_commit_is_rejected`.

Paso 3 — `git stash pop` (fix restaurado).

Paso 4 — mismo comando, resultado CON el fix (exit code 0): `30 passed`.

Los 4 exit codes del mutation-verify (en orden): **1 (rojo, sin fix) -> 0
(verde, con fix restaurado)**, confirmados en dos corridas separadas segun el
protocolo pedido (rojo/verde), cada una con su propio exit code de shell
verificado explicitamente.

### Fase 3.2: gates de calidad completos (corrida final, post-ajuste)

```
.venv\Scripts\python.exe -m ruff check .
```
Salida: `All checks passed!` — exit code 0.

```
.venv\Scripts\python.exe scripts\run_pytest_safe.py
```
Resultado: `9 failed, 3483 passed, 47 skipped, 5 deselected` — exit code 1.
Los 9 fallos son EXACTAMENTE los heredados descritos arriba (8 en
test_agent_controller.py/test_setup_dev_worktree_script.py por estado del
working tree real / no relacion con motor_checkpoint, 1 en
test_remove_cleans_worktree_and_reattaches_main). Verificado por separado
que estos 9 fallan identico con `.agent/motor_checkpoint.py` revertido al
original (independiente de este ticket). CERO fallos nuevos introducidos por
WOT-2026-019q en la corrida completa: los 2 que si dependian del cambio de
contrato (test_mark_ready_motor_scope.py) ya estan actualizados y en verde,
contados dentro de los 3483 passed.

### Resumen de archivos tocados (diff final)

```
.agent/motor_checkpoint.py           |  57 ++++++++--
tests/test_mark_ready_motor_scope.py |  27 +++--
tests/unit/test_motor_checkpoint.py  | 198 +++++++++++++++++++++++++++++++++++
3 files changed, 263 insertions(+), 19 deletions(-)
```

### Self-audit (skill builder-self-audit v2.0.0)

| Paso | Verificacion | Comando | Resultado |
|------|-------------|---------|-----------|
| 1 | Sintaxis Python (3 archivos) | `python -m py_compile .agent/motor_checkpoint.py tests/unit/test_motor_checkpoint.py tests/test_mark_ready_motor_scope.py` | Sin output, exit 0 -> OK |
| 2 | Ya-existia | N/A | No aplica: fix implementado desde cero, no preexistia |
| 3 | Completitud multi-archivo | Verificado cada uno de los 3 archivos por separado (diffstat + pytest por archivo) | OK |
| 4 | Anti-regresion (manejo de errores) | Revision manual de `resolve_motor_checkpoint_files`: Steps 1/2/4 y el manejo de `TimeoutExpired`/`FileNotFoundError` preservados sin cambios; ningun caso de error previo fue eliminado | OK |
| 5 | Frescura documental | Buscado "is stale/expected HEAD/resolve_motor_checkpoint_files" en PROJECT.md y QUICKSTART.md: sin matches (el contrato interno de Step 3 no esta documentado alli, no hay drift que corregir). STATE.md/TURN.md/execution_log.md verificados alineados (ticket WOT-2026-019q, BUILDER, APPROVED) | OK, sin drift |
| 6a | Ruff (excluye .agent, forma del skill) | `ruff check . --exclude .agent` | `All checks passed!`, exit 0 |
| 6b | Ruff (completo, forma del work_plan Fase 3.2) | `ruff check .` | `All checks passed!`, exit 0 |
| 6c | Suite completa | `python scripts/run_pytest_safe.py` | `9 failed, 3483 passed, 47 skipped, 5 deselected`. Los 9 fallos son heredados (confirmados identicos con `.agent/motor_checkpoint.py` revertido al original, ver seccion anterior); CERO fallos nuevos de este ticket. El work_plan (Fase 3.2) exige distinguir explicitamente fallos heredados de nuevos citando archivo/test exacto en vez de bloquear el reporte por ellos -- hecho arriba con evidencia de stash comparativo |

**Nota sobre exit code de la suite:** `run_pytest_safe.py` termina en exit
code != 0 debido UNICAMENTE a los 9 fallos heredados y no relacionados
(8 dependen del estado real del working tree de la worktree-dev -- work_plan.md
modificado sin commit durante la ejecucion del ticket -- y 1 es de
test_setup_dev_worktree_script.py, sin relacion alguna con motor_checkpoint.py).
Ninguno de los 9 involucra `.agent/motor_checkpoint.py`,
`tests/unit/test_motor_checkpoint.py` ni `tests/test_mark_ready_motor_scope.py`.
El Manager puede re-verificar re-ejecutando el subset especifico:
`pytest tests/test_mark_ready_motor_scope.py tests/unit/test_motor_checkpoint.py -v`
(30 passed, exit 0).

**Estado:** READY_FOR_REVIEW. Self-audit completo (Pasos 1-6 del skill
builder-self-audit ejecutados con evidencia real arriba). NO se ha
commiteado ni ejecutado --pre-handoff/--mark-ready; los cambios quedan en el
working tree para revision del Manager.


Scope override: over-captura de arbol limpio (patron conocido): los archivos marcados (agent_controller.py, scope_gate.py, QUICKSTART.md, AUDIT/PLAN/STRATEGY de 019c/019i/019j/019m, scripts/tests varios) NO estan en el commit 9027e10 (git show --name-only 9027e10 -> 0 hits de esos archivos; git diff --stat HEAD -> 0; origin/main..HEAD == 1 commit con solo los 13 archivos de 019q). Arbol limpio verificado. El diff real esta 100% dentro de FLT + hotfix aprobado.. Affected files: <REPO_ROOT>/.agent/agent_controller.py, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019m.md, <REPO_ROOT>/.agent/scope_gate.py, <REPO_ROOT>/QUICKSTART.md, <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/scripts/run_gates_dispatch.py, <REPO_ROOT>/scripts/setup_dev_worktree.ps1, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/unit/test_run_gates_dispatch.py, <REPO_ROOT>/tests/unit/test_scope_gate_deliverable_aware.py, <REPO_ROOT>/tests/unit/test_scope_gate_topology.py

Manager approved canonical closeout for WOT-2026-019q