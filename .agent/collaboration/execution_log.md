# Execution Log - WP-2026-157

## Metadata
- **ID:** WP-2026-157
**Estado:** COMPLETED
- **deliverable_type:** mixed

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** ECC capability pack - deep-research skill, AP contract and minimal EDD

## Fases
- Phase 1: crear y registrar la skill `deep-research`.
- Phase 2: formalizar el contrato AP/observations y anadir el validador.
- Phase 3: crear el harness minimo de regresion en `tests/evals/`.

## Registro de Implementacion
- Ticket nuevo preparado para Builder con alcance ECC-inspired, pero acotado a utilidades reales del sistema.
- La skill `deep-research` debe ser documental y no debe tocar el runtime de produccion.
- El contrato AP se formaliza sobre `ap-schema.md` sin cambiar el formato de almacenamiento.
- El harness EDD minimo debe permanecer aislado y opt-in.
- `.gitignore` debe excluir `.agent/runtime/research/` para no ensuciar el working tree.
- Cada eval file debe apuntar a un contrato concreto, no a una categoria abstracta.

## Calidad Esperada
- `python scripts/discover_skills.py --json`
- `python scripts/validate_observations.py`
- `pytest -m eval tests/evals/ -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de Aceptacion
- [ ] `deep-research` aparece en el discovery de skills y queda registrado en `skills/README.md`.
- [ ] `validate_observations.py` pasa con el `observations.jsonl` actual.
- [ ] `pytest -m eval tests/evals/ -q` pasa con fixtures aisladas.
- [ ] La suite safe principal sigue pasando sin depender de los evals.
- [ ] La validacion canonica pasa sin errores.

## Evidencia de Implementacion
- Fase 1 COMPLETADA: `skills/deep-research/SKILL.md`, `skills/deep-research/references/research-template.md`, `skills/README.md` actualizado.
- Fase 2 COMPLETADA: `skills/_shared/ap-schema.md` formalizado con campos obligatorios/opcionales, `scripts/validate_observations.py` creado, `tests/unit/test_validate_observations.py` creado.
- Fase 3 COMPLETADA: `pytest.ini` con marker `eval`, `tests/evals/__init__.py` y 4 modulos de tests creados (`test_eval_review_bridge.py`, `test_eval_guard_paths.py`, `test_eval_scope_gate.py`, `test_eval_requeue.py`).
- Quality gates:
  - `python scripts/validate_observations.py` -> `Validacion EXITOSA: runtime\\memory\\observations.jsonl es valido`
  - `python -m pytest tests\\unit\\test_validate_observations.py tests\\evals\\test_eval_guard_paths.py tests\\evals\\test_eval_requeue.py -q` -> `59 passed`
  - `python -m pytest -m eval tests\\evals\\ -q` -> `37 passed`
  - `python scripts/run_pytest_safe.py` -> `257 passed`
  - `python .agent/agent_controller.py --validate --json --force` -> `0 errors, 1 warning expected (BUILDER_EXIT invariant)`
- Validacion canonica: `agent_controller --validate` pasa sin errores.


Scope override: Files Likely Touched list includes all implemented files; scope gate detected directory paths instead of specific files. Affected files: C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\scripts\validate_observations.py, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\skills\deep-research, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\tests\evals, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\tests\unit\test_validate_observations.py
Nota de alcance: los cambios en `.agent/hooks/guard_paths.py` y `bus/supervisor.py` son refactors de testabilidad necesarios para exponer `evaluate_tool_request()` y `requeue_ticket()`; el comportamiento externo se mantiene equivalente y los tests eval ejercitan esos contratos sin subprocess real ni bus de produccion.

Manager requested changes (1 rejections)


Scope override: WP-2026-157 hotfix/correcciones solicitadas por Manager y consolidacion de evidencia de review. Affected files: C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\AUDIT_WP-2026-156.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\PLAN_WP-2026-156.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\_archive\plan_audit\AUDIT_WP-2026-156.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\_archive\plan_audit\PLAN_WP-2026-156.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\hooks\guard_paths.py, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\bus\supervisor.py, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\scripts\validate_observations.py, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\skills\deep-research, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\tests\evals, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\tests\unit\test_validate_observations.py


Manager approved canonical closeout for WP-2026-157