# Work Plan - WOT-2026-018b

## Metadata
- **ID:** WOT-2026-018b
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Aislar test_negative_no_commit_no_diff del work_plan.md real (hotfix preexisting gate unblock: CI rojo clavado en main)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Desbloquear el gate de CI (suite canonica verde en main), que quedo CLAVADO en rojo:
`tests/test_agent_controller.py::TestAgentControllerEvidence::test_negative_no_commit_no_diff`
falla de forma determinista porque lee el `work_plan.md` REAL para calcular
`deliverable_type`. Tras cerrar 018a (documentation), el work_plan committed en HEAD
es documentation -> `non_code_ticket=True` -> `_check_implementation_evidence` retorna
antes de emitir "No commit evidence" (early return, agent_controller.py ~L1705) -> el
assert de L2282 falla en cada CI run mientras el ultimo ticket committed sea
documentation/analysis/research.

Clasificacion (finding_triage_protocol): bug PREEXISTENTE que bloquea gate obligatorio,
fix de 1 linea, bajo riesgo, SOLO test, sin cambio de contrato/arquitectura ni
produccion -> "preexisting gate unblock". El test hermano `test_semantic_parity_positive`
ya usa el mismo patron de aislamiento (mockear `read_file`).

## Decision Arquitectonica

- Causa raiz = defecto de AISLAMIENTO del test, NO de produccion. `_check_implementation_evidence`
  se comporta correctamente; el test simplemente no aisla su lectura del work_plan real.
- Fix = mockear `agent_controller.read_file` a `lambda x: ""` tras los setattr de roots, para
  que `deliverable_type` sea vacio (-> non_code_ticket=False -> el flujo llega a "No commit
  evidence"). Identico patron que el hermano en tests/test_agent_controller.py L410.
- NO se toca produccion (agent_controller.py, bus/evidence.py): ampliarla seria scope creep.

## Fases

### Fase 1 - Fix del aislamiento
- En `test_negative_no_commit_no_diff`, anadir
  `monkeypatch.setattr(agent_controller, "read_file", lambda x: "")` tras los setattr de
  `_MOTOR_ROOT`/`PROJECT_ROOT`, con comentario del porque.

### Fase 2 - Verificacion (barrera FAIL-sin/PASS-con)
- CON el mock: el test pasa (ambos asserts: "No commit evidence" + "No implementation evidence").
- SIN el mock: el test vuelve a fallar cuando el work_plan real es documentation/analysis
  (demuestra que el mock es la barrera, no cosmetico).
- La clase entera `TestAgentControllerEvidence` sigue verde (no rompe hermanos).

## Criterios de aceptacion

Criterios binarios (DoD):

1. `test_negative_no_commit_no_diff` PASA independientemente del `deliverable_type` del
   work_plan.md real (verificado con work_plan committed = documentation).
2. BARRERA: sin el mock `read_file`, el test falla con work_plan real documentation/analysis
   (FAIL-sin), y pasa con el mock (PASS-con). Ambos estados verificados.
3. La clase `TestAgentControllerEvidence` completa sigue verde (8 passed).
4. NO se toca produccion (`agent_controller.py`, `bus/evidence.py`): solo el archivo de test.
5. `ruff check` + `ruff format --check` verdes sobre el test tocado.
6. Suite canonica `run_pytest_safe.py --level all` exit 0 (el rojo clavado desaparece).
7. `validate --json --project-root <motor>` = 0 errors / 0 warnings.

## Files Likely Touched

### repo_motor
- `tests/test_agent_controller.py`

## Read/inspect only

- `.agent/agent_controller.py` (`_check_implementation_evidence`, ~L1697-1733: el early return
  por non_code_ticket que causa el sintoma).
- `tests/test_agent_controller.py` L405-411 (patron de aislamiento del test hermano
  `test_semantic_parity_positive`).

## Non-goals

- NO tocar `_check_implementation_evidence` ni la logica de produccion (el comportamiento en
  produccion es correcto; el gap es del test). Ampliarla seria scope creep.
- NO anadir otros mocks ni refactorizar el test mas alla de la linea de aislamiento.
- NO mezclar con 016b (hook obsoleto) ni otros tickets de la serie.
