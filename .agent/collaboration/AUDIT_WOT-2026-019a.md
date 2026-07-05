# AUDIT - WOT-2026-019a

Ticket: WOT-2026-019a - guard_paths resuelve repo-root por cwd, bloquea
Writes legitimos al repo_destino.
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin
  contradiccion: PASO 1 (segundo root dentro de guard_paths.py) -> PASO 2
  (6+ tests de regresion/fail-closed/paridad + mutation check) -> PASO 3
  (verificacion combinada: pytest de ambos archivos de test + ruff + suite
  canonica). Ningun paso pide crear y revertir el mismo contenido de forma
  permanente (el revert del mutation check en PASO 2 es explicitamente
  temporal y documentado, no queda en el commit final).
- TP-02: verificado - cada DoD por paso cita un comando exacto (ruff
  check/format --check con rutas exactas, pytest -v del archivo completo)
  o un contrato de codigo literal (_resolve_extra_root con AGENT_PROJECT_ROOT
  y fallback a destination_root del link, semantica exacta de
  _is_within_repo con 2 roots). No hay criterio narrado como mejora del
  guard sin verificacion concreta.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  concretos (.agent/hooks/guard_paths.py, tests/test_guard_paths.py), cada
  bullet con ruta parseable, sin comodines. Read/inspect only enumera 5
  archivos concretos (claude_guard_entry.py, agents.json,
  motor_checkpoint.py, runtime/project_root.py,
  tests/unit/test_claude_guard_entry.py) explicitamente fuera de alcance
  de edicion.
- TP-04: verificado - no aparece lenguaje blando tipo si procede en el
  flujo critico. La condicionalidad de _resolve_extra_root (AGENT_PROJECT_ROOT
  primero, destination_root del link como fallback, None si ninguna
  resuelve) esta completamente especificada en el PASO 1 con el
  comportamiento exacto de cada rama, no delegada como heuristica libre al
  Builder.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-019a.md y este AUDIT
  describen la misma secuencia (segundo root en guard_paths.py + 6 tests
  de regresion/fail-closed/paridad + mutation check + verificacion
  combinada), los mismos 2 archivos de Files Likely Touched, y los mismos
  8 criterios de aceptacion global. Los Blockers de este AUDIT usan los
  mismos verbos que las restricciones del PLAN (no tocar el entry, no
  relajar los checks existentes, no anadir un tercer origen de root).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01 a TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo si
  existe o si aplica en Objetivo, Pasos o Criterios de Aceptacion Global
  del work_plan.md decidiendo cuando se activa el segundo root: la
  precedencia (AGENT_PROJECT_ROOT primero, link despues, None si ninguna)
  esta cerrada explicitamente, no delegada al Builder. La unica
  condicionalidad real (path cae en repo_root O en extra_root) es la
  logica misma del fix, no una decision de alcance abierta.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-05), leyendo el codigo real:

- .agent/hooks/claude_guard_entry.py::resolve_repo_root (linea 37-43):
  ancestro .claude mas cercano al cwd. Confirmado que con cwd=motor,
  repo_root resuelve al motor.
- .agent/hooks/claude_guard_entry.py::main (linea 93-104): ejecuta
  guard_paths.py con cwd=repo_root via subprocess.run. Confirmado que no
  pasa AGENT_PROJECT_ROOT ni ningun segundo root a guard_paths.py mas alla
  del cwd del subprocess (que hereda el entorno del proceso padre por
  defecto, incluyendo AGENT_PROJECT_ROOT si estuviera seteada -- pero
  guard_paths.py hoy NUNCA la lee).
- .agent/hooks/guard_paths.py::_is_protected_path (linea 121-160) y
  _is_within_repo (linea 100-105): confirmado por lectura directa que
  usan UNICAMENTE el repo_root recibido (o os.getcwd() si es None) para
  decidir si un path esta dentro del repo. Un ValueError de relative_to
  produce return True, "fuera del repo" (linea 144-145).
- grep de "AGENT_PROJECT_ROOT" en todo el repo: 60 archivos la mencionan,
  NINGUNO de ellos es .agent/hooks/guard_paths.py ni
  .agent/hooks/claude_guard_entry.py. Confirma que el hook nunca consulta
  esa env var hoy, exactamente como describe la ficha.
- runtime/project_root.py::resolve_project_root (linea 82-124): confirmado
  que AGENT_PROJECT_ROOT es un mecanismo YA oficial y documentado del
  orquestador (precedencia: env var primero, fallback a derivar de
  __file__), usado por scripts del orquestador (no por el hook).
- .agent/motor_checkpoint.py::resolve_destino_root (linea 424-436):
  confirmado el patron exacto de lectura fail-safe de destination_root
  desde motor_destination_link.json (try/except JSONDecodeError, OSError),
  ya probado en produccion.
- .agent/config/motor_destination_link.json de ESTE motor (leido en esta
  sesion): confirmado que YA contiene un campo destination_root
  (orquestador_de_agentes_workspace) ademas de motor_root -- el campo no
  es una invencion del plan, ya existe y se usa en otro sitio del codigo.
- tests/test_guard_paths.py y tests/unit/test_claude_guard_entry.py
  (leidos completos): confirmado que ninguno de los tests existentes
  ejercita un escenario de 2 roots; el patron init_git_repo
  (tests/test_motor_root_gates.py linea 23-46) y el patron tmp_path con
  marker .claude (tests/unit/test_claude_guard_entry.py::_make_repo, linea
  17-27) estan disponibles para replicar en el test nuevo.
- git status --short del arbol de trabajo del motor: vacio (arbol limpio
  antes del bootstrap). execution_log.md de WOT-2026-019d archivado a
  execution_log_WOT-2026-019d.md antes de este bootstrap (evita
  contaminar el scope gate del nuevo ticket).

## Blockers (para el Manager en review)

- Si claude_guard_entry.py o canonical_hook_command() aparecen modificados
  en el diff final: BLOCKER critico, invalida la decision de diseno
  Opcion (a) elegida en este plan (el fix debe vivir enteramente en
  guard_paths.py).
- Si _resolve_extra_root (o equivalente) propaga cualquier excepcion en
  vez de devolver None ante una fuente ausente o malformada: BLOCKER, el
  hook dejaria de ser fail-safe (podria romper la disponibilidad del guard
  para cualquier Write, no solo los del segundo root).
- Si el test fail-closed (Write a un tercer path fuera de motor Y destino)
  no esta presente, o si pasa a dar blocked=False en cualquier escenario:
  BLOCKER critico de seguridad, el ticket exige explicitamente preservar
  fail-closed.
- Si PROTECTED_PATH_PATTERNS, PROTECTED_FILENAMES o write_roots dejan de
  aplicarse sobre paths que caen en el segundo root (destino): BLOCKER, el
  segundo root debe quedar sujeto a los mismos checks que el primero, sin
  bypass.
- Si se anade un tercer origen de root ademas de AGENT_PROJECT_ROOT y
  destination_root del link (p. ej. leer un archivo de configuracion
  arbitrario, o aceptar un root pasado por argumento de linea de comandos
  no documentado en este plan): BLOCKER, abre una superficie de bypass no
  contemplada ni revisada.
- Si el test de regresion principal (Write al destino via
  AGENT_PROJECT_ROOT) NO falla contra el codigo pre-fix (mutation check
  ausente o mal ejecutado): BLOCKER, no hay evidencia de que el test
  reproduzca el bug real antes de corregirlo.
- Si algun test existente de tests/test_guard_paths.py o
  tests/unit/test_claude_guard_entry.py se rompe con el cambio: BLOCKER,
  el cambio no es tan quirurgico como se penso, o el entry se toco pese a
  la restriccion.
- Si ruff check o ruff format --check fallan sobre cualquiera de los 2
  archivos tocados: BLOCKER, gate de calidad no satisfecho.
- Si la suite canonica (run_pytest_safe.py) no queda verde con stamp
  fresco sobre HEAD antes de mark-ready: BLOCKER, el gate de pre-handoff no
  confiara en el resultado.
- Si execution_log.md no documenta el mutation check (revert + fallo del
  test de regresion + restauracion + exito) con salida literal de pytest:
  BLOCKER, evidencia insuficiente (el test podria ser un placebo).

## Evidencia esperada en execution_log.md

- Diff final (o cita literal) de guard_paths.py mostrando
  _resolve_extra_root completa y el punto exacto donde _is_within_repo (o
  su punto de llamada) acepta el segundo root.
- Cita literal de los 6+ tests nuevos en tests/test_guard_paths.py, con el
  setup de repos (init_git_repo o tmp_path+.claude) y las aserciones sobre
  blocked/reason de cada escenario.
- Salida literal de pytest del mutation check: ANTES del revert (verde,
  incluyendo los tests nuevos), DESPUES del revert temporal de
  _resolve_extra_root a devolver siempre None (los 2 tests de regresion
  fallan, el resto sigue verde), y tras restaurar (verde de nuevo).
- Salida literal de pytest tests/test_guard_paths.py -v Y
  tests/unit/test_claude_guard_entry.py -v completos (todos los tests, no
  solo los nuevos), confirmando 0 fallos en ambos archivos.
- Salida literal de ruff check y ruff format --check sobre
  .agent/hooks/guard_paths.py y tests/test_guard_paths.py, con exit code 0
  en ambos.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  scripts/run_pytest_safe.py confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con
  WOT-2026-019a en el mensaje.
- Confirmacion explicita (con diff vacio o "sin cambios") de que
  claude_guard_entry.py no aparece modificado.
