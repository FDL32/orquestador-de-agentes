# Quickstart

Use this file to start the template in a fresh project, relaunch the terminal-driven workflow, or begin the next planning cycle after canonical closure.

> **Onboarding de agente nuevo:** si arrancas una sesion limpia con un agente que no conoce el repo, pega primero el bootstrap canonico en `prompts/session_bootstrap.md`. Eso lo orienta sobre roles, archivos canonicos y reglas sin gastar contexto cargando docs completas.

## 0. Reproducible launcher

The recommended way to start the three canonical terminals is the repo-local launcher:

```powershell
.\scripts\launch_agent_terminals.ps1
```

The launcher performs a comprehensive startup hygiene check before opening any window:
- Compares `.agent/collaboration/work_plan.md`, `.agent/collaboration/TURN.md` and `.agent/collaboration/STATE.md` to ensure alignment (strict by default, abort on drift)
- Closes stale project sessions before preflight so old supervisor or bridge windows cannot reattach to the previous ticket
- Clears a stale `manager_bridge_state.json` cursor when it points to an older ticket
- Clears a stale `supervisor_state.json` cursor when it points to a different ticket than `work_plan.md`
- Launches Builder only when `.agent/collaboration/TURN.md` says `BUILDER` or when manual override is specified via `-BuilderPrompt`
- Prevents duplicate Builder sessions scoped to the current project using a lock file
- Closes stale project sessions from previous tickets before opening the next cycle
- Reads the active ticket from `.agent/collaboration/work_plan.md` and applies the prompt automatically
- Resolves the current PowerShell host, Codex CLI and OpenCode executable dynamically instead of pinning one extension build
- Emits short reports per launched window for clarity
- **OpenCode integration (historical: WP-2026-067)**: When the Builder backend is OpenCode, the launcher invokes `opencode run "<msg>" --agent builder --model <model> --dir <root> -f <canonicals>` with a composed prompt from the active ticket, model read from `.opencode/opencode.json`, and canonical files attached. No manual paste required.

The launcher opens windows independently for each agent:
- **Supervisor window**: Runs `python scripts\ticket_supervisor.py --reactive`
- **Review Bridge window**: Runs `python scripts\manager_review_bridge.py --watch --backend-path <path>`
- **Builder window**: Opens OpenCode with the active ticket prompt and the Builder contract in `.opencode/agents/builder.md` (only when appropriate)

Use `-StrictLaunch:$false` to skip strict validation. The launcher still cleans stale or corrupt bridge state in both modes, but strict mode additionally aborts on alignment drift before opening windows.
In flexible mode, the preflight output also reports whether `manager_bridge_state.json` and `supervisor_state.json` were repaired.

The launcher is intelligent:
- Always launches Supervisor and Review Bridge (if enabled).
- Launches Builder when the active role in `.agent/collaboration/TURN.md` is `BUILDER` or when `-BuilderPrompt` is provided for manual override.
- Prevents duplicate Builder sessions scoped to the current project using a lock file.
- Closes stale project sessions from previous tickets before opening the next cycle.
- Reconciles stale supervisor runtime state so the next ticket does not inherit a previous `active_ticket`.
- Schedules cleanup for the manager prompt temp file after the Review Bridge starts.
- Cleans up old bridge state to avoid carrying over tickets between sessions.
- **OpenCode backend (historical: WP-2026-067)**: Composes the prompt from the active ticket, reads the model from config, and attaches canonical files via `-f`.

Optional manual Builder auto-run (for testing or override):

```powershell
.\scripts\launch_agent_terminals.ps1 -BuilderPrompt "Actua como BUILDER para [NEXT_TICKET]. Lee .agent/collaboration/TURN.md, .agent/collaboration/work_plan.md, .agent/collaboration/execution_log.md, .agent/collaboration/STATE.md y PROJECT.md. Implementa solo [NEXT_TICKET] siguiendo .agent/collaboration/work_plan.md. No cambies el alcance. No reescribas el plan. Registra evidencia clara en .agent/collaboration/execution_log.md. Mantente en el runtime bus-first y evita editar .agent/collaboration/TURN.md, .agent/collaboration/STATE.md o .agent/collaboration/execution_log.md a mano. Ejecuta ruff y pytest-safe sobre lo tocado. Ejecuta python .agent\agent_controller.py --mark-ready --json --force al final."
```

**Note:** When the Builder backend is OpenCode (default for this repo), the launcher automatically composes the prompt and invokes `opencode run` with the model from `.opencode/opencode.json` and canonical files attached. The manual paste step from WP-2026-066 and earlier is no longer required.

OpenCode model selection lives in the repo-local config in:

```text
.opencode/opencode.json
```

The `model` field in that file is the place to switch the AI used by OpenCode. The current target label is `Qwen3.5 Plus`, but the exact `provider/model` mapping remains [NO VERIFICADO].

## 0b. Role-to-backend mapping

Builder and Manager are roles; the backend can vary.

| Backend | Builder use | Manager use | Where to configure |
|---------|-------------|-------------|--------------------|
| OpenCode | Default Builder sessions for this repo | N/A for review flow | `.opencode/opencode.json` and `.opencode/agents/builder.md` |
| Claude Code | Chat-driven builder sessions or terminal sessions | Review bridge / orchestration | Claude Code app/session settings |
| Codex | File-driven builder or manager runs | Review bridge and terminal orchestration | `~/.codex/config.toml` |
| Cline | VS Code agent manager for Builder or Manager tasks | Manual review or bridge-like workflows | `~/.cline/data/settings/cline_mcp_settings.json` |
| Kilo | Alternate Builder or Manager backend when explicitly selected | Alternate Builder or Manager backend when explicitly selected | `~/.config/kilo/kilo.jsonc` |

Rule:
- If you switch backend during a ticket, update `.agent/collaboration/TURN.md`, `.agent/collaboration/STATE.md`, `.agent/collaboration/execution_log.md`, and `.agent/collaboration/notifications.md`.
- The role stays the same even if the backend changes.

## 0c. Startup Templates

`WP-2026-040` introduced startup templates by role/backend to eliminate manual prompt copying. `WP-2026-041` added automated review loop reusing templates with previous feedback. `WP-2026-042` achieved canonical closure with full archival and documentation synchronization. `WP-2026-043` hardened the closeout boundary so completion required explicit Manager approval before returning to `COMPLETED`, and the repository is now back in idle clean state. `WP-2026-066` aligns integration tests and public documentation with the recovered baseline.

The current cycle is `WP-2026-075` completed (Event Bus Observability). DeepEval / LLM evals are kept separate from the deterministic supervisor flow. `WP-2026-053` remains closed as session closeout robustness.

If you need a clean restart after an interrupted session, use the supervisor directly:

```powershell
Set-Location <repo_root>

python scripts\ticket_supervisor.py --once
```

Regla operativa:
- Builder, Manager y Supervisor comparten la misma estructura de arranque.
- El launcher inyecta `ticket_id`, `work_plan`, `close_command`, `role` y `backend`.
- Si cambias backend durante un ticket, actualiza `.agent/collaboration/TURN.md`, `.agent/collaboration/STATE.md`, `.agent/collaboration/execution_log.md` y `.agent/collaboration/notifications.md`.

## 1. Preflight

```powershell
python .agent\agent_controller.py --validate --json --force
```

If validation is clean, the template is ready to run.

## 2. Terminal-driven startup

For the current active ticket, the launcher follows `.agent/collaboration/work_plan.md`. If the repository is idle, begin the next planning cycle with:

1. **Manager creates new `.agent/collaboration/work_plan.md`** with the next approved ticket
2. **Validate clean state**: Run `python .agent\agent_controller.py --validate --json --force`
3. **Launch terminals**: Use `.\scripts\launch_agent_terminals.ps1` for template-based startup

### Terminal 1: Builder (when active ticket is ready)

```powershell
code .
```

In VS Code, open OpenCode and launch the Agent Manager.
The launcher will automatically apply the correct Builder prompt for the active ticket when the backend is OpenCode.

**Automatic prompt composition (OpenCode backend):**
When the Builder backend is OpenCode, the launcher composes the prompt from the active ticket and invokes:

```powershell
opencode run "<msg>" --agent builder --model <model> --dir <root> -f <canonicals>
```

Where:
- `<msg>` is composed from `ticket_id` with closure instructions
- `<model>` is read from `.opencode/opencode.json`
- `<canonicals>` are `.agent/collaboration/work_plan.md`, `TURN.md`, `execution_log.md`, `STATE.md`, and optionally `PLAN_<ticket>.md` / `AUDIT_<ticket>.md`

No manual paste is required.

### Terminal 2: Supervisor

```powershell
python scripts\ticket_supervisor.py --reactive
```

Supervisor prompt, if you need to run it manually:

```text
Actua como SUPERVISOR del flujo terminal-driven.
Mantén la cola coherente.
No permitas trabajo fuera del ticket activo.
Si el ticket pasa a READY_FOR_REVIEW, deja que el review bridge dispare la revision.
Si el ticket se cierra, prepara el siguiente turno sin inventar tickets.
```

### Terminal 3: Review Bridge

```powershell
python scripts\manager_review_bridge.py --watch --backend-path "<path-to-codex.exe>"
```

Manager review prompt, if you need to run it manually:

```text
Actua como MANAGER reviewer para el ticket activo definido en .agent/collaboration/work_plan.md.
Revisa la implementacion contra .agent/collaboration/work_plan.md y .agent/collaboration/execution_log.md.
Decide solo: APPROVE, CHANGES o INSPECT.
Si apruebas, deja evidencia de aprobacion y permite el paso a READY_TO_CLOSE.
Si pides cambios, enumera solo los ajustes necesarios.
No amplíes el plan.
No reescribas el ticket entero.
```

## 3. What each terminal does

- **Builder**: Implements approved tickets following `.agent/collaboration/work_plan.md`, registers evidence in `.agent/collaboration/execution_log.md`, executes quality gates, and performs mandatory closure protocol.
- **Supervisor**: Orchestrates the sequential queue via terminal-driven workflow, synchronizes `.agent/collaboration/TURN.md`, `.agent/collaboration/execution_log.md`, and `.agent/collaboration/notifications.md`, advances the queue when appropriate.
- **Review Bridge**: Launches Manager review automatically when tickets reach READY_FOR_REVIEW, handles APPROVE/CHANGES decisions with deterministic flow.

## 3b. Flujo operativo para Builder

Builder follows this sequence for each ticket:

1. **Read Context:** Read `.agent/collaboration/TURN.md`, `.agent/collaboration/work_plan.md`, `.agent/collaboration/execution_log.md`, `.agent/collaboration/STATE.md`, `PROJECT.md`.
2. **Implement:** Execute only the active ticket scope using allowed tools and files. Treat `Files Likely Touched` as a hard whitelist. Do not widen scope without Manager approval.
3. **Register Evidence:** Document all changes with timestamps and commands in `.agent/collaboration/execution_log.md`.
4. **Quality Gates:** Run `ruff check`, `pytest-safe`, `pip-audit` on touched files.
5. **Closeout Post-Review:** Execute mandatory closure protocol. The hard scope gate will block `--mark-ready` if any changed files are outside the whitelist unless `--scope-override "reason"` is used.

## 3c. Cierre Post-Review Repetible

After implementation and before reporting work done:

```powershell
python .agent/agent_controller.py --mark-ready --json --force
```

This command:
- Marks the ticket as `READY_FOR_REVIEW` in `.agent/collaboration/execution_log.md`
- Updates `.agent/collaboration/TURN.md` to Manager/REVIEW_WORK
- Regenerates `.agent/collaboration/STATE.md` with current status
- Validates no drift between canonical files
- Emits event for Supervisor and Review Bridge detection
- Leaves the runtime easier to reconcile on the next confirmed closeout because stale cursor files are treated as disposable runtime artifacts.

**Do not consider work finished without executing this command.** It ensures the release is repeatable and reduces post-review drift.

## 4. Reconciliación si Supervisor/Bridge ya están en ejecución

If you see stale state (e.g., Supervisor still watching an old ticket), you must reconcile:

```powershell
# Terminal 1: Kill existing Supervisor/Bridge if they are running
# (Ctrl+C in the terminal, or use Task Manager if needed)

# Terminal 2: Reconcile state
python scripts/ticket_supervisor.py --once

# Then restart Supervisor in reactive mode
python scripts/ticket_supervisor.py --reactive

# And restart the Review Bridge
python scripts/manager_review_bridge.py --watch --backend-path "..."
```

**Why:** Supervisor caches runtime state. If you execute `--mark-ready` while Supervisor is still watching an old ticket, it may not detect the transition immediately. A restart ensures clean reconciliation. Do not delete `.agent/runtime/manager_bridge_state.json`; keep the cursor so the bridge does not replay an already-reviewed ticket.

## 5. Si empiezas desde chat en vez de terminal

> Comparativa completa de modos (chat-driven vs terminal-driven, cuándo usar cada uno, transiciones): ver [INTERACTION_MODES.md](INTERACTION_MODES.md). Esta sección cubre solo el atajo operacional.

Use the current ticket, then update:
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/notifications.md`
- `.agent/collaboration/STATE.md`

## 6. Comandos diarios

> Comandos de instalación y sincronización: ver [AGENTS.md sección "Comandos principales"](AGENTS.md#comandos-principales). Esta sección cubre solo los comandos del ciclo diario (validate, tests, lint).

```powershell
python scripts/run_pytest_safe.py
ruff check .
uv run pip-audit .
python .agent/agent_controller.py --health
```

Prefer `scripts/run_pytest_safe.py` for normal Windows runs. Use raw `pytest` only for targeted diagnostics when the environment is already safe.

El comando `--health` proporciona un resumen operativo derivado de manifests y estado canónico.

## 7. Multi-Ticket Integration Smoke

Para validar la seguridad multi-ticket y que tickets consecutivos no arrastran estado:

```powershell
python scripts/run_pytest_safe.py tests/integration/test_multi_ticket_integration_smoke.py -q
```

Este smoke test de `WP-2026-039` ejecuta tres escenarios deterministas:
- **Escenario A**: Recorrido feliz completo con APPROVE limpio.
- **Escenario B**: CHANGES una vez, re-implementacion y APPROVE en segundo intento.
- **Escenario C**: Cierre directo canónico sin review.

Verifica alineacion canónica antes de cada lanzamiento y ausencia de residuos entre tickets.

## 8. Cierre de sesión

Antes de terminar una sesión de trabajo, ejecuta estos pasos para que el motor quede listo para la siguiente sesión o para ser usado como base en un nuevo proyecto.

```powershell
# 1. Archivar artefactos de planificación cerrados (PLAN/AUDIT de .agent/collaboration/)
python scripts/archive_collaboration_artifacts.py

# 2. Mover PLAN/AUDIT que hayan quedado en la raíz (el archivador no los recoge)
python -c "
import shutil; from pathlib import Path
archive = Path('.agent/collaboration/_archive/plan_audit')
archive.mkdir(parents=True, exist_ok=True)
moved = []
for p in list(Path('.').glob('PLAN_WP-*.md')) + list(Path('.').glob('AUDIT_WP-*.md')):
    shutil.move(str(p), archive / p.name); moved.append(p.name)
print('Moved:', moved if moved else 'nothing')
"

# 3. Validación canónica
python .agent/agent_controller.py --validate --json --force

# 4. Verificar git limpio
git status --short

# 5. Sincronizar README/CHANGELOG si el último ticket no quedó reflejado
# (ver sección 6 para comandos de calidad antes del commit)
```

**Criterio de sesión cerrada:**
- `git status` vacío
- `--validate` sin errores
- Sin `PLAN_WP-*.md` / `AUDIT_WP-*.md` en raíz
- README `Current state` y CHANGELOG reflejan el último WP cerrado
