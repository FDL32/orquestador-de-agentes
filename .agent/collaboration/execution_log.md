# Execution Log - WOT-2026-019m

Ticket: worktree-dev del MOTOR para desarrollo paralelo sin ensuciar el
checkout consumido.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-06). Fase 0 (Orquestador)
  verifico en codigo los dos modos de consumo del motor (sync-copia y
  runtime-en-vivo), el requisito de venv propio por resolucion relativa a
  la raiz auditada, y que `motor_destination_link.json` esta gitignored;
  no se re-deriva en el plan, se cita como verificado.
- work_plan.md, STRATEGY_WOT-2026-019m.md y AUDIT_WOT-2026-019m.md creados.
  Artefactos de WOT-2026-019j (ya COMPLETED en el bus) archivados a
  `.agent/collaboration/_archive/plan_audit/` (PLAN/STRATEGY/AUDIT) y
  `.agent/collaboration/execution_log_WOT-2026-019j.md`.
- Ajuste de redaccion tras `--validate`: 2 ocurrencias de "todo su
  ciclo"/"todo el ciclo" en el criterio de campo diferido disparaban
  TP-PROSE-04 (extremos-lazy) por limite del lookahead del regex sobre
  texto cerca del final del documento; reformuladas a "en cada fase de su
  ciclo" sin cambiar el significado del contrato. Anadida la seccion
  `## Decision Arquitectonica` (ausente, TP-PROSE-10) con el razonamiento
  real de worktree-vs-clon y venv-propio-vs-compartido ya presente en
  Trade-offs, sin contradecirlo.
- `--validate --json --project-root .` final: 0 errores, 1 warning
  (`bus_drift` esperado antes del bootstrap).

## Correccion post-aprobacion: blocker de Fase 0 tardia (rama en dos worktrees)

- El Orquestador (coordinador) reporto un BLOCKER: la premisa de
  `git worktree add ..\orquestador_de_agentes_dev main` con el checkout
  principal todavia en `main` es FALSA -- git no permite la misma rama
  checked-out en dos worktrees a la vez.
- Reproducido de forma INDEPENDIENTE por el Manager en un repo de prueba
  nuevo en el scratchpad (no confiando solo en el reporte): `git worktree
  add ../repo_test_dev main` con `repo_test` en `main` da `fatal: 'main' is
  already used by worktree at '<repo_test>'`, exit 128.
- Verificada tambien la solucion propuesta en el mismo repo de prueba:
  `git checkout --detach` en el principal (queda en el mismo commit, arbol
  intacto) seguido de `git worktree add ../repo_test_dev main` da exit 0;
  `git worktree list` muestra el principal `(detached HEAD)` y la dev
  `[main]`, mismo SHA. Verificados ademas: detach idempotente (segunda
  llamada a `git checkout --detach` con HEAD ya detached, exit 0 sin
  error), `git worktree remove` + `git checkout main` en el principal
  (re-attach exitoso), y `git fetch && git checkout --detach origin/main`
  contra un remoto bare de prueba (exit 0).
- Aplicada la correccion en `work_plan.md`, `STRATEGY_WOT-2026-019m.md` y
  `AUDIT_WOT-2026-019m.md`: el checkout principal queda DETACHED (checkout
  de consumo); la worktree-dev lleva `main` (donde se trabaja y se
  pushea); la actualizacion post-push del principal es `git fetch && git
  checkout --detach origin/main` (no `git pull --ff-only`, que no aplica
  sin rama); el script opcional hace el detach ANTES del `worktree add`, y
  `-Remove` re-ata el principal a `main` solo tras un `worktree remove`
  exitoso.
- Re-verificado que el heading `## Files Likely Touched` sigue apareciendo
  una sola vez en `work_plan.md` y en `AUDIT_WOT-2026-019m.md` tras las
  ediciones (guard del bug 019l/019j).
- `--validate --json --project-root .` tras la correccion: 0 errores, 0
  warnings.

## Implementacion (Builder + verificacion/cierre del Orquestador)

DECISION DE ORDEN (humano): las Fases 1-2 (activacion REAL de la worktree sobre
el motor: `git checkout --detach` + `worktree add` + `uv venv/sync` + suite desde
la dev) quedan DIFERIDAS a post-cierre, para evitar el bootstrap circular (el
ticket que crea la infra se cerraria con main movido a la worktree). Este ticket
entrega SOLO lo versionado + tests contra fixture; la activacion la ejecuta el
Orquestador/humano con el script ya versionado tras pushear 019m.

Entregables:
- `QUICKSTART.md`: seccion `## 0d. Motor dev worktree` (9 puntos: modelo de ramas
  invertido dev=main/principal=detached, creacion en 2 pasos, venv propio, suite
  desde la dev, ciclo de cierre con fetch+checkout --detach origin/main,
  desmontaje, nota canal-estable-futuro, nota alcance del criterio en campo).
- `scripts/setup_dev_worktree.ps1`: idempotente, SupportsShouldProcess (-WhatIf),
  detach-antes-de-add, -Remove con exit 2 fail-closed sobre worktree sucia.
- `tests/test_setup_dev_worktree_script.py`: 6 tests contra un repo FIXTURE
  temporal (uv fake en PATH; git checkout --detach + worktree add REALES sobre el
  fixture, NUNCA sobre el motor): creacion detach+add+venv, idempotencia, -WhatIf
  no-muta, -Remove limpia+reata-main, -Remove sucio->exit 2, y regresion
  detach-antes-de-add (documenta el `fatal: main already used`).

Verificacion del Orquestador (re-corrida sobre el repo real):
- 6 tests PASSED; ruff check `All checks passed!`; ruff format limpio; el .ps1
  parsea (PSParser::Tokenize OK).
- STOP condition respetada: NO se creo `..\orquestador_de_agentes_dev` real;
  `git worktree list` sigue mostrando solo el principal en `[main]` e7defc7.
- validate 0/0.
- DESCARTADO un parche "unborn branch guard" propuesto por un backend externo: sin
  evidencia de necesidad (tests verde sin el; el motor nunca es unborn; el script
  solo corre sobre el motor real), y el parche traia emojis que el encoding guard
  rechazaria. Anadir defensa para un caso imposible contradice los non-goals.
- Eliminado un `run_worktree_tests.ps1` huerfano (scratch manual de un backend
  externo, en la raiz del repo, fuera del FLT): el test canonico ya cubre todo.
- Fix menor propio: RUF059 (variable `worktree_path` sin usar en un test) ->
  prefijo `_`.


Scope override: Sobre-captura del scope gate + activacion diferida. git diff origin/main..HEAD (commit 45c1982) toca SOLO los 12 archivos de 019m (QUICKSTART.md, scripts/setup_dev_worktree.ps1, tests/test_setup_dev_worktree_script.py, colaboracion 019m + churn de archivado 019j). 0 hits para TODOS los archivos ajenos listados (AUDIT/PLAN/STRATEGY 019a/019c/019i/019j, scope_gate/motor_checkpoint/agent_controller/pre_handoff_guard/run_gates_dispatch, test_check_publication_gate, bootstrap: artefactos de tickets ya cerrados y pusheados). El 'missing: ..._dev' es CORRECTO y esperado: la activacion real de la worktree esta DIFERIDA a post-cierre por decision de orden (evita bootstrap circular); este ticket solo versiona el mecanismo. Suite 3518 verde tested_sha==HEAD 45c1982. Verificado auditablemente.. Affected files: <REPO_ROOT>/.agent/agent_controller.py, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019a.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019a.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019c.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019j.md, <REPO_ROOT>/.agent/motor_checkpoint.py, <REPO_ROOT>/.agent/scope_gate.py, <REPO_ROOT>/prompts/orchestrator_session_bootstrap.md, <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/scripts/run_gates_dispatch.py, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_check_publication_gate.py, <REPO_ROOT>/tests/test_setup_dev_worktree_script.py, <REPO_ROOT>/tests/unit/test_motor_checkpoint.py, <REPO_ROOT>/tests/unit/test_run_gates_dispatch.py, <REPO_ROOT>/tests/unit/test_scope_gate_deliverable_aware.py, <REPO_ROOT>/tests/unit/test_scope_gate_topology.py, orquestador_de_agentes_dev

Manager approved canonical closeout for WOT-2026-019m

## Correccion pre-push (2 blockers del Manager review, verificados en codigo)

BLOCKER 1 (real, de fondo): `Step-DetachPrincipal` NO comprobaba el arbol del
checkout principal antes del `git checkout --detach` -> un principal sucio
quedaba detached-y-sucio, justo el estado que 019m existe para evitar. Fix:
`Test-PrincipalHasUncommittedChanges` (mismo patron que el
`Test-WorktreeHasUncommittedChanges` que ya usa -Remove) + guard fail-closed al
inicio de `Step-DetachPrincipal` (exit 2 en modo real; en -WhatIf reporta que
bloquearia sin abortar). Test nuevo `test_creation_fails_closed_when_principal_is_dirty`
(principal sucio -> exit 2, principal sigue en main, worktree NO creada).
MUTATION del Orquestador: neutralizar el guard -> el test falla (script devuelve
0 y crea la worktree sobre principal sucio); restaurado -> 7 passed. Barrera viva.

BLOCKER 2 (error factual en doc): QUICKSTART decia usar `git worktree prune` para
descartar una worktree sucia -> FALSO (prune solo limpia metadatos huerfanos, no
descarta cambios). Fix: reformulado a commitear/`git stash` y reintentar remove;
`git worktree remove --force` descarta sin recuperacion, solo con decision
explicita; prune solo para metadatos huerfanos.

Verificacion: 7 tests PASSED, ruff check/format limpio, script parsea. Ambos fixes
tocan solo los 3 archivos del FLT. Correccion pre-push sobre el ticket ya COMPLETED
(no salio a origin): commit correctivo + re-suite sobre HEAD final antes del push.

## Hotfix CI post-push (barrera CI-only): test no portable a Linux

El push de 7ce31a0 dejo Quality Gates en FAILURE (Security Audit verde). Causa
REAL (no flaky): `test_setup_dev_worktree_script.py` no es portable. El fake uv es
un `uv.bat` (shim Windows) que en el runner Linux (pwsh) NO se resuelve -> el
script cae al `uv` REAL del runner (crea venv Linux py3.11) y la 2a corrida falla
con "venv already exists" (exit 2); ademas las aserciones asumen el layout
`Scripts/python.exe` (Windows), inexistente en Linux (`bin/python`). 2 failed en
CI Linux (test_creation_detaches... + test_creation_is_idempotent...), 0 en la
suite local Windows -> gap de portabilidad que solo el CI Linux caza.

Fix: `pytestmark = pytest.mark.skipif(sys.platform != "win32", ...)` a nivel de
modulo. `setup_dev_worktree.ps1` es infraestructura Windows-native del motor
(PowerShell, rutas `\`, layout `.venv\Scripts\python.exe`, fake `uv.bat`); el
motor se desarrolla en Windows y este script NUNCA corre en el CI Linux ni en
destinos Linux. Mismo patron canonico que tests/unit/test_launcher_powershell_syntax.py
(tests de scripts PS1 Windows-only). Verificado: en Windows los 7 tests corren y
pasan (skip no aplica); en Linux skipean (skipif=True) -> el runner ya no ejecuta
el .ps1 con uv real. ruff limpio. Estado: CLOSED_PENDING_CI -> el cierre real es CI
verde post-push. Follow-up: si se quiere cobertura del .ps1 en CI, exigiria un runner
Windows o un fake uv cross-plataforma + aserciones agnosticas de layout (no-goal aqui).