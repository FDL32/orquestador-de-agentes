# MEMORY

Total de observaciones: 8

- Arranque (1 observaciones)
- Design patterns (2 observaciones)
- Conventions (3 observaciones)
- Ops patterns (1 observaciones)
- Bus architecture (1 observaciones)

## arranque
- Runtime correcto localizado en orquestador_de_agentes; validacion limpia y memoria lista para continuar el trabajo.

## design-patterns
- Pattern: index-file + inline-instructions separation. Canonical inventory (IDs + names) en markdown; instrucciones LLM-optimized en codigo con referencia a esos IDs. Metodo dedicado `_canonical_anti_patterns_path()` lo hace monkeypatcheable. Fallback: OSError -> warnings.warn(RuntimeWarning) + return []. Origin: WP-2026-139.
- Auto-improvement loop operativo: audit finding -> observations.jsonl (applies_to) -> review_bridge inyecta en prompt Manager -> Manager detecta patron -> session-close-observations promueve a AP-NN -> AP-NN en code-rules.md (Builder) + review-checklist.md (Manager). Loop cerrado. Origin: session 2026-05-25.

## conventions
- AP-NN cross-cutting: skills/_shared/anti-patterns.md (IDs canonicos) + bui-implement-from-plan/references/code-rules.md (reglas preventivas Builder) + man-review-implementation/references/review-checklist.md (BLOCKERs Manager). Anadir AP requiere tocar las 3 superficies. AP-01..AP-08 activos. Origin: session 2026-05-25.
- Builder-Manager mirror: cada BLOCKER en review-checklist.md tiene regla preventiva en code-rules.md al mismo AP-NN. Un BLOCKER sin preventiva es AP incompleto. Origin: session 2026-05-25.
- Ruff test linting policy: extend-exclude debe apuntar a tests/sandbox/ (no tests/). Patrones legitimos en tests (S603, S607, S108, SIM115, PERF203) se suprimen via per-file-ignores en pyproject.toml, NO con noqa por linea (ruff autoformat elimina noqa en try:). Origin: WP-2026-140.

## ops-patterns
- Windows pre-commit line endings: archivos editados con herramientas Python pueden tener CRLF+LF mixtos. El hook mixed-line-ending falla si hay unstaged files (conflicto stash+restore). Fix: convertir todos los .py a LF con Python antes de git add. Origin: WP-2026-140.

## bus-architecture
- Bus import boundary firewall: tests/test_bus_boundary.py enforza seam bus/->scripts/ con (1) AST estatico y (2) grep dinamico (importlib/__import__). Seam permitido: scripts.discover_skills. ALLOWED_SCRIPTS_IMPORTS es el punto de extension para futuros seams. Origin: WP-2026-140.
