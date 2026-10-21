# AGENTS.md - Instrucciones transversales

## Backends y roles

- **Backend IA:** producto o LLM que ejecuta trabajo. Ejemplos: Claude Code,
  Codex y GitHub Copilot. Un backend IA puede encarnar varios roles segun el
  turno del pipeline.
- **Roles canonicos, por categoria** (armonizado 2026-10-12 tras bucle
  adversarial de 3 lentes -- codex, nan-fs, opencode/glm -- sobre
  vocabulario de roles; ver Nota de enums de codigo abajo). Usa "rol
  builder" o "rol manager", no "agente builder":
  - **Pipeline secuencial de un ticket:** `orchestrator`, `manager`,
    `builder`, `auditor`.
  - **Capa de revision independiente (sistema de 4 capas/"personas"):**
    `revisor` (anadido WOT-2026-098b). Persona-2 (Revisor) del nucleo
    `prompts/agent_execution_modes.md` -- NUNCA el mismo backend/modelo que
    implemento (condicion dura, ver `prompts/persona_system.md` Seccion 2).
    Para entender la numeracion de personas 0/1/2/3 y su correlacion con
    las Capas del nucleo, lee la cadena completa: `prompts/
    agent_execution_modes.md` -> `prompts/persona_system.md`.
  - **Rol de gobierno/ensemble (no secuencial, no de pipeline de ticket):**
    `proposer` / `challenger` (lentes adversariales de bucles de gobierno:
    CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE, DESIGN_REVIEW). Ver
    `prompts/ensemble_loop.md`.
  - **Actor humano:** `user`. No es backend IA, no tiene model_id que
    resolver -- analogo a `ACTOR_RUNTIME_ROLES` (`SUPERVISOR`, ver abajo):
    actor fuera de los enums de codigo que validan backend, no un olvido.
- **Nota de enums de codigo (por que NO hay un enum 1:1 con esta lista):**
  existen 3 enums de codigo con nombres parecidos y dominios DISTINTOS por
  diseno (DEC-router-skills-001 Seccion 7; no se fusionan):
  `.agent/agents_config.py::CANONICAL_ROLES` (valida `role_mapping`/backend
  resolution), `scripts/discover_skills.py::CANONICAL_ROLES` (valida el
  campo `role` escalar del frontmatter de prompts) y `agents.json::
  ensemble_profiles` (perfiles `proposer`/`challenger`). Ninguno de los 3
  es, ni pretende ser, una copia literal de esta lista -- cada uno valida
  su propio dominio.
- **Supervisor:** actor runtime del bus ya existente (`bus/supervisor.py`,
  eventos `actor="SUPERVISOR"`). No es sinonimo de orchestrator ni de backend IA.
- **Artefactos:** prompts, skills, scripts, gates y DEC. No llamarlos agentes.
- Claude Code: backend IA principal en esta instalacion.
- Codex / GitHub Copilot: backends IA soportados si leen este archivo dentro del arbol.
- Goose / Claw: **[DEPRECATED - WT-2026-254a]** motores orquestados por `scripts/orquestador.py`. No usar en proyectos nuevos; reemplazados por Claude Code como backend IA principal.
- **No confundir Builder real con lente de ensemble:** una tarea de implementacion, lectura o
  escritura con filesystem usa el CLI directo del agente y `prompts/builder_invocation_contract.md`;
  una revision adversarial corta usa `ensemble_dispatch.py loop-round` y `prompts/ensemble_loop.md`.
  `ensemble_dispatch.py` no es un mecanismo generico para encargar tareas.

## Resumen del entorno

- Runtime: Python 3.10+, `pathlib`, `typing`.
- Package manager: `uv` (`uv add <lib>`, nunca `pip` directo).
- Testing y calidad: `pytest`, `ruff`.
- Seguridad: `gitleaks`, `pip-audit`.

## Rutas importantes

- `agent_system/`: codigo base de apoyo incluido con la plantilla.
  - `agent_system/templates/repomix.config.json`: plantilla de configuracion de Repomix.
- `scripts/`: utilidades de instalacion, upgrade, rollback y validacion.
- `skills/`: micro-habilidades reutilizables.
- `.agent/collaboration/`: estado operacional canonico — vive en el `repo_destino`, no en el motor. El motor contiene seeds neutros; apuntar al destino via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`.
- `.agent/runtime/memory/`: memoria persistente por proyecto.
- `.agent/context/repomix.xml`: contexto comprimido del workspace generado por Repomix (bootstrapping).
- `.agent/council/`: broker de consejo y auditoria paralela.
- `.session/repomix_local.xml`: contexto local comprimido para comparacion acelerada (repo-compare skill).
- `.session/repomix_remote.xml`: contexto remoto comprimido para comparacion acelerada (repo-compare skill).
- `REPOSITORY_STRUCTURE.md`: mapa interno publicable del repositorio.

## Vocabulario canonico

No usar "workspace" a secas: el termino es ambiguo porque describe tanto el repo destino como el entorno multi-root del IDE.

| Termino | Descripcion |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` — motor portable, fuente canonica del sistema. Tiene su propio repo git. No contiene estado operativo de tickets. |
| `repo_destino` | El proyecto que usa el motor. Tiene su propio `.agent/` con estado operativo (tickets, memoria, config). Nunca comparte estado con otros destinos. |
| `workspace_activo` | Raiz operativa con `.agent/` desde la que corre el ticket actual. En la topologia actual coincide con `repo_destino`. Se configura via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`. |
| `entorno_multi_root` | IDE abierto con `repo_motor` + `repo_destino` a la vez (VS Code multi-folder workspace). No es un concepto de codigo: solo describe el entorno de desarrollo. |

### Tipos de SESION: DISENO vs DESARROLLO (WOT-2026-039c)

Solo hay DOS tipos de sesion y este es su vocabulario canonico. **No usar "research"** para
designarlas: lo que produce una sesion de planificacion es un DISENO (un artefacto: el flight plan,
la ficha, el DAG), no una investigacion.

| Termino | Que hace | Escribe en | Prompts (bootstrap / cierre) |
|---------|----------|------------|------------------------------|
| `sesion_diseno` | Tria el backlog, disena planes de vuelo y redacta fichas. READ-ONLY sobre el codigo: NO implementa, NO commitea codigo, NO escribe `backlog.md`. | `queued/`, `reports/`, `backlog_inbox/` | `orchestrator_session_bootstrap_design.md` / `orchestrator_session_close_full_audit_design.md` |
| `sesion_desarrollo` | Ejecuta un vuelo: implementa, commitea, mueve `queued/ -> in_flight/ -> done/` y escribe `backlog.md`. | codigo, `backlog.md`, `in_flight/`, `done/` | `orchestrator_session_bootstrap.md` / `orchestrator_session_close_full_audit.md` |

El contrato de no-colision entre ambas vive en `<destino>/orchestrator_pipeline/flight_plans/INDEX.md`.

### Modos de EJECUCION multiagente: Tradicional, 4 capas, Intermedio

Ortogonal al par DISENO/DESARROLLO de arriba: dentro de una `sesion_desarrollo`, el agente puede
delegar el trabajo pesado (implementacion, revision) a `nan` via Kilo CLI en distinto GRADO. Tres
modos: **Tradicional** (Claude Code implementa y revisa el mismo), **4 capas** (Claude Code solo
orquesta y lee resumenes cortos; Manager-nan/Builder-nan/Revisor-nan hacen el trabajo pesado,
ver `prompts/agent_execution_modes.md` y el vuelo que lo origino,
`PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md`), e **Intermedio** (delega SOLO el
triaje/contrato de todo el lote; implementa Y revisa el mismo, sin delegar ninguna de las dos,
los tickets de blast-radius-alto -- regla dura de seguridad, nunca se delega la revision de esos
tickets aunque si se delegue su triaje). El agente PROPONE un modo por señales objetivas
(peticion explicita, disponibilidad de Kilo, blast radius con fuente verificable, tamaño del
vuelo) y el usuario confirma; se puede cambiar de modo en caliente a mitad de sesion
(`/agent-mode <modo>`, skill `agent-execution-mode`). Nucleo normativo completo y UNICO:
`prompts/agent_execution_modes.md` (skill apunta, prompt gobierna, X-09) -- **estado `frozen`**
(congelado 2026-10-11 tras 2 pasadas de bucle adversarial, 7+4 lentes independientes).

**Convencion de nombres (deliberada):** el sufijo `_design` va al FINAL del nombre de fichero, no al
principio (`..._bootstrap_design.md`, no `design_..._bootstrap.md`), aunque en ingles seria mas
normativo el adjetivo delante. Motivo: asi cada par diseno/desarrollo queda ADYACENTE al ordenar el
directorio alfabeticamente, que es como se buscan en la practica. Ergonomia sobre gramatica.

**Regla de repos:** toda operacion git del tooling (diff, log, commit) corre con `cwd=repo_motor`. El estado operativo (tickets, memoria, events) vive en `repo_destino`.

**Regla de `AGENT_PROJECT_ROOT`:** el motor se invoca siempre con esta variable apuntando al `workspace_activo`. Sin ella, el motor usa modo code-only y bloquea escrituras operativas.

**Regla de aislamiento por worktree: aplica al `repo_motor` igual que al `repo_destino`.**
Con 2+ sesiones trabajando en paralelo, cada sesion que vaya a escribir CODIGO en el
`repo_motor` necesita su propio `git worktree` del motor -- exactamente la misma disciplina
que ya se exige para el `repo_destino` (ver `obs-worktree-aisla-codigo-no-estado-operativo-
ni-orquestador`, memoria portable, 2026-07-25). Trabajar directamente en el checkout principal
compartido del motor es colision de superficie aunque no haya colision de CONTENIDO (dos
sesiones pueden tocar ficheros disjuntos y aun asi interferirse: una avanza `HEAD` con sus
commits mientras la otra tiene cambios sin commitear sobre el mismo arbol). El worktree del
motor NO sustituye la higiene de esa leccion (commitear siempre, nunca `stash` para dejar
trabajo "en limbo" entre worktrees, porque `refs/stash` es GLOBAL al repo y visible desde
cualquier worktree hermano).

**Nomenclatura obligatoria del PAR de worktrees (WOT-2026-104f, 2026-10-18):** cuando una
sesion crea su `repo_motor` worktree y su `repo_destino` worktree, AMBOS deben llevar el
MISMO sufijo de rama/directorio (`<nombre-de-sesion>`), difiriendo solo en la raiz padre:

```
.t3/worktrees/<carpeta-del-repo_motor>/<nombre-de-sesion>     (repo_motor)
.t3/worktrees/<carpeta-del-repo_destino>/<nombre-de-sesion>   (repo_destino)
```

Motivo: sin esta regla, emparejar los dos worktrees de una sesion exige abrir
`motor_destination_link.json` o preguntar; con el sufijo compartido, `git worktree list`
en cualquiera de los dos repos basta para identificar la pareja a simple vista. Al crear el
par: (1) crea primero el worktree de `repo_motor` (rama `<owner>/<nombre-de-sesion>`); (2) crea
el worktree de `repo_destino` con el MISMO sufijo; (3) escribe
`<repo_destino>/.agent/config/motor_destination_link.json` apuntando `motor_root` al worktree
de (1) ANTES de lanzar o continuar la sesion -- nunca dejar que la sesion lanzada lo descubra
sola. Origen: un `t3_thread_launch` con `workspaceStrategy: worktree` solo provisiono el lado
`repo_destino` (y una vez ni eso: dejo el directorio vacio sin `git worktree add` real), dejando
a la sesion sin `prompts/` ni enlace al motor hasta que lo reconstruyo manualmente.

**Formato obligatorio de `motor_destination_link.json` (WOT-2026-104g, 2026-10-18):** las rutas
`motor_root`/`destination_root` se escriben con **forward slashes** (ruta absoluta de
Windows con `/` en vez de `\`), NUNCA con backslashes a mano -- un backslash sin escapar correctamente deja el JSON invalido, tolerado en
silencio por `local_audit.py` pero rechazado por `destination_context.py`. Verificado 2/2 de forma
INDEPENDIENTE: las dos sesiones de prueba del vuelo autonomo (`autonomo-a-20261018` y
`autonomo-b-20261018`) encontraron y corrigieron el mismo defecto sin coordinarse entre ellas --
senal de defecto sistemico del mecanismo que genera el fichero, no incidente aislado. Si generas
este fichero a mano (via Bash, por el workaround de `guard_paths` de mas arriba), usa forward
slashes o `json.dumps(..., ensure_ascii=False)` sobre un dict Python -- nunca interpoles
backslashes de Windows directamente en un heredoc o f-string.

**El lanzador debe dar el NOMBRE EXACTO de la sesion coordinadora a cada hija (2026-10-18):** un
mensaje de arranque que dice "informa a la sesion coordinadora" sin el nombre/id exacto (el que
devuelve `ListAgents`) fuerza a la hija a adivinarlo. Verificado en vivo: la sesion
`autonomo-b-20261018` envio su informe final por `SendMessage` a una sesion hermana de una prueba
ANTERIOR (nombre que aparecia en su contexto heredado) en vez de a la sesion que la habia lanzado
realmente -- el informe nunca llego. El prompt de arranque de una sesion hija SIEMPRE debe incluir
el nombre literal de la sesion lanzadora (el que esta usa para si misma, visible en su propio
`ListAgents` o conocido de antemano), nunca una descripcion ("la sesion coordinadora") que la hija
tenga que resolver por su cuenta.

### Glosario de nomenclatura de ticket (WOT-2026-010a)

Nomenclatura canonica de identificadores y artefactos de ticket. "Plan" se
reserva para la familia completa; el artefacto de estrategia de un ticket es
`STRATEGY_`, no `PLAN_`.

| Termino | Descripcion |
|---------|-------------|
| `WOT-YYYY-NNNx` | **Prefijo canonico de ticket** (tres letras). Ej. `WOT-2026-010a`. Es el ID que usan generadores, validadores y bus. |
| `WP-` / `WT-` | **Legacy historico.** Prefijos de tickets antiguos (161 `WP-`, 72 `WT-`). NO se migran en masa; los consumidores los aceptan como `legacy-compat`. |
| familia / plan | El plan/familia completo, ej. `WOT-2026-009` agrupa `009a..009g`. "Plan" NUNCA designa el artefacto de un ticket individual. |
| `work_plan.md` | **Contrato operativo del ticket activo.** Una unica copia viva en `.agent/collaboration/`. Lo lee el scope gate y lo ejecuta el Builder. Sin cambio de nombre. |
| `STRATEGY_WOT-<ID>.md` | **Estrategia tecnica del ticket** (opcional). Sustituye al antiguo `PLAN_WT-<ID>.md`. Libera "PLAN" para la familia. Legacy: `PLAN_WP-*`, `PLAN_WT-*`. |
| `AUDIT_WOT-<ID>.md` | **Criterios de auditoria del ticket.** Solo cambia el prefijo `WT->WOT`. Legacy: `AUDIT_WP-*`, `AUDIT_WT-*`. |

**REGLA: en contextos inter-ticket o inter-repo, usa el ID COMPLETO con prefijo.**
Referencia cada ticket con su identificador completo `<PREFIJO>-YYYY-NNNx` (p.ej.
`CTL-2026-008k`, `WOT-2026-020p`, `EXF-2026-007a`) en chat, commits, memoria, backlog,
work_plan y cualquier artefacto operativo. Motivo: se trabajan varios repos/destinos en
PARALELO, y cada uno tiene su propio prefijo (`CTL-`, `WOT-`, `EXF-`, ...); la forma corta
`008k` a secas es AMBIGUA -- es imposible saber a que repositorio/destino pertenece. El
numero `NNNx` solo es unico DENTRO de un prefijo+ano, no globalmente. La forma corta `008k`
solo es aceptable si el prefijo/familia ya quedo EXPLICITAMENTE desambiguado en el mismo
contexto inmediato (p.ej. tras citar `WOT-2026-009a`, referir `009b..009g` como esa familia
en el mismo parrafo); fuera de ese contexto local, siempre el ID completo.

El prefijo ademas RESUELVE el repo destino: cada destino declara su `ticket_prefix` en su
`motor_destination_link.json` / `PROJECT.md`, y el mapeo inverso prefijo->repo se deriva de
ahi (ver WOT-2026-020s: prefix-resolver + bootstrap guard). Convencion para repos NUEVOS
(sin retrofit de los existentes): sugerir el prefijo desde las iniciales del nombre (3
letras, mayusculas) y verificar unicidad contra los prefijos ya declarados antes de
adoptarlo -- la convencion sugiere, el registro (los links por-destino) resuelve.

**Clases de patron para consumidores de codigo** (archivador, pre-handoff guard,
validador de prosa, review bridge, motor_checkpoint):
- `canonical`: `STRATEGY_WOT-*`, `AUDIT_WOT-*`.
- `legacy-compat`: `PLAN_WP-*`, `PLAN_WT-*`, `AUDIT_WP-*`, `AUDIT_WT-*`. Se
  conservan con alias de transicion; eliminarlos dejaria sin archivar los
  tickets historicos.

**Prompt de auditoria de contrato:** `prompts/audit_ticket_contract.md` (renombrado
desde `audit_plan.md`; stub retirado en WOT-2026-011d). Audita el contrato/plan operativo
del ticket ANTES de Builder; no confundir con review de implementacion, bus,
cierre o publicacion.

**Generador vs historia (regla de gate, WOT-2026-010a):** la gate de
nomenclatura distingue dos usos muy distintos de un ID con prefijo legacy:

- **Generador / ejemplo vivo** (DEBE usar `WOT-`): plantillas, placeholders,
  ejemplos de comando, texto de `--help`, esquemas de formato (`source_ticket`,
  `Plan ID`, `Ticket relacionado`, `--ticket WP-...`). Crean o enseñan
  nomenclatura nueva. La gate FALLA si usan `WP-`/`WT-` sin etiqueta.
- **Historia de commit** (legacy-compat implicito, NO se reescribe): un
  comentario o docstring de la forma `# <TICKET>: <descripcion de lo que se
  hizo>` documenta en que ticket historico se realizo un cambio. Reescribirlo
  falsearia la trazabilidad. La gate lo PERMITE como legacy-compat por su forma
  (`# <TICKET>:` o referencia historica), sin marca por-linea.
- **Bloque legacy etiquetado** (legacy-compat explicito): ver
  [ticket_nomenclatura_bloque_legacy_etiquetado](docs/protocol/ticket_nomenclatura_bloque_legacy_etiquetado.md).

Gate ejecutable: `scripts/check_ticket_nomenclature.py` clasifica cada hit y
falla solo ante un generador/ejemplo vivo con prefijo legacy sin etiqueta.

### Distincion critica: `.agent/collaboration/` del motor vs del destino

| Ubicacion | Rol | Contenido |
|-----------|-----|-----------|
| `repo_motor/.agent/collaboration/` | **Seed neutro** | Archivos en estado READY_TO_START/IDLE. Molde para nuevos destinos instalados. No contienen tickets activos. |
| `repo_destino/.agent/collaboration/` | **Estado operativo activo** | `work_plan.md`, `execution_log.md`, `TURN.md`, `STATE.md`, `backlog.md` con el ticket real en curso. |

**Nunca usar `repo_motor/.agent/collaboration/` como operativo.** El guard anti-drift bloquea escrituras operativas ahi sin `AGENT_PROJECT_ROOT`.

## Contrato de version y portabilidad

- `pyproject.toml` define la version del paquete portable.
- `.agent/.version_manifest.json` define la version tecnica del core.
- `MANIFEST.distribute` define la frontera del motor central (codigo operativo).
- `MANIFEST.workspace` define el contrato del workspace destino (estado, memoria, config).
- Los comandos canonical y legacy se documentan por separado.
- Estado actual: `v9.17.1` motor central + workspace destino, cierre canonico con suite verde, pipeline autonomo por chat, meta-auditoria, auditoria de publicacion Git, guard de integridad del motor, encoding guard endurecido y CEM v0 adoptado.
- El motor vive una unica vez en `orquestador_de_agentes/`; los proyectos destino lo referencian externamente.
- La senal VIVA de staleness NO es esta cadena de version hardcodeada (queda fija hasta el proximo bump manual): es `motor_sha` en el link motor<->destino, comparado en vivo contra el HEAD real del motor en cada `destination_context.py --bootstrap` (WOT-2026-024j, WARN de drift, nunca gate).

## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)

Los archivos `MANIFEST.distribute` y `MANIFEST.workspace` en la raiz del repositorio definen el contrato estricto del motor central y el workspace destino. Detalle (referencia bajo demanda, consulta al tocar la frontera de distribucion o el workspace destino): `.agent/rules/common/manifest_contracts.md`.

## Comandos principales

When running from an external-motor destination workspace (repo_motor + repo_destino topology),
append `--project-root <destino>` to commands that operate on project state.

- Instalacion inicial: `python scripts/install_agent_system.py --install`
- Sincronizacion estricta: `python scripts/install_agent_system.py --sync`
- Sincronizacion interactiva: `python scripts/install_agent_system.py --sync --prune`
- Vista previa: `python scripts/install_agent_system.py --sync --dry-run`
- Estado del sistema: `python .agent/agent_controller.py [--project-root <workspace>]`
- Auditoria local: `python scripts/local_audit.py` (NO acepta `--project-root`)
- Memoria consolidada: `python scripts/memory_consolidate.py [--apply|--dry-run]`.
   El scope se determina por `AGENT_PROJECT_ROOT` o por `motor_destination_link.json` del destino.
- Integridad del motor: `python scripts/check_motor_pristine.py --snapshot --motor-root <repo_motor> --out <snapshot.json>` y despues `python scripts/check_motor_pristine.py --check --snapshot-file <snapshot.json> --report <result.json> --motor-root <repo_motor>`
- Auditoria de publicacion Git: `python scripts/classify_publication.py --repo-root <repo_destino> --out <repo_destino>/orchestrator_pipeline/reports/publication_manifest.json`
- Bundle de contexto para Hermes: `python scripts/hermes_build_context_bundle.py --output-root <hermes_agent>/uploads --soul-output <hermes_agent>/soul.md`. Genera snapshots con version, commit y hashes; no edites copias derivadas como fuentes canonicas.
- Migrar config: `python .agent/agents_config.py --migrate [--dry-run] [--project-root <workspace>]`
- Comparar con repo GitHub: skill `/repo-compare`
- Orquestar backlog por chat: skill `/pipeline` (`prompts/orchestrator_pipeline.md`)
- Orquestar un OBJETIVO como Manager (estrategia -> planes -> Builders -> bucles F/S): nucleo portable
  `prompts/manager_orchestrator_loop.md` + su adaptador a este motor `prompts/manager_orchestrator_loop_adapter_motor.md`
  (skill `manager-orchestrator-loop`). No confundir con `/pipeline`, que ejecuta tickets ya formados.
- Dispatch padre/hijo multi-ticket y multi-backend (Claude Code/Kilo/OpenCode), capa EXPERIMENTAL que
  se apila sobre `/autonomous-ticket-batch` cuando un vuelo necesita backends distintos por ticket:
  `prompts/orchestrator_child_dispatch_multiticket_multibackend_unlimited.md`
  (skill `orchestrate-child-dispatch-multiticket-multibackend-unlimited`). No sustituye el PREDICATE,
  las 8 barreras ni el `GROUP_STOP_REPORT` de ese ejecutor.
- Meta-auditar pipeline cerrado: skill `/audit-pipeline`
- Auditar publicacion Git: skill `/audit-git-publication`
- Auditar salud del sistema post-cambio (motor+destino+integracion): skill `/audit-system-health`. Recolector determinista: `python scripts/collect_system_health.py --motor-root <repo_motor> --project-root <repo_destino> --mode auto`. El script RECOLECTA (read-only: por defecto no toca ningun fichero TRACKED); el agente AUDITA. Salida en `<repo_destino>/.agent/audits/system_health/general_audit_YYYYMMDD[_HHMM]/`. El registro en `INDEX.md` (fichero tracked en el workspace) es opt-in via `--publish-index`, OFF por defecto (WOT-2026-023x). Ver `prompts/audit_post_change_system_health.md`.
- Interaccion por terminal: `python scripts/ticket_supervisor.py --reactive [--project-root <workspace>]`
- Tests: `python scripts/run_pytest_safe.py` (NO acepta `--project-root`; runs against `repo_motor` tests by design)
  - NO usar `python -m pytest` directo sobre tests que importan el controller:
    al insertar `.agent/` en sys.path, `runtime` puede resolver a
    `.agent/runtime/` (que tiene `__init__.py`) en vez de `<motor>/runtime/`,
    y la coleccion falla con `No module named 'runtime.project_root'`.
    El runner seguro configura el entorno correcto y ademas incluye la
    barrera de state-leak (falla si la suite muta `.agent/collaboration/`).
- Calidad: `ruff check . && ruff format .`
- Auditoria de dependencias: `python scripts/pip_audit_project.py`
- Archivar colaboracion: `python scripts/archive_collaboration_artifacts.py [--dry-run] [--project-root <workspace>]`

## Convenciones

### Prompt/contrato citado => LEELO ENTERO antes de redactar contra el (2026-07-29)

**Norma dura, no consejo.** Si un prompt te lo pegan en el chat, lo enlaza otro prompt que te pegaron, o un proceso lo declara como su contrato, **lo abres y lo lees ENTERO antes de producir nada que se mida contra el**. Ver detalles, fallos medidos y agravantes en .agent/rules/common/contract_full_read_and_process_search.md.

### Decision de proceso sin instruccion exacta => BUSCA protocolo documentado antes de suponer uno (2026-10-14)

**Norma con barrera de FORMA parcial desde 2026-10-18 (WOT-2026-104b)**, no barrera semantica: scripts/check_process_decision_search.py (cableado como hook pre-commit en el motor sobre prompts/**/*.md, .claude/rules/**/*.md, AGENTS.md, CLAUDE.md, y como hook pre-push en el destino sobre .agent/planning/*.md/STRATEGY_WOT-*.md CAMBIADOS en el rango a publicar) bloquea un artefacto que se AUTODECLARA con el marcador DECISION DE PROCESO: si no declara ademas una seccion BUSQUEDA-PREVIA: valida (PROTOCOLO ENCONTRADO: <ruta> / NO ENCONTRE PROTOCOLO / EXCEPCION: trivial <justificacion>). Ver criterio de busqueda minima, clases de decision, y candidato de barrera PARCIAL en .agent/rules/common/contract_full_read_and_process_search.md.- Lee `PROJECT.md` antes de tocar arquitectura o estado.
- Lee `INTERACTION_MODES.md` antes de operar por chat o por terminal.
- Para tickets que tocan sincronizacion de estado, bus, proyecciones o codigo topologia-aware (`repo_motor + repo_destino`), comprueba primero si el sintoma encaja con un patron documentado en `docs/KNOWN_FAILURE_PATTERNS.md` antes de proponer un fix nuevo.
- Para arrancar una sesion nueva con cualquier agente, usa el bootstrap canonico en `prompts/orchestrator_session_bootstrap.md` (apunta a archivos clave en lugar de embeber).
- Usa `pathlib` y `try/except` explicito para I/O.
- Mantiene la raiz limpia: no metas basura temporal en el arbol portable.
- Usa `.agent/collaboration/work_plan.md` y `.agent/collaboration/execution_log.md` para el estado canonico.
- En `Files Likely Touched`, escribe una unica ruta parseable por bullet. Las
  aclaraciones van en una linea separada; texto como `o modulo equivalente` en
  el mismo bullet puede impedir que el parser de FLT reconozca la ruta.

### Orden de trabajo: AGRUPA los commits, la suite va la ULTIMA (WOT-2026-026t)

**La suite canonica es el ULTIMO paso antes del push, nunca uno intermedio.** El contrato exige
`tested_commit_sha == HEAD` (`pre_handoff_guard.py:561`), asi que **cualquier commit posterior a la
suite la invalida** y obliga a re-correrla entera (~7 min).

```
ORDEN CORRECTO                          ORDEN QUE DESPERDICIA
1. TODOS los commits                    suite -> commit -> suite -> commit -> suite
2. suite canonica (UNA vez)             (medido 2026-08-04: 3 corridas, ~15 min tirados)
3. verificar tested_commit_sha == HEAD
4. push
```

**Es la misma familia que la regla del bucle** (`obs-canonical-suite-runs-after-the-loop-not-before`:
el bucle adversarial pide cambios, asi que una suite previa queda invalidada). Ahora generalizada:
**cualquier** escritura posterior invalida la corrida, venga de un bucle o de un commit propio.

**Barrera cableada, no norma** (`scripts/check_suite_freshness.py`, hook `check-suite-freshness` en
`pre-commit`): avisa ANTES de commitear si existe una suite verde COMPLETA en el HEAD actual que
ese commit invalidaria, citando cuantos tests se pierden. **No bloquea** -- un commit a mitad de
sesion es legitimo, y bloquearlo forzaria a correr la suite entre cada par de commits, que es el
desperdicio que se quiere evitar. La barrera BLOQUEANTE (no publicar con suite stale) ya existe y
vive en `pre_handoff_guard`.

**No uses `-k` como evidencia de cobertura de una funcion compartida.** El filtro selecciona por
nombre de clase/fichero, no por grafo de call-sites: una funcion ejercitada desde clases con
nombres distintos al filtro puede quedar sin cubrir aunque `-k` de verde. La evidencia final de
cobertura de una funcion compartida debe venir de la suite canonica completa (`--level all`),
nunca de un `-k` por nombre. Rationale completo (por que la comprobacion previa no bastaba, caso
medido WOT-2026-079d con 3 regresiones reales que `-k` dejo pasar): memoria de
`repo_motor`, `obs-canonical-suite-k-filter-insufficient-for-shared-function-coverage`
(2026-09-27).

**Asignacion de rol en despacho trio (Manager/Builder/Revisor, WOT-2026-104k):** cuando el
despacho de un ticket se reparte entre tres roles (protocolo `prompts/kilo_trio_dispatch/`),
SOLO el Manager corre la suite completa `--level all`, como gate de cierre, UNA vez,
inmediatamente antes del push -- tras TODOS los commits del ticket, nunca "antes del commit
final" (la regla de arriba ya fija que la suite es el ULTIMO paso, no uno intermedio). El
Builder se limita a tests focales del area tocada durante la implementacion (nunca `--level all`
como su propio cierre); el Revisor ejecuta de forma independiente sus propios tests focales
sobre el area modificada -- NUNCA cita ni espera una corrida del Manager, porque en el orden
canonico del trio (Manager -> Builder -> Revisor -> Manager-cierre) esa corrida todavia no
existe cuando el Revisor actua. Medido en vivo (2026-10-18, WOT-2026-104j, sesion hija 4 capas):
sin esta asignacion explicita, Builder y el Orquestador corrieron `--level all` CADA UNO por su
cuenta, ambas veces antes de que el Revisor tuviera turno -- exactamente el patron de
desperdicio que la regla de arriba ya advertia, mas una corrida redundante que la regla de
arriba no cubria (quien tiene PERMISO de correrla, no solo cuando). Verificado por bucle de
gobierno DESIGN_REVIEW (`UNI-5`, 4 lentes independientes: codex, opencode/glm, gemini, mistral;
3/4 `APROBAR_CON_CAMBIOS` tras corregir una redaccion anacronica del primer borrador). **Alcance
declarado, no se extiende por si solo:** esta regla cubre el protocolo trio
`prompts/kilo_trio_dispatch/`. NO toca `scripts/run_gates_dispatch.py` ni
`skills/builder-run-quality-gates` (hallazgo de la lente codex en el mismo bucle): esos
mecanismos sirven tambien a tickets de un solo Builder sin Revisor/Manager separados, donde el
Builder SI es el unico verificador legitimo de `--level all`.

#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)

- DECISION DE PROCESO: la publicacion se difiere al final del vuelo, nunca por ticket (2026-10-19).
  BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: prompts/orchestrator_session_bootstrap.md:314 (UN solo push al final de la cola, con OK humano explicito), prompts/orchestrator_pipeline_codeonly.md:199 (Push AGRUPADO al final de sesion ... NO push por ticket) y prompts/manager_orchestrator_loop_backlog.md:455 (informe antes del push).

**La publicacion es una accion del VUELO, no del ticket.** Ver detalles, fallos medidos y contract en `.agent/rules/common/flight_push_policy.md`.
- **NO se pushea entre tickets** (mismo logico que `batch-agrupar-preguntas-antes-de-arrancar`).
- **Sin autorizacion registrada no hay push.** Un vuelo que termina sin decision de publicacion queda en estado declarado `PUBLICACION_PENDIENTE_AUTORIZACION`: todo commiteado y verde en local, remoto intacto.

#### Extension: push a una rama con trafico concurrente de otras sesiones (2026-10-14)

**Gate 2 (push con la rama remota avanzada por otras sesiones):** si, al intentar publicar un
commit YA VERIFICADO por el Gate 1, la rama remota avanzo con commits de otras sesiones, el
merge de esos commits se verifica asi:
- Si el merge es disjunto en ficheros (ninguno tocado por ambos lados) **y** el auto-merge de
  Git no reporta conflicto de texto: ademas de `ast.parse`/sintaxis de los ficheros que SI
  cambiaron y confirmar que no quedan marcadores de conflicto (`<<<<<<<`), se exige ADEMAS
  (i) ausencia de dependencia de import cruzada entre los ficheros tocados por cada lado, y
  (ii) que ninguno de los ficheros tocados sea una superficie transversal de alto blast radius
  (`conftest.py`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `AGENTS.md`,
  `CLAUDE.md`, `bus/`, `runtime/`, `.agent/agents_config.py`). Si cualquiera de las tres
  condiciones falla, tratar como "mismo fichero compartido" (exige suite completa).
- Si el merge toca el mismo fichero en ambos lados: la suite completa SI debe correr antes de
  publicar -- nunca "suite focalizada" por `-k` (ver regla de arriba, WOT-2026-079d).
- El camino relajado del primer bullet NUNCA es alcanzable para el commit resultante de un
  MERGE: el `tested_commit_sha` del Gate 1 es el del commit padre, nunca el del merge commit.
  La "relajacion" ahorra la RE-suite solo cuando se demuestra ANTES de mergear que el merge es
  disjunto y seguro, nunca despues de que el merge commit ya existe.
- Si tras publicar el remoto volvio a avanzar (`non-fast-forward`), repetir el criterio arriba
  en la nueva ronda, sin acumular re-verificaciones completas solo porque ya se hizo una vez.

**Condiciones de rechazo del Gate 2 (default fail-closed):** el Gate 2 relajado NO aplica si
(1) no existe evidencia VERIFICABLE de que el lado entrante corrio su Gate 1 (`tested_commit_sha`
registrado, evento de bus, log de cierre citable -- no basta "presumiblemente"); (2) el lado
entrante toca una superficie transversal (lista arriba); (3) hay dependencia de import cruzada
entre los ficheros tocados por ambos lados; (4) el commit publicado es un merge commit cuyo
`tested_commit_sha` no coincide con el HEAD resultante; (5) han ocurrido 2+ intentos de push
rechazados consecutivos sin que ninguna ronda haya corrido la suite completa sobre el estado
integrado. El default es FAIL-CLOSED: el Gate 2 relajado es la excepcion estrecha, no el
comportamiento esperado por defecto.

**Alcance:** esta politica SOLO aplica a ramas o flujos donde exista, en algun punto del ciclo
de vida del commit, una verificacion equivalente a `assert_canonical_suite_green` (via
`--mark-ready` de un ticket formal, o via un registro explicito de `tested_commit_sha` en la
bitacora de un vuelo sin ticket). Sin esa evidencia, tratar como si el Gate 1 nunca se hubiera
verificado y exigir suite completa, sin excepcion.

**Riesgo residual declarado:** esta politica asume que cada sesion concurrente aplica su propio
Gate 1 antes de publicar. A diferencia de un equipo con CI real (que tiene un verificador
automatico TERCERO sobre el HEAD integrado), aqui no existe ningun verificador automatico
equivalente -- el riesgo es MAYOR que en un equipo con CI, no igual. `check_suite_freshness.py`
no es comparable: es local y depende de que `pre_handoff_guard` corra aguas abajo, lo cual no
ocurre en un push de vuelo sin ticket formal.

### Convencion de encoding y gap v1 (WOT-2026-010e)

- **Preferir Write/Edit sobre heredoc** para contenido no-ASCII en archivos de
  texto (`.md`, `.py`, `.json`, `.toml`, `.yaml`, `.yml`, `.sh`, `.ps1`, `.txt`,
  `.xml`). El hook `encoding_post_write_hook.py` detecta BOM, mojibake y
  question-mark corruption tras cada escritura nativa del agente.
- **Gap v1 conocido:** Bash/heredoc NO esta cubierto por el hook. Las
  escrituras dentro de `Bash`/`RunInTerminal` quedan cubiertas por convencion
  operativa + `check_encoding_guard.py` antes de handoff/commit.
- `TEXT_EXTENSIONS` en `scripts/encoding_guard.py` es la fuente de verdad de
  sufijos texto. No derivarla de `GLOB_PATTERNS`.
- `scripts/check_encoding_guard.py` sigue siendo la autoridad de cierre; el
  hook es defensa en profundidad, no su sustituto.

#### No MEZCLES vias de escritura en el mismo fichero (line endings, medido 2026-08-04)

**El sintoma:** `git commit` ABORTA con `mixed line ending ... Failed` y el hook deja el fichero
"arreglado" pero SIN commitear. El commit **no existe**; hay que re-`git add` y repetir. Paso TRES
veces en una sola sesion, y las tres por lo mismo.

**La causa, medida (no la que parece):** en Windows, las dos vias de escritura del agente dejan
finales de linea DISTINTOS en el mismo repo.

| Via | Deja |
|---|---|
| `Write`/`Edit` (y `Path.write_text()` en modo texto) | **CRLF** -- Windows traduce `\n` al escribir |
| `cat >> f <<'EOF'`, `printf`, `Path.write_bytes()`, `write_text(..., newline="")` | **LF** |

Escribir un fichero con una via y AMPLIARLO con la otra lo deja MIXTO, que es lo que el hook caza.
Reproducido: `write_text()` (CRLF) + `cat >>` heredoc -> `CRLF=2 LF_total=3 bare_LF=1` -> MIXTO.

**Dos creencias FALSAS que conviene no heredar** (ambas se sostuvieron una sesion entera antes de
medirse):
1. *"La mezcla la introduce `git add` al aplicar `.gitattributes`"*. **NO.** Probado: `git add` no
   toca el working tree (`CRLF=0 LF=2` antes y despues; la normalizacion ocurre solo en el INDICE).
2. *"Verificar los line endings antes de stagear no sirve"*. **SI sirve** -- y es la barrera. Lo que
   no servia era mi comprobacion, porque medi el fichero ENTERO (`crlf == lf` -> "homogeneo") en vez
   de buscar LF SOLITARIOS. Un fichero con 2248 CRLF y 1 bare LF pasa el primer test y falla el hook.

**Regla operativa:**
- Elige UNA via por fichero. Para `.py`/`.md` del motor, `Write`/`Edit` (la que el hook de encoding
  ya cubre); si amplias por `Bash`, hazlo con la MISMA via con que se creo.
- Anadir tests a un fichero existente con `cat >>` es el caso que mas muerde: usa `Edit`, o
  normaliza despues.
- Comprobacion correcta (cuenta bare LF, no compara totales):
  `raw.count(b"\r\n")` vs `raw.count(b"\n")`; si la diferencia es > 0 **y** hay CRLF, esta MIXTO.
- Si el hook ya aborto: **no es un fallo, es el flujo**. El fichero queda arreglado en disco; haz
  `git add` de nuevo y repite el commit. Verifica antes que tus cambios sobrevivieron
  (`grep` de un token propio), porque el arreglo reescribe el fichero.

### Nomenclatura de perfiles ensemble (`ensemble_profiles` en `agents.json`)

- **Forma canonica:** `<rol>_<backend>_<familia>[_<caracteristica>]`, con `familia` = UNA
  palabra que identifica el modelo SIN version ni tamano (el campo `model` del perfil ya lleva
  la version exacta; el nombre no la duplica). Colar version/tamano en el nombre es error:
  `challenger_groq_qwen38` es INCORRECTO. Especificacion completa de campos, ejemplos y origen
  de la norma: `.agent/rules/common/ensemble_profile_nomenclature.md`.
- **No renombrar `challenger_opencode_glm_5_2` sin revisar primero** `grep -rn
  "challenger_opencode_glm_5_2" tests/`. Excepcion legacy (por que, estado exacto, consecuencia
  para rutas de seleccion nuevas): `docs/protocol/ensemble_profile_naming_legacy_case.md`.

## Archivado de colaboracion (WP-2026-100)

- `scripts/archive_collaboration_artifacts.py` mueve `PLAN_WP-*.md` y `AUDIT_WP-*.md` cerrados a `.agent/collaboration/_archive/plan_audit/`.
- El ticket activo conserva solo sus documentos vivos en `collaboration/`.
- El archivador es idempotente: segunda ejecucion = no-op.
- Usa `--dry-run` para previsualizar sin modificar, `--list-active` para ver archivos activos.

## Superficies vivas vs historicas en .agent/collaboration/ (WP-2026-107)

Ver las superficies vivas NO archivables y la regla de limpieza en .agent/rules/common/collaboration_live_surfaces.md.

## Convenciones de docstrings y testing

Adaptado de las directrices operativas open-source en `dify-agent`:

### 1. Docstrings como especificación de ejecución (Docstrings-as-Spec)

Cada función, clase o módulo operativo del sistema debe contar con un docstring claro y estructurado en **3 fases**. El agente o auditor contrastará la firma técnica con esta especificación semántica para asegurar el cumplimiento:
- **Before (Pre-condiciones):** Qué estados, variables, archivos o privilegios requiere la función antes de invocarse.
- **During (Proceso y Recursos):** Cuál es el flujo de transformación de datos, qué efectos colaterales (I/O, llamadas de red) realiza y qué recursos del sistema consume.
- **After (Post-condiciones y Errores):** Qué salidas exactas se garantizan, cómo cambian los estados canónicos y qué excepciones específicas se interceptan y lanzan.

### 2. Rúbrica de testing de alta fidelidad (Test Útil vs Basura)

Para evitar la inflación artificial de cobertura sin validación lógica real, el Builder y los quality gates rechazarán cualquier test cosmético. Se define la siguiente rúbrica de aceptación:
- **Test Inútil (descartable):** Aquel que solo hace aserciones pasivas como `assert obj is not None` o verifica constantes mocked estáticas sin desencadenar lógica real.
- **Test Útil (aceptado):** Aquel que fuerza casos límite (boundary limits), valida transiciones reales de estado (en el Event Bus, archivos de configuración o memoria persistente) y verifica explícitamente el lanzamiento de excepciones esperadas (`pytest.raises`).

**Anti-patrones de test que el Builder debe evitar y el Manager debe rechazar:**
- **Mock drift:** el patch apunta a `X` pero el código llama a `Y` (distinta API). El test pasa sin probar nada real. Ejemplo: parchear `pathlib.Path.open` cuando el código usa el built-in `open()`.
- **Floor assertion:** el umbral de una aserción numérica es satisfecho por el valor base sin la feature probada. Ejemplo: `assert score >= 150` cuando el score de recencia solo ya es `~20_000_000`.

### 3. Anti-patrones de implementación

- **Zero-logic wrapper:** una función cuyo cuerpo completo es una única llamada delegada 1:1 sin lógica propia debe ser inlineada o eliminada. Añade indirección cognitiva sin valor.

## CEM v0 - Contrato, Evidencia y Memoria

CEM es el contrato minimo para trabajar con agentes sin convertir cada ticket en burocracia. Se aplica con rigor proporcional al riesgo del cambio.

**Fallback ante duda de diseno sin contrato que la resuelva:** `CONSTITUTION.md` (raiz del motor, carga ON-DEMAND, leelo entero cuando lo consultes) tiene la jerarquia de 6 niveles y 15 tenets de ingenieria que amplian lo de abajo.

- **Contrato antes que fix:** identifica que comportamiento canonico protege el cambio antes de tocar codigo o tests.
- **Evidencia antes que relato:** ningun auto-reporte de agente es evidencia; usa diff, exit code, test, evento de bus, commit o artefacto verificable.
- **Un `exit 0` puede significar "no hice nada":** en operaciones IDEMPOTENTES o con SKIP (cierres, syncs, instaladores), `exit 0` es indistinguible de "ya estaba hecho" o "me salte el trabajo". `exit code` es evidencia NECESARIA pero no SUFICIENTE para estas: verifica el ARTEFACTO (fichero/informe/diff/contador que la operacion debia producir), no solo el codigo de salida; y busca en la salida las palabras de skip (`already`, `skipped`, `nothing to do`, `none present`, `up to date`, `no files to check`). Y lee el CODIGO antes de temer un flag: un `--force` puede vencer SOLO la idempotencia sin tocar los gates (leer 12 lineas convierte un "no me atrevo" en un cierre real). Caso: `--session-close` dio `exit 0` sin cerrar nada (`[INFO] Session already completed`), disparado por un `.session_state.json` STALE que ademas se contradecia con `work_plan.md` (2026-07-15).
  - **Si el artefacto es UNTRACKED, el discriminante es su `mtime` contra su propio timestamp interno** (git no te ayuda: no hay diff que mirar). Dos escrituras en el MISMO acto -- `mtime` y el campo de hora del fichero separados por milisegundos -- prueban que la operacion CORRIO y escribio; un `mtime` INTACTO tras la corrida prueba que no aterrizo NINGUNA escritura. Son veredictos OPUESTOS y el `exit 0` es identico en ambos. Medido 2026-07-29 sobre `.session_state.json` (untracked, `git ls-files --error-unmatch` -> rc=1): un `--session-close` normal dejo el `mtime` en `11:38:23.237` (no aterrizo nada, y ese `exit 0` era el recibo CORRECTO de idempotencia), mientras que el mismo cierre con `--force` lo movio a `23:36:02.901`, a 14 ms de su `last_activity` interno -- misma escritura, luego la rama `save_session()` corrio y copio un `active_plan` ajeno. **Limite: el par prueba QUE corrio y QUE rama se tomo, NO la causa completa.** Instrumentar la ruta productiva es otra cosa y exige su propio probe con control positivo; leer de mas en un par de timestamps es falso verde por relato.
- **El exit code tras una tuberia MIENTE (autoengano-por-pipe):** `$?` tras `cmd | tail` lee el rc del ULTIMO tramo de la tuberia (el consumidor), no del productor: un comando que FALLA se disfraza de exit 0. Cuando necesites a la vez esquilar la salida Y reportar el rc REAL, usa el wrapper aprobado `scripts/tools/run_and_exit.py` (WOT-2026-022p): `python scripts/tools/run_and_exit.py --tail 20 -- <cmd> [args...]` imprime las ultimas lineas y despues `[run-and-exit] exit_code: <n>`, y el proceso sale con ese mismo codigo (127 si el comando no existe, 2 si no hay comando). Desaconsejado explicitamente el encantamiento manual -- `$?` colgado de un pipe, `cmd | tail; echo $?` --: dos actores independientes reprodujeron ya el fallo y dejo un veredicto fail-open fabricado que llego a memoria (2026-07-11/12). Control positivo del wrapper (no lo dupliques): `tests/unit/test_tools_shell_safety.py::test_reports_real_exit_of_failing_command`. Adopcion citada aqui desde WOT-2026-058e.
- **Equivalencia de ruta productiva (evidencia exploratoria vs evidencia de cierre):** un `exit_code:` solo es evidencia de CIERRE si el probe **reproduce la ruta que corre en produccion**. Aplica **rigor proporcional**: obligatorio para todo lo que toca runtime (hooks, guards, CI, tests, scripts ejecutables, instalador); se salta para docs, typos y prosa sin logica de ejecucion.
  - **Asimetria dura:** un probe que NO reproduce la ruta productiva puede **REFUTAR** una hipotesis, pero **NUNCA CONFIRMAR un cierre**. La confirmacion es la que mata: hoy el probe de PowerShell *confirmo* una hipotesis falsa, y fue el probe en la ruta REAL (Git Bash) el que la refuto.
  - **Recibo obligatorio (no basta afirmarlo):** el probe **imprime** su propio contexto -- `sys.executable`, `cwd`, la parte relevante de `PATH`/env, y la cadena de launcher-- y ese recibo se pega junto al `exit_code:`. Sin recibo, es evidencia exploratoria por defecto.
  - **Declara y justifica:** actor real, launcher real, shell, cwd, PATH/env, fichero/config leido, y **POR QUE** ese probe reproduce la ruta productiva.
  - **Vector git (WOT-2026-020r):** si el probe invoca git, pregunta explicitamente **¿el cwd tiene su propio `.git`?** Si no lo tiene, el walk-up de git **alcanza el repo REAL** y te contesta el arbol de la maquina, no el fixture: el probe NO es hermetico y su verde no significa nada.
  - **Por que esto es una regla y no un consejo:** un probe en la ruta equivocada se ve IDENTICO a uno bueno -- tiene `command:` y tiene `exit_code:` -- y por eso atraviesa a los revisores. Casos: `check_entrypoint_fails_closed` valida el entrypoint con `[sys.executable, ENTRYPOINT]` mientras produccion lo lanza **por shell** con `python` pelado, asi que prueba una ruta que produccion nunca toma; y el diagnostico de WOT-2026-020o midio `python` en **PowerShell** cuando el hook corre en **Git Bash**, lo que subio la ficha a Alta y ato WOT-2026-024f a ella sobre una premisa falsa (2026-07-15).
  - **ESTATUS DECLARADO: esto es una NORMA, no una barrera** (segun la definicion de "Barrera cableada" de esta misma lista: nadie la invoca sola, depende de que el agente se acuerde). Se declara asi a proposito en vez de disfrazarla de gate. El recibo es mecanizable y los checks POR DOMINIO si son cableables (p.ej. el censo de WOT-2026-024f debe resolver en Git Bash); un verificador GENERICO de equivalencia no es trivial, porque **no existe oraculo universal de "la ruta productiva"**: para comparar contra produccion hay que ejecutar en produccion, y entonces la comparacion sobra. Deuda declarada con dueno: **WOT-2026-025f**.
- **El conflicto entre probes ES el hallazgo:** si dos mediciones del mismo hecho se contradicen, **no elijas la que confirma tu tesis, ni promedies, ni descartes la incomoda**: averigua QUE mide cada una, porque casi siempre **una de las dos no es produccion**. `python -c "pass"` dio TRES exit codes el mismo dia en la misma maquina -- `subprocess(shell=False)` -> 0 (CreateProcess resuelve primero el dir del ejecutable PADRE: el python del venv), cmd/PowerShell -> 1 (shim `python.BAT`), Git Bash -> 0 (el `python.exe` real). Dos de los tres producian un veredicto FALSO sobre produccion: uno un falso VERDE y otro un falso ROJO. La contradiccion es material de auditoria de primer nivel, no ruido a resolver por mayoria.
- **Memoria despues de aprender:** si una familia de fallos puede repetirse, deja barrera automatica o deuda explicita con ticket y criterio de salida.
- **Rigor proporcional:** docs y typos no cargan la misma ceremonia que bus, supervisor, seguridad, rutas o estado compartido.
- **Barrera verificada:** un guard, hook o test nuevo no cuenta hasta demostrar que bloquea el fallo que promete bloquear.
- **Barrera cableada:** ademas de morder, algo tiene que INVOCARLA. Un guard solo es barrera si lo llama un camino que corre solo (pre-commit, CI, `prepush_check`, closeout, preflight, controlador, hooks de tool-call). Citarlo en un prompt, una skill o este AGENTS.md **no es cableado: es una norma**, y una norma depende de que alguien se acuerde. Barrera de la barrera: `scripts/check_guard_wiring.py` (WOT-2026-024u) - un guard nuevo sin cablear FALLA; la deuda legacy solo puede quedar en WARN si esta DECLARADA con su ticket dueno.
- **Aplicate tu propia vara (y que lo diga otro):** un guard que mide una propiedad P tiende a medirla con una vara MAS FLOJA que la que predica, y sale verde igual. `check_guard_wiring` nacio declarando que "una cita en un prompt es una norma, no un mecanismo"... y clasificaba casando nombres contra el TEXTO CRUDO de los ficheros: la misma vara que su docstring llamaba insuficiente. Daba por cableados guards citados solo en un COMENTARIO, o en hooks `stages: [manual]`. Sus 16 tests, los 4 gates y la suite entera (4094 passed) pasaron verdes: todos hermeticos, y el defecto vivia en la frontera con el repo REAL. Lo cazo una auditoria adversarial HERMANA en contexto fresco. Regla: aplica P a tu propio guard **ejecutandolo**, no leyendolo, y no lo des por bueno sin una pasada adversarial externa - el mismo sesgo que escribio el codigo escribio los tests.
- **Barrera del alcance, no solo del mecanismo:** un guard puede estar cableado, morder, y no mirar donde ocurre el fallo. Caso historico: `check_encoding_guard` es fail-closed y corre en pre-commit, pero durante meses se limitaba a `.py`; por eso DOS fugas de markup de modelo vivieron sin detectar dentro de `AGENTS.md` y `MANUAL_PUBLICATION_CHECKLIST.md` - esta ultima desde el commit inicial del repo (WOT-2026-024x). Ya CORREGIDO (WOT-2026-025n): desde df674bb el guard cubre `.md` (TEXT_EXTENSIONS + GLOB_PATTERNS `*.md`, `prompts/**/*.md`, ...), asi que hoy SI mira donde ocurrio aquel fallo. El PRINCIPIO sigue vigente: un guard nuevo se audita por DONDE mira, no solo por si muerde.
- **Criterio invariante, evidencia fechada:** un DoD debe ser un INVARIANTE, no una MEDICION. Un criterio que fija un numero ("quedan 11 hits", "243 auditorias") caduca solo, sin que nadie toque la ficha, y el Builder ya no puede distinguir "el numero cambio porque el mundo avanzo" de "cambio porque he roto algo". El numero es EVIDENCIA: va etiquetado como snapshot fechado, nunca como criterio de aceptacion (WOT-2026-024t).
- **Un umbral en una MESETA no es un umbral medido** (corolario de la regla anterior, medido 2026-07-22): un numero puede pasar todos los gates y no haberse medido nunca. `_NEGATION_WINDOW=12` se eligio a ojo y su comentario lo justificaba con una precision que no tenia; el barrido posterior mostro `W=4 -> 4 failed | W=10 -> 1 | W>=12 -> 26 passed`: 12 es el BORDE INFERIOR de una meseta ABIERTA, sin cota superior pinneada -- subirlo a 30 no rompe ningun test pero amplia el efecto. **Y el primer barrido dio una cifra FALSA** ("meseta >=6") porque se corrio contra fixtures ad-hoc escritos para el barrido: un barrido contra tus propios fixtures mide tus fixtures, no el sistema. REGLA: barre contra la SUITE REAL, publica AMBOS bordes, y si la cota superior queda abierta, dilo -- "esta en una meseta >=N, sin cota superior" es honesto; una justificacion sin barrido es relato.
- **Fixtures realistas:** un test verde contra un fixture irreal es sospechoso; cuando el contrato sea operativo, contrasta contra artefactos reales.
- **Gates self-service:** un gate preserva autonomia solo si explica que fallo, como reproducirlo y como volver a validar sin escalar al humano.
- **Relaunch con root verificado:** antes de relanzar Builder, valida `AGENT_PROJECT_ROOT`, `repo_motor`, `repo_destino`, bus legible y ticket activo.

Referencia ampliada: `.agent/rules/common/sustainable_engineering.md`.

## Hacer ahora vs aplazar (criterio de decision)

El coste de APLAZAR **no es cero**. Ver criterio completo de 8 gates, balanza minima, STOP de degeneracion y dos reglas durables en .agent/rules/common/do_now_vs_defer.md.

## Skills Formales de Proceso

El repositorio define skills operativas formales para estructurar el trabajo del agente.
Úsalas invocando sus triggers (ej. `/tdd`, `/debug`):

- **Test-Driven Development (TDD)** (`skills/test-driven-development/SKILL.md`): Usar para asegurar cobertura y evitar regresiones en código nuevo o fixes. Obliga a escribir el test primero (Red), el código mínimo (Green) y refactorizar con calidad (`ruff` + `pytest`).
- **Systematic Debugging** (`skills/systematic-debugging/SKILL.md`): Usar ante errores no triviales. Exige investigación de causa raíz antes de parchear y establece un límite estricto de 3 intentos antes de detener la iteración y cuestionar el entendimiento del problema.

No uses estos skills si contradicen el flujo general (ej. usar TDD para escribir un README o depuración para un typo reportado por el linter).

### Gobierno skill<->prompt: skill apunta, prompt gobierna (WOT-2026-014r / X-09)

Ver criterio de re-declaracion prohibido, auditoria automatica y matriz de ownership en .agent/rules/common/x09_skill_prompt_governance.md.

## Atribuciones externas (CREDITS.md)

**Limitación conocida:** CREDITS.md vive en raíz. Ver protocolo completo y formato de tabla en .agent/rules/common/credits_external_attributions.md.

## Memoria por proyecto

**Lo primero, porque es lo que mas se malinterpreta (WOT-2026-057a/b):**

- **`--bootstrap` entrega un INDICE, no el corpus.** Las lineas marcadas
  `...[truncated]` son titulares con su `id`; el pie declara cuantas lecciones NO
  muestra.
- **`--recall` es la puerta de EXPANSION**, y entrega la leccion ENTERA:
  `python scripts/memory_context.py --recall --query "<termino>"` (ordenado por
  cobertura, con fallback por terminos) o
  `python scripts/memory_context.py --recall --id obs-<slug>` (exacto,
  fail-closed). Ejecutalo ANTES de medir o disenar.
- **El archive portable se lee como UNION de MOTOR + root activo**, con cuota por
  origen: la recencia no es relevancia, y sin cuota el repo tocado mas recientemente
  expulsa al otro entero.
- **El hook `SessionStart` inyecta el indice al abrir sesion.** La EXPANSION sigue
  siendo manual.
- **La memoria PRIVADA de un backend no es autoritativa:** lo canonico es lo
  versionado. Una leccion que solo vive en la memoria privada de un agente NO EXISTE
  para el sistema.

Arquitectura completa (jerarquia L3/L2/L1, `bus/memory_loader.py` y sus topes por
puerta, contrato de `MEMORY.md`, historia A1/A2 y limites declarados) -- referencia
bajo demanda, consulta al disenar o depurar el propio mecanismo de memoria:
`.agent/rules/common/memory_hierarchy.md`.

## deliverable_type (work_plan schema, V2)

Cada `work_plan.md` declara `deliverable_type` en su sección Metadata. Valores:
- `code` — el deliverable principal es código fuente (Python u otro).
- `documentation` — markdown, AGENTS.md, READMEs.
- `research` — análisis comparativos, reportes (gap analysis, repo-compare).
- `analysis` — estudios técnicos, audits.
- `mixed` — combinación legítima (ej. WP que toca código y docs).

`agent_controller --validate` valida que exista el campo y no tenga valores inválidos.

### Contrato operativo por tipo de ticket

El `deliverable_type` no es decorativo: cambia que evidencia debe producir el Builder y que debe
auditar el Manager. Detalle (referencia bajo demanda, consulta al redactar o revisar un
`work_plan.md`): `.agent/rules/common/deliverable_type_dispatch.md`.

## Quality gates dispatch by deliverable_type (WP-2026-089)

`builder-run-quality-gates` despacha los gates segun el `deliverable_type` del work_plan activo
via `scripts/run_gates_dispatch.py`: `code`/fallback -> ruff + pytest-safe + pip-audit
(condicional); `mixed` -> ambos sets (code gates + deliverable existence check);
`documentation`/`research`/`analysis` -> solo deliverable existence check. `pip-audit` solo corre
si `Files Likely Touched` (en `work_plan.md`) incluye un manifiesto de dependencias (si no, salto
auditable). Los hooks `ruff-check`/`ruff-format` deben seguir limitados estrictamente a Python
(`scripts/check_ruff_hook_scope.py`); cualquier desviacion detiene inmediatamente las gates de
pytest. Dispatcher, politicas y guardias: stdlib only; no anaden dependencias. Detalle
(referencia bajo demanda): `.agent/rules/common/deliverable_type_dispatch.md`.

## Host-first skill precedence & Config Profiles (WP-2026-090)

En un destino, las skills del host (`<destino>/.agent/skills/`) toman precedencia absoluta sobre
las homonimas del bundle, que actua solo como fallback determinista. `agents.json` define
`active_profile`: `engine-dev` en el motor; `install_agent_system.py` lo cambia a `host-project`
en el destino durante `--install`/`--sync`. Detalle (referencia bajo demanda):
`.agent/rules/common/host_install_integration.md`.

## Host setup hook (WP-2026-094)

Si el destino declara un script ejecutable `.agent/host-setup.sh`/`.ps1`,
`scripts/install_agent_system.py` lo detecta tras la copia del bundle, muestra sus primeras 20 lineas y
solo lo ejecuta con confirmacion humana (`y/N`; `--yes` la salta); exit != 0 aborta el install y
propaga el codigo; sin hook, silencio. Detalle (referencia bajo demanda):
`.agent/rules/common/host_install_integration.md`.

## Pluggable manager review rubric by deliverable_type (WP-2026-091)

`bus/review_bridge.py` adapta el prompt de review del Manager al `deliverable_type` del plan
(tipo ausente o desconocido: fallback seguro y automatico a `code`) y conserva intacta la salida
canonica `DECISION: APPROVE` / `DECISION: CHANGES` (interoperabilidad con el bus y la maquina de
estados). Detalle (referencia bajo demanda): `.agent/rules/common/deliverable_type_dispatch.md`.

## Secretos y seguridad

- No guardes credenciales, tokens ni rutas sensibles.
- No toques `privada/`.
- No desactives `guard_paths` para trabajar mas rapido.
- No pidas dependencias nuevas sin aprobacion.
- `OpenCode Permission Preflight`: si el ticket requiere modificar archivos
  fuera de `.agent/collaboration/` o `scripts/` del `repo_destino` (por
  ejemplo `PROJECT.md`, `AGENTS.md` o `CHANGELOG.md`), el plan o el arranque
  debe verificar antes que esas rutas esten permitidas en
  `.opencode/opencode.json` bajo `external_directory`. Si no lo estan, el
  Builder debe bloquear el arranque con diagnostico claro en vez de continuar
  ciego. En OpenCode, esa allowlist puede necesitar el root completo del
  `repo_destino` (`repo_destino\*`) y no solo permisos por archivo, porque el
  backend puede resolver la lectura como acceso al arbol externo completo.
- La configuracion versionada de `.opencode/opencode.json` debe permanecer
  portable y sin rutas absolutas del `repo_destino` actual. Los permisos
  `external_directory` especificos del proyecto se inyectan en runtime desde el
  launcher y se restauran al terminar; no deben quedar commiteados en el motor.
- Proteger `main` del motor en origin (WOT-2026-024i): `main` es la fuente
  canonica de los destinos; debe llevar un ruleset de GitHub que bloquee
  force-push y deletion (sin exigir PRs, para no romper el push directo del
  cierre). La activacion es accion humana; la verificacion re-ejecutable y la
  prueba de rechazo no destructiva viven en `RELEASE_CHECKLIST.md` (paso 6).

## Robust Builder Relaunch (WP-2026-084)

Tras un CHANGES, el supervisor verifica que el Builder siga vivo (PID + `tasklist`; fallback
mtime <15 min) antes de relanzar y pasa `-ResumeBuilder` al launcher, que entonces salta el
cleanup agresivo para no matar un Builder vivo; sin el flag, el launcher se comporta igual que
antes (aditivo, cero regresion). Detalle (referencia bajo demanda):
`.agent/rules/common/builder_relaunch.md`.

## Criterio de cierre

> Detalle operativo de los quality gates y comandos diarios (incluye flags exactos y secuencia recomendada): ver [QUICKSTART.md sección "6. Comandos diarios"](QUICKSTART.md#6-comandos-diarios).

Considera una tarea cerrada solo cuando:
1. `ruff`, `pytest` y `pip-audit` pasan.
2. El codigo nuevo usa rutas y manejo de errores correctos.
3. Las decisiones importantes quedan consolidadas en `PROJECT.md` o `CHANGELOG.md`.
4. La revision aplica el principio de Google de aprobar cuando el cambio mejora la salud del codigo, aun si no es perfecto: https://google.github.io/eng-practices/review/reviewer/standard.html
