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
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .event_bus import EventBus
from .utils import count_trailing_changes


# Windows CreateProcess argv limit ~8191 chars; leave margin for other args
ARGV_PROMPT_THRESHOLD = 8000


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    CHANGES = "changes"
    INSPECT = "inspect"


@dataclass(slots=True)
class ReviewResult:
    decision: ReviewDecision
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    feedback: str = ""


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

    def __init__(self, event_bus: EventBus, project_root: Path):
        self.event_bus = event_bus
        self.project_root = Path(project_root)
        self.state_ingest = TicketStateIngest(event_bus, project_root)
        self._supports_json_format = self._detect_json_format_support()

    def _detect_json_format_support(self) -> bool:
        try:
            executable = "opencode"
            if os.name == "nt":
                executable = "opencode.cmd"
            exe_full = shutil.which(executable) or executable
            result = subprocess.run(
                [exe_full, "run", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                shell=(os.name == "nt"),
            )
            return "--format" in (result.stdout + result.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _review_env(self) -> dict[str, str]:
        env = os.environ.copy()
        codex_home = self.project_root / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(codex_home)
        env["USERPROFILE"] = str(codex_home)
        env["CODEX_HOME"] = str(codex_home)
        return env

    def _get_manager_backend(self) -> str:
        """Get the backend assigned to MANAGER role from agents.json."""
        try:
            from agents_config import get_backend_for_role, load_agents_config

            config = load_agents_config(self.project_root)
            return get_backend_for_role("MANAGER", config)
        except Exception:
            # Fallback to codex for backward compatibility
            return "codex"

    def _get_manager_model(self) -> str | None:
        """Get the model override for MANAGER from role_models."""
        try:
            from agents_config import get_model_for_role, load_agents_config

            config = load_agents_config(self.project_root)
            return get_model_for_role("MANAGER", config)
        except Exception:
            return None

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
                [git_bin, "diff", "--stat", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=10,
            )
            return result.stdout or "[git diff --stat empty]"
        except Exception as e:
            return f"[Error fetching git diff --stat: {e}]"

    def _build_diff_for_files_likely_touched(
        self, ticket_id: str, budget_bytes: int
    ) -> str:
        try:
            git_bin = shutil.which("git") or "git"
            result = subprocess.run(
                [git_bin, "diff", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                timeout=15,
            )
            diff = result.stdout or ""
            diff_bytes = diff.encode("utf-8")
            if len(diff_bytes) <= budget_bytes:
                return diff
            truncated = diff_bytes[:budget_bytes].decode("utf-8", errors="ignore")
            return truncated + "\n\n[diff truncado por budget]"
        except Exception as e:
            return f"[Error fetching git diff: {e}]"

    def _rubric_for_type(self, dtype: str, ticket_id: str) -> str:
        if dtype == "code":
            return (
                f"Review code ticket {ticket_id}. "
                f"Verify the implementation correctness, testing coverage, and style guides. "
                f"Check acceptance criteria and Files Likely Touched."
            )
        elif dtype == "mixed":
            return (
                f"Review mixed ticket {ticket_id}. "
                f"Verify code correctness, tests, and style guides, and additionally verify "
                f"that all declared non-code deliverables exist, are well-structured, and are fully complete. "
                f"Check acceptance criteria and Files Likely Touched."
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
        for name, content in sections:
            parts.append(f"\n--- {name} ---\n{content}")
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
            "DECISION: CHANGES\n"
        )
        return "\n".join(parts)

    def _run_codex_review(
        self,
        *,
        ticket_id: str,
        manager_executable: Path,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        """Legacy Codex review route. Preserved for backward compatibility."""
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
        manager_executable: Path | None = None,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        """OpenCode review route using manager agent spec with context prompt.

        Uses dual transport: short prompts go via argv, long prompts via tempfile + --file.
        """
        model = self._get_manager_model()

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

        tmp_path = None
        try:
            # Dispatch: short prompt -> argv, long prompt -> tempfile + --file
            if len(prompt) < ARGV_PROMPT_THRESHOLD:
                cmd_args = [
                    exe_full,
                    "run",
                    prompt,
                    "--agent",
                    "manager",
                    "--dir",
                    str(self.project_root),
                    "--port",
                    "0",
                    "--dangerously-skip-permissions",
                ]
            else:
                # Write prompt to tempfile and use --file flag
                # ruff: noqa: SIM115 (delete=False required for Windows subprocess handoff)
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                )
                tmp.write(
                    "Read the attached file and provide your review. "
                    "End with exactly DECISION: APPROVE or DECISION: CHANGES.\n\n"
                )
                tmp.write(prompt)
                tmp.close()
                tmp_path = tmp.name
                cmd_args = [
                    exe_full,
                    "run",
                    "Review.",  # minimal positional required by OpenCode CLI
                    "--file",
                    tmp_path,
                    "--agent",
                    "manager",
                    "--dir",
                    str(self.project_root),
                    "--port",
                    "0",
                    "--dangerously-skip-permissions",
                ]

            if model:
                cmd_args.extend(["--model", model])

            if self._supports_json_format:
                cmd_args.extend(["--format", "json"])

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
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=self.project_root,
                    timeout=timeout_seconds,
                    shell=use_shell,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, subprocess.TimeoutExpired):
                    err_msg = f"TimeoutExpired: {exc}"
                return "", err_msg, 1

            return result.stdout or "", result.stderr or "", result.returncode
        finally:
            # Cleanup tempfile if created (best-effort, may fail on Windows file-lock)
            if tmp_path:
                # ruff: noqa: SIM105 (clearer than contextlib.suppress for this case)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

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

    def _persist_review_attempt(
        self,
        ticket_id: str,
        attempt: int,
        stdout: str,
        stderr: str,
        decision: ReviewDecision,
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
            }
            if decision:
                payload["decision"] = decision.value
            if review_log_path:
                payload["review_log_path"] = str(review_log_path)

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

    def _parse_opencode_json_decision(self, stdout: str) -> ReviewDecision:
        """Parse OpenCode NDJSON output for DECISION: APPROVE|CHANGES pattern.

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
            return final_answer_decision

        # Second pass: use last text event decision (no phase filter)
        last_text_decision = self._extract_decision_from_text_events(
            stdout, require_final_answer=False
        )
        if last_text_decision is not None:
            return last_text_decision

        return ReviewDecision.INSPECT

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

        return None

    def _parse_opencode_decision_with_retry(
        self, stdout: str, stderr: str, max_retries: int = 2
    ) -> tuple[ReviewDecision, int]:
        """Parse OpenCode output with controlled retry for transient parse failures.

        Before: A parse failure could immediately lead to INSPECT and potential
                HUMAN_GATE escalation.
        During: When parser returns INSPECT but output appears valid (non-empty stdout,
                no technical errors), retry parsing up to max_retries times.
        After: Returns (decision, parse_attempts) tuple for audit trail.

        Args:
            stdout: Output from OpenCode review execution.
            stderr: Error output from OpenCode review execution.
            max_retries: Maximum number of parse retry attempts (default: 2).

        Returns:
            Tuple of (ReviewDecision, number_of_parse_attempts).
        """
        # First attempt
        decision = self._parse_opencode_decision(stdout)
        parse_attempts = 1

        # If INSPECT and output looks valid (not a technical failure), retry
        if decision == ReviewDecision.INSPECT:
            # Check if this is a technical failure (timeout, execution error)
            is_technical_failure = (
                "TimeoutExpired" in stderr
                or "FileNotFoundError" in stderr
                or "OSError" in stderr
                or not stdout.strip()
            )

            # Only retry for non-technical failures with substantial output
            if not is_technical_failure and stdout.strip():
                # Output exists but parser couldn't extract decision - retry
                for retry in range(max_retries):
                    # Small delay between retries (exponential backoff)
                    time.sleep(0.1 * (2**retry))
                    # Re-parse the same output (parser is deterministic,
                    # but this provides an audit trail and allows future
                    # enhancements like parser warmup)
                    decision = self._parse_opencode_decision(stdout)
                    parse_attempts += 1
                    if decision != ReviewDecision.INSPECT:
                        break

        return decision, parse_attempts

    def _parse_opencode_decision(self, stdout: str) -> ReviewDecision:
        """Parse OpenCode output for DECISION: APPROVE|CHANGES pattern.

        Prioridad de parseo:
        1. Si hay formato JSON (NDJSON), usar el parser estructurado.
        2. Buscar patron estructurado DECISION:\\s*(APPROVE|CHANGES).
        3. NO hay fallback a palabra desnuda - si no hay patron estructurado,
           retorna INSPECT para evitar falsos positivos.
        """
        if self._supports_json_format:
            json_decision = self._parse_opencode_json_decision(stdout)
            if json_decision != ReviewDecision.INSPECT:
                return json_decision

        # Look for explicit DECISION: pattern only (no bare word fallback)
        stdout_upper = stdout.upper()

        # Require structured DECISION: pattern - no bare word fallback
        if re.search(r"DECISION:\s*CHANGES", stdout_upper):
            return ReviewDecision.CHANGES
        if re.search(r"DECISION:\s*APPROVE", stdout_upper):
            return ReviewDecision.APPROVE

        # No fallback to bare words - prevents false positives like
        # "no changes needed" being interpreted as CHANGES decision
        return ReviewDecision.INSPECT

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
            self.event_bus.emit(
                "MANAGER_REVIEWING",
                ticket_id=ticket_id,
                actor="MANAGER",
                payload={"state": latest_state},
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
                    manager_executable=manager_executable,
                    timeout_seconds=current_timeout,
                )
                # WP-2026-120: Use parser with controlled retry for transient failures
                decision, _ = self._parse_opencode_decision_with_retry(stdout, stderr)
            else:
                # Codex legacy route (or any other backend)
                if manager_executable is None:
                    raise ValueError(
                        f"manager_executable required for backend '{backend}'"
                    )
                stdout, stderr, exit_code = self._run_codex_review(
                    ticket_id=ticket_id,
                    manager_executable=manager_executable,
                    timeout_seconds=current_timeout,
                )
                # Legacy Codex parser
                if "CHANGES" in stdout.upper():
                    decision = ReviewDecision.CHANGES
                elif "APPROVE" in stdout.upper() and exit_code == 0:
                    decision = ReviewDecision.APPROVE
                elif "--uncommitted" in stderr:
                    decision = ReviewDecision.INSPECT
                else:
                    decision = ReviewDecision.INSPECT

            elapsed = time.time() - start_time

            # WP-2026-106: Persist review attempt idempotently
            if decision in (ReviewDecision.CHANGES, ReviewDecision.APPROVE):
                review_log_path = self._persist_review_attempt(
                    ticket_id, attempt, stdout, stderr, decision
                )
            else:
                review_log_path = None

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

            if decision == ReviewDecision.INSPECT:
                # Retry only if the failure was technical (TimeoutExpired in stderr).
                if "TimeoutExpired" in stderr and attempt < max_attempts:
                    continue
                # Semantic issues or non-timeout errors do not trigger retry.
                break

            # WP-2026-106 B3: CHANGES ends the cycle. Re-reviewing the same
            # unchanged code in an inner loop is wasted work; the "5 attempts"
            # threshold means 5 Builder<->Manager cycles, counted from the bus.
            if decision == ReviewDecision.CHANGES:
                break

        # WP-2026-106 B1: keep the bus lightweight. Full review text lives in
        # attempt-N.md on disk; the event only carries a short forensic tail.
        # Emit REVIEW_DECISION FIRST so the bus-derived counter below sees it.
        # WP-2026-118: Wrap in fail-safe
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
            subprocess.run(
                [sys.executable, str(controller), "--request-changes", ticket_id],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.project_root,
                env=self._review_env(),
                timeout=base_timeout,
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
        )
