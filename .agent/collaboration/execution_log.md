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

## Execution Log: WOT-2026-067w (ciclo CHANGES)

**Estado:** EN_CURSO (bloqueado por ENTORNO_DEGRADADO)

### Fase 0: diagnostico (2026-09-16)
- work_plan.md: WOT-2026-022c (STALE - no es de este ticket, el runtime no fue bootstrap para 067w)
- STATE.md: ACTIVE_TICKET: WOT-2026-022c, STATUS: COMPLETED (STALE)
- TURN.md: ROL: BUILDER, Plan ID: WOT-2026-021h (STALE)
- Topologia: OK (check_worktree_topology rc=0)
- Validate: 0 errors, 0 warnings (clean)
- Commit previo 4212082: dual-repo scanning implementado CORRECTO
- _collect_all verificado: rama `if repo is None:` NO puebla `commits_found` (BUG)
- _collect_all verificado: NO puebla `commits_searched_in` en ningun rama (BUG)
- test_backlog_reconcile.py:8-9 docstring dice "NO real git" pero tests nuevos usan git real (BUG)
- Canal `automatic_warnings`: existente, no se crea nuevo

### Fase 1: correcciones (2026-09-16)

**B1 -- `commits_searched_in` (DoD-1 + DoD-4.bis):**
- Record dict (l.538+): anadido `"commits_searched_in": []`
- Rama n/a (l.566+): anadido `record["commits_found"] = 0` y `record["commits_searched_in"] = []`
- Rama else (l.589+): anadido `searched = [repo_label]` + alternate si aplica, `record["commits_searched_in"] = searched`
- `grep_commits` NO modificado en rama n/a (se mantiene `[]` como antes)

**B2 -- docstring modulo de tests:**
- Lineas 1-9: actualizado para declarar DOS convenciones (synthetic + real-git)
- Viejo: "Mirrors test_collect_system_health.py conventions... NO real git"
- Nuevo: "Two conventions coexist... Legacy synthetic + Real-git tests"

### Fase 2: tests (2026-09-16)

**Nuevo test: `test_067w_commits_searched_in_present_in_all_entries`**
- Verifica `commits_searched_in` presente en TODAS las entradas (N tickets, N con campo)
- Verifica n/a scope: `commits_searched_in == []`
- Verifica motor scope: `"motor" in commits_searched_in`
- Verifica destino scope con alternate: `"destino" in` y `"motor" in commits_searched_in`

### Gates focales (2026-09-16)

| Comando | Resultado |
|---------|-----------|
| `pytest-safe --level unit test_backlog_reconcile.py` | 37 passed in 1.33s |
| `uv run ruff check scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py` | All checks passed |
| `uv run ruff format --check scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py` | 2 files already formatted |
| `--validate --json` | 0 errors, 0 warnings |
| `grep "This script NEVER classifies"` | 2 matches (>= 1) |

### Suite canonica (BLOQUEADA)

| Criterio | Valor |
|----------|-------|
| RAM libre | 3.97 GB (< 6 GB threshold) |
| Procesos | 416 |
| Accion | ENTORNO_DEGRADADO - NO lanzar --level all |

La suite canonica `--level all` NO puede ejecutarse por ambiente degradado.
Se requiere esperar a que RAM suba a >= 6 GB antes de lanzar.

### Commits realizados

| SHA | Mensaje |
|-----|---------|
| e3950fa | WOT-2026-067w: add commits_searched_in to all entries + update test docstring |
| 831e30f | WOT-2026-067w: test commits_searched_in present in all entries |

### Desviaciones de scope
- Ninguna. Solo se tocaron los 2 archivos del FLT.
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
