# Execution Log: WOT-2026-022c

**Estado:** COMPLETED

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
- Creado `scripts/init_session_scratch.py` (~1140 lineas): 6 subcomandos (init, add,
  list, audit, archive, gc), writer con lock del SO (msvcrt/fcntl), lock TTL puro,
  takeover atomico + marker TTL, required condicional por event, exit codes hibrido.
- Creado `tests/test_init_session_scratch.py` (~1070 lineas, 51 tests): M1 agnosticismo
  (3 ejes disjuntos), T-LEDGER-CONC (4x25=100 concurrentes, 0 CRLF), T-TAKEOVER-FOSIL,
  T-ARCHIVE-DEST-EXISTE, fail-open/exit2, lock_reclaimed anti-fosilizacion, CRLF/LF hash,
  list/gc ignoran _archive, gc keep-K, audit modes, lock management, init idempotency,
  validation, archive flow, maiden voyage (2 sesiones + takeover competition).
- .gitignore en motor Y workspace: `.agent/runtime/session/` (verificado git check-ignore).
- Gates: py_compile + ruff + ASCII limpios. 51 targeted tests passed.

### 2026-07-11 - Suite completa
- `run_pytest_safe.py --level all`: **3825 passed, 47 skipped, 0 failed** (276s).
- Warning STATE LEAK sobre `*_WOT-*.md` (021i, gitignored) = falso-positivo (tree limpio).

### 2026-07-11 - Review 2 fresh-context (mutation-to-prove) - 12 mutations
- 10/12 barreras con dientes (mutation rompe el test). 2 cosméticas detectadas:
  - Mutation 6 (archive dest-exists): test pasaba por PermissionError downstream.
    FIX: assert `"already exists" in reason` -> ahora discrimina. Verificado: test
    FALLA sin el check (reason = "os.replace failed" != "already exists").
  - Mutation 9 (enum regex filter): test pasaba por check `== ARCHIVE_DIRNAME`.
    FIX: anadir `garbage_dir` (no matchea regex) -> ahora discrimina. Verificado: test
    FALLA sin el filtro (garbage_dir listado).
- Static checks: resolve_project_root NO llamada, O_BINARY presente, msvcrt+fcntl
  presentes, TAKEOVER_TTL presente, git check-ignore OK.
- Restauracion verificada: git diff clean. 51 tests re-verificados tras fixes.

### 2026-07-11 - Cierre commit-directo
- Commit 2e9880c: `feat(session): WOT-2026-022c init_session_scratch.py`.
- Estado COMPLETED. Commit fixes del Review 2.
