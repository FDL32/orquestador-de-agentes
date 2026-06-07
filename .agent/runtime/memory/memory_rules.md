# Memory Rules (L2)

Total rules: 30

Rules derived deterministically from observations.jsonl. Each rule carries an ID (R-XXX), domain, wing, source ticket, and signal text.

## Wing: engine

### Domain: ap-nn-cross-cutting-architecture

#### R-002: AP-NN numbering system established as cross-cutting convention linking 3 artifac

AP-NN numbering system established as cross-cutting convention linking 3 artifacts: skills/_shared/anti-patterns.md (canonical source of IDs + names), bui-implement-from-plan/references/code-rules.md (Builder preventive rules, detailed examples), man-review-implementation/references/review-checklist.md (Manager BLOCKER checklist). Adding a new AP requires touching all 3. observations.jsonl can carry anti_pattern_id field to link findings to AP-NN. AP-01..AP-08 active. Origin: session 2026-05-25.

*Source: session-2026-05-25*


## Wing: meta

### Domain: manager-review-rubric

#### R-011: AP-08 candidate: Test coverage drift. The Builder runs the existing suite, sees

AP-08 candidate: Test coverage drift. The Builder runs the existing suite, sees it pass, and declares quality gates satisfied — but the new functions introduced in the diff have no direct tests. The suite passing is not evidence of coverage when the new code is never called by any test. Manager rule: when the diff introduces new functions (def, method, classmethod), verify that at least one test in test_*.py calls each new function directly. Absence of direct test coverage for new functions = BLOCKER, even if the full suite passes. Origin: WP-2026-139 audit — 3 new methods (_parse_canonical_anti_patterns, _load_canonical_anti_patterns, _render_canonical_anti_pattern_inventory) had zero tests; Manager approved without noticing.

#### R-012: BLOCKER pattern: Boolean truthiness regression in changed return contracts. When

BLOCKER pattern: Boolean truthiness regression in changed return contracts. When a method changes from returning implicit None to returning explicit bool, all callers must be updated from generic truthiness guards (if not x, if x, while x) to identity checks (is False, is True). Mixing None/False/True under a falsy guard silently breaks when the method is monkeypatched to return None (common in tests) or called from a legacy path that predates the type change. Manager must grep all callers in the diff and verify no if not / if pattern remains. Any surviving generic guard = CHANGES. Origin: WP-2026-137 bug audit.

#### R-013: BLOCKER pattern: Exclusive resource acquisition without reentrancy guard. When a

BLOCKER pattern: Exclusive resource acquisition without reentrancy guard. When a method acquires an exclusive resource (O_CREAT|O_EXCL, flock, Lock.acquire, lock-file creation) AND can be reached from more than one call site or called twice on the same instance (e.g. standalone call + internal call from a wrapper), there must be an explicit instance-level reentrancy guard. Without it, the second call hits the exclusion check with its own PID alive and returns False, silently aborting the caller. Manager should grep all call sites of the method in the diff and repo. No reentrancy guard = CHANGES. Origin: WP-2026-137 bug audit.

#### R-014: Validator evidence gate: when a work_plan explicitly declares a validator as a q

Validator evidence gate: when a work_plan explicitly declares a validator as a quality gate (skills/validate_all.py, agent_controller --validate, ruff, pytest), the Manager must find explicit output from that validator showing a clean result in execution_log.md. Declared validator + absent evidence = BLOCKER. This applies especially to scaffolding and documentation tickets where standard code gates do not run automatically. Origin: WP-2026-133 audit.

#### R-015: deliverable_type classification for scaffolding tickets: when Files Likely Touch

deliverable_type classification for scaffolding tickets: when Files Likely Touched contains only structural non-Python files (.gitkeep, empty dirs, placeholders, config stubs) with no logic, the correct deliverable_type is documentation, not code. Using code triggers ruff+pytest rubric which produces false noise on files with no logic. Manager should flag code classification for pure-scaffolding tickets as a planning error (SUGGESTIONS). Origin: WP-2026-133 audit.


### Domain: return_type_falsy_guard

#### R-018: WP-2026-137: Changing a method return type from None->bool (bootstrap) requires

WP-2026-137: Changing a method return type from None->bool (bootstrap) requires updating callers from "if not method():" to "if method() is False:". The falsy guard caused a test regression: existing test monkeypatched bootstrap to "lambda: None", so "if not None" was True and run_reactive exited immediately. Rule: when a method previously returned None and is refactored to return bool, always use "is False" guards in callers to avoid false-positive exits on None-returning mocks or legacy callers.


### Domain: review-quality

#### R-019: AP-12: WP-2026-157: the review packet built from git diff HEAD hid brand-new unt

AP-12: WP-2026-157: the review packet built from git diff HEAD hid brand-new untracked files, so the Manager saw an incomplete/partial diff while the real deliverables lived outside the tracked set. Rule: review packets must include new untracked deliverables explicitly, not only tracked-file diffs.


### Domain: silent_subprocess_failure_pattern

#### R-022: subprocess.run with capture_output=True silently discards stderr/stdout unless r

subprocess.run with capture_output=True silently discards stderr/stdout unless returncode is checked. Pattern: always store subprocess result and log stderr to sys.stderr on rc != 0, especially for state-transition subprocesses where silent failure breaks re-engagement chains.


### Domain: ticket-structure-risk-heuristic

#### R-027: Structural complexity predicts regression risk better than file count. Tickets t

Structural complexity predicts regression risk better than file count. Tickets that apply the same atomic operation N times (e.g. create .gitkeep in 7 dirs) carry near-zero regression risk regardless of file count — majority-scaffolding scope = light review. Tickets that change behavior across multiple call sites or layers carry high risk even with few files — cross-layer behavior changes = deep review. Use as context signal when calibrating review depth, not as a hard blocker criterion. Origin: WP-2026-133 vs WP-2026-137 contrast.


## Wing: project

### Domain: adapter_pipeline_wp_split

#### R-001: WP-2026-147: ticket originally mixed a read-only adapter (graph_context.py) with

WP-2026-147: ticket originally mixed a read-only adapter (graph_context.py) with a full pipeline build (project_scanner.py). Corrected before Builder started. Rule: read-only adapter over existing artifacts and new infrastructure pipeline are different risk profiles — split into separate tickets even when they share a theme.


### Domain: auto-improvement-loop-formalized

#### R-003: Auto-improvement loop architecture documented and operational: (1) human audit f

Auto-improvement loop architecture documented and operational: (1) human audit finding -> (2) observations.jsonl entry with applies_to scope -> (3) review_bridge._render_manager_review_learnings() injects into Manager prompt -> (4) Manager detects pattern in future tickets -> (5) session-close-observations promotes recurring signal to AP-NN -> (6) AP-NN appears in code-rules.md (Builder) and review-checklist.md (Manager). The loop is closed. review_bridge also loads AP IDs from _shared/anti-patterns.md with lazy cache at __init__. Origin: session 2026-05-25.

*Source: session-2026-05-25*


### Domain: builder-manager-mirror-pattern

#### R-004: Convention: every BLOCKER in Manager review-checklist.md has a corresponding pre

Convention: every BLOCKER in Manager review-checklist.md has a corresponding preventive rule in Builder code-rules.md at the same AP-NN ID. The mirror is intentional: Manager detects, Builder prevents. When a new AP is added, both surfaces must be updated in the same commit. A BLOCKER without a preventive rule in code-rules.md is an incomplete AP. Origin: session 2026-05-25.

*Source: session-2026-05-25*


### Domain: config-schema

#### R-005: WP-2026-157: exposing evaluate_tool_request() and requeue_ticket() for eval cove

WP-2026-157: exposing evaluate_tool_request() and requeue_ticket() for eval coverage required refactors in guard_paths.py and bus/supervisor.py that were outside the original Files Likely Touched list. Rule: when the plan requires in-process evals, declare the production refactor surface explicitly so scope gating does not reject necessary testability changes.


### Domain: design-pattern-positive

#### R-006: Pattern: index-file + inline-instructions separation. When a system needs both a

Pattern: index-file + inline-instructions separation. When a system needs both a human-readable canonical inventory (IDs + short names, in a markdown file) and LLM-optimized detection instructions (detailed English text with examples, in code), keep them as separate artifacts with explicit roles. The file is the single source of truth for IDs and names; the code references those IDs in its detailed rubric. Extracting the path to a dedicated method (_canonical_anti_patterns_path) makes it trivially monkeypatcheable in tests. Fallback: OSError -> warnings.warn(RuntimeWarning) + return [] keeps the system online with degraded but functional output. Origin: WP-2026-139 review_bridge canonical AP loading.


### Domain: dispatcher_global_side_effect

#### R-007: WP-2026-149: placing a new side-effecting sync call at the top of main() before

WP-2026-149: placing a new side-effecting sync call at the top of main() before flag dispatch would run it on every invocation, not only the named handlers. Rule: when the plan names specific handlers (for example main status path and --validate), the implementation must call the sync inside those handlers and nowhere earlier in the dispatcher.


### Domain: explicit_legacy_edit_missing_from_diff

#### R-008: WP-2026-149: the plan explicitly required editing an existing function (_materia

WP-2026-149: the plan explicitly required editing an existing function (_materialize_state_transition) but the diff initially only added new code. Rule: if a plan names a legacy function or regex to be modified, the resulting diff must include that exact legacy edit; new tests alone are not sufficient evidence of compliance.


### Domain: future-improvement-memory-categorization

#### R-009: The smithery.ai python-code-review skill organizes project memory into 4 explici

The smithery.ai python-code-review skill organizes project memory into 4 explicit categories: project_overview, common_patterns, known_issues, review_history. Our current observations.jsonl is flat. Adding a category/topic taxonomy could make retrieval and MAX_RUBRIC_OBSERVATIONS selection more precise (e.g. pull only known_issues for code reviews). Worth evaluating as an evolution of observations.jsonl schema. Extracted from external skill audit on 2026-05-25.


### Domain: lock_reentrancy_antipattern

#### R-010: WP-2026-137: Placing lock acquisition inside a method (bootstrap) that is called

WP-2026-137: Placing lock acquisition inside a method (bootstrap) that is called from multiple call sites (run_reactive, run_loop, standalone) created a double-call regression. Second call hit FileExistsError with own PID alive -> returned False -> caller exited immediately without running. Fix: reentrancy flag (_supervisor_lock_held) so same instance re-enters transparently. Rule: when a lock-acquiring method is reused across call sites, guard with an instance-level reentrancy flag before the OS-level O_CREAT|O_EXCL check.


### Domain: projection-probe-debt

#### R-016: Minor debt discovered in the projection probe: _parse_markdown_state accepts tic

Minor debt discovered in the projection probe: _parse_markdown_state accepts ticket_id but does not use it yet; this is safe today because STATE.md is single-ticket, but it would become a silent bug if the file ever became multi-ticket.

*Source: WP-2026-145*


### Domain: request_changes_requeue_deadlock

#### R-017: WP-2026-152: state_from_review_decision maps changes->IN_PROGRESS, making the --

WP-2026-152: state_from_review_decision maps changes->IN_PROGRESS, making the --request-changes guard reject it unconditionally. Fix: derive pending_requeue from events[-1] before the guard. Pattern: any guard on bus_state must account for state machine transitions that map review decisions to in-flight states.


### Domain: scanner_corpus_scope

#### R-020: WP-2026-147: graphify indexed uv-cache, _archive, reviews — 97% noise nodes — be

WP-2026-147: graphify indexed uv-cache, _archive, reviews — 97% noise nodes — because IGNORE_DIRS lacked system-state dirs. Rule: after adding any file scanner, bucket nodes by path prefix and verify signal/noise ratio before using the output.


### Domain: security

#### R-021: AP-11: WP-2026-154: guard_paths.py resolved unknown strictness_profile with prof

AP-11: WP-2026-154: guard_paths.py resolved unknown strictness_profile with profiles.get(profile_name, profiles.get('standard', {})) — silent fallback to standard when the named profile was absent. A partially migrated or hand-edited agents.json could silently reduce enforcement to base-only level. Rule: security gates must fail closed (exit 2 / raise) on invalid or unknown config. Silent permissive fallback in a security gate is more dangerous than an explicit block.


### Domain: test-linting-policy

#### R-023: Policy: ruff extend-exclude should point to tests/sandbox/ (not tests/) so the t

Policy: ruff extend-exclude should point to tests/sandbox/ (not tests/) so the test suite is linted. Use per-file-ignores in pyproject.toml to suppress systematically legitimate patterns (S603, S607, S108, SIM115, PERF203) as policy rather than per-line noqa. Rationale: per-file-ignores survive ruff autoformat; per-line noqa on try: lines get stripped. Origin: WP-2026-140.

*Source: WP-2026-140*


### Domain: testing

#### R-024: AP-09: WP-2026-154: guard_paths.py __main__ read tool_calls/shell_command (assum

AP-09: WP-2026-154: guard_paths.py __main__ read tool_calls/shell_command (assumed keys) instead of tool_input/command (real Claude Code PreToolUse protocol). The same wrong assumption propagated into the integration tests, which also used tool_calls format — so production and tests reinforced each other's error. The hook always exited 0, functionally identical to the old stub. Rule: before reading any key from an external payload, locate the protocol spec and verify the exact key name. If a hook unconditionally exits 0 under all inputs, it is probably reading the wrong key.

#### R-025: AP-10: WP-2026-154: TestGuardHookProfiles created synthetic hook scripts in tmp_

AP-10: WP-2026-154: TestGuardHookProfiles created synthetic hook scripts in tmp_path that loosely mimicked guard_paths.py behavior, then ran subprocess against those surrogates. The real guard_paths.py was never invoked by any integration test. All 3 integration tests passed while the real hook had critical input-format and fail-open bugs. Rule: integration tests must invoke the real module/script — find its path and use it directly. If the test never imports or calls the real artifact, it tests the surrogate, not the code.

#### R-026: WP-2026-157: the safe suite did not include tests/test_guard_paths.py and tests/

WP-2026-157: the safe suite did not include tests/test_guard_paths.py and tests/test_configuration_loading.py, so an import regression in test compatibility was only caught during manual review. Rule: when a regression can occur in a small, stable test file, include that file in the safe suite or explicitly document why it is excluded.


### Domain: timeout_config_key_collision

#### R-028: WP-2026-146: Builder reused manager_review.timeout_seconds (180s, AI subprocess

WP-2026-146: Builder reused manager_review.timeout_seconds (180s, AI subprocess latency) as the HUMAN_GATE expiry timeout. These serve different actors on completely different time scales: model latency (seconds) vs human availability (hours). Fix: separate config key human_gate_timeout_seconds with 86400s fallback. Rule: when two timeouts share a config section but serve actors with different time scales, they must have distinct keys — never reuse a latency timeout for a human-availability timeout.


### Domain: unique_id_generation_smell

#### R-029: WP-2026-146: Builder generated unique IDs with sha256(ticket_id + timestamp), re

WP-2026-146: Builder generated unique IDs with sha256(ticket_id + timestamp), requiring time.sleep(0.01) in tests to avoid collisions. Rule: use uuid4() for IDs that must be unique within a process — it is collision-free by definition, removes sleep dependencies from tests, and does not leak timing information.


### Domain: windows-precommit-line-endings

#### R-030: Pattern: on Windows, files edited by Python tools (Edit/Write) may have mixed CR

Pattern: on Windows, files edited by Python tools (Edit/Write) may have mixed CRLF+LF endings. pre-commit mixed-line-ending hook fixes them but fails if there are unstaged files (stash+restore conflict). Fix: run python -c to convert all .py files to LF before git add, so the hook finds nothing to change. Origin: WP-2026-140 commit session.
*Source: WP-2026-140*
