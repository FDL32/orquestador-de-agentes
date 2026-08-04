# Artifact ownership matrix (cid-artifact-ownership-v0)

> Fuente unica de verdad sobre quien escribe cada artefacto de cierre/evidencia, cuando, que gate lo consume y
> su valor probatorio. Adoptada en WOT-2026-014r (meta-auditoria de proceso 2026-06-27, hallazgo X-09 / P3).
> Regla de gobierno asociada: ver AGENTS.md, "skill apunta, prompt gobierna" + R2.

| Artefacto | Owner (lo escribe) | Momento | Gate que lo consume | Valor probatorio |
|---|---|---|---|---|
| session_close_report.md | scripts/session_closeout.py (REPORT_REL real / DRY_RUN preview) | fin de --session-close | delivery_hygiene allowlist | RELATO; no hecho |
| pipeline_closeout_*.md | orchestrator_pipeline paso 10 -- SOLO pipeline-driven | fin del pipeline | audit_pipeline Fase 0 | RELATO; ausente en cierre manual (X-03) |
| closeout_<ticket>.md | orchestrator_pipeline paso 8 -- SOLO pipeline-driven | cierre de cada ticket | audit_pipeline Fase 1 | RELATO por-ticket; ausente en cierre manual |
| execution_log.md | Builder + cierre (archivado) | durante el ticket | scope gate, validate, audit_pipeline | bitacora; re-derivar de git |
| backlog.md (cola viva) | humano/Manager (NUNCA el closeout) | fuera del cierre | check_backlog_contract | estado de cola, no evidencia de cierre |
| _archive/backlog_done.md (historico terminal) | humano/Manager, al cerrar el ticket | paso 8.ter del cierre, o fuera de el | check_backlog_contract (`validate_archive_states`) | cerrar es un TRASPASO entre estas DOS superficies, no un cambio de etiqueta: un estado terminal NO vive en la cola viva, y una fila archivada con estado VIVO es trabajo pendiente guardado como historia -- invisible en ambas (WOT-2026-026t: 18 filas medidas 2026-08-04) |
| events.jsonl (bus) | runtime/supervisor | continuo | closure_invariants, validate | EVIDENCIA canonica |
| last-run.json | run_pytest_safe.py | tras suite | canonical-suite gate | EVIDENCIA (tested_commit_sha+exit) |

Precedencia probatoria (menor->mayor): closeout/report (RELATO) < execution_log (bitacora) <
git/bus/last-run (EVIDENCIA inmutable). Un gate nunca acepta RELATO donde existe EVIDENCIA.
