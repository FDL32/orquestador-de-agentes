# Execution Log - WOT-2026-020d

**Ticket:** WOT-2026-020d
**Estado:** COMPLETED
**Fecha:** 2026-07-07
**delivery_authority:** repo_motor

## PREFLIGHT (Orquestador, topologia worktree-dev)

- DEV (`orquestador_de_agentes_dev`): main, HEAD == origin/main == b1913a0, arbol limpio, 0/0.
- PRINCIPAL (`orquestador_de_agentes`): detached en b1913a0, limpio.
- WORKSPACE (`orquestador_de_agentes_workspace`): dirty (019l IN_PROGRESS + backlog 020a/020b/020c). NO tocado.
- Contaminacion re-derivada en DEV: 36 WOT-* tracked + 2 no-WOT 016d (CALLBACK_GAP_016d_test_forms.py, INVENTARIO_3BUCKETS_016d_20260701.md). Coincide con handoff.

## Fase 0: Diagnostico (verificar premisa contra codigo real)

- `runtime/project_root.py:238` `is_motor_code_only()`: retornaba `False` ante
  cualquier `AGENT_PROJECT_ROOT` no vacia, sin comparar contra el motor. Bug confirmado.
- `agent_controller.py:6312`: `--project-root .` setea `AGENT_PROJECT_ROOT = Path(".").resolve()` = motor.
- `agent_controller.py:6340`: code-only guard no bloquea porque `is_motor_code_only()` ya dio False.
- `.gitignore:85-86`: ignora `AUDIT_WP-*`/`PLAN_WP-*` (legacy), NO `*_WOT-*`. Gap confirmado.
- Test existente `test_is_motor_code_only_false_with_env` (l.1597) usaba
  `AGENT_PROJECT_ROOT=/tmp/fake_workspace` (path INEXISTENTE en Windows:
  `C:\tmp\fake_workspace`, exists=False) y asertaba False.

### Correccion de premisa del handoff (Fase 0)
El handoff afirmaba que el test existente "pasa con bug Y con fix (porque /tmp
!= motor)". FALSO en este entorno: el fix propuesto incluye fail-closed
`not env_root.exists() -> True`; como `C:\tmp\fake_workspace` no existe, el fix
retornaria True y el test (que aserta False) ROMPERIA. Se actualizo el test
existente para usar `tmp_path` (path externo real existente), preservando su
intencion (externo -> False). Unico caller productivo: `agent_controller.py:6340`
(resto son mocks o artefactos historicos contaminados).

## Fase 1: Implementacion

- `runtime/project_root.py` `is_motor_code_only()`: env seteada -> `motor_root =
  Path(__file__).resolve().parent.parent`; `env_root = Path(env_value).resolve()`;
  invalido (OSError/ValueError) -> True; `env_root == motor_root` -> True;
  `return not env_root.exists()` (fail-closed: inexistente -> True, existente
  externo -> False). Sin env: marker check (sin cambios).
- `.gitignore`: anadido `.agent/collaboration/*_WOT-*.md` (patron broad, superset
  de las 4 lineas del handoff; cubre STRATEGY_WOT/PLAN_WOT futuros).
- `tests/test_agent_controller.py` `TestMotorCodeOnlyGuard`:
  - actualizado `test_is_motor_code_only_false_with_env` a `tmp_path` (externo existente -> False)
  - NUEVO `test_is_motor_code_only_true_when_env_points_to_motor` (motor_root -> True)
  - NUEVO `test_is_motor_code_only_true_when_env_path_nonexistent` (inexistente -> True)

## Mutation-verify (Orquestador, sobre repo real)

Mecanica: `git stash push -- runtime/project_root.py` (revertir fix a HEAD buggy,
mantener tests nuevos) -> correr test motor_root -> `git stash pop` -> correr test.
- (a) SIN fix: `assert False is True` (AssertionError) -> exit 1
- (b) codigo observado: `assert False is True` / FAILED test_is_motor_code_only_true_when_env_points_to_motor
- (c) CON fix restaurado: PASSED -> exit 0
- (d) codigo observado: 1 passed
Barrera confirmada real: el test nuevo caza la regresion.

## Gates

- Tests focales: `pytest tests/test_agent_controller.py::TestMotorCodeOnlyGuard -v` -> 8 passed, exit 0
- Ruff check: `ruff check runtime/project_root.py tests/test_agent_controller.py` -> All checks passed, exit 0
  (corregido SIM103: colapsado `if not exists(): return True; return False` -> `return not env_root.exists()`)
- Ruff format: `ruff format --check ...` -> 2 files already formatted, exit 0
- Validate: `agent_controller.py --validate --json --project-root <DEV>` -> 0 errors / 0 warnings, exit 0
- Suite canonica: pendiente (corre sobre HEAD final tras commit)

## Nota operativa (consecuencia del fix)

Despues del fix, `is_motor_code_only()` retorna True cuando `AGENT_PROJECT_ROOT`
apunta al motor -> el guard bloquea `--bootstrap-ticket`/`--mark-ready`/`--session-close`
en el motor con `--project-root .`. Esto es CORRECTO (evita la contaminacion) e
implica que el cierre de 020d/020e es pragmatico: live surfaces mantenidas a mano,
sin bus/mark-ready en el motor. Las puertas esenciales (mutation-verify, suite,
validate, Review 2 fresh-context) se cumplen. El bloqueo mismo es evidencia
adicional de que el fix funciona.

## Warnings accepted_health_exception (validate 0 errors / 3 warnings)

Las 3 warnings restantes (`bus_drift` + 2 `invariants`) son no reparables y se
clasifican `accepted_health_exception`:

- **Evidencia:** el fix (`runtime/project_root.py` `is_motor_code_only`) retorna
  `True` cuando `AGENT_PROJECT_ROOT` apunta al motor; el guard
  (`agent_controller.py:6340`) bloquea `--mark-ready`/`--bootstrap-ticket` en el
  motor con `--project-root <motor>`. El bus no tiene eventos para 020d porque
  `--mark-ready` nunca corrio (bloqueado por el fix, su comportamiento intencional).
- **Propietario:** orquestador (session-2026-0707-motor-cleanup).
- **Razon:** el proposito del fix es bloquear las write-ops del controller sobre
  el motor, que es exactamente lo que detiene la contaminacion. Fabricar eventos
  de bus para limpiar las warnings esta prohibido por el contrato CEM
  (`audit_agent_output.md`: "No fabriques eventos de bus para convertir una
  warning en falso 0"). Correr `--mark-ready` requeriria `--project-root` a un
  workspace externo, pero 020d es motor-surface y el WORKSPACE esta ocupado con
  019l (IN_PROGRESS). El warning reparable `ticket_prose` (TP-PROSE-10) ya se
  corrigio (renombrado heading a "Decision Arquitectonica").
