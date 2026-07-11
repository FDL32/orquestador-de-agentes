# Execution Log: WOT-2026-022c

**Estado:** IN_PROGRESS

## Bitacora

### 2026-07-11 - Orquestador - Preflight + premisa en vivo
- Preflight clean: motor b4cd641, workspace c17b098, validate errors=0, topology ok.
- Premisa CONFIRMADA in-vivo: `scripts/init_session_scratch.py` NO existe (Test-Path
  False, glob vacio, `git log --grep` vacio). 4 superficies downstream INTACTAS
  (`git grep init_session_scratch` en prompts/ + preflight = 0 matches). 022c NO las toca.
- Canones verificados en codigo vivo:
  - `runtime/project_root.py:82` `@lru_cache(maxsize=1)` SIN args -> trampa confirmada.
  - `bus/builder_locks.py:104-132` `builder_alive` TTL puro (age<900, sin mirar pid).
  - `bus/builder_locks.py:246-289` `_claim_requeue` takeover atomico O_CREAT|O_EXCL.
  - `tests/conftest.py:114` `_pid_is_alive` fail-safe-a-VIVO (canon correcto para pid).
  - `bus/redact.py:50` `redact_payload` red recursiva.
  - `scripts/validate_observations.py:414` `--dry-run` exit 0 siempre (canon audit).
  - `scripts/archive_event_bus.py` shape: --dry-run, JSON stdout, resolve_project_root
    (patron a NO seguir -- usa la trampa lru_cache).

### 2026-07-11 - Plan v2 (plan-audit adversarial con PROBES EJECUTADOS)
- 5 BLOCKER cazados por probes reales (B1-B5) + B6 (lectura de codigo).
- Decisiones W1 (writer con lock del SO), E1 (exit codes hibrido), D4' (regex ampliado),
  D10' (lock TTL + marker TTL), D12' (archive fail-closed).
- Plan v2 incluido en el prompt de arranque; work_plan.md creado desde el v2.

### 2026-07-11 - Implementacion (orquestador directo, persistiendo a disco)
- [EN CURSO]
