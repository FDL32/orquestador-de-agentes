# Memory Profile (L3)

Total observations: 82

High-level profile of project memory for quick context loading. This is the first memory tier loaded (before L2 rules and L1 raw observations).

## Active Domains

- architecture: 11 observations
- delivery-hygiene: 7 observations
- review-quality: 6 observations
- builder-contract: 6 observations
- manager-review-rubric: 5 observations
- testing: 4 observations
- bus-architecture: 3 observations
- meta: 3 observations

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
- WT-2026-248a
- WT-2026-248b
- WT-2026-249b
- WT-2026-249c
- session-2026-05-25

## Recent Signals

- [ci-vs-prepush-coverage] Pre-push local puede quedar verde aunque la suite completa de CI falle; los guards que solo corren en CI deben tener verificacion local focalizada cua (session-close)
- [verified-barrier] Un guard nuevo no cuenta como barrera verificada hasta que exista un test o fixture que demuestre que bloquea el fallo prometido. (session-close)
- [git-history-scan-dedup] Los escaneos de historia Git deben deduplicar por blob SHA o contenido equivalente; deduplicar por par commit-path no reduce trabajo y escala mal. (session-close)
- [subprocess-json-stdout-noise] Los tests de integracion que ejecutan agent_controller.py como subproceso en Windows pueden fallar si stdout mezcla banners humanos con JSON; el contr (session-close)
- [opencode-phase-field-location] In OpenCode --format json NDJSON output, the phase field may be nested at part.metadata.openai.phase instead of the event top level. A parser that onl (curated:WT-2026-249c)
- [ndjson-last-decision-wins] Inside the NDJSON extraction layer, when no canonical final_answer event is available, the parser must keep the LAST matching decision found in text e (curated:WT-2026-249c)
- [builder-brief-live-surface-contract] BUILDER_BRIEF_WT-* and BUILDER_BRIEF_WP-* files are operational handoff artifacts for the active ticket, not workspace residue. They must be listed in (curated:WT-2026-249b)
- [ticket-id-parser] Toda logica que parsea ticket IDs debe usar extract_all_ticket_ids() de bus/ticket_id.py; los regex inline truncan sufijos alfanumericos y degradan ru (session-close)
- [powershell-bom-encoding] En PowerShell 5.1, Set-Content y Out-File con -Encoding UTF8 anaden BOM a archivos trackeados sin BOM; la restauracion byte-exacta debe hacerse con IO (session-close)
- [ticket-closeout-debt] Un ticket puede cerrarse funcionalmente y aun dejar deuda residual de infraestructura o arquitectura; separar fix funcional de follow-up estructural e (session-close)
