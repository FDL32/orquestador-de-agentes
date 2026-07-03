# Work Plan - WOT-2026-016m

## Metadata
- **ID:** WOT-2026-016m
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Gate de publicacion por fila (cross-repo): script canonico con B-TOCTOU, patron laxo, metadata y hermanos (contrato probado en la tanda backup)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Formalizar como script del motor el gate por-fila probado en la tanda backup 2026-07-03
(12 repos) y exigido por dos pasadas adversariales. Cubre el hueco original de 016m
(falso-verde de UNIDAD: motor limpio + hermano sucio publico) MAS los endurecimientos
aprendidos en vivo: B-TOCTOU, patron laxo de PII, scan de metadata git (que classify NO
cubre: solo escanea blobs, no autores/committers) y abort en carpetas "- copia".
Borrador de contrato: C:\tmp\MATRIZ_PUBLICACION_BACKUP_20260702.md.
Verificacion del objetivo: `python scripts/check_publication_gate.py --repo-root <repo>
--sibling <hermano>` devuelve exit 0 SOLO cuando repo y hermanos pasan los 6 checks;
`pytest tests/test_check_publication_gate.py` = 7 passed (incluye el caso UNIDAD).

## Decision Arquitectonica

- `scripts/check_publication_gate.py`, NUEVO, offline y deterministico (sin red: la
  verificacion private:true via API queda como CHECKLIST impresa para el humano, no como
  llamada del script). Reusa `classify_publication.build_manifest` como libreria (hereda el
  history-PII scan de 016o).
- Checks por fila (fail-closed, exit 1 al primer grupo con hallazgos):
  1. NOMBRE: la carpeta del repo matchea `* - copia*` -> ABORT (nunca origen de remoto).
  2. ARBOL: `git status --porcelain` no vacio -> BLOCKED (B-TOCTOU exige arbol limpio).
  3. CLASSIFY: build_manifest full-history; verdict != LISTO_PARA_PUBLICAR -> BLOCKED
     (con blocked_reasons volcados).
  4. PATRON LAXO: `users[^a-z0-9]{0,4}<term>` sobre `git grep` de `rev-list --all`, con
     terms parametrizables (`--pii-term`, repetible; default = nombre de usuario del HOME
     actual, derivado en runtime - NUNCA hardcodeado en el motor).
  5. METADATA: autores/committers de toda la historia que no sean noreply/*.local/allowlist
     (`--allow-email`, repetible) -> BLOCKED. Unico check que classify no puede dar.
  6. HERMANOS: `--sibling <path>` (repetible): cada hermano debe pasar 1-5 tambien
     (recursion sin hermanos anidados) -> el falso-verde de UNIDAD original.
- Salida: JSON a stdout (verdict LISTO|BLOCKED, checks con evidencia, head sha, generated_at)
  + checklist humana final (private:true via API pre/post push; "no ejecutar herramientas del
  motor entre este gate y el push" = B-TOCTOU).
- Exit: 0 solo LISTO; 1 BLOCKED; 2 error de ejecucion.

## Fases

### Fase 0 - Diagnostico (COMPLETADO en tanda + 016o)
- classify (con 016o) cubre blobs tree+history pero NO metadata git -> check 5 es valor unico.
- gitleaks queda FUERA del script (binario externo no garantizado en CI); la matriz lo mantiene
  como segunda herramienta MANUAL de la checklist.

### Fase 1 - Implementacion
- Script nuevo con funciones puras testables: `check_name`, `check_tree_clean`,
  `check_classify`, `check_loose_pattern`, `check_metadata`, `run_gate(repo, siblings, ...)`.

### Fase 2 - Tests (barrera + mutation)
- `tests/test_check_publication_gate.py` (repos git reales en tmp_path):
  - repo limpio -> exit 0 / LISTO.
  - carpeta "x - copia" -> BLOCKED name.
  - arbol sucio -> BLOCKED tree.
  - email personal en metadata (autor real) -> BLOCKED metadata; MUTATION: quitar el check
    (monkeypatch) -> pasa (demuestra que es el check unico que caza metadata).
  - PII en historia de un HERMANO -> BLOCKED sibling (el caso UNIDAD original de 016m).
  - patron laxo con term custom caza slug `Users-term` que classify no ve como ruta.

## Criterios de aceptacion

1. Los 6 checks implementados con evidencia en el JSON de salida; exit 0 solo LISTO.
2. Caso UNIDAD verificado: repo limpio + hermano con PII -> BLOCKED (test).
3. MUTATION del check de metadata verificada.
4. Sin username hardcodeado en el motor (default derivado en runtime; test lo verifica
   leyendo el fuente).
5. ruff + format + encoding verdes; suite canonica exit 0 sha==HEAD; validate 0/0.

## Files Likely Touched

### repo_motor
- `scripts/check_publication_gate.py` (nuevo)
- `tests/test_check_publication_gate.py` (nuevo)

## Non-goals
- NO llamadas de red (gh API = checklist humana impresa).
- NO integrar gitleaks en el script (segunda herramienta manual de la matriz).
- NO reescrituras de historia ni fixes automaticos (es un GATE, detecta y bloquea).
- NO tocar classify_publication (016o ya entrego su parte).
