# Plan de Trabajo: guard de topologia de worktree (WOT vs destino)

## Metadata
- **ID:** WOT-2026-021g
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-09
- **delivery_authority:** repo_motor
- **Prioridad:** ALTA
- **Asignado a:** Builder

## Objetivo
Crear `scripts/check_worktree_topology.py`, un guard ejecutable que bloquea con
exit 1 cuando un ticket `WOT` se trabaja desde el checkout principal detached del
motor (en vez de la worktree `_dev`, rama `main`), y aplicar un fix estrecho a
`scripts/prefix_resolver.py::guard()` para que reconozca `_dev` y el principal
como el MISMO motor (comparando `git rev-parse --git-common-dir` en vez del path
literal), sin exigir en esa funcion la disciplina de escritura.

## Contexto
El 2026-07-09 el mutation-verify del Builder de WOT-2026-019f colisiono con un
commit de CTL-2026-012j en el MISMO checkout detached del motor (compartido por
dos sesiones en paralelo) y se perdio el trabajo del Builder. La infraestructura
de aislamiento (worktree `_dev`, rama `main`, escritura; principal detached,
solo consumo) ya existe (`scripts/setup_dev_worktree.ps1`, QUICKSTART 0d) pero
no esta enforced en el arranque de los agentes: nada bloquea trabajar un ticket
`WOT` desde el principal.

Ademas, se descubrio en vivo que `prefix_resolver.py::guard()` (l.204-237) ya
"protege" el prefijo `WOT`, pero de forma incorrecta para esta topologia: compara
`cwd.resolve()` contra `resolved.resolve()` (`resolved` = `motor_root`, l.230), y
para `WOT` eso siempre resuelve al checkout PRINCIPAL (`resolve_prefix`, l.146-147:
`if prefix == WOT_PREFIX: return motor_root`, y `motor_root` es donde vive
`.agent/agent_controller.py`, que en este arbol es el checkout principal). Por
tanto, ejecutar `prefix_resolver.py --guard WOT-XXX` desde `_dev` da
"Prefix mismatch" / exit 1 -- exactamente el worktree donde SI se debe trabajar
-- mientras que ejecutarlo desde el principal (donde NO se debe escribir) da
exit 0. Es una contradiccion con la topologia real: el guard existente manda al
lugar equivocado.

## Configuracion Privada Requerida
Ninguna. No se necesitan credenciales ni archivos en `privada/`.

## Decision de alcance (fijada por el usuario 2026-07-09, vinculante)
- Script nuevo `scripts/check_worktree_topology.py`: unico lugar donde vive la
  disciplina de escritura ("WOT debe trabajarse en `_dev` rama `main`; el
  principal detached es solo consumo").
- Fix ESTRECHO de `prefix_resolver.py::guard()`: SOLO la rama `prefix == WOT`.
  Sustituye la comparacion de `cwd`/`resolved` por path literal por una
  comparacion de `git rev-parse --git-common-dir` resuelto a ruta absoluta en
  ambos lados (confirma que cwd y `motor_root` son worktrees del MISMO repo
  git). En esa rama, `guard()` NO exige `_dev`/rama `main`: solo verifica "es
  el motor" (lo que ya hacia para otros prefijos), no la disciplina de
  escritura.
- Destinos (`prefix != WOT`, p.ej. `CTL`/`EXF`) en `prefix_resolver.guard()`:
  CERO cambios de comportamiento.
- La disciplina de escritura vive EXCLUSIVAMENTE en `check_worktree_topology.py`.

## Verificacion en vivo (git-common-dir, comando literal ejecutado 2026-07-09)
Desde `_dev` (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev`):
```
git rev-parse --git-common-dir
-> C:/Users/fdl/Proyectos_Python/orquestador_de_agentes/.git
```
Desde el principal (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes`):
```
git rev-parse --git-common-dir
-> .git
```
**BUG DE FORMULA DESCARTADO (verificado en vivo, reproducido por el
Orquestador): `Path(raw_output).resolve()` NO sirve.** Cuando el raw es
relativo (caso del principal: `.git`), `Path(".git").resolve()` lo resuelve
contra el **cwd del PROCESO Python que ejecuta el guard**, NO contra el
directorio del `-C <path>` que se le paso a git. Si el guard corre con
cwd=`_dev` (el caso real de un Builder trabajando en `_dev`), `Path(".git").resolve()`
del lado "principal" da `..._dev\.git` (el `.git` de `_dev`, WRONG), nunca
`...orquestador_de_agentes\.git`. Los dos lados NUNCA coinciden con esta
formula: el MATCH es `False` siempre que cwd != directorio consultado, que es
precisamente el caso de uso real del guard. Con esta formula el fix es
INALCANZABLE (el DoD exige exit 0 desde `_dev`, y la formula rota da exit 1).

**FORMULA CORRECTA (verificada en vivo, MATCH=True):**
```
git -C <path> rev-parse --path-format=absolute --git-common-dir
```
Este flag (`--path-format=absolute`, disponible en git >= 2.31) hace que git
mismo devuelva SIEMPRE una ruta absoluta, sin depender del cwd del proceso que
invoca el comando:
```
git -C "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev" rev-parse --path-format=absolute --git-common-dir
-> C:/Users/fdl/Proyectos_Python/orquestador_de_agentes/.git
git -C "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes" rev-parse --path-format=absolute --git-common-dir
-> C:/Users/fdl/Proyectos_Python/orquestador_de_agentes/.git
```
Ambos lados dan el MISMO string; `Path(...).resolve()` sobre cada resultado
(para normalizar separadores/mayusculas de unidad en Windows) sigue siendo
correcto y necesario, pero YA NO depende del cwd del proceso porque el propio
git resuelve la ruta antes de imprimirla.

**NO usar `--absolute-git-dir`:** ese flag da el git-dir de la WORKTREE
enlazada (`.git/worktrees/<nombre>` dentro del repo principal), no el
common-dir compartido; comparar por ese valor NUNCA coincide entre worktrees
hermanas (cada una tiene su propio subdirectorio `worktrees/<nombre>`) y
reintroduce el mismo bug por otra via.

**Nota critica para el Builder:** el output crudo de `--git-common-dir` SIN el
flag `--path-format=absolute` difiere en FORMA (ruta absoluta vs relativa
`.git`) segun el worktree, Y `Path(...).resolve()` sobre un output relativo
resuelve contra el cwd del proceso, NO contra el directorio consultado. La
UNICA formula correcta es `git -C <path> rev-parse --path-format=absolute
--git-common-dir`, seguida de `Path(...).resolve()` por higiene de
normalizacion (no para corregir relatividad, que el flag ya elimina).

`git worktree list` (verificado en vivo, confirma que son 2 worktrees del MISMO
repo):
```
C:/Users/fdl/Proyectos_Python/orquestador_de_agentes     c344854 (detached HEAD)
C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_dev 2eb88a7 [main]
```

## Rutas exactas verificadas (evitar busqueda a ciegas)
- `scripts/prefix_resolver.py`: `discover_motor_root` (l.46), `resolve_prefix`
  (l.134, rama WOT en l.146-147), `guard` (l.204-237, comparacion problematica
  en l.230), `WOT_PREFIX = "WOT"` (l.38).
- `.agent/scope_gate.py:105`: `read_delivery_authority(content,
  default="repo_motor")`. Import: `.agent/` NO es un package Python; el
  patron real es `sys.path.insert(0, str(motor_root / ".agent"))` seguido de
  `import scope_gate` (ver `scripts/pip_audit_policy.py` l.10-17), NO
  `from .agent.scope_gate import ...` ni `.agent.scope_gate.X` dotted.
- `scripts/setup_dev_worktree.ps1`: existe: SOLO referenciar en mensajes de
  error del guard nuevo; el guard NUNCA lo invoca ni crea `_dev`.
- Cableado PRE: `prompts/orchestrator_destination_bootstrap.md` (seccion
  "Paso 0: Guard de prefijo (WOT-2026-020s)", l.14-31),
  `prompts/orchestrator_launch_builder.md` (seccion "Preflight
  (WOT-2026-009a)", l.8-32), y `prompts/orchestrator_session_bootstrap.md`
  (seccion "Paso 0" / "2. PREFLIGHT (topologia worktree-dev, WOT-2026-019m)",
  l.100-107 -- ya hace un chequeo MANUAL en prosa de la topologia worktree-dev
  para sesiones WOT; se cablea ahi la invocacion del guard nuevo para cerrar
  el eje orquestador-WOT del incidente, no solo destino/Builder).
- Cableado POST: `prompts/manager_review.md`, "Paso 1: Clasificacion" (l.30-45)
  o un paso nuevo inmediatamente despues -- NUNCA el "Paso 0" (l.15-28), que es
  CF-frozen y esta fuera de alcance de este ticket.
- Test existente de referencia (fix estrecho, no-regresion): `tests/unit/test_prefix_resolver.py`
  (clase de tests de `guard()`, l.157-196: `test_guard_wot_in_motor_passes` l.168-170,
  `test_guard_wot_in_destination_blocks` l.173-176, `test_guard_match_returns_zero`
  l.157-159, `test_guard_mismatch_blocks` l.162-165).
- Patron de test Windows-only de referencia: `tests/test_setup_dev_worktree_script.py`
  l.38-41 (`pytestmark = pytest.mark.skipif(sys.platform != "win32", reason=...)`
  a nivel de modulo).

## Files Likely Touched
- `scripts/check_worktree_topology.py` (nuevo)
- `scripts/prefix_resolver.py` (fix estrecho de `guard()`, rama `prefix == WOT`)
- `tests/unit/test_prefix_resolver.py` (tests de no-regresion del fix + test
  nuevo "guard WOT desde `_dev` -> exit 0")
- `tests/unit/test_check_worktree_topology.py` (nuevo; tests del guard nuevo)
- `prompts/orchestrator_destination_bootstrap.md` (cableado PRE, seccion "Paso 0")
- `prompts/orchestrator_launch_builder.md` (cableado PRE, seccion "Preflight")
- `prompts/orchestrator_session_bootstrap.md` (cableado PRE, seccion "Paso 0" /
  "2. PREFLIGHT", l.100-107; cierra el eje orquestador-WOT)
- `prompts/manager_review.md` (cableado POST, Paso 1 o paso nuevo tras el Paso 0
  CF-frozen; el Paso 0 mismo NO se toca)

## Forbidden Surfaces
- NO tocar `prompts/manager_review.md` seccion "Paso 0: Ambito de este review -
  CF-frozen vs implementacion" (l.15-28): es CF-frozen, fuera de alcance.
- NO tocar `scripts/setup_dev_worktree.ps1` ni el modelo de ramas existente.
- NO modificar `resolve_prefix()` ni `discover_motor_root()`: el fix es
  exclusivamente dentro de `guard()`.
- NO tocar el comportamiento de `guard()` para prefijos distintos de `WOT`.

## Non-goals
- NO un hook que bloquee commits (enforcement duro; el preflight ya previene el
  dano real).
- NO cambiar `setup_dev_worktree.ps1` ni el modelo de ramas (ya correcto).
- NO que el guard nuevo CREE `_dev` automaticamente (avisa, no crea; decision
  del usuario).
- NO derivar WOT->workspace por `ticket_prefix` del link (es null en el link del
  workspace; se deriva por `motor_root`/`discover_motor_root`).
- NO tocar el flujo de destinos que ya funciona (CTL/EXF en `prefix_resolver.guard()`
  quedan bit a bit identicos en comportamiento).
- NO leer `AGENT_PROJECT_ROOT` directo: usar `discover_motor_root` (cadena de
  precedencia link > `AGENT_PROJECT_ROOT`).

## Decision Arquitectonica

### 1. `check_worktree_topology.py` -- interfaz y logica
CLI: `python scripts/check_worktree_topology.py --ticket <TICKET_OR_PROJECT>
[--motor-root <PATH>] [--project-root <PATH>] [--allow-diagnostic]` (o env
`WORKTREE_GUARD_BYPASS=1` equivalente a `--allow-diagnostic`). `--project-root`
es el workspace ACTIVO de la sesion (por defecto `Path.cwd()` si se omite,
pero en el caso WOT real el workspace activo -- `orquestador_de_agentes_workspace`
-- casi siempre es un directorio DISTINTO del `cwd` del motor -- `_dev` --
porque son 2 carpetas abiertas en paralelo; el llamador -- los prompts de
cableado -- DEBE pasar `--project-root` explicito con el workspace real de la
sesion, no confiar en el default).

Exit codes (4, tal como exige el DoD):
- `0`: topologia correcta para el prefijo (WOT en `_dev`/main CON workspace ==
  `orquestador_de_agentes_workspace`, o destino con motor detached + workspace
  == destino resuelto).
- `1`: topologia incorrecta (WOT en principal detached, o `_dev` no existe, o
  para WOT el workspace activo -- `--project-root` -- != `orquestador_de_agentes_workspace`,
  o para destino el workspace activo no coincide con el destino resuelto).
- `2`: incoherencia de contrato (prefijo vs `delivery_authority` del
  `work_plan.md` activo, cuando exista) o prefijo no resoluble.
- Con `--allow-diagnostic`/`WORKTREE_GUARD_BYPASS=1`: SIEMPRE exit 0, imprime el
  veredicto real (incluido lo que hubiera bloqueado) con un warning explicito
  `[DIAGNOSTIC MODE] veredicto real: <bloqueado/incoherente>, motivo: <texto>`.
  No se salta la regla de topologia, solo permite depurar el guard sin
  bloquear.

Logica (estructurada en 2 funciones separadas para evitar C901/complejidad
ciclomatica alta seguida de PERF203; NUNCA usar `# noqa` para silenciar
complejidad -- ver seccion Calidad). **Verificacion A (worktree del motor) Y
Verificacion B (workspace activo) son AMBAS obligatorias para WOT segun el
contrato (l.36, l.42-43, l.81-83); ninguna sustituye a la otra:**
- `_check_wot_topology(cwd, motor_root, project_root) -> tuple[int, str]`:
  rama exclusiva de `prefix == WOT`, recibe el `project_root` (workspace
  activo) ademas de `cwd`/`motor_root`. **Verificacion A (worktree del
  motor):** calcula `git -C <cwd> rev-parse --path-format=absolute
  --git-common-dir` y `git -C <motor_root> rev-parse --path-format=absolute
  --git-common-dir` (flag `--path-format=absolute` OBLIGATORIO: sin el, el
  raw output es relativo en el checkout principal y `Path(...).resolve()`
  lo resolveria contra el cwd del proceso, no contra el path consultado --
  ver seccion "Verificacion en vivo", BUG DE FORMULA DESCARTADO). Ambos
  resultados se pasan ademas por `Path(...).resolve()` como higiene de
  normalizacion (separadores, mayusculas de unidad Windows), no para corregir
  relatividad.
  Si no coinciden -> exit 2 ("no se puede determinar topologia: cwd no es
  worktree del mismo repo que motor_root"). Si coinciden: verifica
  `git -C <cwd> symbolic-ref --short HEAD` == `"main"` Y que el toplevel de
  `cwd` (`git -C <cwd> rev-parse --show-toplevel`) coincide con la ruta de
  ALGUNA entrada de `git worktree list --porcelain` (ejecutado con `-C
  <motor_root>`) cuyo nombre de directorio termine en `_dev` (sufijo
  comparado sobre el basename real de esa entrada de worktree, NO un string
  hardcodeado del nombre del repo). Si la rama no es `main` o el toplevel no
  coincide con esa entrada `_dev` -> exit 1, mensaje con instruccion exacta
  ("Ticket WOT escribe en el MOTOR: usa la worktree _dev (rama main), no el
  checkout principal (detached=consumo). Ver scripts/setup_dev_worktree.ps1.").
  Caso borde `_dev` no creada (ninguna entrada de `git worktree list` con
  sufijo `_dev`) -> exit 1, mensaje ("Crea la worktree _dev:
  .\scripts\setup_dev_worktree.ps1" -- SOLO avisa, no la ejecuta el guard).
  **Verificacion B (workspace activo), SOLO si la Verificacion A dio exit 0**
  (no tiene sentido verificar el workspace si el worktree del motor ya fallo;
  se reporta el primer bloqueo encontrado, mensaje mas accionable): deriva el
  workspace esperado escaneando `parent(motor_root)` (mismo `search_root` que
  usa `prefix_resolver.scan_links`; reusar esa funcion o la logica equivalente
  de `resolve_by_project_name`, l.160-184 de `prefix_resolver.py`) por el link
  `motor_destination_link.json` cuyo campo `destination_id ==
  "orquestador_de_agentes_workspace"` (NO por `ticket_prefix`, que es `null`
  en ese link -- verificado en disco: `.agent/config/motor_destination_link.json`
  del workspace tiene `"ticket_prefix": null, "destination_id":
  "orquestador_de_agentes_workspace"`). Si no se encuentra ese link -> exit 2
  ("no se pudo derivar el workspace esperado para WOT: falta el link con
  destination_id == orquestador_de_agentes_workspace"). Si
  `project_root.resolve() != <workspace_esperado>.resolve()` -> exit 1,
  mensaje literal del contrato (l.43): "Ticket WOT necesita el workspace
  orquestador_de_agentes_workspace, no <project_root>." Si coincide -> exit 0
  (topologia COMPLETA: worktree del motor Y workspace correctos).
- `_check_destination_topology(prefix, cwd, motor_root) -> tuple[int, str]`:
  rama exclusiva de `prefix != WOT`. Resuelve `resolved =
  prefix_resolver.resolve_prefix(prefix, motor_root)`. Si `resolved is None`
  -> exit 2 ("prefijo desconocido: <prefix>"). Si `cwd.resolve() !=
  resolved.resolve()` -> exit 1 ("Ticket <PREFIX> necesita el workspace
  <resolved>, no <cwd>."). Si coincide -> exit 0 (el motor detached es lo
  esperado; NO se exige `_dev` para destinos).
- `main(argv)`: parsea `--ticket`, `--project-root` (workspace activo; default
  `Path.cwd()` si se omite), extrae el prefijo con
  `prefix_resolver.extract_prefix` (reusar la funcion existente, no
  reimplementar el regex), descubre `motor_root` con
  `prefix_resolver.discover_motor_root(Path.cwd())` (o `--motor-root`
  explicito), y despacha a la funcion correspondiente segun `prefix == "WOT"`,
  pasando `project_root` a `_check_wot_topology` (rama WOT) o a
  `_check_destination_topology` como el `cwd` de esa funcion (rama destino:
  el "cwd" que compara contra `resolved` en esa rama ES el workspace activo,
  no el `cwd` del proceso).
  Cuando exista un `work_plan.md` activo legible en
  `.agent/collaboration/work_plan.md`, cruza `delivery_authority` (via
  `scope_gate.read_delivery_authority`, importado con el patron real del repo
  -- `.agent/` NO es un package Python importable como `.agent.scope_gate`;
  usar `sys.path.insert(0, str(motor_root / ".agent"))` seguido de
  `import scope_gate`, exactamente el patron de `scripts/pip_audit_policy.py`
  l.10-17) contra el prefijo: `WOT` debe
  traer `repo_motor`, cualquier otro prefijo debe traer `repo_destino`; si
  divergen -> exit 2 ("incoherencia de contrato: prefijo <X> vs
  delivery_authority <Y>"), SIN ejecutar el resto de la logica de topologia (el
  chequeo de incoherencia de contrato precede al de topologia). Si no hay
  `work_plan.md` legible, se omite ese cruce (no es bloqueante: el guard corre
  en preflight, antes de que exista necesariamente un plan).
  El flag `--allow-diagnostic`/env envuelve el resultado final: calcula el
  exit code real, lo imprime con el prefijo `[DIAGNOSTIC MODE]` si aplica, y
  fuerza el return a 0 sea cual sea el resultado real.

### 2. Fix de `prefix_resolver.py::guard()`
Dentro de `guard()` (l.204-237), la unica rama que cambia es cuando `prefix ==
WOT_PREFIX` (usar la constante ya existente, no un string literal nuevo). En
esa rama, en vez de `cwd.resolve() != resolved.resolve()` (l.230), comparar
`git -C <path> rev-parse --path-format=absolute --git-common-dir` de `cwd`
contra el de `motor_root` (flag `--path-format=absolute` OBLIGATORIO -- ver
seccion "Verificacion en vivo", BUG DE FORMULA DESCARTADO: sin el flag, el
raw output relativo del principal resuelto con `Path(...).resolve()` se
resuelve contra el cwd del PROCESO, no contra `motor_root`, y el MATCH nunca
es `True`), ambos resultados pasados ademas por `Path(...).resolve()` como
higiene de normalizacion (usando `subprocess.run(["git", "-C", str(<path>),
"rev-parse", "--path-format=absolute", "--git-common-dir"],
capture_output=True, text=True, check=False)` -- **`check=False`, NUNCA
`check=True`**, ver degradado abajo). Si los dos `git-common-dir` resueltos no
coinciden -> mismatch, exit 1 (mismo formato de mensaje que ya existe,
adaptado). Todas las demas ramas de `guard()` (prefijos distintos de `WOT`,
`resolved is None`, `ValueError` de `extract_prefix`) permanecen exactamente
iguales (cero diff fuera de la rama `prefix == WOT_PREFIX`).

**Degradado obligatorio si `git rev-parse` falla (fail-closed, NUNCA crash,
NUNCA exit 0):** el subprocess se invoca con `check=False` e inspecciona
`returncode` explicitamente (o equivalente `try/except` capturando
`subprocess.CalledProcessError` y `FileNotFoundError`, si se usa `check=True`
en un bloque envuelto -- pero la forma preferida y mas simple es
`check=False` + inspeccion de `returncode`). Causas posibles: `cwd` o
`motor_root` no es un repo git (returncode != 0, stderr tipico "not a git
repository"), o el ejecutable `git` no esta en PATH (`FileNotFoundError`). En
CUALQUIERA de esos casos, para la rama `prefix == WOT_PREFIX`: **no se puede
verificar que cwd y motor_root son el mismo repo -> tratar como mismatch ->
exit 1**, exactamente el mismo camino que un mismatch confirmado. NO lanzar la
excepcion sin capturar (crash inaceptable en un guard de preflight), NO
devolver 0 (un guard que no puede verificar la topologia debe bloquear, no
dejar pasar -- fail-closed). El mensaje de error en ese caso debe distinguir
la causa ("no se pudo determinar git-common-dir de <cwd|motor_root>: <detalle
returncode/stderr o 'git no encontrado en PATH'>") del mensaje de mismatch
confirmado, para que el usuario no confunda "no es un repo git" con
"topologia incorrecta pero SI es un repo git".

### 3. Cableado
- PRE en `prompts/orchestrator_destination_bootstrap.md`: anadir, dentro de la
  seccion existente "Paso 0: Guard de prefijo (WOT-2026-020s)" (l.14-31), un
  sub-paso que invoque `check_worktree_topology.py --ticket <TICKET_O_PROYECTO>`
  inmediatamente despues de la llamada a `prefix_resolver.py --guard`
  (misma logica de exit codes 0/1/2, mismo "detente si no es 0").
- PRE en `prompts/orchestrator_launch_builder.md`: anadir, dentro de la seccion
  "Preflight (WOT-2026-009a)" (l.8-32), antes de "Rol y limites" (l.34), un
  parrafo que exija correr `check_worktree_topology.py --ticket {{TICKET_ID}}`
  y detenerse con `WORKTREE_TOPOLOGY_VIOLATION` si el exit code no es 0.
- POST en `prompts/manager_review.md`: anadir, en "Paso 1: Clasificacion"
  (l.30-45) o como paso nuevo inmediatamente despues (nunca en el "Paso 0"
  CF-frozen, l.15-28), una verificacion de que el Builder respeto la topologia:
  releer `check_worktree_topology.py --ticket {{TICKET_ID}} --motor-root
  <repo_motor>` contra el estado actual del repo y confirmar exit 0; si no,
  `CHANGES` con blocker "topologia de worktree violada".

## Mecanismo de Mutation (DoD obligatorio, worktree/checkout REAL)
El mutation-verify NO usa mocks de `git symbolic-ref` (evita mock-drift: un
mock puede quedar desincronizado del comportamiento real de git). Usa el
worktree principal detached REAL (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes`,
ya existente) y la worktree `_dev` REAL (`C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev`,
ya existente, el propio arbol de trabajo) como fixtures del mutation, ademas de
los tests unitarios con fixtures sinteticas en `tmp_path` (para los casos que no
dependen de la topologia real de esta maquina, ej. caso borde `_dev` no creada,
que se simula con un `tmp_path` sin la worktree, NUNCA borrando o alterando la
`_dev` real).

Secuencia literal a ejecutar y registrar en `execution_log.md`:

```
mutation-verify: prefix_resolver.guard() -- fix del bug real (caso principal)
  sin_fix (revertir temporalmente scripts/prefix_resolver.py a la version
  pre-fix, ej. via `git show HEAD:scripts/prefix_resolver.py` a un archivo
  temporal fuera del repo o `git stash` del fix, ejecutando el script
  revertido):
    command: python scripts/prefix_resolver.py --guard WOT-2026-021g --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes"
    (ejecutado con cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev")
    exit_code: 1   # el bug: _dev rechazada por comparacion de path literal
  con_fix:
    command: <mismo comando, con el fix restaurado>
    exit_code: 0   # _dev reconocida como el mismo motor via git-common-dir

mutation-verify: check_worktree_topology.py -- caso del bug (motor detached + WOT)
  sin_check (documentar que hoy NADA bloquea esto; no hay "sin_fix" de codigo
  previo porque el script es nuevo -- el "antes" es la ausencia del guard):
    command: python scripts/check_worktree_topology.py --ticket WOT-2026-021g --motor-root "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes"
    (ejecutado con cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes" -- el PRINCIPAL detached)
    exit_code: 1   # DEBE bloquear: exactamente el caso que causo la perdida de trabajo de 019f
  con_dev (mismo comando, cwd = "C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev"):
    exit_code: 0   # _dev, rama main: pasa
```

Nota de terminologia: como `check_worktree_topology.py` es un script NUEVO, no
existe un "sin_fix" en el sentido de revertir un commit; el par que demuestra
la barrera es "sin el guard el bug pasa desapercibido" (documentado, no
ejecutable como comando aislado: es la ausencia de la herramienta) vs "con el
guard nuevo, el caso real del bug (principal detached + WOT) da exit 1". El par
ejecutable y verificable en ambos sentidos es el de `prefix_resolver.guard()`
(bug real revertible: comparacion por path literal vs por git-common-dir) y el
de topologia inversa de `check_worktree_topology.py` (exit 1 en principal, exit
0 en `_dev`, ambos ejecutables hoy mismo sobre los 2 worktrees reales). Registrar
AMBOS pares en `execution_log.md`.

## Plan de Implementacion

### Fase 1: Fix estrecho de `prefix_resolver.py::guard()`
- **Archivo:** `scripts/prefix_resolver.py`
- **Accion:** Modificar
- **Descripcion:** Dentro de `guard()` (l.204-237), en la rama donde `prefix ==
  WOT_PREFIX` unicamente, sustituir la comparacion `cwd.resolve() !=
  resolved.resolve()` por una comparacion de `git -C <path> rev-parse
  --path-format=absolute --git-common-dir` (flag OBLIGATORIO; ver "Verificacion
  en vivo", BUG DE FORMULA DESCARTADO) en ambos lados (`cwd` y `motor_root`),
  segun la Decision Arquitectonica seccion 2. Todas las demas ramas de `guard()`
  (prefijos distintos de WOT) quedan bit a bit identicas. **Degradado
  obligatorio:** el subprocess de cada `git rev-parse --git-common-dir` usa
  `check=False` (o try/except equivalente) e inspecciona el resultado
  explicitamente; si `cwd` o `motor_root` no es un repo git (returncode != 0)
  o `git` no esta en PATH (`FileNotFoundError`), el resultado es **fail-closed:
  exit 1** (mismatch), nunca una excepcion sin capturar ni un exit 0. Ver
  Decision Arquitectonica seccion 2 para el detalle completo del mensaje de
  error por causa.
- **Riesgo:** Medio (funcion compartida por todos los prefijos; el cambio esta
  aislado a una rama condicional, pero un error de logica puede romper el
  guard existente para destinos; el degradado mal implementado puede crashear
  un guard de preflight universal)
- **Criterio de Aceptacion:** `git diff scripts/prefix_resolver.py` muestra
  cambios SOLO dentro del cuerpo de `guard()`, en la rama `prefix ==
  WOT_PREFIX`; ninguna otra funcion ni rama cambia. `ast.parse` del archivo no
  lanza excepcion. Ademas: invocar `guard()` con `prefix="WOT"` y un `cwd` que
  NO es un repo git (directorio `tmp_path` plano sin `git init`) devuelve `1`
  de forma determinista, sin lanzar `CalledProcessError` ni ninguna otra
  excepcion no capturada (verificado por el test nuevo de Fase 2 "cwd no es
  repo git en rama WOT").
- **Si falla:** revertir el cambio y escalar al Manager con el traceback exacto

### Fase 2: Tests de no-regresion y del caso corregido en `test_prefix_resolver.py`
- **Archivo:** `tests/unit/test_prefix_resolver.py`
- **Accion:** Modificar
- **Descripcion:** `_make_tree(tmp_path)` (l.56-73) es una factory COMPARTIDA
  usada por ~15 tests del archivo: los de `resolve_prefix`, los 8 de `guard`
  (l.152-215) Y los de `scan_links`. **NO modificar `_make_tree` in-place.**
  Crear un helper NUEVO y SEPARADO (p.ej. `_make_git_tree(tmp_path)`,
  reutilizando el patron `init_git_repo` de `tests/test_pre_handoff_guard.py`
  como PUNTO DE PARTIDA, pero NO reutilizado tal cual: `init_git_repo` hace
  `git init` a secas, y el nombre de la rama por defecto depende de
  `init.defaultBranch` del entorno -- `main` en esta maquina, pero `master`
  en el runner CI (sin esa config), lo que romperia en false-RED el check
  `symbolic-ref == "main"` SOLO en CI. `_make_git_tree` DEBE forzar la rama
  explicitamente: `git init -b main` (preferido, git >= 2.28) o `git init`
  seguido de `git branch -M main` antes del primer commit, en el motor
  sintetico; la `_dev` sintetica se crea con `git worktree add -b main
  <ruta_dev> main` (worktree nueva sobre la rama `main` ya forzada) para que
  `symbolic-ref --short HEAD` en `_dev` de `main` de forma determinista en
  cualquier entorno (local Windows y CI Linux), no solo en esta maquina.
  Usado UNICAMENTE por los tests de la rama WOT que ahora invocan `git` real. Los tests existentes de `resolve_prefix`/`scan_links` y los 8
  tests de `guard()` (l.157-196) siguen usando `_make_tree` plano intacto, SIN
  `git init` y SIN modificar sus asserts.
  Anadir con `_make_git_tree`:
  1. Un test nuevo "guard WOT desde `_dev` -> exit 0":
     `guard("WOT-2026-XXXXx", cwd=<ruta _dev sintetica de _make_git_tree>,
     motor_root=<motor sintetico de _make_git_tree>) == 0`.
  2. Un test nuevo "cwd no es repo git en rama WOT -> exit 1 determinista (no
     crash)": `guard("WOT-2026-XXXXx", cwd=<tmp_path plano SIN git init>,
     motor_root=<motor sintetico CON git init>) == 1`, y asercion explicita de
     que NO se lanza ninguna excepcion (el test falla si `guard()` propaga
     `CalledProcessError` en vez de devolver `1`). Cubre el degradado
     fail-closed de la Fase 1 / Decision Arquitectonica seccion 2.
  Los 8 tests existentes de `guard()` (l.157-196:
  `test_guard_match_returns_zero`, `test_guard_mismatch_blocks`,
  `test_guard_wot_in_motor_passes`, `test_guard_wot_in_destination_blocks`,
  `test_guard_unknown_prefix_returns_2`, `test_guard_malformed_id_returns_2`,
  `test_guard_project_name_match`, `test_guard_project_name_mismatch_blocks`)
  usan `_make_tree` plano (sin `git init`); tras el fix, para la rama WOT eso
  activa el degradado fail-closed de la Fase 1 (ningun lado es repo git ->
  exit 1). Razonamiento explicito por que ninguno cambia de assert:
  - `test_guard_wot_in_motor_passes` (l.168-170): `cwd == motor_root`
    (mismo directorio, sin `git init`). El degradado fail-closed daria exit 1
    para un `cwd` generico sin git, pero aqui `cwd` Y `motor_root` son el
    MISMO path -- si el Builder implementa el degradado por-lado (git-common-dir
    de un lado falla -> exit 1 inmediato sin comparar), este test ROMPE (paso
    de 0 a 1) porque ninguno de los dos tiene `.git`. **Este test DEBE ganar
    `git init` en su fixture local (OBLIGATORIO, no opcional):** bajo el
    degradado fail-closed por-lado fijado en la Fase 1, sin `git init` el
    resultado seria `1` (degradado) en vez de `0` (mismo motor real) y el
    test romperia. Anadir `git init` real a la fixture local de este test
    unicamente (no a `_make_tree`), para que siga siendo un caso "mismo
    motor real" -> exit 0. Documentar en el diff por que este test especifico
    gana `git init` mientras los demas no.
  - `test_guard_wot_in_destination_blocks` (l.173-176): `cwd=exf` (destino,
    sin `git init`), `prefix=WOT` por lo que `resolved=motor` (sin `git
    init`). Con el fix, la rama WOT intenta obtener `git-common-dir` de
    ambos; ninguno es repo git -> degradado fail-closed -> exit 1. **Este
    test NO cambia de assert** (sigue esperando `1`): tanto en el
    comportamiento pre-fix (mismatch por path literal) como en el
    post-fix (degradado fail-closed por ausencia de git) el resultado
    coincide en exit 1, por razones distintas pero mismo exit code -- no
    hace falta tocar su fixture.
  - Los 6 tests restantes (`test_guard_match_returns_zero`,
    `test_guard_mismatch_blocks`, `test_guard_unknown_prefix_returns_2`,
    `test_guard_malformed_id_returns_2`, `test_guard_project_name_match`,
    `test_guard_project_name_mismatch_blocks`) usan prefijos distintos de
    `WOT` (`EXF`/`CTL`/`XYZ`/malformado/nombre de proyecto): caen en la rama
    `_check_destination_topology`-equivalente de `guard()`, que el fix NO
    toca. Sin cambio de comportamiento ni de fixture.
  NO mockear `subprocess.run` de git en ningun test nuevo (evita mock-drift,
  mismo criterio que el mutation).
- **Riesgo:** Medio (tests de git real son mas lentos y pueden ser fragiles en
  CI si no se crean los repos correctamente; mitigar con `tmp_path` real y
  limpieza automatica de pytest; riesgo adicional de mezclar `_make_git_tree`
  con `_make_tree` por descuido)
- **Criterio de Aceptacion:** `python -m pytest tests/unit/test_prefix_resolver.py -v`
  pasa completo, incluye los 2 tests nuevos (`_dev` via `_make_git_tree`, y
  "cwd no es repo git -> exit 1 determinista"); `_make_tree` (l.56-73) no
  tiene diff (`git diff` no muestra cambios en su cuerpo); los 8 tests
  existentes de `guard()` no cambian su assert final, salvo
  `test_guard_wot_in_motor_passes`, que DEBE ganar `git init` en su fixture
  local (OBLIGATORIO bajo el degradado fail-closed, razonado arriba)
  manteniendo el mismo assert `== 0`; comparar contra
  `git show HEAD:tests/unit/test_prefix_resolver.py` antes del ticket para
  confirmar que ningun otro assert cambio.
- **Si falla:** revertir Fase 1 y Fase 2 juntas, escalar al Manager con el log
  de fallo exacto

### Fase 3: Crear `scripts/check_worktree_topology.py`
- **Archivo:** `scripts/check_worktree_topology.py`
- **Accion:** Crear
- **Descripcion:** Implementar segun la Decision Arquitectonica seccion 1: CLI
  `--ticket`, `--motor-root` (opcional), `--project-root` (opcional, workspace
  activo), `--allow-diagnostic` (o env `WORKTREE_GUARD_BYPASS=1`); funciones
  `_check_wot_topology(cwd, motor_root, project_root)` (Verificacion A del
  worktree + Verificacion B del workspace, AMBAS obligatorias para WOT) y
  `_check_destination_topology` separadas (para no acumular complejidad
  ciclomatica en una sola funcion -- ver seccion Calidad); reusa
  `prefix_resolver.extract_prefix`, `prefix_resolver.discover_motor_root`,
  `prefix_resolver.resolve_prefix` (import, NO reimplementar); reusa
  `scope_gate.read_delivery_authority` para el cruce de incoherencia de
  contrato, importado con `sys.path.insert(0, str(motor_root / ".agent"))` +
  `import scope_gate` (patron real de `scripts/pip_audit_policy.py` l.10-17;
  `.agent/` NO es un package, `.agent.scope_gate` como dotted import NO
  funciona). Exit codes 0/1/2 segun la Decision Arquitectonica. Mensajes de
  error citan `scripts/setup_dev_worktree.ps1` solo como referencia (nunca lo
  invoca ni crea `_dev`).
- **Riesgo:** Alto (script nuevo que se cablea como preflight en 2 prompts;
  un falso positivo paraliza el arranque de agentes en toda sesion futura --
  de ahi el escape hatch `--allow-diagnostic` obligatorio en el DoD)
- **Criterio de Aceptacion:** `python scripts/check_worktree_topology.py --help`
  documenta `--ticket`, `--motor-root`, `--project-root`, `--allow-diagnostic`;
  ejecutar manualmente los 5 casos base (WOT en `_dev` + workspace correcto ->
  0; WOT en principal -> 1; WOT en `_dev` + workspace INCORRECTO -> 1; destino
  con workspace correcto -> 0; prefijo desconocido -> 2) reproduce el exit
  code esperado en cada caso
- **Si falla:** revertir el archivo nuevo (`git rm` o descartar), escalar al
  Manager con el caso concreto que no reproduce el exit code esperado

### Fase 4: Tests de `check_worktree_topology.py`
- **Archivo:** `tests/unit/test_check_worktree_topology.py`
- **Accion:** Crear
- **Descripcion:** Cubrir, con fixtures de `tmp_path` + `git init -b main`
  (o `git init` + `git branch -M main`) / `git worktree add -b main` reales
  (mismo helper `_make_git_tree` de la Fase 2, o un helper equivalente que
  fuerce la rama `main` explicitamente -- NO usar `init_git_repo` de
  `tests/test_pre_handoff_guard.py` sin ese forzado: su `git init` a secas
  depende de `init.defaultBranch`, `main` en esta maquina pero `master` en
  el runner CI sin esa config, lo que romperia en false-RED SOLO en CI el
  check `symbolic-ref == "main"` de los casos (a)/(c)/(h); NO mockear `git
  symbolic-ref` ni `subprocess` de git):
  (a) WOT + `_dev` sintetica (rama `main`) + `--project-root` ==
      workspace sintetico con link `destination_id ==
      "orquestador_de_agentes_workspace"` -> exit 0 (Verificacion A y B
      ambas correctas);
  (b) WOT + principal sintetico (detached) -> exit 1, mensaje cita
      `setup_dev_worktree.ps1` (falla en Verificacion A, no llega a evaluar B);
  (c) WOT + `_dev` no existe (`git worktree list` sin entrada `_dev`) -> exit 1,
      mensaje "Crea la worktree _dev";
  (d) destino conocido (prefijo sintetico tipo `EXF`/`CTL` con link de
      `motor_destination_link.json` en `tmp_path`) con motor detached +
      workspace == destino resuelto -> exit 0;
  (e) destino conocido con workspace activo != destino resuelto -> exit 1;
  (f) prefijo desconocido -> exit 2;
  (g) incoherencia de contrato (work_plan.md sintetico con
      `delivery_authority: repo_destino` pero prefijo `WOT`) -> exit 2;
  (h) `--allow-diagnostic` (o `WORKTREE_GUARD_BYPASS=1`) sobre el caso (b) ->
      exit 0, stdout/stderr contiene `[DIAGNOSTIC MODE]` y el veredicto real
      (bloqueado);
  (i) **WOT + `_dev` sintetica correcta (Verificacion A pasa) + `--project-root`
      apuntando a un directorio sintetico DISTINTO del link
      `orquestador_de_agentes_workspace` (workspace incorrecto) -> exit 1,
      mensaje literal del contrato: "Ticket WOT necesita el workspace
      orquestador_de_agentes_workspace, no <project_root>."** Cubre el
      BLOCKER 2 (Verificacion B) de forma aislada de la Verificacion A.
- **Riesgo:** Medio (fixtures de git real son mas lentas; el caso (c) requiere
  simular ausencia de `_dev` sin tocar la `_dev` real de esta sesion)
- **Criterio de Aceptacion:** `python -m pytest tests/unit/test_check_worktree_topology.py -v`
  pasa completo, con los 9 casos (a)-(i) como tests individuales nombrados
  explicitamente por el caso que cubren
- **Si falla:** revertir Fase 3 y Fase 4 juntas, escalar al Manager con el caso
  que no reproduce

### Fase 5: Mutation-verify con worktrees reales
- **Archivo:** ninguno (verificacion transitoria; usa los worktrees reales
  existentes de esta maquina, sin modificarlos)
- **Accion:** Verificar
- **Descripcion:** Ejecutar la secuencia literal de la seccion "Mecanismo de
  Mutation" de este plan: (1) `prefix_resolver.guard()` sin el fix (revertido
  temporalmente en una copia aislada o via `git stash`/checkout parcial en
  `tmp_path`, NUNCA en el arbol de trabajo real sin revertir despues) vs con el
  fix, ambos ejecutados con cwd real = `_dev`; (2) `check_worktree_topology.py`
  ejecutado con cwd real = principal detached (exit esperado 1) y cwd real =
  `_dev` (exit esperado 0). Restaurar cualquier archivo revertido
  temporalmente antes de continuar.
- **Riesgo:** Medio (opera sobre los worktrees reales de la maquina; debe
  revertir cualquier estado temporal antes de dejar la sesion)
- **Criterio de Aceptacion:** los 2 pares `mutation-verify` (4 comandos, 4 exit
  codes) quedan registrados literalmente en `execution_log.md` con el formato
  exacto de la seccion "Mecanismo de Mutation"; `git status --short` en ambos
  worktrees queda limpio despues de la verificacion (ningun revert temporal
  sobrevive)
- **Si falla:** el fix o el guard nuevo no son una barrera genuina; revisar el
  mecanismo y escalar al Manager antes de marcar READY_FOR_REVIEW

### Fase 6: Cableado PRE en los 3 prompts de bootstrap/launch/sesion
- **Archivo:** `prompts/orchestrator_destination_bootstrap.md`,
  `prompts/orchestrator_launch_builder.md`,
  `prompts/orchestrator_session_bootstrap.md`
- **Accion:** Modificar
- **Descripcion:** Segun la Decision Arquitectonica seccion 3: anadir en
  `orchestrator_destination_bootstrap.md` un sub-paso dentro del "Paso 0: Guard
  de prefijo" (l.14-31) que invoque `check_worktree_topology.py --ticket
  <TICKET_O_PROYECTO> --project-root <workspace_activo>` inmediatamente
  despues del `prefix_resolver.py --guard` existente, con la misma politica de
  exit codes (0 continua, 1/2 detente y reporta). En
  `orchestrator_launch_builder.md`, anadir dentro de "Preflight
  (WOT-2026-009a)" (l.8-32), antes de "Rol y limites" (l.34), la misma
  invocacion con `{{TICKET_ID}}` y `--project-root <repo_destino>`,
  deteniendose con `WORKTREE_TOPOLOGY_VIOLATION` si el exit code no es 0. En
  `orchestrator_session_bootstrap.md`, anadir dentro de "2. PREFLIGHT
  (topologia worktree-dev, WOT-2026-019m)" (l.100-107) la misma invocacion
  para el ticket WOT activo con `--project-root
  orquestador_de_agentes_workspace` (o la ruta real del workspace de la
  sesion), reemplazando/complementando el chequeo manual en prosa que ya
  existe ahi con la version programatica del guard nuevo.
- **Riesgo:** Bajo (cambio de prosa en 3 prompts Markdown; no ejecuta codigo,
  no tiene gates de pytest/ruff)
- **Criterio de Aceptacion:** los 3 archivos contienen la invocacion literal de
  `check_worktree_topology.py --ticket ... --project-root ...` con la politica
  de exit codes 0/1/2 descrita; encoding guard (ver Fase 8) pasa sobre los 3
- **Si falla:** revertir el cambio de prosa, escalar al Manager

### Fase 7: Cableado POST en `manager_review.md`
- **Archivo:** `prompts/manager_review.md`
- **Accion:** Modificar
- **Descripcion:** Anadir, en "Paso 1: Clasificacion" (l.30-45) o como paso
  nuevo inmediatamente despues de el (nunca dentro del "Paso 0: Ambito de este
  review" CF-frozen, l.15-28, que NO se toca), una verificacion de cumplimiento:
  el Manager releera `check_worktree_topology.py --ticket {{TICKET_ID}}
  --motor-root <repo_motor>` contra el estado actual del repo tras la entrega
  del Builder; si el exit code no es 0, el veredicto es `CHANGES` con blocker
  "topologia de worktree violada durante la implementacion". Esto es
  verificacion de CUMPLIMIENTO posterior al trabajo del Builder, no prevencion
  (la prevencion ya esta en Fase 6).
- **Riesgo:** Bajo (cambio de prosa en un prompt; no toca el Paso 0 CF-frozen)
- **Criterio de Aceptacion:** `prompts/manager_review.md` contiene la
  verificacion de topologia fuera del Paso 0 (verificable por posicion de
  linea: despues de l.28); el Paso 0 original (l.15-28) queda bit a bit
  identico (`git diff` no muestra cambios en ese rango)
- **Si falla:** revertir el cambio, escalar al Manager

### Fase 8: Calidad, encoding y no-regresion global
- **Archivo:** todos los tocados; toda la suite
- **Accion:** Verificar
- **Descripcion:** (a) `ruff check scripts/prefix_resolver.py
  scripts/check_worktree_topology.py tests/unit/test_prefix_resolver.py
  tests/unit/test_check_worktree_topology.py` con 0 errores -- si el guard
  nuevo genera una advertencia de complejidad (C901) por ramas anidadas,
  reestructurar en funciones mas pequenas (ya previsto en la Decision
  Arquitectonica seccion 1 con `_check_wot_topology`/`_check_destination_topology`);
  NUNCA silenciar con `# noqa`. (b) `uv run ruff format --check` sobre los
  mismos archivos Python. (c) Encoding guard sobre los 3 prompts tocados y el
  script nuevo: UTF-8 limpio, sin mojibake ni em-dash/comillas curvas (usar
  `-`/`"` ASCII), verificado con el comando de la seccion "Check de encoding"
  de `prompts/orchestrator_launch_builder.md`. (d)
  `python scripts/run_pytest_safe.py -- --level all` con exit code 0 (blast
  radius: el fix toca infraestructura compartida -- `prefix_resolver.py` lo
  usan tanto WOT como destinos). (e) `python .agent/agent_controller.py
  --validate --json --force` con 0 errores.
- **Riesgo:** Medio (blast radius de tocar `prefix_resolver.py`, usado por
  otros flujos de destino)
- **Criterio de Aceptacion:** los 5 comandos de la Descripcion terminan con el
  resultado indicado en cada caso
- **Si falla:** aislar si el fallo viene del fix de Fase 1 o de una
  interaccion con otro modulo; revertir la fase minima necesaria y escalar al
  Manager con el log de fallo exacto

## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Guard nuevo separado + fix estrecho de `prefix_resolver.guard()` | Separa responsabilidades: `prefix_resolver` sigue siendo "es el motor correcto", el guard nuevo es "disciplina de escritura"; cambio de riesgo acotado en el codigo existente | Dos puntos de verificacion en vez de uno; requiere cablear 2 guards en preflight | Aceptada (decision del usuario) |
| Reescribir `prefix_resolver.guard()` para incluir toda la logica de `_dev`/rama main | Un solo guard, menos cableado | Mezcla dos responsabilidades distintas (identidad del repo vs disciplina de escritura); mayor riesgo de romper destinos existentes | Descartada |
| Comparar por path literal normalizado (resolver symlinks) en vez de `git-common-dir` | Mas simple, sin invocar `git` externo | No captura la relacion "worktree del mismo repo": dos checkouts independientes del mismo repo (via `git clone`) tendrian paths distintos y `git-common-dir` distinto, que es precisamente la distincion correcta; un path-diff no distingue worktree-hermano de clon-independiente | Descartada |
| Mockear `git symbolic-ref`/`git rev-parse` en los tests | Tests mas rapidos, sin overhead de `git init` real | Mock-drift: un mock puede quedar desincronizado del comportamiento real de git y dar falsos verdes (leccion de memoria: "mutation-verify con worktree/checkout real, no mocks") | Descartada |
| Degradado fail-closed (`git rev-parse` falla -> exit 1) vs fail-open (exit 0) vs propagar excepcion | Fail-closed: un guard de preflight que no puede verificar topologia debe bloquear, no dejar pasar ni crashear; consistente con el resto del guard (mismatch = bloqueo) | Fail-closed puede bloquear un `cwd` legitimo si `git` no esta disponible por una razon ajena a la topologia (ej. PATH mal configurado); mitigado por el escape hatch `--allow-diagnostic` del guard nuevo (no de `prefix_resolver.guard()`, que no lo tiene, pero el caso practico -- `cwd` real siempre es un repo git -- hace este escenario improbable) | Aceptada (fail-closed) |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|---------------------|
| Bajo | Rutinaria (prosa en prompts, tests nuevos aislados) | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion (blast radius compartido, fixtures de git real) | Intentar 2 veces, escalar si dudas |
| Alto | Critica (guard nuevo cableado como preflight universal) | Escalar al primer fallo |

## Calidad
- `ruff check scripts/prefix_resolver.py scripts/check_worktree_topology.py tests/unit/test_prefix_resolver.py tests/unit/test_check_worktree_topology.py` con 0 errores (Fase 8a). Si aparece complejidad ciclomatica alta en el guard nuevo, reestructurar en funciones mas pequenas ANTES de considerar `# noqa`; `# noqa` no es una opcion valida de cierre para este ticket.
- `uv run ruff format --check` sobre los mismos archivos Python (Fase 8b)
- Encoding guard sobre `prompts/orchestrator_destination_bootstrap.md`, `prompts/orchestrator_launch_builder.md`, `scripts/check_worktree_topology.py` (Fase 8c)
- `python scripts/run_pytest_safe.py -- --level all` con exit code 0 (Fase 8d)
- `python .agent/agent_controller.py --validate --json --force` con 0 errores (Fase 8e)
- mutation-verify de Fase 5 registrado en `execution_log.md` con los 2 pares de comandos y exit codes literales (Mecanismo de Mutation)
- Todo test que dependa de layout Windows real (paths con `_dev`/principal reales de esta maquina, si algun test los referenciara directamente) debe usar `pytest.mark.skipif(sys.platform != "win32", ...)` a nivel de modulo, patron de `tests/test_setup_dev_worktree_script.py:38-41`. Los tests de Fase 2 y Fase 4 usan `tmp_path` sintetico (portable), no deberian depender del layout real de esta maquina; si algun caso SI lo hiciera, marcarlo Windows-only explicitamente.

## Criterios de Aceptacion Global
- [ ] `scripts/check_worktree_topology.py` existe, expone `--ticket`, `--motor-root`, `--project-root`, `--allow-diagnostic`/`WORKTREE_GUARD_BYPASS=1`, y produce los 4 exit codes (0/1/2 + diagnostic-siempre-0) segun los casos del DoD del contrato
- [ ] Para WOT, `check_worktree_topology.py` implementa AMBAS verificaciones del contrato: Verificacion A (worktree del motor: `_dev`/rama `main`) Y Verificacion B (workspace activo == `orquestador_de_agentes_workspace`, derivado por `destination_id` del link, NO por `ticket_prefix`); `--project-root` con workspace incorrecto -> exit 1 con el mensaje literal del contrato (test caso (i) de Fase 4)
- [ ] `prefix_resolver.py::guard()` reconoce `_dev` y el principal como el mismo motor via `git -C <path> rev-parse --path-format=absolute --git-common-dir` (flag `--path-format=absolute` obligatorio; la formula sin flag esta descartada por bug reproducido en vivo), SOLO en la rama `prefix == WOT`; el resto de `guard()` queda bit a bit identico
- [ ] `prefix_resolver --guard WOT-XXX` desde `_dev` -> exit 0 (ya no falla por path literal)
- [ ] `check_worktree_topology --ticket WOT-XXX` desde el principal detached -> exit 1
- [ ] Destinos (CTL/EXF) en `prefix_resolver.guard()` sin cambio de comportamiento (los 8 tests existentes de `tests/unit/test_prefix_resolver.py` l.157-196 pasan sin modificar su assert final; `test_guard_wot_in_motor_passes` DEBE ganar `git init` en su fixture local, razonado en Fase 2, manteniendo su assert `== 0`)
- [ ] `guard()` con `cwd` que no es repo git en la rama WOT devuelve `1` de forma determinista (fail-closed), sin lanzar `CalledProcessError` ni excepcion no capturada (degradado de la Fase 1, cubierto por el test nuevo de Fase 2)
- [ ] `_make_tree` (l.56-73 de `tests/unit/test_prefix_resolver.py`) queda sin diff; el helper de fixtures git real (`_make_git_tree`) es una funcion nueva y separada, usada solo por los tests de la rama WOT que invocan `git`
- [ ] Mutation-verify de los 2 pares (prefix_resolver.guard fix, check_worktree_topology inverso) registrado literal en `execution_log.md`
- [ ] Cableado PRE presente en `prompts/orchestrator_destination_bootstrap.md`, `prompts/orchestrator_launch_builder.md` y `prompts/orchestrator_session_bootstrap.md` (cierra el eje orquestador-WOT); cableado POST presente en `prompts/manager_review.md` fuera de su Paso 0 CF-frozen (que queda intacto)
- [ ] `ruff check` y `uv run ruff format --check` en 0 errores sobre los archivos Python tocados, sin usar `# noqa`
- [ ] Suite completa `python scripts/run_pytest_safe.py -- --level all` en exit 0
- [ ] `python .agent/agent_controller.py --validate --json --force` en 0 errores

## Handoff: Manager -> Builder
**Plan:** WOT-2026-021g
**Accion requerida:** Implementar segun work_plan.md
**Estado:** PENDING
