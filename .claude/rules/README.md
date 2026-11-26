---
paths:
  - ".claude/**"
  - ".env*"
  - "privada/**"
  - ".agent/hooks/**"
  - "scripts/pip_audit_project.py"
  - ".agent/collaboration/**"
  - "agent_system/refactor_kit/**"
  - "skills/**"
---
# Claude Code Rules (Modular Context)

> **Ojo: en Claude Code TODO `.md` de este directorio sin frontmatter `paths:` se autocarga en
> cada sesion** (no es "bajo demanda") y suma al gate Claude (`measure_agents_md_units.py` lo
> cuenta: `autoloaded_rules`). Aqui solo va lo que una sesion necesita siempre o
> casi siempre; lo condicional declara `paths:` y se carga solo al tocar superficies coincidentes.

## En este directorio:
- `00-startup.md` se autocarga en cada sesion (sin `paths:`).
- `01-security-architecture.md` es condicional (`paths:`) y se carga al tocar `.claude/**`, `.env*`, `privada/**`, `.agent/hooks/**` o `scripts/pip_audit_project.py`.
- `README.md` es indice/router condicional (`paths:`).

## Router (si tocas X, lee Y; no se autocarga):
- `.agent/collaboration/` (work_plan, logs, TURN, backlog): `.agent/rules/common/session_artifacts.md`.
  Cerrar ticket MUEVE su fila de `backlog.md` a `_archive/backlog_done.md` (estado terminal +
  `commit:<sha>`); ningun script lo hace; verifica con `check_backlog_contract.py`. NO es
  `.session/` (patron antiguo, ya no vigente).
- `agent_system/refactor_kit/` (solo stdlib, NUNCA importes del motor; valida con
  `ruff check agent_system/refactor_kit/`): `.agent/rules/common/refactor_kit.md`.
- `skills/` (frontmatter YAML con `triggers`, max 3; `python scripts/discover_skills.py --json`;
  `python scripts/orquestador.py --skill /review --query "revisa cambios"`): `.agent/rules/common/skills_discovery.md`.

## Referencias bajo demanda (fuera de aqui; leelas solo al entrar en su dominio):
- Backends y roles canonicos: `AGENTS.md`, seccion "Backends y roles".
- `.agent/rules/common/project_manifest_architecture.md`: si trabajas con `project_manifest.toml`, `.version_manifest.json` o deteccion/upgrade de proyectos.
- `.agent/rules/common/t3_ade_coordination.md`: si operas con sesiones T3 paralelas (multi-cuenta o multi-worktree) sobre el mismo vuelo o el mismo repo.
- Resto de reglas de referencia del motor: `.agent/rules/common/` (indexadas desde `AGENTS.md`).
- `.agent/rules/common/vuelo_pilares.md`: estado de pilares del vuelo infinito y su precedencia.

> **Nota para el Agente:** ver `CLAUDE.md` (raiz) para instrucciones de Claude Code especificas.
