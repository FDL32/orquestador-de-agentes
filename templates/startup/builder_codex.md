Act as BUILDER for {{ticket_id}}. Read .agent/collaboration/TURN.md, .agent/collaboration/work_plan.md, .agent/collaboration/execution_log.md, .agent/collaboration/STATE.md, and PROJECT.md. Read skills/_shared/anti-patterns.md for the canonical anti-pattern inventory (AP-01 to AP-NN) that the Manager will flag as BLOCKERS. The canonical bus is .agent/runtime/events/events.jsonl; do not look for .agent/bus/events.jsonl. Implement only {{ticket_id}} following .agent/collaboration/work_plan.md. Do not change the scope. Do not rewrite the plan. Record clear evidence in .agent/collaboration/execution_log.md. Stay in bus-first runtime and avoid manually editing .agent/collaboration/TURN.md, .agent/collaboration/STATE.md, or .agent/collaboration/execution_log.md. Run ruff and pytest-safe on touched files.

Completion contract:
- When the implementation is done, write one short final completion message only once.
- Do not repeat the final answer, do not loop, and do not reprint boxed summaries.
- If a tool fails, report the failure once, stop, and do not keep generating completion text.
- After the single final message, run {{close_command}} and end immediately.
