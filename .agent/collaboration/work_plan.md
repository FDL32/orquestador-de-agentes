# Plan de Trabajo: fix dry-run granularity and counter (WOT-2026-025g)

## Metadata
- **ID:** WOT-2026-025g
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-09-24
- **delivery_authority:** repo_motor
- **Prioridad:** ALTA
- **Asignado a:** Builder

## Objetivo
Corregir `copy_tree` en `scripts/install_agent_system.py` para que `--dry-run`
reporte granularidad por archivo (no por directorio) y fijar el contador del
mensaje "Sync plan" para que cuente ficheros reales en vez de entradas
top-level engañosas.

## Contexto
WOT-2026-025f expuso el flag `--shell` en `_run_entrypoint_shell`. WOT-2026-025g
corre sobre la misma superficie: `copy_tree` en `install_agent_system.py`. El
bug original: `--dry-run` devolvía `[Path('subdir')]` para un directorio
allowlisted, pero la opción (a) de la ficha original exigía devolver los
ficheros individuales dentro del directorio.

Además, el contador del mensaje `[DRY-RUN] Sync plan: {N} top-level entries`
ahora contaba ficheros individuales como si fueran entradas top-level (3
ficheros dentro de `planning/` se reportaban como "3 top-level entries" cuando
hay 1 directorio real).

## Alcance EXACTO

### MODIFICAR `scripts/install_agent_system.py`
- **D1**: `copy_tree` con `allowlist` y `dry_run=True`: cuando el item es un
  directorio allowlisted, llamar a `_copy_allowlisted_dir` que ya itera por
  ficheros y devuelve `list[Path]` con las rutas relativas de cada fichero.
  Esto cambia la granularidad de directory-level a per-file.
- **D2**: Mensaje `[DRY-RUN] Sync plan:` en `sync_agent_system`: cambiar
  `len(copied) top-level entries` por `len(copied) files` ya que `copied`
  ahora contiene ficheros individuales (no directorios).

### MODIFICAR `tests/unit/test_install_agent_system.py`
- **T1**: Actualizar `test_copy_tree_dry_run_reports_at_directory_granularity`
  para reflejar que dry-run ahora reporta per-file (no directory-level).
  El test usaba `_build_destination_with_own_cf` que tiene
  `planning/ticket_contracts.md` ya existente -> no-clobber skip -> `copied == []`.
- **T2**: El test `test_copy_tree_dry_run_reports_per_file_granularity_contract`
  (ya existente) verifica que dry-run con destino limpio devuelve los ficheros
  allowlisted y no crea archivos en disco.

## Definition of Done (DoD)
- (a) `pytest tests/unit/test_install_agent_system.py -k copy_tree_dry_run` ->
  todos los tests de `copy_tree_dry_run` pasan (2 tests focales).
- (b) mutation-verify: sin fix -> test falla; con fix -> test pasa.
- (c) `ruff check` sobre ambos ficheros -> All checks passed.
- (d) `tested_commit_sha == HEAD` tras la suite.

## MUTATIONS (cada barrera, su mutante)
1. quitar llamada a `_copy_allowlisted_dir` en dry-run -> test per-file FALLA
2. no actualizar mensaje Sync plan -> contador engañoso (3 files = "3 top-level")

## Riesgos y barreras
- No-clobber guard: `_copy_allowlisted_dir` salta ficheros destination-owned
  existentes -> `copied` puede estar vacía en tests con destino existente.
- Contador: `len(copied)` cuenta ficheros, no directorios. El mensaje cambia
  de "top-level entries" a "files" para ser preciso.