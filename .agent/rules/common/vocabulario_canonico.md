# Vocabulario canonico (WOT-2026-114c)

> Modulo movido desde `AGENTS.md` seccion "## Vocabulario canonico" (Fase 2 de la Palanca A,
> `docs/followups/palanca-a-raiz-agents-md-diseno.md`). Cuerpo verbatim, sin resumir (non-goal
> duro de `prompts/doc_optimization.md`). La cuspide en `AGENTS.md` conserva las frases
> normativas literales (prohibiciones duras / refutaciones) y un puntero aqui.

No usar "workspace" a secas: el termino es ambiguo porque describe tanto el repo destino como el entorno multi-root del IDE.

| Termino | Descripcion |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` -- motor portable, fuente canonica del sistema. Tiene su propio repo git. No contiene estado operativo de tickets. |
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

**Ese nombre es una foto fija y puede caducar DESPUES de dárselo a la hija** (bucle UNI-7,
2026-10-21): la hija verifica con `ListAgents` antes de su primer `SendMessage` de informe y deja
constancia de esa verificacion. Detalle en
[nombre_coordinadora_puede_caducar](../../../docs/protocol/nombre_coordinadora_puede_caducar.md).

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
  [ticket_nomenclatura_bloque_legacy_etiquetado](../../../docs/protocol/ticket_nomenclatura_bloque_legacy_etiquetado.md).

Gate ejecutable: `scripts/check_ticket_nomenclature.py` clasifica cada hit y
falla solo ante un generador/ejemplo vivo con prefijo legacy sin etiqueta.

### Distincion critica: `.agent/collaboration/` del motor vs del destino

| Ubicacion | Rol | Contenido |
|-----------|-----|-----------|
| `repo_motor/.agent/collaboration/` | **Seed neutro** | Archivos en estado READY_TO_START/IDLE. Molde para nuevos destinos instalados. No contienen tickets activos. |
| `repo_destino/.agent/collaboration/` | **Estado operativo activo** | `work_plan.md`, `execution_log.md`, `TURN.md`, `STATE.md`, `backlog.md` con el ticket real en curso. |

**Nunca usar `repo_motor/.agent/collaboration/` como operativo.** El guard anti-drift bloquea escrituras operativas ahi sin `AGENT_PROJECT_ROOT`.
