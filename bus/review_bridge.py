# ruff: noqa: S603
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import (
    opencode_transport,
    review_observations,
    review_packet,
    review_report,
    review_rubrics,
    review_state,
)
from .blocker_signature import (
    blocker_lines_from_signature,
    extract_signatures_from_feedback,
)
from .decision_parser import (
    ReviewDecision,
    extract_decision_from_single_line,
    extract_decision_from_text_events,
    load_decision_artifact,
    parse_opencode_decision,
    parse_opencode_decision_with_retry,
    parse_opencode_json_decision,
    resolve_event_phase,
)
from .event_bus import EventBus
from .skill_resolver import SkillResolver, create_resolver
from .ticket_id import WORKPLAN_ID_PATTERN
from .time_utils import now_local
from .utils import count_trailing_changes


# Windows CreateProcess argv limit ~8191 chars; leave margin for other args
OS_NAME = os.name
ARGV_PROMPT_THRESHOLD = 8000

# Re-exported from bus/review_observations.py for backward compatibility.
MAX_RUBRIC_OBSERVATIONS = review_observations.MAX_RUBRIC_OBSERVATIONS
MAX_OBSERVATION_SIGNAL_CHARS = review_observations.MAX_OBSERVATION_SIGNAL_CHARS

# WT-2026-242a: canonical source bus/opencode_transport.py (re-exported here).
_UNSUPPORTED_JSON_FLAG_PATTERNS = opencode_transport.UNSUPPORTED_JSON_FLAG_PATTERNS

# Domain-to-deliverable_type relevance mapping (WP-2026-177).
# Canonical source: bus/review_observations.py (re-exported here).
DOMAIN_DTYPE_MAP: dict[str, set[str]] = review_observations.DOMAIN_DTYPE_MAP


# ReviewDecision is defined in bus.decision_parser (WT-2026-255a).
# Re-exported here for backward compatibility.
__all_compat__ = ["ReviewDecision"]


@dataclass(slots=True)
class ReviewResult:
    decision: ReviewDecision
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    feedback: str = ""
    transport_ok: bool = True
    transport_error: str = ""
    parse_method: str = ""


@dataclass(slots=True)
class TicketContext:
    """Canonical ticket state ingested from the bus.

    Before: Requires event_bus, project_root, and valid ticket_id.
    During: Reads work_plan.md for deliverable_type and ticket_id, queries
            event_bus for latest STATE_CHANGED event.
    After: Returns immutable snapshot of ticket state for review transport.
    """

    ticket_id: str
    state: str
    deliverable_type: str


class TicketStateIngest:
    """Canonical ticket state ingestion from the bus.

    This class is responsible for reading the current ticket state from the
    canonical sources (event_bus, work_plan.md) without any transport logic.

    Before: Requires event_bus and project_root.
    During: Queries event_bus for STATE_CHANGED events, parses work_plan.md
            for deliverable_type and active ticket_id.
    After: Returns TicketContext snapshots for review transport.
    """

    def __init__(self, event_bus: EventBus, project_root: Path):
        self.event_bus = event_bus
        self.project_root = Path(project_root)

    def _read_canonical(self, name: str) -> str:
        """Read a canonical collaboration file."""
        path = self.project_root / ".agent" / "collaboration" / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _read_canonical_optional(self, name: str) -> str | None:
        """Read an optional canonical collaboration file."""
        path = self.project_root / ".agent" / "collaboration" / name
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _get_active_ticket_id(self) -> str | None:
        """Read active ticket ID from work_plan.md."""
        work_plan = self.project_root / ".agent" / "collaboration" / "work_plan.md"
        if not work_plan.exists():
            return None
        content = work_plan.read_text(encoding="utf-8")
        match = WORKPLAN_ID_PATTERN.search(content)
        return match.group(1) if match else None

    def _read_deliverable_type(self) -> str:
        """Read the deliverable_type from work_plan.md. Defaults to 'code'."""
        work_plan = self.project_root / ".agent" / "collaboration" / "work_plan.md"
        if not work_plan.exists():
            return "code"
        try:
            content = work_plan.read_text(encoding="utf-8")
            match = re.search(
                r"^\s*-\s*\*\*deliverable_type:\*\*\s*(\S+)",
                content,
                re.IGNORECASE | re.MULTILINE,
            )
            if not match:
                return "code"
            value = match.group(1).strip().lower()
            if "+" in value:
                return "mixed"
            valid_types = {"code", "documentation", "research", "analysis", "mixed"}
            return value if value in valid_types else "code"
        except Exception:
            return "code"

    def _latest_state(self, ticket_id: str) -> str:
        """Get the latest state from the event bus for a ticket."""
        latest = self.event_bus.latest_event(
            ticket_id=ticket_id, event_type="STATE_CHANGED"
        )
        if latest:
            return str((latest.payload or {}).get("to_state", "")).upper()
        return "IN_PROGRESS"

    def get_ticket_context(self, ticket_id: str | None = None) -> TicketContext | None:
        """Get a canonical TicketContext for review transport.

        Before: Requires ticket_id or falls back to work_plan.md active ticket.
        During: Queries event_bus for state, work_plan.md for deliverable_type.
        After: Returns TicketContext or None if ticket cannot be resolved.
        """
        resolved_id = ticket_id or self._get_active_ticket_id()
        if not resolved_id:
            return None
        return TicketContext(
            ticket_id=resolved_id,
            state=self._latest_state(resolved_id),
            deliverable_type=self._read_deliverable_type(),
        )


class ReviewBridge:
    """Review transport bridge between bus and Manager backend.

    This class handles the transport of review prompts and parsing of decisions.
    It delegates state ingestion to TicketStateIngest for separation of concerns.

    Before: Requires event_bus and project_root.
    During: Uses TicketStateIngest for state, builds prompts, executes review.
    After: Returns ReviewResult with decision and emits events to bus.
    """

    def __init__(
        self,
        event_bus: EventBus,
        project_root: Path,
        skill_resolver: SkillResolver | None = None,
    ):
        self.event_bus = event_bus
        self.project_root = Path(project_root)
        self.state_ingest = TicketStateIngest(event_bus, project_root)
        self.skill_resolver = skill_resolver or create_resolver(
            project_root, validate=False
        )
        self._canonical_anti_patterns = self._load_canonical_anti_patterns()
        # WT-2026-242a: Stub for backward compatibility with other test files.
        # This attribute no longer governs the JSON/no-JSON decision — the
        # bridge uses try-first via _run_opencode_review() + _parse_opencode_decision().
        self._supports_json_format = True

    def _get_current_role(self) -> str:
        """Get the current active role from TURN.md.

        Returns:
            Role name (e.g., "BUILDER", "MANAGER") or "BUILDER" as fallback.
        """
        turn_path = self.project_root / ".agent" / "collaboration" / "TURN.md"
        if not turn_path.exists():
            return "BUILDER"
        content = turn_path.read_text(encoding="utf-8")
        match = re.search(r"\|\s*\*\*ROL\*\*\s*\|\s*\*\*([A-Z]+)\*\*\s*\|", content)
        return match.group(1) if match else "BUILDER"

    def _resolve_motor_root(self) -> Path | None:
        """Resolve motor root from workspace's motor_destination_link.json.

        WP-2026-176: Thin compatibility wrapper that delegates to motor_link.
        The workspace may carry motor_destination_link.json in its
        .agent/config/ directory pointing to the external motor repository.

        Returns:
            Absolute Path to the motor root, or None if the link file is missing
            or malformed.
        """
        from runtime.motor_link import resolve_motor_root as _resolve

        return _resolve(self.project_root)

    def _motor_root_or_raise(self) -> Path:
        """Return motor_root for git evidence operations, or raise.

        WT-2026-215: Unico seam para resolver el motor_root en todas las
        funciones de evidencia/provenance git. Cada call site llama a este
        metodo en lugar de pasar ``motor_root`` como parametro encadenado.

        Raises:
            RuntimeError: If motor link is not configured (missing
                motor_destination_link.json or invalid).
        """
        root = self._resolve_motor_root()
        if root is None:
            raise RuntimeError(
                "motor_root not resolvable: motor_destination_link.json missing "
                "or invalid. Cannot run git evidence operations."
            )
        return root

    def _resolve_motor_controller(self) -> Path | None:
        """Resolve agent_controller.py from external motor root, or None.

        Thin compatibility wrapper that delegates to motor_link.

        Returns:
            Absolute Path to the motor's agent_controller.py, or None if the
            motor root cannot be resolved or the controller does not exist there.
        """
        from runtime.motor_link import resolve_motor_controller as _resolve

        return _resolve(self.project_root)

    def _ensure_durable_changes_consumer(
        self,
        *,
        supervisor,
        ticket_id: str,
        review_decision_seq: int,
    ) -> None:
        """Guarantee one supervisor-owned CHANGES consumer in bounded time."""
        if not hasattr(supervisor, "_is_supervisor_lock_stale"):
            return
        if not supervisor._is_supervisor_lock_stale():
            return

        if any(
            event.sequence_number > review_decision_seq
            for event in self.event_bus.read_events(ticket_id=ticket_id)
            if event.event_type == "BUILDER_RELAUNCH_ATTEMPTED"
        ):
            print(
                "[review_bridge] BUILDER_RELAUNCH_ATTEMPTED already exists after "
                "REVIEW_DECISION; skipping supervisor rescue tick to avoid double relaunch.",
                flush=True,
            )
            return

        if all(
            hasattr(supervisor, name)
            for name in ("bootstrap", "run_once", "_release_supervisor_lock")
        ):
            print(
                "[review_bridge] Supervisor daemon absent after --request-changes; "
                "running one durable supervisor tick.",
                flush=True,
            )
            acquired = bool(supervisor.bootstrap())
            if not acquired:
                print(
                    "[review_bridge] Supervisor rescue tick skipped: another "
                    "supervisor instance acquired the lock first.",
                    flush=True,
                )
                return
            try:
                supervisor.run_once()
            finally:
                supervisor._release_supervisor_lock()
            return

        if hasattr(supervisor, "requeue_ticket"):
            print(
                "[review_bridge] Legacy fallback: supervisor object lacks "
                "bootstrap/run_once; invoking requeue_ticket directly.",
                flush=True,
            )
            supervisor.requeue_ticket(ticket_id, review_decision_seq)

    @staticmethod
    def _looks_like_opencode_help(stdout: str, stderr: str) -> bool:
        return opencode_transport.looks_like_opencode_help(stdout, stderr)

    @staticmethod
    def _looks_like_auth_failure(stdout: str, stderr: str) -> bool:
        return opencode_transport.looks_like_auth_failure(stdout, stderr)

    def _classify_transport_result(
        self, stdout: str, stderr: str, exit_code: int
    ) -> tuple[bool, str]:
        """Classify whether the OpenCode invocation reached the model."""
        if "TimeoutExpired" in stderr:
            return True, "timeout_retryable"
        if exit_code != 0:
            return False, f"exit_code={exit_code}"
        # Route through the instance statics so monkeypatched seams keep working.
        if self._looks_like_auth_failure(stdout, stderr):
            return False, "auth_failed"
        if self._looks_like_opencode_help(stdout, stderr):
            return False, "help_output_detected"
        return True, ""

    @staticmethod
    def _needs_json_fallback(stderr: str) -> bool:
        return opencode_transport.needs_json_fallback(stderr)

    def _review_env(self) -> dict[str, str]:
        return opencode_transport.build_review_env()

    def _get_manager_backend(self) -> str:
        """Get the backend assigned to MANAGER role from agents.json.

        Before: Fell back to a legacy backend when agents.json was unreadable.
        During: Reads agents.json and returns the MANAGER backend assignment.
        After: Returns "opencode" as the default fallback for the Manager.
        """
        try:
            from agents_config import get_backend_for_role, load_agents_config

            config = load_agents_config(self.project_root)
            return get_backend_for_role("MANAGER", config)
        except Exception:
            # WP-2026-129: Fallback to opencode for the Manager
            return "opencode"

    def _get_manager_model(self) -> str | None:
        """Get the model override for MANAGER from role_models."""
        try:
            from agents_config import get_model_for_role, load_agents_config

            config = load_agents_config(self.project_root)
            return get_model_for_role("MANAGER", config)
        except Exception:
            return None

    @staticmethod
    def _normalize_opencode_model(model: str | None) -> str | None:
        return opencode_transport.normalize_opencode_model(model)

    def _get_canonical_files(self) -> list[Path]:
        """Get list of canonical collaboration files to attach to OpenCode review."""
        collaboration_dir = self.project_root / ".agent" / "collaboration"
        files = [
            collaboration_dir / "work_plan.md",
            collaboration_dir / "execution_log.md",
            collaboration_dir / "TURN.md",
            collaboration_dir / "STATE.md",
        ]
        ticket_id = self.state_ingest._get_active_ticket_id()
        if ticket_id:
            plan_file = collaboration_dir / f"PLAN_{ticket_id}.md"
            audit_file = collaboration_dir / f"AUDIT_{ticket_id}.md"
            if plan_file.exists():
                files.append(plan_file)
            if audit_file.exists():
                files.append(audit_file)
        return [f for f in files if f.exists()]

    def _prepare_repomix_output(
        self, max_context_bytes: int
    ) -> tuple[Path | None, dict | None]:
        out_path = self.project_root / ".agent" / "context" / "repomix_motor.xml"
        if out_path.exists():
            if out_path.stat().st_size <= max_context_bytes:
                return out_path, {
                    "status": "ok",
                    "reason": "Existing repomix_motor.xml context file found",
                    "output_path": str(out_path),
                }
            out_path.unlink()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return out_path, None

    def _resolve_repomix_runtime(
        self,
    ) -> tuple[Path | None, Path | None, dict | None]:
        motor_root = self._resolve_motor_root()
        if motor_root is None:
            return (
                None,
                None,
                {
                    "status": "skipped",
                    "reason": "motor_root not resolvable; repomix context skipped",
                },
            )
        config_candidates = (
            motor_root / "repomix.config.json",
            motor_root / "agent_system" / "templates" / "repomix.config.json",
        )
        config_path = next((p for p in config_candidates if p.exists()), None)
        if config_path is None:
            return (
                None,
                None,
                {
                    "status": "skipped",
                    "reason": "Repomix config not found in motor_root; context skipped",
                },
            )
        return motor_root, config_path, None

    def _ensure_repomix_context(self, timeout: int = 15) -> tuple[Path | None, dict]:
        """Return (path, repomix_status) where path is the repomix Path or None.

        The repomix_status dict exposes structured diagnostic fields:
          - status: "ok" | "failed" | "skipped"
          - reason: str explanation
          - returncode: int | None (only for failed)
          - stderr_tail: str | None (only for failed, last 500 chars)
          - output_path: str | None (only for ok)

        Non-blocking: returns (None, dict) on any failure so the review continues.
        Uses npx -y to avoid interactive prompts in unattended environments.
        """
        max_context_bytes = 1024 * 1024
        out_path, cached_status = self._prepare_repomix_output(max_context_bytes)
        if cached_status is not None:
            return out_path, cached_status
        motor_root, config_path, setup_status = self._resolve_repomix_runtime()
        if setup_status is not None:
            return None, setup_status
        cmd = [
            "npx",
            "-y",
            "repomix",
            "--style",
            "xml",
            "--compress",
            "--output",
            str(out_path),
        ]
        if config_path.exists():
            cmd.extend(["--config", str(config_path)])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=motor_root,
                timeout=timeout,
            )
            if result.returncode == 0 and out_path.exists():
                if out_path.stat().st_size > max_context_bytes:
                    out_path.unlink()
                    return None, {
                        "status": "skipped",
                        "reason": (
                            f"Repomix output exceeds {max_context_bytes} bytes budget"
                        ),
                    }
                return out_path, {
                    "status": "ok",
                    "reason": "Repomix completed successfully",
                    "output_path": str(out_path),
                }
            stderr_tail = (result.stderr or "")[-500:]
            return None, {
                "status": "failed",
                "reason": (f"Repomix exited with returncode {result.returncode}"),
                "returncode": result.returncode,
                "stderr_tail": stderr_tail,
            }
        except FileNotFoundError:
            return None, {
                "status": "skipped",
                "reason": "npx not found; repomix cannot execute",
            }
        except subprocess.TimeoutExpired:
            return None, {
                "status": "failed",
                "reason": f"Repomix timed out after {timeout}s",
            }
        except Exception as exc:
            return None, {
                "status": "skipped",
                "reason": (f"Repomix failed: {type(exc).__name__}: {exc}"),
            }

    def _get_active_ticket_id(self) -> str | None:
        """Read active ticket ID from work_plan.md."""
        work_plan = self.project_root / ".agent" / "collaboration" / "work_plan.md"
        if not work_plan.exists():
            return None
        content = work_plan.read_text(encoding="utf-8")
        # Look for **- ID:** WP-XXXX-XXX, WT-XXXX-XXX or XXX-XXXX-XXX pattern
        match = WORKPLAN_ID_PATTERN.search(content)
        if match:
            return match.group(1)
        return None

    def _read_deliverable_type(self) -> str:
        """Read the deliverable_type from work_plan.md. Defaults to 'code'."""
        work_plan = self.project_root / ".agent" / "collaboration" / "work_plan.md"
        if not work_plan.exists():
            return "code"
        try:
            content = work_plan.read_text(encoding="utf-8")
            match = re.search(
                r"^\s*-\s*\*\*deliverable_type:\*\*\s*(\S+)",
                content,
                re.IGNORECASE | re.MULTILINE,
            )
            if not match:
                return "code"
            value = match.group(1).strip().lower()
            if "+" in value:
                return "mixed"
            valid_types = {"code", "documentation", "research", "analysis", "mixed"}
            if value not in valid_types:
                return "code"
            return value
        except Exception:
            return "code"

    def _read_canonical(self, name: str) -> str:
        path = self.project_root / ".agent" / "collaboration" / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _read_canonical_optional(self, name: str) -> str | None:
        path = self.project_root / ".agent" / "collaboration" / name
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _extract_ticket_section(self, ticket_id: str) -> str:
        content = self.state_ingest._read_canonical("execution_log.md")
        pattern = rf"### {re.escape(ticket_id)}.*?(?=\n### [A-Za-z]{{2,3}}-|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return (
            match.group(0)
            if match
            else f"[execution_log section for {ticket_id} not found]"
        )

    def _git_diff_stat(self) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            base, warning = self._resolve_review_base(git_bin, ticket_id=None)
            result = subprocess.run(
                [git_bin, "diff", "--stat", f"{base}..HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
            prefix = f"{warning}\n" if warning else ""
            return prefix + (result.stdout or "[git diff --stat empty]")
        except Exception as e:
            return f"[Error fetching git diff --stat: {e}]"

    def _build_diff_for_files_likely_touched(
        self, ticket_id: str, budget_bytes: int
    ) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            base, warning_prefix = self._resolve_review_base(
                git_bin, ticket_id=ticket_id
            )
            result = subprocess.run(
                [git_bin, "diff", f"{base}..HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=15,
            )
            prefix = f"{warning_prefix}\n" if warning_prefix else ""
            diff = prefix + (result.stdout or "")
            diff_bytes = diff.encode("utf-8")
            if len(diff_bytes) <= budget_bytes:
                return diff
            truncated = diff_bytes[:budget_bytes].decode("utf-8", errors="ignore")
            return truncated + "\n\n[diff truncado por budget]"
        except Exception as e:
            return f"[Error fetching git diff: {e}]"

    # WT-2026-221b: canonical source bus/review_packet.py (re-exported here).
    DOCS_ONLY_PATTERNS: tuple[str, ...] = review_packet.DOCS_ONLY_PATTERNS
    COLLABORATION_ONLY_PATTERNS: tuple[str, ...] = (
        review_packet.COLLABORATION_ONLY_PATTERNS
    )

    # ── Diff collection and classification ──────────────────────────────
    # Extracted to bus/review_packet.py (monolith decomposition).
    # Thin wrappers kept for backward compatibility.

    @staticmethod
    def _path_matches_any(path: str, patterns: tuple[str, ...]) -> bool:
        return review_packet.path_matches_any(path, patterns)

    def _get_motor_diff_files(self) -> list[str]:
        motor_root = self._resolve_motor_root()
        if motor_root is None:
            return []
        return review_packet.get_motor_diff_files(motor_root)

    def _get_destination_diff_files(self) -> list[str]:
        return review_packet.get_destination_diff_files(self.project_root)

    def _classify_diff_files(
        self,
        motor_files: list[str],
        destination_files: list[str],
    ) -> dict:
        # Class-level pattern tuples remain the seam (tests may override them).
        return review_packet.classify_diff_files(
            motor_files,
            destination_files,
            docs_patterns=self.DOCS_ONLY_PATTERNS,
            collab_patterns=self.COLLABORATION_ONLY_PATTERNS,
        )

    def classify_review_packet(self, ticket_id: str) -> dict:
        """WT-2026-221b: Classify a review packet for evidence gate.

        Before:
            - ticket_id must be valid.
            - git must be available (best-effort if not).

        During:
            - Collects diff files from motor root (productive changes) and
              project root (destination changes).
            - Classifies files into docs-only, collaboration-only, or productive
              categories.
            - Checks for bus/state activity of the ticket.

        After:
            - Returns a dict with classification keys:
                is_empty: True if no diff files found in either repo
                is_docs_only: True if all changes are documentation
                is_collaboration_only: True if all changes are collaboration
                has_motor_evidence: True if motor repo has productive changes
                has_destination_productive: True if destination has non-doc changes
                motor_diff_files: list of file paths from motor
                destination_diff_files: list of file paths from destination
                docs_only_files: list of docs/collab files
                productive_files: list of productive files
                reason: structured rejection reason string
                bus_active: True if ticket state is consistent
            - Never raises: all exceptions caught, returns safe-fail dict.
        """
        result: dict = {
            "is_empty": True,
            "is_docs_only": False,
            "is_collaboration_only": False,
            "has_motor_evidence": False,
            "has_destination_productive": False,
            "motor_diff_files": [],
            "destination_diff_files": [],
            "docs_only_files": [],
            "productive_files": [],
            "reason": "",
            "bus_active": False,
            "deliverable_type": "code",
        }

        try:
            # Check bus activity
            ctx = self.state_ingest.get_ticket_context(ticket_id)
            if ctx is not None:
                result["bus_active"] = True
                if isinstance(ctx, dict):
                    dtype = str(ctx.get("deliverable_type") or "code").lower()
                else:
                    dtype = str(getattr(ctx, "deliverable_type", "code")).lower()
                result["deliverable_type"] = dtype
            else:
                result["reason"] = (
                    f"Ticket {ticket_id} has no active bus/state context. "
                    "Cannot verify ticket consistency before review."
                )
                return result

            # Collect and classify files via unified evidence module
            motor_root = self._resolve_motor_root()
            from .evidence import resolve_evidence

            cls = resolve_evidence(motor_root, self.project_root, ticket_id)

            result["motor_diff_files"] = cls["motor_files"]
            result["destination_diff_files"] = cls["destination_files"]

            # Check for empty diff
            if not cls["all_files"]:
                result["reason"] = (
                    f"Ticket {ticket_id}: no diff files found in either motor or "
                    "destination repository. Review packet is empty."
                )
                return result

            result["is_empty"] = False

            result.update(
                {
                    "docs_only_files": cls["docs_only_files"],
                    "productive_files": cls["productive_files"],
                    "is_docs_only": cls["is_docs_only"],
                    "is_collaboration_only": cls["is_collaboration_only"],
                    "has_motor_evidence": cls["has_motor_evidence"],
                    "has_destination_productive": cls["has_destination_productive"],
                }
            )

            # Build rejection or acceptance reason
            if cls["is_docs_only"]:
                if cls["is_collaboration_only"]:
                    result["reason"] = (
                        f"Ticket {ticket_id}: all changes are collaboration-only "
                        f"artifacts ({len(cls['docs_only_files'])} files). No productive "
                        "evidence from motor or destination repository. "
                        "Run --pre-handoff first, then produce real changes."
                    )
                else:
                    result["reason"] = (
                        f"Ticket {ticket_id}: all changes are docs-only "
                        f"({len(cls['docs_only_files'])} files). No productive code "
                        "changes detected. Manager review blocked until real "
                        "implementation evidence exists."
                    )
            elif cls["has_motor_evidence"]:
                result["reason"] = (
                    f"Ticket {ticket_id}: has motor evidence "
                    f"({len(cls['motor_productive'])} productive files) and "
                    f"{len(cls['productive_files'])} total productive files "
                    "across both repos."
                )
            elif cls["has_destination_productive"]:
                result["reason"] = (
                    f"Ticket {ticket_id}: has destination productive evidence "
                    f"({len(cls['dest_productive'])} files) but no motor evidence."
                )
            else:
                result["reason"] = (
                    f"Ticket {ticket_id}: {len(cls['productive_files'])} productive "
                    "files found but no motor or destination productive changes "
                    "(unexpected state)."
                )

        except Exception as exc:
            result["reason"] = f"Classification error: {type(exc).__name__}: {exc}"

        return result

    def check_review_packet_diff_empty(self, ticket_id: str) -> bool:
        """WT-2026-203 / WT-2026-221b: Check review packet evidence.

        Before:
            - ticket_id must be valid.
            - git must be available (best-effort if not).

        During:
            - WT-2026-221b: Uses classify_review_packet() to detect if the
              review packet has no productive evidence (docs-only, collaboration-only,
              or empty diff). This replaces the simpler empty-diff-only check.
            - Also checks diff_stat for [git diff --stat empty] marker as fallback.
            - Also checks for [Error fetching git diff] markers.

        After:
            - Returns True if any empty-diff or docs-only/collaboration-only
              condition is met.
            - Returns False if productive evidence exists or check cannot
              be completed.
            - Never raises: all exceptions are caught and return False.
        """
        try:
            # WT-2026-221b: Use classify_review_packet for structured evidence check
            classification = self.classify_review_packet(ticket_id)
            if classification.get("is_empty"):
                return True
            dtype = str(classification.get("deliverable_type") or "code").lower()
            non_code_ticket = dtype in {"documentation", "research", "analysis"}
            if classification.get("is_docs_only") or classification.get(
                "is_collaboration_only"
            ):
                return not non_code_ticket
            if (
                classification.get("productive_files")
                or classification.get("has_motor_evidence")
                or classification.get("has_destination_productive")
            ):
                return False

            # Fallback: legacy empty diff checks for edge cases
            diff_stat = self._git_diff_stat()
            if "[git diff --stat empty]" in diff_stat:
                return True
            if "[Error fetching git diff" in diff_stat:
                return True

        except Exception:  # noqa: S110 - best-effort check, silent on failure
            pass

        return False

    def _git_provenance(self) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            base, warning = self._resolve_review_base(git_bin, ticket_id=None)
            result = subprocess.run(
                [
                    git_bin,
                    "log",
                    f"{base}..HEAD",
                    "--format=%H %ai %an",
                    "--no-merges",
                    "-1",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
            line = result.stdout.strip() or "[no commits found]"
            return f"{warning} {line}".strip() if warning else line
        except Exception as e:
            return f"[Error fetching git provenance: {e}]"

    def _resolve_review_base(
        self, git_bin: str, ticket_id: str | None = None
    ) -> tuple[str, str]:
        """Resolve the best base commit/range anchor for review diffs.

        Order of preference:
        1. merge-base(origin/main, HEAD)
        2. continuous trailing commit streak whose subject contains ticket_id
        3. HEAD^

        Returns:
            (base_ref, warning_prefix) where warning_prefix is empty on the
            primary path and descriptive on fallbacks.
        """
        result = None
        with contextlib.suppress(Exception):
            result = subprocess.run(
                [git_bin, "merge-base", "origin/main", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), ""

        if ticket_id:
            ticket_range = self._fallback_ticket_base_from_log(git_bin, ticket_id)
            if ticket_range:
                return (
                    ticket_range,
                    "[WARNING: origin/main not reachable, using ticket commit range fallback]",
                )

        return "HEAD^", "[WARNING: origin/main not reachable, using HEAD^ fallback]"

    def _fallback_ticket_base_from_log(
        self, git_bin: str, ticket_id: str
    ) -> str | None:
        """Infer ticket commit base from the latest contiguous commit streak."""
        try:
            result = subprocess.run(
                [git_bin, "log", "--format=%H%x09%s", "--no-merges", "-200"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            ticket_upper = ticket_id.upper()
            streak: list[str] = []
            boundary_sha: str | None = None
            for raw in result.stdout.splitlines():
                sha, _, subject = raw.partition("\t")
                if not sha:
                    continue
                if ticket_upper in subject.upper():
                    streak.append(sha)
                    continue
                if streak:
                    boundary_sha = sha
                    break
                return None

            if not streak:
                return None
            if boundary_sha:
                return boundary_sha

            oldest = streak[-1]
            parent = subprocess.run(
                [git_bin, "rev-parse", f"{oldest}^"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
            if parent.returncode == 0 and parent.stdout.strip():
                return parent.stdout.strip()
            return None
        except Exception:
            return None

    def _get_untracked_files(self) -> list[str]:
        """Get list of untracked files (??) from git status, filtered for deliverables.

        WT-2026-215: motor_root — untracked files relevant for review packet are
        code files in the motor pending commit, not workspace deliverables.

        Before: Requires a valid git repository at motor_root.
        During: Runs git status --porcelain -z, parses ?? entries, filters out
                generated artifacts (.agent/collaboration/, .agent/runtime/, .git/).
        After: Returns list of relative paths for untracked deliverables only.
        """
        try:
            git_bin = shutil.which("git") or "git"
            result = subprocess.run(
                [git_bin, "status", "--porcelain", "-z"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._motor_root_or_raise(),
                timeout=10,
            )
            if result.returncode != 0:
                return []

            untracked: list[str] = []
            entries = result.stdout.split("\0")
            for entry in entries:
                if not entry:
                    continue
                # Format: "?? path" when status is untracked
                if entry.startswith("?? "):
                    path = entry[3:]  # Skip "?? "
                    # Filter out generated artifacts and noise
                    if self._is_deliverable_path(path):
                        untracked.append(path)
            return untracked
        except Exception:
            return []

    def _is_deliverable_path(self, path: str) -> bool:
        """Check if an untracked path is a real deliverable (not generated noise).

        Before: Requires a relative path string from git status.
        During: Checks against exclusion patterns for .agent/, __pycache__, etc.
        After: Returns True if path should appear in review packet as deliverable.
        """
        # Exclude generated artifacts and runtime noise
        exclude_patterns = [
            ".agent/collaboration/",
            ".agent/runtime/",
            ".agent/runtime/memory/",
            ".agent/runtime/reviews/",
            ".agent/runtime/review_packets/",
            ".agent/runtime/tmp/",
            ".git/",
            "__pycache__/",
            ".pyc",
            ".pyo",
            ".ruff_cache/",
            ".cache/",
            ".uv-cache/",
            ".venv/",
            "node_modules/",
            "*.pyc",
        ]
        path_lower = path.lower()
        for pattern in exclude_patterns:
            if pattern.startswith("*"):
                if path_lower.endswith(pattern[1:]):
                    return False
            elif pattern in path_lower:
                return False
        return True

    # ── Review memory context ────────────────────────────────────────────
    # Extracted to bus/review_observations.py (monolith decomposition).
    # Thin wrappers kept for backward compatibility with existing tests
    # and any external callers that reach these private helpers.

    def _observations_path(self) -> Path:
        return review_observations.observations_path(self.project_root)

    def _canonical_anti_patterns_path(self) -> Path:
        return review_observations.canonical_anti_patterns_path()

    @staticmethod
    def _parse_canonical_anti_patterns(content: str) -> list[tuple[str, str]]:
        return review_observations.parse_canonical_anti_patterns(content)

    def _load_canonical_anti_patterns(self) -> list[tuple[str, str]]:
        # Pass the instance-resolved path so monkeypatched seams keep working.
        return review_observations.load_canonical_anti_patterns(
            self._canonical_anti_patterns_path()
        )

    def _render_canonical_anti_pattern_inventory(self) -> str:
        return review_observations.render_anti_pattern_inventory(
            self._canonical_anti_patterns
        )

    @staticmethod
    def _parse_observation_timestamp(raw_timestamp: object) -> datetime:
        return review_observations.parse_observation_timestamp(raw_timestamp)

    @staticmethod
    def _truncate_observation_signal(signal: object) -> str:
        return review_observations.truncate_observation_signal(signal)

    @staticmethod
    def _observation_matches_dtype(record: dict, dtype: str) -> bool:
        return review_observations.observation_matches_dtype(record, dtype)

    @staticmethod
    def _parse_observation_record(raw_line: str) -> dict | None:
        return review_observations.parse_observation_record(raw_line)

    @staticmethod
    def _record_to_observation_tuple(
        record: dict,
    ) -> tuple[datetime, str, str] | None:
        return review_observations.record_to_observation_tuple(record)

    def _relevant_domains_for_dtype(self, dtype: str) -> set[str]:
        return review_observations.relevant_domains_for_dtype(dtype)

    def _load_manager_review_observations_by_domain(
        self, dtype: str = "all"
    ) -> list[tuple[datetime, str, str]]:
        return review_observations.load_review_observations_by_domain(
            self.project_root, dtype
        )

    def _load_manager_review_observations(
        self, dtype: str = "all"
    ) -> list[tuple[datetime, str, str]]:
        return review_observations.load_review_observations(self.project_root, dtype)

    def _render_loader_rules(self, dtype: str = "all") -> str:
        if dtype == "all":
            return ""
        # Pass instance-resolved domains so monkeypatched seams keep working.
        return review_observations.render_loader_rules(
            dtype, domains=self._relevant_domains_for_dtype(dtype)
        )

    def _render_manager_review_learnings(self, dtype: str = "all") -> str:
        return review_observations.render_review_learnings(self.project_root, dtype)

    # ── Adaptive review state ────────────────────────────────────────────
    # Extracted to bus/review_state.py (monolith decomposition).
    # Thin wrappers kept for backward compatibility.

    def _adaptive_state_path(self) -> Path:
        return review_state.adaptive_state_path(self.project_root)

    def _load_adaptive_state(self, ticket_id: str) -> dict:
        return review_state.load_adaptive_state(self.project_root, ticket_id)

    def _save_adaptive_state(self, ticket_id: str, state_update: dict) -> None:
        review_state.save_adaptive_state(self.project_root, ticket_id, state_update)

    def _get_current_git_head(self) -> str | None:
        # Unresolvable motor link must degrade to None, not raise (original
        # contract: any failure inside the probe returns None).
        try:
            motor_root = self._motor_root_or_raise()
        except RuntimeError:
            return None
        return review_state.get_current_git_head(motor_root)

    def _compute_changed_files(self, last_git_head: str | None) -> list[str] | dict:
        """Compute files changed since the given git HEAD (WT-2026-196)."""
        if last_git_head is None:
            # Route through the instance method so monkeypatched seams work.
            if self._get_current_git_head() is None:
                return {
                    "status": "unknown",
                    "reason": "git is unavailable or not a repository",
                }
            return []  # First review in this ticket, no previous HEAD
        # Unresolvable motor link degrades to the unknown-dict contract.
        try:
            motor_root = self._motor_root_or_raise()
        except RuntimeError as exc:
            return {"status": "unknown", "reason": f"git error: {exc}"}
        return review_state.compute_changed_files(motor_root, last_git_head)

    def _compute_repeated_blockers(
        self,
        previous_signatures: list[str],
        current_feedback: str,
    ) -> tuple[list[str], bool]:
        return review_state.compute_repeated_blockers(
            previous_signatures, current_feedback
        )

    def _rubric_for_type(self, dtype: str, ticket_id: str) -> str:
        """Rubric text lives in bus/review_rubrics.py (monolith decomposition)."""
        return review_rubrics.rubric_for_type(
            dtype,
            ticket_id,
            anti_pattern_inventory=self._render_canonical_anti_pattern_inventory(),
        )

    def _build_review_prompt(  # noqa: C901
        self,
        ticket_id: str,
        dtype: str,
        adaptive_context: dict | None = None,
    ) -> str:
        # P1-2: work_plan, STATE, TURN (intocables)
        sections = [
            (name, self.state_ingest._read_canonical(name))
            for name in ("work_plan.md", "STATE.md", "TURN.md")
        ]

        # P3: execution_log section
        sections.append(
            (
                "execution_log.md (ticket section)",
                self._extract_ticket_section(ticket_id),
            )
        )

        # P4: PLAN + AUDIT opcionales
        for name in (f"PLAN_{ticket_id}.md", f"AUDIT_{ticket_id}.md"):
            content = self.state_ingest._read_canonical_optional(name)
            if content is not None:
                sections.append((name, content))

        # Calculate used bytes
        used = sum(len(c.encode("utf-8")) for _, c in sections)

        hard_cap_bytes = 80 * 1024
        canonical_budget = 60 * 1024

        # P4.5: git provenance (compact, inserted before diff)
        provenance = self._git_provenance()
        sections.append(("git provenance", provenance))
        used += len(provenance.encode("utf-8"))

        # P5: diff con budget restante
        if used < canonical_budget:
            remaining = hard_cap_bytes - used
            diff = self._build_diff_for_files_likely_touched(ticket_id, remaining)
            if diff:
                sections.append(("git diff (Files Likely Touched)", diff))
        else:
            sections.append(
                (
                    "git diff --stat",
                    self._git_diff_stat()
                    + "\n[diff omitido por budget. Read files directly if needed.]",
                )
            )

        # WP-2026-158: Untracked deliverables section
        untracked = self._get_untracked_files()
        if untracked:
            sections.append(("Untracked Deliverables", "\n".join(untracked)))

        # WP-2026-158: Compute filter_mode and severity metadata
        filter_mode = "added" if untracked else "diff_context"
        # Severity: info for diff_context, warn when untracked deliverables exist
        severity = "warn" if untracked else "info"

        # Compose
        parts = [self._rubric_for_type(dtype, ticket_id)]

        # WP-2026-158: Add packet metadata header
        parts.append(
            f"\n--- Packet Metadata ---\n"
            f"filter_mode: {filter_mode}\n"
            f"severity: {severity}\n"
            f"untracked_count: {len(untracked)}\n"
        )

        # Cross-cutting: validator evidence gate (all types)
        parts.append(
            "\n--- Cross-cutting check (all ticket types) ---\n"
            "AP-06 Validator evidence missing: if the work_plan declares an explicit validator as a "
            "quality gate (e.g. skills/validate_all.py, agent_controller --validate, ruff, pytest), "
            "execution_log.md must contain: (1) the exact command executed, (2) the result, and "
            "(3) a numeric outcome where applicable (e.g. '0 invalid skills', '253 passed', "
            "'All checks passed'). Declared validator + absent or ambiguous evidence: BLOCKER."
        )

        # WT-2026-221b: Motor evidence section (evidence-linked)
        motor_files = self._get_motor_diff_files()
        if motor_files:
            productive_motor = [
                f
                for f in motor_files
                if not self._path_matches_any(f, self.DOCS_ONLY_PATTERNS)
            ]
            if productive_motor:
                parts.append(
                    "\n--- Motor Evidence (repo_motor) ---\n"
                    f"Productive files changed in motor repository ({len(productive_motor)}):\n"
                    + "\n".join(f"- {f}" for f in productive_motor)
                )
            docs_motor = [f for f in motor_files if f not in productive_motor]
            if docs_motor:
                parts.append(
                    "\n--- Motor Documentation Changes ---\n"
                    f"Documentation/collaboration files changed in motor ({len(docs_motor)}):\n"
                    + "\n".join(f"- {f}" for f in docs_motor)
                )
        else:
            parts.append(
                "\n--- Motor Evidence (repo_motor) ---\n"
                "No diff detected in the motor repository. "
                "All changes appear to be destination-only."
            )

        # WP-2026-178: L2 memory rules from the loader (domain-organized, first priority)
        loader_rules = self._render_loader_rules(dtype=dtype)
        if loader_rules:
            parts.append(loader_rules)

        # Dynamic learnings — all types, scoped by dtype
        learnings = self._render_manager_review_learnings(dtype=dtype)
        if learnings:
            parts.append(f"\n--- Lecciones acumuladas de auditoria ---\n{learnings}")
        for name, content in sections:
            parts.append(f"\n--- {name} ---\n{content}")

        # WP-2026-127: Add skill filtering by role
        current_role = self._get_current_role()
        allowed_skills = self.skill_resolver.filter_skills_for_prompt(
            current_role, include_metadata=False
        )
        parts.append(
            f"\n--- ALLOWED SKILLS FOR ROLE {current_role} ---\n{allowed_skills}"
        )

        parts.append(
            "\n--- SYSTEM GENERATED & ARCHIVED ARTIFACTS ---\n"
            "Note: The Manager must treat the following files as system-generated or routinely archived.\n"
            "Deletions, moves to _archive/, or overwrites of these files are expected automated behaviors, not suspicious manual deletions:\n"
            "- PLAN_WP-*.md, AUDIT_WP-*.md\n"
            "- review_queue.md, notifications.md\n"
            "- archive_collaboration_artifacts.py\n"
            "- .session_state.json\n"
        )

        # WT-2026-196: Inject DIAGNOSTIC_MODE section when repeated blockers detected
        if adaptive_context and adaptive_context.get("diagnostic_mode"):
            repeated_blockers = adaptive_context.get("repeated_blockers", [])
            changed_files = adaptive_context.get(
                "changed_files_since_previous_review", []
            )
            last_feedback = adaptive_context.get("last_feedback", "")
            diag_parts = [
                "\n--- DIAGNOSTIC MODE ---\n"
                "The following BLOCKERS have been REPEATED since the previous review:\n"
            ]
            if repeated_blockers:
                diag_parts.extend(
                    f"REPEATED BLOCKER: {line}"
                    for sig in repeated_blockers
                    for line in blocker_lines_from_signature(sig)
                )
            else:
                diag_parts.append(
                    "REPEATED BLOCKER: (overlap detected, see BLOCKERS section)"
                )
            diag_parts.append("")
            if isinstance(changed_files, list):
                if changed_files:
                    diag_parts.append(
                        "Changed files since previous review: "
                        + ", ".join(changed_files)
                    )
                else:
                    diag_parts.append(
                        "Changed files since previous review: (none detected)"
                    )
            else:
                status = (
                    changed_files.get("status", "unknown")
                    if isinstance(changed_files, dict)
                    else "unknown"
                )
                reason = (
                    changed_files.get("reason", "")
                    if isinstance(changed_files, dict)
                    else ""
                )
                diag_parts.append(
                    f"Changed files since previous review: status={status}"
                    + (f" ({reason})" if reason else "")
                )
            diag_parts.append("")
            diag_parts.append(
                "REQUIRED ACTIONS (diagnostic mode):\n"
                "1. Re-read the exact affected code in the files listed under BLOCKERS.\n"
                "2. Check whether the Builder modified the affected files since the previous review "
                "(use the 'Changed files' list above).\n"
                "3. If the affected file WAS touched, explain why the bug persists despite the change.\n"
                "4. If the affected file was NOT touched, note that the Builder did not attempt the fix.\n"
                "5. Propose a concrete solution: specify the exact function, condition, or logic change needed.\n"
                "6. Propose a minimal test that would catch this specific blocker.\n"
                "7. Include a textual patch-plan if the change is small and safe.\n"
            )
            if last_feedback:
                diag_parts.append(
                    f"\nLast review feedback for reference:\n{last_feedback[:2000]}"
                )
            parts.append("\n".join(diag_parts))

        parts.append(
            "\n--- INSTRUCTIONS ---\n"
            "This review is advisory. It informs but does not replace the human operator's judgment.\n\n"
            "Judge whether the ticket OBJECTIVE and every Acceptance Criterion "
            "are actually met by the code in the diff. A criterion not addressed "
            "by the diff is NOT met, even if unrelated code looks fine.\n\n"
            "If you APPROVE, end with EXACTLY one line:\n"
            "DECISION: APPROVE\n\n"
            "If you request changes, you MUST emit this exact structure "
            "(headings included) before the final line:\n\n"
            "## SUMMARY\n"
            "<one line: why the ticket is not approved>\n\n"
            "## BLOCKERS\n"
            "- <file:line> <what is wrong> -> <what the Builder must do>\n\n"
            "## SUGGESTIONS\n"
            "- <non-blocking improvement, or 'none'>\n\n"
            "DECISION: CHANGES\n\n"
            "If you cannot decide and need human intervention, end with EXACTLY:\n"
            "DECISION: INSPECT\n"
        )
        return "\n".join(parts)

    def _run_legacy_manager_review(
        self,
        *,
        ticket_id: str,
        manager_executable: Path,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        """Legacy Manager review route. Preserved for backward compatibility."""
        exe_str = str(manager_executable)
        if OS_NAME == "nt" and exe_str.lower().endswith(".ps1"):
            cmd_candidate = Path(exe_str).with_suffix(".cmd")
            bat_candidate = Path(exe_str).with_suffix(".bat")
            if cmd_candidate.exists():
                exe_str = str(cmd_candidate)
            elif bat_candidate.exists():
                exe_str = str(bat_candidate)

        command = [exe_str, "review", ticket_id]
        if OS_NAME == "nt" and exe_str.lower().endswith(".ps1"):
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                *command,
            ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=self.project_root,
            env=self._review_env(),
            timeout=timeout_seconds,
        )
        return result.stdout or "", result.stderr or "", result.returncode

    def _materialize_manager_agent_spec(self) -> Path:
        """Ensure repo_destino has a runtime copy of the OpenCode manager agent.

        OpenCode resolves ``--agent manager`` from ``<project_root>/.opencode`` when
        ``--dir <project_root>`` is used. The authoritative agent lives in
        ``repo_motor/.opencode/agents/manager.md``, so we copy it into the active
        project just before launch.
        """
        motor_root = self._motor_root_or_raise()
        source = motor_root / ".opencode" / "agents" / "manager.md"
        if not source.exists():
            raise FileNotFoundError(
                f"Manager agent spec not found in repo_motor: {source}"
            )

        destination = self.project_root / ".opencode" / "agents" / "manager.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == destination.resolve():
            return destination
        shutil.copy2(source, destination)
        return destination

    def _run_opencode_review(  # noqa: C901
        self,
        *,
        ticket_id: str,
        prompt: str,
        attempt: int = 1,
        manager_executable: Path | None = None,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        """OpenCode review route using manager agent spec with context prompt.

        Transporte: el contexto completo se escribe a un review packet en
        .agent/runtime/review_packets/<ticket>_attempt-N.md y el prompt
        posicional es corto, indicando al Manager que lo lea. Evita el flag
        --file (array que consume el mensaje) y el limite de longitud de la
        CLI.
        """
        model = self._normalize_opencode_model(self._get_manager_model())

        executable = str(manager_executable) if manager_executable else "opencode"
        if OS_NAME == "nt" and executable == "opencode":
            executable = "opencode.cmd"

        motor_root = self._motor_root_or_raise()

        exe_full = shutil.which(executable) or executable
        if OS_NAME == "nt" and exe_full.lower().endswith(".ps1"):
            cmd_candidate = Path(exe_full).with_suffix(".cmd")
            bat_candidate = Path(exe_full).with_suffix(".bat")
            if cmd_candidate.exists():
                exe_full = str(cmd_candidate)
            elif bat_candidate.exists():
                exe_full = str(bat_candidate)

        repomix_path, repomix_status = self._ensure_repomix_context()

        # Review packet: el contexto completo del review se escribe a un
        # archivo dentro del repo; el Manager lo lee con sus herramientas.
        # El prompt posicional es corto (sin metacaracteres de cmd.exe).

        # Loguear repomix_status en el review packet (WT-2026-227a fix)
        if repomix_status:
            prompt += (
                f"\n\n--- Repomix Context Status ---\n"
                f"Status: {repomix_status.get('status', 'unknown')}\n"
                f"Reason: {repomix_status.get('reason', '')}\n"
            )

        packet_path = self._get_review_packet_path(ticket_id, attempt)
        packet_path.write_text(prompt, encoding="utf-8")
        packet_rel = packet_path.relative_to(self.project_root).as_posix()

        review_message = (
            f"Revisa {ticket_id} leyendo el archivo {packet_rel} con tus "
            "herramientas de lectura. Termina con exactamente "
            "DECISION: APPROVE o DECISION: CHANGES."
        )

        if not review_message.isascii():
            raise ValueError(
                "Review message must be ASCII for Windows command transport."
            )

        self._materialize_manager_agent_spec()

        # WT-2026-242a: Try-first with --format json using the real
        # manager_executable. Fall back without JSON only when stderr
        # contains specific unsupported-flag patterns.
        js_cmd_args = [
            exe_full,
            "run",
            "--agent",
            "manager",
            "--dir",
            str(self.project_root),
        ]
        if model:
            js_cmd_args.extend(["--model", model])
        js_cmd_args.extend(["--format", "json"])  # try-first
        if repomix_path:
            js_cmd_args.extend(["-f", str(repomix_path)])
        js_cmd_args.append(review_message)

        use_shell = False
        if OS_NAME == "nt" and (
            exe_full.lower().endswith(".cmd")
            or exe_full.lower().endswith(".bat")
            or "opencode" in exe_full.lower()
        ):
            use_shell = True

        if OS_NAME == "nt" and exe_full.lower().endswith(".ps1"):
            js_cmd_args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                *js_cmd_args,
            ]

        try:
            # En Windows, shell=True con una lista hace que cmd.exe trate
            # args[1:] como argumentos del propio shell: opencode arrancaria
            # sin ninguno. list2cmdline produce el string correcto.
            run_args = (
                subprocess.list2cmdline(js_cmd_args) if use_shell else js_cmd_args
            )
            result = subprocess.run(
                run_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=motor_root,
                env=self._review_env(),
                timeout=timeout_seconds,
                shell=use_shell,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, subprocess.TimeoutExpired):
                err_msg = f"TimeoutExpired: {exc}"
            return "", err_msg, 1

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode

        # WT-2026-242a: Try-first fallback — check if --format json was
        # rejected by the real executable (stderr indicates unsupported flag).
        if self._needs_json_fallback(stderr):
            fb_cmd_args = [
                exe_full,
                "run",
                "--agent",
                "manager",
                "--dir",
                str(self.project_root),
            ]
            if model:
                fb_cmd_args.extend(["--model", model])
            if repomix_path:
                fb_cmd_args.extend(["-f", str(repomix_path)])
            fb_cmd_args.append(review_message)

            # Recalculate shell for fallback args
            fb_use_shell = False
            if OS_NAME == "nt" and (
                exe_full.lower().endswith(".cmd")
                or exe_full.lower().endswith(".bat")
                or "opencode" in exe_full.lower()
            ):
                fb_use_shell = True

            if OS_NAME == "nt" and exe_full.lower().endswith(".ps1"):
                fb_cmd_args = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    *fb_cmd_args,
                ]

            try:
                fb_run_args = (
                    subprocess.list2cmdline(fb_cmd_args)
                    if fb_use_shell
                    else fb_cmd_args
                )
                fb_result = subprocess.run(
                    fb_run_args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=motor_root,
                    env=self._review_env(),
                    timeout=timeout_seconds,
                    shell=fb_use_shell,
                )
                return (
                    fb_result.stdout or "",
                    fb_result.stderr or "",
                    fb_result.returncode,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, subprocess.TimeoutExpired):
                    err_msg = f"TimeoutExpired: {exc}"
                return "", err_msg, 1

        return stdout, stderr, exit_code

    def _load_review_config(self) -> dict:
        """Load review configuration from agents.json with WP-2026-106 defaults.

        Before: max_attempts was 2 (legacy default).
        During: Reads agents.json manager_review section, applies WP-2026-106 threshold of 5.
        After: Returns config dict with max_attempts=5 for HUMAN_GATE escalation.
        """
        config_path = self.project_root / ".agent" / "config" / "agents.json"
        defaults = {
            "timeout_seconds": 180,
            "max_attempts": 5,  # WP-2026-106: elevated from 3 to 5 for HUMAN_GATE
            "retry_backoff_multiplier": 2.0,
        }
        if not config_path.exists():
            return defaults
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            cfg = data.get("manager_review", {})
            return {
                "timeout_seconds": int(
                    cfg.get("timeout_seconds", defaults["timeout_seconds"])
                ),
                "max_attempts": int(cfg.get("max_attempts", defaults["max_attempts"])),
                "retry_backoff_multiplier": float(
                    cfg.get(
                        "retry_backoff_multiplier", defaults["retry_backoff_multiplier"]
                    )
                ),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return defaults

    # ── Review attempt persistence ───────────────────────────────────────
    # Extracted to bus/review_report.py (monolith decomposition).
    # Thin wrappers kept for backward compatibility.

    def _get_review_log_path(self, ticket_id: str) -> Path:
        return review_report.review_log_path(self.project_root, ticket_id)

    def _get_review_packet_path(self, ticket_id: str, attempt: int) -> Path:
        return review_report.review_packet_path(self.project_root, ticket_id, attempt)

    def _persist_review_attempt(
        self,
        ticket_id: str,
        attempt: int,
        stdout: str,
        stderr: str,
        decision: ReviewDecision,
        review_packet_path: Path | None = None,
        parse_method: str = "",
        transport_ok: bool = True,
        transport_error: str = "",
    ) -> Path:
        """Persist attempt-N.md. Content building: bus/review_report.py."""
        changes_structure = (
            self._parse_changes_structure(stdout)
            if decision == ReviewDecision.CHANGES
            else None
        )
        return review_report.persist_review_attempt(
            self.project_root,
            ticket_id,
            attempt,
            stdout,
            stderr,
            decision,
            review_packet=review_packet_path,
            parse_method=parse_method,
            transport_ok=transport_ok,
            transport_error=transport_error,
            changes_structure=changes_structure,
        )

    @staticmethod
    def _extract_json_stream_text(stdout: str) -> str | None:
        """Extract NDJSON text (WT-2026-204). See bus/opencode_transport.py."""
        return opencode_transport.extract_json_stream_text(stdout)

    def _parse_changes_structure(self, stdout: str) -> dict[str, str]:
        """Parse structured sections from CHANGES review output.

        Before: Requires stdout string from Manager review.
        During: WT-2026-204: first extracts text from NDJSON streaming lines
                via ``_extract_json_stream_text()``, then applies regex on the
                extracted plain text. Falls back to raw stdout if no NDJSON
                text is found.
        After: Returns dict with 'summary', 'blockers', 'suggestions' keys
               (defaults to empty string if section not found).
        """
        result = {"summary": "", "blockers": "", "suggestions": ""}

        # WT-2026-204: Extract text from NDJSON streaming lines first
        parsed_text = self._extract_json_stream_text(stdout)
        search_text = parsed_text if parsed_text is not None else stdout

        # Pattern for ## SUMMARY section
        summary_match = re.search(
            r"##\s*SUMMARY\s*\n(.*?)(?=##\s*(?:BLOCKERS|SUGGESTIONS)|DECISION:|$)",
            search_text,
            re.IGNORECASE | re.DOTALL,
        )
        if summary_match:
            result["summary"] = summary_match.group(1).strip()

        # Pattern for ## BLOCKERS section
        blockers_match = re.search(
            r"##\s*BLOCKERS\s*\n(.*?)(?=##\s*(?:SUMMARY|SUGGESTIONS)|DECISION:|$)",
            search_text,
            re.IGNORECASE | re.DOTALL,
        )
        if blockers_match:
            result["blockers"] = blockers_match.group(1).strip()

        # Pattern for ## SUGGESTIONS section
        suggestions_match = re.search(
            r"##\s*SUGGESTIONS\s*\n(.*?)(?=##\s*(?:SUMMARY|BLOCKERS)|DECISION:|$)",
            search_text,
            re.IGNORECASE | re.DOTALL,
        )
        if suggestions_match:
            result["suggestions"] = suggestions_match.group(1).strip()

        return result

    def _normalize_feedback(self, stdout: str, decision: ReviewDecision) -> str:
        """Normalize Manager review feedback into a legible summary.

        Before: feedback field contained raw stdout or unstructured text.
        During: WT-2026-204: first extracts text from NDJSON streaming lines
                via ``_extract_json_stream_text()``, then applies normalization
                on the extracted plain text. Falls back to raw stdout if no
                NDJSON text is found.
                Extracts structured sections (SUMMARY, BLOCKERS, SUGGESTIONS)
                for CHANGES, or uses the full text for APPROVE/INSPECT,
                cleaning ANSI codes.
        After: Returns normalized, legible feedback string for canonical
               persistence. Never returns raw NDJSON as feedback.
        """
        # Clean ANSI codes
        ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
        clean_stdout = ansi_pattern.sub("", stdout)

        # WT-2026-204: Extract text from NDJSON streaming lines first
        parsed_text = self._extract_json_stream_text(clean_stdout)
        normalized_source = parsed_text if parsed_text is not None else clean_stdout

        if decision == ReviewDecision.CHANGES:
            structured = self._parse_changes_structure(normalized_source)
            parts = []
            if structured.get("summary"):
                parts.append(f"## SUMMARY\n{structured['summary']}")
            if structured.get("blockers"):
                parts.append(f"## BLOCKERS\n{structured['blockers']}")
            if structured.get("suggestions"):
                parts.append(f"## SUGGESTIONS\n{structured['suggestions']}")
            if parts:
                return "\n\n".join(parts)
            # Fallback: return normalized source if no structured sections found
            return normalized_source.strip()
        elif decision == ReviewDecision.APPROVE:
            # Extract the text before DECISION: APPROVE for a cleaner summary
            approve_match = re.search(
                r"(.*?)DECISION:\s*APPROVE",
                normalized_source,
                re.IGNORECASE | re.DOTALL,
            )
            if approve_match:
                return approve_match.group(1).strip()
            return normalized_source.strip()
        elif decision == ReviewDecision.INSPECT:
            # Extract text before DECISION: INSPECT or return cleaned stdout
            inspect_match = re.search(
                r"(.*?)DECISION:\s*INSPECT",
                normalized_source,
                re.IGNORECASE | re.DOTALL,
            )
            if inspect_match:
                return inspect_match.group(1).strip()
            return normalized_source.strip()
        else:
            # TRANSPORT_FAILED, UNKNOWN, etc.
            return normalized_source.strip()

    def _validate_changes_structure(self, stdout: str) -> tuple[bool, list[str]]:
        """Validate that CHANGES response has required structure.

        Before: Requires stdout string from Manager review.
        During: Checks for presence of SUMMARY, BLOCKERS, SUGGESTIONS, and DECISION: CHANGES.
        After: Returns (is_valid, missing_sections) tuple.
        """
        missing = []
        stdout_upper = stdout.upper()

        # Require the exact heading form, not a loose word in prose, so a review
        # that merely mentions "summary" cannot pass structure validation.
        if "## SUMMARY" not in stdout_upper:
            missing.append("SUMMARY")
        if "## BLOCKERS" not in stdout_upper:
            missing.append("BLOCKERS")
        if "## SUGGESTIONS" not in stdout_upper:
            missing.append("SUGGESTIONS")
        if "DECISION: CHANGES" not in stdout_upper:
            missing.append("DECISION: CHANGES")

        return len(missing) == 0, missing

    def _generate_human_review_report(
        self,
        ticket_id: str,
        review_attempts: list[dict],
        last_decision: ReviewDecision,
    ) -> Path:
        """Escalation report at 5th rejection. Body: bus/review_report.py."""
        return review_report.generate_human_review_report(
            self.project_root,
            ticket_id,
            review_attempts,
            last_decision,
            adaptive_state=self._load_adaptive_state(ticket_id),
        )

    def _emit_review_attempt(
        self,
        ticket_id: str,
        attempt: int,
        timeout_s: int,
        exit_code: int,
        duration: float,
        stdout: str,
        decision: ReviewDecision | None = None,
        review_log_path: Path | None = None,
        parse_method: str = "",
        transport_ok: bool = True,
        transport_error: str = "",
    ):
        """Emit a lightweight MANAGER_REVIEW_ATTEMPT event.

        Before: Requires attempt metadata and optional decision/review_log_path.
        During: Emits event with only review_log_path + a short stdout_tail.
        After: Event is recorded in bus; full review content (stdout, stderr,
            parsed blockers) is persisted separately in attempt-N.md, not the bus.

        WP-2026-118: Fail-safe added - if emit() fails, log audibly and continue
        without crashing the review cycle.
        """
        try:
            # WP-2026-106 B2: lightweight payload only. Full stdout/stderr and
            # parsed blockers live in attempt-N.md; the bus keeps a pointer
            # (review_log_path) plus a short stdout_tail for quick forensics.
            payload = {
                "attempt": attempt,
                "timeout_seconds": timeout_s,
                "exit_code": exit_code,
                "duration_seconds": round(duration, 2),
                "stdout_tail": (stdout or "")[-500:],
                "transport_ok": transport_ok,
            }
            if decision:
                payload["decision"] = decision.value
            if review_log_path:
                payload["review_log_path"] = str(review_log_path)
            if parse_method:
                payload["parse_method"] = parse_method
            if transport_error:
                payload["transport_error"] = transport_error

            self.event_bus.emit(
                "MANAGER_REVIEW_ATTEMPT",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload=payload,
            )
        except Exception as exc:
            # WP-2026-118: Fail-safe - log the error audibly but don't crash
            print(
                f"[manager-review-bridge] FAIL-SAFE: event_bus.emit() failed for "
                f"ticket {ticket_id}, attempt {attempt}: {type(exc).__name__}: {exc}. "
                f"Review cycle continues; check attempt-{attempt}.md for full content.",
                file=sys.stderr,
            )

    def _count_prior_changes_from_bus(self, ticket_id: str) -> int:
        """Count consecutive trailing CHANGES decisions for a ticket from the bus.

        Thin wrapper over bus.utils.count_trailing_changes (the single source
        of truth for this logic). Returns 0 if the bus is unreadable.
        """
        try:
            events = self.event_bus.read_events(
                ticket_id=ticket_id, event_type="REVIEW_DECISION"
            )
        except Exception:
            return 0
        return count_trailing_changes(events)

    def _parse_opencode_json_decision(self, stdout: str) -> tuple[ReviewDecision, str]:
        """Delegate to bus.decision_parser.parse_opencode_json_decision (WT-2026-255a)."""
        return parse_opencode_json_decision(stdout)

    def _extract_decision_from_text_events(
        self, stdout: str, require_final_answer: bool
    ) -> ReviewDecision | None:
        """Delegate to bus.decision_parser.extract_decision_from_text_events (WT-2026-255a)."""
        return extract_decision_from_text_events(stdout, require_final_answer)

    @staticmethod
    def _resolve_event_phase(event: dict) -> str:
        """Delegate to bus.decision_parser.resolve_event_phase (WT-2026-255a)."""
        return resolve_event_phase(event)

    def _extract_decision_from_single_line(
        self, line: str, require_final_answer: bool
    ) -> ReviewDecision | None:
        """Delegate to bus.decision_parser.extract_decision_from_single_line (WT-2026-255a)."""
        return extract_decision_from_single_line(line, require_final_answer)

    def _parse_opencode_decision_with_retry(
        self, stdout: str, stderr: str, max_retries: int = 2
    ) -> tuple[ReviewDecision, int, str]:
        """Delegate to bus.decision_parser.parse_opencode_decision_with_retry (WT-2026-255a)."""
        return parse_opencode_decision_with_retry(stdout, stderr, max_retries)

    def _parse_opencode_decision(self, stdout: str) -> tuple[ReviewDecision, str]:
        """Delegate to bus.decision_parser.parse_opencode_decision (WT-2026-255a)."""
        return parse_opencode_decision(stdout)

    def run_manager_review_cycle(  # noqa: C901
        self,
        *,
        ticket_id: str,
        supervisor,
        manager_executable: Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ReviewResult:
        """Run manager review cycle with structured CHANGES validation and HUMAN_GATE escalation.

        Before: Simple review loop with max_attempts retry, no structure validation.
        During: Persists each attempt to attempt-N.md, validates CHANGES structure,
                tracks consecutive CHANGES decisions, escalates to HUMAN_GATE at 5th rejection.
        After: Returns ReviewResult; bus contains lightweight review_log_path + stdout_tail;
               human_review_report.md generated if threshold reached.

        WP-2026-118: Fail-safe added - if emit() fails critically, abort cycle with
        auditable error instead of crashing with raw traceback.
        """
        latest_state = self.state_ingest._latest_state(ticket_id)
        supervisor_closed_event = self.event_bus.latest_event(
            ticket_id=ticket_id, event_type="SUPERVISOR_CLOSED"
        )
        if supervisor_closed_event is not None:
            if latest_state != "COMPLETED":
                self.event_bus.emit(
                    "STATE_CHANGED",
                    ticket_id=ticket_id,
                    actor="SUPERVISOR",
                    payload={
                        "from_state": latest_state,
                        "to_state": "COMPLETED",
                        "reason": "Reconciled after terminal closeout",
                        "source": "manager-review-guard",
                    },
                )
            return ReviewResult(
                decision=ReviewDecision.INSPECT,
                stdout="",
                stderr=f"Ticket {ticket_id} ya está cerrado (SUPERVISOR_CLOSED).",
                exit_code=1,
                feedback="Review bridge bloqueado: ticket ya tiene SUPERVISOR_CLOSED.",
            )
        if latest_state != "READY_FOR_REVIEW":
            return ReviewResult(
                decision=ReviewDecision.INSPECT,
                stdout="",
                stderr=f"Review requested but ticket state is {latest_state}, expected READY_FOR_REVIEW.",
                exit_code=1,
                feedback="Review bridge blocked due to invalid ticket state.",
            )

        # WP-2026-118: Wrap initial emit in fail-safe
        try:
            latest_event = self.event_bus.latest_event(ticket_id=ticket_id)
            self.event_bus.emit(
                "MANAGER_REVIEWING",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload={
                    "state": latest_state,
                    "active_sequence": (
                        latest_event.sequence_number if latest_event else 0
                    ),
                    "started_at": now_local().isoformat(),
                },
            )
        except Exception as exc:
            # WP-2026-118: Fail-safe - abort cycle cleanly if bus fails at startup
            error_msg = (
                f"[manager-review-bridge] FAIL-SAFE: Cannot emit MANAGER_REVIEWING for "
                f"ticket {ticket_id}: {type(exc).__name__}: {exc}. "
                f"Review cycle aborted to prevent ambiguous state."
            )
            print(error_msg, file=sys.stderr)
            return ReviewResult(
                decision=ReviewDecision.INSPECT,
                stdout="",
                stderr=error_msg,
                exit_code=1,
                feedback="Review bridge aborted due to event_bus failure at startup.",
            )

        cfg = self._load_review_config()
        # Honor agents.json unless a non-default (non-300) timeout is provided
        if timeout_seconds is None or timeout_seconds == 300:
            base_timeout = cfg["timeout_seconds"]
        else:
            base_timeout = timeout_seconds

        max_attempts = cfg["max_attempts"]
        multiplier = cfg["retry_backoff_multiplier"]

        dtype = self.state_ingest._read_deliverable_type()

        # WT-2026-221b: Evidence gate - reject docs-only/collaboration-only
        # or no bus/state activity before building the review prompt.
        # This reproduces the binary barrier that was missing in seq 602/606/617.
        classification = self.classify_review_packet(ticket_id)
        reject_reason = None
        if not classification.get("bus_active"):
            reject_reason = classification.get(
                "reason",
                f"Ticket {ticket_id} has no active bus/state context. "
                "Cannot verify ticket consistency before review.",
            )
        elif classification.get("is_docs_only") or classification.get(
            "is_collaboration_only"
        ):
            reject_reason = classification.get(
                "reason", "No productive evidence found."
            )
        if reject_reason:
            print(
                f"[evidence-gate] REJECTED: {reject_reason}",
                file=sys.stderr,
            )
            self.event_bus.emit(
                "REVIEW_EVIDENCE_BLOCKED",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload={
                    "classification": (
                        "bus_inactive"
                        if not classification.get("bus_active")
                        else (
                            "collaboration_only"
                            if classification.get("is_collaboration_only", False)
                            else "docs_only"
                        )
                    ),
                    "reason": reject_reason,
                    "docs_only_files": classification.get("docs_only_files", []),
                    "has_motor_evidence": classification.get(
                        "has_motor_evidence", False
                    ),
                },
            )
            return ReviewResult(
                decision=ReviewDecision.CHANGES,
                stdout="",
                stderr=reject_reason,
                exit_code=1,
                feedback=reject_reason,
            )

        # WT-2026-196: Load adaptive review state from previous cycle
        adaptive_state = self._load_adaptive_state(ticket_id)
        previous_signatures = adaptive_state.get("blocker_signatures", [])
        diagnostic_mode = bool(adaptive_state.get("diagnostic_mode", False))
        adaptive_context: dict | None = None
        if previous_signatures:
            current_git_head = self._get_current_git_head()
            changed_files = self._compute_changed_files(
                adaptive_state.get("last_git_head")
            )
            adaptive_context = {
                "diagnostic_mode": diagnostic_mode,
                "repeated_blockers": adaptive_state.get("repeated_blockers", []),
                "changed_files_since_previous_review": changed_files,
                "last_feedback": adaptive_state.get("last_feedback", ""),
            }
        prompt = self._build_review_prompt(
            ticket_id, dtype, adaptive_context=adaptive_context
        )

        # Dispatch based on backend assigned to MANAGER role
        backend = self._get_manager_backend()

        final_stdout, final_stderr, final_exit = "", "", 0
        decision = ReviewDecision.INSPECT
        parse_method = ""
        transport_ok = True
        transport_error = ""

        # WP-2026-106 B3: the escalation counter is derived purely from bus
        # history, never a local loop accumulator. It is computed once, after
        # this cycle emits its REVIEW_DECISION, so a bridge restart or an
        # internal retry can neither inflate nor reset it.
        review_attempts_payloads: list[dict] = []
        for attempt in range(1, max_attempts + 1):
            current_timeout = int(base_timeout * (multiplier ** (attempt - 1)))
            start_time = time.time()

            if backend == "opencode":
                # OpenCode route
                stdout, stderr, exit_code = self._run_opencode_review(
                    ticket_id=ticket_id,
                    prompt=prompt,
                    attempt=attempt,
                    manager_executable=manager_executable,
                    timeout_seconds=current_timeout,
                )
                transport_ok, transport_error = self._classify_transport_result(
                    stdout, stderr, exit_code
                )
                if transport_ok:
                    # WT-2026-252a follow-up: structured decision artifact is
                    # the primary channel; transcript parsing is the fallback
                    # and the transcript remains the evidence.
                    artifact = load_decision_artifact(
                        self.project_root / ".agent" / "runtime" / "reviews",
                        ticket_id,
                        not_before=start_time,
                    )
                    if artifact is not None:
                        decision, parse_method = artifact
                        transcript_decision, _, transcript_method = (
                            self._parse_opencode_decision_with_retry(stdout, stderr)
                        )
                        if transcript_decision != decision:
                            print(
                                f"[review-bridge] decision artifact ({decision.value})"
                                f" overrides transcript ({transcript_decision.value}"
                                f" via {transcript_method}) for {ticket_id}",
                                flush=True,
                            )
                    else:
                        # WP-2026-120: parser with controlled retry for transient failures
                        decision, _, parse_method = (
                            self._parse_opencode_decision_with_retry(stdout, stderr)
                        )
                else:
                    decision = ReviewDecision.TRANSPORT_FAILED
                    parse_method = "transport_failed"
            else:
                # Legacy Manager route (or any other non-OpenCode backend)
                if manager_executable is None:
                    raise ValueError(
                        f"manager_executable required for backend '{backend}'"
                    )
                stdout, stderr, exit_code = self._run_legacy_manager_review(
                    ticket_id=ticket_id,
                    manager_executable=manager_executable,
                    timeout_seconds=current_timeout,
                )
                transport_ok, transport_error = self._classify_transport_result(
                    stdout, stderr, exit_code
                )
                if transport_ok:
                    parse_method = "legacy_manager"
                    # Legacy Manager parser
                    if "CHANGES" in stdout.upper():
                        decision = ReviewDecision.CHANGES
                    elif "APPROVE" in stdout.upper() and exit_code == 0:
                        decision = ReviewDecision.APPROVE
                    elif "--uncommitted" in stderr:
                        decision = ReviewDecision.INSPECT
                    else:
                        decision = ReviewDecision.INSPECT
                else:
                    decision = ReviewDecision.TRANSPORT_FAILED
                    parse_method = "transport_failed"

            elapsed = time.time() - start_time

            # Persist review attempt idempotently for all decisions
            review_log_path = self._persist_review_attempt(
                ticket_id,
                attempt,
                stdout,
                stderr,
                decision,
                review_packet_path=self._get_review_packet_path(ticket_id, attempt),
                parse_method=parse_method,
                transport_ok=transport_ok,
                transport_error=transport_error,
            )

            # Parse structured sections for CHANGES
            structured = (
                self._parse_changes_structure(stdout)
                if decision == ReviewDecision.CHANGES
                else {}
            )
            blockers = structured.get("blockers", "")

            # WT-2026-235a: Enforce CHANGES structure and non-empty blockers.
            # If invalid, degrade to INSPECT with failure_reason so no false
            # decision reaches the bus or triggers requeue.
            # Extract text from NDJSON first so validation works on the real
            # content, not raw JSON lines.
            search_text = self._extract_json_stream_text(stdout) or stdout
            structure_valid = True
            missing_sections: list[str] = []
            failure_reason: str = ""
            if decision == ReviewDecision.CHANGES:
                structure_valid, missing_sections = self._validate_changes_structure(
                    search_text
                )
                if not structure_valid:
                    failure_reason = "changes_structure_invalid"
                    print(
                        "[manager-review-bridge] ERROR: CHANGES response missing "
                        f"required sections {missing_sections} -- "
                        "degraded to INSPECT.",
                        file=sys.stderr,
                    )
                    decision = ReviewDecision.INSPECT
                elif not blockers.strip():
                    failure_reason = "changes_structure_invalid"
                    missing_sections = ["BLOCKERS (empty content)"]
                    print(
                        "[manager-review-bridge] ERROR: CHANGES response has "
                        "empty BLOCKERS content -- degraded to INSPECT.",
                        file=sys.stderr,
                    )
                    decision = ReviewDecision.INSPECT

            # WP-2026-106: Emit lightweight event (review_log_path + stdout_tail)
            # WP-2026-118: Already wrapped in fail-safe inside _emit_review_attempt
            self._emit_review_attempt(
                ticket_id=ticket_id,
                attempt=attempt,
                timeout_s=current_timeout,
                exit_code=exit_code,
                duration=elapsed,
                stdout=stdout,
                decision=decision,
                review_log_path=review_log_path,
                parse_method=parse_method,
                transport_ok=transport_ok,
                transport_error=transport_error,
            )

            # Track attempt payload for potential human report (in-memory only)
            review_attempts_payloads.append(
                {
                    "attempt": attempt,
                    "payload": {
                        "attempt": attempt,
                        "timeout_seconds": current_timeout,
                        "exit_code": exit_code,
                        "duration_seconds": round(elapsed, 2),
                        "stdout_tail": (stdout or "")[-500:],
                        "stderr_tail": (stderr or "")[-500:],
                        "decision": decision.value,
                        "parse_method": parse_method,
                        "transport_ok": transport_ok,
                        "transport_error": transport_error,
                        "review_log_path": str(review_log_path)
                        if review_log_path
                        else None,
                        "blockers": blockers,
                        "structure_valid": structure_valid,
                        "missing_sections": missing_sections,
                    },
                }
            )

            final_stdout, final_stderr, final_exit = stdout, stderr, exit_code

            # WP-2026-106: Only break on APPROVE or INSPECT
            # CHANGES continues until threshold reached
            if decision == ReviewDecision.APPROVE:
                break

            if decision == ReviewDecision.TRANSPORT_FAILED:
                # Transport failed before the model could produce a valid review.
                # Do not escalate to HUMAN_GATE; surface the infrastructure error
                # to the bus and stop the cycle so the caller can retry manually.
                break

            if decision == ReviewDecision.INSPECT:
                # Retry only if the failure was technical (TimeoutExpired in stderr)
                # and the parser reached fallback_inspect (no explicit DECISION found).
                if "TimeoutExpired" in stderr and attempt < max_attempts:
                    continue
                # Semantic INSPECT (explicit or fallback without timeout) → break
                break

            if decision == ReviewDecision.UNKNOWN:
                # UNKNOWN is no longer returned by the OpenCode parser (now INSPECT+method),
                # but left as safety net for legacy Codex routes.
                if "TimeoutExpired" in stderr and attempt < max_attempts:
                    continue
                decision = ReviewDecision.INSPECT
                break

            # WP-2026-106 B3: CHANGES ends the cycle. Re-reviewing the same
            # unchanged code in an inner loop is wasted work; the "5 attempts"
            # threshold means 5 Builder<->Manager cycles, counted from the bus.
            if decision == ReviewDecision.CHANGES:
                break

        # WP-2026-144 hotfix: timeout-caused INSPECT is an infrastructure failure,
        # not a semantic human-review request. Reclassify so the bus never sees
        # inspect→HUMAN_GATE for a timeout; REVIEW_TRANSPORT_FAILED carries the
        # failure_reason so callers can distinguish timeout from content inspect.
        if decision == ReviewDecision.INSPECT and "TimeoutExpired" in (
            final_stderr or ""
        ):
            decision = ReviewDecision.TRANSPORT_FAILED
            transport_ok = False
            transport_error = "timeout"

        # WP-2026-106 B1: keep the bus lightweight. Full review text lives in
        # attempt-N.md on disk; the event only carries a short forensic tail.
        # Transport failures are tracked as a separate event so they cannot be
        # mistaken for a human review decision.
        if decision == ReviewDecision.TRANSPORT_FAILED:
            try:
                self.event_bus.emit(
                    "REVIEW_TRANSPORT_FAILED",
                    ticket_id=ticket_id,
                    actor="MANAGER",
                    payload={
                        "stdout_tail": (final_stdout or "")[-500:],
                        "stderr_tail": (final_stderr or "")[-500:],
                        "exit_code": final_exit,
                        "transport_error": transport_error,
                        "parse_method": parse_method,
                        "transport_ok": transport_ok,
                        **(
                            {"failure_reason": transport_error}
                            if transport_error
                            else {}
                        ),
                    },
                )
            except Exception as exc:
                print(
                    f"[manager-review-bridge] FAIL-SAFE: Cannot emit REVIEW_TRANSPORT_FAILED for "
                    f"ticket {ticket_id}: {type(exc).__name__}: {exc}.",
                    file=sys.stderr,
                )
                return ReviewResult(
                    decision=decision,
                    stdout=final_stdout,
                    stderr=f"REVIEW_TRANSPORT_FAILED emit failed: {exc}",
                    exit_code=1,
                    feedback=self._normalize_feedback(final_stdout, decision),
                    transport_ok=False,
                    transport_error=transport_error or str(exc),
                    parse_method=parse_method,
                )
            return ReviewResult(
                decision=decision,
                stdout=final_stdout,
                stderr=final_stderr,
                exit_code=final_exit,
                feedback=self._normalize_feedback(final_stdout, decision),
                transport_ok=False,
                transport_error=transport_error,
                parse_method=parse_method,
            )

        # WT-2026-204: Extract blockers from the last attempt's structured output
        last_blockers = ""
        if decision == ReviewDecision.CHANGES and final_stdout:
            last_structured = self._parse_changes_structure(final_stdout)
            last_blockers = last_structured.get("blockers", "")

        try:
            # WT-2026-235a: Include parse_method in every REVIEW_DECISION;
            # include failure_reason and missing_sections when decision was
            # degraded from CHANGES to INSPECT.
            rd_payload: dict = {
                "decision": decision.value,
                "stdout_tail": (final_stdout or "")[-500:],
                "blockers": last_blockers,
                "parse_method": parse_method,
            }
            if failure_reason:
                rd_payload["failure_reason"] = failure_reason
            if missing_sections:
                rd_payload["missing_sections"] = missing_sections
            self.event_bus.emit(
                "REVIEW_DECISION",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload=rd_payload,
            )
        except Exception as exc:
            # WP-2026-118: Fail-safe - log the error but don't crash
            print(
                f"[manager-review-bridge] FAIL-SAFE: Cannot emit REVIEW_DECISION for "
                f"ticket {ticket_id}: {type(exc).__name__}: {exc}. "
                f"Decision was {decision.value}; transition may need manual review.",
                file=sys.stderr,
            )
            # Return early to avoid ambiguous state transition
            return ReviewResult(
                decision=decision,
                stdout=final_stdout,
                stderr=f"REVIEW_DECISION emit failed: {exc}",
                exit_code=1,
                feedback=self._normalize_feedback(final_stdout, decision),
                parse_method=parse_method,
            )

        # WT-2026-189: Capture review_decision_seq immediately after emitting REVIEW_DECISION
        review_decision_seq = max(
            (
                event.sequence_number
                for event in self.event_bus.read_events(ticket_id=ticket_id)
                if event.event_type == "REVIEW_DECISION"
            ),
            default=0,
        )

        if decision == ReviewDecision.APPROVE:
            supervisor.transition_ticket(
                ticket_id=ticket_id,
                new_state="READY_TO_CLOSE",
                reason="Manager approved",
            )
        elif decision == ReviewDecision.CHANGES:
            # WP-2026-106 B3: a single escalation authority. agent_controller
            # --request-changes counts CHANGES from the bus and transitions to
            # IN_PROGRESS or HUMAN_GATE on the shared threshold. The bridge no
            # longer keeps a parallel local counter.
            # WP-2026-176: Resolve controller from external motor if workspace
            # carries motor_destination_link.json; pass --project-root accordingly.
            motor_controller = self._resolve_motor_controller()
            if motor_controller is not None:
                changes_cmd = [
                    sys.executable,
                    str(motor_controller),
                    "--request-changes",
                    ticket_id,
                    "--project-root",
                    str(self.project_root),
                ]
            else:
                changes_cmd = [
                    sys.executable,
                    str(self.project_root / ".agent" / "agent_controller.py"),
                    "--request-changes",
                    ticket_id,
                ]
            rc_result = subprocess.run(
                changes_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                env=self._review_env(),
                timeout=base_timeout,
            )
            if rc_result.returncode != 0:
                print(
                    f"[manager-review-bridge] --request-changes failed (rc={rc_result.returncode}): "
                    f"{rc_result.stderr.strip() or rc_result.stdout.strip()}",
                    file=sys.stderr,
                )
            # Recompute from the bus (now includes this cycle's REVIEW_DECISION).
            consecutive_changes_count = self._count_prior_changes_from_bus(ticket_id)
            if consecutive_changes_count < max_attempts:
                self._ensure_durable_changes_consumer(
                    supervisor=supervisor,
                    ticket_id=ticket_id,
                    review_decision_seq=review_decision_seq,
                )
            if consecutive_changes_count >= max_attempts:
                report_path = self._generate_human_review_report(
                    ticket_id=ticket_id,
                    review_attempts=review_attempts_payloads,
                    last_decision=decision,
                )
                print(
                    f"[manager-review-bridge] HUMAN_GATE: report at {report_path}",
                    file=sys.stderr,
                )

        elif decision == ReviewDecision.INSPECT:
            # WP-2026-124: inspect now triggers the canonical materialization route
            # via CLI, same as changes. This ensures STATE_CHANGED is emitted.
            # WP-2026-176: Resolve controller from external motor if workspace
            # carries motor_destination_link.json; pass --project-root accordingly.
            motor_controller = self._resolve_motor_controller()
            if motor_controller is not None:
                escalate_cmd = [
                    sys.executable,
                    str(motor_controller),
                    "--escalate-human-gate",
                    "--ticket",
                    ticket_id,
                    "--project-root",
                    str(self.project_root),
                ]
            else:
                escalate_cmd = [
                    sys.executable,
                    str(self.project_root / ".agent" / "agent_controller.py"),
                    "--escalate-human-gate",
                    "--ticket",
                    ticket_id,
                ]
            subprocess.run(
                escalate_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                env=self._review_env(),
                timeout=base_timeout,
            )

        if (
            decision == ReviewDecision.INSPECT
            and final_stderr.strip()
            and "TimeoutExpired" not in final_stderr
        ):
            print(
                f"[manager-review-bridge] WARNING: INSPECT fallback due to stderr: {final_stderr.strip()}",
                file=sys.stderr,
            )

        # WT-2026-196: Save adaptive review state for all decisions
        # so the next cycle can detect repeated blockers.
        try:
            current_blocker_sigs = sorted(
                extract_signatures_from_feedback(final_stdout)
            )
            current_git_head = self._get_current_git_head()
            prev_sigs = (
                adaptive_state.get("blocker_signatures", []) if adaptive_state else []
            )
            repeated, should_diag = self._compute_repeated_blockers(
                prev_sigs, final_stdout
            )
            changed_files = self._compute_changed_files(
                adaptive_state.get("last_git_head") if adaptive_state else None
            )
            normalized = self._normalize_feedback(final_stdout, decision)
            adaptive_update: dict = {
                "last_review_sequence": review_decision_seq,
                "last_git_head": current_git_head,
                "blocker_signatures": current_blocker_sigs,
                "repeated_blockers": repeated,
                "diagnostic_mode": should_diag,
                "changed_files_since_previous_review": changed_files,
                "last_feedback": normalized,
            }
            self._save_adaptive_state(ticket_id, adaptive_update)
        except Exception as exc:
            print(
                f"[manager-review-bridge] WARNING: Failed to save adaptive state: {exc}",
                file=sys.stderr,
            )

        # Normalize feedback from structured sections before returning
        normalized_feedback = self._normalize_feedback(final_stdout, decision)

        return ReviewResult(
            decision=decision,
            stdout=final_stdout,
            stderr=final_stderr,
            exit_code=final_exit,
            feedback=normalized_feedback,
            transport_ok=transport_ok,
            transport_error=transport_error,
            parse_method=parse_method,
        )
