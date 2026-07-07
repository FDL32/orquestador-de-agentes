# Work Plan - WOT-2026-019s

## Metadata
- **ID:** WOT-2026-019s
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Corregir Step-CreateVenv para que siempre sincronice dependencias aunque el venv ya exista
- **Creado:** 2026-07-07
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir Step-CreateVenv en scripts/setup_dev_worktree.ps1 para que uv
sync se ejecute SIEMPRE que el venv de la worktree-dev ya este creado (con
o sin python.exe presente), en vez de saltarse por completo la
sincronizacion de dependencias cuando .venv\Scripts\python.exe ya existe.

## Contexto / Root Cause

Step-CreateVenv (scripts/setup_dev_worktree.ps1:175-199) usa la
existencia de .venv\Scripts\python.exe como unico gate de idempotencia:

    function Step-CreateVenv {
        $venvPython = Join-Path $script:WorktreePath '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $venvPython)) {
            # ... uv venv && uv sync ...
        }
        else {
            Write-Host "... El venv de la worktree ya existe ... (idempotente, sin cambios)."
        }
    }

Si python.exe existe, la funcion entera se salta, incluyendo uv sync.
Pero un venv puede tener python.exe con dependencias FALTANTES o
desincronizadas (p.ej. uv venv corrio pero uv sync fallo o se
interrumpio en una corrida anterior, o pyproject.toml/uv.lock
cambiaron despues de crear el venv). En ese caso el script reporta exito
"idempotente sin cambios" pero deja el venv incompleto, y el siguiente uso
(ruff, pytest, agent_controller.py) rompe con ImportError. uv sync
es idempotente por diseno (no reinstala lo ya sincronizado), asi que
correrlo siempre es seguro y barato.

## Decision Arquitectonica

Se elige la opcion (A): correr uv sync incondicionalmente, fuera del
if (-not (Test-Path ...)), preservando la creacion condicional del venv
(uv venv solo si falta python.exe).

Justificacion:
- uv sync ya es idempotente por diseno (no reinstala paquetes ya
  sincronizados a la version del lockfile); ejecutarlo de mas no tiene
  costo funcional relevante frente al riesgo de un venv incompleto
  silencioso.
- Es el cambio minimo: no se anade deteccion heuristica ni estado nuevo,
  solo se saca uv sync del bloque condicional que protege unicamente la
  creacion del venv (uv venv).
- Se alinea con el patron ya usado en el propio repo para gates de
  idempotencia "accion barata siempre, accion cara condicional" (crear vs.
  sincronizar).

Se descarta la opcion (B): detectar dependencias faltantes (intentar
un import o comprobar un marcador de "sync completo") porque anade
superficie nueva (que archivo/marcador declarar como fuente de verdad de
"sync al dia", como invalidarlo si cambia uv.lock) y es mas fragil de
testear con el fake uv.bat de tests/test_setup_dev_worktree_script.py
(el fake no ejecuta uv sync de verdad, asi que no puede materializar
dependencias reales para que una heuristica de deteccion las intente
importar). La opcion (A) evita ese problema por completo.

## Cambio esperado en Step-CreateVenv

- El if (-not (Test-Path -LiteralPath $venvPython)) sigue existiendo,
  pero solo envuelve uv venv (creacion del venv) y su chequeo de exit
  code.
- uv sync (con su chequeo de $LASTEXITCODE) se mueve fuera de ese
  if, de modo que se ejecuta en ambas ramas: cuando se acaba de crear el
  venv y cuando ya existia.
- El Push-Location $script:WorktreePath / finally { Pop-Location } debe
  seguir envolviendo tanto uv venv (si corre) como uv sync (que ahora
  siempre corre), para que uv sync se ejecute con cwd en la worktree.
- Los mensajes Write-Host deben dejar de decir "idempotente, sin
  cambios" para el caso "python.exe ya existe": ahora esa rama SI hace un
  cambio (invoca uv sync). Ajustar el texto para reflejar que el venv ya
  existia pero se resincronizaron dependencias (evitar que el mensaje
  mienta).
- El $PSCmdlet.ShouldProcess(...) debe seguir gobernando la ejecucion
  real de uv sync en modo -WhatIf (no debe invocarse bajo -WhatIf),
  igual que ya protege uv venv hoy.
- Actualizar la docstring del script (.DESCRIPTION, paso 3, lineas
  21-23) para reflejar que ahora siempre se corre uv sync aunque el venv
  ya exista (solo la creacion del venv en si es condicional).

## Files Likely Touched

- scripts/setup_dev_worktree.ps1
- tests/test_setup_dev_worktree_script.py

## Mecanismo de la barrera (FAIL sin fix / PASS con fix)

El fake uv.bat actual (_FAKE_UV_BAT en
tests/test_setup_dev_worktree_script.py:48-58) responde a sync con
exit /b 0 sin dejar rastro de haber sido invocado. Hay que extenderlo (o
anadir una variante local al nuevo test) para que registre cada
invocacion de uv sync, por ejemplo agregando una linea al script batch
que, en la rama "%1"=="sync", escriba/incremente un archivo marcador en
un directorio conocido (p.ej. echo sync >> "%CD%\.uv_sync_calls.log" o
un contador via set /a persistido a archivo), ANTES de exit /b 0. El
test nuevo debe:

1. Ejecutar el script una primera vez (_run_script sin flags) sobre el
   fixture repo, tal como ya hacen los tests existentes, para que se cree
   el venv-dev con python.exe (via el fake uv venv) y se registre la
   primera invocacion de sync.
2. Verificar que el marcador de invocacion de sync existe/tiene 1
   registro tras la primera corrida.
3. Ejecutar el script una segunda vez (mismo fixture, venv y
   python.exe ya presentes).
4. Aserto de la barrera: tras la segunda corrida, el marcador de sync
   debe tener 2 registros (uno por corrida), no 1. Sin el fix, la
   segunda corrida no invoca uv sync en absoluto (el marcador se queda
   en 1 registro) porque Step-CreateVenv entra en la rama else y sale
   sin tocar uv; ese es el estado FAIL-sin-fix. Con el fix, la segunda
   corrida SI invoca uv sync (el marcador sube a 2), que es el estado
   PASS-con-fix.
5. El test hereda automaticamente el pytestmark =
   pytest.mark.skipif(sys.platform != "win32", ...) ya definido a nivel
   de modulo (linea 38-41): NO anadir un skipif propio ni quitar el de
   modulo.
6. Si el test necesita listar git worktree list o comparar paths de la
   worktree, usar str(worktree_path) (la variable ya devuelta por el
   fixture fixture_repo), nunca el substring bare
   "orquestador_de_agentes_dev" (leccion WOT-2026-019q, ya documentada
   en el comentario de test_remove_cleans_worktree_and_reattaches_main,
   lineas 271-276 del archivo).

El mecanismo concreto de conteo (archivo log con >>, contador en
archivo, o un directorio con un archivo por invocacion) queda a criterio
del Builder; el requisito de diseno es que sea legible desde Python
(Path.read_text() / contar archivos) despues de cada corrida del script,
sin depender de parsear stdout del script en si.

## Definition of Done

1. Step-CreateVenv ejecuta uv sync incluso cuando
   .venv\Scripts\python.exe ya existe (creacion de venv sigue siendo
   condicional; sincronizacion de deps deja de serlo).
2. Test nuevo en tests/test_setup_dev_worktree_script.py que demuestra
   la barrera: FAIL-sin-fix (segunda corrida NO invoca uv sync) /
   PASS-con-fix (segunda corrida SI lo invoca), via el fake uv.bat
   extendido con registro de invocaciones. Hereda el
   skipif(sys.platform != "win32") de modulo.
3. Los tests existentes del script siguen en verde:
   test_creation_detaches_principal_and_adds_worktree_with_venv,
   test_creation_fails_closed_when_principal_is_dirty,
   test_creation_is_idempotent_on_second_run,
   test_whatif_creation_mutates_nothing,
   test_remove_cleans_worktree_and_reattaches_main,
   test_remove_with_uncommitted_changes_fails_closed,
   test_regression_add_without_detach_first_fails. En particular,
   test_creation_is_idempotent_on_second_run debe seguir pasando con
   exit 0 y el texto "idempotente" en la salida combinada (referido ahora
   a los pasos de detach/worktree, que siguen siendo genuinamente
   idempotentes; el mensaje de Step-CreateVenv puede cambiar su
   redaccion pero no debe romper ese assert si el test no depende del
   texto exacto de esa linea).
4. Docstring del script (.DESCRIPTION, paso 3) actualizada para
   reflejar el nuevo comportamiento.
5. python .agent/agent_controller.py --validate --json --project-root .
   da 0 errores / 0 warnings (fuera del drift esperado de transicion de
   ticket, que resuelve el Orquestador).
6. ruff aplica unicamente sobre
   tests/test_setup_dev_worktree_script.py (es el unico archivo Python
   tocado; scripts/setup_dev_worktree.ps1 es PowerShell y ruff no
   aplica sobre el).
7. El gate funcional del .ps1 es su propia suite de tests
   (tests/test_setup_dev_worktree_script.py), no ruff ni un linter de
   PowerShell: correr esa suite completa (skip fuera de win32; verde en
   Windows) es el criterio de aceptacion del script.

## Non-goals

- No se modifica la logica de deteccion de "worktree registrada" ni de
  "principal dirty" (Step-CreateWorktree, Test-WorktreeHasUncommittedChanges,
  Invoke-RemoveWorktree): el bug es exclusivo de Step-CreateVenv.
- No se introduce deteccion heuristica de dependencias faltantes (opcion
  B, descartada arriba).
- No se toca assert_work_plan_committed / motor_checkpoint.py /
  scope_gate.py (superficie del ticket anterior, WOT-2026-019v, ya
  cerrado).

## Plan de Implementacion

### Tipos de Tareas

| Marca | Tipo | Ejecutor |
|-------|------|----------|
| [AGENTE] | TAREA AGENTE | Builder |

### Fase 1: Confirmar el estado FAIL-sin-fix con un fake uv.bat que registre invocaciones [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** tests/test_setup_dev_worktree_script.py
- **Accion:** Modificar
- **Descripcion:** Extender _FAKE_UV_BAT (o anadir una variante local)
  para que la rama "%1"=="sync" registre cada invocacion en un archivo
  marcador dentro del cwd de ejecucion (p.ej.
  echo sync >> "%CD%\.uv_sync_calls.log") antes de exit /b 0. Escribir
  un test nuevo (p.ej. test_second_run_resyncs_existing_venv) que: (1)
  corre el script una vez sobre el fixture repo, (2) confirma que el log
  de invocaciones de sync tiene exactamente 1 linea, (3) corre el script
  una segunda vez, (4) afirma que el log tiene 2 lineas tras la segunda
  corrida. Ejecutar el test ANTES de tocar setup_dev_worktree.ps1
  (con el codigo actual, sin fix) y confirmar que FALLA en el paso (4)
  porque el log se queda en 1 linea.
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** El test nuevo, corrido contra el
  setup_dev_worktree.ps1 sin modificar, falla exactamente en el assert
  de "2 lineas tras la segunda corrida" (no por un error de fixture o de
  sintaxis del fake bat).
- **Si falla el criterio (es decir, si el test pasa sin fix, o falla por
  otra razon):** Revisar que el fake uv.bat registra la invocacion
  ANTES del exit /b 0 y que el test lee el log despues de cada corrida
  del script, no una sola vez al final; escalar al Manager si tras 3
  intentos el test no reproduce el FAIL esperado.

### Fase 2: Corregir Step-CreateVenv para sincronizar siempre [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** scripts/setup_dev_worktree.ps1
- **Accion:** Modificar
- **Descripcion:** En Step-CreateVenv (lineas 175-199), sacar la llamada
  a uv sync (y su chequeo de $LASTEXITCODE) del bloque
  if (-not (Test-Path -LiteralPath $venvPython)), de modo que se ejecute
  siempre (tanto si el venv se acaba de crear como si ya existia). El
  bloque if sigue envolviendo unicamente uv venv y su chequeo de exit
  code. Push-Location/Pop-Location deben seguir cubriendo la llamada a
  uv sync en ambos casos. Ajustar el Write-Host de la rama "ya existe"
  para no decir "idempotente, sin cambios" (ahora si hay un cambio: se
  resincronizan dependencias). Actualizar la seccion .DESCRIPTION
  (paso 3, lineas 21-23) del comment-based help del script para reflejar
  que uv sync corre siempre, y que solo la creacion del venv en si
  (uv venv) es condicional.
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** git diff -- scripts/setup_dev_worktree.ps1
  muestra el cambio localizado en Step-CreateVenv y en el bloque
  .DESCRIPTION; ningun otro Step (Step-DetachPrincipal,
  Step-CreateWorktree, Test-WorktreeHasUncommittedChanges,
  Invoke-RemoveWorktree) se modifica.
- **Si falla:** Revertir con
  git checkout -- scripts/setup_dev_worktree.ps1 y escalar al Manager
  citando el error exacto.

### Fase 3: Demostrar PASS-con-fix y correr la suite completa del script [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** tests/test_setup_dev_worktree_script.py (ejecucion, sin
  modificar salvo ajustes menores de assert si hiciera falta)
- **Accion:** Ejecutar / verificar
- **Descripcion:** Re-ejecutar el test de la Fase 1
  (test_second_run_resyncs_existing_venv) contra el
  setup_dev_worktree.ps1 ya corregido en la Fase 2: debe pasar (el log
  de invocaciones de sync llega a 2 lineas tras la segunda corrida).
  Despues, correr la suite entera del archivo:
  .venv\Scripts\python.exe -m pytest tests/test_setup_dev_worktree_script.py -q
  y confirmar que los 7 tests preexistentes
  (test_creation_detaches_principal_and_adds_worktree_with_venv,
  test_creation_fails_closed_when_principal_is_dirty,
  test_creation_is_idempotent_on_second_run,
  test_whatif_creation_mutates_nothing,
  test_remove_cleans_worktree_and_reattaches_main,
  test_remove_with_uncommitted_changes_fails_closed,
  test_regression_add_without_detach_first_fails) mas el test nuevo dan
  8 passed / 0 failed (el modulo entero corre porque estamos en Windows;
  si por algun motivo corre en un entorno no-Windows, confirmar que el
  modulo entero se skipea via el pytestmark existente, sin tocarlo).
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** 8 passed / 0 failed en Windows (o 8 skipped
  fuera de Windows) para tests/test_setup_dev_worktree_script.py.
- **Si falla:** Si test_creation_is_idempotent_on_second_run rompe por
  el cambio de texto del Write-Host, ajustar unicamente el texto
  esperado en ese assert (no relajar el assert de "idempotente" para los
  pasos de detach/worktree, que siguen siendolo); si cualquier otro test
  preexistente rompe, revisar que el diff de Fase 2 no toco nada fuera de
  Step-CreateVenv/.DESCRIPTION. Escalar tras 3 intentos.

### Fase 4: Gates de calidad finales [AGENTE]

- **Tipo:** [AGENTE] TAREA AGENTE
- **Archivo:** N/A (comandos de verificacion)
- **Accion:** Ejecutar (no modifica codigo de produccion)
- **Descripcion:** Ejecutar en este orden desde la raiz del repo con el
  interprete de la worktree-dev:
  1. .venv\Scripts\python.exe -m ruff check tests/test_setup_dev_worktree_script.py
  2. .venv\Scripts\python.exe -m ruff format --check tests/test_setup_dev_worktree_script.py
  3. PYTHONDONTWRITEBYTECODE=1 .venv\Scripts\python.exe scripts/run_pytest_safe.py --level all
     (runner canonico del repo; suite completa, no un subconjunto).
  4. .venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .
- **Riesgo:** [Bajo]
- **Criterio de Aceptacion:** ruff check y ruff format --check devuelven
  exit code 0 sobre tests/test_setup_dev_worktree_script.py; la suite
  completa de scripts/run_pytest_safe.py --level all sale verde (0
  failed) con tested_commit_sha igual al HEAD del commit que contiene
  los cambios de Fase 1-3; --validate --json reporta errors: 0
  (fuera del drift plan-vs-log esperado en la transicion de ticket, que
  resuelve el Orquestador, no el Builder).
- **Si falla:** Si ruff format --check falla, correr
  ruff format tests/test_setup_dev_worktree_script.py y re-verificar
  (no editar el formato a mano). Si la suite completa falla en un test
  fuera del alcance de este ticket, escalar al Manager citando el nombre
  exacto del test y si es un rojo pre-existente conocido o uno nuevo.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| A: uv sync incondicional (fuera del if de Test-Path) | Minimo; aprovecha que uv sync ya es idempotente por diseno; no anade estado nuevo ni superficie de deteccion | Corre uv sync de mas cuando el venv ya estaba sincronizado (costo bajo, red/disco) | Elegida |
| B: deteccion heuristica de deps faltantes (import de prueba o marcador de sync-completo) | Evita invocar uv sync cuando no hace falta | Anade superficie nueva (que marcador, como invalidarlo si cambia uv.lock); dificil de testear con el fake uv.bat (no instala deps reales) | Descartada |

## Guia de Riesgos

| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| [Bajo] | Rutinaria | Intentar 3 veces antes de escalar |

## Criterios de Aceptacion Global

- [ ] Step-CreateVenv invoca uv sync en la segunda corrida del script
      (venv y python.exe ya existentes), demostrado por el test nuevo
      con el fake uv.bat que registra invocaciones (FAIL sin el fix,
      PASS con el fix).
- [ ] La creacion del venv (uv venv) sigue siendo condicional a que
      falte .venv\Scripts\python.exe.
- [ ] Los 7 tests preexistentes de tests/test_setup_dev_worktree_script.py
      siguen pasando (o skipeandose fuera de Windows via el pytestmark
      de modulo, sin modificarlo).
- [ ] La docstring .DESCRIPTION del script refleja el nuevo
      comportamiento del paso 3.
- [ ] assert_work_plan_committed, scope_gate.get_changed_files y
      _handle_pre_handoff (superficie del ticket anterior, 019v) quedan
      bit-a-bit identicos a HEAD.
- [ ] ruff check y ruff format --check sobre
      tests/test_setup_dev_worktree_script.py dan exit code 0.
- [ ] .venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .
      reporta errors: 0.
