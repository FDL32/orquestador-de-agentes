# orquestacion_agentes

Central motor for multi-agent orchestration. Operational code lives once here; destination projects keep only their `.agent/` workspace (state, memory, events, config) and reference the motor externally.

## What this is

A **domain-agnostic central motor** that automates work by making one agent generate plans, another implement them, and a third review the result. The motor lives once in this repo; destination projects prepare a workspace (`.agent/`) and reference the motor externally. No copying of operational code.

### Three-agent loop

| Role | Responsibility | Default backend |
|---|---|---|
| **Supervisor** | Generates plans, derives tickets, coordinates the cycle | Claude Code |
| **Builder** | Implements tickets, runs gates, emits `BUILDER_EXIT` | OpenCode → Qwen 3.5 (`opencode-go/qwen3.5-plus`) |
| **Manager** | Reviews Builder output with a deliverable-type-aware rubric; emits `APPROVE` / `CHANGES` | OpenCode → OpenAI (`openai/gpt-5.4-mini`, routed natively since WP-072) |

Backends are pluggable per role in `.agent/config/agents.json` (`role_assignments` + `role_models`).

### Current reference setup

The author's working configuration on Windows:

- **Supervisor**: Claude Code (chat-driven planning + terminal control)
- **Manager**: OpenCode routed to OpenAI Codex / GPT (`openai/gpt-5.4-mini`)
- **Builder**: OpenCode routed to Qwen 3.5 Plus via the [opencode.ai/go](https://opencode.ai/go) plan
- **Approximate cost**: ~50 EUR/month (Anthropic + opencode-go bundle)

This is a **reference** setup, not a constraint. Swap any role for another backend by editing `agents.json`. The bus, state machine and review bridge are backend-agnostic.

## Current state

- **Version**: `v9.14.0`
- **Status**: Central motor release consolidated (WP-2026-113).
- **Last work**: `WP-2026-113` — Central motor release consolidation.
- **Tests**: 227 passing. Validation 0 errors. Ruff clean. pip-audit clean.

### What changed since v9.9.0

| WP | Topic |
|----|-------|
| WP-2026-086 | Regex-based redaction module (`bus/redact.py`) for secrets/PII scrubbing on the event bus |
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

## Central motor architecture (WP-2026-111)

The motor lives **once** in this repo. A destination project:

1. **Prepares a workspace**: `.agent/` with state, memory, events, config.
2. **References the motor externally**: no copying of operational code.
3. **Can override skills**: put its own skills in `<destination>/.agent/skills/`. The motor catalog acts as fallback. Host-first precedence in `scripts/discover_skills.py`.
4. **Can bootstrap itself**: drop `.agent/host-setup.{sh,ps1}` in the destination. `scripts/install_agent_system.py` detects and invokes it with interactive confirmation post-copy.
5. **Chooses deliverable type per ticket**: `deliverable_type: code | documentation | research | analysis | mixed` in `work_plan.md` switches the gate dispatch and Manager review rubric.
6. **Flips profile automatically**: `agents.json.active_profile` goes from `engine-dev` (motor repo) to `host-project` (destination) during install/sync.

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
- `skills/` — bundled default skills (catalog of 19); destination can override via `.agent/skills/`
- `scripts/` — install, upgrade, gates dispatch, skill discovery, audits, maintenance
- `MANIFEST.distribute` — frontera del motor central (codigo operativo)
- `MANIFEST.workspace` — contrato del workspace destino (estado, memoria, eventos, config)

## Typical flow — engine development

1. Edit `work_plan.md` with the next WP.
2. `python .agent/agent_controller.py --bootstrap-ticket --force` emits initial bus event.
3. Builder implements, then `python .agent/agent_controller.py --mark-ready --json --force` emits `BUILDER_EXIT` + `STATE_CHANGED → READY_FOR_REVIEW`.
4. Manager review bridge dispatches; on `DECISION: APPROVE` the canonical close cascade fires.
5. If the bridge times out / inspects: `python .agent/agent_controller.py --manager-approve --ticket WP-XXXX --force` closes manually.

## Typical flow — installing in a new project

```bash
# From destination project root:
python /path/to/orquestacion_agentes/scripts/install_agent_system.py --install
```

The installer:
1. Prepares the destination workspace (`.agent/` structure with state, memory, config).
2. Flips `active_profile` to `host-project` in `agents.json`.
3. Detects `.agent/host-setup.{sh,ps1}` if present and (with `y/N` confirmation, or `--yes` for CI) executes it.
4. Reports the source (host vs motor) of each discovered skill.
5. Does NOT copy motor code (scripts/, skills/, bus/, agent_system/, core .agent/).

## Common commands

```powershell
# Validation & gates
python .agent/agent_controller.py --validate --json --force
python scripts/run_gates_dispatch.py        # dispatches by deliverable_type
python scripts/run_pytest_safe.py
ruff check .
uv run pip-audit .

# Skill discovery
python scripts/discover_skills.py --json
python scripts/check_skill_collisions.py

# Memory & audit
python scripts/memory_consolidate.py --apply
python scripts/local_audit.py

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
