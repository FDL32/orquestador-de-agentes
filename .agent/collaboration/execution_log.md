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

**Estado:** EN_CURSO (suite canonica pendiente por ENTORNO_DEGRADADO)

### Ronda 1 (2026-09-16)
- Commits: e3950fa (commits_searched_in en record dict + n/a branch), 831e30f (test commits_searched_in present)
- Docstring del modulo de tests actualizado (B2 cumplido)
- 37 tests focales pasaron, ruff limpio, validate 0/0
- Suite canonica BLOQUEADA por RAM 3.97 GB < 6 GB

### Ronda 2 - Manager CHANGES (2026-09-16)

**Blocker 1: rama n/a busca en AMBOS repos (DoD-4.bis)**
- Codigo: la rama `repo is None` ahora itera sobre `("motor", motor_root), ("destino", dest_root)`
  y llama `_signal_commits(ticket_id, root)` para cada repo no-None.
- `grep_commits` sigue vacio en n/a (no se toco - Forbidden Surface).
- `commits_searched_in` ahora contiene ["motor", "destino"] para n/a scope.
- Commit: 4aa1a7a

**Blocker 2: clase de falso negativo vacia (verificado en PRODUCCION)**
- Verificacion en 7 filas n/a de produccion:
  - WOT-2026-002c: motor=1 destino=11 total=12 (antes 0 -> FALSE NEGATIVO corregido)
  - WOT-2026-016v: motor=0 destino=1 total=1 (antes 0 -> FALSE NEGATIVO corregido)
  - WOT-2026-025x: motor=1 destino=1 total=2 (antes 0 -> FALSE NEGATIVO corregido)
  - WOT-2026-044c: motor=0 destino=2 total=2 (antes 0 -> FALSE NEGATIVO corregido)
  - WOT-2026-069h: motor=1 destino=1 total=2 (antes 0 -> FALSE NEGATIVO corregido)
  - WOT-2026-069i: motor=0 destino=0 total=0 (vacío legítimo)
  - WOT-2026-069j: motor=0 destino=0 total=0 (vacío legítimo)
- Clase de falso negativo: VACIA. Blocker 2 CERRADO.

**Blocker 3: test reescrito + test nuevo del invariante**
- `test_067w_na_scope_no_dual_scan`: docstring actualizado (ya no dice "no dual-scan")
- `test_067w_commits_searched_in_present_in_all_entries`: assert de n/a scope cambia
  de `commits_searched_in == []` a `commits_searched_in == ["motor", "destino"]`
- `test_067w_na_scope_with_commits_in_alternate_repo`: TEST NUEVO que pinea el invariante:
  un ticket n/a con commits en motor sale con `commits_found >= 1`.
- `test_routing_infra_ticket_is_na_with_warning`: sigue VERDE (grep_commits == [] intacto)
- 38 tests focales pasaron (37 anteriores + 1 nuevo)

**Blocker 4: claim falso retirado**
- Runtime SI estaba bootstrappeado para 067w (STATE.md: ACTIVE_TICKET: WOT-2026-067w,
  TURN.md: ROL: BUILDER, work_plan.md: ID: WOT-2026-067w).
- La desviacion "runtime no bootstrap" se retira del informe.

**Blocker 5: criterio 4.bis marcado correctamente**
- En ronda 1: `commits_searched_in=[]` en n/a NO era "poblar" segun DoD.
- En ronda 2: n/a scope puebla `commits_searched_in=["motor", "destino"]` -> SÍ cumple.

**Blocker 6: encoding guard ejecutado literalmente**
- `python scripts/check_encoding_guard.py scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py`
- Resultado: `denominador=2 inspeccionados=2 hits=0 saltados=0 (universo: argumentos explicitos), rc=0`

**Blocker 7: suite canonica pendiente**
- RAM actual: 4.25 GB (< 6 GB threshold)
- Suite canonica NO puede lanzarse. Se requiere esperar a que RAM suba.

### Gates focales ronda 2

| Comando | Resultado |
|---------|-----------|
| `pytest-safe --level unit test_backlog_reconcile.py` | 38 passed in 4.40s |
| `uv run ruff check scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py` | All checks passed |
| `uv run ruff format --check scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py` | 2 files already formatted |
| `python scripts/check_encoding_guard.py scripts/backlog_reconcile.py tests/unit/test_backlog_reconcile.py` | denominador=2 inspeccionados=2 hits=0 saltados=0, rc=0 |
| `--validate --json` | 0 errors, 0 warnings |
| `grep "This script NEVER classifies"` | 2 matches (>= 1) |

### Commits ronda 2

| SHA | Mensaje |
|-----|---------|
| 4aa1a7a | WOT-2026-067w: search BOTH repos in n/a branch (DoD-4.bis) |

### Suite canonica (BLOQUEADA)

| Criterio | Valor |
|----------|-------|
| RAM libre | 4.25 GB (< 6 GB threshold) |
| Procesos | 417 |
| Accion | ENTORNO_DEGRADADO - NO lanzar --level all |

La suite canonica `--level all` NO puede ejecutarse por ambiente degradado.
Se requiere esperar a que RAM suba a >= 6 GB antes de lanzar.
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
