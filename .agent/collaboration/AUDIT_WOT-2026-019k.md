# Audit - WOT-2026-019k

## Metadata
- **ID:** WOT-2026-019k
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Fecha:** 2026-07-07

## TP Check

- TP-01: verificado - las 3 fases son secuenciales sin instrucciones
  incompatibles sobre el mismo recurso. Fase 1 modifica el mecanismo de
  invocacion y anade una asercion en el mismo test de
  tests/unit/test_run_gates_dispatch.py; Fase 2 solo VERIFICA (mutation
  temporal en el working tree, sin commit, restaurada antes de continuar,
  documentada explicitamente como no permanente); Fase 3 solo ejecuta
  comandos de verificacion sobre el archivo ya restaurado. Ninguna fase pide
  crear y revertir el mismo cambio de produccion en el mismo paso: la
  Fase 2 revierte y restaura scripts/run_gates_dispatch.py en la MISMA
  sub-tarea, de forma explicita y con el archivo de produccion sin cambios
  en el commit final.
- TP-02: verificado - cada fase tiene un verificador literal: comando
  pytest -k con el nombre exacto del test y --durations=1 (Fase 1.1 y 1.2),
  el mismo comando pytest -k con el fix revertido debe FALLAR con el string
  literal ModuleNotFoundError / "No module named 'runtime.motor_link'"
  seguido del mismo comando en PASS tras restaurar (Fase 2.1), y ruff check
  mas suite completa mas --validate --json (Fase 3.1). No aparece
  "observable" o "correcto" sin una prueba literal que lo verifique.
- TP-03: verificado - Files Likely Touched enumera exactamente 1 archivo
  (tests/unit/test_run_gates_dispatch.py) sin comodines ni "otros archivos
  si hace falta"; scripts/run_gates_dispatch.py aparece mencionado solo
  como objeto de lectura y de mutation TEMPORAL no commiteada (Fase 2.1),
  nunca como archivo a modificar de forma permanente, y el plan lo explicita
  en Non-goals (No se modifica scripts/run_gates_dispatch.py).
- TP-04: verificado - no aparecen expresiones "si procede", "opcionalmente"
  ni "preferiblemente"; el plan especifica valores concretos (menos de 5
  segundos, idealmente menos de 1s; el prefijo exacto [dispatch]; el
  commit exacto 5a7d973 a revertir temporalmente) en vez de terminos
  blandos.
- TP-05: verificado - este AUDIT usa los mismos archivos, comandos y
  criterios que las Fases 1-3 del work_plan: mismo nombre de test
  (test_run_gates_dispatch_importable_without_module_shadowing), mismo
  mecanismo (exec_module via python -c), mismas 3 aserciones (2 originales
  mas "[dispatch]" not in stdout), mismo mecanismo de mutation (revertir el
  diff de 5a7d973 en el working tree sin commit), mismos comandos
  ruff/pytest/validate; no introduce ninguna condicion adicional no
  presente en el plan.

## Blockers Verificados Pre-Aprobacion

- Lectura completa de scripts/run_gates_dispatch.py lineas 1-76: confirma
  que nada entre la linea 1 y la asignacion de MOTOR_ROOT (linea 67, que
  invoca resolve_motor_root_path, la cual hace from runtime.motor_link
  import resolve_motor_root en la linea 58) arranca un subprocess ni
  ejecuta gates. El primer subprocess de gates ocurre dentro de
  run_code_gates (linea 161 en adelante), invocado unicamente desde main()
  (linea 229). Confirma la premisa del ticket: importar el script como
  modulo (sin ejecutar __main__) ejercita el import problematico sin
  correr ningun gate.
- Reproduccion empirica (Manager, subprocess real): exec_module de una
  copia limpia de scripts/run_gates_dispatch.py via spec_from_file_location
  mas module_from_spec mas spec.loader.exec_module, invocado con
  sys.executable en un subprocess nuevo, completa en aproximadamente 0.115
  a 0.119 segundos, exit 0, sin imprimir ninguna linea con el prefijo
  "[dispatch]" (confirmado leyendo que todos los print() de main() y sus
  funciones dependientes usan ese prefijo desde la linea 86 en adelante).
- Reproduccion empirica de la mutation (Manager): insertar manualmente
  ".agent" en sys.path ANTES de exec_module, sobre el script YA CORREGIDO
  por 019i, NO reproduce el ModuleNotFoundError (el propio script inserta
  _PROJECT_ROOT_BOOTSTRAP en el indice 0 de sys.path, lineas 20-22, lo que
  prioriza la raiz del proyecto sobre cualquier insercion posterior de
  ".agent"). Solo reinsertando ".agent" en el INDICE 0 (antes que la raiz
  del proyecto) -- es decir, revirtiendo el ORDEN real del diff de 5a7d973
  -- se reproduce el ModuleNotFoundError original. Verificado literalmente
  por el Manager: insertar ".agent" en sys.path.insert(0, ...) sobre el
  script post-fix (sin revertir el archivo) dio MOTOR_ROOT correcto (sin
  fallo); simular el efecto pre-019i insertando ".agent" en el indice 0 y
  dejando que el import de runtime ocurra antes de cualquier insercion de
  la raiz del proyecto SI reprodujo ModuleNotFoundError: No module named
  'runtime.motor_link'.
- git show 5a7d973 -- scripts/run_gates_dispatch.py leido completo: confirma
  el diff exacto a revertir temporalmente en la Fase 2.1 (eliminar la
  funcion lazy _import_scope_gate, restaurar la asignacion de _AGENT_DIR a
  _PROJECT_ROOT_BOOTSTRAP / ".agent" mas su insercion en sys.path mas un
  import scope_gate a nivel de modulo, en un orden que reproduzca la
  precedencia de ".agent" sobre la raiz del proyecto).
- Grep del archivo de test confirma que subprocess, sys y Path ya estan
  importados a nivel de modulo (tests/unit/test_run_gates_dispatch.py,
  lineas 1 a 9), por lo que la Fase 1 no requiere anadir imports nuevos.
- Confirmado que el test objetivo
  (test_run_gates_dispatch_importable_without_module_shadowing, lineas
  359-383) es el UNICO test del archivo que invoca el script como
  subprocess de __main__ completo; los demas tests del archivo ya usan el
  modulo dispatch cargado una vez al inicio (lineas 13-18) via el mismo
  patron exec_module que este ticket reutiliza para el subprocess fresco.

## Criterios que el Manager verificara en el Review

1. git diff -- tests/unit/test_run_gates_dispatch.py entre el commit base y
   el commit de entrega muestra EXCLUSIVAMENTE cambios dentro de
   test_run_gates_dispatch_importable_without_module_shadowing (cuerpo del
   test y su docstring); ningun otro test del archivo aparece modificado.
2. scripts/run_gates_dispatch.py NO aparece en el diff de entrega (0
   cambios); el Builder documenta en execution_log que cualquier mutation
   temporal de la Fase 2 fue revertida antes del commit final (git status
   sin cambios pendientes sobre ese archivo).
3. El test invoca el script via spec_from_file_location mas
   module_from_spec mas spec.loader.exec_module dentro de un subprocess
   nuevo (python -c), NO via subprocess.run con sys.executable apuntando
   directamente a la ruta del script; el subprocess NUNCA ejecuta main() ni
   imprime ninguna linea con el prefijo "[dispatch]".
4. El test conserva las 2 aserciones originales (ModuleNotFoundError no
   presente en result.stderr, y "No module named 'runtime.motor_link'" no
   presente en result.stderr) sin debilitarlas, y anade una tercera
   asercion estructural ("[dispatch]" no presente en result.stdout o
   equivalente) que confirma que no se ejecuto ningun gate.
5. pytest tests/unit/test_run_gates_dispatch.py -k
   test_run_gates_dispatch_importable_without_module_shadowing -v
   --durations=1, ejecutado por el Builder sobre el commit de entrega, pasa
   en exit 0 con una duracion reportada menor a 5 segundos (el Builder
   documenta la duracion literal en execution_log; no se exige un assert de
   tiempo dentro del propio test).
6. MUTATION documentada en execution_log_WOT-2026-019k.md: el Builder
   revierte temporalmente (working tree, sin commit) el fix de 019i en
   scripts/run_gates_dispatch.py siguiendo el diff de 5a7d973, corre el
   mismo comando pytest -k del punto 5 y obtiene FAIL con
   ModuleNotFoundError y "No module named 'runtime.motor_link'" en la
   salida; luego restaura el archivo (git checkout o equivalente) y
   confirma que el mismo comando vuelve a PASS. Ambas salidas (FAIL y PASS)
   estan documentadas literalmente. Si el Builder reporta que la mutation
   NO reproduce el FAIL, el Manager no aprueba el cierre hasta que la
   barrera quede demostrada como real.
7. ruff check tests/unit/test_run_gates_dispatch.py sale con exit code 0.
8. La suite completa reportada por el Builder (run_pytest_safe --level all
   o equivalente) esta verde y su tested_commit_sha coincide con el HEAD
   del commit de entrega.
9. python .agent/agent_controller.py --validate --json --project-root .
   reportado por el Builder da errors: 0.
10. Ningun otro archivo del repo aparece modificado en el diff de entrega
    salvo tests/unit/test_run_gates_dispatch.py y los artefactos de
    colaboracion que el propio Builder actualice
    (execution_log_WOT-2026-019k.md).

## Evidencia esperada en execution_log_WOT-2026-019k.md

- Diff literal (git diff -- tests/unit/test_run_gates_dispatch.py) o su
  resumen de lineas anadidas/eliminadas dentro del test objetivo.
- Comando y salida literal de pytest -k del test acotado con --durations=1
  (PASS, duracion menor a 5s) sobre el commit de entrega.
- Comando y salida literal de la mutation: pytest -k del test acotado con
  el fix de 019i revertido temporalmente (FAIL con ModuleNotFoundError y
  "No module named 'runtime.motor_link'"), y el mismo comando tras
  restaurar el archivo (PASS). Confirmacion explicita de que
  scripts/run_gates_dispatch.py quedo sin cambios en el commit final
  (git status o git diff vacio sobre ese archivo).
- Output de ruff check sobre tests/unit/test_run_gates_dispatch.py.
- Checkpoint de la suite completa con su tested_commit_sha.
- Output de --validate --json.
