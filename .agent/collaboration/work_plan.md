# Work Plan - WOT-2026-019k

## Metadata
- **ID:** WOT-2026-019k
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Acotar test_run_gates_dispatch_importable_without_module_shadowing a subprocess de solo-import (sin main/gates), de ~165s a menos de 1s
- **Creado:** 2026-07-07
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Reducir el coste de test_run_gates_dispatch_importable_without_module_shadowing
(tests/unit/test_run_gates_dispatch.py) de ~165 segundos a menos de 1 segundo,
acotando el subprocess de verificacion a ejecutar SOLO el codigo a nivel de
modulo de scripts/run_gates_dispatch.py (hasta MOTOR_ROOT inclusive, linea
67) sin invocar main() (linea 229), preservando integramente la capacidad de
la barrera de detectar el shadowing de runtime.motor_link que causo el bug de
WOT-2026-019i.

## Contexto / Root Cause

El test actual invoca el script completo como __main__
(subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" /
"run_gates_dispatch.py")], cwd=PROJECT_ROOT, ...)),
tests/unit/test_run_gates_dispatch.py:374-379,
lo que ejecuta main() -> arranca ruff, run_pytest_safe.py y el resto de
gates de calidad (~165s, confirmado por Review 2 de 019i: "1 passed in
164.48s"). Pero el fallo original de 019i (ModuleNotFoundError: No module
named 'runtime.motor_link') ocurria en MOTOR_ROOT =
resolve_motor_root_path(PROJECT_ROOT) (scripts/run_gates_dispatch.py:67),
que internamente llama from runtime.motor_link import resolve_motor_root
(scripts/run_gates_dispatch.py:58) -- codigo a NIVEL DE MODULO, ejecutado
mucho antes de que main() (linea 229) sea siquiera invocado. Confirmado por
lectura completa de scripts/run_gates_dispatch.py lineas 1-76: nada entre la
linea 1 y la linea 67 (bootstrap de sys.path, definicion de
_import_scope_gate, resolve_project_root_path, get_collab_dir_path,
resolve_motor_root_path, y la asignacion de MOTOR_ROOT) arranca un
subprocess ni ejecuta gates; el primer subprocess de gates ocurre dentro de
run_code_gates (linea 161 en adelante), que solo se llama desde main().
El subprocess completo del test actual es, por tanto, ~165s de trabajo
desperdiciado para verificar un import que falla o no falla en menos de 0.2s.

## Non-goals

- No se modifica scripts/run_gates_dispatch.py (produccion). El fix es
  exclusivamente del test.
- No se anade ningun assert de wall-clock (medicion de tiempo) al test nuevo;
  seria flaky en CI. La verificacion de "no ejecuta gates" es estructural
  (ausencia de los strings de stdout que main()/run_code_gates emiten, ver
  Fase 1.2), no temporal.
- No se elimina el aislamiento de subprocess: la verificacion sigue
  ejecutandose en un proceso Python fresco e independiente (no se reutiliza
  el modulo dispatch ya cargado por importlib.util al inicio del archivo
  de test, lineas 13-18), porque reimportar en el mismo proceso no
  re-ejercitaria el fallo de import a nivel de modulo (ya documentado en el
  docstring actual del test, lineas 367-372).
- No se modifica ningun otro test de tests/unit/test_run_gates_dispatch.py.
- No se anade un marker slow ni se salta el test bajo ninguna condicion:
  el test acotado debe correr siempre, en local y en CI, sin flags
  especiales.

## Files Likely Touched

- tests/unit/test_run_gates_dispatch.py

## Plan de Implementacion

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| Bot | TAREA AGENTE | Builder |

### Fase 1: Acotar el subprocess a solo-import, sin ejecutar main()/gates (Bot)

#### 1.1: Bot Reemplazar el subprocess de script completo por un subprocess de exec_module via -c
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/unit/test_run_gates_dispatch.py
- **Accion:** Modificar
- **Descripcion:** En
  test_run_gates_dispatch_importable_without_module_shadowing (lineas
  359-383), reemplazar la invocacion actual
  (subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" /
  "run_gates_dispatch.py")], cwd=PROJECT_ROOT, capture_output=True,
  text=True)) por un subprocess que ejecute el script COMO MODULO (no como
  __main__) via python -c, de modo que el codigo a nivel de modulo
  (incluida la linea 67, MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT),
  y el import problematico de la linea 58 dentro de ella) se ejecute
  integramente, pero el bloque if __name__ == "__main__": ... main() NO se
  dispare (su guarda es falsa al importar el archivo como modulo en vez de
  ejecutarlo directamente).

  Codigo exacto del subprocess (usar -c con este cuerpo, pasado como un
  unico string; usar PROJECT_ROOT ya definido en el archivo de test,
  linea 12, para construir la ruta absoluta del script):

  ```python
  _EXEC_MODULE_ONLY_SNIPPET = (
      "import importlib.util, sys\n"
      "from pathlib import Path\n"
      "project_root = Path(sys.argv[1]).resolve()\n"
      "spec = importlib.util.spec_from_file_location(\n"
      "    'run_gates_dispatch_module_probe',\n"
      "    project_root / 'scripts' / 'run_gates_dispatch.py',\n"
      ")\n"
      "module = importlib.util.module_from_spec(spec)\n"
      "spec.loader.exec_module(module)\n"
  )

  result = subprocess.run(
      [sys.executable, "-c", _EXEC_MODULE_ONLY_SNIPPET, str(PROJECT_ROOT)],
      cwd=PROJECT_ROOT,
      capture_output=True,
      text=True,
  )
  ```

  Mecanismo: spec_from_file_location + module_from_spec +
  spec.loader.exec_module(module) ejecuta el codigo de nivel superior
  del archivo (imports, PROJECT_ROOT, MOTOR_ROOT y las definiciones de
  funcion, lineas 10-227), equivalente a un import, no a correrlo como
  __main__,
  por lo que __name__ dentro del modulo ejecutado es
  'run_gates_dispatch_module_probe' (el name pasado a
  spec_from_file_location), NUNCA '__main__'; la guarda if __name__ ==
  "__main__": al final de scripts/run_gates_dispatch.py permanece False y
  main() no se invoca. Esto es el mismo mecanismo que ya usa el propio
  archivo de test para cargar dispatch al inicio (lineas 13-18), aplicado
  aqui dentro de un SUBPROCESO nuevo en vez del proceso pytest actual (la
  aislacion en subprocess se preserva; solo cambia que en vez de ejecutar el
  script como __main__, se ejecuta como modulo importado).

  Mantener las 2 aserciones actuales sin cambios:
  assert "ModuleNotFoundError" not in result.stderr y
  assert "No module named 'runtime.motor_link'" not in result.stderr.

  Actualizar el docstring del test para explicar el nuevo mecanismo acotado
  (que solo se ejercita el import de nivel de modulo, no main()) en vez
  del mecanismo de "invocar el script completo".
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** pytest
  tests/unit/test_run_gates_dispatch.py -k
  test_run_gates_dispatch_importable_without_module_shadowing -v --durations=1
  pasa (exit 0) y la duracion reportada por --durations=1 para ese test es
  menor a 5 segundos (verificacion manual del Builder al documentar en
  execution_log; NO se anade un assert de tiempo dentro del test, ver
  Non-goals). El test ya no imprime en su output ninguna de las cadenas que
  emite main()/run_code_gates ("[dispatch] Running ruff check",
  "[dispatch] Running pytest-safe"), verificable inspeccionando
  result.stdout y result.stderr del subprocess dentro del propio test
  (ver criterio 1.2, que formaliza esto como assert).
- **Si falla:** Si spec.loader.exec_module no reproduce el
  ModuleNotFoundError original en absoluto (ni siquiera con la mutation de
  2.1), escalar al Manager con el output literal antes de volver al
  subprocess de script completo.

#### 1.2: Bot Assert estructural de "no se ejecutaron gates" (sin medir tiempo)
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/unit/test_run_gates_dispatch.py
- **Accion:** Modificar (mismo test de 1.1)
- **Descripcion:** Anadir, junto a las 2 aserciones existentes, una tercera
  asercion que confirme estructuralmente que main() no corrio: assert
  "[dispatch]" not in result.stdout. El prefijo "[dispatch]" es el que
  aparece en los print() de main(), run_code_gates y
  run_deliverable_gates y sus sub-pasos (confirmado por lectura de
  scripts/run_gates_dispatch.py: cada print(...) desde la linea 86 en
  adelante usa el prefijo "[dispatch]" o f"[dispatch] ..."); el codigo a
  nivel de modulo (lineas 1-76, incluida resolve_motor_root_path) no
  imprime nada con ese prefijo. Esta asercion es la evidencia estructural de
  que el subprocess acotado no ejecuto ningun gate, sin depender de medir
  wall-clock.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El test con las 3 aserciones (2 existentes +
  la nueva de "[dispatch]" not in result.stdout) pasa en exit 0 sobre el
  commit de entrega (post-1.1).
- **Si falla:** Si "[dispatch]" aparece en stdout del subprocess acotado
  (indicando que el codigo de nivel-modulo ejecuta un print con ese
  prefijo), escalar al Manager: implicaria que el analisis de Fase 0 sobre
  el codigo a nivel de modulo era incompleto y el diseno de la Fase 1
  necesita revisarse antes de continuar.

### Fase 2: Mutation-verify sin tocar produccion de forma permanente (Bot)

#### 2.1: Bot Verificar que el test acotado sigue fallando ante el shadowing reintroducido
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/unit/test_run_gates_dispatch.py (verificacion manual,
  sin commit del estado mutado)
- **Accion:** Verificar (mutation temporal, no permanente)
- **Descripcion:** Reproducir localmente, sin modificar
  scripts/run_gates_dispatch.py de forma permanente, el bug pre-019i:
  revertir temporalmente (en el working tree, sin commitear) el fix de
  019i en scripts/run_gates_dispatch.py -- reinsertar
  sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP / ".agent")) a nivel de
  modulo ANTES de la definicion de _import_scope_gate y volver a un
  import scope_gate global tal como estaba antes del commit 5a7d973 (ver
  git show 5a7d973 -- scripts/run_gates_dispatch.py para el diff exacto a
  revertir) -- y confirmar que el test acotado de la Fase 1 FALLA con el
  mismo ModuleNotFoundError: No module named 'runtime.motor_link' que
  capturaba el test original. Verificado por el Manager antes de aprobar
  este plan: simplemente insertar .agent en sys.path DESPUES de que el
  propio script ya inserta _PROJECT_ROOT_BOOTSTRAP en el indice 0 NO
  reproduce el bug (el script post-fix prioriza la raiz del proyecto); la
  mutation debe revertir el ORDEN real del commit 5a7d973 (insertar .agent
  en el indice 0 ANTES de insertar la raiz del proyecto, exactamente como
  estaba pre-019i), no una insercion adicional posterior. Tras confirmar el
  FAIL, restaurar el archivo a su estado del commit de entrega con
  git checkout -- scripts/run_gates_dispatch.py (o equivalente) antes de
  continuar; el archivo de produccion no debe quedar modificado en el
  commit final de este ticket.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** Con el fix de 019i revertido temporalmente en
  el working tree, pytest tests/unit/test_run_gates_dispatch.py -k
  test_run_gates_dispatch_importable_without_module_shadowing -v FALLA con
  salida que contiene literalmente ModuleNotFoundError y "No module named
  'runtime.motor_link'" en la asercion fallida. Tras restaurar el archivo,
  el mismo comando vuelve a pasar (exit 0). El Builder documenta ambos
  comandos y sus salidas literales (FAIL-con-shadowing / PASS-sin) en
  execution_log_WOT-2026-019k.md.
- **Si falla:** Si la mutation NO logra reproducir el
  ModuleNotFoundError (el test acotado pasa igual con el shadowing
  reintroducido), la barrera de la Fase 1 esta rota: escalar al Manager con
  el diff exacto de la mutation aplicada y el output del test antes de
  marcar READY_FOR_REVIEW. No se aprueba el cierre sin este FAIL confirmado.

### Fase 3: Verificacion y cierre de calidad (Bot)

#### 3.1: Bot Gates de calidad, suite completa y validate
- **Tipo:** TAREA AGENTE
- **Archivo:** N/A (solo comandos)
- **Accion:** Verificar
- **Descripcion:** Con el archivo de produccion restaurado (sin la
  mutation de la Fase 2 aplicada), ejecutar en orden: ruff check
  tests/unit/test_run_gates_dispatch.py; la suite completa (run_pytest_safe
  con nivel all o el equivalente documentado en AGENTS.md) registrando el
  tested_commit_sha; python .agent/agent_controller.py --validate --json
  --project-root . Los tres comandos deben salir en verde antes de marcar
  READY_FOR_REVIEW.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** ruff check exit 0 sobre el archivo tocado; la
  suite completa termina en exit 0 y su tested_commit_sha coincide con el
  HEAD del commit de entrega; --validate --json reporta errors: 0.
- **Si falla:** Si la suite completa revela otro flaky no relacionado con
  este ticket, documentarlo en execution_log y escalar al Manager en vez de
  intentar arreglarlo fuera de scope.

## Calidad

| Fase | Comando de verificacion |
|------|--------------------------|
| 1.1 | pytest tests/unit/test_run_gates_dispatch.py -k test_run_gates_dispatch_importable_without_module_shadowing -v --durations=1 (exit 0, duracion menor a 5s) |
| 1.2 | Mismo comando de 1.1; confirma que "[dispatch]" no aparece en stdout del subprocess acotado |
| 2.1 | Con el fix de 019i revertido temporalmente (working tree, sin commit): mismo pytest -k del test acotado FALLA con ModuleNotFoundError / "No module named 'runtime.motor_link'"; tras restaurar el archivo, el mismo comando vuelve a pasar |
| 3.1 | ruff check tests/unit/test_run_gates_dispatch.py; suite completa (tested_commit_sha == HEAD); python .agent/agent_controller.py --validate --json --project-root . |

## Decision Arquitectonica

Se elige exec_module via python -c sobre un env var/flag que corte
scripts/run_gates_dispatch.py antes de main() (opcion B descartada)
porque: (a) no toca produccion, reduciendo el blast radius del cambio a un
unico archivo de test; (b) el mecanismo (spec_from_file_location +
module_from_spec + exec_module) ya es el patron canonico usado en el
propio archivo de test para cargar dispatch al inicio (lineas 13-18), asi
que no introduce una tecnica nueva al codebase; (c) preserva el aislamiento
de subprocess que la barrera necesita (el import a nivel de modulo se
ejecuta en un proceso Python fresco, no en el proceso pytest donde dispatch
ya esta cacheado en sys.modules), condicion necesaria para que la barrera
siga siendo real y no un placebo. Verificado empiricamente por el Manager
antes de aprobar este plan: exec_module de una copia limpia del script
tarda aproximadamente 0.12 segundos (sin ejecutar gates), y reproducir el
ORDEN de sys.path pre-019i (.agent insertado en el indice 0 antes de la
raiz del proyecto) sobre el archivo revertido SI reproduce el
ModuleNotFoundError original; insertar .agent en un indice posterior al
que el propio script post-fix ya usa para la raiz del proyecto NO lo
reproduce, de ahi que la Fase 2 modele la mutation como una reversion real
del diff de 019i (working tree, no commiteada) en vez de una manipulacion
adicional de sys.path desde el test.

No se anade un assert de wall-clock (elapsed menor a 5) porque estos son
tipicamente flaky en CI (maquinas compartidas, contencion de CPU); en su
lugar la Fase 1.2 usa una asercion estructural ("[dispatch]" not in
result.stdout) que es deterministica: o el codigo a nivel de modulo
imprime ese prefijo (no deberia, confirmado por lectura del archivo) o no lo
hace, sin zona gris de "cuanto es demasiado lento".

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| exec_module via python -c en subprocess fresco (import como modulo, no como __main__) | No toca produccion; reutiliza el patron ya usado en el propio archivo de test; preserva aislamiento de subprocess; aproximadamente 0.12s | Requiere pasar el snippet como string -c (legibilidad ligeramente menor que un archivo .py dedicado) | Aceptada |
| Env var/flag en scripts/run_gates_dispatch.py para cortar antes de main() | Podria ser mas explicito en el propio script | Toca codigo de produccion para un unico test; introduce una rama condicional en el script real solo para testing | Descartada |
| Ejecutar el script completo como hoy (subprocess de __main__, aproximadamente 165s) | Cero cambios, cero riesgo de regresion en la barrera | Coste de aproximadamente 165s por ejecucion, principal motivador del ticket; desperdicia tiempo de CI verificando un import ya cubierto en menos de 1s | Descartada (es el problema que este ticket resuelve) |
| Assert de wall-clock (elapsed menor a 5) dentro del test | Verificacion directa y facil de entender del objetivo "es rapido" | Flaky en CI compartido; no es la garantia real que importa (la garantia real es "no ejecuta gates", no "tarda X segundos") | Descartada |
| Asercion estructural ("[dispatch]" not in stdout) para confirmar ausencia de ejecucion de gates | Deterministica, no depende de wall-clock ni de la maquina | Depende de que ningun print futuro fuera de main() use el prefijo "[dispatch]" (mitigado: confirmado por lectura completa del archivo antes de aprobar) | Aceptada |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Criterios de Aceptacion Global
- [ ] test_run_gates_dispatch_importable_without_module_shadowing invoca el
      script via exec_module (import-como-modulo) en un subprocess fresco,
      NO como __main__; nunca llama a main() ni ejecuta ningun gate.
- [ ] El test pasa en menos de 5 segundos (idealmente menos de 1s), sin usar
      un assert de wall-clock dentro del propio test.
- [ ] Las 2 aserciones originales (ausencia de "ModuleNotFoundError" y de
      "No module named 'runtime.motor_link'" en stderr) se preservan sin
      debilitarse.
- [ ] Nueva asercion estructural: "[dispatch]" no aparece en el stdout del
      subprocess acotado (confirma que no se ejecutaron gates).
- [ ] MUTATION: revirtiendo temporalmente (sin commit) el fix de 019i en
      scripts/run_gates_dispatch.py, el test acotado FALLA con el mismo
      ModuleNotFoundError; restaurado el archivo, vuelve a pasar. Evidencia
      documentada en execution_log_WOT-2026-019k.md.
- [ ] Cross-platform: el mecanismo (exec_module, sys.executable) no depende
      de sys.platform ni de rutas especificas de Windows; corre igual en CI
      Linux.
- [ ] scripts/run_gates_dispatch.py NO se modifica en el commit final (solo
      el archivo de test).
- [ ] ruff check + suite completa + --validate --json en verde.

## 2026-07-07 Handoff: Manager a Builder
**Plan:** WOT-2026-019k
**Accion requerida:** Implementar segun work_plan.md
**Estado:** PENDING
