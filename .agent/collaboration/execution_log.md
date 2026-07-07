# Execution Log: WOT-2026-020a

## Ticket
- **ID:** WOT-2026-020a
- **deliverable_type:** code
- **Scope:** motor/guard-paths-cwd-vs-operational-root

## Fase 0 - Verificacion de premisa (2026-07-07)

**Premisa del backlog:** guard_paths falla-cerrado como "fuera del repo" cuando
cwd=motor y target esta en repo_destino. El link vive en el destino, no en el
motor.

**Verificacion contra codigo real:**
- `claude_guard_entry.py:103` ejecuta guard_paths con `cwd=str(repo_root)` donde
  repo_root = nearest `.claude` ancestor = motor.
- `guard_paths.py:304` pasa `repo_root=Path.cwd()` = motor a `evaluate_tool_request`.
- `_is_protected_path` (l.199): si target no esta en repo_root, llama
  `_resolve_extra_root(repo_root)`.
- `_resolve_extra_root` Source 2 (l.149): busca link en
  `repo_root/.agent/config/motor_destination_link.json` -> NO EXISTE en el motor.
- Motor (DEV) verificado: `Test-Path .agent/config/motor_destination_link.json` = False.
- Link del destino (Aduanas_pedidos_agencias) verificado: tiene `motor_root` +
  `destination_root`, vive en `<destino>/.agent/config/`.
- **Premisa CONFIRMADA.** Source 2 nunca puede resolver cuando repo_root=motor.

## Implementacion

**Fix:** anadir Source 3 a `_resolve_extra_root` — camina ancestros del TARGET
buscando `motor_destination_link.json`, verifica `motor_root == repo_root`.
Extraida a helper `_resolve_destino_from_target` para complejidad < 10 (ruff C901).

**Archivos modificados:**
- `.agent/hooks/guard_paths.py`: +30 lineas (helper + Source 3 call + docstring)
- `tests/test_guard_paths.py`: +65 lineas (5 tests nuevos en TestExtraRootViaTargetLink)

**Call site modificado:**
- `_is_protected_path` l.200: `_resolve_extra_root(repo_root, path_obj)`

## Gates

- ruff check: All checks passed!
- ruff format: 1 file reformatted
- Tests focales (guard_paths): 51 passed, 0 failed
- validate_agent_config.py: Configuration valid - all checks passed
- Suite canonica --level all: 3532 passed, 47 skipped, 0 failed, 0 errors (444s)

## Mutation-verify (orquestador sobre repo real)

1. Deshabilitar Source 3: `if path_obj is not None and False:`
2. `test_write_to_destino_via_target_link_allowed` -> FAILED (blocked=True, "fuera del repo")
3. 4 tests fail-closed -> PASSED (no dependen de Source 3)
4. Restaurar Source 3 -> 51/51 PASSED

**Veredicto:** mutation-verify confirma que el test nuevo detecta la regresion.

## Commits

- `WOT-2026-020a: guard_paths Source 3 - resolver destino desde link del target (motor_root == repo_root)`
- `WOT-2026-020a: tests TestExtraRootViaTargetLink (5 casos, fail-closed + happy path + mutation)`

## Decision

APROBADO para cierre pragmatico. El fix es fail-closed en todos los edge cases
(link malformado, motor_root != repo_root, ancestro sin marker). No amplía la
superficie de escritura mas alla de destinos verificados linkeados al motor.
