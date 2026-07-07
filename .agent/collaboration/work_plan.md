# Work Plan

## Metadata
- **ID:** WOT-2026-019l
- **Estado:** COMPLETED
- **deliverable_type:** code
- **delivery_authority:** repo_motor

## Objetivo

Los parsers de seccion del scope gate detectan el heading por SUBSTRING, no por heading exacto. Una mencion en prosa del literal `## Files Likely Touched` (o `## Builder`) ANTES de la seccion real hace que el parser abra la seccion en la prosa y lea tokens basura. Fix: exigir que el heading sea la LINEA COMPLETA (stripped == f"## {heading}"), no un substring.

## Root cause

5 parsers usan substring match:
- `scope_gate.py:125` - `_section_path_tokens`: `if f"## {heading}" in line:`
- `scope_gate.py:162` - `_extract_section_paths`: `if f"## {heading}" in line:`
- `scope_gate.py:230` - `_parse_flt_section`: `if "## Files Likely Touched" in stripped and stripped.startswith("## ")`
- `scope_gate.py:188` - `_parse_builder_fallback_entries`: `if "## Builder" in stripped and stripped.startswith("## ")`
- `pre_handoff_guard.py` - `_parse_raw_flt_paths`: `if "## Files Likely Touched" in line_s:`

## Files Likely Touched

- `.agent/scope_gate.py`
- `scripts/pre_handoff_guard.py`
- `tests/unit/test_scope_gate.py`

## Read/inspect only

- `tests/test_agent_controller.py` (tests de integracion que usan FLT)
- `scripts/check_deliverables_exist.py` (usa `startswith("## Files Likely Touched")` - ya correcto)

## Manager-only

- `prompts/orchestrator_pipeline.md` (referencia de flujo)

## Criterios binarios de aceptacion

- [ ] Un work_plan con el literal `## Files Likely Touched` en prosa ANTES de la seccion real resuelve el FLT de la seccion REAL (no la prosa)
- [ ] mutation: revertir el fix -> vuelve a leer la prosa (FLT resuelto = tokens basura)
- [ ] Todos los tests de scope_gate existentes siguen verdes (no romper deteccion de secciones reales)
- [ ] `validate --json` da 0 errors / 0 warnings
- [ ] `ruff check` pasa sobre archivos Python tocados
- [ ] Suite canonica: `run_pytest_safe.py --level all` exit 0, tested_commit_sha == HEAD

## Non-goals

- No cambiar la semantica de las secciones reales existentes
- No anadir nuevos headings o secciones
- No tocar el guard `_check_implementation_evidence` (l.1774 de agent_controller.py)
- No tocar `check_deliverables_exist.py` (ya usa `startswith` correcto)

## Decision Arquitectonica

Se elige `==` (linea completa exacta) sobre `startswith("## {heading}")` porque el
parser ya hacia `startswith("## ")` como pre-filtro en 2 de los 5 parsers, pero el
substring match `in` abria la seccion en CUALQUIER linea que contuviera el literal
del heading, incluyendo prosa. Exigir `stripped == f"## {heading}"` garantiza que
solo la linea de heading real (sin contenido adicional) abre la seccion. Es el
cambio minimo que preserva la deteccion de las secciones reales existentes (los 23
tests de scope_gate siguen verdes) y elimina la captura de tokens basura desde
prosa. No introduce un nuevo gate ni relaja uno existente.

## TP Check

- TP-01: Premisa verificada en codigo real (5 parsers substring confirmados en scope_gate.py l.125,162,188,230 + pre_handoff_guard.py)
- TP-02: Fix mecanico claro: cambiar `in` por `==` o `startswith` con normalizacion (heading = linea completa)
- TP-03: Tests de regresion: work_plan con prosa que menciona `## Files Likely Touched` antes de la seccion real
- TP-04: Mutation-verify: revertir fix -> parser vuelve a leer prosa
- TP-05: No romper tests existentes de scope_gate (23 tests siguen verdes)