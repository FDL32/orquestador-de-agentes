# Work Plan - WOT-2026-016b

## Metadata
- **ID:** WOT-2026-016b
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Hook pre-commit/pre-push con INSTALL_PYTHON obsoleto: detectar/regenerar cuando la ruta del interprete del hook no existe (repo movido)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

El hook generado por pre-commit hardcodea `INSTALL_PYTHON=<ruta al interprete>` en la
plantilla (linea 7 de `.git/hooks/pre-commit` y `.git/hooks/pre-push`). Si el repo se MUEVE,
esa ruta queda obsoleta y no existe en disco -> el hook cae al fallback `command -v pre-commit`
del PATH, cuyo launcher puede estar roto (en esta maquina resuelve al shim conda roto
`nsight-compute\python.bat`) -> commits/push fallan o resuelven ruidosamente al interprete
equivocado.

Estado REAL de este repo (VERIFICADO EN VIVO 2026-07-02):
- `.git/hooks/pre-commit` L7: `INSTALL_PYTHON='...\orquestador_de_agentes\.venv\Scripts\python.exe'`
  -> la ruta EXISTE (regenerada en 017a). pre-commit funciona.
- `.git/hooks/pre-push` L7: `INSTALL_PYTHON='...\z_scripts\orquestador_de_agentes\.venv\Scripts\python.exe'`
  -> ruta OBSOLETA (el repo ya no vive en `z_scripts\`); NO existe. Hook roto vivo.

El repo no detecta ni avisa de la ruta obsoleta: el siguiente repo movido reproducira el fallo.

Clasificacion (finding_triage_protocol): ticket propio con contrato en backlog, deliverable
`code`, bajo riesgo, superficie nueva acotada (un check + su test). No reescribe historia, no
toca remoto, no versiona `.git/hooks/*`.

## Decision Arquitectonica

- El fix NO es versionar el hook generado (`.git/hooks/*` es local, no versionable) ni "arreglar
  a mano" el pre-push (eso solo cura este repo, no la clase de bug). El fix es un CHECK que
  detecta que el `INSTALL_PYTHON` de un hook generado no existe en disco y (a) FALLA con mensaje
  accionable, o (b) REGENERA los hooks via `pre_commit install --overwrite`.
- El check DEBE cubrir AMBOS tipos (pre-commit Y pre-push), no solo el que hoy esta bien.
- Se implementa como script standalone `scripts/check_hook_interpreter.py` siguiendo la
  convencion de `scripts/check_*.py` (funciones puras + `main(argv) -> int`, fail-closed,
  UTF-8/ASCII). Modo por defecto `--check` (exit != 0 con mensaje si algun interprete falta);
  modo `--fix` regenera via `pre_commit install --overwrite --hook-type pre-commit --hook-type
  pre-push`.
- Enganche en `.pre-commit-config.yaml` como hook LOCAL en stage `manual` (no automatico):
  un hook automatico seria circular (el propio hook roto no puede invocar de forma fiable al
  check). El stage manual lo hace ejecutable por tooling de instalacion / bajo demanda sin
  anadir un gate obligatorio nuevo que relaje o duplique los existentes.

## Fases

### Fase 0 - Diagnostico (COMPLETADO)
- Confirmado: ningun codigo existente gestiona `INSTALL_PYTHON` ni corre `pre_commit install`
  (grep 0 hits) -> superficie nueva, no modificacion de seam existente.
- Confirmado formato estable de hook: L7 = `INSTALL_PYTHON='<path>'` en pre-commit y pre-push.
- Confirmada convencion de `scripts/check_*.py` y de `tests/test_check_*.py` (repos git reales
  en tmp_path via `subprocess`, import `from scripts import ...`).

### Fase 1 - Implementacion
- `scripts/check_hook_interpreter.py`:
  - `parse_install_python(hook_text) -> str | None`: extrae la ruta de la linea
    `INSTALL_PYTHON='...'` (tolera comillas simples/dobles y ausencia).
  - `check_hook(hooks_dir, hook_type) -> HookStatus`: lee el hook, parsea, comprueba
    `Path(interpreter).exists()`.
  - `check_all(hooks_dir) -> list[HookStatus]` sobre `("pre-commit", "pre-push")`.
  - `main(argv)`: `--hooks-dir` (default `<repo>/.git/hooks`), `--fix`. Sin `--fix`, exit 1 con
    mensaje accionable si algun hook presente tiene interprete inexistente; exit 0 cuando cada
    hook presente resuelve a un interprete existente (o el hook esta ausente). Con `--fix`,
    ejecuta `pre_commit install --overwrite` y re-verifica.

### Fase 2 - Tests (barrera FAIL-sin/PASS-con)
- `tests/test_check_hook_interpreter.py`:
  - hook con `INSTALL_PYTHON` inexistente -> `main` exit != 0 con mensaje (para pre-commit Y
    pre-push por separado -> cubre ambos tipos, DoD #2).
  - hook con `INSTALL_PYTHON` existente -> exit 0.
  - hook ausente -> exit 0 (no falso positivo).
  - MUTATION/barrera: comprobar que es la existencia del interprete lo que discrimina (mismo
    hook, interprete valido -> pass; interprete borrado -> fail).

## Criterios de aceptacion

Criterios binarios (DoD del backlog + refinados por evidencia en vivo):

1. Test que simula un hook con `INSTALL_PYTHON` a ruta INEXISTENTE y verifica que el check lo
   DETECTA (exit != 0 con mensaje accionable, o regeneracion efectiva).
2. El check cubre pre-commit Y pre-push (ambos tipos).
3. BARRERA: con interprete valido el check pasa; con interprete inexistente falla (demuestra que
   la existencia del interprete es el discriminante, no cosmetico).
4. `check_encoding_guard.py` exit 0 sobre los archivos tocados.
5. `ruff check` + `ruff format --check` verdes sobre los .py tocados.
6. Suite canonica `run_pytest_safe.py --level all` exit 0 (tested_commit_sha == HEAD).
7. `validate --json --project-root <motor>` = 0 errors / 0 warnings.

## Files Likely Touched

### repo_motor
- `scripts/check_hook_interpreter.py` (nuevo)
- `tests/test_check_hook_interpreter.py` (nuevo)
- `.pre-commit-config.yaml` (enganche del hook manual)

## Read/inspect only

- `.git/hooks/pre-commit`, `.git/hooks/pre-push` (formato del hook generado; NO versionar).
- `scripts/check_motor_pristine.py`, `scripts/check_ruff_hook_scope.py` (convencion de check).
- `tests/test_check_motor_pristine.py` (patron de test con repos reales).

## Non-goals

- NO versionar `.git/hooks/*` (es local, no versionable).
- NO "arreglar" solo pre-push a mano (cura este repo, no la clase de bug).
- NO anadir un gate automatico obligatorio nuevo ni relajar/duplicar gates existentes (el
  enganche es stage `manual`).
- NO tocar remoto ni reescribir historia.
- NO mezclar con 016c/016e/016g/016m ni otros tickets de la serie.
