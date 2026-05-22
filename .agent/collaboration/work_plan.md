# Work Plan - WP-2026-127

## Metadata
- **ID:** WP-2026-127
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** State revision, approval timeout and skill filtering

## Objetivo
Implantar revision explicita por artefacto, aprobaciones con timeout configurable y filtrado de skills por rol para reducir drift, bloqueos y ruido de contexto.

## Decision Arquitectonica
- La revision valida es por artefacto JSON/Markdown, no global por bus.
- Las escrituras de estado deben ser atomicas y con control de concurrencia optimista.
- La expiracion de aprobacion debe seguir una politica configurable por tipo de escalacion.
- El filtrado de skills debe resolverse en el catalogo/routing de skills, no en el transporte de review.

## Files Likely Touched
- `bus/supervisor.py`
- `bus/event_bus.py`
- `bus/exceptions.py`
- `bus/approval.py`
- `bus/skill_resolver.py`
- `bus/review_bridge.py`
- `.agent/agent_controller.py`
- `.agent/agents_config.py`
- `scripts/ticket_supervisor.py`
- `scripts/discover_skills.py`
- `.agent/config/agents.json`
- `tests/test_supervisor.py`
- `tests/test_manager_review_bridge.py`
- `tests/unit/test_agents_config.py`
- `tests/unit/test_skill_discovery.py`
- `tests/test_orquestador_scope.py`
- `tests/unit/test_review_budget_retry.py`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WP-2026-127.md`
- `.agent/collaboration/AUDIT_WP-2026-127.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `PROJECT.md`

## Fases
1. Implementar `expectedRevision` por artefacto en estados JSON con escritura atomica y retry OCC.
2. Introducir skill filtering por rol reutilizando `discover_skills.py` y validacion temprana de skills.
3. Implementar pipeline de aprobacion con timeout configurable, razon de expiracion y resolucion canonica.

## Calidad
- `ruff check .`
- `pytest`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- Un write con revision desfasada falla sin sobrescribir el artefacto.
- Cada rol solo ve las skills permitidas por su allowlist.
- Una aprobacion pendiente expira segun politica y materializa el estado correcto con trazabilidad de causa.
- La documentacion canonica y el bus quedan sincronizados.

## Nota
WP-2026-126 queda como referencia historica; este ticket abre la siguiente fase de robustez del motor.
