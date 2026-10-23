# Claude Code Rules (Modular Context)

> **Ojo: en Claude Code TODO `.md` de este directorio sin frontmatter `paths:` se autocarga en
> cada sesion** (no es "bajo demanda"), y suma al contexto de arranque frio aunque el medidor
> `measure_agents_md_units.py` no lo cuente. Aqui solo va lo que una sesion necesita siempre o
> casi siempre; lo condicional vive en `.agent/rules/common/` (no se autocarga).

## En este directorio (se autocargan en Claude Code):
- `00-startup.md`: protocolo de inicio, carga de memoria y quality gates.
- `01-security-architecture.md`: si tocas variables de entorno, hooks o permisos.
- `03-skills-discovery.md`: si disenas o modificas micro-habilidades bajo `skills/`.
- `04-refactor-kit.md`: si utilizas el refactor kit portable.
- `05-session-artifacts.md`: ciclo de vida de `.agent/collaboration/` y sus logs.

## Referencias bajo demanda (fuera de aqui; leelas solo al entrar en su dominio):
- Backends y roles canonicos: `AGENTS.md`, seccion "Backends y roles".
- `.agent/rules/common/project_manifest_architecture.md`: si trabajas con `project_manifest.toml`, `.version_manifest.json` o deteccion/upgrade de proyectos.
- `.agent/rules/common/t3_ade_coordination.md`: si operas con sesiones T3 paralelas (multi-cuenta o multi-worktree) sobre el mismo vuelo o el mismo repo.
- Resto de reglas de referencia del motor: `.agent/rules/common/` (indexadas desde `AGENTS.md`).

> **Nota para el Agente:** ver `CLAUDE.md` (raiz) para instrucciones de Claude Code especificas.
