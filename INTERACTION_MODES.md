# Interaction Modes

This template supports two operating modes:

All commands below are relative to the repository root.

## Agent backends

Builder and Manager are roles, not products. You can run each role with any supported agent frontend as long as it can read and write the canonical files.

### Supported backends

| Backend | Typical use | Builder | Manager | Notes |
|---------|-------------|---------|---------|-------|
| Claude Code | Terminal/chat orchestration | Yes | Yes | Good for plan/review/chat-driven work. |
| Codex | Terminal review bridge and orchestration | Yes | Yes | Good for file-driven planning and review. |
| Cline | VS Code / terminal workflow | Yes | Yes | Good when you want VS Code-native Builder sessions. |
| Kilo | VS Code / terminal workflow | Yes | Yes | Good for interactive or autonomous agent runs. |

Rules:
- The backend may change, but the role contract does not.
- Builder still implements the ticket.
- Manager still approves, requests changes, or closes the cycle.
- Update `TURN.md`, `STATE.md`, `execution_log.md`, and `notifications.md` when you switch backend mid-ticket.

## 1. Chat-driven mode

Use chat-driven mode when:
- you are exploring scope,
- you need back-and-forth reasoning,
- the change is small or primarily documentary,
- or the Builder/Manager roles are being coordinated manually.

Typical flow:
1. Manager and Builder coordinate in chat.
2. Builder implements the requested change.
3. Builder runs quality gates.
4. Manager reviews the result.
5. User confirms final closeout when needed.

Canonical files:
- `PROJECT.md`
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `CHANGELOG.md`

Rules:
- Keep one active ticket at a time.
- Builder writes evidence in `execution_log.md`.
- Manager requests changes or approves in chat.
- Run `ruff`, `pytest-safe`, and `pip-audit` before closing.

## 2. Terminal-driven mode

Use terminal-driven mode when:
- you want sequential execution across several tickets,
- you want the supervisor to advance the queue automatically,
- or you want Builder and Manager to interact through files and terminal prompts.

Typical flow:
1. Start the supervisor:
   - `python scripts/ticket_supervisor.py --reactive`
2. Builder works on the active ticket in `TURN.md`.
3. Supervisor enforces order and ticket transitions.
4. Manager reviews from terminal using the review bridge:
   - `python scripts/manager_review_bridge.py --watch`
   - If `codex` is not on `PATH`, set `CODEX_CLI_PATH` or pass `--backend-path`.
5. Manager moves the ticket to `READY_TO_CLOSE`.
6. User confirms final closeout.
7. Supervisor advances to the next ticket.

Canonical files:
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/notifications.md`
- `.agent/collaboration/execution_log.md`
- `.agent/runtime/events/events.jsonl`
- `.agent/runtime/ui_state.json`
- `.agent/runtime/manager_bridge_state.json`

Rules:
- Do not mix chat and terminal on the same ticket without updating the canonical files first.
- `READY_FOR_REVIEW` means Manager review is pending.
- `READY_TO_CLOSE` means Manager approved and user closeout is pending.
- `COMPLETED` only happens after `CLOSE_CONFIRMED`.
- `CLOSE_REJECTED` returns the ticket to `REWORK_REQUESTED`.

## Choosing a mode

- Choose chat-driven mode for discovery, planning, and one-off changes.
- Choose terminal-driven mode for repeatable sequential work and minimal manual handoffs.
- If you switch modes mid-ticket, write the reason in `execution_log.md` and update `TURN.md`.

## Minimum terminal commands

```powershell
python .agent\agent_controller.py --validate --json --force
python scripts\ticket_supervisor.py --once
python scripts\ticket_supervisor.py --reactive
python scripts\manager_review_bridge.py --watch
python .agent\agent_controller.py --closeout --force
```
