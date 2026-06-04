# orquestador_de_agentes

Central motor for multi-agent orchestration. Operational code lives once here; destination projects keep only their `.agent/` workspace (state, memory, events, config) and reference the motor externally.

## Motor vs Workspace

- This repository is the reusable motor only. It owns orchestration code, hooks, review transport, and install/sync tooling.
- It does not own active ticket state for any project.
- Active collaboration state always lives in the `.agent/` of the project being operated on.
- `orquestador_de_agentes/.agent/` is the motor development workspace when working on the motor itself.
- `z_scripts/.agent/` is the canonical workspace for the `z_scripts` project.
- Any other destination project gets its own `<project>/.agent/` with the same collaboration structure.
- Use `AGENT_PROJECT_ROOT` or the workspace `motor_destination_link.json` to select the current workspace.
- Do not mix motor-side collaboration history with project-side collaboration history.

## What this is

A **domain-agnostic central motor** that automates work by making one agent generate plans, another implement them, and a third review the result. The motor lives once in this repo; destination projects prepare a workspace (`.agent/`) and reference the motor externally. No copying of operational code.

### Engineering philosophy: CEM v0

The motor now follows **CEM: Contract, Evidence, Memory** as its lightweight engineering philosophy for agent-assisted development.

- **Contract:** decide the canonical behavior before changing code or tests.
- **Evidence:** treat agent self-reports as hypotheses; accept diffs, exit codes, tests, bus events, commits and artifacts as evidence.
- **Memory:** turn recurring lessons into guards, hooks, rules or explicit debt with an exit criterion.
- **Proportionality:** scale rigor to blast radius; documentation changes and bus/supervisor changes do not need the same ceremony.

The expanded v0 rule lives in `.agent/rules/common/sustainable_engineering.md`. `WT-2026-221a` is the first planned field test: relaunch with verified root/topology and an evidence-linked Builder handoff capsule.

### Three-agent loop

| Role | Responsibility | Default backend |
|---|---|---|
| **Supervisor** | Generates plans, derives tickets, coordinates the cycle | Claude Code |
| **Builder** | Implements tickets, runs gates, emits `BUILDER_EXIT` | OpenCode → DeepSeek V4 Flash (`opencode-go/deepseek-v4-flash`) |
| **Manager** | Reviews Builder output with a deliverable-type-aware rubric; emits `APPROVE` / `CHANGES` | OpenCode → OpenAI (`openai/gpt-5.4-mini`, routed natively since WP-072) |

Backends are pluggable per role in `.agent/config/agents.json` (`role_assignments` + `role_models`).

### Current reference setup

The author's working configuration on Windows:

- **Supervisor**: Claude Code (chat-driven planning + terminal control)
- **Manager**: OpenCode routed to OpenAI Codex / GPT (`openai/gpt-5.4-mini`)
- **Builder**: OpenCode routed to MiMo V2.5 via the [opencode.ai/go](https://opencode.ai/go) plan
- **Approximate cost**: ~50 EUR/month (Anthropic + opencode-go bundle)

This is a **reference** setup, not a constraint. Swap any role for another backend by editing `agents.json`. The bus, state machine and review bridge are backend-agnostic.

## Current state

- **Version**: `v9.14.1`
- **Status**: Stable. Session closed. Security hardening files added.
- **Last work**: Session close — CHANGELOG completeness (WP-151/152), `.claude/` security patterns, `bui-self-audit` Paso 4b, WP-2026-153 grill-with-docs skill.
- **Tests**: 255 passing. Validation 0 errors. Ruff clean. pip-audit clean.

### What changed since v9.9.0

| WP | Topic |
|----|-------|
| WP-2026-153 | Pre-plan grilling skill (`/grill-plan`, `/grill`, `grill-wp`) for resolving ambiguous terminology before work plan creation |
| WP-2026-144 | Destination prefix onboarding + timeout hotfix: `--install --prefix XXX` writes namespace; timeout no longer emits `inspect` to bus |
| WP-2026-087 | Smoke test bus agnóstico + 5-gap analysis (proved bus is domain-neutral) |
| WP-2026-088 | `deliverable_type` field in work_plan schema (V1 informational) |
| WP-2026-089 | Pluggable quality-gates dispatch by deliverable_type (`scripts/run_gates_dispatch.py`) |
| WP-2026-090 | **Host-first skill precedence + config profiles** (`active_profile: engine-dev/host-project`) |
| WP-2026-091 | Pluggable manager review rubric by deliverable_type (code / mixed / docs / research / analysis) |
| WP-2026-092 | Conditional pip-audit by dependency surface (only runs when manifest files in scope) |
| WP-2026-093 | Pre-commit ruff scope guard (Python-only enforcement) |
| WP-2026-094 | **Host setup hook** for post-install bootstrap (`.agent/host-setup.{sh,ps1}`) |
| WP-2026-095 | **Manager review V2**: single-shot prompt with budget, retry, forensic events |
| WP-2026-111 | **Central motor + destination workspace**: motor lives once, destination references externally |
| WP-2026-113 | **Central motor release consolidation**: manifiestos, documentacion e instalador alineados |
| WP-2026-123 | **Workspace minimo del destino**: enlace motor-destino con schema explicito |
| WP-2026-135 | **Pre-compact hook**: recuperacion selectiva de contexto antes de compactacion |
| WP-2026-136 | **session_close_observations `--candidates`**: canal de inyeccion semantica para el bucle de autoaprendizaje del Manager |
| WP-2026-139 | **Anti-patterns index file**: inventario canonico AP-01..AP-08 con cache y separacion indice/instrucciones |
| WP-2026-140 | **Bus import boundary firewall**: test AST+grep que protege el seam `bus/→scripts/` (`scripts.discover_skills` unica excepcion); 255 tests, ruff limpio |
| WP-2026-141 | **Review standards (eng-practices)**: criterio de aprobacion Google, convencion `Nit`, trazabilidad en AGENTS.md y CREDITS.md |
| WP-2026-142 | **Symmetric scope gate**: `--mark-ready` blocks when no whitelist file appears in diff |
| WP-2026-143 | **Idempotent `--mark-ready`**: bus-state guard prevents double review cycle emission |
| WP-2026-144 | **Destination prefix onboarding + timeout hotfix**: `--install --prefix XXX` writes namespace; timeout no longer emits `inspect` to bus |

## Central motor architecture (WP-2026-111)

The motor lives **once** in this repo. A destination project:

1. **Prepares a workspace**: `.agent/` with state, memory, events, config.
2. **References the motor externally**: no copying of operational code.
3. **Can override skills**: put its own skills in `<destination>/.agent/skills/`. The motor catalog acts as fallback. Host-first precedence in `scripts/discover_skills.py`.
4. **Can bootstrap itself**: drop `.agent/host-setup.{sh,ps1}` in the destination. `scripts/install_agent_system.py` detects and invokes it with interactive confirmation post-copy.
5. **Chooses deliverable type per ticket**: `deliverable_type: code | documentation | research | analysis | mixed` in `work_plan.md` switches the gate dispatch and Manager review rubric.
6. **Flips profile automatically**: `agents.json.active_profile` goes from `engine-dev` (motor repo) to `host-project` (destination) during install/sync.
7. **Receives motor-destination link file**: `.agent/config/motor_destination_link.json` with schema (motor_root, destination_root, motor_version, destination_id, created_at, manifest_version) for portable traceability (WP-2026-123).
8. **Uses a local ticket namespace in the destination**: the destination `PROJECT.md` declares `Ticket prefix: XXX`, and tickets in that repo use `XXX-YYYY-NNN`. The motor repo keeps `WP-YYYY-NNN`. The installer can write this prefix with `--install --prefix XXX` or `--sync --prefix XXX`.

## Version contract

- `pyproject.toml` → portable package version.
- `.agent/.version_manifest.json` → installed core/system version.
- Canonical upgrade scripts: `scripts/detect_version.py`, `scripts/upgrade.py`, `scripts/rollback.py`.

## Main layers

- `.agent/collaboration/` — canonical operational state (`TURN.md`, `STATE.md`, `work_plan.md`, `execution_log.md`)
- `.agent/runtime/events/events.jsonl` — append-only event bus (authoritative)
- `.agent/runtime/memory/` — persistent project memory (`observations.jsonl` + `MEMORY.md`)
- `.agent/runtime/audit/` — local audit snapshots
- `.agent/runtime/compare/` — repo-compare reports (gitignored)
- `.agent/config/agents.json` — backends + roles + `manager_review` tuning
- `.agent/hooks/` — safety and validation hooks
- `bus/` — event bus, supervisor, state machine, review bridge, redaction
- `skills/` — bundled default skills (catalog of 20); destination can override via `.agent/skills/`
- `scripts/` — install, upgrade, gates dispatch, skill discovery, audits, maintenance
- `MANIFEST.distribute` — frontera del motor central (codigo operativo)
- `MANIFEST.workspace` — contrato del workspace destino (estado, memoria, eventos, config)

## Typical flow — engine development

1. Edit `work_plan.md` with the next WP.
2. `python .agent/agent_controller.py --bootstrap-ticket --force` emits initial bus event.
3. Builder implements, then `python .agent/agent_controller.py --mark-ready --json --force` emits `BUILDER_EXIT` + `STATE_CHANGED → READY_FOR_REVIEW`.
4. Manager review bridge dispatches; on `DECISION: APPROVE` the canonical close cascade fires.
5. If the bridge times out / inspects: `python .agent/agent_controller.py --manager-approve --ticket WP-XXXX --force` closes manually.
6. At end of session: `python .agent/agent_controller.py --session-close --project-root .` runs the canonical session closeout pipeline (prepush check, audit, memory consolidation, archival) and syncs state for the next cycle.

## Memory bootstrap

**If memory already exists**, read in this order:

1. `.agent/runtime/memory/MEMORY.md` — short index (start here).
2. `.agent/runtime/memory/observations.jsonl` — full history for depth.
3. `.agent/runtime/memory/session_close_report.md` — last closeout summary.
4. `graphify-out/GRAPH_REPORT.md` — compact graph snapshot (optional).

**If memory is empty or missing**, seed it after the first closed cycle:

```powershell
python scripts/session_close_observations.py --ticket WP-YYYY-NNN
python scripts/memory_consolidate.py --apply --verbose
```

## Typical flow — installing in a new project

```bash
# From destination project root:
python /path/to/orquestador_de_agentes/scripts/install_agent_system.py --install
```

The installer:
1. Prepares the destination workspace (`.agent/` structure with state, memory, config).
2. Flips `active_profile` to `host-project` in `agents.json`.
3. Detects `.agent/host-setup.{sh,ps1}` if present and (with `y/N` confirmation, or `--yes` for CI) executes it.
4. Reports the source (host vs motor) of each discovered skill.
5. Does NOT copy motor code (scripts/, skills/, bus/, agent_system/, core .agent/).
6. Writes `.agent/config/motor_destination_link.json` with schema explicit for portable traceability (WP-2026-123).

Before the first ticket in the destination, set the namespace in that repo's `PROJECT.md`:

```text
Ticket prefix: XXX
```

Or let the installer write it for you:

```bash
python /path/to/orquestador_de_agentes/scripts/install_agent_system.py --install --prefix XXX
```

Use that prefix for all local ticket IDs and work-plan documents in the destination. Do not reuse the motor's `WP-YYYY-NNN` namespace there.

## Common commands

```powershell
# Validation & gates
python .agent/agent_controller.py --validate --json --force
python scripts/run_gates_dispatch.py        # dispatches by deliverable_type
python scripts/run_pytest_safe.py
ruff check .
python scripts/pip_audit_project.py

# Skill discovery
python scripts/discover_skills.py --json
python scripts/check_skill_collisions.py

# Memory & audit
python scripts/memory_consolidate.py --apply
python scripts/local_audit.py

# Session closeout (canonical entrypoint for end-of-session)
python .agent/agent_controller.py --session-close --project-root .

# Config migration (idempotent)
python .agent/agents_config.py --migrate [--dry-run]

# Compare with another GitHub repo
# via repo-compare skill (uses MCP GitHub tools)
```

## Documentation map

- `AGENTS.md` — transversal rules + dual-mode architecture notes
- `CLAUDE.md` — Claude Code entry guide
- `PROJECT.md` — current project state and contract
- `QUICKSTART.md` — minimal setup checklist and daily commands
- `INTERACTION_MODES.md` — chat-driven vs terminal-driven flow
- `REPOSITORY_STRUCTURE.md` — internal layout and public boundary
- `CHANGELOG.md` — change history (WP-by-WP)
- `CREDITS.md` — external attributions (every WP with `Origen externo` has a row)
- `prompts/session_bootstrap.md` — canonical onboarding prompt for fresh agent sessions

## License

MIT (core). See `LICENSE`.
