# PLAN - WOT-2026-019a

Ticket: WOT-2026-019a - guard_paths resuelve repo-root por cwd, bloquea
Writes legitimos al repo_destino.
Estado: APPROVED
delivery_authority: repo_motor | deliverable_type: code

Este documento es la estrategia tecnica breve del ticket; el contrato
completo (Files Likely Touched, DoD por paso, STOP conditions, Criterios de
Aceptacion Global) vive en work_plan.md. Si algo difiere entre ambos,
work_plan.md manda.

## Resumen del problema

El hook PreToolUse (claude_guard_entry.py -> guard_paths.py) resuelve
repo_root por el ancestro .claude mas cercano al cwd del proceso harness.
Con cwd=repo_motor, guard_paths.py::_is_protected_path usa UNICAMENTE ese
repo_root para _is_within_repo (path_obj.relative_to(repo_root)). Un Write
legitimo a un archivo del repo_destino (otro repo git) no cuelga de ese
unico root: relative_to lanza ValueError y el guard bloquea con "fuera del
repo", aunque AGENT_PROJECT_ROOT (env var oficial del orquestador) o
destination_root (campo ya presente en motor_destination_link.json)
apunten correctamente al destino.

## Decision de diseno elegida: Opcion (a)

guard_paths.py resuelve un SEGUNDO root internamente (funcion privada
_resolve_extra_root, leida de AGENT_PROJECT_ROOT o, en su ausencia, de
destination_root del link) y lo trata como repo valido ADEMAS del
repo_root recibido. Un Write cuenta como legitimo si cuelga de CUALQUIERA
de los dos; sigue bloqueado si no cuelga de NINGUNO (fail-closed
preservado). claude_guard_entry.py y canonical_hook_command() (el
bootstrap hardcodeado validado estaticamente por el gate de portabilidad)
NO se tocan.

Descartadas: Opcion (b) (pasar el destino explicito desde el entry)
obligaria a tocar el comando que invoca guard_paths.py y probablemente el
bootstrap, ampliando el blast-radius al gate de portabilidad sin
necesidad. Opcion (c) (CONTRACT_FORMATION_REQUIRED) no aplica: el fix cabe
dentro del contrato actual del hook sin requerir arquitectura nueva ni
decision de producto.

## Estrategia (2 pasos IMPLEMENT + 1 VERIFY)

1. .agent/hooks/guard_paths.py: anadir _resolve_extra_root(repo_root) ->
   Path | None (AGENT_PROJECT_ROOT primero, destination_root del link como
   fallback, fail-safe ante cualquier fuente ausente/malformada -- nunca
   propaga excepcion). Generalizar _is_within_repo (o su punto de llamada)
   para aceptar el segundo root: dentro de repo_root O dentro de
   extra_root. El resto de checks (PROTECTED_PATH_PATTERNS,
   PROTECTED_FILENAMES, write_roots) se aplican igual sobre CUALQUIERA de
   los dos roots, sin relajarse.
2. tests/test_guard_paths.py: 6 tests minimo -- 2 de regresion (via
   AGENT_PROJECT_ROOT y via destination_root del link), 1 fail-closed
   (tercer path fuera de ambos sigue bloqueado), 1 de paridad (sin segundo
   root, comportamiento identico al actual), 1 de valor malformado
   (fail-closed), 1 de que los patterns/filenames protegidos siguen
   aplicandose sobre el segundo root. Patron de repos git reales
   (init_git_repo, tests/test_motor_root_gates.py linea 23-46) o tmp_path
   con marker .claude (tests/unit/test_claude_guard_entry.py::_make_repo).
   Mutation check documentado: revertir _resolve_extra_root a devolver
   siempre None, confirmar que los 2 tests de regresion FALLAN y que el
   fail-closed/paridad siguen en verde; restaurar y confirmar verde total.
3. Verificacion combinada: pytest de ambos archivos de test (guard_paths y
   claude_guard_entry, este ultimo debe seguir en verde SIN cambios), ruff
   check/format --check, y la suite canonica run_pytest_safe.py
   (level=all) antes de mark-ready.

## Archivos tocados

- .agent/hooks/guard_paths.py (segundo root en _is_protected_path /
  _is_within_repo)
- tests/test_guard_paths.py (6+ tests nuevos: 2 regresion, 1 fail-closed,
  1 paridad sin segundo root, 1 valor malformado, 1 patterns protegidos
  sobre el segundo root)

## Read/inspect only

.agent/hooks/claude_guard_entry.py (entry+bootstrap, NO se toca),
.agent/agents.json, .agent/motor_checkpoint.py (fuente del patron
resolve_destino_root, solo lectura), runtime/project_root.py (fuente de
la semantica de AGENT_PROJECT_ROOT, solo lectura, NO se importa desde el
hook), tests/unit/test_claude_guard_entry.py (debe seguir verde sin
modificacion).

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion Global". No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de
los comandos exactos.
