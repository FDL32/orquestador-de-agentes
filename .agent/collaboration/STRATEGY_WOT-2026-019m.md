# STRATEGY - WOT-2026-019m

Ticket: worktree-dev del MOTOR para desarrollo paralelo sin ensuciar el
checkout consumido.
Estado del plan: APPROVED

## Resumen tecnico

El motor se consume en dos modos (sync-copia y runtime-en-vivo) que leen
el working tree real del checkout principal. Trabajar tickets del motor
directamente ahi contamina las corridas de los destinos mientras el ticket
esta a medias. La estrategia es crear una worktree de git separada
(`..\orquestador_de_agentes_dev`) donde se trabajen los tickets del motor,
con su propio venv (`uv venv && uv sync`, porque el tooling resuelve
`<root>/.venv` relativo a la raiz auditada).

CORRECCION (blocker de Fase 0 tardia, verificado en vivo en un repo de
prueba): `git worktree add ..\orquestador_de_agentes_dev main` con el
checkout principal todavia en `main` FALLA (`fatal: 'main' is already used
by worktree at '<principal>'`, exit 128) porque git no permite la misma
rama checked-out en dos worktrees a la vez. El modelo correcto invierte
quien lleva la rama: el checkout principal se pone DETACHED (`git checkout
--detach`, mismo commit, arbol intacto) ANTES de `git worktree add
..\orquestador_de_agentes_dev main`; la worktree-dev queda en `[main]` y es
donde se trabaja y se pushea (`git push origin main` no cambia). El
checkout principal, ya detached, se actualiza tras cada push de cierre con
`git fetch && git checkout --detach origin/main` (no `git pull --ff-only`,
que no aplica sin rama).

## Secuencia (identica al work_plan.md; este documento no la reemplaza)

1. Fase 1: poner el checkout principal detached (`git checkout --detach`),
   crear la worktree con `main` (`git worktree add
   ..\orquestador_de_agentes_dev main`, en ese orden) y su venv propio (`uv
   venv && uv sync`).
2. Fase 2: verificar en vivo, desde la worktree: suite canonica
   (`scripts\run_pytest_safe.py --level all`) con su propio interprete;
   commit `--allow-empty` que pasa los hooks pre-commit compartidos (luego
   revertido con `git reset --hard HEAD~1`); y confirmar que el checkout
   principal queda `(detached HEAD)` con `git status --short` vacio en
   todo momento.
3. Fase 3: documentar el procedimiento completo (incluido el modelo de
   ramas invertido y la actualizacion post-push con `fetch && checkout
   --detach origin/main`) en una seccion nueva de `QUICKSTART.md` (heading
   `0d. Motor dev worktree`), entre `0c. Startup Templates` y
   `1. Preflight`.
4. Fase 4 (decision cerrada: SI se incluye): `scripts/setup_dev_worktree.ps1`,
   idempotente, que hace el detach del principal ANTES del `worktree add`,
   con `-WhatIf` (comprobacion previa, PowerShell `SupportsShouldProcess`,
   cubre ambos flujos) y `-Remove` (desmontaje que re-ata el principal a
   `main` con `git checkout main`, fallando cerrado con exit 2 si hay
   cambios sin commitear en la worktree).

## Decisiones de diseno

- Worktree de git (no clon completo separado): comparte objetos y hooks
  pre-commit con el checkout principal; el trade-off (recordar cual arbol
  lleva la rama) se acepta porque el beneficio de aislamiento del arbol de
  trabajo es el objetivo del ticket.
- Principal detached + dev en `main` (no una rama efimera por ticket): la
  alternativa de crear una rama nueva por ticket en la worktree evitaria el
  concepto de HEAD detached, pero rompe el flujo de cierre actual (`git
  push origin main` deja de funcionar tal cual, obligando a merge/push
  HEAD:main y a cambiar todos los procedimientos de cierre). Invertir la
  rama (detach del principal, `main` vive en la dev) preserva el flujo de
  push sin cambios y hace del principal un "checkout de consumo" de facto
  read-only.
- venv propio obligatorio en la worktree, no reutilizar el `.venv` del
  checkout principal: verificado que `run_pytest_safe.py:132` resuelve el
  interprete relativo a la raiz auditada, y que `pyvenv.cfg` no ancla la
  ruta del propio venv.
- El canal estable (tag/rama dedicada para que los destinos consuman una
  version fija del motor) queda fuera de este ticket: protege contra un
  riesgo distinto (estabilidad de version), no contra la suciedad del
  checkout que este ticket resuelve. Se documenta como nota de futuro.
- El criterio "un ticket completo trabajado en la worktree deja el
  checkout principal limpio en cada fase de su ciclo" no se verifica dentro
  de este ticket porque 019m se trabaja en el checkout principal (es el
  ticket que crea la worktree); queda documentado como criterio de campo
  del primer ticket que use la worktree ya creada.

## Riesgos principales y mitigacion

- Riesgo: los hooks pre-commit podrian no compartirse correctamente entre
  worktrees en esta version de git. Mitigacion: verificacion en vivo
  obligatoria (Fase 2.2) con un commit `--allow-empty` real, no una
  asuncion documental.
- Riesgo: `uv venv`/`uv sync` podrian fallar por resolucion de cache o
  version de Python distinta a la del checkout principal. Mitigacion: el
  criterio de aceptacion de la Fase 1.2 exige exit code 0 explicito antes
  de continuar a la Fase 2.
- Riesgo: el script opcional (`Fase 4`) podria introducir un modo `-Remove`
  destructivo. Mitigacion: falla cerrado (exit 2) si detecta cambios sin
  commitear en la worktree, nunca fuerza el borrado, y solo re-ata el
  principal a `main` cuando el `git worktree remove` tuvo exito.
- Riesgo (ya materializado y corregido en este plan): asumir que la
  worktree-dev y el checkout principal pueden llevar la misma rama `main`
  simultaneamente. Mitigacion: verificado en vivo en un repo de prueba que
  esto falla (`fatal: 'main' is already used by worktree`); el modelo
  corregido invierte la rama (detach del principal antes del `worktree
  add`).

## Relacion con AUDIT_WOT-2026-019m.md

El `AUDIT_WOT-2026-019m.md` replica exactamente los criterios de
aceptacion de cada fase de este documento y del `work_plan.md`. Cualquier
diferencia entre ambos se resuelve a favor de `work_plan.md` (fuente larga
canonica).
