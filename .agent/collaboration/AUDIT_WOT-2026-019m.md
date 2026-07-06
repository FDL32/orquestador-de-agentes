# AUDIT - WOT-2026-019m

Ticket: worktree-dev del MOTOR para desarrollo paralelo sin ensuciar el
checkout consumido.
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las 4 fases del PLAN son secuenciales sin
  contradiccion: Fase 1 (detach del checkout principal, crear worktree con
  `main` en ESE orden, + venv propio) -> Fase 2 (verificar suite, commit de
  prueba y el estado detached/[main] del checkout principal DESDE la
  worktree ya creada) -> Fase 3 (documentar en QUICKSTART.md) -> Fase 4
  (script auxiliar opcional que automatiza las Fases 1 y su desmontaje con
  re-attach). Ningun paso pide crear y eliminar el mismo recurso en el
  mismo punto; la reversion del commit de prueba en la Fase 2.2 (`git
  reset --hard HEAD~1`) es explicita, acotada a la worktree, y documentada
  como paso de verificacion, no como estado final contradictorio. El orden
  detach-antes-que-worktree-add es el UNICO orden valido (git rechaza el
  orden inverso, ver evidencia del `fatal:` reproducido) y el plan lo fija
  como secuencia obligatoria, no como alternativa.
- TP-02: verificado - cada criterio de aceptacion de cada fase cita un
  comando o assert literal: `git worktree list` mostrando `(detached HEAD)`
  y `[main]`, `uv sync` exit code 0, `scripts\run_pytest_safe.py --level
  all` exit code 0, `git commit --allow-empty` + verificacion de hooks +
  `git reset --hard HEAD~1`, `git status --short` vacio, `git branch
  --show-current` devolviendo `main` tras `-Remove`, contenido concreto de
  `QUICKSTART.md`, y los escenarios con exit codes 0/0/1/2 del script
  opcional.
- TP-03: verificado - la seccion "Files Likely Touched" del `work_plan.md`
  enumera exactamente `QUICKSTART.md`, `scripts/setup_dev_worktree.ps1` y
  los 4 artefactos de colaboracion del ticket, sin comodines; la worktree y
  su `.venv` quedan explicitamente fuera del arbol versionado (declarado,
  no un "etc." implicito).
- TP-04: verificado - no aparece "si procede", "stale" ni semantica blanda
  equivalente en ninguna fase; el criterio de campo diferido (worktree
  limpia durante un ticket completo) esta marcado como Non-goal explicito
  de este ticket, no como ambiguedad.
- TP-05: verificado - este `AUDIT_WOT-2026-019m.md` replica los mismos
  criterios de aceptacion, los mismos comandos y los mismos verbos que el
  `work_plan.md` y el `STRATEGY_WOT-2026-019m.md`; ningun blocker de este
  documento introduce una condicion no presente en las Fases del plan.
- TP-07: verificado - la unica decision de alcance condicional aparente
  (script opcional) se cierra explicitamente en el `work_plan.md` como
  "decision de alcance (cerrada, no condicional): se incluye"; no queda
  como "si aplica".

## Criterios de aceptacion verificables (replican 1:1 el work_plan.md)

### Fase 1 - Detach del principal + Worktree y venv propio

- [ ] `git checkout --detach` ejecutado en el checkout principal ANTES de
      `git worktree add`; `git worktree add ..\orquestador_de_agentes_dev
      main` ejecutado DESPUES devuelve exit code 0 (evidencia negativa: si
      se invierte el orden, reproduce el `fatal: 'main' is already used by
      worktree`, ver TP-01 y Evidencia).
- [ ] `git worktree list` (checkout principal) muestra 2 entradas: el
      checkout principal como `(detached HEAD)` y
      `orquestador_de_agentes_dev` como `[main]`.
- [ ] `git rev-parse HEAD` identico en checkout principal y worktree-dev
      inmediatamente despues de crear la worktree.
- [ ] `git status --short` del checkout principal vacio inmediatamente
      despues de `git checkout --detach` y de `git worktree add`.
- [ ] `orquestador_de_agentes_dev\.venv\Scripts\python.exe` existe tras
      `uv venv && uv sync` con exit code 0.
- [ ] `orquestador_de_agentes_dev\.venv\pyvenv.cfg` no referencia la ruta
      del `.venv` del checkout principal (solo `home` al Python base
      compartido de `uv`).

### Fase 2 - Verificacion en vivo

- [ ] `orquestador_de_agentes_dev\.venv\Scripts\python.exe
      scripts\run_pytest_safe.py --level all` (ejecutado DESDE la
      worktree) exit code 0.
- [ ] El stamp/last-run de `run_pytest_safe.py` queda dentro de
      `orquestador_de_agentes_dev`, no en el checkout principal.
- [ ] `git commit --allow-empty -m "WOT-2026-019m: verificacion de hooks
      pre-commit desde la worktree-dev"` ejecutado dentro de la worktree
      muestra los hooks de `pre-commit` corriendo y terminando en exito
      (no "no pre-commit hooks configured").
- [ ] Tras `git reset --hard HEAD~1` en la worktree, `git log --oneline -3`
      no conserva el commit de prueba.
- [ ] `git status --short` del checkout principal vacio durante y despues
      de toda la Fase 2 (Fase 2.1 + 2.2 + 2.3).
- [ ] `git worktree list` al final de la Fase 2 sigue mostrando 2 entradas
      (`(detached HEAD)` en el checkout principal, `[main]` en la dev) sin
      marca `prunable` ni error de git.

### Fase 3 - Documentacion

- [ ] `QUICKSTART.md` contiene una seccion nueva con heading `0d. Motor dev
      worktree` ubicada entre `0c. Startup Templates` y `1. Preflight`.
- [ ] Esa seccion cubre los 9 puntos (a)-(i) enumerados en la Fase 3.1 del
      `work_plan.md`: motivo (2 modos de consumo), modelo de ramas
      (dev=main, principal=detached), comando de creacion en 2 pasos
      (detach del principal, luego worktree add main), creacion del venv,
      comando de suite, ciclo de cierre con `fetch && checkout --detach
      origin/main` (no `pull --ff-only`), desmontaje con re-attach a
      `main`, nota de futuro sobre canal estable, y nota de alcance sobre
      el criterio de campo diferido.
- [ ] La seccion NO afirma en ningun punto que el checkout principal
      conserve la rama `main` mientras la worktree-dev existe (contradiria
      el modelo verificado; blocker si aparece).
- [ ] Los comandos citados en la seccion nueva coinciden literalmente
      (mismo flag, mismo path relativo, mismo interprete, mismo orden
      detach-antes-que-add) con los ejecutados en las Fases 1 y 2.

### Fase 4 - Script opcional (si se implementa segun decision cerrada del plan)

- [ ] `.\scripts\setup_dev_worktree.ps1 -WhatIf` (principal ya detached,
      worktree ya existente) no modifica `git worktree list`, no cambia la
      rama del checkout principal, ni el contenido de
      `orquestador_de_agentes_dev\.venv`.
- [ ] `.\scripts\setup_dev_worktree.ps1` sin `-WhatIf`, ejecutado una
      segunda vez sobre un principal ya detached y worktree+venv ya
      existentes, exit code 0 con mensajes de "ya existe"/"ya detached"
      para los 3 pasos (detach, worktree add, venv).
- [ ] `.\scripts\setup_dev_worktree.ps1 -Remove` sobre worktree limpia
      (sin cambios sin commitear) la elimina; `git worktree list` deja de
      listarla; el checkout principal queda re-atado a `main`
      (`git branch --show-current` devuelve `main`).
- [ ] `.\scripts\setup_dev_worktree.ps1 -Remove` sobre worktree con un
      archivo modificado sin commitear devuelve exit code 2, NO ejecuta
      `git worktree remove` y NO ejecuta `git checkout main` (el checkout
      principal permanece detached).

### Cierre

- [ ] `.venv\Scripts\python.exe .agent\agent_controller.py --validate
      --json --project-root .` exit 0/0 en el checkout PRINCIPAL sobre el
      `work_plan.md` real del ticket.
- [ ] `execution_log.md` documenta la evidencia literal (salidas de
      comandos, no solo narrativa) de cada bloque anterior, porque la
      worktree y su venv no son artefactos versionados y su verificacion
      solo queda registrada ahi.

## Blockers (si aparecen durante la review)

- Blocker si `git worktree add ..\orquestador_de_agentes_dev main` se
  ejecuta ANTES de `git checkout --detach` en el checkout principal (orden
  invertido): reproduce el `fatal: 'main' is already used by worktree`
  documentado en Evidencia; el plan exige el orden detach-primero como
  secuencia obligatoria, no opcional.
- Blocker si `git status --short` del checkout principal muestra CUALQUIER
  cambio en algun punto de las Fases 1-2 (viola el objetivo central del
  ticket: aislar el checkout principal).
- Blocker si el commit de prueba de la Fase 2.2 NO dispara los hooks de
  pre-commit (indica que la worktree no comparte el directorio de hooks
  del `.git` comun, contradiciendo la premisa de Fase 0 punto 5).
- Blocker si `scripts/setup_dev_worktree.ps1` (de implementarse) tiene un
  modo `-Remove` que borra la worktree con cambios sin commitear sin
  fallar cerrado primero (AP-D01: limpieza destructiva fuera de scope
  declarado), o que ejecuta `git checkout main` en el principal ANTES de
  confirmar que `git worktree remove` tuvo exito.
- Blocker si `QUICKSTART.md` afirma o da a entender que el checkout
  principal conserva la rama `main` mientras la worktree-dev existe
  (contradice el modelo verificado en vivo).
- Blocker si `QUICKSTART.md` omite la nota de alcance explicita (punto i)
  sobre el criterio de campo diferido: dejaria la impresion falsa de que
  019m ya verifico "un ticket completo limpio", cosa que el plan declara
  expresamente como Non-goal.

## Evidencia esperada en execution_log.md

- Reproduccion del `fatal:` (evidencia del blocker de Fase 0 tardia que
  origino esta correccion): salida literal de `git worktree add
  ..\orquestador_de_agentes_dev main` intentado con el checkout principal
  TODAVIA en `main` (antes del detach), mostrando `fatal: 'main' is
  already used by worktree at '<...>'` y exit code 128. Esta reproduccion
  ya se hizo en un repo de prueba en el scratchpad durante la planificacion
  (Manager); el Builder puede referenciarla o reproducirla de nuevo contra
  el repo real como confirmacion adicional, sin que sea obligatorio
  repetirla si ya quedo documentada.
- Salida literal de `git checkout --detach` en el checkout principal y de
  `git worktree add ..\orquestador_de_agentes_dev main` (exit 0, en ese
  orden) mostrando el `(detached HEAD)` resultante.
- Salida literal de `git worktree list` antes y despues de la Fase 1.
- Salida literal (o resumen con exit code) de `uv venv` y `uv sync`.
- Salida literal (ultimas lineas relevantes) de `run_pytest_safe.py --level
  all` ejecutado desde la worktree, incluyendo el exit code.
- Salida literal del `git commit --allow-empty` mostrando los hooks
  ejecutandose, y del `git reset --hard HEAD~1` posterior.
- Salida de `git status --short` del checkout principal en al menos 2
  puntos: tras la Fase 1 y tras la Fase 2.
- Si se implementa la Fase 4: salida literal de los escenarios de
  `setup_dev_worktree.ps1` (whatif, idempotencia, remove limpio con
  re-attach a `main`, remove bloqueado por cambios sin commitear) con sus
  exit codes.
