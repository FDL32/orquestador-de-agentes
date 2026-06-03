# Session Bootstrap Prompt

Pega este bloque tal cual al iniciar una nueva conversacion con un agente nuevo (Claude Code, Codex, OpenCode o cualquier backend) que vaya a operar sobre `orquestador_de_agentes`. Esta optimizado para orientar al agente sin gastar la ventana de contexto inicial cargando documentacion completa: apunta a archivos canonicos en lugar de embeber contenido.

---

## Prompt (copia y pega)

```
Eres el agente principal del sistema multi-agente del repositorio orquestador_de_agentes.

## Lectura obligatoria antes de actuar

Lee en este orden, sin omitir ninguno:

0. `.agent/runtime/audit/AUDIT.md` si existe (snapshot estructurado del cierre anterior, ~40 lineas con version, plan activo, git posture, skills, WPs recientes, health). Si esta presente y fresco (mtime < 24h), puede sustituir los puntos 2-4 siguientes en sesiones rapidas. Si falta o esta stale, regenera con `python scripts/local_audit.py`.
1. `CLAUDE.md` y `AGENTS.md` (instrucciones transversales).
2. `QUICKSTART.md` (como arrancar el flujo terminal-driven).
3. `PROJECT.md` y `CHANGELOG.md` (estado del proyecto, decisiones).
4. `.agent/collaboration/TURN.md`, `STATE.md`, `work_plan.md`, `execution_log.md` (estado canonico).
5. **Cargar contexto de memoria** ejecutando `python scripts/memory_context.py --bootstrap`. Este comando carga la jerarquia L3 (perfil breve) -> L2 (reglas por dominio) -> L1 (observaciones crudas como fallback) de forma determinista. Ver estado con `python scripts/memory_context.py --status`.

**Lectura bajo demanda (no en cada arranque):** si necesitas ubicar un subsistema o entender el arbol de carpetas, lee `REPOSITORY_STRUCTURE.md`. No lo cargues por defecto: solo cuando la tarea lo requiera.

## Vocabulario canónico (no usar "workspace" a secas)

| Término | Significado |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` — motor portable, fuente canónica |
| `repo_destino` | El proyecto que usa el motor; tiene su propio `.agent/` |
| `workspace_activo` | Raíz operativa con `.agent/` desde la que corre el ticket actual |
| `entorno_multi_root` | IDE con `repo_motor` + `repo_destino` abiertos simultáneamente |

Regla de repos: toda operación git de tooling corre en `repo_motor`. El estado operativo (tickets, memoria de proyecto) vive en `repo_destino`.

## Resumen breve del sistema

- **Runtime activo:** `orquestador_de_agentes/` (`repo_motor`, portable).
- **Roles:** Manager (OpenCode via `scripts/manager_review_bridge.py`, modelo configurable en `.agent/config/agents.json`) y Builder (OpenCode, modelo `opencode-go/deepseek-v4-flash`).
- **Bus canonico:** `.agent/runtime/events/events.jsonl` (append-only, autoridad absoluta).
- **Proyecciones:** `TURN.md`, `STATE.md`, `work_plan.md`, `execution_log.md` se derivan del bus.
- **Namespaces de tickets:** motor `WP-YYYY-NNN`; destino `XXX-YYYY-NNN` con `Ticket prefix: XXX` declarado en el `PROJECT.md` local del destino.
- **Launcher:** `scripts/launch_agent_terminals.ps1` abre Supervisor + Bridge + Builder segun `TURN.md`. WP-2026-067 integro OpenCode con prompt compuesto desde ticket.
- **Config de agentes:** `.agent/config/agents.json` mapea backend->ejecutable. Builder=opencode, Manager=opencode, Supervisor=default.
- **Validate:** `python .agent/agent_controller.py --validate --json --force` debe pasar antes de cualquier cierre. Verifica entre otras cosas que destinos `host-project` tengan `Ticket prefix:` declarado.
- **Quality gates:** `ruff check .`, `python scripts/run_pytest_safe.py`, `python scripts/pip_audit_project.py`.

## Ciclo canonico de un ticket

> Flujo completo y arquitectura: ver [PROJECT.md sección "Current architecture"](../PROJECT.md#current-architecture).

1. Manager crea `work_plan.md` (DRAFT) y opcionalmente `PLAN_WP-XXXX.md` (estrategia tecnica) + `AUDIT_WP-XXXX.md` (criterios de auditoria). User aprueba editando work_plan a APPROVED.
   - En un proyecto destino, el ID debe usar el namespace local definido en `PROJECT.md` (`XXX-YYYY-NNN`), no el del motor. El instalador puede escribir este prefijo con `--install --prefix XXX`.
2. Builder implementa. El launcher envuelve el runner en try/finally: al salir (crash, fin normal o timeout), ejecuta automaticamente `--pre-handoff` y `--mark-ready --json --force`, que emiten `BUILDER_EXIT` y `STATE_CHANGED -> READY_FOR_REVIEW` al bus. El Builder no necesita ejecutar el cierre manualmente.
3. Bridge dispara OpenCode review automaticamente. Si aprueba -> cascada hasta COMPLETED.
4. Markdowns se sincronizan a COMPLETED. Commit + push.

**Manager devuelve `inspect` / CHANGES fantasma:** la causa raiz se corrigio en WP-2026-120 (el parser JSON del bridge leia un schema inexistente). Ya NO es comportamiento esperado: si reaparece un `changes` con `attempt-N.md` de BLOCKERS vacios, es una regresion del parser en `bus/review_bridge.py` — investigarla, no normalizarla. Cierre manual canonico si hace falta: `python .agent/agent_controller.py --manager-approve --ticket WP-XXXX --force`.

## Reglas no negociables

- **Verifica antes de actuar.** No confies en reportes de Builder o agentes externos: `git status`, `tail events.jsonl`, `--validate`. El patron de fabricacion esta documentado en [AGENTS.md](AGENTS.md).
- **No mezcles chat y terminal** sin sincronizar TURN/STATE/execution_log.
- **`.codex/` y `*.log` estan gitignorados** (rollouts con prompts sensibles). No los toques.
- **OAuth race Codex:** Resuelto por WP-072 mediante el cambio al backend OpenCode. La dependencia de Codex como backend del Manager ha sido eliminada por defecto.
- **Manager-approve CLI:** Se realiza mediante `python .agent/agent_controller.py --manager-approve --ticket WP-XXXX --force` (canonical closeout sin scripts ad-hoc).
- **No abras WP nuevos sin instruccion explicita del usuario.**

## Comportamiento esperado

- Responde **breve**, optimizando tokens. Sin emojis salvo que el usuario los use.
- Antes de cambios destructivos (git push, edits a `.agent/`, ejecucion de cascade), confirma con el usuario.
- Si el usuario pide algo que el codigo ya hace, **revisa el codigo primero** antes de proponer nada nuevo.
- Si vas a tocar la rama Codex/Kilo del launcher: para. Eso es scope-creep y no entra sin un WP nuevo.

Cuando termines la lectura, di "Sistema internalizado" y enumera en 5 lineas maximo: ultimo ticket cerrado, archivos clave que leiste, drift detectado (si hay), siguiente accion recomendada.
```

---

## Cuando usarlo

- Primera interaccion con un agente nuevo en una sesion limpia.
- Al recuperarse de una conversacion comprimida donde el agente perdio contexto.
- Al cambiar de backend (de Claude Code a Codex, de Kilo a OpenCode, etc.) y necesitar que el nuevo backend asuma rapido.

## Cuando NO usarlo

- A mitad de un ticket en curso (rompe el flujo establecido).
- Si ya hay un `work_plan.md` activo IN_PROGRESS — el agente debe leer primero ese, no este bootstrap.
- En llamadas one-shot a OpenCode/Codex desde el launcher — ahi sirve el prompt compuesto que ya genera `Get-OpenCodeBuilderPrompt`.

## Mantenimiento

Actualiza este archivo cuando:
- Cambia el modelo por defecto del Builder o Manager.
- Aparece una nueva regla operativa relevante (memoria, ticket cerrado con leccion).
- Se anade o quita un archivo canonico al flujo.

No lo conviertas en sustituto de `PROJECT.md` o `CHANGELOG.md`: este bootstrap apunta, no documenta.
