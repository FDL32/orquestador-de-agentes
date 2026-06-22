# Retired Integration Tests - WP-2026-066

## Context

WP-2026-066 aligns the recovered baseline with integration tests by either updating them to reflect the current runtime or retiring them with clear justification.

## Retired: test_multi_ticket_integration_smoke.py

**Status:** RETIRED in WP-2026-066

**Reason:** This test file depends on removed controller APIs that no longer exist in the recovered baseline:
- `controller.mark_ready()` - function removed
- `controller.request_changes()` - function removed
- `controller.perform_document_closeout()` - function removed
- `controller.get_log_status()` - function removed
- `controller.get_rejection_count()` - function removed
- `controller.COUNCIL_BROKER_AVAILABLE` - constant removed
- `controller.EVENT_BUS_AVAILABLE` - constant removed

**Decision:** Rather than restoring these symbols (which would create API debt), the test is retired. The multi-ticket security model guarantees from WP-2026-039 remain documented in `PROJECT.md` but the smoke test itself is removed since it tested integration patterns that no longer match the current runtime contract.

**Alternative validation:** The core ticket flow is validated through:
- Unit tests in `tests/unit/` that cover the controller's current API surface
- Manual terminal-driven runs following the canonical closeout protocol
- `python .agent/agent_controller.py --validate --json --force` for state consistency

## Retired: test_manager_builder_loop.py

**Status:** RETIRED in WP-2026-061

**Reason:** Depended on `STATE_FILE` constant and controller patterns that do not exist in the recovered baseline. The Manager/Builder loop is now validated through the bus-first event contract and terminal-driven workflows.

## Retired: tests/deprecated/ (Goose integration suite)

**Status:** RETIRED in WOT-2026-013f

**Files removed:**
- `tests/deprecated/test_goose_triggers.py`
- `tests/deprecated/test_goose_realworld.py`
- `tests/deprecated/__init__.py`

**Reason:** These tests covered the Goose orchestration engine, which was deprecated by **WT-2026-254a** (Claude Code is now the primary AI backend). Both files carried the header `# DEPRECATED (WT-2026-254a): Goose integration deprecated. Moved from scripts/ to tests/deprecated/.`

**Why removal is safe (zero impact on canonical collection):** The directory was already excluded from the runner via `norecursedirs = ... tests/deprecated ...` in `pytest.ini`, so these files were never collected by `python scripts/run_pytest_safe.py` nor by `python -m pytest tests`. Pruning them does **not** reduce the canonical test count: collect-only stays at 3111 before and after (verified in the WOT-2026-013f execution log). No live consumer references `tests/deprecated/` — `scripts/cleanup_legacy.py` resolves its `OLD_SCRIPT_NAMES` only against `scripts/` (not this directory), and the only other references are in gitignored generated cache (`graphify-out/`) and a historical, already-deprecated note in `.claude/rules/03-skills-discovery.md`.

**Audit source:** WOT-2026-013e suite audit (`docs/test_performance/test_suite_audit.md`) classified `tests/deprecated/` as a `legacy candidate` and proposed this prune as follow-up FU-013E-2.

## Known Debt

No outstanding test debt remains after WOT-2026-013f. All retired tests are documented here with clear justification.
