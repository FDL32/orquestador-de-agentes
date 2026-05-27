# ruff: noqa: S603
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .event_bus import EventBus
from .skill_resolver import SkillResolver, create_resolver
from .time_utils import now_local
from .utils import count_trailing_changes


# Windows CreateProcess argv limit ~8191 chars; leave margin for other args
ARGV_PROMPT_THRESHOLD = 8000
MAX_RUBRIC_OBSERVATIONS = 5
MAX_OBSERVATION_SIGNAL_CHARS = 200


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    CHANGES = "changes"
    INSPECT = "inspect"
    UNKNOWN = "unknown"
    TRANSPORT_FAILED = "transport_failed"


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
        match = re.search(r"\*\*ID:\*\*\s*(WP-\d{4}-\d+)", content)
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
        self._supports_json_format = self._detect_json_format_support()
        self._canonical_anti_patterns = self._load_canonical_anti_patterns()

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

    @staticmethod
    def _looks_like_opencode_help(stdout: str, stderr: str) -> bool:
        """Detect an OpenCode help banner instead of model output.

        Guards: if stdout contains real NDJSON events (step_start / step_finish)
        it is genuine model output — the marker strings may appear inside source
        code the model read, not as an actual help banner. Only inspect stderr
        in that case, since OpenCode writes its CLI help to stderr.
        """
        ndjson_signatures = ('"type":"step_finish"', '"type":"step_start"')
        stdout_has_ndjson = any(sig in stdout for sig in ndjson_signatures)
        candidate = (
            stderr.lower() if stdout_has_ndjson else f"{stdout}\n{stderr}".lower()
        )
        markers = (
            "opencode run [message..]",
            "run opencode with a message",
            "show help",
        )
        return any(marker in candidate for marker in markers)

    def _classify_transport_result(
        self, stdout: str, stderr: str, exit_code: int
    ) -> tuple[bool, str]:
        """Classify whether the OpenCode invocation reached the model."""
        if "TimeoutExpired" in stderr:
            return True, "timeout_retryable"
        if exit_code != 0:
            return False, f"exit_code={exit_code}"
        if self._looks_like_opencode_help(stdout, stderr):
            return False, "help_output_detected"
        return True, ""

    def _detect_json_format_support(self) -> bool:
        try:
            executable = "opencode"
            if os.name == "nt":
                executable = "opencode.cmd"
            exe_full = shutil.which(executable) or executable
            detect_args = [exe_full, "run", "--help"]
            use_detect_shell = os.name == "nt"
            result = subprocess.run(
                subprocess.list2cmdline(detect_args)
                if use_detect_shell
                else detect_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                shell=use_detect_shell,
            )
            return "--format" in (result.stdout + result.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _review_env(self) -> dict[str, str]:
        """Return an environment dict for the review subprocess.

        OpenCode on Windows calls mkdir without the recursive flag when
        initialising its config directory. If the directory already exists
        from a prior session the process exits immediately with EEXIST.
        The fix: redirect HOME / USERPROFILE / XDG vars to a fresh per-run
        scratch directory so OpenCode always starts from a clean slate.

        Auth is preserved by copying auth.json from the real home before the
        redirect, so credentials survive the isolation.
        """
        env = os.environ.copy()

        scratch_root = self.project_root / ".agent" / "runtime" / "tmp"
        scratch_root.mkdir(parents=True, exist_ok=True)
        review_home = Path(
            tempfile.mkdtemp(prefix="manager_review_home_", dir=str(scratch_root))
        )

        # Locate and copy auth credentials before redirecting home vars.
        real_home = os.path.expanduser(
            os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~"
        )
        for auth_parts in (
            (".local", "share", "opencode", "auth.json"),
            (".config", "opencode", "auth.json"),
        ):
            auth_src = os.path.join(real_home, *auth_parts)
            if os.path.exists(auth_src):
                auth_dst = os.path.join(str(review_home), *auth_parts)
                os.makedirs(os.path.dirname(auth_dst), exist_ok=True)
                shutil.copy2(auth_src, auth_dst)
                break

        for key in ("HOME", "USERPROFILE", "CODEX_HOME"):
            if key in env:
                env[key] = str(review_home)
        review_home_str = str(review_home)
        env["XDG_CONFIG_HOME"] = os.path.join(review_home_str, ".config")
        env["XDG_DATA_HOME"] = os.path.join(review_home_str, ".local", "share")
        return env

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

    # Known namespaces that OpenCode CLI accepts verbatim (provider/model format).
    _OPENCODE_VALID_PREFIXES = ("opencode-go/", "opencode/", "github-copilot/")

    @staticmethod
    def _normalize_opencode_model(model: str | None) -> str | None:
        """Normalize a role model to the identifier accepted by OpenCode.

        Valid OpenCode model IDs use the ``opencode-go/<model>``,
        ``opencode/<model>`` or ``github-copilot/<model>`` namespaces and are
        passed through unchanged.
        ``openai/<model>`` is mapped to ``github-copilot/<model>`` because this
        OpenCode installation exposes the OpenAI-backed catalog via the
        GitHub Copilot namespace.
        """
        if model is None:
            return None
        normalized = model.strip()
        if not normalized:
            return None
        for prefix in ReviewBridge._OPENCODE_VALID_PREFIXES:
            if normalized.startswith(prefix):
                return normalized
        if normalized.startswith("openai/"):
            bare = normalized.split("/", 1)[1].strip()
            if bare:
                mapped = f"github-copilot/{bare}"
                print(
                    f"[review_bridge] WARNING: model '{normalized}' mapped to '{mapped}'.",
                    flush=True,
                )
                return mapped
            return None
        # Unknown provider prefix — keep the bare model name as a last resort
        # so the caller can still try a direct catalog lookup.
        if "/" in normalized:
            provider, bare = normalized.split("/", 1)
            print(
                f"[review_bridge] WARNING: model '{normalized}' uses unknown provider"
                f" '{provider}'. Falling back to bare model '{bare}'.",
                flush=True,
            )
            normalized = bare.strip()
        return normalized or None

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

    def _get_active_ticket_id(self) -> str | None:
        """Read active ticket ID from work_plan.md."""
        work_plan = self.project_root / ".agent" / "collaboration" / "work_plan.md"
        if not work_plan.exists():
            return None
        content = work_plan.read_text(encoding="utf-8")
        # Look for **- ID:** WP-XXXX-XXX pattern
        match = re.search(r"\*\*ID:\*\*\s*(WP-\d{4}-\d+)", content)
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
        pattern = rf"### {re.escape(ticket_id)}.*?(?=\n### WP-|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return (
            match.group(0)
            if match
            else f"[execution_log section for {ticket_id} not found]"
        )

    def _git_diff_stat(self) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            result = subprocess.run(
                [git_bin, "diff", "--stat", "origin/main...HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout or "[git diff --stat empty]"
            result = subprocess.run(
                [git_bin, "diff", "--stat", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=10,
            )
            return "[WARNING: origin/main not reachable, using HEAD fallback]\n" + (
                result.stdout or "[git diff --stat empty]"
            )
        except Exception as e:
            return f"[Error fetching git diff --stat: {e}]"

    def _build_diff_for_files_likely_touched(
        self, ticket_id: str, budget_bytes: int
    ) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            result = subprocess.run(
                [git_bin, "diff", "origin/main...HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=15,
            )
            warning_prefix = ""
            if result.returncode != 0:
                result = subprocess.run(
                    [git_bin, "diff", "HEAD"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=self.project_root,
                    timeout=15,
                )
                warning_prefix = "[WARNING: origin/main not reachable, using git diff HEAD fallback]\n"
            diff = warning_prefix + (result.stdout or "")
            diff_bytes = diff.encode("utf-8")
            if len(diff_bytes) <= budget_bytes:
                return diff
            truncated = diff_bytes[:budget_bytes].decode("utf-8", errors="ignore")
            return truncated + "\n\n[diff truncado por budget]"
        except Exception as e:
            return f"[Error fetching git diff: {e}]"

    def _git_provenance(self) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            result = subprocess.run(
                [
                    git_bin,
                    "log",
                    "origin/main..HEAD",
                    "--format=%H %ai %an",
                    "--no-merges",
                    "-1",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip() or "[no new commits since origin/main]"
            # Remote genuinely unreachable — fall back to latest HEAD commit
            result = subprocess.run(
                [git_bin, "log", "HEAD", "--format=%H %ai %an", "--no-merges", "-1"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=10,
            )
            line = result.stdout.strip() or "[no commits found]"
            return f"[WARNING: origin/main not reachable] {line}"
        except Exception as e:
            return f"[Error fetching git provenance: {e}]"

    def _observations_path(self) -> Path:
        return (
            self.project_root / ".agent" / "runtime" / "memory" / "observations.jsonl"
        )

    def _canonical_anti_patterns_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "_shared"
            / "anti-patterns.md"
        )

    @staticmethod
    def _parse_canonical_anti_patterns(content: str) -> list[tuple[str, str]]:
        inventory: list[tuple[str, str]] = []
        pattern = re.compile(r"^##\s+(AP-\d{2})\s*-\s*(.+?)\s*$")
        for raw_line in content.splitlines():
            match = pattern.match(raw_line.strip())
            if not match:
                continue
            inventory.append((match.group(1), match.group(2).strip()))
        return inventory

    def _load_canonical_anti_patterns(self) -> list[tuple[str, str]]:
        path = self._canonical_anti_patterns_path()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.warn(
                f"Canonical anti-pattern inventory unavailable at {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return []

        inventory = self._parse_canonical_anti_patterns(content)
        if not inventory:
            warnings.warn(
                f"Canonical anti-pattern inventory at {path} is empty or invalid.",
                RuntimeWarning,
                stacklevel=2,
            )
        return inventory

    def _render_canonical_anti_pattern_inventory(self) -> str:
        if not self._canonical_anti_patterns:
            return ""
        lines = [
            "Canonical anti-pattern inventory (from skills/_shared/anti-patterns.md):"
        ]
        for ap_id, ap_name in self._canonical_anti_patterns:
            lines.append(f"- {ap_id} {ap_name}")
        return "\n".join(lines)

    @staticmethod
    def _parse_observation_timestamp(raw_timestamp: object) -> datetime:
        if isinstance(raw_timestamp, str):
            stamp = raw_timestamp.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(stamp)
                return (
                    parsed
                    if parsed.tzinfo is not None
                    else parsed.replace(tzinfo=timezone.utc)
                )
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _truncate_observation_signal(signal: object) -> str:
        text = str(signal or "").strip()
        if len(text) <= MAX_OBSERVATION_SIGNAL_CHARS:
            return text
        return text[: MAX_OBSERVATION_SIGNAL_CHARS - 3].rstrip() + "..."

    @staticmethod
    def _observation_matches_dtype(record: dict, dtype: str) -> bool:
        """Return True if the observation applies to the given deliverable_type."""
        applies_to = record.get("applies_to")
        if applies_to is None or applies_to == "all":
            return True
        targets = applies_to if isinstance(applies_to, list) else [applies_to]
        return dtype in targets or "all" in targets

    def _load_manager_review_observations(
        self, dtype: str = "all"
    ) -> list[tuple[datetime, str, str]]:
        """Load manager-review-rubric observations filtered by deliverable_type scope.

        Absent applies_to = all types (legacy compat). "all" = all types.
        List or string value = include only when dtype matches.
        """
        path = self._observations_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []

        observations: list[tuple[datetime, str, str]] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("topic") != "manager-review-rubric":
                continue
            if not self._observation_matches_dtype(record, dtype):
                continue
            signal = self._truncate_observation_signal(record.get("signal", ""))
            if not signal:
                continue
            timestamp = self._parse_observation_timestamp(record.get("timestamp"))
            source_ticket = str(record.get("source_ticket", "")).strip() or "unknown"
            observations.append((timestamp, signal, source_ticket))

        observations.sort(key=lambda item: item[0], reverse=True)
        return observations[:MAX_RUBRIC_OBSERVATIONS]

    def _render_manager_review_learnings(self, dtype: str = "all") -> str:
        observations = self._load_manager_review_observations(dtype=dtype)
        if not observations:
            return ""

        lines = ["Lecciones acumuladas de auditoria (de revisiones anteriores):"]
        for timestamp, signal, source_ticket in observations:
            date = timestamp.astimezone(timezone.utc).date().isoformat()
            lines.append(f"- [{date}] {signal} ({source_ticket})")
        return "\n".join(lines)

    def _rubric_for_type(self, dtype: str, ticket_id: str) -> str:
        scaffolding_precheck = (
            "AP-07 Scaffolding misclassified as code precheck: if the majority of Files Likely Touched are "
            "structural non-Python artifacts (references/, .gitkeep, empty dirs, placeholders, "
            "config stubs) with no logic — even if one small support file is included — "
            "the correct deliverable_type is 'documentation', not 'code'. "
            "Flag 'code' classification for majority-scaffolding tickets as a planning error "
            "(SUGGESTIONS, not BLOCKER)."
        )
        canonical_anti_patterns = self._render_canonical_anti_pattern_inventory()
        canonical_anti_patterns_block = (
            f"{canonical_anti_patterns}\n\n" if canonical_anti_patterns else ""
        )
        if dtype == "code":
            return (
                f"Review code ticket {ticket_id}. "
                f"Verify the implementation correctness, testing coverage, and style guides. "
                f"Check acceptance criteria and Files Likely Touched.\n\n"
                f"{scaffolding_precheck}\n\n"
                f"{canonical_anti_patterns_block}"
                f"Test anti-patterns — flag as BLOCKERS if found:\n"
                f"- AP-01 Mock drift: each patch/mock must target the actual API the code calls "
                f"(e.g. patching pathlib.Path.open is inert if the code uses the built-in open()).\n"
                f"- AP-02 Floor assertion: each numeric threshold must exceed the base value that exists "
                f"without the tested feature (e.g. assert score >= 150 is trivially true if "
                f"the base recency score alone is ~20_000_000).\n\n"
                f"Implementation anti-patterns — flag as BLOCKERS if found:\n"
                f"- AP-03 Zero-logic wrapper: a function whose entire body is a single 1:1 delegate "
                f"call with no own logic must be inlined or eliminated.\n"
                f"- AP-04 Exclusive resource acquisition without reentrancy guard: if the diff introduces "
                f"exclusive resource acquisition (O_CREAT|O_EXCL, flock, Lock.acquire(), lock-file "
                f"creation) inside a method that can be reached from more than one call site or "
                f"called twice on the same instance (e.g. standalone + inside a wrapper), verify "
                f"that an explicit instance-level reentrancy guard exists. Without it: BLOCKER.\n"
                f"- AP-05 Boolean truthiness regression in changed return contracts: if the diff changes "
                f"a method's return type from implicit None to explicit bool, verify that every "
                f"caller uses `is False` / `is True` rather than generic truthiness (`if not x`, "
                f"`if x`, `while x`). Mixing None, False, and True under a falsy guard silently "
                f"breaks when the method is monkeypatched or called from a legacy path. "
                f"Any caller still using generic truthiness after the return-type change: BLOCKER."
            )
        elif dtype == "mixed":
            return (
                f"Review mixed ticket {ticket_id}. "
                f"Verify code correctness, tests, and style guides, and additionally verify "
                f"that all declared non-code deliverables exist, are well-structured, and are fully complete. "
                f"Check acceptance criteria and Files Likely Touched.\n\n"
                f"{scaffolding_precheck}\n\n"
                f"{canonical_anti_patterns_block}"
                f"Test anti-patterns — flag as BLOCKERS if found:\n"
                f"- AP-01 Mock drift: each patch/mock must target the actual API the code calls.\n"
                f"- AP-02 Floor assertion: each numeric threshold must exceed the base value that "
                f"exists without the tested feature.\n\n"
                f"Implementation anti-patterns — flag as BLOCKERS if found:\n"
                f"- AP-03 Zero-logic wrapper: a function whose entire body is a single 1:1 delegate "
                f"call with no own logic must be inlined or eliminated.\n"
                f"- AP-04 Exclusive resource acquisition without reentrancy guard: if the diff introduces "
                f"exclusive resource acquisition (O_CREAT|O_EXCL, flock, Lock.acquire(), lock-file "
                f"creation) inside a method that can be reached from more than one call site or "
                f"called twice on the same instance, verify that an explicit reentrancy guard exists. "
                f"Without it: BLOCKER.\n"
                f"- AP-05 Boolean truthiness regression in changed return contracts: if the diff changes "
                f"a method's return type from implicit None to explicit bool, verify all callers use "
                f"`is False` / `is True` rather than generic truthiness (`if not x`, `if x`). "
                f"Any caller still using generic truthiness after the change: BLOCKER."
            )
        else:  # documentation, research, analysis
            return (
                f"Review non-code {dtype} ticket {ticket_id}. "
                f"Since this is a non-code deliverable, focus strictly on the clarity, depth, correctness, "
                f"structure, and completeness of the requested document deliverables. "
                f"Check acceptance criteria and Files Likely Touched."
            )

    def _build_review_prompt(self, ticket_id: str, dtype: str) -> str:
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

        # Compose
        parts = [self._rubric_for_type(dtype, ticket_id)]

        # Cross-cutting: validator evidence gate (all types)
        parts.append(
            "\n--- Cross-cutting check (all ticket types) ---\n"
            "AP-06 Validator evidence missing: if the work_plan declares an explicit validator as a "
            "quality gate (e.g. skills/validate_all.py, agent_controller --validate, ruff, pytest), "
            "execution_log.md must contain: (1) the exact command executed, (2) the result, and "
            "(3) a numeric outcome where applicable (e.g. '0 invalid skills', '253 passed', "
            "'All checks passed'). Declared validator + absent or ambiguous evidence: BLOCKER."
        )

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
        if os.name == "nt" and exe_str.lower().endswith(".ps1"):
            cmd_candidate = Path(exe_str).with_suffix(".cmd")
            bat_candidate = Path(exe_str).with_suffix(".bat")
            if cmd_candidate.exists():
                exe_str = str(cmd_candidate)
            elif bat_candidate.exists():
                exe_str = str(bat_candidate)

        command = [exe_str, "review", ticket_id]
        if os.name == "nt" and exe_str.lower().endswith(".ps1"):
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
        if os.name == "nt" and executable == "opencode":
            executable = "opencode.cmd"

        exe_full = shutil.which(executable) or executable
        if os.name == "nt" and exe_full.lower().endswith(".ps1"):
            cmd_candidate = Path(exe_full).with_suffix(".cmd")
            bat_candidate = Path(exe_full).with_suffix(".bat")
            if cmd_candidate.exists():
                exe_full = str(cmd_candidate)
            elif bat_candidate.exists():
                exe_full = str(bat_candidate)

        # Review packet: el contexto completo del review se escribe a un
        # archivo dentro del repo; el Manager lo lee con sus herramientas.
        # El prompt posicional es corto (sin metacaracteres de cmd.exe).
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

        cmd_args = [exe_full, "run", "--agent", "manager"]
        if model:
            cmd_args.extend(["--model", model])
        if self._supports_json_format:
            cmd_args.extend(["--format", "json"])
        cmd_args.append(review_message)

        use_shell = False
        if os.name == "nt" and (
            exe_full.lower().endswith(".cmd")
            or exe_full.lower().endswith(".bat")
            or "opencode" in exe_full.lower()
        ):
            use_shell = True

        if os.name == "nt" and exe_full.lower().endswith(".ps1"):
            cmd_args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                *cmd_args,
            ]

        try:
            # En Windows, shell=True con una lista hace que cmd.exe trate
            # args[1:] como argumentos del propio shell: opencode arrancaria
            # sin ninguno. list2cmdline produce el string correcto.
            run_args = subprocess.list2cmdline(cmd_args) if use_shell else cmd_args
            result = subprocess.run(
                run_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                env=self._review_env(),
                timeout=timeout_seconds,
                shell=use_shell,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, subprocess.TimeoutExpired):
                err_msg = f"TimeoutExpired: {exc}"
            return "", err_msg, 1

        return result.stdout or "", result.stderr or "", result.returncode

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

    def _get_review_log_path(self, ticket_id: str) -> Path:
        """Get the review log directory for a ticket.

        Before: Requires ticket_id string.
        During: Creates directory structure under .agent/runtime/reviews/<TICKET_ID>/.
        After: Returns Path object for the ticket's review log directory.
        """
        reviews_dir = self.project_root / ".agent" / "runtime" / "reviews"
        ticket_dir = reviews_dir / ticket_id
        ticket_dir.mkdir(parents=True, exist_ok=True)
        return ticket_dir

    def _get_review_packet_path(self, ticket_id: str, attempt: int) -> Path:
        """Get the canonical review packet path for a ticket attempt."""
        packets_dir = self.project_root / ".agent" / "runtime" / "review_packets"
        packets_dir.mkdir(parents=True, exist_ok=True)
        return packets_dir / f"{ticket_id}_attempt-{attempt}.md"

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
        """Persist a review attempt to attempt-N.md idempotently.

        Before: Requires ticket_id, attempt number, stdout, stderr, and decision.
        During: Writes review content to .agent/runtime/reviews/<TICKET_ID>/attempt-N.md,
                overwriting any existing file with the same attempt number.
        After: Returns the Path to the persisted review file.
        """
        ticket_dir = self._get_review_log_path(ticket_id)
        attempt_file = ticket_dir / f"attempt-{attempt}.md"

        # Build structured review content
        content_parts = [
            f"# Review Attempt {attempt}",
            "",
            f"## Ticket: {ticket_id}",
            f"## Decision: {decision.value.upper()}",
            f"## Parse Method: {parse_method or 'unknown'}",
            f"## Transport OK: {transport_ok}",
            "",
            "## Review Packet",
            "",
            str(review_packet_path.relative_to(self.project_root).as_posix())
            if review_packet_path is not None
            else "[not recorded]",
            "",
            "## Transport Error",
            "",
            transport_error or "[none]",
            "",
            "## STDOUT",
            "",
            stdout or "[empty]",
            "",
            "## STDERR",
            "",
            stderr or "[empty]",
            "",
        ]

        # Parse and add structured sections for CHANGES decisions
        if decision == ReviewDecision.CHANGES:
            structured = self._parse_changes_structure(stdout)
            content_parts.extend(
                [
                    "",
                    "## SUMMARY",
                    "",
                    structured.get("summary", "[no summary provided]"),
                    "",
                    "## BLOCKERS",
                    "",
                    structured.get("blockers", "[no blockers provided]"),
                    "",
                    "## SUGGESTIONS",
                    "",
                    structured.get("suggestions", "[no suggestions provided]"),
                    "",
                ]
            )

        attempt_file.write_text("\n".join(content_parts), encoding="utf-8")
        return attempt_file

    def _parse_changes_structure(self, stdout: str) -> dict[str, str]:
        """Parse structured sections from CHANGES review output.

        Before: Requires stdout string from Manager review.
        During: Extracts SUMMARY, BLOCKERS, SUGGESTIONS sections using regex patterns.
        After: Returns dict with 'summary', 'blockers', 'suggestions' keys (defaults if not found).
        """
        result = {"summary": "", "blockers": "", "suggestions": ""}

        # Pattern for ## SUMMARY section
        summary_match = re.search(
            r"##\s*SUMMARY\s*\n(.*?)(?=##\s*(?:BLOCKERS|SUGGESTIONS)|DECISION:|$)",
            stdout,
            re.IGNORECASE | re.DOTALL,
        )
        if summary_match:
            result["summary"] = summary_match.group(1).strip()

        # Pattern for ## BLOCKERS section
        blockers_match = re.search(
            r"##\s*BLOCKERS\s*\n(.*?)(?=##\s*(?:SUMMARY|SUGGESTIONS)|DECISION:|$)",
            stdout,
            re.IGNORECASE | re.DOTALL,
        )
        if blockers_match:
            result["blockers"] = blockers_match.group(1).strip()

        # Pattern for ## SUGGESTIONS section
        suggestions_match = re.search(
            r"##\s*SUGGESTIONS\s*\n(.*?)(?=##\s*(?:SUMMARY|BLOCKERS)|DECISION:|$)",
            stdout,
            re.IGNORECASE | re.DOTALL,
        )
        if suggestions_match:
            result["suggestions"] = suggestions_match.group(1).strip()

        return result

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
        """Generate human_review_report.md from template at 5th rejection.

        Before: Requires ticket_id, list of review attempt payloads, and last decision.
        During: Reads template from .agent/templates/human_review_report.md,
                fills placeholders with consolidated review data,
                writes to .agent/runtime/reviews/<TICKET_ID>/human_review_report.md.
        After: Returns Path to generated report file.
        """
        template_path = (
            self.project_root / ".agent" / "templates" / "human_review_report.md"
        )

        # Load template
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            # Fallback inline template
            template = """# Human Review Report

## Ticket
- **Ticket ID:** {{ticket_id}}
- **Generated at:** {{generated_at}}
- **Review attempts:** {{review_attempt_count}}

## Summary
{{summary}}

## Decision Context
- **Last decision:** {{last_decision}}
- **Escalation reason:** {{escalation_reason}}

## Consolidated Blockers
{{blockers}}

## Notes
{{notes}}
"""

        # Consolidate blockers from all attempts
        all_blockers = []
        for attempt in review_attempts:
            payload = attempt.get("payload", {})
            blockers = payload.get("blockers", "")
            if blockers:
                all_blockers.append(
                    f"### Attempt {attempt.get('attempt', '?')}\n{blockers}"
                )

        # Build summary
        summary_lines = [
            f"Ticket {ticket_id} reached HUMAN_GATE after {len(review_attempts)} consecutive CHANGES decisions.",
            "",
            "## Review History",
            "",
        ]
        for attempt in review_attempts:
            payload = attempt.get("payload", {})
            summary_lines.append(
                f"- Attempt {attempt.get('attempt', '?')}: "
                f"exit_code={payload.get('exit_code', 'N/A')}, "
                f"duration={payload.get('duration_seconds', 'N/A')}s"
            )

        # Fill template
        report_content = (
            template.replace("{{ticket_id}}", ticket_id)
            .replace("{{generated_at}}", datetime.now(timezone.utc).isoformat())
            .replace("{{review_attempt_count}}", str(len(review_attempts)))
            .replace("{{summary}}", "\n".join(summary_lines))
            .replace("{{last_decision}}", last_decision.value.upper())
            .replace(
                "{{escalation_reason}}",
                f"Reached {len(review_attempts)} consecutive CHANGES decisions (threshold: 5)",
            )
            .replace(
                "{{blockers}}",
                "\n\n".join(all_blockers)
                if all_blockers
                else "[No structured blockers found]",
            )
            .replace(
                "{{notes}}",
                "This report was auto-generated when the review budget was exhausted. Human review required.",
            )
        )

        # Write report
        ticket_dir = self._get_review_log_path(ticket_id)
        report_path = ticket_dir / "human_review_report.md"
        report_path.write_text(report_content, encoding="utf-8")

        return report_path

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
        """Parse OpenCode NDJSON output for DECISION: APPROVE|CHANGES|INSPECT pattern.

        Returns (decision, parse_method) where parse_method is:
          - "json_final_answer" if decision extracted from phase:final_answer
          - "json_last_text" if decision extracted from last text event
          - "json_no_decision" if no decision found in any JSON event

        Schema real de OpenCode:
        - Eventos type:"text" con part.text contienen el texto del modelo.
        - Eventos con phase:"final_answer" tienen autoridad superior.
        - Se prioriza el texto de final_answer sobre otros fragmentos.
        """
        # First pass: look for final_answer phase (highest authority)
        final_answer_decision = self._extract_decision_from_text_events(
            stdout, require_final_answer=True
        )
        if final_answer_decision is not None:
            return final_answer_decision, "json_final_answer"

        # Second pass: use last text event decision (no phase filter)
        last_text_decision = self._extract_decision_from_text_events(
            stdout, require_final_answer=False
        )
        if last_text_decision is not None:
            return last_text_decision, "json_last_text"

        return ReviewDecision.INSPECT, "json_no_decision"

    def _extract_decision_from_text_events(
        self, stdout: str, require_final_answer: bool
    ) -> ReviewDecision | None:
        """Extract DECISION from text events, optionally filtering by phase.

        Args:
            stdout: NDJSON output from OpenCode.
            require_final_answer: If True, only consider events with phase:"final_answer".

        Returns:
            ReviewDecision if found, None otherwise.
        """
        last_decision = None
        for line in stdout.splitlines():
            decision = self._extract_decision_from_single_line(
                line, require_final_answer
            )
            if decision is not None:
                if require_final_answer:
                    return decision
                if last_decision is None:
                    last_decision = decision
        return last_decision

    def _extract_decision_from_single_line(
        self, line: str, require_final_answer: bool
    ) -> ReviewDecision | None:
        """Extract decision from a single NDJSON line.

        Args:
            line: Single line of NDJSON output.
            require_final_answer: If True, only consider events with phase:"final_answer".

        Returns:
            ReviewDecision if found, None otherwise.
        """
        line = line.strip()
        if not line or not line.startswith("{"):
            return None

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None

        if event.get("type") != "text":
            return None

        # Phase filter
        phase = event.get("phase", "")
        if require_final_answer and phase != "final_answer":
            return None

        # Extract text from part.text
        part = event.get("part", {})
        if not isinstance(part, dict):
            return None
        text = part.get("text", "")
        if not text:
            return None

        text_upper = text.upper()
        if "DECISION: CHANGES" in text_upper:
            return ReviewDecision.CHANGES
        if "DECISION: APPROVE" in text_upper:
            return ReviewDecision.APPROVE
        if "DECISION: INSPECT" in text_upper:
            return ReviewDecision.INSPECT

        return None

    def _parse_opencode_decision_with_retry(
        self, stdout: str, stderr: str, max_retries: int = 2
    ) -> tuple[ReviewDecision, int, str]:
        """Parse OpenCode output with controlled retry for transient parse failures.

        Returns (decision, parse_attempts, parse_method).

        Before: A parse failure could immediately lead to INSPECT and potential
                HUMAN_GATE escalation.
        During: When parser returns INSPECT with fallback_inspect but output
                appears valid (non-empty stdout, no technical errors), retry
                parsing up to max_retries times.
        After: Returns (decision, parse_attempts, parse_method) for audit trail.
        """
        # First attempt
        decision, parse_method = self._parse_opencode_decision(stdout)
        parse_attempts = 1

        # If fallback INSPECT and output looks valid (not a technical failure), retry
        if decision == ReviewDecision.INSPECT and parse_method == "fallback_inspect":
            is_technical_failure = (
                "TimeoutExpired" in stderr
                or "FileNotFoundError" in stderr
                or "OSError" in stderr
                or not stdout.strip()
            )
            if not is_technical_failure and stdout.strip():
                for retry in range(max_retries):
                    time.sleep(0.1 * (2**retry))
                    decision, parse_method = self._parse_opencode_decision(stdout)
                    parse_attempts += 1
                    if parse_method != "fallback_inspect":
                        break

        return decision, parse_attempts, parse_method

    def _parse_opencode_decision(self, stdout: str) -> tuple[ReviewDecision, str]:
        """Parse OpenCode output for DECISION: APPROVE|CHANGES|INSPECT pattern.

        Returns (decision, parse_method):
          parse_method is one of:
            - "json_final_answer"  — NDJSON final_answer phase
            - "json_last_text"     — NDJSON last text event
            - "text_regex"         — DECISION: pattern via regex
            - "explicit_inspect"   — DECISION: INSPECT explicitly found
            - "fallback_inspect"   — parser default, no pattern recognized

        Prioridad de parseo:
        1. Si hay formato JSON (NDJSON), usar el parser estructurado.
        2. Buscar patron estructurado DECISION:\\s*(APPROVE|CHANGES|INSPECT).
        3. NO hay fallback a palabra desnuda — si no hay patron estructurado,
           retorna INSPECT + "fallback_inspect" para evitar falsos positivos.
        """
        if self._supports_json_format:
            json_decision, json_method = self._parse_opencode_json_decision(stdout)
            if json_decision != ReviewDecision.INSPECT:
                return json_decision, json_method

        # Look for explicit DECISION: pattern only (no bare word fallback)
        stdout_upper = stdout.upper()

        if re.search(r"DECISION:\s*CHANGES", stdout_upper):
            return ReviewDecision.CHANGES, "text_regex"
        if re.search(r"DECISION:\s*APPROVE", stdout_upper):
            return ReviewDecision.APPROVE, "text_regex"
        if re.search(r"DECISION:\s*INSPECT", stdout_upper):
            return ReviewDecision.INSPECT, "explicit_inspect"

        return ReviewDecision.INSPECT, "fallback_inspect"

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
        prompt = self._build_review_prompt(ticket_id, dtype)

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
                    # WP-2026-120: Use parser with controlled retry for transient failures
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

            # WP-2026-106: Enforce CHANGES structure. Validate BEFORE emitting
            # so the result is auditable on the bus and in attempt-N.md, not a
            # stderr print that gets lost.
            structure_valid = True
            missing_sections: list[str] = []
            if decision == ReviewDecision.CHANGES:
                structure_valid, missing_sections = self._validate_changes_structure(
                    stdout
                )
                if not structure_valid:
                    print(
                        "[manager-review-bridge] ERROR: CHANGES response missing "
                        f"required sections {missing_sections} -- recorded as "
                        "structure_invalid (see attempt-N.md).",
                        file=sys.stderr,
                    )

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
                    feedback=final_stdout.strip() or final_stderr.strip(),
                    transport_ok=False,
                    transport_error=transport_error or str(exc),
                    parse_method=parse_method,
                )
            return ReviewResult(
                decision=decision,
                stdout=final_stdout,
                stderr=final_stderr,
                exit_code=final_exit,
                feedback=final_stdout.strip() or final_stderr.strip(),
                transport_ok=False,
                transport_error=transport_error,
                parse_method=parse_method,
            )

        try:
            self.event_bus.emit(
                "REVIEW_DECISION",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload={
                    "decision": decision.value,
                    "stdout_tail": (final_stdout or "")[-500:],
                },
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
                feedback=final_stdout.strip() or final_stderr.strip(),
                parse_method=parse_method,
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
            controller = self.project_root / ".agent" / "agent_controller.py"
            rc_result = subprocess.run(
                [sys.executable, str(controller), "--request-changes", ticket_id],
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
            controller = self.project_root / ".agent" / "agent_controller.py"
            subprocess.run(
                [
                    sys.executable,
                    str(controller),
                    "--escalate-human-gate",
                    "--ticket",
                    ticket_id,
                ],
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

        return ReviewResult(
            decision=decision,
            stdout=final_stdout,
            stderr=final_stderr,
            exit_code=final_exit,
            feedback=final_stdout.strip() or final_stderr.strip(),
            transport_ok=transport_ok,
            transport_error=transport_error,
            parse_method=parse_method,
        )
