# Work Plan

## Metadata
- **ID:** WOT-2026-020d
- **Estado:** COMPLETED
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Origen:** handoff C:\tmp\HANDOFF_20260707_motor_cleanup.md

## Objetivo

Cerrar la causa raiz 1 de la contaminacion del motor: `is_motor_code_only()`
(`runtime/project_root.py`) no verificaba que `AGENT_PROJECT_ROOT` apunte a un
workspace EXTERNO distinto del motor. Ejecutar `--bootstrap-ticket --project-root .`
desde el motor seteaba `AGENT_PROJECT_ROOT` al motor mismo, el guard retornaba
`False` y permitia escribir artefactos WOT-* en `repo_motor/.agent/collaboration/`.

Causa raiz 2 (gap de `.gitignore`) se cierra en este mismo ticket: el `.gitignore`
ignoraba `AUDIT_WP-*`/`PLAN_WP-*` (legacy) pero no `*_WOT-*`, asi los artefactos
WOT se trackeaban sin barrera. La limpieza de los 38 archivos ya commiteados es
WOT-2026-020e (prerrequisito: este ticket cierra el `.gitignore`).

## Root cause

`is_motor_code_only()` (l.238) retornaba `False` ante cualquier
`AGENT_PROJECT_ROOT` no vacia, sin comparar contra el motor. Cadena de fallo:
`--project-root .` desde el motor -> `AGENT_PROJECT_ROOT = Path(".").resolve()`
= motor (agent_controller.py:6312) -> `is_motor_code_only()` = False (l.238-239)
-> code-only guard no bloquea `--bootstrap-ticket` (l.6340) -> artefactos WOT-*
escritos en `repo_motor/.agent/collaboration/` y commiteados.

## Files Likely Touched
- `runtime/project_root.py`
- `.gitignore`
- `tests/test_agent_controller.py`

## Read/inspect only
- `.agent/agent_controller.py` (guard l.6340, set env l.6312)

## Criterios binarios de aceptacion
- [x] `is_motor_code_only()` con `AGENT_PROJECT_ROOT=motor_root` -> True
- [x] `is_motor_code_only()` con `AGENT_PROJECT_ROOT=externo existente` -> False
- [x] `is_motor_code_only()` con `AGENT_PROJECT_ROOT=inexistente` -> True (fail-closed)
- [x] mutation-verify: revertir fix -> test motor_root falla (exit 1); restaurar -> pasa (exit 0)
- [x] `.gitignore` ignora `*_WOT-*.md` en `.agent/collaboration/` (patron broad, cubre AUDIT/PLAN/execution_log/work_plan/STRATEGY WOT-*)
- [x] validate 0/0, ruff check limpio, suite canonica exit 0

## Non-goals
- No limpiar los 38 archivos contaminados (es WOT-2026-020e, despues de este ticket)
- No relajar el guard a warning-only: sigue bloqueante
- No usar `resolve_project_root()` para motor_root en el fix (lru_cache); usar `Path(__file__)`
- No usar `Path(__file__).parent.parent.parent` (daria Proyectos_Python); usar `parent.parent`
- No crear AUDIT_WOT-2026-020d.md / PLAN_WOT-2026-020d.md (evita nueva contaminacion)

## Decision Arquitectonica
- `motor_root = Path(__file__).resolve().parent.parent`: deterministico, independiente
  del lru_cache de `resolve_project_root()` (que puede retener el path del motor tras
  re-inyeccion de `--project-root`).
- fail-closed para path invalido (`OSError`/`ValueError`) e inexistente: un
  `AGENT_PROJECT_ROOT` que no resuelve a un workspace real se trata como code-only.
- `.gitignore`: patron broad `*_WOT-*.md` (1 linea) en vez de 4 lineas especificas
  del handoff. Cubre STRATEGY_WOT-*/PLAN_WOT-* futuros (latente en
  `prompts/orchestrator_launch_builder.md`); las live surfaces sin sufijo `_WOT`
  (STATE/TURN/execution_log/work_plan/notifications/review_queue) quedan trackeadas.

## TP Check
- TP-01: Premisa verificada contra codigo real (project_root.py:238, agent_controller.py:6312/6340)
- TP-02: Fix mecanico: env seteada -> comparar contra motor_root + fail-closed exists()
- TP-03: Tests: motor_root->True (NUEVO, caza regresion), inexistente->True (NUEVO), externo existente->False (actualizado a tmp_path)
- TP-04: Mutation: revertir fix -> test motor_root falla (exit 1); restaurar -> pasa (exit 0)
- TP-05: Fase 0 corrigio premisa del handoff: test existente false_with_env usaba path inexistente y romperia con fail-closed; actualizado a tmp_path
