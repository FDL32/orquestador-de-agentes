# Memory Profile (L3)

Total observations: 90

High-level profile of project memory for quick context loading. This is the first memory tier loaded (before L2 rules and L1 raw observations).

## Active Domains

- architecture: 12 observations
- delivery-hygiene: 7 observations
- builder-contract: 7 observations
- review-quality: 6 observations
- manager-review-rubric: 5 observations
- testing: 5 observations
- bus-architecture: 4 observations
- meta: 3 observations

## Active Tickets Referenced

- WOT-2026-003a
- WOT-2026-003c
- WOT-2026-003d
- WOT-2026-003f
- WOT-2026-005b
- WOT-2026-006a
- WOT-AUDIT
- WOT-AUDIT-C1
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
- WT-2026-248a
- WT-2026-248b
- WT-2026-249b
- WT-2026-249c
- session-2026-05-25

## Recent Signals

- [premise-verification-before-implementation] Before implementing a ticket that describes a past system state, reproduce its premise read-only first and re-scope if the premise is false. In WOT-20 (session-close)
- [host-extends-resolver-audit-first] In host-extends topology, removing motor-provides copies is not safe until the destination is audited for live resolvers, hooks, CI references, and la (session-close)
- [delivery-authority-drives-closure] Closure gates and scope gates in a multi-repo system must respect delivery_authority. A code or mixed ticket owned by repo_destino cannot require prod (session-close)
- [security-hook-fail-closed] A security hook that cannot resolve its guard must fail closed. Returning exit 0 because the guard dependency is missing is a false barrier and leaves (session-close)
- [false-green-is-not-evidence] A green test or gate with no real assert path or with broken explicit-input parsing is not evidence. False-greens must be treated as critical debt and (session-close)
- [bus-absent-is-unverifiable] In CI or a fresh clone, an absent runtime bus means closure invariants are unverifiable, not violated. Raise an error only when the bus for the ticket (session-close)
- [ci-vs-prepush-coverage] Pre-push local puede quedar verde aunque la suite completa de CI falle; los guards que solo corren en CI deben tener verificacion local focalizada cua (session-close)
- [verified-barrier] Un guard nuevo no cuenta como barrera verificada hasta que exista un test o fixture que demuestre que bloquea el fallo prometido. (session-close)
- [git-history-scan-dedup] Los escaneos de historia Git deben deduplicar por blob SHA o contenido equivalente; deduplicar por par commit-path no reduce trabajo y escala mal. (session-close)
- [subprocess-json-stdout-noise] Los tests de integracion que ejecutan agent_controller.py como subproceso en Windows pueden fallar si stdout mezcla banners humanos con JSON; el contr (session-close)
