# Work Plan - WOT-2026-019v

## Metadata
- **ID:** WOT-2026-019v
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Cerrar el escape de mock en TestPreHandoff que ejecuta git real cuando work_plan.md esta sucio
- **Creado:** 2026-07-07
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir el aislamiento de `tests/test_agent_controller.py::TestPreHandoff`
(7 tests) y
`tests/test_agent_controller.py::TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`
(1 test) para que los 8 pasen de forma deterministica sin depender del
estado real del working tree del repositorio, incluyendo cuando
`.agent/collaboration/work_plan.md` esta modificado sin commitear (estado
normal a mitad de cualquier cierre de ticket).

## Contexto

Root cause verificada por el Orquestador y reconfirmada por este Manager
leyendo el codigo citado y reproduciendo el fallo: `_handle_pre_handoff`
(`.agent/agent_controller.py:3769`) llama a
`motor_checkpoint.assert_work_plan_committed(project_root=..., motor_root=...)`
(`.agent/motor_checkpoint.py:76-96`), que a su vez llama a
`scope_gate.get_changed_files(project_root=..., motor_root=...)`
(`.agent/motor_checkpoint.py:90-93`) SIN pasar `run_fn`. La firma de
`scope_gate.get_changed_files` (`.agent/scope_gate.py:439-443`) declara
`run_fn=subprocess.run` como valor por defecto del parametro: ese default
se resuelve UNA SOLA VEZ, en el momento en que Python define la funcion
(import de `scope_gate.py`), y queda ligado al objeto funcion original
`subprocess.run` de ese instante. Los tests de `TestPreHandoff` hacen
`monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)`, que
SI reasigna el atributo `run` del modulo `subprocess` compartido (mismo
objeto en `sys.modules["subprocess"]` para `agent_controller`, `scope_gate`
y `motor_checkpoint` -- confirmado empiricamente), pero el default
`run_fn=subprocess.run` ya congelado en `get_changed_files` no vuelve a
mirar el atributo `subprocess.run` en cada llamada: sigue apuntando a la
funcion original. Por eso `git_mock` NUNCA se ejecuta dentro de
`assert_work_plan_committed`, y `get_changed_files` corre `git status
--porcelain -z` REAL sobre el working tree de la worktree-dev.

Reproducido end-to-end: con `.agent/collaboration/work_plan.md` limpio,
`pytest tests/test_agent_controller.py::TestPreHandoff
tests/test_agent_controller.py::TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`
da 14 passed. Ensuciando `work_plan.md` con un cambio no commiteado
(`echo "" >> .agent/collaboration/work_plan.md`) y repitiendo el mismo
comando: 8 failed / 6 passed, con el mensaje literal `[ERROR] Pre-handoff
blocked: .agent/collaboration/work_plan.md is not committed.` en los 8
casos. Restaurar el archivo (`git checkout --
.agent/collaboration/work_plan.md`) vuelve a dar 14 passed. Los 8 tests
fallidos coinciden exactamente con los 6 tests de `TestPreHandoff` que
usan `_setup_basic_mocks` (`test_happy_path_commit_tag_clean`,
`test_happy_path_resets_circuit_breaker`,
`test_idempotent_no_changes_tag_aligned`,
`test_no_changes_tag_missing_create_only`,
`test_no_changes_tag_misaligned_delete_then_recreate`,
`test_hook_failure_propagates_stderr`, `test_dirty_tree_after_ops`) mas
`test_builder_brief_does_not_block_pre_handoff` (que monkeypatchea el
mismo patron inline, sin usar `_setup_basic_mocks`). Los otros 8 tests de
`TestPreHandoff` (`test_pre_handoff_blocks_stale_builder_round`,
`test_pre_handoff_orphan_for_post_success_states` parametrizado x4,
`test_pre_handoff_stays_blocking_when_bus_state_unknown`) bloquean antes
de llegar a `assert_work_plan_committed` (bloqueo por stale Builder round)
y no dependen de `get_changed_files`; siguen pasando siempre y no forman
parte de este ticket.

El codigo de PRODUCCION (`assert_work_plan_committed`,
`_handle_pre_handoff`) es CORRECTO y NO se modifica: el guard 009g
(fail-closed) debe ver el estado real del arbol en runtime de produccion.
El defecto esta exclusivamente en el aislamiento de estos 8 tests.

## Decision Arquitectonica

Dos disenos candidatos, evaluados contra el vocabulario de
`docs/protocol/manager_review_design_vocabulary.md`:

**Opcion A (elegida):** en `_setup_basic_mocks` (y en el bloque de mocks
inline de `test_builder_brief_does_not_block_pre_handoff`), anadir
`monkeypatch.setattr(motor_checkpoint.scope_gate, "get_changed_files",
lambda *, project_root, motor_root, run_fn=None: changed_files)` (mismo
`changed_files`/`{brief_file}` ya usado para el mock existente de
`agent_controller.get_changed_files`, para no introducir una segunda
fuente de verdad divergente dentro del mismo test). Este patron YA es
canonico en el propio repo: `tests/unit/test_motor_checkpoint.py::test_delegates_to_scope_gate_not_new_git_parser`
(lineas 177-202) hace exactamente
`motor_checkpoint.scope_gate.get_changed_files = fake_get_changed_files`
para verificar delegacion, sin tocar `subprocess.run`. Verificado
empiricamente en esta sesion: con este monkeypatch aplicado,
`assert_work_plan_committed` devuelve `(True, {})` incluso con el arbol
real sucio, sin ejecutar git real. Es minimo (una linea de monkeypatch
adicional por punto de entrada), no cambia la forma de los 8 tests
existentes (mismos fixtures, mismos asserts de comportamiento) y cierra
exactamente el punto de fuga citado en la causa raiz.

Contraste con el vocabulario: `get_changed_files(run_fn=...)` es un seam
EXTERNO real segun `manager_review_design_vocabulary.md` (dos
implementadores ya existentes: `subprocess.run` real y el `run_fn` fake
que usan otros tests) -- mockear la funcion completa por-modulo en vez de
inyectar via `run_fn` podria parecer que evita ese seam. Pero en este
caso el seam `run_fn` esta out of reach para el caller real: la cadena de
produccion `_handle_pre_handoff -> assert_work_plan_committed -> scope_gate.get_changed_files`
NO propaga `run_fn` en ningun punto (ni `assert_work_plan_committed` lo
acepta como parametro, ni lo necesita para su contrato de produccion), y
anadir un parametro `run_fn` a `assert_work_plan_committed` solo para uso
de tests seria cambiar la interfaz publica de produccion para un problema
de aislamiento de test, alcance que Non-goals de este ticket cierra
explicitamente. El monkeypatch de modulo
(`motor_checkpoint.scope_gate.get_changed_files`) es coherente con
`test_delegates_to_scope_gate_not_new_git_parser`, que ya trata ese punto
como el seam de facto correcto para tests que no llegan a traves de
`run_fn`.

**Opcion B (descartada):** aislar `project_root`/`cwd` a un `tmp_path` con
`git init` real (patron `init_git_repo` de `tests/test_pre_handoff_guard.py`
y `_init_git_repo` de `tests/unit/test_motor_checkpoint.py`), cruzando la
interfaz publica completa sin mockear nada. Es el patron mas fiel a
"interface is the test surface" y YA es el patron canonico para tests
UNITARIOS de `assert_work_plan_committed` en aislamiento
(`tests/unit/test_motor_checkpoint.py`). Se descarta para ESTE archivo
porque `TestPreHandoff` no ejercita `assert_work_plan_committed` en
aislamiento: ejercita `_handle_pre_handoff` completo, una funcion que ya
depende de mocks deterministas de git para simular escenarios especificos
que un repo real no puede producir de forma simple y legible (hook de
pre-commit que falla con un stderr fijo en
`test_hook_failure_propagates_stderr`; tag desalineado en
`test_no_changes_tag_misaligned_delete_then_recreate`; arbol que queda
sucio DESPUES de las operaciones de commit/tag en
`test_dirty_tree_after_ops`). Migrar los 8 tests a repos git reales
exigiria reescribir ademas los mocks de add/commit/tag/checkpoint que hoy
son deterministas por diseno, multiplicando el blast radius de un ticket
de riesgo Bajo y arriesgando introducir no-determinismo de git real
(mensajes de hook, formato de `git commit` de la version de git del
entorno) en tests que hoy son deliberadamente sinteticos. La Opcion B ya
tiene su lugar correcto y cubierto: los tests unitarios de
`assert_work_plan_committed` en aislamiento
(`tests/unit/test_motor_checkpoint.py`), que YA usan git real y no forman
parte de este ticket porque ya pasan (no estan en la lista de 8 rojos).

## Non-goals

- No se modifica ninguna funcion de produccion: `assert_work_plan_committed`
  (`.agent/motor_checkpoint.py`), `get_changed_files`
  (`.agent/scope_gate.py`) y `_handle_pre_handoff`
  (`.agent/agent_controller.py`) quedan bit-a-bit identicos. El guard 009g
  fail-closed no se relaja.
- No se anade un parametro `run_fn` a `assert_work_plan_committed`: seria
  un cambio de interfaz de produccion para resolver un problema exclusivo
  de aislamiento de test.
- No se migra `TestPreHandoff` al patron de repos git reales en
  `tmp_path` (Opcion B, descartada arriba); ese patron ya existe y ya
  cubre `assert_work_plan_committed` en `tests/unit/test_motor_checkpoint.py`.
- No se tocan los tests de `TestPreHandoff` que ya pasan hoy
  (`test_pre_handoff_blocks_stale_builder_round`,
  `test_pre_handoff_orphan_for_post_success_states` x4,
  `test_pre_handoff_stays_blocking_when_bus_state_unknown`,
  `test_is_motor_code_only_true`, `test_is_motor_code_only_false_with_env`)
  ni ningun otro test fuera de `tests/test_agent_controller.py`.
- No se cambia el comportamiento observable de ninguno de los 8 tests
  corregidos: mismos asserts de exit code y de texto de salida que hoy;
  solo se corrige el aislamiento del mock de git subyacente.

## Files Likely Touched

- `tests/test_agent_controller.py`

## Plan de Implementacion

### Tipos de Tareas

| Marca | Tipo | Ejecutor |
|-------|------|----------|
| [AGENTE] | TAREA AGENTE | Builder |

### Fase 1: Confirmar el punto de fuga exacto [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** `tests/test_agent_controller.py` (lectura), `.agent/motor_checkpoint.py` (lectura), `.agent/scope_gate.py` (lectura)
- **Accion:** Verificar (sin modificar)
- **Descripcion:** Reproducir el estado rojo antes de tocar nada: desde la
  raiz del repo, ejecutar `echo "" >> .agent/collaboration/work_plan.md`
  para ensuciar el archivo sin commitear, correr
  `.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py::TestPreHandoff tests/test_agent_controller.py::TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff -q`
  y confirmar 8 failed / 6 passed con el mensaje `[ERROR] Pre-handoff
  blocked: .agent/collaboration/work_plan.md is not committed.` en los 8
  casos. Inmediatamente despues, ejecutar
  `git checkout -- .agent/collaboration/work_plan.md` para restaurar el
  arbol antes de continuar a la Fase 2. Confirmar por lectura de codigo
  (no solo por el mensaje) que `motor_checkpoint.assert_work_plan_committed`
  (`.agent/motor_checkpoint.py` lineas 90-93) llama a
  `scope_gate.get_changed_files` sin pasar `run_fn`.
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** El comando de pytest del paso anterior,
  ejecutado con el arbol sucio, produce exactamente 8 failed y 6 passed; el
  comando `git status --porcelain .agent/collaboration/work_plan.md`
  ejecutado inmediatamente despues del `git checkout` de restauracion
  devuelve salida vacia (arbol limpio) antes de iniciar la Fase 2.
- **Si falla:** Si el numero de failed/passed no coincide (por ejemplo por
  drift del repo desde que este plan se escribio), escalar al Manager
  citando el output literal de pytest antes de continuar.

### Fase 2: Cerrar el escape de mock en `_setup_basic_mocks` [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** `tests/test_agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** En el metodo `TestPreHandoff._setup_basic_mocks`
  (linea ~1140-1173), anadir un monkeypatch adicional inmediatamente
  despues del `monkeypatch.setattr(agent_controller, "get_changed_files",
  lambda: changed_files)` existente:
  `monkeypatch.setattr(motor_checkpoint.scope_gate, "get_changed_files",
  lambda *, project_root, motor_root, run_fn=None: changed_files)`. Debe
  usar el MISMO `changed_files` que ya recibe `_setup_basic_mocks` como
  parametro (no un valor nuevo ni una constante distinta), para que ambos
  mocks describan el mismo estado de git dentro del mismo test. Anadir el
  import `import motor_checkpoint` al inicio del archivo de test si no
  esta ya presente (verificar primero con
  `grep -n "^import motor_checkpoint" tests/test_agent_controller.py`; si
  ya existe, no duplicar el import).
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** `git diff -- tests/test_agent_controller.py`
  muestra unicamente lineas anadidas dentro de `_setup_basic_mocks` (mas,
  si hacia falta, una linea de import al inicio del archivo); ninguna
  linea existente de `_setup_basic_mocks` se elimina ni se reordena mas
  alla de insertar la linea nueva.
- **Si falla:** Revertir el archivo a HEAD con
  `git checkout -- tests/test_agent_controller.py` y escalar al Manager
  citando el error exacto.

### Fase 3: Cerrar el escape de mock en `test_builder_brief_does_not_block_pre_handoff` [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** `tests/test_agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** En
  `TestBuilderBriefExclusion.test_builder_brief_does_not_block_pre_handoff`
  (linea ~4212-4266), anadir el mismo monkeypatch inmediatamente despues
  del `monkeypatch.setattr(agent_controller, "get_changed_files", lambda:
  {brief_file})` existente:
  `monkeypatch.setattr(motor_checkpoint.scope_gate, "get_changed_files",
  lambda *, project_root, motor_root, run_fn=None: {brief_file})`, usando
  el mismo `brief_file` ya definido en el test (no un valor nuevo).
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** `git diff -- tests/test_agent_controller.py`
  muestra la linea anadida dentro del cuerpo de
  `test_builder_brief_does_not_block_pre_handoff`, sin tocar ninguna otra
  linea de ese test ni de `TestBuilderBriefExclusion`.
- **Si falla:** Revertir el archivo a HEAD con
  `git checkout -- tests/test_agent_controller.py` y escalar al Manager
  citando el error exacto.

### Fase 4: Gates de calidad y demostracion FAIL-sin-fix / PASS-con-fix [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** N/A (comandos de verificacion)
- **Accion:** Ejecutar (no modifica codigo de produccion)
- **Descripcion:** Ejecutar en este orden desde la raiz del repo con el
  interprete de la worktree-dev:
  1. Demostrar FAIL-sin-fix (estado documentado en Fase 1, ya verificado):
     no se repite aqui; se referencia como evidencia ya capturada en la
     Fase 1.
  2. Demostrar PASS-con-fix bajo la condicion adversa exacta del bug: con
     los cambios de Fase 2 y Fase 3 aplicados, ensuciar de nuevo
     `.agent/collaboration/work_plan.md`
     (`echo "" >> .agent/collaboration/work_plan.md`) y ejecutar
     `.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py::TestPreHandoff tests/test_agent_controller.py::TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff -q`.
     Debe dar 14 passed / 0 failed (los 8 corregidos mas los 6 que ya
     pasaban). Restaurar inmediatamente el arbol con
     `git checkout -- .agent/collaboration/work_plan.md`.
  3. Confirmar que con el arbol limpio (tras el `git checkout` del paso
     anterior) el mismo comando de pytest sigue dando 14 passed / 0
     failed (no-regresion).
  4. `.venv/Scripts/python.exe -m ruff check tests/test_agent_controller.py`
  5. `.venv/Scripts/python.exe -m ruff format --check tests/test_agent_controller.py`
  6. `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all`
     (runner canonico del repo; suite completa, no un subconjunto).
  7. `.venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .`
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** El paso 2 (arbol sucio, con fix) da
  exactamente 14 passed / 0 failed; el paso 3 (arbol limpio, con fix) da
  igualmente 14 passed / 0 failed; ruff check y ruff format --check
  devuelven exit code 0 sobre `tests/test_agent_controller.py`; la suite
  completa de `scripts/run_pytest_safe.py --level all` sale verde (0
  failed) con `tested_commit_sha` igual al HEAD del commit que contiene
  los cambios de Fase 2 y Fase 3; `--validate --json` reporta `errors: 0`.
- **Si falla:** Si el paso 2 sigue dando failed, NO se ha cerrado el
  escape de mock; revisar que el monkeypatch de Fase 2/3 apunta
  exactamente a `motor_checkpoint.scope_gate.get_changed_files` (no a
  `agent_controller.get_changed_files`, que es un wrapper distinto no
  invocado por `assert_work_plan_committed`). Si el arbol queda sucio
  despues de cualquier paso de este plan por un error del propio Builder,
  restaurar con `git checkout -- .agent/collaboration/work_plan.md` antes
  de escalar. No proceder a handoff sin los 7 comandos de gates en verde.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| A: monkeypatch de `motor_checkpoint.scope_gate.get_changed_files` por test | Minimo, reutiliza patron ya canonico en `tests/unit/test_motor_checkpoint.py`, no cambia forma de los 8 tests, no toca produccion | Mockea una funcion de modulo en vez de cruzar el seam `run_fn` end-to-end | Elegida |
| B: migrar `TestPreHandoff` a repos git reales en `tmp_path` (patron `init_git_repo`) | Mas fiel a "interface is the test surface"; cero mocks de git | Exige reescribir los mocks deterministas de commit/tag/hook-failure/dirty-tree de los 8 tests; blast radius mucho mayor para un ticket de riesgo Bajo; ese patron ya existe y cubre el caso en `tests/unit/test_motor_checkpoint.py` | Descartada |
| C: anadir parametro `run_fn` a `assert_work_plan_committed` | Cruza el seam existente de forma explicita | Cambia la interfaz publica de una funcion de produccion solo para resolver un problema de aislamiento de test; viola el Non-goal de no tocar produccion | Descartada |

## Guia de Riesgos

| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| [Bajo] | Rutinaria | Intentar 3 veces antes de escalar |

## Criterios de Aceptacion Global

- [ ] Con `.agent/collaboration/work_plan.md` modificado sin commitear,
      los 8 tests objetivo (`TestPreHandoff::test_happy_path_commit_tag_clean`,
      `test_happy_path_resets_circuit_breaker`,
      `test_idempotent_no_changes_tag_aligned`,
      `test_no_changes_tag_missing_create_only`,
      `test_no_changes_tag_misaligned_delete_then_recreate`,
      `test_hook_failure_propagates_stderr`, `test_dirty_tree_after_ops`,
      `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`)
      PASAN.
- [ ] Con el arbol limpio (work_plan.md commiteado), los mismos 8 tests
      siguen PASANDO (no-regresion).
- [ ] `motor_checkpoint.assert_work_plan_committed`,
      `scope_gate.get_changed_files` y `agent_controller._handle_pre_handoff`
      quedan bit-a-bit identicos a HEAD (0 lineas modificadas en
      `.agent/motor_checkpoint.py`, `.agent/scope_gate.py` y
      `.agent/agent_controller.py`).
- [ ] `ruff check tests/test_agent_controller.py` y
      `ruff format --check tests/test_agent_controller.py` dan exit code 0.
- [ ] `.venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .`
      reporta `errors: 0` y `warnings: {}`.
