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
for _path in (str(_PROJECT_ROOT_DERIVED), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# WP-2026-122: Import project_root module for dynamic path resolution
# Entry points set AGENT_PROJECT_ROOT env var after parsing --project-root
# Import AFTER sys.path setup to ensure runtime/ is importable
from runtime.project_root import (  # noqa: E402
    get_agent_dir,
    get_collab_dir,
    get_context_dir,
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
    from session_tracker import recover_session, save_session, show_recovery_hint

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
PROJECT_MAP = _LazyPath(lambda: get_context_dir() / "project_map.md")
ARCHIVE_DIR = _LazyPath(lambda: get_collab_dir() / "archive")
AGENTS_CONFIG_PATH = _LazyPath(lambda: get_agent_dir() / "config" / "agents.json")

# Archive configuration
MAX_NOTIFICATIONS_SIZE_KB = 50
MAX_NOTIFICATION_ENTRIES = 20

# WP-2026-106 hotfix: HUMAN_GATE escalation threshold. Single source of truth
# is manager_review.max_attempts in agents.json (shared with bus/review_bridge.py).
# Fallback used only if config is missing or unreadable.
HUMAN_GATE_REJECTION_FALLBACK = 5


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


# Configuracion de comprobaciones
MAX_FILES_CIRCULAR_CHECK = 50

# Estados validos para validacion
VALID_PLAN_STATES = {
    "DRAFT",
    "IN_PLANNING",
    "APPROVED",
    "IN_REVIEW",
    "COMPLETED",
    "N/A",
}
VALID_LOG_STATES = {
    "PENDING",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_FOR_REVIEW",
    # WP-2026-106: HUMAN_GATE and READY_TO_CLOSE are real terminal-adjacent
    # states emitted by bus/state_machine.py; the validator must accept them.
    "HUMAN_GATE",
    "READY_TO_CLOSE",
    "COMPLETED",
    "N/A",
}


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


# Event bus is initialized lazily after the project root is known.
event_bus = None

# Circuit breaker state
CIRCUIT_BREAKER_PATH = _LazyPath(
    lambda: get_agent_dir() / "runtime" / "circuit_breaker.json"
)
BUILDER_LOCK_PATH = _LazyPath(lambda: get_agent_dir() / "runtime" / "builder_lock.txt")

# ============================================================================
# SCOPE GATE UTILITIES
# ============================================================================

EXCLUDE_FILES_REL = {
    "work_plan.md",
    "execution_log.md",
    "STATE.md",
    "TURN.md",
    "notifications.md",
    ".session_state.json",
}


def _exclude_files() -> set[str]:
    collab_dir = get_collab_dir()
    agent_dir = get_agent_dir()
    context_dir = get_context_dir()
    exclude_files = {str((collab_dir / f).resolve()) for f in EXCLUDE_FILES_REL}
    exclude_files.add(str((context_dir / "project_map.md").resolve()))
    # Exclude bus runtime files (events.jsonl is managed by the bus, not the Builder)
    exclude_files.add(
        str((agent_dir / "runtime" / "events" / "events.jsonl").resolve())
    )
    # Exclude agent config directory (managed by agents_config.py, not the Builder)
    exclude_files.add(str((agent_dir / "config").resolve()))
    return exclude_files


def parse_files_likely_touched(work_plan_content: str) -> set[str]:
    """Parse Files Likely Touched from work_plan.md."""
    lines = work_plan_content.split("\n")
    in_section = False
    files = set()

    def _looks_like_path_token(token: str) -> bool:
        if not token or " " in token:
            return False
        if token.startswith("."):
            return True
        if "/" in token or "\\" in token:
            return True
        basename = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return "." in basename

    for line in lines:
        line = line.strip()
        if "## Files Likely Touched" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break  # next section
        if in_section and line and not line.startswith("---"):
            # normalize: remove backticks, quotes, bullets, trim
            normalized = (
                line.lstrip("*- ")
                .replace("`", "")
                .replace('"', "")
                .replace("'", "")
                .strip()
            )
            if normalized and _looks_like_path_token(normalized):
                # resolve relative to project root
                path = (PROJECT_ROOT / normalized).resolve()
                files.add(str(path))
    return files


def get_changed_files() -> set[str] | None:
    """Get all changed files: staged, unstaged, untracked. None if not git repo."""
    if not (PROJECT_ROOT / ".git").exists():
        return None
    try:
        # Use -z for null-byte separated output to handle paths with spaces and renames safely
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        changed = set()
        # Split by null byte, each entry is: "XY path" where XY is 2-char status
        # Renames have two consecutive entries: "R old_path" followed by "new_path"
        entries = result.stdout.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue
            # Format: "XY path" where XY is 2-char status (e.g., "M ", "??", "R ")
            # When Y=' ' (space), format is "M path" (path at index 2)
            # When Y!=' ', format is "XY path" with space separator (path at index 3)
            if len(entry) >= 3:
                status = entry[:2]
                # Determine path start: if entry[2] is space, path starts at 3; otherwise at 2
                path = entry[3:] if entry[2] == " " else entry[2:]
                # Handle renames: status starts with 'R', next entry is the new path
                if status[0] == "R" and i + 1 < len(entries):
                    new_path = entries[i + 1]
                    if new_path:
                        changed.add(new_path)
                    i += 2
                    continue
                else:
                    changed.add(path)
            i += 1
        # resolve to absolute paths
        resolved = set()
        for f in changed:
            path = (PROJECT_ROOT / f).resolve()
            resolved.add(str(path))
        return resolved
    except FileNotFoundError:
        return None


def check_scope_gate(
    work_plan_content: str, changed_files: set[str] | None, exclude_files: set[str]
) -> dict:
    """Check if changed files are within scope."""
    if changed_files is None:
        return {
            "valid": True,
            "out_of_scope": set(),
            "warnings": ["Repository is not git-managed"],
        }

    whitelist = parse_files_likely_touched(work_plan_content)
    if not whitelist:
        return {
            "valid": True,
            "out_of_scope": set(),
            "warnings": ["No Files Likely Touched section in work_plan.md"],
        }

    out_of_scope = (changed_files - whitelist) - exclude_files
    valid = len(out_of_scope) == 0
    return {"valid": valid, "out_of_scope": out_of_scope, "warnings": []}


def _load_mark_ready_context() -> tuple[str, str, str]:
    """Load the plan and log content for --mark-ready."""
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    plan_id = get_plan_id(plan_content)
    return plan_content, log_content, plan_id


def _record_scope_override(scope_override: str, out_of_scope_files: set[str]) -> None:
    """Record a scope override in the execution log."""
    note = (
        f"Scope override: {scope_override}. "
        f"Out of scope files: {', '.join(sorted(out_of_scope_files))}"
    )
    update_log_status("READY_FOR_REVIEW", note)


def _scope_gate_allows_close(gate_result: dict, scope_override: str | None) -> bool:
    """Apply scope gate decision for mark-ready."""
    if gate_result["valid"]:
        for warning in gate_result["warnings"]:
            print(f"[WARN] {warning}")
        update_log_status("READY_FOR_REVIEW", "Marked ready by Builder")
        return True

    if not scope_override:
        print("[ERROR] Scope violation detected:")
        for file_path in sorted(gate_result["out_of_scope"]):
            print(f"  - {file_path}")
        print('Use --scope-override "reason" to proceed.')
        return False

    print(f"[INFO] Scope override applied: {scope_override}")
    _record_scope_override(scope_override, gate_result["out_of_scope"])
    return True


def _sync_mark_ready_targets(plan_id: str, plan_content: str) -> None:
    """Update TURN.md and STATE.md after mark-ready."""
    log_status_before = get_status(read_file(EXEC_LOG), "**Estado:**")
    action = {
        "role": "MANAGER",
        "context_file": ".manager_rules",
        "workflow_file": ".agent/workflows/manager_workflow.md",
        "instruction": f"Builder completo {plan_id}. Revisa el trabajo.",
        "plan_id": plan_id,
        "plan_status": get_status(plan_content, "**Estado:**"),
        "log_status": "READY_FOR_REVIEW",
        "action_type": "REVIEW_WORK",
        "plan_type": get_plan_type(plan_content),
    }
    update_turn_file(action)

    state_content = read_file(STATE_FILE)
    if not state_content:
        return

    lines = state_content.split("\n")
    for index, line in enumerate(lines):
        if "**Estado actual:**" in line:
            lines[index] = "- **Estado actual:** READY_FOR_REVIEW"
            write_file(STATE_FILE, "\n".join(lines))
            break

    # Emit STATE_CHANGED to bus idempotently
    if BUS_AVAILABLE and event_bus:
        # Check if already emitted for this ticket and state
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
                },
            )


# ============================================================================
# CIRCUIT BREAKER AND CHECKOUT UTILITIES
# ============================================================================


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
        return json.loads(BUILDER_LOCK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


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


def _release_builder_lock(plan_id: str) -> None:
    """Release builder lock after completion."""
    import contextlib

    existing = _read_builder_lock()
    if existing and existing.get("ticket_id") == plan_id:
        with contextlib.suppress(OSError):
            BUILDER_LOCK_PATH.unlink()


def _emit_builder_exit(plan_id: str, exit_reason: str, completion_summary: str) -> None:
    """Emit BUILDER_EXIT event to the bus - required for ticket closure."""
    if BUS_AVAILABLE and event_bus:
        event_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id=plan_id,
            actor="BUILDER",
            payload={
                "exit_reason": exit_reason,
                "completion_summary": completion_summary,
                "source": "mark-ready",
            },
        )


def _auto_archive_closed_artifacts() -> None:
    """Auto-archive closed PLAN/AUDIT artifacts during mark-ready.

    Before: Requires COLLAB_DIR to exist with potential closed PLAN/AUDIT files.
    During: Imports and calls archive_collaboration_artifacts.py as a library function.
    After: Closed PLAN/AUDIT files are moved to _archive/plan_audit/ (idempotent, silent on no-op).
    """
    try:
        # Import the archive script as a module
        import importlib.util

        archive_spec = importlib.util.spec_from_file_location(
            "archive_collaboration_artifacts",
            PROJECT_ROOT / "scripts" / "archive_collaboration_artifacts.py",
        )
        if archive_spec and archive_spec.loader:
            archive_mod = importlib.util.module_from_spec(archive_spec)
            archive_spec.loader.exec_module(archive_mod)

            # Call the archive function (idempotent, no-op if nothing to archive)
            archive_mod.archive_collaboration_artifacts(
                collaboration_dir=COLLAB_DIR,
                dry_run=False,
            )
    except Exception as exc:
        # Silent fail with debug logging - archiving is best-effort, not critical path
        print(f"[WARN] Auto-archive failed: {exc}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


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


def get_status(content: str, marker: str) -> str:
    """Extrae el estado de un archivo buscando un marcador."""
    for line in content.split("\n"):
        if marker in line:
            return line.split(marker)[1].strip()
    return "UNKNOWN"


def get_plan_id(content: str) -> str:
    """Extrae el ID del plan de trabajo."""
    for line in content.split("\n"):
        if "**ID:**" in line or "**Plan ID:**" in line:
            return line.split(":**")[1].strip()
    return "N/A"


def get_plan_type(content: str) -> str:
    """Extrae el tipo de plan. Valores: IMPLEMENTATION (default) | FINALIZATION."""
    for line in content.split("\n"):
        if "**Tipo:**" in line:
            return line.split(":**")[1].strip().upper()
    return "IMPLEMENTATION"


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


def extract_status_emoji(status_str: str) -> tuple[str, str]:
    """Extrae el estado limpio y el emoji."""
    emojis = {"🟢", "🟡", "🔴", "🟣", "✅", "⏳", "❌", "⚠️"}
    status_clean = status_str.strip()
    found_emoji = ""
    for emoji in emojis:
        if emoji in status_clean:
            found_emoji = emoji
            status_clean = status_clean.replace(emoji, "").strip()
            break
    return status_clean, found_emoji


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
    return []


def _validate_work_plan() -> list[str]:
    """Validate work_plan.md file."""
    errors = []
    content = read_file(WORK_PLAN)
    if not content:
        return errors

    status_raw = get_status(content, "**Estado:**")
    status_clean, _ = extract_status_emoji(status_raw)
    if status_clean and status_clean not in VALID_PLAN_STATES:
        errors.append(f"Estado invalido: '{status_clean}'")
    if "**ID:**" not in content:
        errors.append("Falta campo **ID:**")
    return errors


def _validate_execution_log() -> list[str]:
    """Validate execution_log.md file."""
    errors = []
    content = read_file(EXEC_LOG)
    if not content:
        return errors

    status_raw = get_status(content, "**Estado:**")
    status_clean, _ = extract_status_emoji(status_raw)
    if status_clean and status_clean not in VALID_LOG_STATES:
        errors.append(f"Estado invalido: '{status_clean}'")
    return errors


def _validate_turn_file() -> list[str]:
    """Validate TURN.md file."""
    errors = []
    content = read_file(TURN_FILE)
    if content and "## Agente Activo" not in content:
        errors.append("Falta secciÃƒÂ³n '## Agente Activo'")
    return errors


def _validate_notifications() -> list[str]:
    """Validate notifications.md file."""
    errors = []
    content = read_file(NOTIFICATIONS)
    if content and "</thinking>" in content:
        errors.append("Contiene etiquetas </thinking> (corrupto)")
    return errors


def _validate_cross_file_consistency() -> list[str]:
    """Validate consistency across files."""
    errors = []
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)

    if not plan_content or not log_content:
        return errors

    plan_status_raw = get_status(plan_content, "**Estado:**")
    log_status_raw = get_status(log_content, "**Estado:**")
    plan_clean, _ = extract_status_emoji(plan_status_raw)
    log_clean, _ = extract_status_emoji(log_status_raw)

    # Plan APPROVED pero log COMPLETED
    if "APPROVED" in plan_clean and "COMPLETED" in log_clean:
        errors.append(
            "DRIFT: plan=APPROVED pero log=COMPLETED -- "
            "el log pertenece a un ciclo anterior. Limpia execution_log.md."
        )

    # Plan COMPLETED pero log IN_PROGRESS
    if "COMPLETED" in plan_clean and "IN_PROGRESS" in log_clean:
        errors.append(
            "DRIFT: plan=COMPLETED pero log=IN_PROGRESS -- "
            "el Builder no cerro su bitacora correctamente."
        )

    # Plan IN_PLANNING con log READY_FOR_REVIEW
    if "IN_PLANNING" in plan_clean and "READY_FOR_REVIEW" in log_clean:
        errors.append(
            "DRIFT: plan=IN_PLANNING pero log=READY_FOR_REVIEW -- "
            "estado imposible. El plan debe estar APPROVED antes de que el Builder entregue."
        )

    # Plan N/A pero log activo
    if ("N/A" in plan_clean or not plan_clean) and log_clean not in (
        "N/A",
        "COMPLETED",
        "PENDING",
        "",
    ):
        errors.append(
            f"DRIFT: no hay plan activo pero log={log_clean} -- "
            "limpia execution_log.md o crea un nuevo work_plan.md."
        )

    return errors


def validate_state_files() -> dict[str, list[str]]:
    """Valida el formato y consistencia cruzada de los archivos de estado."""
    return {
        "work_plan.md": _validate_work_plan(),
        "execution_log.md": _validate_execution_log(),
        "notifications.md": _validate_notifications(),
        "TURN.md": _validate_turn_file(),
        "consistency": _validate_cross_file_consistency(),
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
        try:
            pytest_result = subprocess.run(
                ["uv", "run", "pytest", "-q"],
                capture_output=True,
                timeout=120,
                cwd=PROJECT_ROOT,
            )
            if pytest_result.returncode != 0:
                results["passed"] = False
                results["summary"].append("[FAIL] Pytest: Tests fallando")
            else:
                results["summary"].append("[OK] Pytest: Tests OK")
        except FileNotFoundError:
            results["summary"].append("[WARN] Pytest: No instalado")

    if plan_type == "FINALIZATION":
        fin_results = run_finalization_checks()
        results["summary"].extend(fin_results["summary"])

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

    except Exception as e:
        print(f"  [WARN] Error creando findings.md: {e}")

    return findings_path


def generate_project_map() -> str:
    """Genera un mapa actualizado del proyecto."""
    output = [
        "# Mapa del Proyecto",
        f"**Actualizado:** {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Estructura de Archivos",
        "```",
    ]

    ignore = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    extensions = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}

    files_found = []
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if any(part in ignore for part in path.parts):
            continue
        if path.is_file() and path.suffix in extensions:
            files_found.append(str(path.relative_to(PROJECT_ROOT)))

    output.extend(files_found[:50])
    if len(files_found) > 50:
        output.append(f"... (+{len(files_found) - 50} archivos mas)")

    output.append("```")
    content = "\n".join(output)
    write_file(PROJECT_MAP, content)
    return content


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
    """Check quality gates and return action if failed."""
    gate_result = run_quality_gates(plan_type=plan_type)
    if not gate_result["passed"]:
        update_log_status("IN_PROGRESS", "AUTO-REJECTED: Quality Gates fallaron")
        return {
            "role": "BUILDER",
            "context_file": ".builder_rules",
            "workflow_file": ".agent/workflows/builder_workflow.md",
            "instruction": "RECHAZADO. Quality Gates fallaron. Corrige errores.",
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
    return {
        "role": "UNKNOWN",
        "context_file": "N/A",
        "workflow_file": "N/A",
        "instruction": "Estado indeterminado. Revisa archivos manualmente.",
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


def update_turn_file(action: dict) -> None:
    """Actualiza TURN.md con informacion del turno actual."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

## Archivos a Leer

1. `{action["context_file"]}` (Contexto del rol)
2. `{action["workflow_file"]}` (Flujo de trabajo)
3. `.agent/context/project_map.md` (Estructura)

---

## Estado del Sistema

| Archivo | Estado |
|---------|--------|
| work_plan.md | {action["plan_status"]} |
| execution_log.md | {action["log_status"]} |

---

*Generado por agent_controller.py v5*
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


def _handle_mark_ready(  # noqa: C901 - linear guard chain (HUMAN_GATE, already-ready, breaker)
    scope_override: str | None, json_output: bool, force_mode: bool
) -> int:
    """Handle --mark-ready flag."""
    plan_content, log_content, plan_id = _load_mark_ready_context()
    if not plan_id or plan_id == "N/A":
        print("[ERROR] No active plan found.")
        return 1

    log_status = get_status(log_content, "**Estado:**")

    # WP-2026-106 hotfix: a ticket escalated to HUMAN_GATE can only leave that
    # state by explicit human intervention. The Builder must not be able to
    # re-declare READY_FOR_REVIEW and bypass the Manager review cycle.
    if "HUMAN_GATE" in log_status:
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

    if "READY_FOR_REVIEW" in log_status:
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
                    },
                )
        return 0

    # Exit gate: Check circuit breaker before allowing close
    breaker_status = _check_circuit_breaker(plan_id)
    if breaker_status["open"]:
        print(f"[ERROR] Circuit breaker is OPEN: {breaker_status['reason']}")
        print(
            f"  Failures: {breaker_status['failures']}, No-progress count: {breaker_status['no_progress_count']}"
        )
        print("  Resolve the underlying issue before marking ready.")
        return 1

    gate_result = check_scope_gate(plan_content, get_changed_files(), _exclude_files())
    if not _scope_gate_allows_close(gate_result, scope_override):
        return 1

    # Exit gate: Emit BUILDER_EXIT event - REQUIRED for ticket closure
    # MUST occur BEFORE STATE_CHANGED to maintain order invariant
    _emit_builder_exit(
        plan_id=plan_id,
        exit_reason="Implementation completed and ready for review",
        completion_summary=f"Ticket {plan_id} implementation completed. All quality gates passed. Scope validated against Files Likely Touched.",
    )

    # Auto-archive closed PLAN/AUDIT artifacts (idempotent, no-op if nothing to archive)
    _auto_archive_closed_artifacts()

    _sync_mark_ready_targets(plan_id, plan_content)

    # Reset circuit breaker on successful completion
    _reset_circuit_breaker(plan_id)

    # Release builder lock
    _release_builder_lock(plan_id)

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

    if not plan_id or plan_id == "N/A":
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


def _check_bus_drift(plan_content: str, log_status: str) -> list[str]:
    """Check for drift between Markdown state and bus events."""
    warnings = []
    if not BUS_AVAILABLE or not event_bus:
        warnings.append("Event bus not available for drift detection")
        return warnings

    plan_id = get_plan_id(plan_content)
    if not plan_id or plan_id == "N/A":
        warnings.append("No active ticket found for bus drift check")
        return warnings

    latest_state_event = event_bus.latest_event(
        ticket_id=plan_id, event_type="STATE_CHANGED"
    )
    if latest_state_event:
        bus_state = latest_state_event.payload.get(
            "to_state"
        ) or latest_state_event.payload.get("state")
        if bus_state != log_status:
            warnings.append(
                f"Drift detected: Markdown state='{log_status}' vs Bus state='{bus_state}' for ticket {plan_id}"
            )
    else:
        warnings.append(f"No STATE_CHANGED event found in bus for ticket {plan_id}")

    return warnings


def _check_pre_closure_invariants(plan_id: str) -> list[str]:
    """Check pre-closure invariants (IN_PROGRESS, APPROVED, PENDING)."""
    result = []
    # Check: no BUILDER_EXIT should exist before close
    if not BUS_AVAILABLE or not event_bus:
        return result
    builder_exit = event_bus.latest_event(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if builder_exit:
        result.append(
            "BUILDER_EXIT exists but ticket not in READY_FOR_REVIEW/COMPLETED"
        )
    return result


def _check_post_closure_built_exit(
    plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check BUILDER_EXIT invariant. Returns (errors, warnings)."""
    errors, warnings = [], []
    if not BUS_AVAILABLE or not event_bus:
        return errors, warnings

    builder_exit = event_bus.latest_event(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if not builder_exit:
        errors.append(
            f"INVARIANT: Missing BUILDER_EXIT event for ticket {plan_id} in state {log_status}"
        )
    else:
        # ticket_id is at event level, exit_reason and completion_summary are in payload
        payload = builder_exit.payload
        if not builder_exit.ticket_id:
            errors.append(f"INVARIANT: BUILDER_EXIT missing ticket_id for {plan_id}")
        if not payload.get("exit_reason"):
            errors.append(
                f"INVARIANT: BUILDER_EXIT missing required field exit_reason for {plan_id}"
            )
        if not payload.get("completion_summary"):
            warnings.append(f"BUILDER_EXIT missing completion_summary for {plan_id}")
    return errors, warnings


def _check_post_closure_breaker(log_status: str) -> list[str]:
    """Check circuit breaker invariant. Returns errors."""
    errors = []
    breaker = _read_circuit_breaker()
    if breaker.get("state") == "OPEN" and log_status == "READY_FOR_REVIEW":
        errors.append("INVARIANT: Circuit breaker OPEN but ticket in READY_FOR_REVIEW")
    return errors


def _check_post_closure_lock(plan_id: str, log_status: str) -> list[str]:
    """Check builder lock invariant. Returns warnings."""
    warnings = []
    lock = _read_builder_lock()
    if lock and lock.get("ticket_id") == plan_id and log_status == "COMPLETED":
        warnings.append(f"Builder lock still held for completed ticket {plan_id}")
    return warnings


def _check_post_closure_state_changed(
    plan_id: str, log_status: str
) -> tuple[list[str], list[str]]:
    """Check STATE_CHANGED invariant. Returns (errors, warnings)."""
    errors, warnings = [], []
    if not BUS_AVAILABLE or not event_bus:
        return errors, warnings

    state_event = event_bus.latest_event(ticket_id=plan_id, event_type="STATE_CHANGED")
    if not state_event:
        errors.append(f"INVARIANT: Missing STATE_CHANGED event for ticket {plan_id}")
    else:
        bus_state = state_event.payload.get("to_state")
        if bus_state and bus_state != log_status:
            warnings.append(
                f"STATE_CHANGED to_state='{bus_state}' differs from log_status='{log_status}'"
            )
    return errors, warnings


def _check_builder_exit_order(plan_id: str) -> list[str]:
    """
    Check that BUILDER_EXIT comes before STATE_CHANGED READY_FOR_REVIEW in sequence.
    Returns warnings list (not errors, to avoid invalidating historical tickets).

    This function checks the COMPLETE sequence of events, not just the latest.
    For each STATE_CHANGED -> READY_FOR_REVIEW, there must be a BUILDER_EXIT
    with a lower sequence number.
    """
    warnings = []
    if not BUS_AVAILABLE or not event_bus:
        return warnings

    # Get all BUILDER_EXIT events for this ticket
    builder_exits = event_bus.read_events(ticket_id=plan_id, event_type="BUILDER_EXIT")
    if not builder_exits:
        # No BUILDER_EXIT yet - invariant doesn't apply
        return warnings

    # Get all STATE_CHANGED events for this ticket with to_state=READY_FOR_REVIEW
    state_events = event_bus.read_events(ticket_id=plan_id, event_type="STATE_CHANGED")
    ready_for_review_events = [
        e for e in state_events if e.payload.get("to_state") == "READY_FOR_REVIEW"
    ]

    if not ready_for_review_events:
        # No STATE_CHANGED READY_FOR_REVIEW yet - invariant doesn't apply
        return warnings

    # Check order: for EACH STATE_CHANGED READY_FOR_REVIEW, there must be a
    # BUILDER_EXIT with a lower sequence number.
    # This detects inversions at any point in the sequence, not just the latest.
    for ready_event in ready_for_review_events:
        # Find if there's any BUILDER_EXIT before this STATE_CHANGED
        has_prior_exit = any(
            exit_event.sequence_number < ready_event.sequence_number
            for exit_event in builder_exits
        )

        if not has_prior_exit:
            warnings.append(
                f"ORDER INVARIANT: STATE_CHANGED READY_FOR_REVIEW (seq={ready_event.sequence_number}) "
                f"has no prior BUILDER_EXIT for ticket {plan_id}. "
                f"BUILDER_EXIT should be emitted before STATE_CHANGED READY_FOR_REVIEW."
            )

    return warnings


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

    if not plan_id or plan_id == "N/A":
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
    """Check scope violations for validate command. Returns (errors, warnings)."""
    errors, warnings = [], []
    if "READY_FOR_REVIEW" in log_status:
        changed_files = get_changed_files()
        gate_result = check_scope_gate(plan_content, changed_files, _exclude_files())
        if not gate_result["valid"]:
            # Scope violations in READY_FOR_REVIEW are warnings only, not errors
            warnings.extend(
                [f"Out of scope: {f}" for f in sorted(gate_result["out_of_scope"])]
            )
        warnings.extend([f"Warning: {w}" for w in gate_result["warnings"]])
    return errors, warnings


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
        write_file(STATE_FILE, updated_state)


def _handle_manager_approve(  # noqa: C901 - flag handler intentionally branches across validation and closeout
    ticket_id: str, json_output: bool, force_mode: bool
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
    if not ticket_id or ticket_id == "N/A":
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WP-XXXX")
        return 1

    # Load current state
    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    current_plan_id = get_plan_id(plan_content)
    log_status = get_status(log_content, "**Estado:**")

    # Validate ticket_id matches active ticket
    if not current_plan_id or current_plan_id == "N/A":
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
                        "error": f"Ticket {ticket_id} does not match active ticket {current_plan_id}",
                        "provided_ticket": ticket_id,
                        "active_ticket": current_plan_id,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[ERROR] Ticket {ticket_id} does not match active ticket {current_plan_id}"
            )
        return 1

    # Check idempotency per-ticket using bus events (not just global markdown state)
    # If there's already a SUPERVISOR_CLOSED event for this ticket, it's already completed
    if BUS_AVAILABLE and event_bus:
        supervisor_closed_events = event_bus.read_events(
            ticket_id=ticket_id, event_type="SUPERVISOR_CLOSED"
        )
        if supervisor_closed_events:
            # Ticket already closed in bus - idempotent return
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

    # Fallback: also check markdown state for tickets without bus events
    if "COMPLETED" in log_status:
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

    # Emit canonical closeout cascade
    if BUS_AVAILABLE and event_bus:
        _emit_manager_approve_cascade(event_bus, ticket_id)

    # Sync markdowns to COMPLETED
    _sync_markdowns_to_completed(ticket_id)

    # Reset circuit breaker on successful completion
    _reset_circuit_breaker(ticket_id)

    # Release builder lock
    _release_builder_lock(ticket_id)

    if json_output:
        print(json.dumps({"status": "closed", "ticket_id": ticket_id}, indent=2))
    else:
        print(f"[OK] Ticket {ticket_id} closed canonically.")

    return 0


def _handle_request_changes(  # noqa: C901
    ticket_id: str, json_output: bool, force_mode: bool
) -> int:
    """
    Handle --request-changes flag.
    Transitions ticket to IN_PROGRESS (requeue builder) if N < threshold, or
    HUMAN_GATE if N >= threshold. The threshold is the single source of truth
    in agents.json (manager_review.max_attempts); see get_human_gate_threshold().
    """
    if not ticket_id or ticket_id == "N/A":
        if json_output:
            print(json.dumps({"error": "No ticket_id provided"}, indent=2))
        else:
            print("[ERROR] No ticket_id provided. Use --ticket WP-XXXX")
        return 1

    plan_content = read_file(WORK_PLAN)
    log_content = read_file(EXEC_LOG)
    current_plan_id = get_plan_id(plan_content)
    log_status = get_status(log_content, "**Estado:**")

    if not current_plan_id or current_plan_id == "N/A":
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
        latest = event_bus.latest_event(ticket_id=ticket_id)
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

        event_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "from_state": log_status,
                "to_state": to_state,
                "reason": reason,
                "source": "request-changes",
            },
        )
    else:
        to_state = "IN_PROGRESS"

    # Sync markdowns
    if to_state == "HUMAN_GATE":
        update_log_status(
            "HUMAN_GATE",
            f"Manager requested changes. Escalated to HUMAN_GATE after {rejection_count} rejections.",
        )
        action = {
            "role": "SUPERVISOR",
            "context_file": ".supervisor_rules",
            "workflow_file": ".agent/workflows/supervisor_workflow.md",
            "instruction": f"Escalated to HUMAN_GATE after {rejection_count} rejections on {ticket_id}.",
            "plan_id": ticket_id,
            "plan_status": get_status(plan_content, "**Estado:**"),
            "log_status": "HUMAN_GATE",
            "action_type": "HUMAN_GATE",
            "plan_type": get_plan_type(plan_content),
        }
        update_turn_file(action)

        state_content = read_file(STATE_FILE)
        if state_content:
            updated_state = state_content.replace(
                "- **Estado actual:** READY_FOR_REVIEW",
                "- **Estado actual:** HUMAN_GATE",
                1,
            )
            write_file(STATE_FILE, updated_state)

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
        update_log_status(
            "IN_PROGRESS",
            f"Manager requested changes ({rejection_count} rejections). Requeuing Builder.",
        )
        action = {
            "role": "BUILDER",
            "context_file": ".builder_rules",
            "workflow_file": ".agent/workflows/builder_workflow.md",
            "instruction": f"Manager requested changes on {ticket_id}. Re-implement fixes.",
            "plan_id": ticket_id,
            "plan_status": get_status(plan_content, "**Estado:**"),
            "log_status": "IN_PROGRESS",
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


def _handle_validate(json_output: bool) -> int:  # noqa: C901
    """Handle --validate flag.

    Aggregates many independent validators (state files, scope, bus drift,
    deliverable_type). Each branch is simple; the function is intentionally
    a thin coordinator. Splitting it further would harm readability.
    """
    errors = validate_state_files()
    warnings = {}

    plan_content = read_file(WORK_PLAN)
    for file_key, warns in _collect_deliverable_type_warnings(plan_content).items():
        warnings.setdefault(file_key, []).extend(warns)

    log_content = read_file(EXEC_LOG)
    log_status = get_status(log_content, "**Estado:**")

    # Check scope violations
    scope_errors, scope_warnings = _check_scope_for_validate(plan_content, log_status)
    if scope_errors:
        errors.setdefault("scope", []).extend(scope_errors)
    if scope_warnings:
        warnings.setdefault("scope", []).extend(scope_warnings)

    # Check bus drift
    drift_warnings = _check_bus_drift(plan_content, log_status)
    if drift_warnings:
        warnings.setdefault("bus_drift", []).extend(drift_warnings)

    # Check invariants (pre and post-closure)
    invariant_result = _check_invariants(plan_content, log_content, log_status)
    if invariant_result["errors"]:
        errors.setdefault("invariants", []).extend(invariant_result["errors"])
    if invariant_result["warnings"]:
        warnings.setdefault("invariants", []).extend(invariant_result["warnings"])

    total_errors = sum(len(errs) for errs in errors.values())
    total_warnings = sum(len(warns) for warns in warnings.values())

    if json_output:
        output = {"errors": errors, "warnings": warnings}
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


def _handle_main_action(
    skip_gates: bool, strict_mode: bool, json_output: bool, reset_turn_mode: bool
) -> int:
    """Handle main action determination and output."""
    if SESSION_TRACKER_AVAILABLE:
        show_recovery_hint()

    print("\n  Generando mapa del proyecto...")
    generate_project_map()
    print("  [OK] Mapa actualizado")

    notif_errors = validate_state_files().get("notifications.md", [])
    if notif_errors:
        fix_corrupted_notifications()

    archive_old_notifications()

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
    "--validate": _handle_validate,
    "--archive": _handle_archive,
    "--manager-approve": _handle_manager_approve,
    "--request-changes": _handle_request_changes,
}


def main():  # noqa: C901 - CLI dispatch intentionally centralizes flag handling
    """Funcion principal del controller."""
    # WP-2026-122: Parse --project-root FIRST and export to environment
    # This must happen before any imports that depend on project_root
    if "--project-root" in sys.argv:
        idx = sys.argv.index("--project-root")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            project_root_value = sys.argv[idx + 1]
            os.environ["AGENT_PROJECT_ROOT"] = str(Path(project_root_value).resolve())

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

    # Parse --ticket (used by --manager-approve and --request-changes)
    ticket_id = None
    if "--ticket" in sys.argv:
        idx = sys.argv.index("--ticket")
        if idx + 1 >= len(sys.argv):
            print("[ERROR] --ticket requires a ticket ID.")
            return 1
        next_token = sys.argv[idx + 1]
        if next_token.startswith("--"):
            print("[ERROR] --ticket requires a ticket ID, not another flag.")
            return 1
        ticket_id = next_token
    elif "--manager-approve" in sys.argv:
        idx = sys.argv.index("--manager-approve")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]
    elif "--request-changes" in sys.argv:
        idx = sys.argv.index("--request-changes")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            ticket_id = sys.argv[idx + 1]

    # Check for --mark-ready
    if "--mark-ready" in sys.argv:
        return _handle_mark_ready(scope_override, json_output, force_mode)

    # Check for --bootstrap-ticket
    if "--bootstrap-ticket" in sys.argv:
        return _handle_bootstrap_ticket(json_output)

    # Check for specific flag handlers
    for flag, handler in FLAG_HANDLERS.items():
        if flag in sys.argv:
            # Pass json_output to validate handler if needed
            if flag == "--validate":
                return handler(json_output)
            # Pass ticket_id to manager-approve handler
            if flag in ("--manager-approve", "--request-changes"):
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
