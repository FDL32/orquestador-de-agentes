# Work Plan - WOT-2026-019m

## Metadata
- **ID:** WOT-2026-019m
- **Estado:** APPROVED
- **deliverable_type:** mixed
- **Titulo:** worktree-dev del MOTOR para desarrollo paralelo sin ensuciar el
  checkout consumido.
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Crear y documentar una worktree de git separada del motor
(`orquestador_de_agentes`) donde se trabajen los tickets del motor, de modo
que el checkout principal permanezca siempre limpio y DETACHED en el commit
de `origin/main` (actualizado solo con `git fetch && git checkout --detach
origin/main` tras cada cierre) y sea el unico consumido por los destinos en
sus dos modos de uso: sync-copia y runtime-en-vivo. La rama `main` vive en
la worktree-dev, no en el checkout principal (git no permite la misma rama
en dos worktrees a la vez; ver Contexto punto 2).

## Contexto

Fase 0 (verificada en codigo hoy, 2026-07-06, no se re-deriva en este plan):

1. El motor se consume en DOS modos: sync-copia
   (`install_agent_system.py:344-422`, via `shutil.copy2`/`copytree`) y
   runtime-en-vivo (`run_gates_dispatch.py`: `MOTOR_SCRIPTS_DIR =
   MOTOR_ROOT/scripts`, subprocess con `cwd=MOTOR_ROOT`; `prepush_check.py`
   resuelve `motor_root` via `motor_destination_link.json`). Un ticket del
   motor a medias contamina las corridas de los destinos porque los guards
   leen el working tree real del checkout principal.
2. Fix elegido (CORREGIDO tras blocker de Fase 0 tardia, verificado en
   vivo en un repo de prueba): git NO permite que la misma rama este
   checked-out en dos worktrees a la vez -- `git worktree add
   ..\orquestador_de_agentes_dev main` ejecutado con el checkout principal
   todavia en `main` FALLA con `fatal: 'main' is already used by worktree
   at '<principal>'` (exit 128). El procedimiento correcto invierte quien
   lleva la rama: (a) el checkout principal se pone DETACHED con `git
   checkout --detach` (permanece en el mismo commit, arbol intacto); (b)
   solo entonces `git worktree add ..\orquestador_de_agentes_dev main`
   funciona, y la worktree-dev queda en `[main]`. Los tickets del motor se
   trabajan y se pushean desde la worktree-dev (que lleva `main`); el
   checkout principal, ya detached, se actualiza tras cada push de cierre
   con `git fetch && git checkout --detach origin/main` (un `git pull
   --ff-only` no aplica sobre un HEAD detached sin rama). El checkout
   principal detached es de facto read-only para uso operativo (commitear
   ahi deja commits huerfanos), que es exactamente el rol de "checkout de
   consumo" que necesitan los destinos.
3. La worktree necesita un venv PROPIO: `run_pytest_safe.py:132` resuelve
   `<root>/.venv/Scripts/python.exe` relativo a la raiz del proyecto que se
   audita, y `pyvenv.cfg` no ancla la ruta del propio venv (solo `home`
   apunta al Python compartido de `uv`). Se crea con `uv venv && uv sync`
   (el `uv.lock` del repo ya existe y fija las versiones).
4. `motor_destination_link.json` esta gitignored (verificado con `git
   check-ignore`), por lo que la worktree nueva arranca deslinkada de
   cualquier destino: comportamiento correcto para hacer dogfooding del
   motor contra si mismo.
5. Los hooks pre-commit comparten el directorio de hooks del `.git` comun
   entre todas las worktrees (git worktree: `.git` es un archivo puntero
   compartido) y referencian el interprete via ruta absoluta; un commit de
   prueba hecho desde la worktree debe pasar esos hooks igual que en el
   checkout principal. Esto se verifica en vivo (Fase 2.2 del plan), no se
   asume.
6. `Resolve-VenvPython` en `launch_agent_terminals.ps1:113-127` busca
   `.venv` relativo a la raiz que recibe como parametro; con un venv propio
   en la worktree, resuelve correctamente si el launcher se apunta a esa
   raiz.
7. Un canal estable (tag o rama dedicada que consuman los destinos, para
   proteger contra breaking changes) queda fuera de este ticket: es un
   riesgo distinto (estabilidad de version, no suciedad del checkout) y se
   deja anotado como nota de futuro en la documentacion nueva.

## Non-goals

- No se crea ni modifica ningun canal estable (tag/rama dedicada) para que
  los destinos consuman una version fija del motor; queda como nota de
  futuro en la documentacion.
- No se modifica `install_agent_system.py`, `run_gates_dispatch.py`,
  `prepush_check.py` ni ningun otro modulo de sincronizacion o runtime-en-
  vivo: este ticket es puramente de flujo de desarrollo (worktree +
  documentacion + script auxiliar opcional), no de logica de negocio.
- No se modifican hooks pre-commit ni la configuracion de CI: se verifica
  en vivo que los hooks existentes funcionan igual desde la worktree, sin
  tocar su definicion.
- No se mueve ni se reconfigura el repositorio
  `orquestador_de_agentes_workspace`.
- No se deja la worktree creada por este ticket como entregable permanente
  del repo: es un artefacto de desarrollo local (no versionado, fuera de
  `orquestador_de_agentes/`), reproducible en cualquier maquina siguiendo la
  documentacion o ejecutando el script opcional. Al cierre del ticket puede
  desmontarse o dejarse montada; ambos estados son validos porque no forma
  parte del arbol versionado del motor.
- El criterio de campo "un ticket completo trabajado en la worktree deja el
  checkout principal limpio en cada fase de su ciclo" NO se verifica dentro de
  este ticket 019m (este ticket SE HACE en el checkout principal porque es
  el que crea la worktree). Es el criterio de aceptacion en campo del
  PRIMER ticket del motor que se trabaje usando la worktree ya creada por
  019m; se documenta explicitamente como tal en la seccion nueva del
  `QUICKSTART.md`, no se declara verificado aqui.

## Decision Arquitectonica

Por que worktree de git y no un clon completo separado: una worktree
comparte el mismo repositorio Git (objetos, historia y directorio de
hooks) con el checkout principal, de modo que un commit hecho desde la
worktree pasa por los mismos hooks de pre-commit sin configuracion
adicional, y no duplica en disco la historia completa del repositorio. Un
clon separado resolveria el mismo problema de aislamiento del arbol de
trabajo, pero a costa de mantener remotes y hooks configurados por
duplicado y de poder divergir de `main` sin una disciplina de
sincronizacion extra. Por que venv propio en la worktree y no compartir el
`.venv` del checkout principal: el tooling de calidad (`run_pytest_safe.py`)
resuelve el interprete relativo a la raiz del proyecto que audita en cada
invocacion; compartir un unico venv entre dos arboles de trabajo
distintos, cada uno potencialmente en una rama o estado distinto,
arriesgaria a que dependencias distintas de cada ticket contaminen el
otro arbol.

## Configuracion Privada Requerida

Ninguna. No se necesitan archivos en `privada/`.

## Plan de Implementacion

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| 🤖 | TAREA AGENTE | Builder |

### Fase 1: Crear la worktree y su venv propio

#### 1.1: 🤖 Poner el checkout principal DETACHED y crear la worktree con `main`
- **Accion:** Ejecutar (no crea archivo versionado)
- **Descripcion:** Desde el checkout principal del motor
  (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes`), en DOS pasos
  secuenciales obligatorios: (1) `git checkout --detach` (deja el checkout
  principal en el mismo commit, arbol de trabajo intacto, pero ya no lleva
  la rama `main` -- paso necesario porque git no permite la misma rama
  checked-out en dos worktrees a la vez); (2) solo despues del paso (1),
  `git worktree add ..\orquestador_de_agentes_dev main`. Confirmar con `git
  worktree list` que aparecen exactamente dos entradas: el checkout
  principal en estado detached y `orquestador_de_agentes_dev` en `[main]`.
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** `git worktree list` ejecutado desde el
  checkout principal muestra el checkout principal como `(detached HEAD)`
  y `orquestador_de_agentes_dev` como `[main]`; ambos apuntan al mismo
  commit (`git rev-parse HEAD` identico en ambos); el checkout principal
  (`git status --short`) permanece sin cambios tras ambos comandos.

#### 1.2: 🤖 Crear el venv propio de la worktree
- **Accion:** Ejecutar
- **Descripcion:** Desde `orquestador_de_agentes_dev`, ejecutar `uv venv`
  seguido de `uv sync` para materializar `.venv/` local a la worktree
  usando el `uv.lock` existente.
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** Existe
  `orquestador_de_agentes_dev\.venv\Scripts\python.exe`; `uv sync` termina
  con exit code 0; `orquestador_de_agentes_dev\.venv\pyvenv.cfg` no
  contiene ninguna ruta al checkout principal (`orquestador_de_agentes\.venv`)
  salvo la linea `home` que apunta al Python base compartido de `uv` (no al
  venv del checkout principal).

### Fase 2: Verificar la worktree en vivo (suite + commit de prueba + aislamiento del checkout principal)

#### 2.1: 🤖 Correr la suite canonica DESDE la worktree con su propio venv
- **Accion:** Ejecutar
- **Descripcion:** Desde `orquestador_de_agentes_dev`, ejecutar
  `.venv\Scripts\python.exe scripts\run_pytest_safe.py --level all` (el
  mismo runner canonico del motor, invocado con el interprete de la
  worktree, no el del checkout principal).
- **Riesgo:** 🟡 Medio
- **Criterio de Aceptacion:** El comando termina con exit code 0; el stamp
  de `run_pytest_safe.py` (last-run) queda escrito dentro de
  `orquestador_de_agentes_dev` (no en el checkout principal); durante y
  despues de la corrida, `git status --short` ejecutado en el checkout
  principal (`orquestador_de_agentes`) no muestra ningun cambio.

#### 2.2: 🤖 Verificar que un commit de prueba desde la worktree pasa los hooks pre-commit
- **Accion:** Ejecutar
- **Descripcion:** Desde `orquestador_de_agentes_dev`, crear un commit de
  prueba con `git commit --allow-empty -m "WOT-2026-019m: verificacion de
  hooks pre-commit desde la worktree-dev"` y confirmar que los hooks de
  `pre-commit` configurados en el repo se ejecutan y pasan. Tras verificar,
  revertir el commit de prueba DENTRO de la worktree con `git reset --hard
  HEAD~1` (nunca en el checkout principal) para no dejar commits de prueba
  en `main`.
- **Riesgo:** 🟡 Medio
- **Criterio de Aceptacion:** La salida del `git commit` muestra los hooks
  de pre-commit ejecutandose (no "no pre-commit hooks configured" ni
  saltados) y terminando en exito; tras revertir el commit de prueba,
  `git log --oneline -3` en la worktree no conserva el commit de prueba; el
  checkout principal sigue sin cambios (`git status --short` vacio)
  durante toda esta fase.

#### 2.3: 🤖 Confirmar el checkout principal detached y limpio de punta a punta
- **Accion:** Verificar (no crea archivo)
- **Descripcion:** Ejecutar `git status --short` y `git worktree list` en
  el checkout principal una vez completadas las fases 1 y 2, como cierre de
  la evidencia operativa de aislamiento.
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** `git status --short` en el checkout principal
  devuelve vacio; `git worktree list` sigue mostrando las dos worktrees, el
  checkout principal como `(detached HEAD)` en el commit de `origin/main` y
  `orquestador_de_agentes_dev` como `[main]`, sin worktrees marcadas
  `prunable` ni corruptas.

### Fase 3: Documentar el procedimiento en QUICKSTART.md

#### 3.1: 🤖 Anadir la seccion "Motor dev worktree" a QUICKSTART.md
- **Archivo:** `QUICKSTART.md`
- **Accion:** Modificar
- **Descripcion:** Insertar una seccion nueva con heading `0d. Motor dev
  worktree` entre la seccion existente `0c. Startup Templates` y
  `1. Preflight`, cubriendo en este orden: (a) por que existe (los dos
  modos de consumo del motor, citados de la seccion Contexto de este plan,
  en prosa breve sin reproducir literalmente los nombres de funcion linea
  por linea); (b) el modelo de ramas: la worktree-dev lleva `main` (es
  donde se trabaja y se pushea); el checkout principal queda DETACHED (es
  lo que consumen los destinos), porque git no permite la misma rama
  checked-out en dos worktrees a la vez; (c) comando de creacion en DOS
  pasos, en este orden: `git checkout --detach` en el checkout principal,
  seguido de `git worktree add ..\orquestador_de_agentes_dev main`; (d)
  creacion del venv propio (`uv venv && uv sync` dentro de la worktree);
  (e) como correr la suite canonica desde la worktree
  (`.venv\Scripts\python.exe scripts\run_pytest_safe.py --level all`, con
  el interprete de la worktree); (f) el ciclo de cierre: tras cada push de
  un ticket resuelto en la worktree (que ya lleva `main`, el push normal
  `git push origin main` funciona sin cambios), el checkout principal se
  actualiza SOLO con `git fetch && git checkout --detach origin/main`
  (nunca se trabaja un ticket directamente en el checkout principal, y
  `git pull --ff-only` no aplica porque el principal no lleva rama); (g)
  desmontaje: `git worktree remove ..\orquestador_de_agentes_dev` desde el
  checkout principal (y `git worktree prune` si `remove` reporta cambios
  sin commitear que el usuario decide descartar), seguido de `git checkout
  main` en el checkout principal para devolverlo al estado pre-ticket (la
  rama vuelve al checkout principal); (h) nota de futuro explicita: un
  canal estable (tag/rama dedicada) para que los destinos consuman una
  version fija del motor NO esta cubierto por este procedimiento, queda
  como trabajo futuro separado; (i) nota de alcance explicita: el criterio
  "un ticket completo trabajado en la worktree deja el checkout principal
  limpio en cada fase del ciclo" se verifica la primera vez que un ticket
  del motor completo se trabaje usando este procedimiento, no en el
  ticket que lo crea.
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** `QUICKSTART.md` contiene la seccion con
  heading `0d. Motor dev worktree` con los 9 puntos (a)-(i) anteriores en
  algun orden que preserve el sentido; los comandos citados en la seccion
  coinciden literalmente con los usados en las Fases 1 y 2 de este plan
  (mismo flag, mismo path relativo, mismo interprete referenciado, mismo
  orden detach-antes-que-add).

### Fase 4: Script auxiliar opcional (decision: SI se incluye)

Decision de alcance (cerrada, no condicional): se incluye
`scripts/setup_dev_worktree.ps1` porque el coste es bajo (script corto,
reutiliza patrones ya existentes en `scripts/launch_agent_terminals.ps1`
para resolver rutas) y el beneficio es reproducibilidad determinista del
procedimiento documentado en la Fase 3, con verificacion propia en vez de
quedar solo como prosa.

#### 4.1: 🤖 Crear scripts/setup_dev_worktree.ps1
- **Archivo:** `scripts/setup_dev_worktree.ps1`
- **Accion:** Crear
- **Descripcion:** Script idempotente que, ejecutado desde el checkout
  principal (o resolviendo la raiz del repo igual que
  `launch_agent_terminals.ps1` via `$PSScriptRoot`), realiza: (1) si el
  checkout principal NO esta ya en estado detached (`git symbolic-ref -q
  HEAD` devuelve una rama), ejecuta `git checkout --detach`; si ya esta
  detached, lo reporta y continua sin error (idempotente) -- este paso va
  SIEMPRE antes del paso (2); (2) si `..\orquestador_de_agentes_dev` no
  existe como worktree registrada (`git worktree list` no la lista),
  ejecuta `git worktree add ..\orquestador_de_agentes_dev main`; si ya
  existe, lo reporta y continua sin error (idempotente); (3) si
  `..\orquestador_de_agentes_dev\.venv\Scripts\python.exe` no existe,
  ejecuta `uv venv` y `uv sync` dentro de la worktree; si ya existe, lo
  reporta y continua sin error; (4) expone `-Remove` como parametro
  explicito que ejecuta `git worktree remove ..\orquestador_de_agentes_dev`
  para el desmontaje, y a continuacion `git checkout main` en el checkout
  principal para re-atar la rama y devolverlo al estado pre-ticket (en vez
  de dejarlo solo como instruccion en prosa); (5) expone el parametro
  estandar `-WhatIf` de PowerShell (`[CmdletBinding(SupportsShouldProcess)]`)
  que cubre AMBOS flujos (creacion y `-Remove`) e imprime que haria sin
  ejecutar `git checkout --detach`, `git worktree add`, `uv venv`/`uv sync`,
  `git worktree remove` ni `git checkout main`; el modo por defecto (sin
  `-WhatIf`) SIEMPRE ejecuta las acciones reales, `-WhatIf` es
  exclusivamente el modo de comprobacion previa y nunca sustituye a la
  ejecucion real documentada en la Fase 1. Codigos de salida: `0` en exito
  (incluye los casos ya-existe/ya-detached idempotentes), `1` si `git
  checkout --detach`, `git worktree add` o `uv venv`/`uv sync` fallan, `2`
  cuando `-Remove` se pide sobre una worktree con cambios sin commitear
  (falla cerrado, no fuerza el borrado y NO ejecuta `git checkout main`).
- **Riesgo:** 🟡 Medio
- **Criterio de Aceptacion:** `.\scripts\setup_dev_worktree.ps1 -WhatIf`
  ejecutado con el checkout principal ya detached y la worktree ya creada
  por la Fase 1 imprime el plan de accion sin modificar nada (`git
  worktree list`, la rama del checkout principal, y el contenido de
  `orquestador_de_agentes_dev\.venv` identicos antes/despues); ejecutado
  SIN `-WhatIf` una segunda vez sobre un checkout principal ya detached y
  una worktree+venv ya existentes, termina con exit code `0` y mensajes de
  "ya existe"/"ya detached" para los 3 pasos (idempotencia real, no solo
  narrativa); `.\scripts\setup_dev_worktree.ps1 -Remove` sobre la worktree
  limpia (sin cambios sin commitear) la elimina, `git worktree list` deja
  de listarla, y el checkout principal queda de nuevo en la rama `main`
  (`git branch --show-current` devuelve `main`); `.\scripts\setup_dev_worktree.ps1
  -Remove` invocado con la worktree teniendo un archivo modificado sin
  commitear devuelve exit code `2`, NO ejecuta `git worktree remove` y NO
  ejecuta `git checkout main` (el checkout principal permanece detached).
- **Si falla:** Si `-WhatIf` no puede implementarse limpiamente con
  `SupportsShouldProcess` por alguna limitacion de version de PowerShell,
  sustituirlo por un parametro explicito `-DryRun` casero con la misma
  semantica exacta, documentando el cambio en `execution_log.md`; el modo
  de comprobacion previa no se omite en ningun caso.

## Calidad

- `git worktree list` (Fase 1.1, Fase 2.3): verifica creacion, el estado
  detached del principal y `[main]` en la worktree-dev, y el aislamiento.
- `uv venv && uv sync` exit code 0 dentro de la worktree (Fase 1.2).
- `.venv\Scripts\python.exe scripts\run_pytest_safe.py --level all` exit
  code 0 ejecutado DESDE `orquestador_de_agentes_dev` con SU venv (Fase
  2.1).
- `git commit --allow-empty` desde la worktree pasando los hooks de
  pre-commit, luego revertido con `git reset --hard HEAD~1` (Fase 2.2).
- `git status --short` vacio en el checkout principal verificado al final
  de la Fase 2 (Fase 2.3).
- Fase 4 (script opcional): `.\scripts\setup_dev_worktree.ps1 -WhatIf`,
  ejecucion real idempotente repetida, y `.\scripts\setup_dev_worktree.ps1
  -Remove` en los dos escenarios (limpio y con cambios sin commitear),
  cada uno con el exit code declarado en el criterio de aceptacion de la
  Fase 4.1.
- No se requiere `ruff check`/`ruff format` adicional: el ticket no
  modifica ningun archivo `.py`.
- `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json
  --project-root .` exit 0/0 tras el cierre, ejecutado en el checkout
  PRINCIPAL sobre el `work_plan.md` real de este ticket.

## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Worktree del motor con principal detached + dev en main (git worktree add) | Comparte objetos y hooks con el checkout principal; sin duplicar el .git; nativo de git; el push de cierre no cambia (main vive en la dev) | Requiere invertir la rama (detach del principal primero, git no permite main en dos worktrees) y recordar que el principal es de solo consumo | Aceptada |
| Rama efimera por ticket en vez de detach (alternativa descartada) | Evita el concepto de HEAD detached | Rompe el flujo de cierre actual (`git push origin main`); obligaria a merge/push HEAD:main y cambiar cada procedimiento de cierre existente | Descartada |
| Clon completo separado (git clone) | Aislamiento total, sin compartir .git | Duplica historia completa en disco; hooks y remotes se configuran por separado; diverge facilmente de main sin disciplina extra de sync | Descartada |
| Script setup_dev_worktree.ps1 (Fase 4) | Reproducibilidad determinista; verificacion propia; idempotente | Superficie nueva a mantener | Aceptada (coste bajo, cubierto con verificacion) |
| Canal estable (tag/rama dedicada) para destinos | Protege contra breaking changes de version | Fuera del alcance de este ticket (riesgo distinto: estabilidad de version, no suciedad de checkout) | Descartada para este ticket; nota de futuro en la documentacion |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Decision sobre REVIEW

Review 2 adversarial fresh-context NO obligatoria (regla de blast-radius):
este ticket no toca gate/bus/estado/CI/hooks/seguridad; los hooks
pre-commit solo se VERIFICAN en vivo (Fase 2.2), no se modifican. Single
review del Manager es suficiente. Se recomienda que el Manager en review
repita literalmente el `git worktree list` y el `git status --short` del
checkout principal con sus propios ojos antes de aprobar el cierre, en vez
de confiar solo en el relato del `execution_log.md`.

## Files Likely Touched

- `QUICKSTART.md` (Fase 3.1, modificar)
- `scripts/setup_dev_worktree.ps1` (Fase 4.1, crear)
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/STRATEGY_WOT-2026-019m.md`
- `.agent/collaboration/AUDIT_WOT-2026-019m.md`
- `.agent/collaboration/execution_log.md`

Fuera del arbol versionado del motor (no aparecen en el diff del ticket,
solo en el `execution_log.md` como evidencia operativa): la worktree
`..\orquestador_de_agentes_dev` y su `.venv\` interno.

## Criterios de Aceptacion Global

- [ ] `git worktree list` (desde el checkout principal) muestra el
      checkout principal como `(detached HEAD)` y `orquestador_de_agentes_dev`
      como `[main]`, ambos en el mismo commit.
- [ ] `orquestador_de_agentes_dev` tiene su propio
      `.venv\Scripts\python.exe` creado con `uv venv && uv sync`, sin
      referenciar el `.venv` del checkout principal (salvo la linea `home`
      de `pyvenv.cfg` apuntando al Python base compartido de `uv`).
- [ ] `scripts\run_pytest_safe.py --level all` ejecutado DESDE la worktree
      con SU venv termina con exit code 0.
- [ ] Un commit `--allow-empty` ejecutado desde la worktree pasa los hooks
      de pre-commit (evidencia literal en `execution_log.md`) y queda
      revertido sin dejar rastro en `main`.
- [ ] El checkout principal permanece con `git status --short` vacio
      durante y despues de todo el proceso (Fases 1 y 2).
- [ ] `QUICKSTART.md` documenta el procedimiento completo (modelo de
      ramas detached-principal/main-en-dev, creacion en 2 pasos, venv,
      suite, cierre con `fetch && checkout --detach origin/main`,
      desmontaje con re-attach a `main`, nota de futuro sobre canal
      estable, nota de alcance sobre el criterio de campo).
- [ ] `scripts/setup_dev_worktree.ps1` (Fase 4) cumple los 4 escenarios de
      su criterio de aceptacion (whatif, idempotencia real, remove limpio,
      remove con cambios sin commitear fallando cerrado con exit 2).
- [ ] `.venv\Scripts\python.exe .agent\agent_controller.py --validate
      --json --project-root .` exit 0/0 en el checkout principal al cierre
      del ticket.
