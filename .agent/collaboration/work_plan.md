# Work Plan - WP-2026-153

## Metadata
- **ID:** WP-2026-153
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Add grill-with-docs skill
- **Asignado a:** Builder

## Objetivo
Add a pre-plan interrogation skill that resolves ambiguous terminology before a work plan is created. The skill should ask one question at a time, provide a recommended answer before the user responds, prefer codebase-derived answers when possible, and keep domain context compact by using `PROJECT.md` and `MEMORY.md` by default. `CONTEXT.md` should remain optional and only be created or updated when it adds value as a separate glossary. The skill should reduce fuzzy scopes and avoid avoidable review loops before implementation begins.

## Decision Arquitectonica
- The new skill is a prompt/documentation artifact, not a Python runtime component.
- `PROJECT.md` and `MEMORY.md` are the default context inputs for the grilling flow.
- `CONTEXT.md` lives at the project root, alongside `PROJECT.md`; it is optional and should only be used when it provides a useful glossary boundary.
- The skill must support one-question-at-a-time interrogation with a recommended answer from the agent before the user replies.
- The workflow must be explicit and ordered: read `PROJECT.md` + `MEMORY.md`, optionally read `CONTEXT.md` if it exists, derive questions from the requirement (preferring those the codebase can answer directly), loop question -> recommended answer -> user confirmation/correction, propose a `CONTEXT.md` entry only when the term is not already defined in `PROJECT.md` or `MEMORY.md`, and then emit the completion handshake.
- The completion handshake must be exact: `> ✅ Grill completo. Términos resueltos: N. Puedes crear el WP con /plan.`
- The skill should describe when an ADR is justified using the three mattpocock criteria: hard to revert, surprising without context, and a real trade-off.
- No new dependencies are allowed.
- Any integration into `man-create-work-plan` is intentionally deferred unless it remains optional and non-disruptive.

## Files Likely Touched
- `skills/grill-work-plan/SKILL.md`
- `skills/README.md`
- `README.md`
- `PROJECT.md`
- `CHANGELOG.md`
- `PLAN_WP-2026-153.md`
- `AUDIT_WP-2026-153.md`
- `.agent/collaboration/execution_log.md`

## Fases
1. Create `skills/grill-work-plan/SKILL.md` with frontmatter, explicit triggers (`/grill-plan`, `/grill`, `grill-wp`), the ordered workflow, optional `CONTEXT.md` handling at repo root, one-question-at-a-time flow, ADR criteria, and the exact completion handshake.
2. Register the new skill in `skills/README.md` so it becomes discoverable.
3. Refresh the repo notes (`README.md`, `PROJECT.md`, and `CHANGELOG.md`) so the new pre-plan grilling step is visible.
4. Keep any `man-create-work-plan` integration optional and out of the hot path.
5. Refresh project metadata so the new cycle is the active ticket.

## Calidad
- `python skills/validate_all.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- The repository contains a new `skills/grill-work-plan/SKILL.md` that describes the interrogation workflow.
- The skill treats `PROJECT.md` and `MEMORY.md` as the default context inputs and keeps `CONTEXT.md` optional.
- The skill emits the exact completion handshake line `> ✅ Grill completo. Términos resueltos: N. Puedes crear el WP con /plan.`
- The skill documentation includes the three ADR criteria from mattpocock.
- The skill is discoverable from `skills/README.md` and documented in the repo notes.
- No mandatory code-path integration is introduced into `man-create-work-plan`.
- Validation passes without new warnings or errors.
