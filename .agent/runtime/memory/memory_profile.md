# Memory Profile (L3)

Total observations: 71

High-level profile of project memory for quick context loading. This is the first memory tier loaded (before L2 rules and L1 raw observations).

## Active Domains

- architecture: 11 observations
- delivery-hygiene: 6 observations
- manager-review-rubric: 5 observations
- review-quality: 5 observations
- builder-contract: 4 observations
- testing: 3 observations
- meta: 3 observations
- supervisor-behavior: 2 observations

## Active Tickets Referenced

- WP-2026-140
- WP-2026-145
- WP-2026-175
- WT-2026-229a
- WT-2026-234a
- WT-2026-235a
- WT-2026-236a
- WT-2026-237a
- WT-2026-243a
- WT-2026-244a
- session-2026-05-25

## Recent Signals

- [state-surface-separation] Cierre canonical: STATE.md, execution_log.md and TURN.md must reflect the same closeout contract. IDLE works as a workspace sentinel with no active ti (session-2026-05-30)
- [ticket-state-enum-contract] IDLE is a workspace-level sentinel, not a validator-facing terminal state. When closing tickets, do not write IDLE into motor-facing state files; rese (session-2026-05-30)
- [review-queue-traceability] review_queue.md is a traceability surface, not a manual scratchpad. Preserve it as history for the full review cycle and let the code manage it; do no (session-2026-05-30)
- [ticket-lineage-rule] Every plan starts from a completed `...a` ticket. Tickets `...b`, `...c`, `...d` and later letters are reserved for planned splits or for fixes discov (promoted-from-repo-destino)
- [bus-recovery-rule] When a shell-launched Builder leaves the bus short of canonical termination, the durable path is root-cause analysis first, then chat closeout of the  (promoted-from-repo-destino)
- [opencode-runtime-permission-injection] In repo_motor plus repo_destino topology, the tracked .opencode/opencode.json must remain path-agnostic and portable. Workspace-specific external_dire (curated:WT-2026-244a)
- [topology-contract-stub-elevation] In repo_motor plus repo_destino topology, any fallback or stub that silently degrades behavior when motor_root is absent, such as fail-open stubs for  (curated:WT-2026-237a)
- [code-ticket-prehandoff-packaging] For code or mixed tickets in repo_motor/repo_destino topology, preflight must verify five packaging invariants before Builder launch: Files Likely Tou (curated:WT-2026-236a)
- [powershell-strictmode-dynamic-properties] Launcher PowerShell under Set-StrictMode must not access ConvertFrom-Json/PSCustomObject properties via direct dotted chains ($config.permission, $obj (curated:WT-2026-236a)
- [portable-ticket-filename-boundary] En repo_motor, un ID de ticket en el nombre de un archivo versionado es senal de historia operativa o naming legacy, pero no autoriza borrado automati (memory_upload_review)
