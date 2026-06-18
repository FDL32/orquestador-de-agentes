# DEC-008G-001: Vocabulario canonico y naming por rol

**Ticket:** WOT-2026-008g
**Fecha:** 2026-06-18
**Estado:** DECIDED
**Autor:** Manager

## Contexto

El ecosistema `orquestador_de_agentes` usa "agente" para conceptos distintos:
backend IA, rol del pipeline y artefacto operativo. Esa polisemia complica los
renames de prompts/skills y hace que un mismo archivo parezca pertenecer a un
rol cuando en realidad es una herramienta transversal.

`DEC-008D-001` fijo reglas lexicas por tipo (`snake_case`, `kebab-case`,
actor-primero para acciones de pipeline), pero no escribio la regla
actor/family como vocabulario de producto. `WOT-2026-008g` formaliza ese
contrato antes de ejecutar nuevos renames.

## Decision

### 1. Vocabulario canonico

| Termino | Significado | No usar como |
|---------|-------------|--------------|
| backend IA | Claude Code, Codex, Copilot u otro LLM/IDE que ejecuta trabajo | rol de pipeline |
| rol | orchestrator, manager, builder, auditor, user | backend IA |
| artefacto | prompt, skill, script, gate, DEC, work_plan | agente |
| supervisor | actor runtime del bus ya existente (`bus/supervisor.py`, `actor="SUPERVISOR"`) | rol humano/orchestrator |
| usuario | persona humana que opera el sistema | backend IA |

Regla de uso: evitar "agente" como comodin. Usar "backend IA" para Claude
Code/Codex/Copilot, "rol" para builder/manager/orchestrator/auditor/user y
"artefacto" para prompts, skills, scripts y gates.

### 2. Roles canonicos

| Rol | Descripcion | Prefijo prompt | Prefijo skill actual | Prefijo skill futuro |
|-----|-------------|----------------|----------------------|----------------------|
| orchestrator | Coordina sesiones, bootstrap, cierre y handoffs | `orchestrator_` | n/a | n/a |
| manager | Forma contratos y revisa implementaciones | `manager_` | `man-` | `manager-` si un ticket posterior lo confirma |
| builder | Implementa el contrato aprobado | `builder_` | `bui-` | `builder-` si un ticket posterior lo confirma |
| auditor | Audita adversarialmente artefactos o procesos | `auditor_` solo si el artefacto es propiedad del rol | familia audit actual | role frontmatter en ticket posterior |
| user | Humano que decide o desbloquea | `user_` si aparece un artefacto propio | n/a | n/a |

Un mismo backend IA puede encarnar varios roles. La clasificacion describe
propiedad del artefacto, no capacidad del backend.

### 3. Supervisor es runtime

`supervisor` queda reservado para componentes runtime y bus. Ya existe en
`bus/supervisor.py`, `supervisor_state.json` y eventos con `actor="SUPERVISOR"`.
Esta DEC documenta ese uso; no lo redefine ni lo traslada a prompts.

### 4. Regla actor-primero / family-primero

Esta DEC formaliza una regla implicita en `_PIPELINE_ACTIONS` y en el
comportamiento de `discover_skills.py --check-naming`.

- Actor-primero: cuando el artefacto pertenece principalmente a un rol.
  Ejemplos: `manager_review.md`, futuros `orchestrator_launch_builder.md`.
- Family-primero: cuando el artefacto es una herramienta transversal de tarea.
  Ejemplos: `audit_*`, `memory_*`, `contract_formation_*`.
- Criterio de desempate: si el artefacto es una herramienta reutilizable de
  tarea, family gana aunque hoy la use un solo rol.

`audit_*` es familia de tarea transversal, no propiedad del rol auditor. Por
eso `audit_ticket_contract.md` no pasa a `auditor_ticket_contract.md`: lo usa el
Manager antes de Builder. `audit_agent_output.md` tampoco pasa a `auditor_*`
porque lo usan varios roles.

### 5. Tabla congelada de prompts

Estado verificado del arbol `prompts/` al crear la DEC: 21 archivos fisicos,
19 canonicos/operativos y 2 legacy stubs (`audit_plan.md`,
`review_manager.md`).

| Archivo fisico | Clasificacion canonica | Nota |
|----------------|------------------------|------|
| `launch_builder.md` | future `orchestrator_launch_builder.md` | rename en lote posterior |
| `orchestrator_pipeline.md` | `orchestrator_pipeline.md` | ya canonico; no se renombra; pipeline transversal del orchestrator |
| `session_bootstrap.md` | future `orchestrator_session_bootstrap.md` | rename en lote posterior |
| `session_close_chat.md` | future `orchestrator_session_close_chat.md` | rename en lote posterior |
| `destination_bootstrap.md` | future `orchestrator_destination_bootstrap.md` | rename en lote posterior |
| `refactor_bootstrap.md` | future `orchestrator_refactor_bootstrap.md` | rename en lote posterior |
| `manager_review.md` | `manager_review.md` | canonico desde 008e |
| `audit_agent_output.md` | `audit_*` family | transversal |
| `audit_bus.md` | `audit_*` family | transversal |
| `audit_cf_plan_graph.md` | `audit_*` family | contract formation |
| `audit_cf_repo_charter.md` | `audit_*` family | contract formation |
| `audit_cf_ticket_contract.md` | `audit_*` family | contract formation |
| `audit_complete_motor_destination.md` | `audit_*` family | transversal |
| `audit_git_publication.md` | `audit_*` family | transversal |
| `audit_pipeline.md` | `audit_*` family | transversal |
| `audit_plan.md` | `audit_*` family | legacy stub alias dentro de la familia audit |
| `audit_post_change_system_health.md` | `audit_*` family | transversal |
| `audit_ticket_contract.md` | `audit_*` family | canonico del contrato de ticket |
| `memory_upload.md` | `memory_*` family | herramienta reutilizable |
| `contract_formation_pipeline.md` | `contract_formation_*` family | pipeline transversal |
| `review_manager.md` | legacy stub alias | alias de `manager_review.md` |

Resumen: 6 `orchestrator_*` relacionados (5 futuros renames y 1 ya canonico),
1 `manager_*`, 11 `audit_*` family (incluye `audit_plan.md` como stub-in-family),
1 `memory_*` family, 1 `contract_formation_*` family y 1 legacy stub adicional
(`review_manager.md`).

### 6. Plan de lotes con shims

Los renames se ejecutan en tickets posteriores con shims/versionado y baseline
de consumidores antes/despues.

| Ticket | Alcance propuesto | Nota |
|--------|-------------------|------|
| 008h | Renombrar 5 prompts de orchestrator | `orchestrator_pipeline.md` ya es canonico y no entra en el rename |
| 008i | Expandir `man-*` a `manager-*` | solo si la DEC final confirma que el coste compensa |
| 008j | Expandir `bui-*` a `builder-*` | solo si la DEC final confirma que el coste compensa |
| 008k | Formalizar `role: auditor` en frontmatter de skills auditoras | sin rename de directorio salvo nuevo contrato |

El blast radius de `man-*`/`bui-*` se estima alto (158 referencias
aproximadas), por lo que no se ejecuta en esta DEC.

### 7. AGENTS.md

`AGENTS.md` debe distinguir "Backends y roles" en vez de agrupar todo como
"Agentes disponibles". Esa seccion es la superficie transversal que los agentes
leen al arrancar.

## Consecuencias

- Reduce ambiguedad conceptual antes de renombrar prompts/skills.
- Mantiene `audit_*` como familia transversal porque refleja mejor el uso real.
- Reserva `supervisor` para runtime y evita mezclarlo con orchestrator.
- Deja deuda explicitamente serializada para 008h-008k.

## Non-goals

- No renombrar prompts, skills ni scripts en 008g.
- No tocar frontmatter.
- No modificar `discover_skills.py`, `_PIPELINE_ACTIONS`, bus ni runtime.
- No cerrar automaticamente la deuda de `man-`/`bui-`.

## Gates esperados

- `python scripts/discover_skills.py --check-naming`
- `python scripts/check_encoding_guard.py docs/decisions/DEC-008G-001-vocabulary-and-role-naming.md AGENTS.md`
- `python .agent/agent_controller.py --validate --json --project-root <repo_destino>`
