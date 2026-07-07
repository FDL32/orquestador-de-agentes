# Work Plan

## Metadata
- **ID:** WOT-2026-019h
- **Estado:** COMPLETED
- **deliverable_type:** code
- **delivery_authority:** repo_motor

## Objetivo

`_resolve_extra_root` (guard_paths.py l.108-143) acepta como segundo root valido
CUALQUIER directorio existente al que apunte `AGENT_PROJECT_ROOT` (o
`destination_root` del link), sin exigir que sea un repo real. Fix: exigir que el
candidate contenga `.claude` o `.git` antes de aceptarlo (mismo marker que
`resolve_repo_root` del entry usa para el primer root).

## Root cause

`_resolve_extra_root` solo verifica `.exists()` (l.128 y l.143). No verifica
marker de repo. Un `AGENT_PROJECT_ROOT` mal seteado apuntando a un dir amplio
(p.ej. `C:\Users\<user>` o un tmp) ampliaria la superficie de escritura del guard
mas alla de un repo conocido. `resolve_repo_root` (claude_guard_entry.py:37-43)
SI usa `.claude` como marker para el primer root.

## Files Likely Touched

- `.agent/hooks/guard_paths.py`
- `tests/test_guard_paths.py`

## Read/inspect only

- `.agent/hooks/claude_guard_entry.py` (resolve_repo_root, marker de referencia)

## Criterios binarios de aceptacion

- [ ] `_resolve_extra_root` con `AGENT_PROJECT_ROOT`=<dir sin `.claude`/`.git`>
      devuelve `None`; un Write bajo ese dir sigue bloqueado ("fuera del repo")
- [ ] `_resolve_extra_root` con `AGENT_PROJECT_ROOT`=<repo con `.claude`> sigue
      devolviendo ese root (los 6 tests de 019a siguen verdes)
- [ ] mutation: revertir el check de marker -> el dir arbitrario vuelve a
      aceptarse -> el test fail-closed nuevo FALLA
- [ ] `validate --json` da 0 errors / 0 warnings
- [ ] `ruff check` pasa sobre archivos Python tocados
- [ ] Suite canonica: `run_pytest_safe.py --level all` exit 0, tested_commit_sha == HEAD

## Non-goals

- No cambiar la fuente del segundo root (sigue siendo
  `AGENT_PROJECT_ROOT`/`destination_root`)
- No tocar `claude_guard_entry.py` ni el bootstrap
- No relajar ningun otro check del guard

## Decision Arquitectonica

Se elige exigir `.claude` O `.git` (no solo `.claude`) porque algunos destinos
pueden no tener `.claude` si usan un backend distinto (Codex, OpenCode) pero si
tienen `.git`. El marker `.git` cubre el caso de un repo git sin `.claude`. Es
fail-closed: si el candidate no tiene ningun marker, se rechaza (None). Esto
preserva los 6 tests de 019a (que crean `.claude` en `destino_root`) y anade la
barrera contra dirs arbitrarios sin marker.

## TP Check

- TP-01: Premisa verificada en codigo real (_resolve_extra_root l.108-143 solo
  verifica .exists(), sin marker; resolve_repo_root l.37-43 SI usa .claude)
- TP-02: Fix mecanico claro: anadir check `(candidate / ".claude").exists() or
  (candidate / ".git").exists()` antes de retornar el candidate
- TP-03: Tests de regresion: AGENT_PROJECT_ROOT=<dir sin marker> -> None;
  AGENT_PROJECT_ROOT=<dir con .git> -> aceptado
- TP-04: Mutation-verify: revertir el check de marker -> dir sin marker aceptado
- TP-05: No romper los 6 tests de 019a (destino_root tiene .claude)
