# execution_log_WOT-2026-042r

## Fase 0: Paso 0 — Mediciones de baseline rojo

### 0.1: Rojo del eje (i) — `test_step_observations_skip_when_nothing_written`

- **Node-id:** `test_step_observations_skip_when_nothing_written`
- **Archivo:** `tests/unit/test_closeout_steps_observations.py:52-68`
- **rc rojo previo (HEAD 13a5538 / bui-042r):**
  - El test EXISTS en 13a5538 y PASSe con el fake de una sola linea
  - Pero el mecanismo real NO funciona: el productor imprime SIEMPRE 2 lineas
    (`[DRY-RUN] Report written to ...` + `OBSERVATIONS appended=...`)
  - Probe de ruta productiva (rev042r_prodpath.py, ver REVISION_WOT-2026-042r_r1.md):
    - stdout real del productor (rc=0): 2 lineas
    - Paso con ese stdout → `WARN "No protocol line"` (rc=0)
    - Control (misma linea como PRIMERA): `SKIP` → el parseo funciona, falla el ancla
    - Line-by-line scan → HIT vs whole-string `match` → False
  - **Comando re-ejecutado:**
    `python -m pytest tests/unit/test_closeout_steps_observations.py::test_step_observations_skip_when_nothing_written -v` → 1 passed (fake de 1 linea)
  - **Comando prod (probe propio, ver r1 review):** WARN (rc=0, 2-line stdout)

### 0.2: Rojo del eje (ii) — `test_process_candidates_dedupes_intra_run`

- **Node-id:** `test_process_candidates_dedupes_intra_run`
- **Archivo:** `tests/unit/test_session_close_observations.py:678-699`
- **rc rojo previo (HEAD 13a5538 / bui-042r):**
  - El test EXISTS en 13a5538 y PASSe (dedup intra-corrida implementado)
  - Mutacion propia (M2, ver r1 review): `if key in seen:` → `if False:` → 1 failed (rc=1)
  - Restaurado: `porcelain=''`, HEAD 13a5538
  - **Comando re-ejecutado:**
    `python -m pytest tests/unit/test_session_close_observations.py::test_process_candidates_dedupes_intra_run -v` → 1 passed

### 0.3: Rojo del eje (iii) — `test_archive_surface_excused_from_dirty_tree`

- **Node-id:** `test_archive_surface_excused_from_dirty_tree`
- **Archivo:** `tests/test_pre_handoff_guard.py`
- **rc rojo previo (HEAD 13a5538 / bui-042r):**
  - El test EXISTS en 13a5538 y PASSe (archive excused en LIVE_SURFACES_REL)
  - Mutacion propia (M3, ver r1 review): `.agent/runtime/memory/archive/` → `…/archiveMUT/` → 1 failed (rc=1)
  - Restaurado: `porcelain=''`, HEAD 13a5538
  - **Comando re-ejecutado:**
    `python -m pytest tests/test_pre_handoff_guard.py::test_archive_surface_excused_from_dirty_tree -v` → 1 passed

## Gates r2 (post-fix)

- **Commit r2:** 4e51fb4
- **archivos tocados:**
  - `scripts/closeout_steps/observations.py` (parseo linea-a-linea)
  - `scripts/session_close_observations.py` (NIT dedup reason)
  - `tests/unit/test_closeout_steps_observations.py` (test contrato productor→consumidor)
- **Tests focal scope:** 5 passed (test_closeout_steps_observations) + 44 passed (test_session_close_observations) + 3 archive tests (test_pre_handoff_guard)
- **ruff check:** 0 issues
- **ruff format:** 3 files checked, 0 reformatted
- **Arbol:** limpio (HEAD 4e51fb4, porcelain vacio)

## Historial de revisiones

- **REV-042r-r1:** DECISION: CHANGES (2 bloqueantes: mecanismo D1 broken on real stdout, receipt ausente)
- **REV-042r-r2:** PENDIENTE (orquestador despacha)