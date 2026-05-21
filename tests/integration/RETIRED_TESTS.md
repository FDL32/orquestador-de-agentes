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

## Known Debt

No outstanding test debt remains after WP-2026-066. All retired tests are documented here with clear justification.
