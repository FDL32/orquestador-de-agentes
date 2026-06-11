# Project: orquestador_de_agentes
**Version:** v9.15.0
**State:** READY (2026-06-11) - review packet hardening for WT-2026-249 and Git EOL hygiene for WT-2026-248b published locally

## Current Cycle

- Last ticket: WT-2026-248b IMPLEMENTED (2026-06-11). `.gitattributes` now normalizes LF for portable docs/config/memory surfaces, with regression coverage to prevent recurring CRLF noise in local updates.
- Last ticket: WT-2026-249c IMPLEMENTED (2026-06-11). `review_bridge.py` now honors nested OpenCode phase metadata and uses the last matching NDJSON decision when `final_answer` is absent.
- Last ticket: WT-2026-249b IMPLEMENTED (2026-06-11). `BUILDER_BRIEF_WT-*` / `BUILDER_BRIEF_WP-*` are treated as live handoff surfaces, not workspace residue, in pre-handoff packaging.
- Last ticket: WT-2026-249a IMPLEMENTED (2026-06-11). CLI contract around `--pre-handoff` / session-close warnings stays exit-0 clean on non-fatal orphan flows.
- Last ticket: WT-2026-216 COMPLETED (2026-06-02). Launcher reads bus instead of TURN.md for agent decision (`get_launcher_state.py`).
- Last ticket: WT-2026-212 COMPLETED (2026-06-02). Guarantee durable CHANGES consumer (`_ensure_durable_changes_consumer` in review_bridge.py).
- Last ticket: WT-2026-211 COMPLETED (2026-06-02). Centralize transition projection writes — controller emits events, supervisor materializes projections.
- Last ticket: WT-2026-210 COMPLETED (2026-06-02). Bus architecture audit + reconcile_ticket.py for orphaned runtime.
- Last session closed: WP-2026-175 COMPLETED (2026-05-29). Canonical session closeout and cycle rollover.
- Open deuda priorizada: follow-up estructural post-248a/249 (alineacion prompt/skill y separacion mas clara del runtime state temporal frente a config versionada).
- `validate_ticket_prose.py` TP-06 / TP-07 detection remains active; the canonical TP Check format is still enforced.

## Current readiness

- Canonical close complete: bus reconstruction, suite stabilization, encoding guard hardening and CEM v0 are published.
- Review packet hardening published locally for `WT-2026-249a/249b/249c`: stale-orphan CLI contract aligned, `BUILDER_BRIEF_*` excluded from workspace residue guards, and NDJSON decision parsing hardened for OpenCode review flows.
- Git hygiene hardening published locally for `WT-2026-248b`: portable text surfaces now normalize to LF through `.gitattributes`, reducing false diffs in docs/config/memory updates on Windows.
- Motor suite verified green: 2071 passed, 22 skipped, 0 failed.
- Next strategic front: follow-up estructural post-248a/249 (prompt-skill alignment y aislamiento mas limpio del runtime temporal de OpenCode).

## Repomix Context Integration (WT-2026-182)

The system integrates `repomix` as a compressed context layer for agent bootstrapping:

- **Bootstrapping:** On session start, `launch_agent_terminals.ps1` runs `npx repomix --compress`
  to generate `.agent/context/repomix.xml`, which is injected as an explicit context file for
  the Builder agent (via `-f` flag). Gives agents instant "X-ray vision" of the workspace.
- **Config:** A `repomix.config.json` template is provisioned to the workspace root by
  `install_agent_system.py` (from `agent_system/templates/repomix.config.json`).
- **Repo-Compare:** The `skills/repo-compare/` skill uses repomix locally (`.session/repomix_local.xml`)
  and optionally for remote repos (`.session/repomix_remote.xml`) to accelerate comparisons.
- **Failure tolerance:** If `npx repomix` fails or times out (>15s), the session continues
  without the compressed context — no blocking.

## Source of truth

> See `[AGENTS.md](AGENTS.md)` for the canonical runtime paths and operational contract.

- Destination projects declare `Ticket prefix: XXX` in their local `PROJECT.md` (or via `--install --prefix XXX`) and use `XXX-YYYY-NNN`; this motor keeps `WP-YYYY-NNN`.

## Ticket System Contract

- Every new plan starts from a base ticket ending in `a`.
- There is no canonical plan without an `...a` ticket; that ticket defines the
  first complete deliverable and the base closeout of the cycle.
- Tickets `...b`, `...c`, `...d` and later letters are reserved for:
  - splitting long plans into smaller deliverables;
  - formalizing fixes discovered after the `...a` closeout;
  - absorbing follow-up hardening without polluting the original base ticket.

## Bus Recovery Rule

- When a shell-launched Builder does not carry the bus to canonical
  termination, the priority is root-cause analysis, not forcing a superficial
  close.
- The durable workflow is:
  1. diagnose why the bus did not reach terminal state;
  2. close the corresponding `...a` ticket through chat to keep commits clean;
  3. open derived tickets `...b`, `...c`, `...d` for the concrete fixes;
  4. implement those fixes through chat rather than trying to repair the bus
     through the same broken live bus path.
- Operational rule: avoid fixing the bus "through the bus" unless the ticket is
  explicitly about recovery semantics and the evidence justifies that path.

## OpenCode Permission Preflight

- If a Builder ticket needs to touch files outside `.agent/collaboration/` or
  `scripts/`, the plan or launcher bootstrap must verify before launch that
  those paths are permitted in `.opencode/opencode.json`.
- If the required paths are not permitted, startup must fail fast with a clear
  diagnostic instead of letting the Builder run blind and discover the gap only
  after partial execution.
- The work plan can correctly declare the intended surfaces and still be
  insufficient on its own: what failed in practice was not the plan, but the
  missing alignment between that plan and the backend permission layer.
- For OpenCode specifically, the effective allowlist may need the destination
  root wildcard itself (for example `repo_destino\*`), not only individual
  files, because the backend can resolve reads as an `external_directory`
  request over the enclosing tree.
- For documentation tickets in `repo_destino`, declaring `Files Likely Touched`
  is not enough. The backend must also have real access to those declared
  surfaces, or the Builder cannot execute the contract it was given.
- The tracked `.opencode/opencode.json` in `repo_motor` must stay path-agnostic
  and portable. Workspace-specific `external_directory` permissions belong to
  runtime injection by the launcher and must be restored after the Builder run,
  not committed as absolute paths to one local `repo_destino`.
