# Execution Log: WOT-2026-021g

**Estado:** COMPLETED

## Bitacora

### 2026-07-09 - Manager - Plan aprobado
- work_plan.md creado y aprobado (Estado: APPROVED).
- STRATEGY_WOT-2026-021g.md creado (resumen tecnico).
- AUDIT_WOT-2026-021g.md creado con seccion TP Check completa.
- Handoff canonico al Builder pendiente de confirmacion del Orquestador antes
  de --reset-turn / --bootstrap-ticket.

Pendiente de registrar por el Builder (segun contrato del work_plan.md):
- Fase 5: mutation-verify con worktrees reales (2 pares, comando + exit code
  literal cada uno).
- Fase 6: cableado PRE en orchestrator_destination_bootstrap.md,
  orchestrator_launch_builder.md y orchestrator_session_bootstrap.md.
- Fase 7: cableado POST en manager_review.md (fuera de su Paso 0 CF-frozen).
- Fase 8: ruff check, ruff format --check, encoding guard,
  test_no_legacy_topology_terms.py, suite --level all, --validate --json
  --force.

### 2026-07-09 - Builder - Fase 1: fix de guard() en prefix_resolver.py
- Anadidos 2 helpers de modulo nuevos: `_git_executable()` (resuelve el
  binario git via `shutil.which`, evita S607 sin noqa) y `_git_common_dir(path)`
  (invoca `git -C <path> rev-parse --path-format=absolute --git-common-dir`
  con `check=False`, retorna `Path` resuelto o `None` si falla).
- Dentro de `guard()` (antes l.204-237), unicamente se anadio la rama
  `if prefix == WOT_PREFIX:` (tras el chequeo `resolved is None`): compara
  `_git_common_dir(cwd)` vs `_git_common_dir(motor_root)`; si alguno es
  `None` -> mensaje "Cannot determine git-common-dir..." + exit 1
  (fail-closed, nunca crash ni exit 0); si difieren -> exit 1 (mismatch);
  si coinciden -> exit 0. El resto de `guard()` (rama no-WOT) es identica
  al original.
- `ast.parse` del archivo: OK, sin excepcion.
- `git diff --stat scripts/prefix_resolver.py`: 88 inserciones, 1 eliminacion
  (solo imports nuevos `shutil`/`subprocess`, los 2 helpers nuevos, y la
  rama `WOT_PREFIX` dentro de `guard()`; ninguna otra funcion/rama cambio).
- Caso borde verificado: `guard()` con `cwd` que no es repo git en rama WOT
  -> exit 1 determinista (ver test nuevo de Fase 2).

### 2026-07-09 - Builder - Fase 2: tests de no-regresion en test_prefix_resolver.py
- Anadido helper NUEVO y SEPARADO `_git_init_main(repo_path)` (git init -b
  main + config + commit inicial) y `_make_git_tree(tmp_path)` (crea motor
  git real, lo detacha de `main` -- `git checkout --detach main` -- ANTES
  de anadir el worktree `_dev` via `git worktree add <path> main`, porque
  git rechaza la misma rama checked-out en 2 worktrees a la vez; replica
  EXACTAMENTE la topologia real verificada en vivo: principal detached,
  solo `_dev` lleva `main`). `_make_tree` (l.56-73 original) queda SIN diff
  (confirmado con `git diff` sobre esa funcion: 0 cambios).
- `test_guard_wot_in_motor_passes` GANO `git init` real en su fixture local
  (via `_git_init_main(motor)` tras `_make_tree`), tal como exige el
  contrato bajo el degradado fail-closed; su assert sigue `== 0`.
- 2 tests nuevos: `test_guard_wot_from_dev_worktree_passes` (guard() desde
  `_dev` sintetico -> 0) y `test_guard_wot_cwd_not_git_repo_returns_one_no_crash`
  (cwd sin git init, motor_root con git init -> 1 determinista, sin
  excepcion).
- HALLAZGO EN VIVO no anticipado por el work_plan: `test_guard_wot_in_destination_blocks`
  (usa `_make_tree` plano, SIN `git init` en ninguno de los 2 lados) fallo
  en la primera corrida (`0 == 1` en vez de `1`). Causa raiz: la sandbox de
  pytest vive DENTRO del propio worktree `orquestador_de_agentes_dev` (un
  repo git real); sin aislar el descubrimiento de git, `git -C <tmp_path_subdir>
  rev-parse --git-common-dir` ASCIENDE por los directorios padre y encuentra
  el `.git` REAL del repo contenedor para AMBOS lados (`exf` y `motor`
  sinteticos), dando un match falso (0) en vez del mismatch esperado bajo
  el degradado fail-closed. Verificado en vivo: `git -C tests/sandbox
  rev-parse --path-format=absolute --git-common-dir` devuelve
  `C:/Users/fdl/Proyectos_Python/orquestador_de_agentes/.git` (el repo
  real). Fix: `monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))`
  SOLO en ese test (fixture-only, produccion sin tocar), verificado en vivo
  que corta la busqueda ascendente (`fatal: not a git repository` con la
  variable puesta). El assert del test NO cambio (sigue `== 1`), solo se
  aislo su fixture del contenedor real.
- `python -m pytest tests/unit/test_prefix_resolver.py -v`: **38 passed**
  (incluye los 2 tests nuevos).

### 2026-07-09 - Builder - Fase 3: creacion de scripts/check_worktree_topology.py
- Script nuevo creado con CLI `--ticket` (required), `--motor-root`,
  `--project-root`, `--allow-diagnostic` (+ env `WORKTREE_GUARD_BYPASS=1`).
- `_check_wot_topology(cwd, motor_root, project_root)`: Verificacion A
  (git-common-dir de cwd == motor_root; si no coinciden o no son repo git
  -> exit 2 "no se puede determinar topologia"; si coinciden, exige rama
  `main` Y que el toplevel de `cwd` coincida con la entrada de
  `git worktree list --porcelain` cuyo basename termina en `_dev` -- si no
  hay ninguna entrada `_dev` -> exit 1 "Crea la worktree _dev..."; si hay
  pero no coincide -> exit 1 con el mensaje literal del contrato citando
  `setup_dev_worktree.ps1`) seguida de Verificacion B SOLO si A dio exit 0
  (deriva el workspace esperado escaneando `parent(motor_root)` por
  `destination_id == "orquestador_de_agentes_workspace"`, NUNCA por
  `ticket_prefix`; si `project_root` no coincide -> exit 1 con el mensaje
  literal "Ticket WOT necesita el workspace orquestador_de_agentes_workspace,
  no <project_root>.").
- `_check_destination_topology(prefix, cwd, motor_root)`: reusa
  `prefix_resolver.resolve_prefix`; sin exigencia de `_dev` (motor detached
  esperado para destinos).
- `check_topology()` (dispatcher): extrae prefijo con
  `prefix_resolver.extract_prefix`, cruza `delivery_authority` del
  `work_plan.md` activo (si existe) contra el prefijo ANTES de la logica de
  topologia via `scope_gate.read_delivery_authority`, importado con
  `sys.path.insert(0, str(motor_root / ".agent"))` + `import scope_gate`
  (patron real de `scripts/pip_audit_policy.py` l.10-17, NO dotted import).
- `--help` ejecutado manualmente: documenta `--ticket`, `--motor-root`,
  `--project-root`, `--allow-diagnostic`.
- 5 casos base ejecutados manualmente sobre los worktrees/workspace REALES
  de esta maquina:
  1. WOT en `_dev` + workspace correcto:
     `python scripts/check_worktree_topology.py --ticket WOT-2026-021g
     --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes"
     --project-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace"`
     (cwd=`_dev`) -> `[OK] topologia correcta...` exit=0. CORRECTO.
  2. WOT en el principal detached (mismo comando, cwd=principal) ->
     `[ERROR] Ticket WOT escribe en el MOTOR: usa la worktree _dev (rama
     main)...` exit=1. CORRECTO.
  3. WOT en `_dev` + workspace INCORRECTO (--project-root apuntando al
     propio principal) -> `[ERROR] Ticket WOT necesita el workspace
     orquestador_de_agentes_workspace, no C:\Users\fdl\Proyectos_Python\orquestador_de_agentes.`
     exit=1. CORRECTO (Verificacion B aislada).
  4/5. Casos manuales con prefijos CTL/XYZ sobre el ESTADO REAL de esta
     maquina dieron exit=2 por "incoherencia de contrato" (el `work_plan.md`
     REAL activo es WOT-2026-021g con `delivery_authority: repo_motor`, y
     el chequeo de coherencia se evalua ANTES de la topologia, por diseno
     -- no es un bug, es el comportamiento esperado del cruce de contrato
     cuando se prueba un prefijo distinto al del ticket activo real). Los
     casos (d)/(e)/(f) puros (sin ese cruce) se cubren limpiamente en Fase
     4 con fixtures sinteticas SIN `work_plan.md`, donde SI dan los exit
     codes 0/1/2 esperados (ver resultados de pytest abajo).

### 2026-07-09 - Builder - Fase 4: tests de check_worktree_topology.py
- Archivo nuevo `tests/unit/test_check_worktree_topology.py`, 11 tests
  (9 casos a-i + 1 duplicado de (h) via env var + 1 de `--help`), todos
  con fixtures `tmp_path` + `git init -b main` real (helper local
  `_git_init_main`/`_make_git_tree`, replicando el patron de Fase 2;
  fixture `autouse` `_isolate_git_discovery` fija `GIT_CEILING_DIRECTORIES`
  en TODOS los tests del modulo para evitar el mismo problema de ascenso
  de git hallado en Fase 2).
- `python -m pytest tests/unit/test_check_worktree_topology.py -v`:
  **11 passed** (test_case_a..i + test_case_h_worktree_guard_bypass_env +
  test_cli_help_documents_all_flags).

### 2026-07-09 - Builder - Fase 5: mutation-verify con worktrees reales
Secuencia literal ejecutada (par 1: `git stash push -- scripts/prefix_resolver.py`
para revertir temporalmente el fix, comando, `git stash pop` para restaurar;
par 2: `check_worktree_topology.py` ejecutado con cwd real en cada worktree):

```
mutation-verify: prefix_resolver.guard() -- fix del bug real (caso principal)
  sin_fix (revertido via `git stash push -- scripts/prefix_resolver.py`):
    command: python scripts/prefix_resolver.py --guard WOT-2026-021g --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes"
    (ejecutado con cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev")
    exit_code: 1   # confirmado en vivo: "[ERROR] Prefix mismatch: 'WOT-2026-021g'
                   # resolves to ...orquestador_de_agentes, but cwd is
                   # ...orquestador_de_agentes_dev"
  con_fix (restaurado via `git stash pop`):
    command: python scripts/prefix_resolver.py --guard WOT-2026-021g --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes"
    (mismo cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev")
    exit_code: 0   # confirmado en vivo: sin output de error, exit limpio

mutation-verify: check_worktree_topology.py -- caso del bug (motor detached + WOT)
  (par ejecutable REAL: mismo comando desde el PRINCIPAL detached -> exit 1, desde
   _dev -> exit 0; ambos ejecutados en vivo. El par de barrera-vs-desactivacion del
   guard esta ademas en el bloque "Review 2 fresh-context" mas abajo, donde se muto
   el codigo de produccion y los tests fallaron.)
  desde_principal_detached (el caso del bug que causo la perdida de 019f):
    command: python scripts/check_worktree_topology.py --ticket WOT-2026-021g --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes" --project-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace"
    (ejecutado con cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes" -- el PRINCIPAL detached)
    exit_code: 1   # confirmado en vivo: "[ERROR] Ticket WOT escribe en el
                   # MOTOR: usa la worktree _dev (rama main), no el checkout
                   # principal (detached=consumo). Ver
                   # scripts/setup_dev_worktree.ps1."
  con_dev (mismo comando, cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev"):
    exit_code: 0   # confirmado en vivo: "[OK] topologia correcta: worktree
                   # del motor (_dev/main) y workspace correctos"
```

- `git status --short` en ambos worktrees tras el mutation-verify:
  - Principal (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes`):
    salida VACIA (arbol limpio, ningun revert temporal sobrevivio -- el
    `git stash push`/`pop` operaron sobre el arbol de `_dev`, nunca sobre
    el principal).
  - `_dev` (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev`):
    `M .agent/collaboration/TURN.md`, `M .agent/collaboration/execution_log.md`,
    `M .agent/collaboration/work_plan.md`, `M scripts/prefix_resolver.py`,
    `M tests/unit/test_prefix_resolver.py`, `?? scripts/check_worktree_topology.py`,
    `?? tests/unit/test_check_worktree_topology.py` -- exactamente el
    conjunto esperado de cambios del ticket (el fix quedo RESTAURADO tras
    el `git stash pop`, ningun revert temporal sobrevive).

### 2026-07-09 - Builder - Fase 6: cableado PRE en 3 prompts
- `prompts/orchestrator_destination_bootstrap.md` (l.37 tras el fix):
  anadido sub-parrafo dentro del "Paso 0: Guard de prefijo" invocando
  `check_worktree_topology.py --ticket <TICKET_O_PROYECTO> --motor-root
  <motor_root> --project-root <workspace_activo>`, misma politica de exit
  codes (0 continua, 1/2 detente).
- `prompts/orchestrator_launch_builder.md` (l.38 tras el fix): anadido
  dentro de "Preflight (WOT-2026-009a)", ANTES de "## Rol y limites", la
  invocacion `check_worktree_topology.py --ticket {{TICKET_ID}} --motor-root
  <MOTOR_ROOT> --project-root <DESTINO>`, deteniendose con
  `WORKTREE_TOPOLOGY_VIOLATION` si el exit code no es 0.
- `prompts/orchestrator_session_bootstrap.md` (l.100-114 tras el fix):
  anadida, dentro de "2. PREFLIGHT (topologia worktree-dev)", la invocacion
  programatica del guard para el ticket WOT activo con
  `--project-root orquestador_de_agentes_workspace`, complementando el
  chequeo manual en prosa que ya existia.
- Confirmado con `grep -n check_worktree_topology` sobre los 3 archivos:
  las 3 lineas de invocacion existen literalmente.

### 2026-07-09 - Builder - Fase 7: cableado POST en manager_review.md
- Anadido "## Paso 1b: Verificacion de topologia de worktree (WOT-2026-021g)"
  INMEDIATAMENTE DESPUES del "Paso 1: Clasificacion" (antes del "Paso 2:
  Verificacion mecanica"), citando `check_worktree_topology.py --ticket
  {{TICKET_ID}} --motor-root <repo_motor>`; si exit code != 0 -> veredicto
  `CHANGES` con blocker "topologia de worktree violada durante la
  implementacion".
- `git diff prompts/manager_review.md`: el diff completo empieza en la
  linea 46 del archivo (dentro/despues del Paso 1, l.30-45); el "Paso 0:
  Ambito de este review - CF-frozen vs implementacion" (l.15-28) queda
  bit a bit identico -- confirmado, 0 lineas de diff en ese rango.

### 2026-07-09 - Orquestador - Fase 8: gates (completada por el orquestador)
El Builder agoto su tanda tras Fase 7 sin registrar Fase 8. El orquestador
corre y verifica los gates de forma independiente (que es tambien la
verificacion de cumplimiento previa al Review 2 fresh-context):

- `ruff check scripts/prefix_resolver.py scripts/check_worktree_topology.py
  tests/unit/test_prefix_resolver.py tests/unit/test_check_worktree_topology.py`:
  **All checks passed!** (exit 0, sin `# noqa` de complejidad; el `# noqa: S603`
  del subprocess es el estandar aceptado para args controlados, no silencia
  complejidad).
- `ruff format --check` (mismos 4 archivos): **4 files already formatted** (exit 0).
- `pytest tests/unit/test_no_legacy_topology_terms.py tests/unit/test_prefix_resolver.py
  tests/unit/test_check_worktree_topology.py -q`: **54 passed** (exit 0). Incluye
  el gate focal `test_no_legacy_topology_terms.py` (cambio de prosa de topologia
  en prompts) verde.
- Suite completa `python scripts/run_pytest_safe.py --level all`:
  **3627 passed, 47 skipped en 194.43s, 0 failed/error** (leido del output real,
  no del exit code del wrapper).
  NOTA DE FALSE-GREEN CAZADO: la 1a invocacion fue `run_pytest_safe.py -- --level all`
  (INCORRECTA: `--level` es flag del wrapper, va ANTES del `--`; pasarlo tras `--`
  lo manda a pytest -> "unrecognized arguments: --level" -> pytest aborta pero el
  wrapper reporto exit 0). Cazado leyendo el output. Invocacion correcta:
  `run_pytest_safe.py --level all` (sin `--`). Leccion: leer el output real de la
  suite, nunca fiarse del exit code del wrapper.
- `python .agent/agent_controller.py --validate --json --force`: **0 errores**,
  7 warnings (6 ticket_prose + 1 bus_drift), TODOS esperados/no-bloqueantes en
  code-only mode (documentado en el handoff).
- Encoding: los em-dash detectados por el Builder en los prompts eran
  PREEXISTENTES (l.14 titulo "Paso 0 ... - ANTES de tocar nada"), no del diff
  de 021g -- confirmado por `git show HEAD:`.

### 2026-07-09 - Review 2 fresh-context (manager) - APPROVE, con mutation de PRODUCCION
Revisor fresh-context muto el codigo de PRODUCCION real (no fixtures) para probar
que las barreras del guard nuevo son genuinas, no false-green. Par ejecutable
(el bloque `sin_check` documentado del mutation de Fase 5 NO era ejecutable; ESTE si):
```
mutation-verify (Review 2): check_worktree_topology.py Verificacion B es barrera genuina
  sin_B (desactivar Verif. B en el codigo: return (0,...) directo antes del check de workspace):
    test: pytest test_case_i_wot_dev_correct_wrong_workspace_exits_one
    resultado: FAILED (0 != 1)  # el test caza la desactivacion -> barrera genuina
  con_B (codigo restaurado):
    resultado: PASSED
mutation-verify (Review 2): check_worktree_topology.py Verificacion A es barrera genuina
  sin_A (forzar `if False:` en el chequeo de rama/toplevel):
    test: pytest test_case_b_wot_primary_detached_exits_one
    resultado: FAILED  # el test caza la desactivacion -> barrera genuina
  con_A (codigo restaurado):
    resultado: PASSED
```
Ambas mutaciones revertidas; 11/11 passed reconfirmado; git status identico al original.

### 2026-07-09 - Orquestador - Fix post-review (BLOCKER de cierre)
Un review de cierre cazo que el cableado POST en `prompts/manager_review.md` (Paso 1b)
citaba el guard SIN `--project-root` -- unico de los 4 prompts sin ese flag. Consecuencia:
al ejecutar el check POST para un ticket WOT, la Verificacion B no podria derivar el
workspace -> exit 1 -> falso CHANGES "topologia violada" en un ticket que SI respeto la
topologia. Corregido: `manager_review.md:51` ahora incluye `--project-root <workspace_activo>`
+ nota de obligatoriedad. Verificado en vivo que los otros 3 prompts YA lo tenian
(destination_bootstrap:37, launch_builder:38, session_bootstrap:111).
- Rerun focal con el RUNNER CANONICO (`run_pytest_safe.py`, gestiona basetemp en temp del
  sistema): **54 passed** (test_prefix_resolver + test_check_worktree_topology +
  test_no_legacy_topology_terms). El PermissionError de un rerun con pytest DIRECTO
  (sin el runner) es del sandbox in-repo, no del ticket.
- `--validate` tras el fix del prompt: **0 errores**, 7 warnings esperados en esa verificacion puntual; la revalidacion post-cierre queda registrada abajo con 9 warnings aceptadas en code-only mode.
- Mi edicion del prompt es 100% ASCII; los em-dash del archivo son preexistentes (l.237/240/260,
  template MANAGER REVIEW REPORT), no de 021g.

### 2026-07-09 - Orquestador - Ajuste post-cierre de proyecciones
- TURN.md actualizado a estado terminal: WOT-2026-021g COMPLETED. Motivo: tras el commit 3711dc8, STATE/work_plan/execution_log estaban COMPLETED, pero TURN conservaba la ultima instruccion BUILDER/IMPLEMENT; era una proyeccion visual stale.
- Revalidacion posterior al cierre: `python .agent/agent_controller.py --validate --json --project-root C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev --force` devuelve 0 errores y 9 warnings aceptadas en code-only mode: 6 `ticket_prose`, 1 `bus_drift`, 2 `invariants` por bus ausente (`BUILDER_EXIT` y `STATE_CHANGED`). Estas warnings no bloquean este cierre porque WOT-2026-021g se cerro commit-directo/code-only, igual que la serie 020/021b.
