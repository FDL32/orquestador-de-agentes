# MEMORY

Regenerated: 2026-05-29T17:05:26.828367+00:00

Total observations: 48

- Adapter Pipeline Wp Split (1 observations)
- Ap-Nn-Cross-Cutting-Architecture (1 observations)
- Architecture (1 observations)
- Arranque (1 observations)
- Auto-Improvement-Loop-Formalized (1 observations)
- Builder-Closeout-Hallucination (1 observations)
- Builder-Manager-Mirror-Pattern (1 observations)
- Builder-Window-Silent-Fail (1 observations)
- Bus-Import-Boundary (1 observations)
- Delivery-Hook-Mutation (2 observations)
- Design-Pattern-Positive (1 observations)
- Dispatcher Global Side Effect (1 observations)
- Explicit Legacy Edit Missing From Diff (1 observations)
- Future-Improvement-Diff-Based-Review (1 observations)
- Future-Improvement-Memory-Categorization (1 observations)
- Handoff-Blocked-Not-Crash (1 observations)
- Lock Reentrancy Antipattern (1 observations)
- Manager-Review-Rubric (5 observations)
- Projection-Probe-Debt (1 observations)
- Protocol-Key-Assumption (1 observations)
- Request Changes Requeue Deadlock (1 observations)
- Return Type Falsy Guard (1 observations)
- Review-Packet-Untracked-Files (1 observations)
- Safe-Suite-Coverage-Gap (1 observations)
- Scanner Corpus Scope (1 observations)
- Security-Gate-Fail-Open (1 observations)
- Session-Close-Manual-Gap (1 observations)
- Silent Subprocess Failure Pattern (1 observations)
- Skills-Taxonomy-V2 (1 observations)
- State-Projection-Drift (1 observations)
- Supervisor-Process-Staleness (1 observations)
- Test-Linting-Policy (1 observations)
- Test-Surrogate-Antipattern (1 observations)
- Testability-Refactor-Scope-Drift (1 observations)
- Ticket-Completion (1 observations)
- Ticket-Contradiction-Sequence (1 observations)
- Ticket-Gate-Placement (1 observations)
- Ticket-Plan-Audit-Parity-Gap (1 observations)
- Ticket-Structure-Risk-Heuristic (1 observations)
- Ticket-Unverifiable-Acceptance (1 observations)
- Timeout Config Key Collision (1 observations)
- Unique Id Generation Smell (1 observations)
- Windows-Precommit-Line-Endings (1 observations)

## adapter_pipeline_wp_split
- WP-2026-147: ticket originally mixed a read-only adapter (graph_context.py) with a full pipeline build (project_scanner.py). Corrected before Builder started. Rule: read-only adapter over existing art

## ap-nn-cross-cutting-architecture
- AP-NN numbering system established as cross-cutting convention linking 3 artifacts: skills/_shared/anti-patterns.md (canonical source of IDs + names), bui-implement-from-plan/references/code-rules.md 

## architecture
- Decisiones arquitectonicas documentadas en WP-2026-175

## arranque
- Runtime correcto localizado en orquestador_de_agentes; validacion limpia y memoria lista para continuar el trabajo.

## auto-improvement-loop-formalized
- Auto-improvement loop architecture documented and operational: (1) human audit finding -> (2) observations.jsonl entry with applies_to scope -> (3) review_bridge._render_manager_review_learnings() inj

## builder-closeout-hallucination
- WP-2026-159: the Builder prompt that told a fresh window to 'emit BUILDER_EXIT' manually caused a hallucinated close command (--emit-exit builder ...) instead of the intended mark-ready flow. Rule: cl

## builder-manager-mirror-pattern
- Convention: every BLOCKER in Manager review-checklist.md has a corresponding preventive rule in Builder code-rules.md at the same AP-NN ID. The mirror is intentional: Manager detects, Builder prevents

## builder-window-silent-fail
- Cuando el supervisor emite BUILDER_RELAUNCH_ATTEMPTED y el launcher reporta exito, puede ocurrir que la ventana del Builder se abra pero el proceso opencode interior falle silenciosamente. El supervis

## bus-import-boundary
- Bus import boundary firewall implemented: tests/test_bus_boundary.py enforces bus/ -> scripts/ seam via (1) AST static analysis (ast.walk ImportFrom/Import) and (2) grep-based dynamic import detection

---

[MEMORY.md truncated at 80 lines. Full history available in observations.jsonl]