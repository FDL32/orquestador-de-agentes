# Memory Profile (L3)

Total observations: 65

High-level profile of project memory for quick context loading. This is the first memory tier loaded (before L2 rules and L1 raw observations).

## Active Domains

- architecture: 9 observations
- manager-review-rubric: 5 observations
- review-quality: 5 observations
- delivery-hygiene: 5 observations
- builder-contract: 4 observations
- testing: 3 observations
- supervisor-behavior: 2 observations
- meta: 2 observations

## Active Tickets Referenced

- WP-2026-140
- WP-2026-145
- WP-2026-175
- WT-2026-229a
- WT-2026-234a
- WT-2026-235a
- session-2026-05-25

## Recent Signals

- [state-surface-separation] Cierre canonical: STATE.md, execution_log.md and TURN.md must reflect the same closeout contract. IDLE works as a workspace sentinel with no active ti (session-2026-05-30)
- [ticket-state-enum-contract] IDLE is a workspace-level sentinel, not a validator-facing terminal state. When closing tickets, do not write IDLE into motor-facing state files; rese (session-2026-05-30)
- [review-queue-traceability] review_queue.md is a traceability surface, not a manual scratchpad. Preserve it as history for the full review cycle and let the code manage it; do no (session-2026-05-30)
- [portable-ticket-filename-boundary] En repo_motor, un ID de ticket en el nombre de un archivo versionado es senal de historia operativa o naming legacy, pero no autoriza borrado automati (memory_upload_review)
- [review-decision-provenance-contract] Solo json_final_answer es fuente autoritativa para APPROVE o CHANGES en review_bridge. json_last_text, json_no_decision y text_regex son diagnosticos: (review-bridge-provenance-audit)
- [validator-enforce-not-observe] Un validador que solo registra errores sin cambiar el resultado del flujo es fail-open. Patron observado en _validate_changes_structure(): el validato (review-bridge-provenance-audit)
- [repo-motor-portable-root] La raiz del repo_motor debe contener solo producto portable y reusable: codigo, prompts, tests, scripts, docs de producto y configuracion del motor. E (session-2026-06-05-WT-2026-229a)
- [cem-auto-report-is-hypothesis] In agent-assisted development, an agent self-report is a hypothesis, not evidence. Accept only verifiable artifacts such as diffs, exit codes, test ou (session-2026-06-04-cem-v0)
- [cem-false-green] A false green is critical debt: guards, hooks and tests must be validated by injecting the failure they claim to block, especially when they protect h (session-2026-06-04-cem-v0)
- [cem-contract-before-fix] When tests and production disagree, classify before changing: compare the test, committed production behavior and canonical contract. Sometimes the ri (session-2026-06-04-cem-v0)
