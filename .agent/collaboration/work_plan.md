# Work Plan

## Metadata
- **ID:** WOT-2026-019g
- **Estado:** COMPLETED
- **deliverable_type:** code
- **delivery_authority:** repo_motor

## Objetivo

El guard code de mark-ready (_check_implementation_evidence en agent_controller.py)
exige que un archivo del Files Likely Touched aparezca en el diff git. Un
deliverable_type=code cuyo entregable vive ENTERAMENTE en superficie gitignored
no satisface el guard. Fix: si cada FLT es gitignored (verificado con
git check-ignore), saltar los checks de evidencia productiva y FLT-match.

## Root cause

_check_implementation_evidence (l.1764+) verifica has_productive_evidence,
is_collaboration_only, is_docs_only y FLT-match-git. Cada uno falla para un
ticket code con deliverable gitignored porque git no ve los archivos.

## Files Likely Touched

- `.agent/agent_controller.py`
- `tests/test_agent_controller.py`

## Read/inspect only

- `bus/evidence.py` (resolve_evidence, fuente de all_files)

## Criterios binarios de aceptacion

- [ ] _flt_all_gitignored retorna True cuando cada FLT es gitignored
- [ ] _flt_all_gitignored retorna False cuando al menos un FLT no es gitignored
- [ ] code ticket con FLT gitignored no recibe "No implementation evidence" ni
      "Collaboration-only" ni "No FLT match" errors
- [ ] mutation: revertir el flag flt_gitignored -> vuelve el bloqueo
- [ ] validate 0/0
- [ ] ruff check pasa
- [ ] Suite canonica exit 0, tested_commit_sha == HEAD

## Non-goals

- No eliminar el check FLT-match para tickets code con deliverable VERSIONADO
- No tocar resolve_evidence en bus/evidence.py
- No relajar has_commit ni quality gate evidence

## Decision Arquitectonica

Se elige tratar code ticket con FLT gitignored como non_code_ticket (skip
evidencia productiva + FLT-match) en vez de aceptar exit-code de gate como
sustituto, porque: (a) es el cambio minimo (reutiliza el patron existente de
non_code_ticket que hace return antes del FLT-match); (b) no introduce un
nuevo canal de evidencia (exit-code) que requeriria validacion adicional;
(c) git check-ignore es determinista y no requiere confianza en el agente.

## TP Check

- TP-01: Premisa verificada (resolve_evidence usa git diff/log que no ven
  gitignored; _check_implementation_evidence l.1764+ bloquea sin evidencia)
- TP-02: Fix mecanico: _flt_all_gitignored + flag flt_gitignored en 3 checks
- TP-03: Tests: _flt_all_gitignored true/false + code ticket skip evidence
- TP-04: Mutation: revertir flag -> code ticket gitignored recibe errores
- TP-05: No romper 8 tests existentes de TestImplementationEvidenceGate
