# Memory Architecture - Surface Classification

## Purpose
Document the canonical classification of every operational surface in `.agent/` to avoid cargo-cult loading, accidental rotation of canonical state, or blind archival of live feedback.

## Classification Taxonomy

| Category | Description | Safe to delete/regenerate? |
|----------|-------------|---------------------------|
| **canonical** | Single source of truth for active state. Must never be archived or rotated as cache. | NO |
| **projection** | Derived view from canonical state. Can be regenerated but not arbitrarily deleted. | Only if regenerable from canonical |
| **persistent-memory** | Curated long-term memory (L1/L2/L3). Preserved across sessions. | NO (loss of project context) |
| **private-mirror** | Local non-portable mirrors of external tools (~/.claude/, etc.). | YES (but not by this project) |
| **cache** | Regenerable artifacts, temporary computations. Safe to delete. | YES |
| **archive** | Historical closed-ticket artifacts. Read-only, reference only. | Advisory (loss of forensics) |

## Surface Inventory

### canonical

| Path | Owner | Readers | Writers | Bootstrap-load? | Rotation policy |
|------|-------|---------|---------|-----------------|-----------------|
| `.agent/collaboration/work_plan.md` | Controller | Builder, Supervisor, Manager, CLIs | agent_controller.py, completion_checker.py | YES (active ticket) | Never archived; updated by controller on state change |
| `.agent/collaboration/STATE.md` | Controller | Builder, Supervisor, Manager, CLIs | agent_controller.py, session_tracker.py | YES | Never archived; updated by controller on state change |
| `.agent/collaboration/TURN.md` | Controller | Builder, Supervisor, Manager | agent_controller.py | YES | Never archived; regenerated each turn |
| `.agent/runtime/events/events.jsonl` | Event Bus | All agents | bus/*.py, scripts/*.py | NO (too large; filtered queries only) | Archived by `archive_event_bus.py` on session close |
| `.agent/collaboration/bus.jsonl/` | Event Bus (legacy) | Supervisor, Manager | bus/supervisor.py | NO | Legacy; preserved until migration complete |

### projection

| Path | Owner | Readers | Writers | Bootstrap-load? | Rotation policy |
|------|-------|---------|---------|-----------------|-----------------|
| `.agent/collaboration/notifications.md` | Controller | CLI, user | agent_controller.py (ui_state_projector) | YES (summary) | Rotated by controller archive mechanism; never deleted entirely |
| `.agent/runtime/memory/session_close_report.md` | Closeout | Human, Manager | session_closeout.py | NO | Overwritten each session close |
| `.agent/collaboration/execution_log.md` | Controller | Builder, Supervisor, Manager | agent_controller.py, completion_checker.py, stop_hook.py | YES (status only) | Archived by `archive_execution_log.py` on session close; new one created |

### persistent-memory

| Path | Owner | Readers | Writers | Bootstrap-load? | Rotation policy |
|------|-------|---------|---------|-----------------|-----------------|
| `.agent/runtime/memory/observations.jsonl` | Memory system | Builder, Manager, memory_loader | session_close_observations.py | NO (loaded on demand via recall) | Never rotated; appended only |
| `.agent/runtime/memory/MEMORY.md` | Memory system | Builder, Manager, memory_loader | memory_consolidate.py | YES (index) | Regenerated on consolidation |
| `.agent/runtime/memory/memory_profile.md` | Memory system (L3) | Builder, Manager | memory_consolidate.py | YES (profile) | Regenerated on consolidation |
| `.agent/runtime/memory/memory_rules.md` | Memory system (L2) | Builder, Manager | memory_consolidate.py | NO (loaded per domain) | Regenerated on consolidation |
| `.agent/runtime/memory/closeout_lessons.md` | Memory system | Manager (Paso 0b) | Builder, Manager | YES (lesson list) | Updated manually or by ticket |
| `.agent/runtime/memory/memory_architecture.md` | Memory system | All agents | Builder | NO | Updated per WT-2026-190 scope |

### cache

| Path | Owner | Readers | Writers | Bootstrap-load? | Rotation policy |
|------|-------|---------|---------|-----------------|-----------------|
| `.agent/runtime/tmp/` | Runtime | Temporary scripts | Various | NO | Cleaned on session close |
| `.agent/runtime/reviews/` | Review Bridge | Manager | manager_review_bridge.py | NO | Preserved as review log; not auto-cleaned |

### archive

| Path | Owner | Readers | Writers | Bootstrap-load? | Rotation policy |
|------|-------|---------|---------|-----------------|-----------------|
| `.agent/collaboration/_archive/plan_audit/` | Closeout | Human reference | archive_collaboration_artifacts.py | NO | Written on session close; never rotated |
| `.agent/collaboration/_archive/legacy/` | Closeout | Human reference | archive_collaboration_artifacts.py | NO | Legacy snapshots; never rotated |
| `.agent/collaboration/archive/review_queue_*.md` | Closeout | Human reference | session_closeout.py | NO | Written on session close rotation |
| `.agent/collaboration/archive/manager_feedback/` | Closeout | Human reference | archive_collaboration_artifacts.py, session_closeout.py | NO | Written on session close when close proven |

### review-queue (special: write-mostly operational log)

| Path | Category | Owner | Readers | Writers |
|------|----------|-------|---------|---------|
| `.agent/collaboration/review_queue.md` | **Operational log** (not canonical state) | Review Bridge | Supervisor, Manager, Builder | bus/supervisor.py, scripts/manager_review_bridge.py, .agent/agent_controller.py, .agent/completion_checker.py, .agent/hooks/stop_hook.py |
| `.agent/collaboration/archive/review_queue_*.md` | Archive | Closeout | Human reference | session_closeout.py |

**Policy for review_queue.md:**
- Not loaded in bootstrap (too large; use filtered queries or summary).
- Not canonical state; it is an append-only operational log.
- Rotated **only** by `session_closeout.py` in `--session-close` flow, between `_step_archive_collaboration` and `_step_archive_execution_log`.
- Lock-checked against `builder_lock.txt` and `supervisor_lock.txt` before rotation.
- Manual pruning is forbidden (CL-03).
- After rotation: header + active ticket entry + 10 most recent logical entries are preserved.
- Archived portion goes to `.agent/collaboration/archive/review_queue_YYYY-MM-DD.md`.

### manager-feedback (special: feedback per ticket)

| Path | Category | Owner | Readers | Writers |
|------|----------|-------|---------|---------|
| `.agent/collaboration/manager_feedback_*.md` | **Operational feedback** (temporary) | Review Bridge | Supervisor, Manager, Builder | scripts/manager_review_bridge.py |
| `.agent/collaboration/archive/manager_feedback/` | Archive | Closeout | Human reference | archive_collaboration_artifacts.py, session_closeout.py |

**Policy for manager_feedback_*:**
- Each file corresponds to one ticket (e.g., `manager_feedback_WP-2026-155.md`).
- Not canonical state; it is per-ticket review feedback.
- Archived **only** when the bus confirms close/approval for that ticket.
- If close cannot be proven from the bus, the file remains alive.
- No manual archival based on filename alone.
- Destined for `.agent/collaboration/archive/manager_feedback/`.

## Writers of review_queue.md

Confirmed by grep of the codebase:

| Writer script | Mechanism |
|---------------|-----------|
| `bus/supervisor.py` | Appends review results to review_queue.md during supervision |
| `scripts/manager_review_bridge.py` | Appends manager review output and decision |
| `.agent/agent_controller.py` | Records review lifecycle events |
| `.agent/completion_checker.py` | Reads review_queue.md to verify completion state |
| `.agent/hooks/stop_hook.py` | References REVIEW_QUEUE path constant for completion verification |

## Bootstrap Safety Rules

1. **Never** load `review_queue.md`, `manager_feedback_*` or `events.jsonl` in full as bootstrap context.
2. Always use `memory_loader` filtered queries (`recall_observations`, `get_review_context`) for memory access.
3. Canonical state (`work_plan.md`, `STATE.md`, `TURN.md`) is loaded only for status, not for full content.
4. Archive surfaces (`_archive/*`, `archive/*`) are never loaded in bootstrap.
