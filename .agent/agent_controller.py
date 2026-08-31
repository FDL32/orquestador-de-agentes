# ruff: noqa: S603,S607
"""
Agent Controller v5 - Sistema Multi-Agente
==========================================
Orquestador con:
- Hook System (pre-action, post-tool y stop hooks)
- Native Claude Code hooks (PostToolUse, PreCompact, Stop, SubagentStop)
- Completion Verification antes de review
- Quality Gates extendidos
- Session Recovery
- Project Map y estado del workflow

Uso:
    python .agent/agent_controller.py              # Ver estado y turno actual
    python .agent/agent_controller.py --json       # Output en JSON
    python .agent/agent_controller.py --skip-gates # Saltar Quality Gates
    python .agent/agent_controller.py --archive    # Archivar notificaciones antiguas
    python .agent/agent_controller.py --validate   # Solo validar archivos de estado
    python .agent/agent_controller.py --strict     # Modo estricto (bloquea si falla)
    python .agent/agent_controller.py --bootstrap-ticket # Emitir STATE_CHANGED inicial para el ticket activo
    python .agent/agent_controller.py --project-root /path/to/destino  # Operar sobre workspace externo
"""

# Fix encoding issues on Windows
import codecs
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


if sys.platform == "win32":
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer)
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer)

# Fix imports when run as script (not as package)
# WP-2026-122: project_root is now resolved dynamically via runtime.project_root
_AGENT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT_DERIVED = _AGENT_DIR.parent
for _path in (str(_AGENT_DIR), str(_PROJECT_ROOT_DERIVED)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# WP-2026-122: Import project_root module for dynamic path resolution
# Entry points set AGENT_PROJECT_ROOT env var after parsing --project-root
# Import AFTER sys.path setup to ensure runtime/ is importable
import closure_invariants  # noqa: E402 - sibling module in .agent/
import motor_checkpoint  # noqa: E402 - sibling module in .agent/
import scope_gate  # noqa: E402 - sibling module in .agent/
import state_validation  # noqa: E402 - sibling module in .agent/
from bus.ticket_id import extract_all_ticket_ids  # noqa: E402
from runtime.project_root import (  # noqa: E402
    get_agent_dir,
    get_collab_dir,
    get_context_dir,
    get_runtime_dir,
    is_motor_code_only,
    resolve_project_root,
)


# ============================================================================
# IMPORTS: HOOK SYSTEM, SESSION TRACKER & COMPLETION CHECKER
# ============================================================================
try:
    from hooks import registry as hook_registry
    from hooks.post_tool_hook import post_tool_hook
    from hooks.pre_action_hook import pre_action_hook
    from hooks.stop_hook import stop_hook

    HOOKS_AVAILABLE = True
    hook_registry.register("pre_action", pre_action_hook)
    hook_registry.register("post_tool", post_tool_hook)
    hook_registry.register("stop", stop_hook)
except ImportError:
    HOOKS_AVAILABLE = False
    hook_registry = None

try:
    from session_tracker import (
        clear_session,
        recover_session,
        save_session,
        show_recovery_hint,
    )

    SESSION_TRACKER_AVAILABLE = True
except ImportError:
    SESSION_TRACKER_AVAILABLE = False

try:
    from completion_checker import check_completion, show_completion_report

    COMPLETION_CHECKER_AVAILABLE = True
except ImportError:
    COMPLETION_CHECKER_AVAILABLE = False

try:
    from bus.event_bus import EventBus
    from bus.utils import count_trailing_changes

    BUS_AVAILABLE = True
except ImportError:
    BUS_AVAILABLE = False
    EventBus = None
    count_trailing_changes = None

# WP-2026-146: Import approval system for HUMAN_GATE timeout
try:
    from bus.approval import (
        ApprovalPolicy,
        ApprovalReason,
        ApprovalStatus,
        ApprovalStore,
    )

    APPROVAL_SYSTEM_AVAILABLE = True
except ImportError:
    APPROVAL_SYSTEM_AVAILABLE = False
    ApprovalPolicy = None
    ApprovalReason = None
    ApprovalStatus = None
    ApprovalStore = None

# ============================================================================
# PATH CONFIGURATION - WP-2026-122: Deferred resolution via project_root module
# ============================================================================
# Paths now resolved dynamically via runtime.project_root functions


def _project_root() -> Path:
    return resolve_project_root()


class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __truediv__(self, other):
        return self.resolve() / other

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())

    def __repr__(self) -> str:
        return f"_LazyPath({self.resolve()!r})"


SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = _LazyPath(_project_root)
AGENT_DIR = _LazyPath(get_agent_dir)
COLLAB_DIR = _LazyPath(get_collab_dir)
CONTEXT_DIR = _LazyPath(get_context_dir)

# State files
WORK_PLAN = _LazyPath(lambda: get_collab_dir() / "work_plan.md")
EXEC_LOG = _LazyPath(lambda: get_collab_dir() / "execution_log.md")
REVIEW_QUEUE = _LazyPath(lambda: get_collab_dir() / "review_queue.md")
NOTIFICATIONS = _LazyPath(lambda: get_collab_dir() / "notifications.md")
TURN_FILE = _LazyPath(lambda: get_collab_dir() / "TURN.md")
STATE_FILE = _LazyPath(lambda: get_collab_dir() / "STATE.md")
ARCHIVE_DIR = _LazyPath(lambda: get_collab_dir() / "archive")
AGENTS_CONFIG_PATH = _LazyPath(lambda: get_agent_dir() / "config" / "agents.json")

# Auxiliary state files (cleared on ticket closeout)
_MANAGER_BRIDGE_STATE_PATH = _LazyPath(
    lambda: get_agent_dir() / "runtime" / "manager_bridge_state.json"
)
_SUPERVISOR_STATE_PATH = _LazyPath(
    lambda: get_agent_dir() / "runtime" / "supervisor_state.json"
)

# Archive configuration
MAX_NOTIFICATIONS_SIZE_KB = 50
MAX_NOTIFICATION_ENTRIES = 20

# WP-2026-106 hotfix: HUMAN_GATE escalation threshold. Single source of truth
# is manager_review.max_attempts in agents.json (shared with bus/review_bridge.py).
# Fallback used only if config is missing or unreadable.
HUMAN_GATE_REJECTION_FALLBACK = 5

# WP-2026-146: HUMAN_GATE timeout configuration. Single source of truth is
# manager_review.human_gate_timeout_seconds in agents.json. Fallback used if missing.
# Distinct from manager_review.timeout_seconds (AI subprocess wait, ~180s).
HUMAN_GATE_TIMEOUT_FALLBACK = 86400  # 24 hours

# WP-2026-147: Graph context adapter import (optional)
try:
    from scripts.graph_context import generate_context_for_destination

    GRAPH_CONTEXT_AVAILABLE = True
except ImportError:
    GRAPH_CONTEXT_AVAILABLE = False
    generate_context_for_destination = None

# WP-2026-150: Project scanner import (optional)
try:
    from scripts.project_scanner import (
        generate_report as scanner_generate_report,
        scan_project,
    )

    SCANNER_AVAILABLE = True
except ImportError:
    SCANNER_AVAILABLE = False
    scan_project = None
    scanner_generate_report = None


def get_human_gate_threshold() -> int:
    """Return the consecutive-CHANGES count that escalates a ticket to HUMAN_GATE.

    Reads manager_review.max_attempts from agents.json so both this controller
    and bus/review_bridge.py escalate on the same number. Falls back to
    HUMAN_GATE_REJECTION_FALLBACK if the config is absent or malformed.
    """
    try:
        cfg = json.loads(AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))
        value = int(cfg.get("manager_review", {}).get("max_attempts"))
        return value if value > 0 else HUMAN_GATE_REJECTION_FALLBACK
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return HUMAN_GATE_REJECTION_FALLBACK


def get_human_gate_timeout() -> int:
    """Return the timeout in seconds for HUMAN_GATE approval requests.

    Reads manager_review.human_gate_timeout_seconds from agents.json.
    This is intentionally separate from manager_review.timeout_seconds,
    which controls the AI subprocess wait (~180s). Human gates need hours.
    Falls back to HUMAN_GATE_TIMEOUT_FALLBACK (24h) if absent or malformed.

    Returns:
        Timeout in seconds (positive integer).
    """
    try:
        cfg = json.loads(AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))
        value = int(cfg.get("manager_review", {}).get("human_gate_timeout_seconds"))
        return value if value > 0 else HUMAN_GATE_TIMEOUT_FALLBACK
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return HUMAN_GATE_TIMEOUT_FALLBACK


# Configuracion de comprobaciones
MAX_FILES_CIRCULAR_CHECK = 50

# Estados validos para validacion.
# Canonical source: .agent/state_validation.py (re-exported here).
VALID_PLAN_STATES = state_validation.VALID_PLAN_STATES
VALID_LOG_STATES = state_validation.VALID_LOG_STATES


def _ensure_runtime_dirs() -> None:
    context_dir = get_context_dir()
    archive_dir = get_collab_dir() / "archive"
    context_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)


def _get_event_bus() -> EventBus | None:
    global event_bus
    if not BUS_AVAILABLE:
        return None
    if event_bus is None:
        event_bus = EventBus(get_agent_dir() / "runtime" / "events")
    return event_bus


def _get_approval_store() -> ApprovalStore | None:
    """Get or create the approval store for HUMAN_GATE timeout.

    Before: No approval store existed in agent_controller.
    During: Creates ApprovalStore under runtime_dir with configurable timeout.
    After: Returns configured ApprovalStore or None if approval system unavailable.
    """
    if not APPROVAL_SYSTEM_AVAILABLE:
        return None
    store_path = get_agent_dir() / "runtime" / "approvals" / "store.json"
    timeout_seconds = get_human_gate_timeout()
    policy = ApprovalPolicy(
        policy_name="human_gate",
        timeout_seconds=timeout_seconds,
        auto_resolve=True,
        auto_resolve_status=ApprovalStatus.EXPIRED,
    )
    return ApprovalStore(store_path=store_path, policy=policy)


# Event bus is initialized lazily after the project root is known.
event_bus = None

# Circuit breaker state
CIRCUIT_BREAKER_PATH = _LazyPath(
    lambda: get_agent_dir() / "runtime" / "circuit_breaker.json"
)
BUILDER_LOCK_PATH = _LazyPath(lambda: get_agent_dir() / "runtime" / "builder_lock.txt")

# Scope gate utilities
EXCLUDE_FILES_REL = scope_gate.EXCLUDE_FILES_REL


def _exclude_files() -> set[str]:
    return scope_gate.exclude_files(
        collab_dir=get_collab_dir(),
        agent_dir=get_agent_dir(),
        context_dir=get_context_dir(),
        exclude_files_rel=EXCLUDE_FILES_REL,
    )


def parse_files_likely_touched(
    work_plan_content: str, *, deliverable_type: str | None = None
) -> set[str]:
    dt = (
        deliverable_type
        if deliverable_type is not None
        else _read_deliverable_type(work_plan_content)
    )
    return scope_gate.parse_files_likely_touched(
        work_plan_content,
        project_root=PROJECT_ROOT.resolve(),
        deliverable_type=dt,
    )


def parse_flt_namespaced(work_plan_content: str) -> dict[str, set[str]]:
    """Return FLT paths split by namespace (motor / destino)."""
    da = _read_delivery_authority(work_plan_content)
    dt = _read_deliverable_type(work_plan_content)
    motor = (
        _MOTOR_ROOT.resolve()
        if (_MOTOR_ROOT / ".git").exists()
        else PROJECT_ROOT.resolve()
    )
    return scope_gate.parse_flt_namespaced(
        work_plan_content,
        motor_root=motor,
        project_root=PROJECT_ROOT.resolve(),
        delivery_authority=da,
        deliverable_type=dt,
    )


def get_productive_changed_files(delivery_authority: str) -> set[str] | None:
    """Return changed files from the productive root for the given delivery_authority.

    For repo_motor tickets: returns files changed in motor_root (motor diff).
    For repo_destino tickets: returns files changed in project_root (destino diff).
    """
    if delivery_authority == "repo_motor" and (_MOTOR_ROOT / ".git").exists():
        return scope_gate.get_changed_files(
            project_root=_MOTOR_ROOT.resolve(),
            motor_root=None,
            run_fn=subprocess.run,
        )
    return scope_gate.get_changed_files(
        project_root=PROJECT_ROOT.resolve(),
        motor_root=None,
        run_fn=subprocess.run,
    )


def _git_log_recent_files(git_root: Path, n: int = 10) -> set[str]:
    return scope_gate.git_log_recent_files(git_root, n=n, run_fn=subprocess.run)


def get_changed_files() -> set[str] | None:
    return scope_gate.get_changed_files(
        project_root=PROJECT_ROOT.resolve(),
        motor_root=_MOTOR_ROOT.resolve() if (_MOTOR_ROOT / ".git").exists() else None,
        run_fn=subprocess.run,
    )


def _check_cross_root_contamination(
    delivery_authority: str,
) -> dict[str, set[str]]:
    """Check for productive files in the non-authority root.

    WOT-2026-009c: reciprocal isolation guard (observability layer in validate).
    For repo_motor tickets: inspects repo_destino for productive changes.
    For repo_destino tickets: inspects repo_motor for productive changes.
    Returns {"productive": set[str], "operational": set[str]}.
    """
    if delivery_authority == "repo_motor":
        other_root = PROJECT_ROOT.resolve()
        other_exclude = _exclude_files()
    else:
        if not (_MOTOR_ROOT / ".git").exists():
            return {"productive": set(), "operational": set()}
        other_root = _MOTOR_ROOT.resolve()
        collab = other_root / ".agent" / "collaboration"
        agent_dir = other_root / ".agent"
        context_dir = agent_dir / "context"
        other_exclude = scope_gate.exclude_files(
            collab_dir=collab,
            agent_dir=agent_dir,
            context_dir=context_dir,
        )
    return scope_gate.check_cross_root_contamination(
        other_root=other_root,
        other_exclude=other_exclude,
    )


def check_scope_gate(
    work_plan_content: str, changed_files: set[str] | None, exclude_files: set[str]
) -> dict:
    dt = _read_deliverable_type(work_plan_content)
    return scope_gate.check_scope_gate(
        work_plan_content,
        changed_files,
        exclude_files,
        parse_files_likely_touched_fn=parse_files_likely_touched,
        deliverable_type=dt,
    )


def _load_mark_ready_context() -> tuple[str, str, str]:
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    return plan_content, log_content, get_plan_id(plan_content)


def _record_scope_override(scope_override: str, problem_files: set[str]) -> None:
    return scope_gate.record_scope_override(
        scope_override,
        problem_files,
        update_log_status_fn=update_log_status,
        repo_root=PROJECT_ROOT.resolve(),
    )


def _scope_gate_allows_close(gate_result: dict, scope_override: str | None) -> bool:
    return scope_gate.scope_gate_allows_close(
        gate_result,
        scope_override,
        update_log_status_fn=update_log_status,
        record_scope_override_fn=_record_scope_override,
        print_fn=print,
    )


def _sync_mark_ready_targets(
    plan_id: str, plan_content: str, current_round: int | None = None
) -> None:
    """Emit READY_FOR_REVIEW after mark-ready and refresh projections."""
    log_status_before = get_status(read_file(EXEC_LOG), "**Estado:**")
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine, TicketState

        events = event_bus.read_events(ticket_id=plan_id)
        bus_state = (
            StateMachine.derive_state_from_events([e.to_dict() for e in events])
            if events
            else TicketState.UNKNOWN
        )
        from_state = (
            bus_state.value if bus_state != TicketState.UNKNOWN else log_status_before
        )
    else:
        from_state = log_status_before

    if BUS_AVAILABLE and event_bus:
        latest_state_event = event_bus.latest_event(
            ticket_id=plan_id, event_type="STATE_CHANGED"
        )
        should_emit_ready = (
            not latest_state_event
            or latest_state_event.payload.get("to_state") != "READY_FOR_REVIEW"
            or from_state == "IN_PROGRESS"
        )
        if should_emit_ready:
            event_bus.emit(
                event_type="STATE_CHANGED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload={
                    "from_state": from_state,
                    "to_state": "READY_FOR_REVIEW",
                    "reason": "Builder completed implementation",
                    "source": "mark-ready",
                    **({"round": current_round} if current_round is not None else {}),
                },
            )
        if should_emit_ready:
            bus_from_state = (
                latest_state_event.payload.get("to_state")
                if latest_state_event and latest_state_event.payload
                else log_status_before
            )
            event_bus.emit(
                event_type="STATE_CHANGED",
                ticket_id=plan_id,
                actor="SUPERVISOR",
                payload={
                    "from_state": bus_from_state,
                    "to_state": "READY_FOR_REVIEW",
                    "reason": "Builder completed implementation",
                    "source": "mark-ready",
                    **({"round": current_round} if current_round is not None else {}),
                },
            )

    try:
        from bus.state_machine import TicketState
        from bus.supervisor import SequentialTicketSupervisor

        SequentialTicketSupervisor(
            project_root=PROJECT_ROOT,
            collaboration_dir=get_collab_dir(),
            runtime_dir=get_runtime_dir(),
        )._materialize_ticket_projection(plan_id, TicketState.READY_FOR_REVIEW)
    except Exception:
        try:
            from scripts.state_projection_sync import sync_state_projection

            sync_state_projection(
                runtime_dir=get_runtime_dir() / "events",
                collaboration_dir=get_collab_dir(),
                ticket_id=plan_id,
            )
        except Exception:  # noqa: S110 - fallback sync must not block mark-ready
            pass


# Circuit breaker and checkout utilities


def _read_circuit_breaker() -> dict:
    """Read circuit breaker state from JSON file."""
    if not CIRCUIT_BREAKER_PATH.exists():
        return {
            "state": "CLOSED",
            "failures": 0,
            "last_failure": None,
            "no_progress_count": 0,
        }
    try:
        return json.loads(CIRCUIT_BREAKER_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "state": "CLOSED",
            "failures": 0,
            "last_failure": None,
            "no_progress_count": 0,
        }


def _write_circuit_breaker(state: dict) -> None:
    """Write circuit breaker state to JSON file."""
    CIRCUIT_BREAKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_BREAKER_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _check_circuit_breaker(plan_id: str) -> dict:
    """
    Check circuit breaker state for a ticket.
    Returns dict with 'open', 'reason', 'failures', 'no_progress_count'.
    """
    breaker = _read_circuit_breaker()
    if breaker.get("state") == "OPEN":
        return {
            "open": True,
            "reason": breaker.get("reason", "Circuit breaker triggered"),
            "failures": breaker.get("failures", 0),
            "no_progress_count": breaker.get("no_progress_count", 0),
        }
    return {
        "open": False,
        "reason": None,
        "failures": breaker.get("failures", 0),
        "no_progress_count": breaker.get("no_progress_count", 0),
    }


def _trigger_circuit_breaker(
    reason: str, plan_id: str, is_no_progress: bool = False
) -> None:
    """Trigger circuit breaker to OPEN state."""
    breaker = _read_circuit_breaker()
    breaker["state"] = "OPEN"
    breaker["reason"] = reason
    breaker["last_triggered"] = datetime.now(timezone.utc).isoformat()
    breaker["ticket_id"] = plan_id
    if is_no_progress:
        breaker["no_progress_count"] = breaker.get("no_progress_count", 0) + 1
    else:
        breaker["failures"] = breaker.get("failures", 0) + 1
    _write_circuit_breaker(breaker)


def _reset_circuit_breaker(plan_id: str) -> None:
    """Reset circuit breaker to CLOSED state after successful completion."""
    _write_circuit_breaker(
        {
            "state": "CLOSED",
            "failures": 0,
            "last_failure": None,
            "no_progress_count": 0,
            "last_reset": datetime.now(timezone.utc).isoformat(),
            "last_ticket": plan_id,
        }
    )


def _record_error_for_breaker(plan_id: str, error_msg: str) -> None:
    """Record an error for circuit breaker evaluation."""
    breaker = _read_circuit_breaker()
    breaker["failures"] = breaker.get("failures", 0) + 1
    breaker["last_error"] = error_msg
    breaker["last_error_time"] = datetime.now(timezone.utc).isoformat()

    # Trigger if 3+ consecutive errors
    if breaker["failures"] >= 3:
        _trigger_circuit_breaker(f"Repeated errors: {error_msg[:100]}", plan_id)
    else:
        _write_circuit_breaker(breaker)


def _record_no_progress_for_breaker(plan_id: str) -> None:
    """Record no-progress event for circuit breaker evaluation."""
    breaker = _read_circuit_breaker()
    breaker["no_progress_count"] = breaker.get("no_progress_count", 0) + 1
    breaker["last_no_progress"] = datetime.now(timezone.utc).isoformat()

    # Trigger if 3+ no-progress events
    if breaker["no_progress_count"] >= 3:
        _trigger_circuit_breaker(
            "No progress detected in multiple iterations", plan_id, is_no_progress=True
        )
    else:
        _write_circuit_breaker(breaker)


def _read_builder_lock() -> dict | None:
    """Read builder lock file if it exists."""
    if not BUILDER_LOCK_PATH.exists():
        return None
    try:
        return json.loads(BUILDER_LOCK_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_process_builder_round() -> int | None:
    """Read the Builder round assigned to this shell process, if any."""
    raw = os.environ.get("AGENT_BUILDER_ROUND", "").strip()
    if not raw:
        return None
    try:
        round_num = int(raw)
    except ValueError:
        return None
    return round_num if round_num >= 1 else None


def _ensure_active_builder_round(plan_id: str) -> tuple[bool, int | None, str | None]:
    """Verify that this Builder shell still owns the active round for the ticket.

    Before: Builder may be running in a shell launched for an older round while a
    newer round is already active.
    During: Compares AGENT_BUILDER_TICKET / AGENT_BUILDER_ROUND from the current
    shell against builder_lock.txt, which tracks the active Builder round.
    After: Returns (is_valid, process_round, reason). If no process round is
    available, the check is skipped for backward compatibility.
    """
    process_ticket = os.environ.get("AGENT_BUILDER_TICKET", "").strip()
    process_round = _read_process_builder_round()
    if process_ticket and process_ticket != plan_id:
        return (
            False,
            process_round,
            f"shell ticket {process_ticket} does not match active plan {plan_id}",
        )
    if process_round is None:
        return (True, None, None)

    lock_data = _read_builder_lock()
    if lock_data is None:
        return (
            False,
            process_round,
            "builder_lock.txt missing for a Builder shell with explicit round identity",
        )

    lock_ticket = lock_data.get("ticket_id")
    lock_round = lock_data.get("round")
    if lock_ticket != plan_id:
        return (
            False,
            process_round,
            f"builder_lock ticket {lock_ticket} does not match active plan {plan_id}",
        )
    if lock_round != process_round:
        return (
            False,
            process_round,
            f"stale Builder round {process_round}; active round is {lock_round}",
        )

    return (True, process_round, None)


def _acquire_builder_lock(
    plan_id: str, pid: int, role: str = "BUILDER", backend: str = "unknown"
) -> bool:
    """
    Attempt to acquire builder lock atomically.
    Returns True if lock was acquired, False if another session holds it.
    """
    existing = _read_builder_lock()
    if existing is not None:
        # Check if lock is stale (different ticket or dead process)
        if existing.get("ticket_id") != plan_id:
            # Stale lock from different ticket - override
            lock_data = {
                "pid": pid,
                "ticket_id": plan_id,
                "project_root": str(PROJECT_ROOT),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "role": role,
                "backend": backend,
                "round": 1,
            }
            BUILDER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            BUILDER_LOCK_PATH.write_text(
                json.dumps(lock_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        # Same ticket - check if process is alive (simplified: just allow re-acquisition)
        lock_data = {
            "pid": pid,
            "ticket_id": plan_id,
            "project_root": str(PROJECT_ROOT),
            "started_at": existing.get(
                "started_at", datetime.now(timezone.utc).isoformat()
            ),
            "role": role,
            "backend": backend,
            "round": existing.get("round", 1) + 1,
        }
        BUILDER_LOCK_PATH.write_text(
            json.dumps(lock_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True

    # No existing lock - acquire fresh
    lock_data = {
        "pid": pid,
        "ticket_id": plan_id,
        "project_root": str(PROJECT_ROOT),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "backend": backend,
        "round": 1,
    }
    BUILDER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUILDER_LOCK_PATH.write_text(
        json.dumps(lock_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return True


def _release_builder_lock(plan_id: str, expected_round: int | None = None) -> None:
    """Release builder lock after completion."""
    import contextlib

    existing = _read_builder_lock()
    if (
        existing
        and existing.get("ticket_id") == plan_id
        and (expected_round is None or existing.get("round") == expected_round)
    ):
        with contextlib.suppress(OSError):
            BUILDER_LOCK_PATH.unlink()
    # WP-2026-180: Clean up builder session file on lock release.
    _cleanup_builder_session(plan_id)


_BUILDER_SESSION_PATH = _LazyPath(
    lambda: get_agent_dir() / "runtime" / "builder_session.json"
)


def _cleanup_builder_session(plan_id: str) -> None:
    """Remove builder_session.json if it exists for a given ticket.

    Before: builder_session.json may or may not exist.
    During: Checks if the file exists and matches the given plan_id.
    After: File is removed if it matched or if no plan_id filtering needed.
    """
    import contextlib

    path = _BUILDER_SESSION_PATH.resolve()
    if not path.exists():
        return
    if plan_id:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("ticket_id") != plan_id:
                return  # Belongs to a different ticket; leave it alone
        except (OSError, json.JSONDecodeError):
            pass
    with contextlib.suppress(OSError):
        path.unlink()


def _capture_builder_session(plan_id: str, current_round: int) -> dict | None:
    """Capture the OpenCode session ID from the local SQLite DB.

    Before: The Builder must have been launched with --title '<plan_id>-R<round>'.
    During: Queries the OpenCode SQLite session database for a session matching
            the title, extracts the session ID, and persists it to
            .agent/runtime/builder_session.json.
    After: Returns session info dict on success, None on failure.
           On failure, any stale builder_session.json is NOT removed (deliberate:
           caller decides fallback behaviour).
    """
    import sqlite3

    # Determine OpenCode DB path (platform-specific)
    home_path = Path.home()
    db_candidates = [
        home_path / ".local" / "share" / "opencode" / "opencode.db",
        Path(os.environ.get("LOCALAPPDATA", "")) / "opencode" / "opencode.db",
        Path(os.environ.get("APPDATA", "")) / "opencode" / "opencode.db",
        home_path / ".opencode" / "opencode.db",
    ]

    db_path: Path | None = None
    for candidate in db_candidates:
        if candidate.exists():
            db_path = candidate
            break

    if not db_path:
        print(
            "[WARN] OpenCode DB not found; cannot capture builder session ID",
            flush=True,
        )
        return None

    title = f"{plan_id}-R{current_round}"
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM session WHERE title = ? ORDER BY time_updated DESC LIMIT 1",
            (title,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(
                f"[WARN] No OpenCode session found with title '{title}'",
                flush=True,
            )
            return None

        session_id: str = row[0]
        now_iso = datetime.now(timezone.utc).isoformat()
        session_data = {
            "session_id": session_id,
            "ticket_id": plan_id,
            "started_at": now_iso,
            "round": current_round,
            "title": title,
        }

        # Write to builder_session.json
        session_path = _BUILDER_SESSION_PATH.resolve()
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(
            json.dumps(session_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            f"[OK] Captured OpenCode session {session_id} for '{title}'",
            flush=True,
        )
        return session_data

    except sqlite3.OperationalError as exc:
        # WOT-2026-019d: SEGURO, no tocar. sqlite3.OperationalError no tiene
        # .filename; su mensaje describe el error SQL, no una ruta de filesystem.
        print(
            f"[WARN] OpenCode DB query failed (schema mismatch?): {exc}",
            flush=True,
        )
        return None
    except OSError as exc:
        # WOT-2026-019d: str(exc) de un OSError (p.ej. de session_path.write_text)
        # concatena la ruta absoluta local (con username). Componer el mensaje
        # a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        print(
            f"[WARN] Failed to capture OpenCode session: {detail}",
            flush=True,
        )
        return None
    except Exception as exc:
        print(
            f"[WARN] Failed to capture OpenCode session: {exc}",
            flush=True,
        )
        return None


def _emit_builder_exit(
    plan_id: str,
    exit_reason: str,
    completion_summary: str,
    current_round: int | None = None,
) -> None:
    """Emit BUILDER_EXIT event to the bus - required for ticket closure."""
    if BUS_AVAILABLE and event_bus:
        payload = {
            "exit_reason": exit_reason,
            "completion_summary": completion_summary,
            "source": "mark-ready",
        }
        if current_round is not None:
            payload["round"] = current_round
        event_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id=plan_id,
            actor="BUILDER",
            payload=payload,
        )


def _create_human_gate_approval_request(
    ticket_id: str, timeout_seconds: int | None = None
) -> bool:
    """Create and persist an ApprovalRequest when escalating to HUMAN_GATE.

    Before: HUMAN_GATE escalation had no persistent timeout tracking.
    During: Creates an ApprovalRequest with timeout metadata in the ApprovalStore.
    After: The approval request persists across restarts and can be expired by
           the supervisor's check_and_expire_all() loop.

    Args:
        ticket_id: The ticket ID being escalated to HUMAN_GATE.
        timeout_seconds: Optional timeout override. Defaults to config value.

    Returns:
        True if the approval request was created successfully, False otherwise.
    """
    if not APPROVAL_SYSTEM_AVAILABLE:
        print(
            "[WARN] Approval system unavailable; HUMAN_GATE timeout will not persist.",
            file=sys.stderr,
            flush=True,
        )
        return False

    store = _get_approval_store()
    if store is None:
        print(
            "[WARN] Could not create ApprovalStore; HUMAN_GATE timeout will not persist.",
            file=sys.stderr,
            flush=True,
        )
        return False

    import uuid

    approval_id = f"hg-{uuid.uuid4().hex[:12]}"

    # Create and persist the approval request
    timeout = (
        timeout_seconds if timeout_seconds is not None else get_human_gate_timeout()
    )
    metadata = {
        "escalation_type": "human_gate",
        "timeout_seconds": timeout,
        "created_by": "agent_controller",
        "source": "escalate-human-gate",
    }

    try:
        # Use custom policy if timeout_seconds was provided
        if timeout_seconds is not None:
            custom_policy = ApprovalPolicy(
                policy_name="human_gate_custom",
                timeout_seconds=timeout_seconds,
                auto_resolve=True,
                auto_resolve_status=ApprovalStatus.EXPIRED,
            )
            store.create_request(
                approval_id=approval_id,
                ticket_id=ticket_id,
                metadata=metadata,
                policy=custom_policy,
            )
        else:
            store.create_request(
                approval_id=approval_id,
                ticket_id=ticket_id,
                metadata=metadata,
            )
        print(
            f"[OK] Created HUMAN_GATE approval request {approval_id} for {ticket_id} "
            f"(timeout={timeout}s).",
            flush=True,
        )
        return True
    except OSError as exc:
        # WOT-2026-019d: store.create_request persiste a archivo (ApprovalStore
        # save/_write_store); un OSError real trae .filename absoluto. Componer
        # el mensaje a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        print(
            f"[ERROR] Failed to create HUMAN_GATE approval request: {detail}",
            file=sys.stderr,
            flush=True,
        )
        return False
    except Exception as exc:
        print(
            f"[ERROR] Failed to create HUMAN_GATE approval request: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False


def _auto_archive_closed_artifacts() -> None:
    """Auto-archive closed PLAN/AUDIT artifacts during mark-ready.

    Before: Requires COLLAB_DIR to exist with potential closed PLAN/AUDIT files.
    During: Imports and calls archive_collaboration_artifacts.py as a library function.
    After: Closed PLAN/AUDIT files are moved to _archive/plan_audit/ (idempotent, silent on no-op).
    """
    try:
        # Import the archive script as a module
        import importlib.util

        # Script lives in the motor, not in the workspace (Model B)
        archive_spec = importlib.util.spec_from_file_location(
            "archive_collaboration_artifacts",
            _MOTOR_ROOT / "scripts" / "archive_collaboration_artifacts.py",
        )
        if archive_spec and archive_spec.loader:
            archive_mod = importlib.util.module_from_spec(archive_spec)
            archive_spec.loader.exec_module(archive_mod)

            # Call the archive function (idempotent, no-op if nothing to archive)
            archive_mod.archive_collaboration_artifacts(
                collaboration_dir=COLLAB_DIR,
                dry_run=False,
            )
    except OSError as exc:
        # WOT-2026-019d: archive_collaboration_artifacts mueve/renombra archivos
        # bajo COLLAB_DIR (ruta absoluta); un OSError real trae .filename. Componer
        # el mensaje a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        print(f"[WARN] Auto-archive failed: {detail}")
    except Exception as exc:
        # Silent fail with debug logging - archiving is best-effort, not critical path
        print(f"[WARN] Auto-archive failed: {exc}")


def _check_mark_ready_archive_rename() -> dict | None:
    """Detect an uncommitted archival rename left by mark-ready's auto-archive.

    WOT-2026-011h. Before: ``_auto_archive_closed_artifacts()`` has just run and
    may have moved closed STRATEGY_/AUDIT_/PLAN_ artifacts into _archive/plan_audit/
    without committing, leaving the ``D old + ?? new`` limbo. During: reuse the
    canonical 011a/010u detector ``check_archive_rename_complete`` against the root
    whose git tree tracks the collaboration artifacts (PROJECT_ROOT). After: return
    None when clean (no false positive on an unrelated dirty file), or a dict with
    the stable reason ``archive_rename_uncommitted`` and the exact reconcile command
    when the limbo is present. Fail closed: if the detector cannot run, return a
    block dict rather than silently passing (guard parity with pre_handoff_guard).
    """
    project_root = Path(str(PROJECT_ROOT))
    if not (project_root / ".git").exists():
        # No git tree tracking the artifacts here: nothing this guard can assert.
        return None
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "delivery_hygiene_check",
            _MOTOR_ROOT / "scripts" / "delivery_hygiene_check.py",
        )
        if not (spec and spec.loader):
            return {
                "status": "blocked",
                "reason": "archive_rename_guard_error",
                "details": [
                    "No se pudo cargar delivery_hygiene_check para verificar el "
                    "archivado de mark-ready (WOT-2026-011h, fail-closed)."
                ],
            }
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rename_result = module.check_archive_rename_complete(project_root)
    except OSError as exc:
        # WOT-2026-019d: check_archive_rename_complete inspecciona el arbol de
        # archivos bajo project_root (ruta absoluta); un OSError real trae
        # .filename. Componer el mensaje a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        return {
            "status": "blocked",
            "reason": "archive_rename_guard_error",
            "details": [
                f"check_archive_rename_complete no pudo ejecutarse: {detail}. "
                "Barrera fail-closed (WOT-2026-011h)."
            ],
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "archive_rename_guard_error",
            "details": [
                f"check_archive_rename_complete no pudo ejecutarse: {exc}. "
                "Barrera fail-closed (WOT-2026-011h)."
            ],
        }
    if rename_result.passed:
        return None
    return {
        "status": "blocked",
        "reason": "archive_rename_uncommitted",
        "details": list(rename_result.details) or [rename_result.message],
    }


# Utility functions
def read_file(path: Path) -> str:
    """Lee un archivo si existe, retorna string vacio si no."""
    if not path.exists():
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_file(path: Path, content: str) -> None:
    """Escribe contenido a un archivo, creando directorios si es necesario."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# Parsing helpers: canonical source .agent/state_validation.py
# (re-exported here for the many internal callers and test imports).
get_status = state_validation.get_status
get_plan_id = state_validation.get_plan_id
get_plan_type = state_validation.get_plan_type
# WOT-2026-010f: single source of truth for invalid plan/ticket ids.
is_invalid_plan_id = state_validation.is_invalid_plan_id


def check_git_status() -> bool | None:
    """Verifica si el repositorio esta limpio."""
    if not (PROJECT_ROOT / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        return not result.stdout.strip()
    except FileNotFoundError:
        return None


extract_status_emoji = state_validation.extract_status_emoji


_VALID_DELIVERABLE_TYPES = {"code", "documentation", "research", "analysis", "mixed"}
_DELIVERABLE_TYPE_RE = re.compile(
    r"^\s*-\s*\*\*deliverable_type:\*\*\s*(\S+)",
    re.IGNORECASE | re.MULTILINE,
)


def _check_deliverable_type(content: str) -> list[str]:
    """Check deliverable_type field in work_plan.md content.

    Before: Requires work_plan.md content as string.
    During: Searches for deliverable_type field using regex, validates against allowed values.
    After: Returns list of warning strings (empty if valid). Never returns errors (V1 informational).
    """
    match = _DELIVERABLE_TYPE_RE.search(content)
    if not match:
        return [
            "work_plan.md missing deliverable_type field. "
            "Add one of: code, documentation, research, analysis, mixed."
        ]
    value = match.group(1).strip().lower()
    if "+" in value:
        return [
            f"work_plan.md deliverable_type='{value}' uses compound syntax. "
            "Use 'mixed' instead of 'code+documentation' etc."
        ]
    if value not in _VALID_DELIVERABLE_TYPES:
        return [
            f"work_plan.md has unknown deliverable_type '{value}'. "
            f"Expected one of: {sorted(_VALID_DELIVERABLE_TYPES)}"
        ]
    return _check_deliverable_type_file_congruence(content, value)


# Code-deliverable extensions: a doc-type ticket that declares one of these as a
# Builder deliverable is likely mislabeled (or the file is a source to read, not
# produce -- which belongs under '## Read/inspect only', not Files Likely Touched).
_CODE_DELIVERABLE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx")
_DOC_DELIVERABLE_TYPES_CONGRUENCE = frozenset({"documentation", "research", "analysis"})


def _check_deliverable_type_file_congruence(content: str, value: str) -> list[str]:
    """Warn (never error) when a doc-type ticket lists a code file as deliverable.

    Conservative single-direction check: only flags ``documentation`` /
    ``research`` / ``analysis`` tickets whose Files Likely Touched (or Builder
    section) names a code deliverable. It does NOT flag ``code``/``mixed`` with
    no code file (legit for config/scaffolding tickets), and it ignores
    ``## Read/inspect only`` sources by construction (``files_likely_touched_tokens``
    never reads them). Informational only -- does not block ``--validate``.
    """
    if value not in _DOC_DELIVERABLE_TYPES_CONGRUENCE:
        return []
    tokens = scope_gate.files_likely_touched_tokens(content, deliverable_type=value)
    code_deliverables = sorted(
        {t for t in tokens if t.lower().endswith(_CODE_DELIVERABLE_SUFFIXES)}
    )
    if not code_deliverables:
        return []
    return [
        f"work_plan.md deliverable_type='{value}' but Files Likely Touched lists "
        f"code deliverable(s): {code_deliverables}. If these are sources to read "
        "(not produce), move them under '## Read/inspect only'; if the ticket "
        "actually produces code, use deliverable_type 'code' or 'mixed'."
    ]


def _read_deliverable_type(content: str, default: str = "code") -> str:
    """Read normalized deliverable_type from work_plan.md content."""
    match = _DELIVERABLE_TYPE_RE.search(content or "")
    if not match:
        return default
    value = match.group(1).strip().lower()
    if "+" in value:
        return "mixed"
    if value not in _VALID_DELIVERABLE_TYPES:
        return default
    return value


_VALID_DELIVERY_AUTHORITIES = frozenset({"repo_motor", "repo_destino"})
_DELIVERY_AUTHORITY_RE = re.compile(
    r"(?:delivery_authority|repo\s+de\s+autoridad)\s*:?\**\s*"
    r"(`?)(repo_motor|repo_destino)\1",
    re.IGNORECASE,
)


def _read_delivery_authority(content: str, default: str = "repo_motor") -> str:
    """Read the repo that owns code/mixed delivery evidence.

    Before: work_plan.md may omit the field for legacy tickets.
    During: Accepts either ``delivery_authority: repo_destino`` or the
        Spanish contract line ``Repo de autoridad: repo_destino``.
    After: Returns repo_motor by default to preserve the existing M3 behavior.
    """
    match = _DELIVERY_AUTHORITY_RE.search(content or "")
    if not match:
        return default
    value = match.group(2).strip().lower()
    if value not in _VALID_DELIVERY_AUTHORITIES:
        return default
    return value


def _resolve_checkpoint_root(plan_content: str, deliverable_type: str) -> Path:
    """Resolve the git repo that owns checkpoint M3 for code/mixed tickets."""
    project_root = PROJECT_ROOT.resolve()
    motor_root = _MOTOR_ROOT.resolve()
    if deliverable_type in {"documentation", "research", "analysis"}:
        return project_root
    if (
        _read_delivery_authority(plan_content) == "repo_destino"
        and (project_root / ".git").exists()
    ):
        return project_root
    if motor_root != project_root and (motor_root / ".git").exists():
        return motor_root
    return project_root


# Keywords that indicate a generic/checkpoint commit (not a meaningful closeout)
_CHECKPOINT_KEYWORDS = frozenset({"checkpoint", "pre-handoff", "wip", "interim"})


def _validate_closeout_commit_message(msg: str, active_id: str) -> tuple[bool, str]:
    """Validate that a commit message is appropriate for ticket closeout.

    Before:
        - msg is a git commit message string.
        - active_id is the active ticket ID (e.g., WT-2026-188).

    During:
        - Checks for checkpoint keywords that indicate a generic commit.
        - Extracts all ticket IDs (WT-XXXX / WP-XXXX) from the message.
        - Validates that the active ticket ID is referenced.

    After:
        - Returns (True, "") if the message is valid for closeout.
        - Returns (False, reason_string) if invalid.

    Rules:
        1. Generic checkpoint commits (containing 'checkpoint', 'pre-handoff',
           'wip', 'interim') are rejected regardless of ticket ID.
        2. Commits without any ticket ID are rejected.
        3. Commits referencing a different ticket ID than active_id are rejected.
        4. Commits with active_id and meaningful content are accepted.
    """
    if not msg or not active_id:
        return False, "Empty message or ticket ID"

    msg_lower = msg.lower()
    # Check for checkpoint keywords first (generic commits are always rejected)
    for keyword in _CHECKPOINT_KEYWORDS:
        if keyword in msg_lower:
            return (
                False,
                f"Commit appears to be a '{keyword}' commit, "
                f"not a meaningful closeout message",
            )

    # Use the canonical ticket-id parser so suffixes like WT-2026-248a are
    # preserved consistently across bus, closeout, and manager validation.
    ticket_ids = extract_all_ticket_ids(msg)

    if not ticket_ids:
        return False, "Commit message does not reference any ticket ID"

    if active_id not in ticket_ids:
        found = ", ".join(ticket_ids)
        return (
            False,
            f"Commit references [{found}] but active ticket is {active_id}",
        )

    return True, ""


def _check_last_commit(project_root: Path, active_id: str) -> tuple[bool, str]:
    """Get the last commit message and validate it for closeout.

    Before:
        - project_root must be a git repository with at least one commit.
        - active_id is the active ticket ID.

    During:
        - Runs 'git log -1 --format=%s' to get the latest commit message.
        - Delegates to _validate_closeout_commit_message() for validation.

    After:
        - Returns (True, "") if valid for closeout.
        - Returns (False, reason_string) if invalid or git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if result.returncode != 0:
            return False, f"Failed to get last commit: {result.stderr.strip()}"

        msg = result.stdout.strip()
        if not msg:
            return False, "No commit message found"

        return _validate_closeout_commit_message(msg, active_id)
    except FileNotFoundError:
        return False, "Git not available"


def _resolve_closeout_commit_root(
    deliverable_type: str, plan_content: str | None = None
) -> Path:
    """Resolve which git repo owns closeout commit validation.

    Before:
        - deliverable_type is normalized via _read_deliverable_type().

    During:
        - In motor/destino topology, code and mixed tickets validate against
          the declared delivery authority. Legacy plans default to repo_motor.
        - Documentation/research/analysis keep using PROJECT_ROOT if they ever
          opt into commit validation in the future.

    After:
        - Returns the Path that should be used as cwd for _check_last_commit().
    """
    project_root = PROJECT_ROOT.resolve()
    motor_root = _MOTOR_ROOT.resolve()

    if plan_content is not None:
        return _resolve_checkpoint_root(plan_content, deliverable_type)

    if deliverable_type in {"documentation", "research", "analysis"}:
        return project_root

    if motor_root != project_root and (motor_root / ".git").exists():
        return motor_root

    return project_root


def _clear_auxiliary_states(ticket_id: str) -> None:
    """Clear auxiliary state files after ticket closeout.

    Before:
        - manager_bridge_state.json and/or supervisor_state.json may exist
          with stale cursors from the current or a previous ticket.

    During:
        - Unlinks each file if it exists. Does NOT touch other runtime state.
        - Idempotent: safe to call even if files don't exist.

    After:
        - Both auxiliary state files are removed (if they existed).
        - The next supervisor/bridge restart starts fresh.
    """
    import contextlib

    for path, name in [
        (_MANAGER_BRIDGE_STATE_PATH.resolve(), "manager_bridge_state.json"),
        (_SUPERVISOR_STATE_PATH.resolve(), "supervisor_state.json"),
    ]:
        if path.exists():
            with contextlib.suppress(OSError):
                path.unlink()
                print(f"[OK] Cleared auxiliary state: {name}")


def _run_git_diff_cmd(args: list[str], cwd: Path | None = None) -> set[str]:
    """Run a git diff/log command and return the set of file paths.

    Args:
        args: Command list starting with "git".
        cwd: Directory to run git from. Defaults to PROJECT_ROOT.

    Returns:
        Set of normalized file paths (forward slashes). Empty on error.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd or PROJECT_ROOT,
            timeout=30,
        )
        if result.returncode == 0:
            return {
                line.strip().replace("\\", "/")
                for line in result.stdout.strip().split("\n")
                if line.strip()
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return set()


# Motor root: directory containing this controller file (orquestador_de_agentes/)
_MOTOR_ROOT: Path = Path(__file__).resolve().parent.parent


def _flt_all_gitignored(plan_content: str) -> bool:
    """Check if all Files Likely Touched are gitignored.

    Returns True when there is at least one FLT entry and every entry is
    gitignored (``git check-ignore`` returns 0). This lets code tickets
    whose deliverable lives entirely in a gitignored surface (e.g.
    ``data/``) close without ``--allow-empty`` when a deterministic gate
    verifies the fix (WOT-2026-019g).
    """
    try:
        likely_files = parse_files_likely_touched(plan_content)
    except Exception:
        return False
    if not likely_files:
        return False
    for f in likely_files:
        path = Path(f)
        try:
            rel = path.relative_to(_MOTOR_ROOT) if path.is_absolute() else path
        except ValueError:
            rel = path
        try:
            result = subprocess.run(
                ["git", "check-ignore", str(rel)],
                capture_output=True,
                text=True,
                cwd=str(_MOTOR_ROOT),
                timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
    return True


def _collect_git_diff_files() -> set[str]:
    """Collect files from git diff (unstaged + staged + last commit).

    Delegates to bus.evidence.resolve_evidence for unified evidence handling.
    """
    try:
        from bus.evidence import resolve_evidence

        evidence = resolve_evidence(_MOTOR_ROOT, PROJECT_ROOT)
        return set(evidence["all_files"])
    except Exception:
        return set()


def _check_log_has_evidence() -> bool:
    """Check execution_log.md for non-boilerplate evidence.

    Before:
        - EXEC_LOG must be accessible.

    During:
        - Reads execution_log.md and filters out boilerplate lines.

    After:
        - Returns True if non-boilerplate evidence exists.
        - Returns False if log is empty, missing, or has only boilerplate.
        - Never raises: read errors are caught and return False.
    """
    try:
        log_content = read_file(EXEC_LOG)
        if not log_content:
            return False
        lines = log_content.strip().split("\n")
        evidence_lines = [
            line.strip()
            for line in lines
            if line.strip()
            and "Marked ready by Builder" not in line
            and not line.strip().startswith("#")
            and not line.strip().startswith("**")
            and not line.strip().startswith("---")
            and not line.strip().startswith("[")
        ]
        return bool(evidence_lines)
    except Exception:
        return False


def _check_git_log_has_plan_id(plan_id: str) -> bool:
    """WT-2026-203: Check if the plan_id appears in the last 20 git commit subjects.

    Before:
        - plan_id must be a non-empty string.
        - git must be available (best-effort if not).

    During:
        - Runs git log --oneline -20 in both PROJECT_ROOT and _MOTOR_ROOT.
        - Searches for plan_id in each commit line.

    After:
        - Returns True if plan_id found in any commit subject in either repo.
        - Returns False if not found, git unavailable, or any error.
        - Never raises: all exceptions are caught and return False.
    """
    for root in {PROJECT_ROOT, _MOTOR_ROOT}:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                capture_output=True,
                text=True,
                cwd=root,
                timeout=30,
            )
            if result.returncode == 0 and plan_id in result.stdout:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):  # noqa: PERF203 - iterates at most 2 roots
            pass
    return False


def _check_log_has_quality_gate_evidence(deliverable_type: str = "code") -> bool:
    """WT-2026-203: Check execution_log.md for explicit quality gate evidence.

    Before:
        - EXEC_LOG must be accessible.

    During:
        - Reads execution_log.md and searches for deliverable-type-specific
          quality gate markers.
        - This is stricter than the general non-boilerplate check.

    After:
        - Returns True if at least one quality gate evidence line found.
        - Returns False if log is empty, missing, or no evidence found.
        - Never raises: read errors are caught and return False.
    """
    try:
        log_content = read_file(EXEC_LOG)
        if not log_content:
            return False
        lines = log_content.strip().split("\n")
        quality_markers = {
            "code": ("pytest", "ruff", "passed", "all checks passed"),
            "mixed": ("pytest", "ruff", "passed", "all checks passed"),
            "documentation": (
                "validate",
                "check-deliverables",
                "deliverable",
                "report",
                "success",
                "0 warnings",
                "0 errores",
                "0 errors",
                "passed",
            ),
            "research": (
                "validate",
                "check-deliverables",
                "deliverable",
                "report",
                "success",
                "0 warnings",
                "0 errores",
                "0 errors",
                "passed",
            ),
            "analysis": (
                "validate",
                "check-deliverables",
                "deliverable",
                "report",
                "success",
                "0 warnings",
                "0 errores",
                "0 errors",
                "passed",
            ),
        }
        markers = quality_markers.get(deliverable_type, quality_markers["code"])
        for line in lines:
            stripped = line.strip().lower()
            if deliverable_type in {"documentation", "research", "analysis"}:
                artifact_markers = (
                    "check-deliverables",
                    "deliverable",
                    "reporte",
                    "report",
                    ".agent/runtime/compare",
                    "runtime/compare",
                )
                if "pendiente" in stripped or "pending" in stripped:
                    continue
                if not any(marker in stripped for marker in artifact_markers):
                    continue
            if any(kw in stripped for kw in markers):
                return True
        return False
    except Exception:
        return False


def _check_declared_deliverables_exist(plan_content: str) -> list[str]:
    """Return missing declared deliverables for non-code tickets."""
    try:
        from scripts.check_deliverables_exist import extract_paths_from_work_plan

        # WOT-2026-019d: SEGURO, no tocar. extract_paths_from_work_plan es
        # parsing puro de texto (sin I/O); el unico riesgo es el import.
        declared_paths = extract_paths_from_work_plan(plan_content)
    except Exception as exc:
        return [f"Could not inspect declared deliverables: {exc}"]

    if not declared_paths:
        return []

    missing = [path for path in sorted(declared_paths) if not path.exists()]
    if not missing:
        return []
    return [
        "Missing declared deliverables: " + ", ".join(str(path) for path in missing)
    ]


def _check_implementation_evidence(plan_id: str) -> list[str]:  # noqa: C901
    """WP-2026-188 Phase 4 / WT-2026-203: Check implementation evidence before --mark-ready.

    Before:
        - plan_id must be valid (non-empty string).
        - WORK_PLAN and EXEC_LOG must be accessible.
        - git must be available (best-effort if not).

    During:
        - Checks git diff (unstaged, staged, last commit) for files outside
          .agent/collaboration/.
        - Checks execution_log.md for non-boilerplate evidence.
        - Best-effort: checks if Files Likely Touched appear in git changes.
        - WT-2026-203: Checks git log --oneline -20 for plan_id.
        - WT-2026-203: Checks execution_log.md for explicit quality gate markers.
        - NOT bypassable via --force or --scope-override: the gate is unconditional.

    After:
        - Returns list of error strings (empty = all checks pass).
        - Never raises: all exceptions are caught and reported as strings.
    """
    errors: list[str] = []
    all_files = set()
    has_commit = False
    plan_content = read_file(WORK_PLAN)
    deliverable_type = _read_deliverable_type(plan_content)
    non_code_ticket = deliverable_type in {"documentation", "research", "analysis"}
    flt_gitignored = not non_code_ticket and _flt_all_gitignored(plan_content)

    try:
        from bus.evidence import resolve_evidence

        evidence = resolve_evidence(_MOTOR_ROOT, PROJECT_ROOT, plan_id)
        all_files = set(evidence["all_files"])
        has_commit = evidence["has_ticket_commit"]

        if all_files:
            if (
                evidence["is_collaboration_only"]
                and not non_code_ticket
                and not flt_gitignored
            ):
                errors.append(
                    "Collaboration-only evidence: all git changes are collaboration "
                    f"artifacts ({len(all_files)} files). No productive code changes "
                    "detected in motor or destination. Run --pre-handoff first, "
                    "then produce real implementation changes."
                )
            elif (
                evidence["is_docs_only"] and not non_code_ticket and not flt_gitignored
            ):
                errors.append(
                    "Docs-only evidence: all git changes are documentation artifacts "
                    f"({len(all_files)} files). No productive implementation files "
                    "detected. Manager would reject this review (see seq 602/606/617)."
                )

        if (
            not evidence["has_productive_evidence"]
            and not non_code_ticket
            and not flt_gitignored
            and not evidence["is_docs_only"]
            and not evidence["is_collaboration_only"]
        ):
            errors.append(
                "No implementation evidence: git diff shows no files changed "
                "outside .agent/collaboration/"
            )
    # WOT-2026-019d: SEGURO, no tocar. resolve_evidence solo ejecuta git via
    # subprocess con manejo interno de OSError; no hace I/O directo propio.
    except Exception as exc:
        errors.append(f"Git check error (non-blocking): {exc}")

    # 2. Check execution_log.md for non-boilerplate evidence
    has_evidence = _check_log_has_evidence()
    if not has_evidence:
        errors.append(
            "No implementation evidence in execution_log.md (only boilerplate content)"
        )

    if non_code_ticket:
        errors.extend(_check_declared_deliverables_exist(plan_content))
        has_qg_evidence = _check_log_has_quality_gate_evidence(deliverable_type)
        if not has_qg_evidence:
            errors.append(
                "No documentation/research quality gate evidence in execution_log.md: "
                "expected validate/check-deliverables/report evidence."
            )
        return errors

    # 3. Best-effort: check Files Likely Touched
    if not flt_gitignored:
        try:
            if plan_content:
                likely_files = parse_files_likely_touched(plan_content)
                if likely_files and all_files:
                    likely_basenames = {Path(f).name for f in likely_files}
                    matched = any(
                        Path(f).name in likely_basenames or f in likely_files
                        for f in all_files
                    )
                    if not matched:
                        errors.append(
                            "No Files Likely Touched match git changes (best-effort)"
                        )
        except Exception:  # noqa: S110 - best-effort check, silent on parse failure
            pass

    # 4. WT-2026-203: Check git log --oneline -20 contains plan_id
    # has_commit already computed via resolve_evidence above
    if not has_commit and not all_files:
        # Fallback just in case resolve_evidence failed but we want to check
        has_commit = _check_git_log_has_plan_id(plan_id)

    if not has_commit:
        errors.append(
            f"No commit evidence: git log --oneline -20 does not contain '{plan_id}'"
        )

    # 5. WT-2026-203: Check execution_log.md for explicit quality gate evidence
    has_qg_evidence = _check_log_has_quality_gate_evidence(deliverable_type)
    if not has_qg_evidence:
        errors.append(
            "No quality gate evidence in execution_log.md: expected at least "
            "one line with 'pytest', 'ruff', 'passed', or 'All checks passed'"
        )

    return errors


# ── State-file validation ────────────────────────────────────────────────
# Pure content->errors logic lives in .agent/state_validation.py (monolith
# decomposition). These wrappers read the files via the module-global
# read_file / lazy paths, which remain the seam that tests monkeypatch.


def _validate_work_plan() -> list[str]:
    """Validate work_plan.md file."""
    return state_validation.validate_work_plan_content(read_file(WORK_PLAN))


def _validate_execution_log() -> list[str]:
    """Validate execution_log.md file."""
    return state_validation.validate_execution_log_content(read_file(EXEC_LOG))


def _validate_turn_file() -> list[str]:
    """Validate TURN.md file."""
    return state_validation.validate_turn_content(read_file(TURN_FILE))


def _validate_notifications() -> list[str]:
    """Validate notifications.md file."""
    return state_validation.validate_notifications_content(read_file(NOTIFICATIONS))


def _validate_cross_file_consistency() -> list[str]:
    """Validate consistency across files."""
    return state_validation.validate_cross_file_consistency(
        read_file(WORK_PLAN), read_file(EXEC_LOG)
    )


def _validate_host_project_prefix() -> list[str]:
    """Validate that host-project destinations have 'Ticket prefix:' in PROJECT.md.

    Before: Requires PROJECT.md to exist at project root; agents.json to be readable.
    During: Checks if active_profile is 'host-project' and if PROJECT.md has 'Ticket prefix:'.
    After: Returns list of warnings (empty if validation passes).

    Returns:
        List of warning strings (empty if no issues).
    """
    warnings = []
    agents_config = AGENTS_CONFIG_PATH
    if not agents_config.exists():
        return warnings

    try:
        config_data = json.loads(agents_config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return warnings

    active_profile = config_data.get("active_profile", "")
    if active_profile != "host-project":
        return warnings

    # Only check for host-project profile
    project_md = PROJECT_ROOT / "PROJECT.md"
    if not project_md.exists():
        warnings.append(
            "[WARN] host-project destination lacks PROJECT.md. "
            "Add 'Ticket prefix: XXX' to declare local ticket namespace."
        )
        return warnings

    content = project_md.read_text(encoding="utf-8")
    if "Ticket prefix:" not in content:
        warnings.append(
            "[WARN] host-project destination lacks 'Ticket prefix:' in PROJECT.md. "
            "Add 'Ticket prefix: XXX' to declare local ticket namespace (XXX-YYYY-NNN)."
        )

    return warnings


def _validate_git_presence() -> list[str]:
    """Warn when the workspace is not a git repository.

    The motor evidence chain (implementation evidence, scope gate, M3
    checkpoints, prepush) depends on git probes; without a repository every
    Builder handoff dies with implementation_evidence_failed. Surfacing it
    in --validate makes the root cause visible at bootstrap instead of at
    handoff time (found live in the Crear_Texto_LLM integration audit).
    """
    if (Path(str(PROJECT_ROOT)) / ".git").exists():
        return []
    return [
        "[WARN] workspace is NOT a git repository - the evidence chain "
        "(implementation evidence, scope gate, checkpoints) cannot operate "
        "and Builder handoffs will fail with implementation_evidence_failed. "
        "Fix: git init + initial commit with a security-reviewed .gitignore."
    ]


def _validate_contract_gap_coherence(plan_content: str) -> list[str]:  # noqa: C901
    """WOT-2026-007f: Validate CONTRACT_GAP event ↔ CG-*.md file coherence.

    Before:
        - plan_content is the content of work_plan.md (may be empty).
        - BUS_AVAILABLE controls whether the event bus can be queried.
        - The agent dir is resolved via get_agent_dir().

    During:
        - Extracts the active ticket_id from plan_content.
        - Reads CONTRACT_GAP events from the bus for that ticket.
        - Scans contract_gaps/ directory for CG-<ticket_id>.md files.
        - Compares the two surfaces for coherence.

    After:
        - Returns [] if both surfaces agree (both present or both absent).
        - Returns an error string if event present without CG file, or CG file
          present without event (incoherent projection).
        - Returns [] if ticket_id cannot be determined (no active ticket).
        - Never raises; all exceptions are caught and reported as errors.
    """
    errors: list[str] = []

    # Skip if bus is unavailable
    if not BUS_AVAILABLE:
        return errors

    # Determine active ticket_id
    ticket_id = get_plan_id(plan_content).strip()
    if is_invalid_plan_id(ticket_id):
        return errors

    # Check bus for CONTRACT_GAP events
    bus = _get_event_bus()
    if bus is None:
        return errors

    try:
        contract_gap_events = bus.read_events(
            ticket_id=ticket_id, event_type="CONTRACT_GAP"
        )
        # Guard: read_events must return a list (not a mock or unexpected type).
        # If the bus is mocked in tests or returns an unexpected type, skip.
        if not isinstance(contract_gap_events, list):
            return errors
        has_bus_event = bool(contract_gap_events)
    except OSError as exc:
        # WOT-2026-019d: bus.read_events -> _read_raw_events hace
        # self.events_path.read_text; un OSError real trae .filename absoluto.
        # Componer el mensaje a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        errors.append(f"CONTRACT_GAP coherence: error reading bus events: {detail}")
        return errors
    except Exception as exc:
        errors.append(f"CONTRACT_GAP coherence: error reading bus events: {exc}")
        return errors

    # WOT-2026-007f review: emit_contract_gap enforces a canonical cg_file_path,
    # but legacy or tampered events may carry a non-canonical path. Verify the
    # stored payload path of every event matches contract_gaps/CG-<ticket_id>.md.
    canonical_cg_path = f"contract_gaps/CG-{ticket_id}.md"
    for event in contract_gap_events:
        stored_path = str(event.payload.get("cg_file_path", "")).replace("\\", "/")
        if stored_path != canonical_cg_path:
            errors.append(
                f"CONTRACT_GAP path incoherence for {ticket_id}: event payload "
                f"cg_file_path='{stored_path}' != canonical '{canonical_cg_path}'. "
                "Re-emit the event with the canonical relative path."
            )

    # Check contract_gaps/ directory for CG-<ticket_id>.md
    contract_gaps_dir = get_agent_dir() / "planning" / "contract_gaps"
    cg_pattern = f"CG-{ticket_id}.md"
    try:
        has_cg_file = (contract_gaps_dir / cg_pattern).exists()
    except OSError as exc:
        # WOT-2026-019d: Path.exists() re-lanza OSError (con .filename poblado)
        # cuando errno no esta en la lista de errores ignorados de pathlib
        # (p. ej. EACCES). Componer el mensaje a mano sin exponer la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        errors.append(
            f"CONTRACT_GAP coherence: error scanning contract_gaps/: {detail}"
        )
        return errors

    # Coherence check: both must agree
    if has_bus_event and not has_cg_file:
        errors.append(
            f"CONTRACT_GAP incoherence: bus has CONTRACT_GAP event for {ticket_id} "
            f"but {cg_pattern} not found in contract_gaps/. "
            "Create the CG file or remove the stale bus event."
        )
    elif has_cg_file and not has_bus_event:
        errors.append(
            f"CONTRACT_GAP incoherence: {cg_pattern} exists in contract_gaps/ "
            f"but no CONTRACT_GAP event found in bus for {ticket_id}. "
            "Emit the CONTRACT_GAP event or remove the stale CG file."
        )

    return errors


def validate_state_files() -> dict[str, list[str]]:
    """Valida el formato y consistencia cruzada de los archivos de estado."""
    return {
        "work_plan.md": _validate_work_plan(),
        "execution_log.md": _validate_execution_log(),
        "notifications.md": _validate_notifications(),
        "consistency": _validate_cross_file_consistency(),
        "TURN.md": _validate_turn_file(),
        "host_project_prefix": _validate_host_project_prefix(),
        "git_presence": _validate_git_presence(),
    }


def fix_corrupted_notifications() -> bool:
    """Intenta reparar notifications.md si esta corrupto."""
    content = read_file(NOTIFICATIONS)
    if not content:
        return False
    original = content
    content = re.sub(r"</thinking>\s*", "", content)
    content = re.sub(r"\n{4,}", "\n\n---\n\n", content)
    if content != original:
        write_file(NOTIFICATIONS, content)
        return True
    return False


def archive_old_notifications() -> str | None:
    """Archiva notificaciones antiguas si el archivo es muy grande."""
    content = read_file(NOTIFICATIONS)
    if not content:
        return None

    file_size_kb = len(content.encode("utf-8")) / 1024
    entry_count = len([e for e in content.split("---") if e.strip()])

    if (
        file_size_kb < MAX_NOTIFICATIONS_SIZE_KB
        and entry_count <= MAX_NOTIFICATION_ENTRIES
    ):
        return None

    parts = content.split("---")
    entries = [p.strip() for p in parts if p.strip()]

    if len(entries) <= MAX_NOTIFICATION_ENTRIES:
        return None

    entries_to_archive = entries[:-MAX_NOTIFICATION_ENTRIES]
    entries_to_keep = entries[-MAX_NOTIFICATION_ENTRIES:]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_file = ARCHIVE_DIR / f"notifications_{timestamp}.md"

    archive_content = "# Notificaciones Archivadas\n\n"
    archive_content += f"**Fecha:** {datetime.now():%Y-%m-%d %H:%M:%S}\n"
    archive_content += "\n---\n\n".join(entries_to_archive)

    write_file(archive_file, archive_content)

    new_content = "# Registro de Notificaciones\n\n---\n\n"
    new_content += "\n\n---\n\n".join(entries_to_keep)
    new_content += "\n\n---\n"
    write_file(NOTIFICATIONS, new_content)

    # WOT-2026-036a: prune old notifications_*.md snapshots after archiving a
    # new one. Best-effort: pruning is disk hygiene, not a gate, so an
    # OPERATIONAL failure here must never break archiving or session close.
    #
    # The import is OUTSIDE the try/except on purpose (MANAGER_REVIEW 1->9->2,
    # comun branch): an ImportError is a PROGRAMMING/deployment error, not an
    # operational one -- swallowing it as a WARN would silently disable pruning
    # forever and reintroduce the unbounded-growth defect this ticket fixes,
    # with no signal. Let it propagate so CI/tests catch it. Only the prune
    # EXECUTION is best-effort.
    from scripts.prune_runtime_retention import prune, select_all

    try:
        selection = select_all(PROJECT_ROOT, {"keep_notification_archives": 10})
        prune(selection, apply=True)
    except Exception as exc:
        print(f"[WARN] Notification archive prune failed: {exc}")

    return str(archive_file)


def run_finalization_checks() -> dict:
    """Checks adicionales para planes de tipo FINALIZATION."""
    results = {"passed": True, "summary": []}
    checks = {
        "README.md": PROJECT_ROOT / "README.md",
        "CHANGELOG.md": PROJECT_ROOT / "CHANGELOG.md",
        "closeout_report.md": COLLAB_DIR / "closeout_report.md",
    }
    for name, path in checks.items():
        if path.exists():
            results["summary"].append(f"[OK] {name}: Presente")
        else:
            results["summary"].append(f"[WARN] {name}: No encontrado")
    return results


def _read_pytest_safe_verdict() -> dict:
    """Read the canonical runner's stamp (`run_pytest_safe` last-run.json).

    WOT-2026-016c: the quality gate must reflect the REAL health of the suite
    without re-running it under an artificial `timeout=120` (the canonical suite
    exceeds that, which either AUTO-REJECTs spuriously or masks a real failure as
    a benign timeout). This reads the stamp that `scripts/run_pytest_safe.py`
    writes after running the full suite with no cap.

    Returns ``{"verdict": "green"|"red"|"inconclusive", "detail": str}``:
    - ``green``: stamp exists, ``status == "finished"``, ``exit_code == 0`` and
      ``tested_commit_sha == HEAD`` (fresh, real, passing run).
    - ``red``: stamp is fresh for HEAD but ``exit_code != 0`` (real failure);
      ``detail`` names the failing tests when available.
    - ``inconclusive``: stamp absent, unreadable, or ``tested_commit_sha`` does
      NOT match HEAD (stale). Never faked as green: the caller emits a WARN and
      does not force ``passed``. The canonical pre-handoff still requires a fresh
      green stamp separately, so this is a soft signal, not a silent no-op.
    """
    stamp_path = PROJECT_ROOT / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not stamp_path.exists():
        return {"verdict": "inconclusive", "detail": "sin last-run.json"}
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except OSError as exc:
        # WOT-2026-019b: str(exc) de un OSError concatena la ruta absoluta
        # (exc.filename), que bajo PROJECT_ROOT arrastra el username local.
        # Componer el detail a mano sin exponer nunca la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"stamp ilegible: {exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"stamp ilegible: {exc.strerror} (errno {exc.errno})"
        return {"verdict": "inconclusive", "detail": detail}
    except json.JSONDecodeError as exc:
        return {"verdict": "inconclusive", "detail": f"stamp ilegible: {exc}"}

    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=10,
        )
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        head_sha = ""

    tested_sha = str(stamp.get("tested_commit_sha", ""))
    if not head_sha or tested_sha != head_sha:
        return {
            "verdict": "inconclusive",
            "detail": f"stamp de {tested_sha[:7] or '?'} != HEAD {head_sha[:7] or '?'}",
        }
    if stamp.get("status") != "finished":
        return {
            "verdict": "inconclusive",
            "detail": f"run no finalizado (status={stamp.get('status')})",
        }
    # WOT-2026-016c (Rev2 nit): a partial run (`--level unit` or explicit paths)
    # must NOT green-light the gate -- that would be a new false green with only
    # a fraction of the suite. Require the canonical full-suite shape, the same
    # criterion assert_canonical_suite_green enforces at pre-handoff.
    level = stamp.get("level")
    args_mode = stamp.get("args_mode")
    if level != "all" or (args_mode is not None and args_mode != "default_discovery"):
        return {
            "verdict": "inconclusive",
            "detail": (
                f"cobertura parcial (level={level}, args_mode={args_mode}); "
                "el gate solo confia en --level all con discovery por defecto"
            ),
        }
    if stamp.get("exit_code") == 0:
        return {"verdict": "green", "detail": "suite verde sobre HEAD"}
    failed = stamp.get("failed_test_ids") or []
    detail = (
        f"{len(failed)} test(s) fallando: {failed[:3]}"
        if failed
        else f"exit_code={stamp.get('exit_code')}"
    )
    return {"verdict": "red", "detail": detail}


def run_quality_gates(plan_type: str = "IMPLEMENTATION") -> dict:
    """Ejecuta validaciones automaticas."""
    print("\n[QUALITY GATES] Ejecutando Quality Gates...")
    results = {"passed": True, "errors": [], "summary": [], "warnings": []}

    state_errors = validate_state_files()
    total_state_errors = sum(len(errs) for errs in state_errors.values())
    if total_state_errors > 0:
        results["warnings"].append(
            f"Archivos de estado: {total_state_errors} problemas"
        )
    else:
        results["summary"].append("[OK] Estado: Archivos validos")

    src_dir = PROJECT_ROOT / "src"
    tests_dir = PROJECT_ROOT / "tests"
    dirs_to_check = [str(d) for d in [src_dir, tests_dir] if d.exists()]
    if not dirs_to_check:
        dirs_to_check = ["."]

    try:
        ruff = subprocess.run(
            ["uv", "run", "ruff", "check", *dirs_to_check],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if ruff.returncode != 0:
            results["passed"] = False
            results["summary"].append("[FAIL] Ruff: Errores de linting")
        else:
            results["summary"].append("[OK] Ruff: Limpio")
    except FileNotFoundError:
        results["summary"].append("[WARN] Ruff: No instalado")

    if tests_dir.exists():
        # WOT-2026-016c: NO re-run pytest here with a hard `timeout=120`. The
        # canonical suite (~3470 tests) legitimately exceeds 120s, so a direct
        # `subprocess.run(pytest, timeout=120)` ALWAYS times out and either
        # (a) AUTO-REJECTs spuriously, or (b) after the naive timeout fix, turns
        # the gate into a silent no-op that can MASK a real failure as a benign
        # timeout (false green). Instead, read the verdict of the canonical
        # runner `scripts/run_pytest_safe.py`, which runs the full suite with no
        # artificial cap and stamps `last-run.json`. The gate reflects the real
        # health of the suite: PASS only when the stamp is fresh (tested against
        # HEAD), finished and green; FAIL on a real failure; inconclusive (does
        # not force pass) when the stamp is stale/absent.
        pytest_status = _read_pytest_safe_verdict()
        if pytest_status["verdict"] == "green":
            results["summary"].append("[OK] Pytest: suite verde (run_pytest_safe)")
        elif pytest_status["verdict"] == "red":
            results["passed"] = False
            results["summary"].append(f"[FAIL] Pytest: {pytest_status['detail']}")
        else:  # inconclusive: stale/absent stamp -> do NOT fake a pass or a fail
            results["warnings"].append(
                f"[WARN] Pytest: veredicto no concluyente ({pytest_status['detail']}); "
                "corre scripts/run_pytest_safe.py --level all sobre HEAD"
            )

    if plan_type == "FINALIZATION":
        fin_results = run_finalization_checks()
        results["summary"].extend(fin_results["summary"])

    for warning in results["warnings"]:
        print(f"   {warning}")

    status = "[PASSED]" if results["passed"] else "[FAILED]"
    print(f"   {status}")
    return results


def update_log_status(new_status: str, note: str) -> bool:
    """Actualiza el estado en execution_log.md."""
    content = read_file(EXEC_LOG)
    if not content:
        return False
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "**Estado:**" in line:
            lines[i] = f"**Estado:** {new_status}"
            new_content = "\n".join(lines) + f"\n\n{note}"
            write_file(EXEC_LOG, new_content)
            return True
    return False


def create_findings_file(plan_id: str = "N/A") -> Path:
    """Crea findings.md desde template."""
    findings_path = COLLAB_DIR / "findings.md"

    if findings_path.exists():
        return findings_path

    template_path = AGENT_DIR / "templates" / "findings_template.md"

    try:
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = """# Hallazgos de Investigacion

**Plan ID:** {{PLAN_ID}}
**Creado:** {{DATE}}

---

## Hallazgos

<!-- Documenta aqui tus hallazgos durante la investigacion -->
"""

        content = template.replace("{{PLAN_ID}}", plan_id)
        content = content.replace(
            "{{DATE}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        write_file(findings_path, content)
        print("  [OK] Creado findings.md")

    except OSError as e:
        # WOT-2026-019d: template_path.read_text/write_file hacen I/O directo
        # sobre rutas absolutas bajo AGENT_DIR/COLLAB_DIR; un OSError real trae
        # .filename. Componer el mensaje a mano sin exponer la ruta cruda.
        if e.filename:
            where = scope_gate._relativize_scope_path(e.filename, PROJECT_ROOT)
            detail = f"{e.strerror} (errno {e.errno}) en {where}"
        else:
            detail = f"{e.strerror} (errno {e.errno})"
        print(f"  [WARN] Error creando findings.md: {detail}")
    except Exception as e:
        print(f"  [WARN] Error creando findings.md: {e}")

    return findings_path


def _run_pre_action_hooks(
    plan_id: str, plan_status: str, log_status: str, action_type: str
) -> None:
    """Run pre-action hooks if available."""
    if HOOKS_AVAILABLE and hook_registry:
        hook_registry.execute(
            "pre_action",
            {
                "action_type": action_type,
                "plan_id": plan_id,
                "plan_status": plan_status,
                "log_status": log_status,
            },
        )


def _check_quality_gates(
    plan_id: str, plan_type: str, plan_status: str, skip_gates: bool
) -> dict | None:
    """Check quality gates and return action if failed.

    Before: plan_id must be non-empty, plan_type and plan_status must be valid.
    During: Runs quality gates via run_quality_gates(). On failure, emits
            AUTO-REJECT with a distinct instruction (no `.builder_rules` or
            `builder_workflow.md` references - WT-2026-204).
    After: Returns action dict with role=BUILDER for AUTO-REJECT, or None if
           all gates pass.
    """
    gate_result = run_quality_gates(plan_type=plan_type)
    if not gate_result["passed"]:
        update_log_status("IN_PROGRESS", "AUTO-REJECTED: Quality Gates fallaron")
        return {
            "role": "BUILDER",
            "context_file": "",
            "workflow_file": "",
            "instruction": (
                f"PLAN {plan_id} AUTO-REJECTED: Quality Gates fallaron. "
                "Corrige errores de linter o tests antes de marcar como listo."
            ),
            "plan_id": plan_id,
            "plan_status": plan_status,
            "log_status": "AUTO-REJECTED",
            "action_type": "FIX_QUALITY_ISSUES",
        }
    return None


def _check_completion_verification(
    plan_id: str, plan_status: str, log_status: str, plan_type: str, strict_mode: bool
) -> dict | None:
    """Check completion verification in strict mode and return action if failed."""
    if HOOKS_AVAILABLE and hook_registry:
        stop_result = stop_hook(
            {
                "plan_status": plan_status,
                "plan_type": plan_type,
                "mode": "strict" if strict_mode else "normal",
            }
        )
        if strict_mode and not stop_result.get("can_complete", True):
            return {
                "role": "BUILDER",
                "context_file": ".builder_rules",
                "workflow_file": ".agent/workflows/builder_workflow.md",
                "instruction": (
                    f"Plan {plan_id} no supera Completion Verification. "
                    "Corrige advertencias antes de review."
                ),
                "plan_id": plan_id,
                "plan_status": plan_status,
                "log_status": log_status,
                "action_type": "FIX_QUALITY_ISSUES",
            }
    return None


# Transition table for base routing
TRANSITION_TABLE = {
    ("no_plan", "any"): (
        "MANAGER",
        "CREATE_PLAN",
        "No hay plan activo. Crea un nuevo work_plan.md",
    ),
    ("completed", "any"): (
        "MANAGER",
        "CREATE_PLAN",
        "No hay plan activo. Crea un nuevo work_plan.md",
    ),
    ("in_planning", "any"): (
        "MANAGER",
        "FINALIZE_PLAN",
        "Plan {plan_id} en borrador. Finaliza y cambia a APPROVED",
    ),
    ("approved", "ready_for_review"): (
        "MANAGER",
        "REVIEW_WORK",
        "Builder completo {plan_id}. Revisa el trabajo.",
    ),
    ("approved", "any"): (
        "BUILDER",
        "IMPLEMENT",
        "Plan {plan_id} aprobado. Implementa segun work_plan.md",
    ),
    ("in_review", "any"): (
        "MANAGER",
        "REVIEW_CHANGES",
        "Plan {plan_id} en revision. Verifica cambios.",
    ),
    ("any", "blocked"): (
        "MANAGER",
        "RESOLVE_BLOCK",
        "Builder BLOQUEADO en {plan_id}. Resuelve en review_queue.md",
    ),
}


def _lookup_transition(
    plan_status: str, log_status: str, plan_id: str
) -> tuple[str, str, str] | None:
    """Lookup transition from table."""
    # Normalize status for lookup
    plan_key = (
        "no_plan"
        if not plan_status or plan_status in ("COMPLETED", "N/A")
        else plan_status.lower().replace(" ", "_")
    )
    log_key = log_status.lower().replace(" ", "_") if log_status else "any"

    # Check specific matches first
    for (p_key, l_key), (role, action, template) in TRANSITION_TABLE.items():
        if (p_key == plan_key or p_key == "any") and (
            l_key == log_key or l_key == "any"
        ):
            instruction = template.format(plan_id=plan_id)
            return role, action, instruction

    return None


def _inject_graph_context(instruction: str) -> str:
    """
    Inject a compact ## Project Context block into the instruction if graphify or scanner artifacts exist.

    Before:
        - instruction is a plain string.
        - GRAPH_CONTEXT_AVAILABLE and SCANNER_AVAILABLE determine available adapters.

    During:
        - Tries scanner context first (preferred, more compact).
        - Falls back to graphify context if scanner unavailable.
        - Prepends context block to instruction.

    After:
        - Returns instruction with ## Project Context prepended.
        - Returns original instruction unchanged if both contexts unavailable.
    """
    # Try scanner context first (preferred - WP-2026-150)
    if SCANNER_AVAILABLE:
        result = _inject_scanner_context(instruction)
        if result != instruction:
            return result

    # Fallback to graphify context
    if not GRAPH_CONTEXT_AVAILABLE:
        return instruction

    try:
        context_block = generate_context_for_destination(PROJECT_ROOT.resolve())
        if context_block:
            return f"{context_block}\n\n---\n\n{instruction}"
    except Exception:  # noqa: S110
        pass  # Gracefully degrade if graph context unavailable

    return instruction


def _build_scanner_context_block(project_map: dict) -> str:
    """Build compact context block from scanner project_map."""
    summary = project_map.get("summary", {})
    frameworks = project_map.get("frameworks", {})
    import_map = project_map.get("importMap", {})
    parse_errors = project_map.get("parse_errors", [])

    lines = [
        "## Project Context",
        "",
        f"- **Total files:** {summary.get('total_files', 0)}",
        f"- **Total size:** {summary.get('total_size_bytes', 0) / 1024:.1f} KB",
    ]

    # Categories
    categories = summary.get("categories", {})
    if categories:
        lines.append("")
        lines.append("**Files by category:**")
        for cat, count in sorted(categories.items()):
            lines.append(f"  - {cat}: {count}")

    # Frameworks
    fw_list = frameworks.get("frameworks", [])
    tools_list = frameworks.get("tools", [])
    if fw_list or tools_list:
        lines.append("")
        if fw_list:
            lines.append(f"**Frameworks:** {', '.join(sorted(fw_list))}")
        if tools_list:
            lines.append(f"**Tools:** {', '.join(sorted(tools_list))}")

    # Import stats
    python_files = import_map.get("python_files", {})
    if python_files:
        lines.append("")
        lines.append(f"**Python files with imports:** {len(python_files)}")
        if parse_errors:
            lines.append(f"**Parse errors:** {len(parse_errors)}")

    return "\n".join(lines)


def _inject_scanner_context(instruction: str) -> str:
    """
    Inject a compact ## Project Context block from project-map.json scanner artifact.

    Before:
        - instruction is a plain string.
        - SCANNER_AVAILABLE determines if scanner module is importable.

    During:
        - Checks for .agent/context/project-map.json existence.
        - Reads and parses the JSON artifact.
        - Builds compact summary with file counts, categories, frameworks, and import stats.
        - Prepends context block to instruction.

    After:
        - Returns instruction with ## Project Context prepended.
        - Returns original instruction unchanged if scanner artifact unavailable.
    """
    if not SCANNER_AVAILABLE:
        return instruction

    try:
        context_dir = get_context_dir()
        scanner_output = context_dir / "project-map.json"

        if not scanner_output.exists():
            return instruction

        import json

        project_map = json.loads(scanner_output.read_text(encoding="utf-8"))
        context_block = _build_scanner_context_block(project_map)
        return f"{context_block}\n\n---\n\n{instruction}"

    except Exception:  # noqa: S110
        pass  # Gracefully degrade if scanner unavailable

    return instruction


def determine_next_action(skip_gates: bool = False, strict_mode: bool = False) -> dict:
    """Analiza el estado y determina la siguiente accion."""
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)

    plan_status = get_status(plan_content, "**Estado:**")
    log_status = get_status(log_content, "**Estado:**")
    plan_id = get_plan_id(plan_content)
    plan_type = get_plan_type(plan_content)

    # Determine pre-action type for hooks
    pre_action_type = "CHECK_STATUS"
    if not plan_content.strip() or "COMPLETED" in plan_status or "N/A" in plan_status:
        pre_action_type = "CREATE_PLAN"
    elif "APPROVED" in plan_status and "READY_FOR_REVIEW" in log_status:
        pre_action_type = "REVIEW_WORK"
    elif "APPROVED" in plan_status:
        pre_action_type = "IMPLEMENT"

    _run_pre_action_hooks(plan_id, plan_status, log_status, pre_action_type)

    # Check quality gates for review state
    if (
        "APPROVED" in plan_status
        and "READY_FOR_REVIEW" in log_status
        and not skip_gates
    ):
        gate_action = _check_quality_gates(plan_id, plan_type, plan_status, skip_gates)
        if gate_action:
            return {"plan_type": plan_type, **gate_action}

    # Check completion verification in strict mode
    if "APPROVED" in plan_status and "READY_FOR_REVIEW" in log_status:
        verification_action = _check_completion_verification(
            plan_id, plan_status, log_status, plan_type, strict_mode
        )
        if verification_action:
            return {"plan_type": plan_type, **verification_action}

    # Handle finalization instruction variation
    if "APPROVED" in plan_status and plan_type == "FINALIZATION":
        instruction = f"Plan {plan_id} aprobado. Ejecuta cierre segun work_plan.md"
        instruction = _inject_graph_context(instruction)
        return {
            "role": "BUILDER",
            "context_file": ".builder_rules",
            "workflow_file": ".agent/workflows/builder_workflow.md",
            "instruction": instruction,
            "plan_id": plan_id,
            "plan_status": plan_status,
            "log_status": log_status,
            "action_type": "IMPLEMENT",
            "plan_type": plan_type,
        }

    # Lookup base transition
    transition = _lookup_transition(plan_status, log_status, plan_id)
    if transition:
        role, action_type, instruction = transition
        instruction = _inject_graph_context(instruction)
        context_file = ".manager_rules" if role == "MANAGER" else ".builder_rules"
        workflow_file = (
            ".agent/workflows/manager_workflow.md"
            if role == "MANAGER"
            else ".agent/workflows/builder_workflow.md"
        )
        return {
            "role": role,
            "context_file": context_file,
            "workflow_file": workflow_file,
            "instruction": instruction,
            "plan_id": plan_id,
            "plan_status": plan_status,
            "log_status": log_status,
            "action_type": action_type,
            "plan_type": plan_type,
        }

    # Fallback for unknown states
    instruction = "Estado indeterminado. Revisa archivos manualmente."
    instruction = _inject_graph_context(instruction)
    return {
        "role": "UNKNOWN",
        "context_file": "N/A",
        "workflow_file": "N/A",
        "instruction": instruction,
        "plan_id": plan_id,
        "plan_status": plan_status,
        "log_status": log_status,
        "action_type": "MANUAL_INTERVENTION",
        "plan_type": plan_type,
    }


def should_overwrite_turn(turn_path: Path, force_reset: bool = False) -> bool:
    """Devuelve True solo si TURN.md debe ser regenerado."""
    if force_reset or not turn_path.exists():
        return True
    try:
        content = turn_path.read_text(encoding="utf-8")
        return bool("UNKNOWN" in content or "MANUAL_INTERVENTION" in content)
    except Exception:
        return True


def _validate_turn_blockers_content(blockers_text: str) -> bool:
    """Check that blockers section is valid (non-empty, < 15 KB, no JSONL crudo).

    Before: blockers_text is the content of the ``## Blockers from Manager``
            section to be appended to TURN.md.
    During: Checks size < 15 KB and absence of ``{"type":`` / ``sessionID``.
    After: Returns True only if all checks pass and the content is useful.
    """
    if not blockers_text or not blockers_text.strip():
        return False
    if len(blockers_text.encode("utf-8")) >= 15 * 1024:
        return False
    return not ('{"type":' in blockers_text or "sessionID" in blockers_text)


def update_turn_file(action: dict) -> None:
    """Actualiza TURN.md con informacion del turno actual.

    WT-2026-204: Preserves the ``## Blockers from Manager`` section from the
    previous TURN.md only if it passes validation (non-empty, < 15 KB, no
    JSONL crudo ``{"type":`` / ``sessionID``).  If validation fails, the
    invalid blockers are discarded silently.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    import contextlib

    existing_blockers = ""
    with contextlib.suppress(Exception):
        turn_path = TURN_FILE.resolve()
        if turn_path.exists():
            current_content = turn_path.read_text(encoding="utf-8")
            idx = current_content.find("## Blockers from Manager")
            if idx != -1:
                blockers_section = current_content[idx:].strip()
                # WT-2026-204: validate before preserving
                if _validate_turn_blockers_content(blockers_section):
                    existing_blockers = "\n\n" + blockers_section
                else:
                    print(
                        "[WARN] Discarded invalid blockers section in TURN.md "
                        "(empty, oversized, or contains JSONL crudo)",
                        flush=True,
                    )

    content = f"""# TURNO ACTUAL

**Ultima actualizacion:** {timestamp}

---

## Agente Activo

| Campo | Valor |
|-------|-------|
| **ROL** | **{action["role"]}** |
| **Plan ID** | {action["plan_id"]} |
| **Tipo** | {action.get("plan_type", "IMPLEMENTATION")} |
| **Accion** | {action["action_type"]} |

---

## Instruccion

> {action["instruction"]}

---

## Estado del Sistema

| Archivo | Estado |
|---------|--------|
| work_plan.md | {action["plan_status"]} |
| execution_log.md | {action["log_status"]} |

---

*Generado por agent_controller.py v5*{existing_blockers}
"""
    write_file(TURN_FILE, content)


def print_human_readable(action: dict) -> None:
    """Muestra el estado de forma legible."""
    role = action["role"]
    role_emoji = {"MANAGER": "MANAGER", "BUILDER": "BUILDER", "UNKNOWN": "UNKNOWN"}.get(
        role, "UNKNOWN"
    )

    plan_type = action.get("plan_type", "IMPLEMENTATION")
    type_label = " [CIERRE]" if plan_type == "FINALIZATION" else ""

    print("\n" + "=" * 70)
    print("  SISTEMA MULTI-AGENTE v5 - Panel de Control")
    print("=" * 70)
    print(f"\n  TURNO ACTUAL: {role_emoji} {role}{type_label}")
    print(f"  Plan: {action['plan_id']}")
    print("\n  ESTADOS:")
    print(f"     - Plan:     {action['plan_status']}")
    print(f"     - Progreso: {action['log_status']}")
    print("\n  ACCION:")
    print(f"     {action['instruction']}")

    # Siguiente paso accionable para el usuario
    action_type = action.get("action_type", "")
    if action_type == "IMPLEMENT":
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y continua con el plan'"
    elif action_type in ("REVIEW_WORK", "REVIEW_CHANGES"):
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y revisa la implementacion'"
    elif action_type == "CREATE_PLAN":
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y crea el plan'"
    elif action_type == "FIX_QUALITY_ISSUES":
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y corrige los errores'"
    elif action_type == "RESOLVE_BLOCK":
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y resuelve el bloqueo'"
    else:
        next_msg = f"Abre el agente {role} y dile: 'Ejecuta python .agent/agent_controller.py y continua'"

    print("\n  SIGUIENTE PASO:")
    print(f"     {next_msg}")
    print("\n  COMANDOS:")
    print("     python .agent/agent_controller.py")
    print("     python .agent/agent_controller.py --strict")
    print("=" * 70 + "\n")


def _handle_recover() -> int:
    """Handle --recover flag."""
    if SESSION_TRACKER_AVAILABLE:
        result = recover_session()
        if not result:
            print("[INFO] No hay sesion previa para recuperar.")
    else:
        print("[WARN] Session tracker no disponible.")
    return 0


def _handle_check_completion() -> int:
    """Handle --check-completion flag."""
    if COMPLETION_CHECKER_AVAILABLE:
        result = check_completion()
        show_completion_report(result)
        return 0 if result["can_complete"] else 1
    print("[WARN] Completion checker no disponible.")
    return 1


def _fallback_checkpoint_motor(
    guard_result: dict, plan_id: str, plan_content: str = ""
) -> dict:
    """WT-2026-232a: Fallback check for checkpoint tag in _MOTOR_ROOT.

    In legacy motor/destino topology, the checkpoint tag lives in repo_motor,
    not PROJECT_ROOT. The pre_handoff_guard.py script checks PROJECT_ROOT
    only; this fallback retries in _MOTOR_ROOT when the guard fails. Plans
    that declare repo_destino delivery authority are intentionally excluded.
    """
    if _read_delivery_authority(plan_content) == "repo_destino":
        return guard_result
    if (
        not guard_result.get("valid")
        and guard_result.get("missing_checkpoint")
        and not guard_result.get("dirty_tree")
        and not guard_result.get("dirty_files")
        and _MOTOR_ROOT.resolve() != PROJECT_ROOT.resolve()
    ):
        checkpoint_valid, _files, _error = _resolve_motor_checkpoint_files(
            _MOTOR_ROOT, plan_id
        )
        if checkpoint_valid:
            guard_result["valid"] = True
            guard_result["missing_checkpoint"] = False
    return guard_result


def _run_pre_handoff_guard(plan_id: str, json_output: bool) -> dict:  # noqa: C901
    """
    Run the pre-handoff guard before emitting READY_FOR_REVIEW.

    WP-2026-167: Invokes scripts/pre_handoff_guard.py to verify:
    - Tree is clean (no uncommitted changes outside live surfaces)
    - Checkpoint M3 (checkpoint/review-<ticket>) exists

    Args:
        plan_id: Ticket ID (e.g., WP-2026-167)
        json_output: Whether to output guard result as JSON

    Returns:
        dict with 'valid' (bool), 'dirty_tree', 'missing_checkpoint', etc.
    """
    try:
        # WT-2026-245b: Read deliverable type early to skip checkpoint checks
        # for non-code tickets (documentation/research/analysis) that bypass
        # the motor checkpoint in mark-ready.
        _plan_content_ph = read_file(WORK_PLAN)
        _dt_ph = _read_deliverable_type(_plan_content_ph)
        _is_non_code = _dt_ph in {"documentation", "research", "analysis"}

        guard_script = SCRIPT_DIR.parent / "scripts" / "pre_handoff_guard.py"
        if not guard_script.exists():
            print("[WARN] pre_handoff_guard.py not found; skipping guard check")
            return {"valid": True}

        cmd = [
            sys.executable,
            str(guard_script),
            "--project-root",
            str(PROJECT_ROOT),
            "--ticket-id",
            plan_id,
            "--json",
        ]
        if _MOTOR_ROOT != PROJECT_ROOT and (_MOTOR_ROOT / ".git").exists():
            cmd += ["--motor-root", str(_MOTOR_ROOT)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        try:
            guard_result = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"[WARN] Failed to parse guard output: {result.stdout}")
            guard_result = {"valid": result.returncode == 0}

        # WT-2026-232a: Fallback check for checkpoint tag in _MOTOR_ROOT.
        guard_result = _fallback_checkpoint_motor(
            guard_result, plan_id, _plan_content_ph
        )

        # WT-2026-245b / WOT-AUDIT-M3: When the guard passed without checking
        # the tag, explicitly verify the checkpoint exists in the delivery
        # authority repo. Legacy code/mixed plans still resolve to _MOTOR_ROOT.
        # Skip this verification for non-code tickets (documentation/research/
        # analysis) since they bypass checkpoint enforcement in mark-ready.
        if (
            not _is_non_code
            and guard_result.get("valid")
            and _MOTOR_ROOT.resolve() != PROJECT_ROOT.resolve()
            and not guard_result.get("missing_checkpoint")
        ):
            _checkpoint_root = _resolve_checkpoint_root(_plan_content_ph, _dt_ph)
            cp_valid, _cp_files, cp_error = _resolve_motor_checkpoint_files(
                _checkpoint_root, plan_id
            )
            if not cp_valid:
                guard_result["valid"] = False
                guard_result["missing_checkpoint"] = True
                if not json_output:
                    print(
                        f"[ERROR] {cp_error}",
                        file=sys.stderr,
                        flush=True,
                    )

        # WT-2026-245b: For non-code tickets, override missing_checkpoint to
        # False so the guard does not block mark-ready. Tree hygiene (dirty_tree)
        # is still enforced by the guard script.
        if _is_non_code and guard_result.get("missing_checkpoint"):
            guard_result["valid"] = True
            guard_result["missing_checkpoint"] = False

        if not json_output:
            if guard_result.get("valid"):
                print(f"[OK] Pre-handoff guard passed for {plan_id}")
                if guard_result.get("scope_discrepancy"):
                    print(
                        f"[WARN] Scope discrepancy (non-blocking): "
                        f"{', '.join(guard_result['scope_discrepancy'])}"
                    )
            else:
                print(f"[ERROR] Pre-handoff guard failed for {plan_id}")
                if guard_result.get("missing_checkpoint"):
                    print(f"  - Missing checkpoint M3: checkpoint/review-{plan_id}")
                if guard_result.get("dirty_tree"):
                    print(
                        f"  - Dirty tree: {', '.join(guard_result.get('dirty_files', []))}"
                    )
                # WOT-2026-010c: surface the canonical-suite gate diagnostic so
                # the operator sees why the handoff is blocked and how to fix it.
                _cs = guard_result.get("canonical_suite") or {}
                if _cs.get("canonical_suite_required") and _cs.get("reason") not in (
                    None,
                    "fresh_green",
                    "deliverable_type_skip",
                ):
                    print(f"  - Canonical suite not fresh-green: {_cs.get('reason')}")
                    if _cs.get("canonical_suite_error"):
                        print(f"    {_cs['canonical_suite_error']}")
                    if _cs.get("remediation"):
                        print(f"    Fix: {_cs['remediation']}")
                if guard_result.get("scope_discrepancy"):
                    print(
                        f"  - Scope discrepancy (non-blocking): "
                        f"{', '.join(guard_result['scope_discrepancy'])}"
                    )

        return guard_result

    except OSError as exc:
        # WOT-2026-019d: read_file(WORK_PLAN) y subprocess.run(cmd, ...) con
        # guard_script pueden lanzar OSError (p.ej. FileNotFoundError) con
        # .filename absoluto. Componer el mensaje a mano sin exponer la ruta
        # cruda. Un unico bloque cubre AMBOS usos de exc (print y warnings).
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        print(f"[WARN] Pre-handoff guard execution failed: {detail}")
        return {"valid": True, "warnings": [f"Guard execution error: {detail}"]}
    except Exception as exc:
        print(f"[WARN] Pre-handoff guard execution failed: {exc}")
        return {"valid": True, "warnings": [f"Guard execution error: {exc}"]}


def _is_bus_state_post_success(bus_state: object | None) -> bool:
    """Check if bus-derived state is past IN_PROGRESS (orphan-safe territory).

    When a stale Builder shell runs mark-ready or pre-handoff but the ticket
    is already past IN_PROGRESS, the shell is orphaned. This function returns
    True for READY_FOR_REVIEW, READY_TO_CLOSE, HUMAN_GATE, and COMPLETED.

    Returns False for None (unknown/unavailable bus) so the caller falls back
    to the current blocking behavior.
    """
    if bus_state is None:
        return False
    from bus.state_machine import TicketState

    return bus_state in (
        TicketState.READY_FOR_REVIEW,
        TicketState.READY_TO_CLOSE,
        TicketState.HUMAN_GATE,
        TicketState.COMPLETED,
    )


def _maybe_handle_stale_builder_orphan(
    *,
    plan_id: str,
    process_round: int | None,
    round_reason: str,
    bus_state: object | None,
) -> tuple[bool, str]:
    """Contain stale Builder noise after success without changing IN_PROGRESS rules.

    WT-2026-242b intentionally adds only controller-side containment. It does
    not resolve launcher/process identity or stale-shell root cause.
    """
    if not _is_bus_state_post_success(bus_state):
        return False, round_reason

    state_name = str(bus_state.value) if bus_state else "post-success"
    msg = (
        f"Stale Builder shell detected for {plan_id}: {round_reason}. "
        f"Ticket is already in {state_name}. No action taken."
    )
    if BUS_AVAILABLE and event_bus:
        event_bus.emit(
            event_type="STALE_BUILDER_ORPHAN",
            ticket_id=plan_id,
            actor="BUILDER",
            payload={
                "reason": "stale_builder_round",
                "process_round": process_round,
                "bus_state": state_name,
                "details": round_reason,
            },
        )
    return True, msg


def _handle_mark_ready(  # noqa: C901 - linear guard chain (HUMAN_GATE, already-ready, breaker)
    scope_override: str | None, json_output: bool, force_mode: bool
) -> int:
    """Handle --mark-ready flag.

    WP-2026-143: Bus-backed idempotency. Consults bus-derived state as authority.
    - READY_FOR_REVIEW, READY_TO_CLOSE, COMPLETED: clean no-op (no duplicate events).
    - HUMAN_GATE: blocked (requires human intervention).
    - Fallback to markdown-based logic if bus is unavailable.
    """
    from bus.state_machine import TicketState

    plan_content, log_content, plan_id = _load_mark_ready_context()
    if is_invalid_plan_id(plan_id):
        print("[ERROR] No active plan found.")
        return 1

    log_status = get_status(log_content, "**Estado:**")
    round_ok, process_round, round_reason = _ensure_active_builder_round(plan_id)

    # WP-2026-143 / WT-2026-242b: Derive bus state early for orphan detection.
    bus_state = None
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine

        events = event_bus.read_events(ticket_id=plan_id)
        if events:
            bus_state = StateMachine.derive_state_from_events(
                [e.to_dict() for e in events]
            )

    if not round_ok:
        # WT-2026-242b: Orphan containment - if the ticket is already past
        # IN_PROGRESS, emit STALE_BUILDER_ORPHAN instead of HANDOFF_BLOCKED.
        # This prevents stale shells from contaminating the bus post-success.
        was_orphan, msg = _maybe_handle_stale_builder_orphan(
            plan_id=plan_id,
            process_round=process_round,
            round_reason=round_reason,
            bus_state=bus_state,
        )
        if was_orphan:
            if json_output:
                print(
                    json.dumps(
                        {
                            "status": "orphan_ignored",
                            "reason": "stale_builder_round",
                            "details": msg,
                            "plan_id": plan_id,
                            "process_round": process_round,
                            "bus_state": str(bus_state.value)
                            if bus_state
                            else "unknown",
                        },
                        indent=2,
                    )
                )
            else:
                print(f"[WARN] {msg}")
            return 0
        # Ticket is still IN_PROGRESS - maintain existing blocking behavior.
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="HANDOFF_BLOCKED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload={
                    "reason": "stale_builder_round",
                    "process_round": process_round,
                    "details": round_reason,
                },
            )
        msg = (
            f"Stale Builder shell cannot mark ready for {plan_id}: {round_reason}. "
            "Close the old Builder window and continue from the active round."
        )
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "stale_builder_round",
                        "details": msg,
                        "plan_id": plan_id,
                        "process_round": process_round,
                    },
                    indent=2,
                )
            )
        else:
            print(f"[ERROR] {msg}")
        return 1

    # WP-2026-143: Get bus-derived state as authority (also derived above for orphan detection)

    # WP-2026-106 hotfix: a ticket escalated to HUMAN_GATE can only leave that
    # state by explicit human intervention. The Builder must not be able to
    # re-declare READY_FOR_REVIEW and bypass the Manager review cycle.
    if bus_state == TicketState.HUMAN_GATE or (
        bus_state is None and "HUMAN_GATE" in log_status
    ):
        msg = (
            f"Ticket {plan_id} is in HUMAN_GATE. mark-ready is blocked: "
            "only a human can move it out of HUMAN_GATE."
        )
        if json_output:
            print(
                json.dumps(
                    {"status": "blocked", "reason": msg, "plan_id": plan_id}, indent=2
                )
            )
        else:
            print(f"[ERROR] {msg}")
        return 1

    # WP-2026-143: Bus-backed idempotency guard
    # If bus state is READY_FOR_REVIEW, READY_TO_CLOSE, or COMPLETED, exit cleanly
    # without emitting duplicate BUILDER_EXIT or STATE_CHANGED events.
    if bus_state is not None and bus_state in (
        TicketState.READY_FOR_REVIEW,
        TicketState.READY_TO_CLOSE,
        TicketState.COMPLETED,
    ):
        if bus_state == TicketState.READY_FOR_REVIEW:
            _sync_mark_ready_targets(plan_id, plan_content, current_round=process_round)
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "already_ready",
                        "plan_id": plan_id,
                        "bus_state": bus_state.value,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[INFO] Ticket {plan_id} bus state is {bus_state.value}. No action needed."
            )
        return 0

    # Fallback: markdown-based idempotency (bus unavailable or no events)
    if bus_state is None and "READY_FOR_REVIEW" in log_status:
        if json_output:
            print(json.dumps({"status": "already_ready", "plan_id": plan_id}, indent=2))
        else:
            print(f"[INFO] Ticket {plan_id} already marked as ready.")
        # Ensure STATE_CHANGED and BUILDER_EXIT are emitted idempotently
        # BUILDER_EXIT MUST come before STATE_CHANGED to maintain order invariant
        if BUS_AVAILABLE and event_bus:
            # Check if BUILDER_EXIT already exists
            builder_exit = event_bus.latest_event(
                ticket_id=plan_id, event_type="BUILDER_EXIT"
            )
            if not builder_exit:
                _emit_builder_exit(
                    plan_id=plan_id,
                    exit_reason="Implementation completed and ready for review",
                    completion_summary=f"Ticket {plan_id} implementation completed. All quality gates passed. Scope validated against Files Likely Touched.",
                    current_round=process_round,
                )

            # Check if STATE_CHANGED already exists
            latest_state_event = event_bus.latest_event(
                ticket_id=plan_id, event_type="STATE_CHANGED"
            )
            if (
                not latest_state_event
                or latest_state_event.payload.get("to_state") != "READY_FOR_REVIEW"
            ):
                bus_from_state = (
                    latest_state_event.payload.get("to_state")
                    if latest_state_event and latest_state_event.payload
                    else log_status
                )
                event_bus.emit(
                    event_type="STATE_CHANGED",
                    ticket_id=plan_id,
                    actor="BUILDER",
                    payload={
                        "from_state": bus_from_state,
                        "to_state": "READY_FOR_REVIEW",
                        "reason": "Ticket already in ready state",
                        "source": "mark-ready",
                        **(
                            {"round": process_round}
                            if process_round is not None
                            else {}
                        ),
                    },
                )
        return 0

    def _fail_closeout(reason: str, details: dict | None = None) -> int:
        payload = {"reason": reason}
        if details:
            payload.update(details)
        if process_round is not None:
            payload["round"] = process_round
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="HANDOFF_BLOCKED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload=payload,
            )
            _emit_builder_exit(
                plan_id=plan_id,
                exit_reason=f"mark-ready blocked: {reason}",
                completion_summary=json.dumps(payload, ensure_ascii=False),
                current_round=process_round,
            )
        _release_builder_lock(plan_id, expected_round=process_round)
        return 1

    # Exit gate: Check circuit breaker before allowing close
    breaker_status = _check_circuit_breaker(plan_id)
    if breaker_status["open"]:
        print(f"[ERROR] Circuit breaker is OPEN: {breaker_status['reason']}")
        print(
            f"  Failures: {breaker_status['failures']}, No-progress count: {breaker_status['no_progress_count']}"
        )
        print("  Resolve the underlying issue before marking ready.")
        return _fail_closeout(
            "circuit_breaker_open",
            {
                "details": breaker_status["reason"],
                "failures": breaker_status["failures"],
                "no_progress_count": breaker_status["no_progress_count"],
            },
        )

    # WP-2026-188 Phase 4: Builder ready evidence gate (unconditional - not bypassable)
    evidence_errors = _check_implementation_evidence(plan_id)
    if evidence_errors:
        for err in evidence_errors:
            if json_output:
                print(json.dumps({"error": err, "plan_id": plan_id}, indent=2))
            else:
                print(f"[ERROR] {err}")
        print(
            "[ERROR] --mark-ready blocked: no implementation evidence found for "
            f"{plan_id}. Complete the implementation before marking ready.",
            file=sys.stderr,
            flush=True,
        )
        return _fail_closeout(
            "implementation_evidence_failed",
            {"errors": evidence_errors},
        )

    # WP-2026-167: Pre-handoff guard - verify tree hygiene and M3 checkpoint
    guard_result = _run_pre_handoff_guard(plan_id, json_output)
    if not guard_result["valid"]:
        return _fail_closeout(
            "pre_handoff_guard_failed",
            {
                "dirty_tree": guard_result.get("dirty_tree", False),
                "missing_checkpoint": guard_result.get("missing_checkpoint", False),
                "dirty_files": guard_result.get("dirty_files", []),
                "scope_discrepancy": guard_result.get("scope_discrepancy", []),
                # WOT-2026-010c: propagate the structured canonical-suite diag
                # (last_run_json, reason, remediation, canonical_suite_error) so
                # the closeout failure payload is self-service, not opaque.
                "canonical_suite": guard_result.get("canonical_suite"),
            },
        )

    # --- WT-2026-232a / WOT-AUDIT-M3: authority-aware checkpoint scope gate ---
    # When motor/destino topology exists (different repos), check the declared
    # delivery authority checkpoint commit for scope compliance. Legacy plans
    # default to repo_motor; destination-authority code/mixed plans validate
    # against repo_destino without fabricating a motor commit.
    motor_root_mr = _MOTOR_ROOT.resolve()
    project_root_mr = PROJECT_ROOT.resolve()
    is_motor_topology = motor_root_mr != project_root_mr
    checkpoint_scope_pass = False

    if is_motor_topology:
        # For documentation/research/analysis tickets, skip motor checkpoint:
        # the evidence gate already verified declared deliverables exist on disk.
        _dt_mr = _read_deliverable_type(plan_content)
        _non_code_ticket = _dt_mr in {"documentation", "research", "analysis"}
        if _non_code_ticket:
            checkpoint_scope_pass = True
        else:
            checkpoint_root_mr = _resolve_checkpoint_root(plan_content, _dt_mr)
            checkpoint_label = (
                "Destination" if checkpoint_root_mr == project_root_mr else "Motor"
            )
            cp_valid, cp_files, cp_error = _resolve_motor_checkpoint_files(
                checkpoint_root_mr, plan_id
            )
            if cp_valid and cp_files:
                flt_motor_paths = _parse_raw_flt_paths(
                    plan_content, deliverable_type=_dt_mr
                )
                motor_set = {f.replace("\\", "/") for f in cp_files}
                flt_set = {p.replace("\\", "/") for p in flt_motor_paths}
                outside_flt = motor_set - flt_set
                inside_flt = motor_set & flt_set

                if inside_flt and not outside_flt:
                    # Full scope compliance: checkpoint files within FLT
                    if not json_output:
                        print(
                            f"[OK] {checkpoint_label} scope: "
                            f"{len(inside_flt)} files within "
                            "Files Likely Touched"
                        )
                    checkpoint_scope_pass = True
                elif outside_flt:
                    # Checkpoint files outside FLT -> block (or override)
                    print(
                        f"[ERROR] {checkpoint_label} checkpoint has files "
                        "outside Files Likely Touched:"
                    )
                    for f in sorted(outside_flt):
                        print(f"  - {f}")
                    if not scope_override:
                        print('Use --scope-override "reason" to proceed.')
                        return _fail_closeout(
                            "checkpoint_scope_outside_flt",
                            {"outside_flt": sorted(outside_flt)},
                        )
                    _record_scope_override(scope_override, outside_flt)
                    checkpoint_scope_pass = True
                # else: inside_flt empty, no outside_flt -> fall through to legacy
            elif not cp_valid:
                # No valid checkpoint in delivery authority repo -> block.
                if checkpoint_root_mr == motor_root_mr:
                    _print_motor_checkpoint_guidance(plan_id, cp_error)
                else:
                    print(
                        f"[ERROR] No valid destination checkpoint for {plan_id}: "
                        f"{cp_error}"
                    )
                    print(
                        "Run --pre-handoff first to create "
                        "checkpoint/review-<ticket> in repo_destino."
                    )
                return _fail_closeout(
                    "checkpoint_missing",
                    {"cp_error": cp_error},
                )
            # cp_valid but cp_files empty -> fall through to legacy

    if not checkpoint_scope_pass:
        # For the scope gate, supplement current git status with recent commits so
        # implementation files are found even when the tree is clean after hotfixes.
        _scope_changed = get_changed_files()
        if not _scope_changed:
            # Tree is clean: resolve recent commits to absolute paths
            _git_root_l = (
                PROJECT_ROOT
                if (PROJECT_ROOT / ".git").exists()
                else (_MOTOR_ROOT if (_MOTOR_ROOT / ".git").exists() else None)
            )
            if _git_root_l:
                _scope_changed = {
                    str((_git_root_l / f).resolve())
                    for f in _git_log_recent_files(_git_root_l)
                }
        gate_result = check_scope_gate(plan_content, _scope_changed, _exclude_files())
        if not _scope_gate_allows_close(gate_result, scope_override):
            return 1

    # Exit gate: Emit BUILDER_EXIT event - REQUIRED for ticket closure
    # MUST occur BEFORE STATE_CHANGED to maintain order invariant
    _emit_builder_exit(
        plan_id=plan_id,
        exit_reason="Implementation completed and ready for review",
        completion_summary=f"Ticket {plan_id} implementation completed. All quality gates passed. Scope validated against Files Likely Touched.",
        current_round=process_round,
    )

    # Auto-archive closed PLAN/AUDIT artifacts (idempotent, no-op if nothing to archive)
    _auto_archive_closed_artifacts()

    # WOT-2026-011h: the auto-archive above moves closed STRATEGY_/AUDIT_/PLAN_
    # artifacts with shutil.move and does NOT commit, so it can leave the same
    # `D old + ?? new` limbo that 011a closed for --session-close. The pre-handoff
    # guard ran BEFORE this archive, so it cannot catch a limbo that mark-ready
    # itself creates. Reuse the exact stable detector (archive_rename_uncommitted)
    # and fail closed BEFORE emitting READY_FOR_REVIEW. No auto-commit: the fix is
    # to surface the reconcile command, never to record the rename automatically.
    archive_block = _check_mark_ready_archive_rename()
    if archive_block is not None:
        if json_output:
            print(json.dumps(archive_block, indent=2))
        else:
            print(f"[ERROR] {archive_block['reason']}")
            for line in archive_block.get("details", []):
                print(f"  {line}")
        return 1

    _sync_mark_ready_targets(plan_id, plan_content, current_round=process_round)

    # Reset circuit breaker on successful completion
    _reset_circuit_breaker(plan_id)

    # Release builder lock
    _release_builder_lock(plan_id, expected_round=process_round)

    if json_output:
        print(json.dumps({"status": "marked_ready", "plan_id": plan_id}, indent=2))
    else:
        print(f"[OK] Ticket {plan_id} marked as ready for review.")

    return 0


def _handle_bootstrap_ticket(json_output: bool) -> int:
    """Handle --bootstrap-ticket flag.

    Emit STATE_CHANGED -> IN_PROGRESS for the active ticket if no such event
    exists yet in the bus. Called by launch_agent_terminals.ps1 before opening
    agent windows, ensuring the bridge and other consumers can derive initial
    state from events.jsonl instead of falling back to UNKNOWN.
    Idempotent: if a STATE_CHANGED event already exists for this ticket,
    returns early with status 'already_bootstrapped'.
    """
    plan_content = read_file(WORK_PLAN)
    plan_id = get_plan_id(plan_content)

    if is_invalid_plan_id(plan_id):
        if json_output:
            print(
                json.dumps(
                    {"error": "No active plan found", "status": "no_plan"}, indent=2
                )
            )
        else:
            print("[ERROR] No active plan found in work_plan.md")
        return 1

    if not BUS_AVAILABLE or not event_bus:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "skipped",
                        "reason": "bus_not_available",
                        "plan_id": plan_id,
                    },
                    indent=2,
                )
            )
        else:
            print(f"[WARN] Event bus not available. Skipping bootstrap for {plan_id}.")
        return 0

    latest_state_event = event_bus.latest_event(
        ticket_id=plan_id, event_type="STATE_CHANGED"
    )
    if latest_state_event:
        if json_output:
            print(
                json.dumps(
                    {"status": "already_bootstrapped", "plan_id": plan_id}, indent=2
                )
            )
        else:
            print(
                f"[INFO] Ticket {plan_id} already has STATE_CHANGED in bus. Skipping bootstrap."
            )
        return 0

    event_bus.emit(
        event_type="STATE_CHANGED",
        ticket_id=plan_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "Initial state bootstrap for launcher preflight",
            "source": "bootstrap",
        },
    )

    if json_output:
        print(json.dumps({"status": "bootstrapped", "plan_id": plan_id}, indent=2))
    else:
        print(f"[OK] Bootstrapped STATE_CHANGED -> IN_PROGRESS for {plan_id}")

    return 0


def _handle_resolve_launcher_roots(json_output: bool) -> int:
    """Handle --resolve-launcher-roots flag.

    WT-2026-232a: Single source of truth for launcher root resolution.
    Consumed by scripts/launch_agent_terminals.ps1 via JSON output.

    Before: PROJECT_ROOT must be set (either via --project-root or env var).
    During: Delegates to _resolve_launcher_roots() for deterministic resolution.
    After: Prints JSON or plain-text representation of the three roots.
           Returns 0 on success, 1 on error.
    """
    try:
        roots = _resolve_launcher_roots(PROJECT_ROOT)
        if json_output:
            print(json.dumps(roots, indent=2))
        else:
            for key, value in roots.items():
                print(f"{key}: {value}")
        return 0
    except RuntimeError as e:
        # WOT-2026-019d: SEGURO, no tocar. El unico raise RuntimeError de
        # resolve_launcher_roots usa un mensaje fijo con el nombre de una clave
        # de dict, nunca una ruta variable; RuntimeError no tiene .filename.
        print(f"[ERROR] {e}", file=sys.stderr, flush=True)
        return 1


# Pre-handoff helper (WP-2026-173)
# Live-surface constants: canonical source .agent/motor_checkpoint.py
_LIVE_SURFACES_REL = motor_checkpoint.LIVE_SURFACES_REL
_WORKSPACE_EXCLUDED_PREFIXES = motor_checkpoint.WORKSPACE_EXCLUDED_PREFIXES
_LIVE_SURFACE_DIRS = motor_checkpoint.LIVE_SURFACE_DIRS

# Motor checkpoint cluster: canonical source .agent/motor_checkpoint.py
# (name-stable aliases preserve internal call sites and test seams).
_build_live_surface_sets = motor_checkpoint.build_live_surface_sets
_is_live_surface = motor_checkpoint.is_live_surface
_path_is_under = motor_checkpoint.path_is_under
_parse_raw_flt_paths = motor_checkpoint.parse_raw_flt_paths
_resolve_motor_checkpoint_files = motor_checkpoint.resolve_motor_checkpoint_files
_contiguous_ticket_commits = motor_checkpoint.contiguous_ticket_commits
_files_from_commits = motor_checkpoint.files_from_commits
_resolve_git_head_sha = motor_checkpoint.resolve_git_head_sha
_print_motor_checkpoint_guidance = motor_checkpoint.print_motor_checkpoint_guidance
_resolve_git_tag_sha = motor_checkpoint.resolve_git_tag_sha
_is_git_ancestor_of_head = motor_checkpoint.is_git_ancestor_of_head
_resolve_launcher_roots = motor_checkpoint.resolve_launcher_roots
_resolve_destino_root = motor_checkpoint.resolve_destino_root
_resolve_workspace_root = motor_checkpoint.resolve_workspace_root
_try_motor_commit = motor_checkpoint.try_motor_commit
_try_motor_tag = motor_checkpoint.try_motor_tag


def _handle_pre_handoff(json_output: bool) -> int:  # noqa: C901
    """Handle --pre-handoff flag.

    Prepares the Builder handoff by:
    1. Parsing Files Likely Touched from work_plan.md
    2. Staging and committing delivery changes (if any)
    3. Creating/refreshing checkpoint M3 tag (checkpoint/review-<ticket>)
    4. Verifying the tree is clean (excluding live surfaces)

    Idempotent: if no delivery changes and checkpoint is already aligned with
    HEAD, exits cleanly without any action.

    Before: Requires an active plan in work_plan.md with a ticket ID.
    During: Runs git add, git commit (if changes), git tag operations, and
            git status --porcelain for final verification.
            Live surfaces (TURN.md, STATE.md, execution_log.md, events.jsonl,
            etc.) are excluded from dirty tree detection.
    After: Returns 0 on success, 1 on failure. On failure, prints diagnostic
           info. On success, the tree is ready for --mark-ready.
    """
    from bus.evidence import motor_uncommitted_productive

    plan_content = read_file(WORK_PLAN)
    if not plan_content:
        print("[ERROR] No work_plan.md found.", file=sys.stderr, flush=True)
        return 1

    # --- WT-2026-248a: BOM autocorrection for .opencode/opencode.json ---
    # WOT-2026-010f: this hygiene runs BEFORE the plan_id guard because it is
    # infrastructure cleanup of a motor-owned file, independent of any ticket.
    # The launcher finally-block may write the config via Set-Content -Encoding
    # UTF8 which prepends the UTF-8 BOM (EF BB BF).  Detect the exact residual:
    # bytes_actuales == BOM_UTF8 + bytes_head -- autocorrect if so.
    #
    # FLT gate: if .opencode/opencode.json is declared in Files Likely Touched,
    # DO NOT autocorrect - the file is in scope and the Builder may have made
    # legitimate changes. Fall through to normal scope/evidence rules.
    _opencode_path = _MOTOR_ROOT / ".opencode" / "opencode.json"
    if _opencode_path.exists():
        _dt_bom = _read_deliverable_type(plan_content)
        _flt_paths = _parse_raw_flt_paths(plan_content, deliverable_type=_dt_bom)
        _opencode_rel = ".opencode/opencode.json"
        if _opencode_rel not in {p.replace("\\", "/") for p in _flt_paths}:
            _bom_bytes = b"\xef\xbb\xbf"
            try:
                _head_proc = subprocess.run(
                    ["git", "show", "HEAD:.opencode/opencode.json"],
                    capture_output=True,
                    cwd=_MOTOR_ROOT.resolve(),
                    timeout=10,
                )
                if _head_proc.returncode == 0:
                    _head_bytes = _head_proc.stdout
                    _current_bytes = _opencode_path.read_bytes()
                    _expected_bom_drift = _bom_bytes + _head_bytes
                    if _current_bytes == _expected_bom_drift:
                        # Autocorrect: restore exact HEAD bytes
                        _opencode_path.write_bytes(_head_bytes)
                        print(
                            "[OK] Pre-handoff BOM autocorrected: "
                            ".opencode/opencode.json restored to HEAD (removed BOM drift).",
                            file=sys.stderr,
                            flush=True,
                        )
                    # else: no autocorrection - fall through to normal logic
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
    # --- end WT-2026-248a BOM autocorrection ---

    plan_id = get_plan_id(plan_content)
    if is_invalid_plan_id(plan_id):
        print("[ERROR] No active plan found.", file=sys.stderr, flush=True)
        return 1

    round_ok, process_round, round_reason = _ensure_active_builder_round(plan_id)

    # WT-2026-242b: Derive bus state for orphan detection.
    bus_state = None
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine

        events = event_bus.read_events(ticket_id=plan_id)
        if events:
            bus_state = StateMachine.derive_state_from_events(
                [e.to_dict() for e in events]
            )

    if not round_ok:
        # WT-2026-242b: Orphan containment - if ticket is past IN_PROGRESS,
        # emit STALE_BUILDER_ORPHAN instead of HANDOFF_BLOCKED.
        # This prevents stale shells from contaminating the bus post-success.
        was_orphan, msg = _maybe_handle_stale_builder_orphan(
            plan_id=plan_id,
            process_round=process_round,
            round_reason=round_reason,
            bus_state=bus_state,
        )
        if was_orphan:
            # WT-2026-249a: returncode governs; this is a non-fatal warning,
            # not an error. stdout keeps it visible for the operator; stderr
            # stays clean so consumers (email, CI, wrappers) don't treat a
            # healthy stale-shell exit as a failure.
            print(f"[WARN] {msg}", flush=True)
            # Return 0 so the stale shell exits cleanly without polluting the bus.
            return 0
        # Ticket is still IN_PROGRESS - maintain existing blocking behavior.
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="HANDOFF_BLOCKED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload={
                    "reason": "stale_builder_round",
                    "process_round": process_round,
                    "details": round_reason,
                },
            )
        print(
            f"[ERROR] Pre-handoff blocked for stale Builder shell: {round_reason}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # Check that we are in a git repository.
    # Model B: workspace (PROJECT_ROOT) and motor (_MOTOR_ROOT) are separate repos.
    # If the workspace has no .git, fall back to the motor root for git operations
    # while keeping project_root for live-surface detection (surfaces live in workspace).
    project_root = PROJECT_ROOT.resolve()
    motor_root = _MOTOR_ROOT.resolve()  # TP-11: declared before guard
    _dt_ph = _read_deliverable_type(plan_content)
    _delivery_authority_ph = _read_delivery_authority(plan_content)
    if (project_root / ".git").exists():
        git_root = project_root
    else:
        if (motor_root / ".git").exists():
            git_root = motor_root
        else:
            print(
                "[ERROR] Not a git repository. Pre-handoff requires git.",
                file=sys.stderr,
                flush=True,
            )
            return 1
    if (
        _dt_ph not in {"documentation", "research", "analysis"}
        and _delivery_authority_ph == "repo_destino"
        and not (project_root / ".git").exists()
    ):
        print(
            "[ERROR] delivery_authority=repo_destino requires PROJECT_ROOT to be "
            "a git repository.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # --- WOT-2026-009g: work_plan.md must be committed before any handoff ---
    # This check runs once, after project_root/motor_root are resolved and BEFORE
    # the three successful-return branches: (1) docs/research/analysis bypass,
    # (2) motor auto-commit, (3) idempotent no-op.
    # work_plan.md stays in LIVE_SURFACES_REL (exempt from dirty-tree); this is
    # an additional, separate rule: "the active contract must be committed".
    #
    # Fail-closed: this check IS the barrier closing the 008b false green. If
    # the helper raises (API drift, bug), BLOCK with a diagnostic instead of
    # letting an unhandled traceback or a silent pass reopen the false green.
    try:
        _wp_ok, _wp_diag = motor_checkpoint.assert_work_plan_committed(
            project_root=project_root,
            motor_root=motor_root,
        )
    except Exception as _wp_exc:
        print(
            "[ERROR] Pre-handoff blocked: work_plan commit guard could not run "
            f"({type(_wp_exc).__name__}: {_wp_exc}). Fix the guard before retrying.",
            file=sys.stderr,
            flush=True,
        )
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="HANDOFF_BLOCKED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload={
                    "reason": "work_plan_guard_error",
                    "error": f"{type(_wp_exc).__name__}: {_wp_exc}",
                },
            )
        return 1
    if not _wp_ok:
        _wp_path = _wp_diag.get("path", ".agent/collaboration/work_plan.md")
        _wp_remediation = _wp_diag.get(
            "remediation", "git add .agent/collaboration/work_plan.md && git commit"
        )
        print(
            f"[ERROR] Pre-handoff blocked: {_wp_path} is not committed.\n"
            f"  uncommitted_work_plan: true\n"
            f"  Fix: {_wp_remediation}",
            file=sys.stderr,
            flush=True,
        )
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="HANDOFF_BLOCKED",
                ticket_id=plan_id,
                actor="BUILDER",
                payload={
                    "reason": "uncommitted_work_plan",
                    "uncommitted_work_plan": True,
                    "path": _wp_path,
                    "remediation": _wp_remediation,
                },
            )
        return 1

    # --- WT-2026-239a: Docs/research/analysis early bypass ---
    # For non-code tickets, skip motor commit/tag/checkpoint and workspace
    # commit/tag. Only verify tree hygiene (excluding live surfaces).
    # WT-2026-240a: Block if motor has uncommitted productive changes.
    if _dt_ph in {"documentation", "research", "analysis"}:
        # WT-2026-240a: Check motor hygiene before bypass
        _motor_dirty_docs = motor_uncommitted_productive(motor_root)
        if _motor_dirty_docs:
            print(
                "Productive changes in repo_motor "
                "(documentation ticket bypass blocked):\n"
                + "\n".join(f"  {f}" for f in sorted(_motor_dirty_docs)),
                file=sys.stderr,
                flush=True,
            )
            if BUS_AVAILABLE and event_bus:
                event_bus.emit(
                    event_type="HANDOFF_BLOCKED",
                    ticket_id=plan_id,
                    actor="BUILDER",
                    payload={
                        "reason": "motor_uncommitted_productive_docs_bypass",
                        "deliverable_type": _dt_ph,
                        "productive_files": sorted(_motor_dirty_docs),
                    },
                )
            return 1
        # Continue with bypass (no motor commit/tag/checkpoint)
        _live_files_ph, _live_dirs_ph = _build_live_surface_sets(project_root)
        try:
            _status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=git_root,
            )
        except FileNotFoundError:
            print(
                "[ERROR] git not available for status check",
                file=sys.stderr,
                flush=True,
            )
            return 1
        _dirty_entries: list[str] = []
        if _status_result.stdout:
            for _line_raw in _status_result.stdout.splitlines():
                _line = _line_raw.strip()
                if not _line or len(_line_raw) < 3:
                    continue
                _path = _line_raw[3:].strip()
                _abs_git = str((git_root / _path).resolve())
                _abs_ws = str((project_root / _path).resolve())
                if not (
                    _is_live_surface(
                        _abs_git, project_root, _live_files_ph, _live_dirs_ph
                    )
                    or _is_live_surface(
                        _abs_ws, project_root, _live_files_ph, _live_dirs_ph
                    )
                ):
                    _dirty_entries.append(_path)
        if _dirty_entries:
            print(
                f"[ERROR] Tree dirty after pre-handoff: {', '.join(_dirty_entries)}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        _reset_circuit_breaker(plan_id)
        _capture_builder_session(plan_id, process_round or 1)
        if not json_output:
            print(
                f"[OK] Pre-handoff complete for {plan_id} "
                f"(deliverable_type={_dt_ph}). Tree is clean."
            )
        else:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "plan_id": plan_id,
                        "deliverable_type": _dt_ph,
                    },
                    indent=2,
                )
            )
        return 0

    # --- Commit-or-block for uncommitted productive motor changes ---
    # WT-2026-231a: Replace the simple barrier from WT-2026-228a with a
    # commit-or-block decision. If all motor productive changes are within
    # Files Likely Touched, auto-commit in repo_motor. If outside FLT, block.
    motor_uncommitted = motor_uncommitted_productive(motor_root)
    if motor_uncommitted:
        if _delivery_authority_ph == "repo_destino":
            print(
                "Productive changes in repo_motor during a repo_destino-authority "
                "ticket:\n" + "\n".join(f"  {f}" for f in sorted(motor_uncommitted)),
                file=sys.stderr,
                flush=True,
            )
            return 1
        flt_motor_paths = _parse_raw_flt_paths(plan_content, deliverable_type=_dt_ph)
        # Normalize both sets to motor-relative forward-slash paths (TP-06)
        motor_set = {f.replace("\\", "/") for f in motor_uncommitted}
        flt_set = {p.replace("\\", "/") for p in flt_motor_paths}
        outside_flt = motor_set - flt_set
        inside_flt = motor_set & flt_set

        if not outside_flt:
            # All motor changes within FLT: commit in motor_root (TP-02)
            commit_ok, commit_err = _try_motor_commit(
                motor_root, sorted(inside_flt), plan_id, json_output
            )
            if not commit_ok:
                print(commit_err, file=sys.stderr, flush=True)
                return 1
            # Create/refresh checkpoint tag in motor_root (TP-05, TP-12)
            tag_ok, tag_err = _try_motor_tag(motor_root, plan_id, json_output)
            if not tag_ok:
                print(tag_err, file=sys.stderr, flush=True)
                return 1
            _reset_circuit_breaker(plan_id)
            if not json_output:
                print(f"[OK] Pre-handoff complete for {plan_id}. Motor committed.")
            else:
                print(json.dumps({"status": "success", "plan_id": plan_id}, indent=2))
            return 0
        else:
            # Some motor changes outside FLT: block with diagnostic (TP-03)
            print(
                "Productive changes in repo_motor outside "
                "Files Likely Touched:\n"
                + "\n".join(f"  {f}" for f in sorted(outside_flt)),
                file=sys.stderr,
                flush=True,
            )
            return 1
    # No motor productive changes -> fall through to destination logic
    # (TP-04: mark-ready will block if there is no commit evidence)
    # --- end commit-or-block ---

    # Build live surface sets
    live_files, live_dirs = _build_live_surface_sets(project_root)

    # Parse Files Likely Touched (inline, already in this module)
    files_likely_touched = parse_files_likely_touched(plan_content)

    # Get changed files and filter out live surfaces
    changed_files = get_changed_files() or set()
    delivery_changes = {
        f
        for f in changed_files
        if not _is_live_surface(f, project_root, live_files, live_dirs)
    }

    # Determine files to stage: intersection of whitelist and delivery changes
    files_to_stage = set()
    if files_likely_touched and delivery_changes:
        files_to_stage = files_likely_touched & delivery_changes

    tag_name = f"checkpoint/review-{plan_id}"

    # Check current checkpoint state
    tag_exists = False
    tag_aligned = False
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"{tag_name}^{{}}"],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
        if result.returncode == 0:
            tag_exists = True
            tag_commit = result.stdout.strip()
            head_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=git_root,
            )
            tag_aligned = (
                head_result.returncode == 0 and tag_commit == head_result.stdout.strip()
            )
    except FileNotFoundError:
        print("[ERROR] git not available.", file=sys.stderr, flush=True)
        return 1

    needs_commit = bool(files_to_stage)

    # --- Step 1: Commit (if needed) ---
    if needs_commit:
        # Convert absolute paths to relative for git add (relative to git_root)
        rel_files = {
            str(Path(f).relative_to(git_root))
            for f in files_to_stage
            if _path_is_under(Path(f), git_root)
        }

        if rel_files:
            add_result = subprocess.run(
                ["git", "add", "--", *sorted(rel_files)],
                capture_output=True,
                text=True,
                cwd=git_root,
            )
            if add_result.returncode != 0:
                err = add_result.stderr.strip() or add_result.stdout.strip()
                print(
                    f"[ERROR] git add failed:\n{err}",
                    file=sys.stderr,
                    flush=True,
                )
                return 1

        commit_msg = f"chore({plan_id}): pre-handoff checkpoint"
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
        if commit_result.returncode != 0:
            # Propagate raw stderr verbatim for hook failures
            err = commit_result.stderr.strip() or commit_result.stdout.strip()
            print(err, file=sys.stderr, flush=True)
            return commit_result.returncode

        if not json_output:
            print(f"[OK] Committed: {commit_msg}")

        # After a new commit, the tag always needs refresh
        needs_tag = True
    else:
        needs_tag = not tag_aligned

    # --- Step 2: Create/refresh checkpoint M3 tag ---
    # WT-2026-245b / WOT-AUDIT-M3: In Model B topology legacy code/mixed tickets
    # tag repo_motor, while repo_destino-authority tickets tag git_root.
    if needs_tag:
        if motor_root != project_root and _delivery_authority_ph != "repo_destino":
            # Model B: delegate to _try_motor_tag which always operates on motor_root
            tag_ok, tag_err = _try_motor_tag(motor_root, plan_id, json_output)
            if not tag_ok:
                print(tag_err, file=sys.stderr, flush=True)
                return 1
        else:
            try:
                tag_msg = f"Checkpoint M3 for {plan_id}"
                if tag_exists:
                    delete_result = subprocess.run(
                        ["git", "tag", "-d", tag_name],
                        capture_output=True,
                        text=True,
                        cwd=git_root,
                    )
                    if delete_result.returncode != 0:
                        err = (
                            delete_result.stderr.strip() or delete_result.stdout.strip()
                        )
                        print(
                            f"[ERROR] Failed to delete tag {tag_name}:\n{err}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return 1

                tag_result = subprocess.run(
                    ["git", "tag", "-a", tag_name, "-m", tag_msg],
                    capture_output=True,
                    text=True,
                    cwd=git_root,
                )
                if tag_result.returncode != 0:
                    err = tag_result.stderr.strip() or tag_result.stdout.strip()
                    print(
                        f"[ERROR] Failed to create tag {tag_name}:\n{err}",
                        file=sys.stderr,
                        flush=True,
                    )
                    return 1

                if not json_output:
                    print(f"[OK] Created/refreshed tag: {tag_name}")
            except FileNotFoundError:
                print(
                    "[ERROR] git not available for tag operation",
                    file=sys.stderr,
                    flush=True,
                )
                return 1

    # --- Idempotent no-op case: no changes + tag already aligned ---
    if not needs_commit and tag_aligned:
        # A successful pre-handoff is the recovery point for a previously open
        # breaker: once the tree is clean and the checkpoint is aligned, the
        # Builder can proceed to --mark-ready on the next step.
        _reset_circuit_breaker(plan_id)
        if not json_output:
            print(
                f"[OK] No delivery changes. Checkpoint {tag_name}"
                " already aligned with HEAD."
            )
        else:
            print(json.dumps({"status": "idempotent", "plan_id": plan_id}, indent=2))
        return 0

    # --- Step 3: Final verification - tree must be clean ---
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
    except FileNotFoundError:
        print(
            "[ERROR] git not available for final status check",
            file=sys.stderr,
            flush=True,
        )
        return 1

    dirty_entries = []
    if status_result.stdout:
        for line_raw in status_result.stdout.splitlines():
            line = line_raw.strip()
            if not line or len(line_raw) < 3:
                continue
            # Extract path from raw line preserving git porcelain "XY <path>" format.
            # Using splitlines() avoids strip() eating the leading status space
            # on the first line of multi-line output.
            path = line_raw[3:].strip()
            # Model B: git status runs in git_root (motor) but live surfaces are
            # keyed on project_root (workspace). Check both resolved paths so that
            # auto-generated files like project-map.json are excluded regardless of
            # which root they fall under.
            abs_from_git = str((git_root / path).resolve())
            abs_from_ws = str((project_root / path).resolve())
            if not (
                _is_live_surface(abs_from_git, project_root, live_files, live_dirs)
                or _is_live_surface(abs_from_ws, project_root, live_files, live_dirs)
            ):
                dirty_entries.append(path)

    if dirty_entries:
        print(
            f"[ERROR] Tree still dirty after pre-handoff: {', '.join(dirty_entries)}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # The recovery path is complete: clear any open breaker so the next step
    # can execute the canonical --mark-ready closeout.
    _reset_circuit_breaker(plan_id)

    # WP-2026-180: Capture OpenCode session ID after successful pre-handoff.
    # Read the round from builder_lock.txt to compose the session title.
    current_round = process_round or 1
    _capture_builder_session(plan_id, current_round)

    if not json_output:
        print(f"[OK] Pre-handoff complete for {plan_id}. Tree is clean.")
    else:
        print(json.dumps({"status": "success", "plan_id": plan_id}, indent=2))
    return 0


# ── Closure invariants ───────────────────────────────────────────────────
# Bodies extracted to .agent/closure_invariants.py (monolith decomposition).
# These wrappers keep the module-global seams (BUS_AVAILABLE, event_bus,
# _read_circuit_breaker, _read_builder_lock) that tests monkeypatch.


def _check_bus_drift(plan_content: str, log_status: str) -> list[str]:
    """Check for drift between Markdown state and bus events."""
    if not BUS_AVAILABLE or not event_bus:
        return ["Event bus not available for drift detection"]
    plan_id = get_plan_id(plan_content)
    if is_invalid_plan_id(plan_id):
        return ["No active ticket found for bus drift check"]
    if _ticket_events_archived(plan_id):
        return []
    # WOT-2026-024q: bus ABSENT for the ticket + commit landed in origin/main ->
    # closure evidence satisfied by commit, not by bus (no fabrication). Bus
    # PRESENT but missing the required event stays a real drift (below).
    if not closure_invariants.bus_has_ticket_events(
        event_bus, plan_id
    ) and _ticket_landed_by_archived_commit(plan_id):
        return []
    return closure_invariants.check_bus_drift(event_bus, plan_id, log_status)


def _check_pre_closure_invariants(plan_id: str) -> list[str]:
    """Check pre-closure invariants (IN_PROGRESS, APPROVED, PENDING)."""
    if not BUS_AVAILABLE or not event_bus:
        return []
    return closure_invariants.check_pre_closure_invariants(event_bus, plan_id)


def _ticket_events_archived(plan_id: str) -> bool:
    """True when the ticket's bus events were rotated to the archive.

    archive_event_bus.py moves terminal tickets to
    .agent/runtime/events/archive/events.<ticket>.jsonl. Those archived
    events remain the canonical evidence: post-closure invariants must not
    report them as missing (otherwise every session close re-orphans the
    still-projected COMPLETED ticket - recurring drift seen with 251a).
    """
    archive_file = get_runtime_dir() / "events" / "archive" / f"events.{plan_id}.jsonl"
    return archive_file.exists()


def _ticket_landed_by_archived_commit(plan_id: str) -> bool:
    """True when the ticket's archived backlog row cites a commit that LANDED.

    WOT-2026-024q. In code-only closure (bus muerto), a ticket's canonical state
    is proven by its COMMIT reaching ``origin/main``, not by a bus event. The
    post-closure invariants only know how to verify by bus, so for a landed-by-
    commit ticket they emit spurious "no STATE_CHANGED"/"cannot verify" warnings.

    This recognizes the EXISTING evidence -- the archived
    ``_archive/backlog_done.md`` row + the landed-commit guard semantics -- WITHOUT
    fabricating any bus event. It reuses ``parse_archived_commits`` and ``audit``
    from ``scripts.check_backlog_commits_landed`` (import is NOT circular: that
    script imports neither agent_controller nor closure_invariants). ONLY the
    verdicts ``OK`` / ``OK_BY_SUBJECT`` count as landed -- ``PENDING_GROUPED_PUSH``
    (committed but unpushed), ``WARN`` (no git object) and ``ERROR`` (lost close)
    do NOT, so validate never blesses a close that has not actually reached
    origin/main.

    Before: ``plan_id`` non-empty. Reads the archive file and runs read-only git
    against the motor repo; never mutates.
    During: parses the archive, filters to this ticket's (id, sha) pairs, and
    classifies them against ``origin/main`` in the motor repo.
    After: returns True iff the ticket has at least one cited pair and ALL of
    them land as OK / OK_BY_SUBJECT (a grouped ``commit:sha1+sha2`` row must land
    in full); False on any read/parse/git error (fail-closed: unproven).
    """
    try:
        from scripts.check_backlog_commits_landed import audit, parse_archived_commits

        archive = get_collab_dir() / "_archive" / "backlog_done.md"
        content = archive.read_text(encoding="utf-8-sig")
        pairs = [
            (tid, sha) for tid, sha in parse_archived_commits(content) if tid == plan_id
        ]
        if not pairs:
            return False
        motor_root = _MOTOR_ROOT.resolve()
        results = audit(pairs, "origin/main", motor_root)
        # WOT-2026-024q (Codex-FS review): a row may cite SEVERAL grouped SHAs
        # (``commit:sha1+sha2``); parse_archived_commits emits one pair per SHA.
        # ALL of them must land -- ``any`` would bless a ticket whose landed SHA
        # sits beside a PENDING/ERROR sibling, the exact false-green 024q blocks.
        return bool(results) and all(
            r["verdict"] in ("OK", "OK_BY_SUBJECT") for r in results
        )
    except Exception:
        return False


def _check_post_closure_built_exit(
    plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check BUILDER_EXIT invariant. Returns (errors, warnings)."""
    if not BUS_AVAILABLE or not event_bus:
        return [], []
    # WOT-2026-058k: an invalid plan id ('-', none, N/A, ...) has no ticket
    # events by construction -- do not fabricate a bus lookup on the literal
    # string (measured: read_events(ticket_id="-") -> phantom warnings).
    if is_invalid_plan_id(plan_id):
        return [], []
    if _ticket_events_archived(plan_id):
        return [], []
    # WOT-2026-024q: see _check_bus_drift -- landed-by-commit + bus absent.
    if not closure_invariants.bus_has_ticket_events(
        event_bus, plan_id
    ) and _ticket_landed_by_archived_commit(plan_id):
        return [], []
    return closure_invariants.check_post_closure_built_exit(
        event_bus, plan_id, log_status
    )


def _check_post_closure_breaker(log_status: str) -> list[str]:
    """Check circuit breaker invariant. Returns errors."""
    return closure_invariants.check_post_closure_breaker(
        _read_circuit_breaker(), log_status
    )


def _check_post_closure_lock(plan_id: str, log_status: str) -> list[str]:
    """Check builder lock invariant. Returns warnings."""
    return closure_invariants.check_post_closure_lock(
        _read_builder_lock(), plan_id, log_status
    )


def _check_post_closure_state_changed(
    plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check STATE_CHANGED invariant. Returns (errors, warnings)."""
    if not BUS_AVAILABLE or not event_bus:
        return [], []
    # WOT-2026-058k: same as built_exit -- an invalid plan id must not
    # trigger a bus lookup on the literal string.
    if is_invalid_plan_id(plan_id):
        return [], []
    if _ticket_events_archived(plan_id):
        return [], []
    # WOT-2026-024q: see _check_bus_drift -- landed-by-commit + bus absent.
    if not closure_invariants.bus_has_ticket_events(
        event_bus, plan_id
    ) and _ticket_landed_by_archived_commit(plan_id):
        return [], []
    return closure_invariants.check_post_closure_state_changed(
        event_bus, plan_id, log_status
    )


def _check_builder_exit_order(plan_id: str) -> list[str]:
    """BUILDER_EXIT must precede STATE_CHANGED READY_FOR_REVIEW (warnings)."""
    if not BUS_AVAILABLE or not event_bus:
        return []
    return closure_invariants.check_builder_exit_order(event_bus, plan_id)


def _check_post_closure_invariants(plan_id: str, log_status: str) -> dict:
    """Check post-closure invariants (READY_FOR_REVIEW, COMPLETED)."""
    result = {"errors": [], "warnings": []}

    # Invariant 1: BUILDER_EXIT
    exit_errors, exit_warnings = _check_post_closure_built_exit(plan_id, log_status)
    result["errors"].extend(exit_errors)
    result["warnings"].extend(exit_warnings)

    # Invariant 2: Circuit breaker
    result["errors"].extend(_check_post_closure_breaker(log_status))

    # Invariant 3: Builder lock
    result["warnings"].extend(_check_post_closure_lock(plan_id, log_status))

    # Invariant 4: STATE_CHANGED
    state_errors, state_warnings = _check_post_closure_state_changed(
        plan_id, log_status
    )
    result["errors"].extend(state_errors)
    result["warnings"].extend(state_warnings)

    # Invariant 5: Order check - BUILDER_EXIT must come before STATE_CHANGED READY_FOR_REVIEW
    order_warnings = _check_builder_exit_order(plan_id)
    result["warnings"].extend(order_warnings)

    return result


def _check_invariants(plan_content: str, log_content: str, log_status: str) -> dict:
    """
    Check pre and post-closure invariants.
    Returns dict with 'errors' and 'warnings' lists.
    """
    result = {"errors": [], "warnings": []}
    plan_id = get_plan_id(plan_content)

    if is_invalid_plan_id(plan_id):
        result["warnings"].append("No active plan for invariant check")
        return result

    # Pre-closure invariants
    if log_status in ("IN_PROGRESS", "APPROVED", "PENDING"):
        result["warnings"].extend(_check_pre_closure_invariants(plan_id))

    # Post-closure invariants
    if log_status in ("READY_FOR_REVIEW", "COMPLETED"):
        result.update(_check_post_closure_invariants(plan_id, log_status))

    return result


def _check_scope_for_validate(
    plan_content: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check scope violations for validate command. Returns (errors, warnings).

    WOT-2026-009b: Uses productive diff root based on delivery_authority.
    For repo_motor tickets, validates motor diff against FLT ### repo_motor paths.
    For repo_destino tickets, validates destino diff against FLT destino paths.
    Only emits warnings when there are actual scope violations; a clean motor
    gate produces no warnings.

    WOT-2026-009c: Adds reciprocal isolation check. After the authority-side
    gate, inspects the non-authority root for productive (non-operational)
    changes and emits contaminacion_productiva warnings if found.
    """
    errors, warnings = [], []
    if "READY_FOR_REVIEW" not in log_status:
        return errors, warnings

    da = _read_delivery_authority(plan_content)

    if da == "repo_motor":
        flt = parse_flt_namespaced(plan_content)
        motor_whitelist = flt["motor"]
        if not motor_whitelist:
            warnings.append(
                "scope: No repo_motor paths in Files Likely Touched "
                f"(delivery_authority={da}). "
                "Add a ### repo_motor subsection or flat FLT paths. "
                "Re-validate: python .agent/agent_controller.py --validate --json "
                "--project-root <destino>"
            )
        else:
            changed_files = get_productive_changed_files(da) or set()
            out_of_scope = changed_files - motor_whitelist
            if out_of_scope:
                motor_root_str = str(_MOTOR_ROOT.resolve())

                def _to_rel(p: str) -> str:
                    try:
                        return str(Path(p).relative_to(motor_root_str))
                    except ValueError:
                        return p

                warnings.extend(
                    [
                        f"Out of scope (motor): {_to_rel(f)}"
                        for f in sorted(out_of_scope)
                    ]
                )
    else:
        changed_files_destino = get_changed_files()
        gate_result = check_scope_gate(
            plan_content, changed_files_destino, _exclude_files()
        )
        if not gate_result["valid"]:
            warnings.extend(
                [f"Out of scope: {f}" for f in sorted(gate_result["out_of_scope"])]
            )
        warnings.extend([f"Warning: {w}" for w in gate_result["warnings"]])

    # WOT-2026-009c: reciprocal isolation — inspect non-authority root
    cross = _check_cross_root_contamination(da)
    if cross["productive"]:
        other = "repo_destino" if da == "repo_motor" else "repo_motor"
        warnings.extend(
            f"contaminacion_productiva ({other}): {f}"
            for f in sorted(cross["productive"])
        )

    return errors, warnings


def _backfill_builder_exit(event_bus, ticket_id: str) -> bool:
    """Emit a synthetic BUILDER_EXIT if the bus has none for this ticket.

    Chat-driven closeouts skip --mark-ready, leaving the BUILDER_EXIT
    invariant permanently broken in --validate. A trailing BUILDER_EXIT is
    state-neutral (derive_state_from_events ignores it), so backfilling is
    safe even after SUPERVISOR_CLOSED.

    Returns True if an event was emitted.
    """
    # WOT-2026-058z: la guarda debe usar el MISMO predicado que el invariante.
    # WOT-2026-050a (3eaaac2) endurecio `validate` para DESCARTAR un
    # BUILDER_EXIT sintetico de reconcile_ticket, pero esta funcion -- de
    # 7407e84, ANTERIOR -- seguia contando cualquiera. Dos criterios
    # incompatibles sobre el MISMO evento: el invariante lo descartaba (=> ERROR
    # permanente) y el backfill lo veia (=> no reparaba). Un ticket reconciliado
    # quedaba sin reparacion barata: `--manager-approve` devolvia
    # `already_completed` sin emitir nada.
    # El evento que ESTA funcion emite NO es reconciliado, asi que una segunda
    # pasada sigue siendo no-op: la idempotencia se conserva.
    if closure_invariants._latest_real_builder_exit(event_bus, ticket_id) is not None:
        return False
    event_bus.emit(
        event_type="BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "exit_reason": "backfilled_closeout",
            "completion_summary": (
                "Synthesized by manager-approve: ticket was "
                "completed via chat flow without bus events."
            ),
            "source": "manager-approve-backfill",
        },
    )
    return True


def _emit_manager_approve_cascade(event_bus, ticket_id: str) -> None:
    """Emit the canonical closeout cascade for manager approve."""
    # 1. REVIEW_DECISION with approve
    event_bus.emit(
        event_type="REVIEW_DECISION",
        ticket_id=ticket_id,
        actor="MANAGER",
        payload={
            "decision": "approve",
            "note": "Canonical closeout approved",
            "source": "manager-approve",
        },
    )

    # 2. STATE_CHANGED -> READY_TO_CLOSE
    event_bus.emit(
        event_type="STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_FOR_REVIEW",
            "to_state": "READY_TO_CLOSE",
            "reason": "Manager approved canonical closeout",
            "source": "manager-approve",
        },
    )

    # 3. CLOSE_CONFIRMED
    event_bus.emit(
        event_type="CLOSE_CONFIRMED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "source": "manager_closeout",
            "reason": "Canonical closeout approved by Manager",
        },
    )

    # 4. STATE_CHANGED -> COMPLETED
    event_bus.emit(
        event_type="STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "from_state": "READY_TO_CLOSE",
            "to_state": "COMPLETED",
            "reason": "Canonical closeout completed",
            "source": "manager-approve",
        },
    )

    # 5. SUPERVISOR_CLOSED
    event_bus.emit(
        event_type="SUPERVISOR_CLOSED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "source": "manager-approve",
            "reason": "Canonical closeout completed",
        },
    )


def _sync_markdowns_to_completed(ticket_id: str) -> None:
    """Sync markdown files to COMPLETED state."""
    update_log_status(
        "COMPLETED", f"Manager approved canonical closeout for {ticket_id}"
    )

    # Normalize the execution log projections as well.
    exec_log_content = read_file(EXEC_LOG)
    if exec_log_content:
        updated_exec_log = exec_log_content
        updated_exec_log = updated_exec_log.replace(
            f"- Current state: {ticket_id} IN_PROGRESS",
            f"- Current state: {ticket_id} COMPLETED",
            1,
        )
        updated_exec_log = updated_exec_log.replace(
            "**Fase:** IMPLEMENTATION", "**Fase:** CLOSEOUT", 1
        )
        updated_exec_log = updated_exec_log.replace(
            "**Estado:** IN_PROGRESS", "**Estado:** COMPLETED", 1
        )
        write_file(EXEC_LOG, updated_exec_log)

    # Update work_plan.md to COMPLETED so the canonical ticket snapshot closes too.
    work_plan_content = read_file(WORK_PLAN)
    if work_plan_content:
        updated_work_plan = work_plan_content
        updated_work_plan = updated_work_plan.replace(
            "- **Estado:** APPROVED", "- **Estado:** COMPLETED", 1
        )
        # Chat-driven builders may set READY_FOR_REVIEW directly on the plan.
        updated_work_plan = updated_work_plan.replace(
            "- **Estado:** READY_FOR_REVIEW", "- **Estado:** COMPLETED", 1
        )
        updated_work_plan = updated_work_plan.replace(
            "- **Estado del ticket:** READY_FOR_REVIEW",
            "- **Estado del ticket:** COMPLETED",
            1,
        )
        updated_work_plan = updated_work_plan.replace(
            "- **Accion:** REVIEW_WORK", "- **Accion:** CLOSEOUT", 1
        )
        write_file(WORK_PLAN, updated_work_plan)

    # Update TURN.md for next cycle
    action = {
        "role": "MANAGER",
        "context_file": ".manager_rules",
        "workflow_file": ".agent/workflows/manager_workflow.md",
        "instruction": f"Ticket {ticket_id} closed. Create new work_plan.md for next cycle.",
        "plan_id": "N/A",
        "plan_status": "COMPLETED",
        "log_status": "COMPLETED",
        "action_type": "CREATE_PLAN",
    }
    update_turn_file(action)

    # Update STATE.md
    state_content = read_file(STATE_FILE)
    if state_content:
        updated_state = state_content
        updated_state = updated_state.replace(
            "- **Quality Gates:** PENDING (WP-2026-069 no ejecutado)",
            "- **Quality Gates:** GREEN (WP-2026-069 completed)",
            1,
        )
        updated_state = updated_state.replace(
            "- **Ultimo task en execution_log.md:** WP-2026-069 IN_PROGRESS",
            "- **Ultimo task en execution_log.md:** WP-2026-069 COMPLETED",
            1,
        )
        updated_state = updated_state.replace(
            "- **Estado actual:** READY_FOR_REVIEW",
            "- **Estado actual:** COMPLETED",
            1,
        )
        updated_state = re.sub(
            r"(?m)^STATUS:\s*\S+\s*$",
            "STATUS: COMPLETED",
            updated_state,
            count=1,
        )
        updated_state = re.sub(
            r"(?m)^Estado actual:\s*\S+\s*$",
            "Estado actual: COMPLETED",
            updated_state,
            count=1,
        )
        write_file(STATE_FILE, updated_state)


def _handle_manager_approve(  # noqa: C901 - flag handler intentionally branches across validation and closeout
    ticket_id: str, json_output: bool, force_mode: bool, dry_run: bool = False
) -> int:
    """
    Handle --manager-approve flag.
    Emits canonical closeout cascade:
    REVIEW_DECISION (approve) -> STATE_CHANGED READY_TO_CLOSE -> CLOSE_CONFIRMED ->
    STATE_CHANGED COMPLETED -> SUPERVISOR_CLOSED

    Validation:
    - ticket_id must be provided
    - ticket_id must match the active ticket in work_plan.md
    - Ticket must be in READY_FOR_REVIEW state
    - Idempotent: returns already_completed if ticket already has SUPERVISOR_CLOSED event in bus
    """
    if is_invalid_plan_id(ticket_id):
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WT-XXXX or WP-XXXX")
        return 1

    # Load current state
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    current_plan_id = get_plan_id(plan_content)
    log_status = get_status(log_content, "**Estado:**")

    # Validate ticket_id matches active ticket
    if is_invalid_plan_id(current_plan_id):
        if json_output:
            print(
                json.dumps(
                    {"error": "No active ticket found in work_plan.md"}, indent=2
                )
            )
        else:
            print("[ERROR] No active ticket found in work_plan.md")
        return 1

    if ticket_id != current_plan_id:
        if json_output:
            print(
                json.dumps(
                    {
                        "error": f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[ERROR] Ticket {ticket_id} does not match active ticket {current_plan_id}"
            )
        return 1

    # Check idempotency per-ticket using the current bus-derived state. A historical
    # SUPERVISOR_CLOSED is not sufficient after an explicit terminal reopen.
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine, TicketState

        supervisor_closed_events = event_bus.read_events(
            ticket_id=ticket_id, event_type="SUPERVISOR_CLOSED"
        )
        ticket_events = event_bus.read_events(ticket_id=ticket_id)
        if supervisor_closed_events and ticket_events:
            bus_state = StateMachine.derive_state_from_events(
                [event.to_dict() for event in ticket_events]
            )
        else:
            bus_state = None
        if supervisor_closed_events and bus_state == TicketState.COMPLETED:
            if dry_run:
                if json_output:
                    print(
                        json.dumps(
                            {
                                "status": "dry_run_preview",
                                "ticket_id": ticket_id,
                                "current_state": "COMPLETED",
                                "would_apply": "idempotent_noop",
                            },
                            indent=2,
                        )
                    )
                else:
                    print(
                        f"[DRY-RUN] Ticket {ticket_id} already COMPLETED; no action. No state mutated."
                    )
                return 0
            # Ticket already closed in bus - idempotent return. Still repair
            # a missing BUILDER_EXIT (chat-driven closeouts skip --mark-ready)
            # and re-sync markdown projections so --validate converges on the
            # bus-derived state.
            _backfill_builder_exit(event_bus, ticket_id)
            _sync_markdowns_to_completed(ticket_id)
            if json_output:
                print(
                    json.dumps(
                        {"status": "already_completed", "ticket_id": ticket_id},
                        indent=2,
                    )
                )
            else:
                print(
                    f"[INFO] Ticket {ticket_id} is already COMPLETED (SUPERVISOR_CLOSED event exists)."
                )
            return 0

    # Markdown says COMPLETED but the bus (canonical authority) has no
    # closeout: chat-driven closeouts leave this drift, and --validate then
    # fails permanently with no repair path. Backfill the canonical cascade
    # to reconcile toward the bus instead of returning passively.
    if "COMPLETED" in log_status:
        if dry_run:
            if json_output:
                print(
                    json.dumps(
                        {
                            "status": "dry_run_preview",
                            "ticket_id": ticket_id,
                            "current_state": "COMPLETED",
                            "would_apply": "backfill_closeout",
                        },
                        indent=2,
                    )
                )
            else:
                print(
                    f"[DRY-RUN] Ticket {ticket_id} markdown COMPLETED; would backfill closeout. No state mutated."
                )
            return 0
        if BUS_AVAILABLE and event_bus:
            _backfill_builder_exit(event_bus, ticket_id)
            _emit_manager_approve_cascade(event_bus, ticket_id)
            _sync_markdowns_to_completed(ticket_id)
            if json_output:
                print(
                    json.dumps(
                        {"status": "backfilled_closeout", "ticket_id": ticket_id},
                        indent=2,
                    )
                )
            else:
                print(
                    f"[OK] Ticket {ticket_id} was COMPLETED in markdown only; "
                    "canonical closeout cascade backfilled to bus."
                )
            return 0
        if json_output:
            print(
                json.dumps(
                    {"status": "already_completed", "ticket_id": ticket_id}, indent=2
                )
            )
        else:
            print(f"[INFO] Ticket {ticket_id} is already COMPLETED.")
        return 0

    # Check if ticket is in READY_FOR_REVIEW
    if "READY_FOR_REVIEW" not in log_status:
        if json_output:
            print(
                json.dumps(
                    {
                        "error": f"Ticket {ticket_id} is not in READY_FOR_REVIEW",
                        "current_state": log_status,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[ERROR] Ticket {ticket_id} is not in READY_FOR_REVIEW (current state: {log_status})"
            )
        return 1

    # WT-2026-239a: For documentation/research/analysis tickets, skip
    # last-commit validation (no manual commit requirement for docs).
    _dt_ma = _read_deliverable_type(plan_content)

    # WP-2026-188: Validate last commit message for closeout hygiene
    # Block generic checkpoints, wrong/missing ticket IDs unless --force
    if not force_mode and _dt_ma not in {"documentation", "research", "analysis"}:
        commit_root = _resolve_closeout_commit_root(_dt_ma, plan_content)
        commit_valid, commit_reason = _check_last_commit(commit_root, ticket_id)
        if not commit_valid:
            # Best-effort lookup of the literal last-commit text, purely for
            # display in the WARN message below. This is a separate, disposable
            # query (not reused by _check_last_commit/_validate_closeout_commit_message):
            # if git is unavailable or the query fails for any reason, silently
            # skip that line instead of breaking the already-decided gate result.
            last_commit_text = None
            try:
                _last_commit_result = subprocess.run(
                    ["git", "log", "-1", "--format=%s"],
                    capture_output=True,
                    text=True,
                    cwd=commit_root,
                )
                if _last_commit_result.returncode == 0:
                    _stripped = _last_commit_result.stdout.strip()
                    if _stripped:
                        last_commit_text = _stripped
            except Exception:
                last_commit_text = None

            warn_parts = [
                f"[WARN] Last commit validation failed: {commit_reason}",
            ]
            if last_commit_text is not None:
                warn_parts.append(f'[WARN] Last commit found: "{last_commit_text}"')
            warn_parts.extend(
                [
                    f"[WARN] Recommended: commit your closeout referencing ticket "
                    f"{ticket_id} with a meaningful message (not a generic "
                    f"checkpoint), then retry --manager-approve.",
                    "[WARN] Alternatively, if the last commit legitimately cannot "
                    "reference this ticket, use --force to approve anyway.",
                ]
            )
            warn_msg = "\n".join(warn_parts)
            print(warn_msg, file=sys.stderr, flush=True)
            return 1

    if dry_run:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "dry_run_preview",
                        "ticket_id": ticket_id,
                        "current_state": log_status,
                        "would_apply": "READY_FOR_REVIEW -> COMPLETED",
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[DRY-RUN] Would close ticket {ticket_id}: {log_status} -> COMPLETED. No state mutated."
            )
        return 0

    # Emit canonical closeout cascade
    if BUS_AVAILABLE and event_bus:
        _emit_manager_approve_cascade(event_bus, ticket_id)

    # Sync markdowns to COMPLETED
    _sync_markdowns_to_completed(ticket_id)

    # WP-2026-188: Clear auxiliary state files (bridge + supervisor cursors)
    # so the next ticket cycle starts with a clean slate
    _clear_auxiliary_states(ticket_id)

    # Reset circuit breaker on successful completion
    _reset_circuit_breaker(ticket_id)

    # Release builder lock
    _release_builder_lock(ticket_id)

    if json_output:
        print(json.dumps({"status": "closed", "ticket_id": ticket_id}, indent=2))
    else:
        print(f"[OK] Ticket {ticket_id} closed canonically.")

    return 0


def _materialize_state_transition(
    ticket_id: str,
    to_state: str,
    reason: str,
    actor: str = "SUPERVISOR",
    source: str = "canonical",
    allow_reentry: bool = False,
) -> None:
    """Materialize a state transition canonically.

    This is the shared route for all state transitions (approve, changes, inspect).
    WT-2026-211: the controller only emits the bus transition; the supervisor
    synchronizes TURN.md, STATE.md and execution_log.md from the derived state.

    Before: Requires ticket_id, to_state, reason, and optional actor/source.
    During: Emits STATE_CHANGED to bus and creates a HUMAN_GATE approval request
            when needed.
    After: The supervisor can materialize projections from the bus event.
    """
    log_content = read_file(EXEC_LOG)
    log_status = get_status(log_content, "**Estado:**")

    # Emit STATE_CHANGED to bus first (bus is the authority)
    if BUS_AVAILABLE and event_bus:
        event_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id=ticket_id,
            actor=actor,
            payload={
                "from_state": log_status,
                "to_state": to_state,
                "reason": reason,
                "source": source,
            },
            allow_reentry=allow_reentry,
        )

    # WP-2026-146: Create persistent ApprovalRequest when escalating to HUMAN_GATE
    if to_state == "HUMAN_GATE":
        _create_human_gate_approval_request(ticket_id)


def _handle_escalate_human_gate(ticket_id: str, json_output: bool) -> int:
    """Handle --escalate-human-gate flag for inspect decisions.

    This emits STATE_CHANGED -> HUMAN_GATE (actor SUPERVISOR) and synchronizes
    all projections (STATE.md, TURN.md, execution_log.md) via the canonical
    materialization route. Does NOT touch the rejection counter.

    Before: Requires ticket_id string.
    During: Calls _materialize_state_transition with to_state=HUMAN_GATE.
    After: All projections reflect HUMAN_GATE state, bus has STATE_CHANGED event.
    """
    if is_invalid_plan_id(ticket_id):
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WT-XXXX or WP-XXXX")
        return 1

    plan_content = read_file(WORK_PLAN)
    current_plan_id = get_plan_id(plan_content)

    if is_invalid_plan_id(current_plan_id):
        if json_output:
            print(json.dumps({"error": "No active ticket found"}, indent=2))
        else:
            print("[ERROR] No active ticket found in work_plan.md")
        return 1

    if ticket_id != current_plan_id:
        if json_output:
            print(
                json.dumps(
                    {
                        "error": f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[ERROR] Ticket {ticket_id} does not match active ticket {current_plan_id}"
            )
        return 1

    # Materialize the transition canonically
    _materialize_state_transition(
        ticket_id=ticket_id,
        to_state="HUMAN_GATE",
        reason="Manager inspect: human review required",
        actor="SUPERVISOR",
        source="escalate-human-gate",
    )

    if json_output:
        print(
            json.dumps(
                {"status": "escalated_to_human_gate", "ticket_id": ticket_id}, indent=2
            )
        )
    else:
        print(f"[OK] Ticket {ticket_id} escalated to HUMAN_GATE (inspect).")

    return 0


def _handle_resume_human_gate(ticket_id: str, json_output: bool) -> int:
    """Handle --resume-human-gate flag.

    Resolucion humana de un ticket en HUMAN_GATE: emite STATE_CHANGED ->
    READY_FOR_REVIEW (actor SUPERVISOR) y sincroniza las proyecciones via la
    ruta canonica de materializacion. Es la salida que faltaba al contrato de
    --escalate-human-gate. Solo valida si el estado derivado del bus es
    HUMAN_GATE.

    Before: Requires ticket_id; bus-derived state must be HUMAN_GATE.
    During: Verifies bus state, calls _materialize_state_transition.
    After: Ticket returns to READY_FOR_REVIEW for a fresh review cycle.
    """
    if is_invalid_plan_id(ticket_id):
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WT-XXXX or WP-XXXX")
        return 1

    current_plan_id = get_plan_id(read_file(WORK_PLAN))
    if ticket_id != current_plan_id:
        msg = f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    # El bus es la autoridad: solo se resume desde HUMAN_GATE.
    from bus.state_machine import StateMachine, TicketState

    bus_state = None
    if BUS_AVAILABLE and event_bus:
        events = event_bus.read_events(ticket_id=ticket_id)
        if events:
            bus_state = StateMachine.derive_state_from_events(
                [e.to_dict() for e in events]
            )
    if bus_state != TicketState.HUMAN_GATE:
        msg = (
            f"Ticket {ticket_id} bus state is {bus_state}, not HUMAN_GATE. "
            "--resume-human-gate solo aplica a tickets en HUMAN_GATE."
        )
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    _materialize_state_transition(
        ticket_id=ticket_id,
        to_state="READY_FOR_REVIEW",
        reason="Human resolution: resumed from HUMAN_GATE for a fresh review",
        actor="SUPERVISOR",
        source="resume-human-gate",
    )

    if json_output:
        print(
            json.dumps(
                {"status": "resumed_to_review", "ticket_id": ticket_id}, indent=2
            )
        )
    else:
        print(f"[OK] Ticket {ticket_id} resumed from HUMAN_GATE to READY_FOR_REVIEW.")

    return 0


def _handle_pause_ticket(ticket_id: str, reason: str, json_output: bool) -> int:  # noqa: C901
    """Handle --pause-ticket flag (WOT-2026-010d).

    Pauses the active ticket to address urgent hotfixes. Transitions from
    IN_PROGRESS to PAUSED with mandatory reason, captures git state, emits
    TICKET_PAUSED event, and writes canonical artifact in repo_destino.

    Before: Requires matching ticket_id and non-empty reason.
    During: Captures diff, creates stash if needed, emits TICKET_PAUSED.
    After: Ticket in PAUSED state; artifact written to .agent/collaboration/paused/.

    Returns 0 on success, 1 on validation failure.
    """
    if is_invalid_plan_id(ticket_id):
        msg = "No ticket_id provided. Use --ticket WOT-XXXX-NNNx"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    if not reason or not reason.strip():
        msg = "Pause reason is required. Use --reason 'description'"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    current_plan_id = get_plan_id(read_file(WORK_PLAN))
    if ticket_id != current_plan_id:
        msg = f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    # Check if already paused
    import subprocess
    from datetime import datetime, timezone

    dest_root = resolve_project_root()
    paused_dir = dest_root / ".agent" / "collaboration" / "paused"
    paused_artifact = paused_dir / f"{ticket_id}.json"

    if paused_artifact.exists():
        msg = (
            f"Ticket {ticket_id} is already paused. "
            "Use --resume-ticket or --abort-paused-ticket."
        )
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    # Capture git state
    try:
        # Get changed files
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
        changed_files = (
            result.stdout.strip().split("\n") if result.stdout.strip() else []
        )

        # Get diff stat
        diff_result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            check=False,
        )
        diff_stat = diff_result.stdout.strip() if diff_result.stdout.strip() else ""

        stash_ref = None
        if changed_files and changed_files[0]:  # Tree is dirty
            # Create stash
            stash_result = subprocess.run(
                ["git", "stash", "push", "-m", f"WOT-2026-010d pause: {reason}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if stash_result.returncode == 0:
                # Extract stash ref from git stash show
                list_result = subprocess.run(
                    ["git", "stash", "list"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if list_result.stdout.startswith("stash@{0}"):
                    stash_ref = "stash@{0}"  # Reference, not the name
                else:
                    stash_ref = "stash"  # Fallback marker

        # Get bus sequences
        bus_last_seq = 0
        ticket_last_seq = 0
        if BUS_AVAILABLE and event_bus:
            bus_last_seq = event_bus.get_last_sequence()
            events = event_bus.read_events(ticket_id=ticket_id)
            if events:
                ticket_last_seq = events[-1].seq if hasattr(events[-1], "seq") else 0

        # Write artifact
        paused_dir.mkdir(parents=True, exist_ok=True)
        artifact = {
            "ticket_id": ticket_id,
            "status": "PAUSED",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "repo": "motor",
            "changed_paths": changed_files,
            "diff_stat": diff_stat,
            "stash_ref": stash_ref,
            "wip_commit": None,
            "bus_last_seq_global": bus_last_seq,
            "ticket_last_seq": ticket_last_seq,
            "state_snapshot": {},
            "turn_snapshot": {},
            "resume_instructions": "Use --resume-ticket to restore changes",
        }

        paused_artifact.write_text(json.dumps(artifact, indent=2))

        # Emit bus event
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="TICKET_PAUSED",
                ticket_id=ticket_id,
                payload={
                    "reason": reason,
                    "changed_paths": changed_files,
                    "stash_ref": stash_ref,
                },
            )

        # Update STATE.md (keep ACTIVE_TICKET, change STATUS to PAUSED)
        state_path = resolve_project_root() / ".agent" / "collaboration" / "STATE.md"
        if state_path.exists():
            state_text = state_path.read_text()
            # Replace STATUS line
            import re

            state_text = re.sub(
                r"STATUS:.*",
                "STATUS: PAUSED",
                state_text,
            )
            state_path.write_text(state_text)

        if json_output:
            print(
                json.dumps(
                    {
                        "status": "paused",
                        "ticket_id": ticket_id,
                        "reason": reason,
                        "artifact": str(paused_artifact),
                    },
                    indent=2,
                )
            )
        else:
            print(f"[OK] Ticket {ticket_id} paused: {reason}")

        return 0

    except Exception as e:
        msg = f"Pause failed: {e!s}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1


def _handle_resume_ticket(ticket_id: str, json_output: bool) -> int:  # noqa: C901
    """Handle --resume-ticket flag (WOT-2026-010d).

    Resumes a paused ticket: restores changes from stash, checks bus for
    intervening events, emits TICKET_RESUMED, and transitions back to
    IN_PROGRESS. Fails safely if conflicts detected.

    Before: Requires matching ticket_id; pause artifact must exist and be valid.
    During: Verifies stash/ref resoluble, checks bus for ticket-specific events.
    After: Ticket returns to IN_PROGRESS; pause artifact deleted.

    Returns 0 on success, 1 on validation failure.
    """
    if is_invalid_plan_id(ticket_id):
        msg = "No ticket_id provided. Use --ticket WOT-XXXX-NNNx"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    current_plan_id = get_plan_id(read_file(WORK_PLAN))
    if ticket_id != current_plan_id:
        msg = f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    # Check if pause artifact exists
    import subprocess

    dest_root = resolve_project_root()
    paused_dir = dest_root / ".agent" / "collaboration" / "paused"
    paused_artifact = paused_dir / f"{ticket_id}.json"

    if not paused_artifact.exists():
        msg = f"No pause artifact for {ticket_id}. Use --pause-ticket to pause first."
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    try:
        # Load artifact
        artifact = json.loads(paused_artifact.read_text())

        # Check if bus advanced for this ticket
        if BUS_AVAILABLE and event_bus:
            ticket_last_seq_saved = artifact.get("ticket_last_seq", 0)
            events = event_bus.read_events(ticket_id=ticket_id)
            if events:
                latest_seq = events[-1].seq if hasattr(events[-1], "seq") else 0
                if latest_seq > ticket_last_seq_saved:
                    msg = (
                        f"Ticket {ticket_id} has advanced since pause "
                        f"(saved seq {ticket_last_seq_saved}, now {latest_seq}). "
                        "Cannot resume. Use --abort-paused-ticket or reopen manually."
                    )
                    if json_output:
                        print(json.dumps({"error": msg}, indent=2))
                    else:
                        print(f"[ERROR] {msg}")
                    return 1

        # Restore stash if needed
        stash_ref = artifact.get("stash_ref")
        if stash_ref:
            apply_result = subprocess.run(
                ["git", "stash", "apply", stash_ref],
                capture_output=True,
                text=True,
                check=False,
            )
            if apply_result.returncode != 0:
                msg = (
                    "Stash apply failed with conflicts. "
                    "Tree left clean. Manual resolution required."
                )
                if json_output:
                    print(json.dumps({"error": msg}, indent=2))
                else:
                    print(f"[ERROR] {msg}")
                return 1

        # Emit bus event
        if BUS_AVAILABLE and event_bus:
            event_bus.emit(
                event_type="TICKET_RESUMED",
                ticket_id=ticket_id,
                payload={"from_paused": True},
            )

            # Transition back to IN_PROGRESS
            _materialize_state_transition(
                ticket_id=ticket_id,
                to_state="IN_PROGRESS",
                reason="Resumed from PAUSED state",
                actor="BUILDER",
                source="resume-ticket",
            )

        # Delete artifact
        paused_artifact.unlink()

        if json_output:
            print(
                json.dumps(
                    {"status": "resumed", "ticket_id": ticket_id},
                    indent=2,
                )
            )
        else:
            print(f"[OK] Ticket {ticket_id} resumed to IN_PROGRESS.")

        return 0

    except Exception as e:
        msg = f"Resume failed: {e!s}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1


def _handle_abort_paused_ticket(ticket_id: str, reason: str, json_output: bool) -> int:  # noqa: C901
    """Handle --abort-paused-ticket flag (WOT-2026-010d).

    Aborts a paused ticket: records abort reason in artifact, cleans up stash,
    and transitions to a terminal state or explicit abort marker.

    Before: Requires matching ticket_id; pause artifact must exist.
    During: Records abort reason, removes stash (if any).
    After: Pause marked as aborted; stash discarded.

    Returns 0 on success, 1 on validation failure.

    NOTE: This is a v1 stub. Full abort workflow may require additional
    cleanup or escalation logic in future versions.
    """
    if is_invalid_plan_id(ticket_id):
        msg = "No ticket_id provided. Use --ticket WOT-XXXX-NNNx"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    current_plan_id = get_plan_id(read_file(WORK_PLAN))
    if ticket_id != current_plan_id:
        msg = f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    # Check if pause artifact exists
    import subprocess
    from datetime import datetime, timezone

    dest_root = resolve_project_root()
    paused_dir = dest_root / ".agent" / "collaboration" / "paused"
    paused_artifact = paused_dir / f"{ticket_id}.json"

    if not paused_artifact.exists():
        msg = f"No pause artifact for {ticket_id}. Nothing to abort."
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    try:
        # Load and update artifact
        artifact = json.loads(paused_artifact.read_text())
        artifact["abort_reason"] = reason
        artifact["aborted_at"] = datetime.now(timezone.utc).isoformat()
        artifact["aborted_by"] = "BUILDER"
        artifact["status"] = "ABORTED"

        paused_artifact.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

        # Try to discard stash
        stash_ref = artifact.get("stash_ref")
        if stash_ref and stash_ref != "stash":
            subprocess.run(
                ["git", "stash", "drop", stash_ref],
                capture_output=True,
                check=False,
            )

        if json_output:
            print(
                json.dumps(
                    {
                        "status": "aborted",
                        "ticket_id": ticket_id,
                        "reason": reason,
                    },
                    indent=2,
                )
            )
        else:
            print(f"[OK] Pause for {ticket_id} aborted: {reason}")

        return 0

    except Exception as e:
        msg = f"Abort failed: {e!s}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1


def _handle_reopen_terminal_ticket(  # noqa: C901 - flag handler validates bus state and projections
    ticket_id: str, json_output: bool
) -> int:
    """Handle --reopen-terminal-ticket flag.

    Explicit human-controlled recovery path for a ticket already in COMPLETED.
    Reopens the active ticket to IN_PROGRESS by bypassing the EventBus reentry
    guard intentionally. This is reserved for canonical repair flows.
    """
    if is_invalid_plan_id(ticket_id):
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WT-XXXX or WP-XXXX")
        return 1

    current_plan_id = get_plan_id(read_file(WORK_PLAN))
    if ticket_id != current_plan_id:
        msg = f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    if not BUS_AVAILABLE or not event_bus:
        msg = "EventBus unavailable; cannot reopen terminal ticket canonically."
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    from bus.state_machine import StateMachine, TicketState

    events = event_bus.read_events(ticket_id=ticket_id)
    if not events:
        msg = f"No bus events found for ticket {ticket_id}."
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
    if bus_state != TicketState.COMPLETED:
        msg = (
            f"Ticket {ticket_id} bus state is {bus_state}, not COMPLETED. "
            "--reopen-terminal-ticket solo aplica a tickets terminales."
        )
        if json_output:
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(f"[ERROR] {msg}")
        return 1

    _materialize_state_transition(
        ticket_id=ticket_id,
        to_state="IN_PROGRESS",
        reason="Human recovery: reopen terminal ticket for canonical repair cycle",
        actor="SUPERVISOR",
        source="reopen-terminal-ticket",
        allow_reentry=True,
    )

    update_log_status(
        "IN_PROGRESS",
        f"Terminal reopen requested by human for {ticket_id}",
    )

    try:
        from scripts.state_projection_sync import sync_state_projection

        sync_state_projection(
            runtime_dir=get_runtime_dir() / "events",
            collaboration_dir=get_collab_dir(),
            ticket_id=ticket_id,
        )
    except OSError as exc:
        # WOT-2026-019d: sync_state_projection hace state_md_path.write_text
        # (ruta absoluta bajo collaboration_dir); un OSError real trae
        # .filename. Componer el mensaje a mano sin exponer la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        if not json_output:
            print(
                f"[WARN] Ticket {ticket_id} reopened in bus, but projection sync "
                f"failed: {detail}",
                file=sys.stderr,
            )
    except Exception as exc:
        if not json_output:
            print(
                f"[WARN] Ticket {ticket_id} reopened in bus, but projection sync "
                f"failed: {exc}",
                file=sys.stderr,
            )

    if json_output:
        print(
            json.dumps(
                {"status": "reopened_to_in_progress", "ticket_id": ticket_id},
                indent=2,
            )
        )
    else:
        print(f"[OK] Ticket {ticket_id} reopened from COMPLETED to IN_PROGRESS.")

    return 0


def _assert_bus_projection_consistency(ticket_id: str) -> list[str]:
    """Assert that bus-derived state matches projection state.

    WP-2026-124: Post-cycle verification that bus and projections are aligned.
    Does NOT auto-heal - returns warnings for manual intervention.

    Before: Requires ticket_id string.
    During: Compares bus-derived state with STATE.md and execution_log.md states.
    After: Returns list of drift warnings (empty if consistent).
    """
    warnings = []
    if not BUS_AVAILABLE or not event_bus:
        warnings.append("Bus not available for consistency check")
        return warnings

    # Get bus-derived state
    events = event_bus.read_events(ticket_id=ticket_id)
    if not events:
        warnings.append(f"No events in bus for ticket {ticket_id}")
        return warnings

    from bus.state_machine import StateMachine

    bus_state = StateMachine.derive_state_from_events([e.to_dict() for e in events])

    # Get projection states
    state_content = read_file(STATE_FILE)
    exec_log_content = read_file(EXEC_LOG)

    state_md_state = (
        get_status(state_content, "**Estado actual:**") if state_content else "UNKNOWN"
    )
    exec_log_state = (
        get_status(exec_log_content, "**Estado:**") if exec_log_content else "UNKNOWN"
    )

    # Compare
    if bus_state.value != state_md_state:
        warnings.append(
            f"DRIFT: bus_state={bus_state.value} != STATE.md={state_md_state}"
        )
    if bus_state.value != exec_log_state:
        warnings.append(
            f"DRIFT: bus_state={bus_state.value} != execution_log.md={exec_log_state}"
        )

    return warnings


def _handle_request_changes(  # noqa: C901
    ticket_id: str, json_output: bool, force_mode: bool
) -> int:
    """
    Handle --request-changes flag.
    Transitions ticket to IN_PROGRESS (requeue builder) if N < threshold, or
    HUMAN_GATE if N >= threshold. The threshold is the single source of truth
    in agents.json (manager_review.max_attempts); see get_human_gate_threshold().

    WP-2026-124: Now uses bus-derived state via _materialize_state_transition.
    WP-2026-152: Derives pending_requeue from already-read events slice (events[-1]),
      not a second latest_event() bus read. Accepts IN_PROGRESS only when
      REVIEW_DECISION=changes is the direct antecedent. UNKNOWN falls back to
      execution_log path. Generic IN_PROGRESS without that antecedent fails closed.
    """
    if is_invalid_plan_id(ticket_id):
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WT-XXXX or WP-XXXX")
        return 1

    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    current_plan_id = get_plan_id(plan_content)
    log_status = get_status(log_content, "**Estado:**")

    if is_invalid_plan_id(current_plan_id):
        if json_output:
            print(
                json.dumps(
                    {"error": "No active ticket found in work_plan.md"}, indent=2
                )
            )
        else:
            print("[ERROR] No active ticket found in work_plan.md")
        return 1

    if ticket_id != current_plan_id:
        if json_output:
            print(
                json.dumps(
                    {
                        "error": f"Ticket {ticket_id} does not match active ticket {current_plan_id}"
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[ERROR] Ticket {ticket_id} does not match active ticket {current_plan_id}"
            )
        return 1

    # WP-2026-124 + WP-2026-152: Check bus-derived state with explicit branching.
    # Derive pending_requeue from the already-read events slice, not a second read.
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine, TicketState

        events = event_bus.read_events(ticket_id=ticket_id)
        bus_state = (
            StateMachine.derive_state_from_events([e.to_dict() for e in events])
            if events
            else TicketState.UNKNOWN
        )

        # WP-2026-152: Derive pending_requeue from events[-1] when present.
        # Do not perform a second latest_event() bus read.
        pending_requeue = False
        if events:
            latest_event = events[-1]
            if (
                latest_event.event_type == "REVIEW_DECISION"
                and str((latest_event.payload or {}).get("decision", "")).lower()
                == "changes"
            ):
                pending_requeue = True

        # Explicit branching per WP-2026-152:
        # - UNKNOWN: fall back to execution_log path
        # - READY_FOR_REVIEW: proceed normally
        # - IN_PROGRESS: only accept when pending_requeue is true (direct changes antecedent)
        # - Other states: fail closed
        if bus_state == TicketState.UNKNOWN:
            # Fallback to execution_log.md when bus has no usable state
            if "READY_FOR_REVIEW" not in log_status:
                if json_output:
                    print(
                        json.dumps(
                            {"error": f"Ticket {ticket_id} is not in READY_FOR_REVIEW"},
                            indent=2,
                        )
                    )
                else:
                    print(
                        f"[ERROR] Ticket {ticket_id} is not in READY_FOR_REVIEW (current state: {log_status})"
                    )
                return 1
            # Continue with execution_log fallback path below
        elif bus_state == TicketState.READY_FOR_REVIEW:
            # Proceed normally - no pending_requeue check needed
            pass
        elif bus_state == TicketState.IN_PROGRESS:
            # Only accept IN_PROGRESS when pending_requeue is true (direct changes antecedent)
            if not pending_requeue:
                if json_output:
                    print(
                        json.dumps(
                            {
                                "error": f"Ticket {ticket_id} is IN_PROGRESS without pending_requeue antecedent"
                            },
                            indent=2,
                        )
                    )
                else:
                    print(
                        f"[ERROR] Ticket {ticket_id} is IN_PROGRESS without pending_requeue antecedent (generic IN_PROGRESS fails closed)"
                    )
                return 1
            # Accept the requeue - continue below
        else:
            # All other states fail closed
            if json_output:
                print(
                    json.dumps(
                        {
                            "error": f"Ticket {ticket_id} bus state is {bus_state.value} (fails closed)"
                        },
                        indent=2,
                    )
                )
            else:
                print(
                    f"[ERROR] Ticket {ticket_id} bus state is {bus_state.value} (fails closed)"
                )
            return 1

    rejection_count = 0
    if BUS_AVAILABLE and event_bus:
        # Single source of truth for the consecutive count: bus.utils.
        # A history of changes->approve->changes counts as 1, not 2.
        rejection_count = count_trailing_changes(
            event_bus.read_events(ticket_id=ticket_id, event_type="REVIEW_DECISION")
        )

        # If the latest event is not already a REVIEW_DECISION->changes (e.g.
        # --request-changes invoked manually without the bridge), emit one so
        # the bus stays the single source of truth. The bridge path already
        # emits it, so this is a no-op there (no duplicate).
        # WP-2026-152: Use events[-1] already read, not a second latest_event() call.
        latest = events[-1] if events else event_bus.latest_event(ticket_id=ticket_id)
        if (
            not latest
            or latest.event_type != "REVIEW_DECISION"
            or str((latest.payload or {}).get("decision", "")).lower() != "changes"
        ):
            event_bus.emit(
                event_type="REVIEW_DECISION",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload={
                    "decision": "changes",
                    "source": "agent_controller",
                },
            )
            # Recompute from the bus now that this changes is recorded.
            rejection_count = count_trailing_changes(
                event_bus.read_events(ticket_id=ticket_id, event_type="REVIEW_DECISION")
            )

        threshold = get_human_gate_threshold()
        to_state = "HUMAN_GATE" if rejection_count >= threshold else "IN_PROGRESS"
        reason = (
            f"Manager requested changes ({rejection_count} rejections)"
            if rejection_count < threshold
            else f"Escalated to HUMAN_GATE after {rejection_count} rejections"
        )

        # WP-2026-124: Use canonical materialization route
        _materialize_state_transition(
            ticket_id=ticket_id,
            to_state=to_state,
            reason=reason,
            actor="SUPERVISOR",
            source="request-changes",
        )
    else:
        to_state = "IN_PROGRESS"
        # Fallback: legacy route without bus
        update_log_status(
            to_state,
            f"Manager requested changes ({rejection_count} rejections). Requeuing Builder.",
        )
        action = {
            "role": "BUILDER",
            "context_file": ".builder_rules",
            "workflow_file": ".agent/workflows/builder_workflow.md",
            "instruction": f"Manager requested changes on {ticket_id}. Re-implement fixes.",
            "plan_id": ticket_id,
            "plan_status": get_status(plan_content, "**Estado:**"),
            "log_status": to_state,
            "action_type": "IMPLEMENT",
            "plan_type": get_plan_type(plan_content),
        }
        update_turn_file(action)
        state_content = read_file(STATE_FILE)
        if state_content:
            updated_state = state_content.replace(
                "- **Estado actual:** READY_FOR_REVIEW",
                "- **Estado actual:** IN_PROGRESS",
                1,
            )
            write_file(STATE_FILE, updated_state)

    if to_state == "HUMAN_GATE":
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "escalated_to_human_gate",
                        "ticket_id": ticket_id,
                        "rejections": rejection_count,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[OK] Ticket {ticket_id} escalated to HUMAN_GATE after {rejection_count} rejections."
            )
    else:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "changes_requested",
                        "ticket_id": ticket_id,
                        "rejections": rejection_count,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[OK] Ticket {ticket_id} transitioned to IN_PROGRESS ({rejection_count} rejections)."
            )

    return 0


def _collect_deliverable_type_warnings(plan_content: str) -> dict[str, list[str]]:
    """Helper for _handle_validate: returns {file: [warnings]} or {} if clean."""
    if not plan_content:
        return {}
    deliverable_warnings = _check_deliverable_type(plan_content)
    if not deliverable_warnings:
        return {}
    return {"work_plan.md": deliverable_warnings}


def _handle_validate(json_output: bool, no_heal: bool = False) -> int:  # noqa: C901
    """Handle --validate flag.

    Aggregates many independent validators (state files, scope, bus drift,
    deliverable_type, ticket_prose). Each branch is simple; the function is intentionally
    a thin coordinator. Splitting it further would harm readability.
    """
    errors = validate_state_files()
    warnings = {}

    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    seed_neutral = state_validation.is_seed_neutral_state(plan_content, log_content)
    for file_key, warns in _collect_deliverable_type_warnings(plan_content).items():
        warnings.setdefault(file_key, []).extend(warns)

    log_status = get_status(log_content, "**Estado:**")

    # WP-2026-162: Ticket prose validation
    if not seed_neutral:
        try:
            from scripts.validate_ticket_prose import validate_ticket_prose

            prose_result = validate_ticket_prose(WORK_PLAN, get_collab_dir())
            if prose_result["warnings"]:
                # Convert ProseWarning dicts to strings for consistent warning format
                prose_warnings = [
                    f"[{w['rule_id']}] {w['rule_name']}: {w['suggestion']}"
                    for w in prose_result["warnings"]
                ]
                warnings.setdefault("ticket_prose", []).extend(prose_warnings)
        except ImportError:
            pass  # Gracefully degrade if validator not available

    # WOT-2026-019f: validate the ACTIVE ticket's Reactivation format early.
    # The backlog contract (structured Reactivation) used to be enforced ONLY at
    # --session-close (prepush_check, closeout_mode), so a Reactivation written in
    # free prose passed the per-ticket --validate and blocked the close hours
    # later, far from the write that caused it. We validate here too, but scoped
    # to the ACTIVE ticket only: validate_backlog checks the WHOLE live queue, and
    # failing --validate on another ticket's historical debt would block unrelated
    # work.
    if not seed_neutral:
        try:
            from scripts.check_backlog_contract import validate_backlog

            active_id = get_plan_id(plan_content)
            backlog_path = get_collab_dir() / "backlog.md"
            if active_id and backlog_path.exists():
                backlog_violations = validate_backlog(backlog_path)
                # Error strings are formatted "<ticket>: <detail>"; keep only the
                # active ticket's Reactivation/status violations.
                own = [
                    v
                    for v in backlog_violations
                    if v.startswith(f"{active_id}:")
                    and ("Reactivation" in v or "status" in v)
                ]
                if own:
                    errors.setdefault("backlog_reactivation", []).extend(own)
        except ImportError:
            pass  # Gracefully degrade if the contract checker is unavailable.

    # Check scope violations
    if not seed_neutral:
        scope_errors, scope_warnings = _check_scope_for_validate(
            plan_content, log_status
        )
        if scope_errors:
            errors.setdefault("scope", []).extend(scope_errors)
        if scope_warnings:
            warnings.setdefault("scope", []).extend(scope_warnings)

    # Check bus drift - heal first (unless --no-heal), then report any residual.
    # WOT-2026-024a: a READ-ONLY caller (e.g. scripts/collect_system_health.py,
    # which AGENTS.md documents as a read-only collector) passes no_heal=True so
    # --validate NEVER writes the git-TRACKED STATE.md via sync_state_projection
    # (state_projection_sync.py write_text on DRIFTED). The residual drift is
    # still REPORTED as a warning below -- read-only observation, not mutation.
    if not seed_neutral:
        if not no_heal:
            try:
                from scripts.state_projection_sync import sync_state_projection

                sync_state_projection(
                    runtime_dir=get_runtime_dir() / "events",
                    collaboration_dir=get_collab_dir(),
                    ticket_id=get_plan_id(plan_content),
                )
            except Exception:  # noqa: S110 - sync is best-effort and must not block validate
                pass
        drift_warnings = _check_bus_drift(plan_content, log_status)
        if drift_warnings:
            warnings.setdefault("bus_drift", []).extend(drift_warnings)

    # Check invariants (pre and post-closure)
    if not seed_neutral:
        invariant_result = _check_invariants(plan_content, log_content, log_status)
        if invariant_result["errors"]:
            errors.setdefault("invariants", []).extend(invariant_result["errors"])
        if invariant_result["warnings"]:
            warnings.setdefault("invariants", []).extend(invariant_result["warnings"])

    # WOT-2026-007f: Check CONTRACT_GAP event ↔ CG-*.md file coherence.
    if not seed_neutral:
        cg_errors = _validate_contract_gap_coherence(plan_content)
        if cg_errors:
            errors.setdefault("contract_gap", []).extend(cg_errors)

    # WOT-2026-026j D4: agents.json schema fail-closed. Una clave de role_mapping
    # fuera del enum canonico (o un actor_runtime desconocido) DEBE hacer fallar
    # --validate (exit!=0), no solo el load en runtime. Cablea la barrera de
    # schema al gate self-service que ya corre en bootstrap/preflight. No depende
    # del ticket activo: la validez del config es transversal (no seed_neutral).
    if AGENTS_CONFIG_PATH.exists():
        try:
            from agents_config import AgentsConfigError, load_agents_config

            load_agents_config(PROJECT_ROOT)
        except AgentsConfigError as exc:
            errors.setdefault("agents_config_schema", []).append(str(exc))
        except ImportError:
            pass  # agents_config no disponible -> degradar sin bloquear

    total_errors = sum(len(errs) for errs in errors.values())
    total_warnings = sum(len(warns) for warns in warnings.values())

    if json_output:
        output = {
            "errors": errors,
            "warnings": warnings,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        }
        print(json.dumps(output, indent=2))
    else:
        if total_errors == 0 and total_warnings == 0:
            print("[OK] Todos los archivos de estado son validos.")
        else:
            if total_errors > 0:
                print(f"[ERROR] {total_errors} problema(s) encontrados.")
            if total_warnings > 0:
                print(f"[WARN] {total_warnings} advertencia(s) encontradas.")
    # Only fail on actual errors, not on warnings
    return 0 if total_errors == 0 else 1


def _handle_archive() -> int:
    """Handle --archive flag."""
    archive_path = archive_old_notifications()
    if archive_path:
        print(f"[OK] Archivado: {archive_path}")
    else:
        print("[INFO] No es necesario archivar.")
    return 0


def _sync_state_after_session_close() -> None:
    """Sync STATE.md to a TERMINAL, ticket-less state after a real session close.

    Before: STATE.md exists con el formato vivo (``ACTIVE_TICKET:``/``STATUS:``) o
        con el legacy (``Estado actual:``).
    During: pone el estado en COMPLETED y, en el formato vivo, LIBERA el ticket
        (``ACTIVE_TICKET: -``): tras cerrar la sesion ya no hay ticket activo.
    After: STATE.md no arrastra el ticket de la sesion cerrada al siguiente ciclo.

    Por que se toca esto (defecto medido 2026-07-21): esta funcion regexeaba SOLO
    ``Estado actual:``, pero el fichero vivo usa ``ACTIVE_TICKET:``/``STATUS:``, asi
    que el sub nunca casaba, ``updated == state_content`` y NO SE ESCRIBIA NADA. El
    cierre creia haber sincronizado y STATE.md arrastraba el ticket de una sesion
    anterior indefinidamente (medido: cerrando el vuelo de 026v/026r, STATE.md
    seguia en WOT-2026-022i). De ahi que ``--session-close`` resolviera el ticket
    por FALLBACK del work_plan stale. Es el mecanismo concreto detras del sintoma
    que WOT-2026-037c(c) describe. Un no-op silencioso: exit 0, cero efecto.
    """
    state_content = read_file(STATE_FILE)
    if not state_content:
        return

    import re

    updated = re.sub(
        r"^(- \*\*Estado actual:\*\*|Estado actual:) .+",
        "Estado actual: COMPLETED",
        state_content,
        flags=re.MULTILINE,
    )
    # Formato vivo: dos claves separadas. El ticket se LIBERA -- dejarlo apuntando
    # al de la sesion cerrada es lo que contamina el arranque siguiente.
    updated = re.sub(
        r"^ACTIVE_TICKET:[^\r\n]*",
        "ACTIVE_TICKET: -",
        updated,
        flags=re.MULTILINE,
    )
    updated = re.sub(
        r"^STATUS:[^\r\n]*",
        "STATUS: COMPLETED",
        updated,
        flags=re.MULTILINE,
    )
    if updated != state_content:
        write_file(STATE_FILE, updated)


def _refresh_session_tracker_after_close() -> None:
    """Refresca o limpia `.session_state.json` tras un close EXITOSO.

    Before: el close real (no dry-run) acaba de retornar 0; el work_plan
        canonico puede o no declarar un ID de ticket.
    During: si el tracker esta disponible, resuelve el ID del work_plan
        cerrado via `session_tracker._get_current_plan_id()`; con ID
        resoluble llama `save_session()` (rama i); sin ID resoluble llama
        `clear_session()` (rama ii). Nunca lanza: cualquier fallo del tracker
        no debe convertir un close exitoso en fallido (el tracker es pista,
        no clave del cierre -- NON-GOAL de WOT-2026-039d).
    After: el tracker refleja el estado post-close (refrescado o vacio); en
        un close FALLIDO esta funcion no se invoca y el tracker se preserva.
    """
    if not SESSION_TRACKER_AVAILABLE:
        return
    try:
        from session_tracker import _get_current_plan_id

        if _get_current_plan_id() != "N/A":
            save_session()
        else:
            clear_session()
    except Exception:  # noqa: S110 - tracker best-effort, nunca degrada el close
        pass


_STATE_STATUS_RE = re.compile(r"^STATUS:\s*(\S+)\s*$", re.MULTILINE)


def _state_status_is_terminal(state_content: str) -> bool:
    """True si el CAMPO ``STATUS:`` de STATE.md declara un estado terminal.

    WOT-2026-042a. Nace de un fallo medido en vivo: la idempotencia de
    ``--session-close`` se decidia con ``"COMPLETED" in state_content``, un
    substring CRUDO sobre STATE.md, que es una PROYECCION.

    Before:
        `state_content` es el texto de STATE.md tal cual (puede venir vacio, con
        CRLF, o con lineas de prosa que NOMBREN un estado sin declararlo).
    During:
        Casa la linea que declara el campo ``STATUS:`` (misma forma anclada que
        :4699) y delega el veredicto de terminalidad en
        `bus.state_machine.is_terminal_state`, que es la AUTORIDAD canonica
        (asi la cita `scripts/check_backlog_contract.py`). Solo el campo cuenta:
        una mencion en una nota de blocker o en un titulo de ticket NO es un
        estado.
    After:
        Retorna bool. No lanza ni muta nada. Un STATE.md sin campo ``STATUS:``
        da False (fail-OPEN deliberado: ante un fichero ilegible, la idempotencia
        NO se activa y el closeout CORRE, que es la direccion segura -- el fallo
        que este helper corrige era justamente saltarse el cierre creyendolo hecho).

    Por que se DELEGA en vez de declarar un set local (review de Manager
    2026-07-27, BLOCKER): un `frozenset({"COMPLETED"})` propio seria un SEGUNDO
    oraculo de terminalidad -- el mismo defecto "un dato, dos formas de leerlo"
    que este ticket dice erradicar. Y divergiria en un caso REAL, no hipotetico:
    `bus/supervisor.py:956` escribe ``STATUS: {state.value}`` con CUALQUIER
    TicketState, asi que un ticket cerrado como SUPERSEDED o BLOCKED_FINAL
    (terminales IRREVERSIBLES por diseno) volveria a correr el closeout entero.
    """
    match = _STATE_STATUS_RE.search(state_content or "")
    if match is None:
        return False
    try:
        from bus.state_machine import is_terminal_state
    except ImportError:
        # El docstring promete "no lanza", y el import PUEDE fallar: medido
        # 2026-07-27, `python -c "from bus.state_machine import ..."` con cwd en
        # el destino da `ImportError: No module named 'bus'`. Sin este except, el
        # ImportError sube al caller -- que lo evalua ANTES de su bloque try -- y
        # aborta el cierre con traceback en vez de correrlo. Fail-OPEN coherente
        # con el resto del helper: sin autoridad resoluble NO se afirma
        # terminalidad, asi que el closeout CORRE (direccion segura).
        return False

    return is_terminal_state(match.group(1).strip())


def _handle_session_close(  # noqa: C901 - delegation handler with flag building
    dry_run: bool,
    skip_slow: bool,
    ticket: str | None,
    tickets: str | None,
    force_mode: bool,
    json_output: bool,
    skip_gates: bool = False,
) -> int:
    """Handle --session-close flag by delegating to scripts/session_closeout.py.

    Before:
        - scripts/session_closeout.py must exist in repo_motor or in the
          legacy single-repo project root.
        - STATE.md may be in any state.

    During:
        - Checks idempotency: if STATE.md already COMPLETED and no --force, skip.
        - Delegates to session_closeout.py with replicated flags.
        - If real close (not dry-run) succeeds, syncs STATE.md to COMPLETED.

    After:
        - Returns exit code from session_closeout.py (0=success, 1=failure).
        - If already completed, exits 0 without running anything.
    """
    # Idempotency check: if STATE.md already terminal and no --force, skip.
    #
    # WOT-2026-042a: se lee el CAMPO `STATUS:`, no un substring del fichero.
    # El guardia anterior (`"COMPLETED" in state_content`) casaba cualquier
    # MENCION de la palabra sobre STATE.md, que es una PROYECCION: una nota de
    # blocker o un titulo de ticket que la nombrara saltaba el closeout entero
    # (gates, reconcile, archivado) devolviendo exit 0 con already_completed.
    # Es el patron CEM "un exit 0 puede significar que no hice nada", con
    # disparador TEXTUAL. Mismo `^STATUS:` canonico que ya usan :4699 y
    # scripts/check_backlog_contract.py::_STATUS_RE (un dato, una forma de leerlo).
    state_content = read_file(STATE_FILE)
    if not force_mode and state_content and _state_status_is_terminal(state_content):
        if json_output:
            print(
                json.dumps({"status": "already_completed", "plan_id": "N/A"}, indent=2)
            )
        else:
            print(
                "[INFO] Session already completed. Use --force to re-run session close."
            )
        return 0

    # Model B keeps operational scripts in repo_motor. Preserve the local
    # project-root lookup only as a compatibility fallback for legacy installs.
    script_path = _MOTOR_ROOT / "scripts" / "session_closeout.py"
    if not script_path.exists():
        script_path = PROJECT_ROOT / "scripts" / "session_closeout.py"
    if not script_path.exists():
        print(
            "[ERROR] scripts/session_closeout.py not found in repo_motor "
            "or project root.",
            file=sys.stderr,
        )
        return 1

    # Build command with flags
    cmd = [
        sys.executable,
        str(script_path),
        "--project-root",
        str(PROJECT_ROOT),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if skip_slow:
        cmd.append("--skip-slow")
    if skip_gates:
        # WOT-2026-020i: forward --skip-gates so session_closeout passes it on to
        # prepush_check. Previously the flag was parsed but never reached the
        # closeout, so --session-close --skip-gates had no effect.
        cmd.append("--skip-gates")
    if ticket:
        cmd.extend(["--ticket", ticket])
    if tickets:
        cmd.extend(["--tickets", tickets])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=600
        )
        # WT-2026-249a: returncode governs stderr propagation.
        # Print stdout from the subprocess unconditionally.
        # Propagate stderr only when returncode indicates failure,
        # so warnings in stderr with returncode 0 do not contaminate
        # the parent's error stream (email, CI, wrappers).
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0 and result.stderr:
            print(result.stderr, file=sys.stderr, end="")

        if result.returncode != 0:
            return result.returncode

        # Post-close sync: only for real close (not dry-run)
        if not dry_run:
            _sync_state_after_session_close()
            # WOT-2026-039d: refresh-or-clear del session tracker AL FINAL de
            # un close EXITOSO. Antes, save_session() vivia solo en la rama
            # STATUS y el tracker quedaba STALE tras --session-close,
            # apuntando a un ticket ajeno (caso 2026-07-15: disparo el falso
            # "[INFO] Session already completed"). Logica adjudicada:
            # (i) work_plan cerrado con ID resoluble -> save_session (refresca
            #     active_plan + last_activity);
            # (ii) sin ID resoluble -> clear_session (tracker vacio);
            # (iii) close FALLIDO -> no se llega aqui (return antes): el
            #     tracker se preserva como pista de recovery.
            _refresh_session_tracker_after_close()

        if json_output:
            print(json.dumps({"status": "completed", "exit_code": 0}, indent=2))
        else:
            action = "dry-run" if dry_run else "close"
            print(f"[OK] Session {action} completed.")
        return 0
    except subprocess.TimeoutExpired:
        print("[ERROR] Session close timed out after 600s.", file=sys.stderr)
        return 1
    except OSError as exc:
        # WOT-2026-019d: subprocess.run(cmd, ...) lanza FileNotFoundError (una
        # subclase de OSError) con .filename absoluto si el script/ejecutable
        # no existe. Componer el mensaje a mano sin exponer la ruta cruda.
        if exc.filename:
            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
            detail = f"{exc.strerror} (errno {exc.errno}) en {where}"
        else:
            detail = f"{exc.strerror} (errno {exc.errno})"
        print(f"[ERROR] Session close failed: {detail}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Session close failed: {exc}", file=sys.stderr)
        return 1


def _handle_main_action(  # noqa: C901 - WOT-2026-019d: +1 branch from except OSError split
    skip_gates: bool, strict_mode: bool, json_output: bool, reset_turn_mode: bool
) -> int:
    """Handle main action determination and output."""
    if SESSION_TRACKER_AVAILABLE:
        show_recovery_hint()

    # Use project scanner to generate project-map.json context artifact
    if SCANNER_AVAILABLE and scan_project:
        print("\n  Scanning project with project_scanner...")
        try:
            context_dir = get_context_dir()
            context_dir.mkdir(parents=True, exist_ok=True)
            project_map = scan_project(PROJECT_ROOT.resolve())

            # Write scanner output
            output_path = context_dir / "project-map.json"
            output_path.write_text(
                json.dumps(project_map, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            print(f"  [OK] Project map: {project_map['summary']['total_files']} files")
            print(
                f"       Python files with imports: {len(project_map['importMap']['python_files'])}"
            )
        except OSError as e:
            # WOT-2026-019d: context_dir.mkdir/output_path.write_text hacen I/O
            # directo sobre rutas absolutas bajo PROJECT_ROOT/AGENT_DIR; un
            # OSError real trae .filename. Componer el mensaje sin exponer la
            # ruta cruda.
            if e.filename:
                where = scope_gate._relativize_scope_path(e.filename, PROJECT_ROOT)
                detail = f"{e.strerror} (errno {e.errno}) en {where}"
            else:
                detail = f"{e.strerror} (errno {e.errno})"
            print(f"  [WARN] Scanner failed: {detail}")
        except Exception as e:
            print(f"  [WARN] Scanner failed: {e}")
    else:
        print(
            "\n  [INFO] Project scanner not available; skipping project map generation"
        )

    notif_errors = validate_state_files().get("notifications.md", [])
    if notif_errors:
        fix_corrupted_notifications()

    archive_old_notifications()

    # WP-2026-149: Heal STATE.md drift before determining next action
    try:
        from scripts.state_projection_sync import sync_state_projection

        sync_state_projection(
            runtime_dir=get_runtime_dir() / "events",
            collaboration_dir=get_collab_dir(),
            ticket_id=get_plan_id(read_file(WORK_PLAN)),
        )
    except Exception:  # noqa: S110 - sync is best-effort and must not block status path
        pass

    action = determine_next_action(skip_gates=skip_gates, strict_mode=strict_mode)

    if should_overwrite_turn(TURN_FILE, force_reset=reset_turn_mode):
        update_turn_file(action)

    if json_output:
        print(json.dumps(action, indent=2, ensure_ascii=False))
    else:
        print_human_readable(action)

    if SESSION_TRACKER_AVAILABLE:
        save_session()

    return 0


# Flag dispatch table
FLAG_HANDLERS = {
    "--recover": _handle_recover,
    "--check-completion": _handle_check_completion,
    "--archive": _handle_archive,
    "--manager-approve": _handle_manager_approve,
    "--request-changes": _handle_request_changes,
}


def _handle_get_closeout_skip(json_output: bool) -> int:
    """WT-2026-246b: Decide whether the launcher should skip closeout.

    Called by the launcher's Add-BuilderCloseout finally-block to query
    state authority BEFORE running --pre-handoff / --mark-ready.

    Returns 0 and prints JSON with {"skip": true/false}:
    - skip=true  → ticket is in READY_FOR_REVIEW, READY_TO_CLOSE, HUMAN_GATE
                   or COMPLETED; closeout is a no-op and should be skipped.
    - skip=false → ticket is still IN_PROGRESS (or unknown); closeout must
                   run so the supervisor can recover from a stuck Builder.

    Authority: bus-derived state is the ONLY source for skip=true.
    When the bus is unavailable or has no events for the ticket,
    the function returns skip=false (fail-open). No markdown-based
    fallback is used - execution_log.md / STATE.md are projections
    derived from the bus, not authority.
    """
    _plan_content, _log_content, plan_id = _load_mark_ready_context()
    if is_invalid_plan_id(plan_id):
        if json_output:
            print(json.dumps({"skip": False, "reason": "no_active_plan"}, indent=2))
        else:
            print("[WARN] No active plan; closeout will run.")
        return 0

    # Authority: bus-derived state only
    bus_state = None
    if BUS_AVAILABLE and event_bus:
        from bus.state_machine import StateMachine

        events = event_bus.read_events(ticket_id=plan_id)
        if events:
            bus_state = StateMachine.derive_state_from_events(
                [e.to_dict() for e in events]
            )

    # Only skip when bus explicitly says post-success
    if _is_bus_state_post_success(bus_state):
        if json_output:
            print(
                json.dumps(
                    {
                        "skip": True,
                        "plan_id": plan_id,
                        "bus_state": bus_state.value,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[INFO] Ticket {plan_id} bus state is {bus_state.value}. "
                "Closeout skipped."
            )
        return 0

    # Fail-open: bus unavailable, no events, or not post-success → do not skip
    if json_output:
        print(
            json.dumps(
                {
                    "skip": False,
                    "plan_id": plan_id,
                    "bus_state": bus_state.value if bus_state else None,
                    "reason": "bus_authority_not_post_success",
                },
                indent=2,
            )
        )
    else:
        print(
            f"[INFO] Ticket {plan_id} bus state is not post-success "
            f"({bus_state.value if bus_state else 'unknown'}). "
            "Closeout will run."
        )
    return 0


# --validate is dispatched via direct call (not FLAG_HANDLERS) so that
# monkeypatching agent_controller._handle_validate in tests works correctly.
# A dict entry captures the function object at import time, bypassing patches.

HELP_TEXT = """Agent Controller - CLI reference

Usage:
  python .agent/agent_controller.py [options]

Mode flags:
  --json              Print machine-readable JSON where supported.
  --force             Continue when local safety checks would otherwise stop.
  --strict            Run strict validation mode.
  --dry-run           Preview the operation without applying changes.
  --no-heal           With --validate: report bus drift read-only, never write
                      the tracked STATE.md (WOT-2026-024a; for read-only callers).

Action flags:
  --mark-ready                    Mark the active ticket as READY_FOR_REVIEW.
  --pre-handoff                   Run pre-handoff checks before mark-ready.
  --validate                      Validate collaboration state.
  --bootstrap-ticket              Emit initial bus state for the active ticket.
  --manager-approve <ticket>      Approve and close a ticket canonically.
  --request-changes <ticket>      Request changes for a ticket.
  --escalate-human-gate           Move a ticket to HUMAN_GATE.
  --resume-human-gate             Resume review from HUMAN_GATE.
  --reopen-terminal-ticket <ticket>  Reopen the active COMPLETED ticket to IN_PROGRESS.
  --pause-ticket                  Pause the active ticket temporarily (WOT-2026-010d).
  --resume-ticket                 Resume a paused ticket (WOT-2026-010d).
  --abort-paused-ticket           Abort a paused ticket (WOT-2026-010d).
  --session-close                 Close the current session.
  --recover                       Recover session state.
  --archive                       Archive old notifications.
  --resolve-launcher-roots        Print resolved repo_motor/destino/workspace roots.
  --get-closeout-skip             Query state authority for closeout skip decision.

Control flags:
  --project-root <path>       Destination project root.
  --ticket <ticket>           Ticket ID for actions that accept one
                              (--manager-approve/--request-changes/--reopen-terminal-ticket
                              accept either `--ticket <id>` or the positional `<id>` form).
  --tickets <ids>             Ticket list for session close.
  --reason <text>             Pause reason (for --pause-ticket/--abort-paused-ticket).
  --skip-gates                Skip quality gates.
  --skip-slow                 Skip slow checks during session close.
  --reset-turn                Regenerate TURN.md.
  --scope-override <reason>   Override scope gate with a reason.

Example:
  python .agent/agent_controller.py --validate --json --project-root C:\\path\\to\\repo_destino
"""


def main():  # noqa: C901 - CLI dispatch intentionally centralizes flag handling
    """Funcion principal del controller."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP_TEXT)
        return 0

    # WP-2026-122: Parse --project-root FIRST and export to environment
    # This must happen before any imports that depend on project_root
    if "--project-root" in sys.argv:
        idx = sys.argv.index("--project-root")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            project_root_value = sys.argv[idx + 1]
            os.environ["AGENT_PROJECT_ROOT"] = str(Path(project_root_value).resolve())
            # Invalidate lru_cache on resolve_project_root: the cache may have
            # been populated during module import (before argv parsing) using the
            # motor path. Clearing it ensures all subsequent calls return the
            # workspace path set above.
            from runtime.project_root import clear_cache as _clear_project_root_cache

            _clear_project_root_cache()

    # WP-2026-176: Motor code-only guard. Block write operations when no
    # external workspace is configured (no AGENT_PROJECT_ROOT / --project-root).
    # Read-only operations (--validate, --json, --archive, etc.) are NOT blocked.
    _code_only_blocked_flags = frozenset(
        {
            "--mark-ready",
            "--pre-handoff",
            "--request-changes",
            "--manager-approve",
            "--session-close",
            "--bootstrap-ticket",
            "--escalate-human-gate",
            "--resume-human-gate",
            "--reopen-terminal-ticket",
            "--pause-ticket",
            "--resume-ticket",
            "--abort-paused-ticket",
        }
    )
    if is_motor_code_only() and any(
        flag in sys.argv for flag in _code_only_blocked_flags
    ):
        print(
            "[ERROR] Motor code-only mode: write operations require an external\n"
            "        workspace. Use --project-root <workspace> or set the\n"
            "        AGENT_PROJECT_ROOT environment variable to point to an\n"
            "        external project workspace (e.g., z_scripts/).\n"
            "        Read-only operations (--validate, --json, --archive) still\n"
            "        work without it.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    _ensure_runtime_dirs()
    _get_event_bus()

    skip_gates = "--skip-gates" in sys.argv
    json_output = "--json" in sys.argv
    force_mode = "--force" in sys.argv
    strict_mode = "--strict" in sys.argv
    reset_turn_mode = "--reset-turn" in sys.argv

    # Parse --scope-override
    scope_override = None
    if "--scope-override" in sys.argv:
        idx = sys.argv.index("--scope-override")
        if idx + 1 >= len(sys.argv):
            print("[ERROR] --scope-override requires a reason.")
            return 1
        next_token = sys.argv[idx + 1]
        # Reject if next token is another flag
        if next_token.startswith("--"):
            print("[ERROR] --scope-override requires a reason, not another flag.")
            return 1
        scope_override = next_token

    # Parse --ticket (used by closeout/review/reopen action flags).
    # WOT-2026-013u: the guard must accept a value that EXISTS (idx + 1 in range)
    # and is not another flag; the old `idx + 1 >= len(sys.argv)` was inverted and
    # never captured the ticket, so `--manager-approve --ticket <id>` failed with
    # "No ticket_id provided" while the positional form worked. --ticket takes
    # precedence; the positional forms below remain supported (backward-compat).
    ticket_id = None
    if "--ticket" in sys.argv:
        idx = sys.argv.index("--ticket")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]
    elif "--manager-approve" in sys.argv:
        idx = sys.argv.index("--manager-approve")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]
    elif "--request-changes" in sys.argv:
        idx = sys.argv.index("--request-changes")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]
    elif "--reopen-terminal-ticket" in sys.argv:
        idx = sys.argv.index("--reopen-terminal-ticket")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]

    # Parse --reason (used by pause-ticket and abort-paused-ticket)
    reason = None
    if "--reason" in sys.argv:
        idx = sys.argv.index("--reason")
        if idx + 1 >= len(sys.argv):
            print("[ERROR] --reason requires a reason text.")
            return 1
        next_token = sys.argv[idx + 1]
        if next_token.startswith("--"):
            print("[ERROR] --reason requires text, not another flag.")
            return 1
        reason = next_token

    # Check for --resolve-launcher-roots (WT-2026-232a)
    if "--resolve-launcher-roots" in sys.argv:
        return _handle_resolve_launcher_roots(json_output)

    # Check for --get-closeout-skip (WT-2026-246b)
    if "--get-closeout-skip" in sys.argv:
        return _handle_get_closeout_skip(json_output)

    # Check for --mark-ready
    if "--mark-ready" in sys.argv:
        return _handle_mark_ready(scope_override, json_output, force_mode)

    # Check for --bootstrap-ticket
    if "--bootstrap-ticket" in sys.argv:
        return _handle_bootstrap_ticket(json_output)

    # Check for --escalate-human-gate
    if "--escalate-human-gate" in sys.argv:
        return _handle_escalate_human_gate(ticket_id, json_output)

    # Check for --resume-human-gate (salida canonica de HUMAN_GATE)
    if "--resume-human-gate" in sys.argv:
        return _handle_resume_human_gate(ticket_id, json_output)

    # WOT-2026-010d: Check for pause/resume ticket flags
    if "--pause-ticket" in sys.argv:
        return _handle_pause_ticket(ticket_id, reason, json_output)

    if "--resume-ticket" in sys.argv:
        return _handle_resume_ticket(ticket_id, json_output)

    if "--abort-paused-ticket" in sys.argv:
        return _handle_abort_paused_ticket(ticket_id, reason, json_output)

    # Check for --reopen-terminal-ticket (salida manual de tickets COMPLETED)
    if "--reopen-terminal-ticket" in sys.argv:
        return _handle_reopen_terminal_ticket(ticket_id, json_output)

    # Check for --pre-handoff (WP-2026-173)
    if "--pre-handoff" in sys.argv:
        return _handle_pre_handoff(json_output)

    # Parse --session-close specific flags
    session_skip_slow = "--skip-slow" in sys.argv
    session_tickets = None
    if "--tickets" in sys.argv:
        idx = sys.argv.index("--tickets")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            session_tickets = sys.argv[idx + 1]

    # Check for --session-close
    if "--session-close" in sys.argv:
        session_dry_run = "--dry-run" in sys.argv
        return _handle_session_close(
            dry_run=session_dry_run,
            skip_slow=session_skip_slow,
            ticket=ticket_id,
            tickets=session_tickets,
            force_mode=force_mode,
            json_output=json_output,
            skip_gates=skip_gates,
        )

    # Check for --validate via direct call (see FLAG_HANDLERS comment above)
    if "--validate" in sys.argv:
        # WOT-2026-024a: --no-heal makes --validate read-only (report drift, never
        # write STATE.md). Default (flag absent) heals as before: additive, no regression.
        return _handle_validate(json_output, no_heal="--no-heal" in sys.argv)

    # Check for specific flag handlers
    for flag, handler in FLAG_HANDLERS.items():
        if flag in sys.argv:
            # Pass ticket_id to manager-approve handler
            if flag == "--manager-approve":
                return handler(
                    ticket_id,
                    json_output,
                    force_mode,
                    dry_run=("--dry-run" in sys.argv),
                )
            if flag == "--request-changes":
                return handler(ticket_id, json_output, force_mode)
            return handler()

    # Shared prechecks
    git_status = check_git_status()
    if not force_mode and git_status is False:
        print("\n[WARN] Tienes cambios sin guardar en git.")
        print("   Guarda tus cambios antes de continuar:")
        print("   git add . && git commit -m 'Guardo trabajo'")
        print("   O usa --force para ignorar.\n")
        return 1

    # Main action
    return _handle_main_action(skip_gates, strict_mode, json_output, reset_turn_mode)


if __name__ == "__main__":
    sys.exit(main())
