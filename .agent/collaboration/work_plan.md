# Plan de Trabajo: guard_paths cwd vs operational root

## Metadata
- **ID:** WOT-2026-020a
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-07
- **delivery_authority:** repo_motor

## Objetivo

Resolver el falso bloqueo de guard_paths cuando cwd=motor y el target esta en
repo_destino. En la topologia multi-root motor+destino, el link
`motor_destination_link.json` vive en el destino (no en el motor), con
`motor_root` apuntando al motor. `_resolve_extra_root` solo buscaba el link en
`repo_root` (Source 2), que no existe cuando repo_root=motor. Fix: anadir
Source 3 que camina los ancestros del TARGET buscando el link y verificando que
`motor_root == repo_root`.

## Files Likely Touched
- `.agent/hooks/guard_paths.py`
- `tests/test_guard_paths.py`

## Criterios binarios (DoD)
- [x] Write a un archivo del destino con cwd=motor -> permitido
- [x] Target fuera de motor Y de destino -> sigue bloqueado (fail-closed)
- [x] Test con monkeypatch de cwd + MUTATION (revertir -> vuelve a bloquear)

## Non-goals
- No ampliar superficie a dirs sin marker de repo (ligado a 019h)
- No tocar claude_guard_entry.py (el entrypoint ya pasa cwd=repo_root)

## Implementacion

Source 3 en `_resolve_extra_root`: extraida a helper `_resolve_destino_from_target`
para mantener complejidad ciclomatica < 10 (ruff C901). Fail-closed en todos los
casos: link malformado, motor_root != repo_root, ancestro sin marker.

## Mutation-verify
- Deshabilitar Source 3 (`if path_obj is not None and False:`)
- `test_write_to_destino_via_target_link_allowed` FAILS (blocked=True, "fuera del repo")
- Los 4 tests fail-closed siguen pasando (no dependen de Source 3)
- Restaurar Source 3 -> 51/51 pasan
